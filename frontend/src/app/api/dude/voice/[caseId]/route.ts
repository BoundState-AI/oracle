/**
 * DUDE Voice Bridge — one utterance per request.
 *
 * WHY this exists: the backend voice endpoint is a WebSocket authenticated
 * by an X-API-Key HANDSHAKE HEADER (dude/api/app.py checks it before
 * accept). Browsers cannot set headers on a WebSocket handshake, and
 * exposing ORACLE_API_KEY to the browser would break the repo-wide trust
 * boundary (browser never sees credentials). Next.js route handlers cannot
 * hold a browser-facing WebSocket open either (see the bundled
 * backend-for-frontend guide: "WebSockets won't work"). The voice protocol,
 * however, is strictly per-utterance — client sends audio + {"type":"end"},
 * server answers with an ordered frame sequence — so a single POST can
 * relay one full utterance:
 *
 *   Browser --POST audio--> this route --WS (X-API-Key)--> backend /dude
 *   Browser <-- NDJSON stream of frames as they arrive --  this route
 *
 * Binary WAV replies are forwarded as {"type":"audio","wav_base64":...}
 * lines. Frames are streamed the moment the backend sends them, so the
 * transcript renders without waiting for TTS.
 *
 * FAIL CLOSED, VISIBLY (spec v0.2 I12): every transport failure surfaces
 * as a {"type":"refusal"} frame — the UI must never pretend voice worked.
 * Transport copy here is infrastructure chrome, never a description of the
 * user (spec I2).
 */

import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.ORACLE_API_KEY ?? "";

if (!API_KEY && process.env.NODE_ENV === "production") {
  throw new Error(
    "ORACLE_API_KEY is not set.  The voice bridge cannot function without it."
  );
}

// Hold-to-talk utterances are short; webm/opus at ~32 kbps makes 12 MiB
// several minutes of audio. The backend remains the authority on limits.
const MAX_AUDIO_BYTES = 12 * 1024 * 1024;

// STT + capture + TTS can be slow on local backends; a hung socket must
// still terminate the response rather than hold the function open forever.
const TOTAL_TIMEOUT_MS = 180_000;

// After the "reply" frame the only possible follow-ups are a binary WAV or
// a TTS refusal. When TTS is not configured the backend sends neither, so
// a grace window closes the exchange. Text frames were already streamed —
// waiting here never delays rendering.
const POST_REPLY_GRACE_MS = 20_000;

// The DOM lib types WebSocket's second argument as protocols only, but
// Node's built-in (undici) WebSocket accepts an options bag with handshake
// headers — exactly what the backend's pre-accept X-API-Key check needs.
type NodeWebSocketCtor = new (
  url: string,
  options: { headers: Record<string, string> }
) => WebSocket;

export async function POST(
  req: NextRequest,
  ctx: { params: Promise<{ caseId: string }> }
) {
  const { caseId } = await ctx.params;
  const audio = await req.arrayBuffer();

  if (audio.byteLength === 0) {
    return NextResponse.json({ error: "Empty audio body" }, { status: 400 });
  }
  if (audio.byteLength > MAX_AUDIO_BYTES) {
    return NextResponse.json(
      { error: "Audio exceeds the 12 MB voice limit" },
      { status: 413 }
    );
  }

  const wsUrl = `${API_BASE.replace(/^http/, "ws")}/dude/cases/${encodeURIComponent(caseId)}/voice`;
  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let socket: WebSocket;
      try {
        socket = new (WebSocket as unknown as NodeWebSocketCtor)(wsUrl, {
          headers: { "X-API-Key": API_KEY },
        });
      } catch {
        controller.enqueue(
          encoder.encode(
            JSON.stringify({
              type: "refusal",
              reason: "Voice connection to the backend could not be opened.",
            }) + "\n"
          )
        );
        controller.close();
        return;
      }
      socket.binaryType = "arraybuffer";

      let finished = false;
      let sawReply = false;
      let graceTimer: ReturnType<typeof setTimeout> | undefined;

      const emit = (frame: Record<string, unknown>) => {
        if (finished) return;
        controller.enqueue(encoder.encode(JSON.stringify(frame) + "\n"));
      };

      const finish = () => {
        if (finished) return;
        finished = true;
        clearTimeout(totalTimer);
        clearTimeout(graceTimer);
        try {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "bye" }));
          }
          socket.close();
        } catch {
          // Closing a dying socket must never mask frames already streamed.
        }
        controller.close();
      };

      const totalTimer = setTimeout(() => {
        emit({
          type: "refusal",
          reason: "Voice exchange timed out before the backend finished.",
        });
        finish();
      }, TOTAL_TIMEOUT_MS);

      socket.addEventListener("open", () => {
        // The backend buffers binary frames until {"type":"end"} — one send
        // of the accumulated utterance is protocol-equivalent to chunks.
        socket.send(audio);
        socket.send(JSON.stringify({ type: "end" }));
      });

      socket.addEventListener("message", (event: MessageEvent) => {
        if (finished) return;
        if (typeof event.data === "string") {
          let frame: Record<string, unknown>;
          try {
            frame = JSON.parse(event.data);
          } catch {
            return; // Unparseable frame: ignore rather than invent content.
          }
          emit(frame);
          // Terminal frames per dude/api/app.py: every refusal ends the
          // utterance, and nothing follows the post-reply audio/refusal.
          if (frame.type === "refusal") {
            finish();
            return;
          }
          if (frame.type === "reply") {
            sawReply = true;
            graceTimer = setTimeout(finish, POST_REPLY_GRACE_MS);
          }
          return;
        }
        // Binary frame: the spoken WAV reply — always the final frame.
        const bytes =
          event.data instanceof ArrayBuffer
            ? Buffer.from(event.data)
            : Buffer.from(event.data as Uint8Array);
        emit({ type: "audio", wav_base64: bytes.toString("base64") });
        finish();
      });

      socket.addEventListener("close", (event: CloseEvent) => {
        if (finished) return;
        if (!sawReply) {
          // 4401 is the backend's pre-accept auth rejection code.
          emit({
            type: "refusal",
            reason:
              event.code === 4401
                ? "Voice connection was rejected by the backend (unauthorized)."
                : "Voice connection closed before the backend replied.",
          });
        }
        finish();
      });

      socket.addEventListener("error", () => {
        if (finished) return;
        if (!sawReply) {
          emit({
            type: "refusal",
            reason: "Voice connection to the backend failed.",
          });
        }
        finish();
      });
    },
  });

  return new NextResponse(stream, {
    status: 200,
    headers: {
      "content-type": "application/x-ndjson; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
