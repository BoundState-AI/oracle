/**
 * Server-Sent Events (SSE) connection and status-polling fallback
 * for long-running Oracle sessions (reviews and pack generation).
 *
 * `connectSSE` opens an EventSource for real-time log streaming.
 * If the live connection drops (e.g. Vercel 25 s timeout, deploy),
 * the caller should fall back to `startStatusPolling` which hits
 * the session endpoint on a 5-second interval until the job resolves.
 */

import { apiGet } from "./oracleApi";

/* ------------------------------------------------------------------ */
/*  SSE live connection                                                */
/* ------------------------------------------------------------------ */

/**
 * Open an SSE stream for the given session.
 *
 * @returns A cleanup function that closes the EventSource.
 */
export function connectSSE(
  sessionId: string,
  onLog: (msg: string) => void,
  onDone: (data: Record<string, unknown>) => void,
  onError: (err: string, recoverable: boolean) => void,
): () => void {
  const url = `/api/oracle/stream/${sessionId}`;
  const eventSource = new EventSource(url);

  eventSource.addEventListener("log", (e) => {
    onLog(e.data);
  });

  eventSource.addEventListener("done", (e) => {
    try {
      const data = JSON.parse(e.data);
      onDone(data);
    } catch {
      onError("Failed to parse result", false);
    }
    eventSource.close();
  });

  eventSource.addEventListener("error", (e) => {
    if (e instanceof MessageEvent) {
      onError(e.data, false);
    } else {
      onError("Live connection dropped — checking Oracle status...", true);
    }
    eventSource.close();
  });

  return () => eventSource.close();
}

/* ------------------------------------------------------------------ */
/*  Polling fallback                                                   */
/* ------------------------------------------------------------------ */

/**
 * Poll the session endpoint every 5 s until it completes or errors.
 *
 * @returns A cleanup function that stops the polling loop.
 */
export function startStatusPolling(
  sessionId: string,
  onDone: (data: Record<string, unknown>) => void,
  onError: (err: string) => void,
  onProgress?: (data: Record<string, unknown>) => void,
): () => void {
  let active = true;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const tick = async () => {
    if (!active) return;
    try {
      const res = await apiGet(`/session/${sessionId}`);
      if (res.status === 404) {
        onDone({
          status: "error",
          error:
            "Oracle session was interrupted by a server restart or redeploy. Please start the review again.",
        });
        return;
      }
      if (!res.ok) {
        throw new Error(`Polling failed (${res.status})`);
      }
      const data = (await res.json()) as Record<string, unknown>;
      const status = data.status as string | undefined;
      if (status === "processing") {
        onProgress?.(data);
        timer = setTimeout(tick, 5000);
        return;
      }
      onDone(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Polling failed";
      if (!active) return;
      onError(message);
      timer = setTimeout(tick, 5000);
    }
  };

  void tick();

  return () => {
    active = false;
    if (timer) clearTimeout(timer);
  };
}

/* ------------------------------------------------------------------ */
/*  Shared helpers                                                     */
/* ------------------------------------------------------------------ */

/** Extract up to the last 20 log messages from a session status payload. */
export function readLogMessages(data: Record<string, unknown>): string[] {
  const value = data.log_messages;
  if (!Array.isArray(value)) return [];
  return value
    .filter((entry): entry is string => typeof entry === "string")
    .slice(-20);
}
