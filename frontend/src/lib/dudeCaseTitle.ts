/**
 * Case-title derivation for capture-first entry (DUDE mobile vision v0.1).
 *
 * The home screen centers on "something happened", not on case
 * management: an utterance or typed note that arrives with no case
 * selected files itself into a new case titled from the first few words
 * of what was said. Shared by the no-case voice bridge (server) and the
 * home screen's text path (client) so both entrances name cases the same
 * way.
 */

/** Word budget for a derived title — roughly one spoken breath. */
const TITLE_WORD_LIMIT = 6;

/**
 * Reserved title of the hidden transcription-intake case used by the
 * no-case voice bridge (`/api/dude/voice/new`). WHY it exists: the
 * backend voice endpoint transcribes and captures atomically into an
 * EXISTING case (dude/api/app.py) and cases cannot be renamed, so
 * titling a case from its own transcript requires transcribing first.
 * Home-screen utterances are transcribed via this sentinel case; the
 * transcript is then attached to a properly titled new case. Every
 * user-facing case list filters this title out.
 */
export const VOICE_INTAKE_TITLE = "DUDE voice intake";

/** First ~6 words of an utterance, with an ellipsis when truncated. */
export function titleFromUtterance(text: string): string {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const head = words.slice(0, TITLE_WORD_LIMIT).join(" ");
  return words.length > TITLE_WORD_LIMIT ? `${head}…` : head;
}
