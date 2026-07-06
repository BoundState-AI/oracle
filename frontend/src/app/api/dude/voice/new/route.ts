/**
 * DUDE No-Case Voice Bridge — "something happened" before any case exists.
 *
 * The home screen's hold-to-talk button has no case selected. This route
 * (the literal `new` segment wins over the `[caseId]` sibling) takes the
 * utterance, gets it transcribed with the safety floor running
 * immediately, then files it: a new case titled from the first ~6 words
 * of the transcript, with the transcript attached as its first capture.
 *
 * WHY an intake case: the backend voice endpoint (dude/api/app.py)
 * transcribes and captures atomically into an EXISTING case — there is no
 * transcribe-only endpoint and cases cannot be renamed — so titling a
 * case from its own words requires transcription first. The utterance is
 * relayed into the reserved intake case (VOICE_INTAKE_TITLE, hidden from
 * every user-facing list); the transcript frame then drives creation of
 * the real case via the REST API.
 *
 * Frames streamed to the client, in order:
 *   backend transcript / safety / reply / audio frames, verbatim, plus —
 *   right after the transcript — a safety frame from the new case's own
 *   capture scan when it flags (identical payloads collapse client-side;
 *   a crisis is never swallowed), and {"type":"case","case_id","title"}
 *   announcing where the moment was filed.
 *
 * FAIL CLOSED, VISIBLY (spec v0.2 I12): if the case cannot be created or
 * the transcript cannot be attached, a {"type":"refusal"} frame says so
 * and the home screen falls back to the text path — never pretend.
 */

import { NextRequest, NextResponse } from "next/server";

import { titleFromUtterance, VOICE_INTAKE_TITLE } from "@/lib/dudeCaseTitle";
import {
  API_BASE,
  API_KEY,
  MAX_AUDIO_BYTES,
  ndjsonResponse,
  refusalFrame,
  relayUtteranceFrames,
  type BridgeFrame,
} from "@/lib/server/dudeVoiceRelay";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface CaseListing {
  case_id: string;
  title: string;
}

interface CaptureResult {
  crisis: boolean;
  message: string;
  flags: string[];
  resources: { name: string; contact: string; note: string }[];
}

/** Authenticated JSON call to the backend REST surface. */
async function backend<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown
): Promise<T> {
  const response = await fetch(`${API_BASE}/dude${path}`, {
    method,
    headers: {
      "X-API-Key": API_KEY,
      ...(body !== undefined ? { "content-type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`${method} ${path} failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

/** Find-or-create the reserved transcription-intake case. */
async function ensureIntakeCase(): Promise<string> {
  const cases = await backend<CaseListing[]>("GET", "/cases");
  const existing = cases.find((c) => c.title === VOICE_INTAKE_TITLE);
  if (existing) return existing.case_id;
  const created = await backend<{ case_id: string }>("POST", "/cases", {
    title: VOICE_INTAKE_TITLE,
  });
  return created.case_id;
}

/** Create the titled case and attach the transcript as its first capture. */
async function* fileIntoNewCase(
  transcript: string
): AsyncGenerator<BridgeFrame> {
  const title = titleFromUtterance(transcript);
  try {
    const created = await backend<{ case_id: string }>("POST", "/cases", {
      title,
    });
    const capture = await backend<CaptureResult>(
      "POST",
      `/cases/${encodeURIComponent(created.case_id)}/capture`,
      { text: transcript }
    );
    // The attach ran its own safety scan inside the new case; surface it
    // (backend copy verbatim). Duplicates of the websocket safety frame
    // collapse client-side — never suppressed here.
    if (capture.crisis || capture.flags.length > 0) {
      yield {
        type: "safety",
        crisis: capture.crisis,
        message: capture.message,
        flags: capture.flags,
        resources: capture.resources,
      };
    }
    yield { type: "case", case_id: created.case_id, title };
  } catch {
    yield refusalFrame(
      "The words were transcribed, but a case could not be created for " +
        "them. Use the text box to file them."
    );
  }
}

async function* noCaseUtteranceFrames(
  audio: ArrayBuffer
): AsyncGenerator<BridgeFrame> {
  let intakeCaseId: string;
  try {
    intakeCaseId = await ensureIntakeCase();
  } catch {
    yield refusalFrame(
      "Voice intake is unavailable — the backend could not be reached. " +
        "Use the text box instead."
    );
    return;
  }
  for await (const frame of relayUtteranceFrames(intakeCaseId, audio)) {
    yield frame;
    if (frame.type === "transcript" && typeof frame.text === "string") {
      yield* fileIntoNewCase(frame.text);
    }
  }
}

export async function POST(req: NextRequest) {
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

  return ndjsonResponse(noCaseUtteranceFrames(audio));
}
