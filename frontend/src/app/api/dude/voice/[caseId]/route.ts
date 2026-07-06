/**
 * DUDE Voice Bridge — one utterance per request, attached to a known case.
 *
 * POSTed audio is relayed through the backend voice websocket for this
 * case and the backend's frames stream back as NDJSON, verbatim. All
 * relay mechanics (auth header handshake, timeouts, WAV forwarding,
 * fail-closed refusal frames) live in lib/server/dudeVoiceRelay.ts and
 * are shared with the no-case bridge (../new/route.ts).
 */

import { NextRequest, NextResponse } from "next/server";

import {
  MAX_AUDIO_BYTES,
  ndjsonResponse,
  relayUtteranceFrames,
} from "@/lib/server/dudeVoiceRelay";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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

  return ndjsonResponse(relayUtteranceFrames(caseId, audio));
}
