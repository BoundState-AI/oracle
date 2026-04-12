/**
 * OracleChatPanel — real-time chat interface over authority packs.
 * Two modes: authority-grounded (cites governing clauses from selected packs)
 * and review-only (critiques draft requirements without external authority).
 * Streams responses via SSE with meta/text/done/error event dispatch.
 */

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRightLeft,
  Library,
  Quote,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { PackSummary } from "@/components/ReviewTab";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: string | null;
  citations?: string[];
  followUps?: string[];
  advisoryOnly?: boolean;
  selectedPacks?: string[];
  reviewOnly?: boolean;
  isStreaming?: boolean;
};

type OracleChatPanelProps = {
  availablePacks: PackSummary[];
  selectedPacks: string[];
  onSelectPacks: (packs: string[]) => void;
  onRefreshPacks: () => Promise<void> | void;
  packsLoading: boolean;
};

type StreamOptions = {
  message: string;
  sessionId: string | null;
  history: Array<{ role: "user" | "assistant"; content: string }>;
  selectedPacks: string[];
  compareOnly: boolean;
  reviewOnly: boolean;
  onMeta: (meta: {
    status?: string;
    selectedPacks?: string[];
    compareOnly?: boolean;
    reviewOnly?: boolean;
  }) => void;
  onText: (chunk: string) => void;
  onDone: (payload: {
    sessionId?: string;
    status?: string;
    citations?: string[];
    followUps?: string[];
    selectedPacks?: string[];
    compareOnly?: boolean;
    reviewOnly?: boolean;
    advisoryOnly?: boolean;
  }) => void;
};

const AUTHORITY_STARTER_PROMPTS = [
  "What does the selected standard say about pure tin finishes?",
  "Show the governing clause for connector plating limits.",
  "Compare the selected packs on PEM usage restrictions.",
  "What evidence would I need to close a capacitor derating question?",
];

const REVIEW_ONLY_STARTER_PROMPTS = [
  "Review this requirement for ambiguity: The contractor shall provide appropriate support as needed.",
  "What is missing from this approval clause: The team will obtain approval before release.",
  "Rewrite this into a testable requirement: Update the interface documentation in a timely manner.",
  "Tear apart this scope sentence: Add the new work and update the baseline.",
];

function parseSsePayload(raw: string): Record<string, unknown> {
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return {};
  }
}

async function streamOracleChat({
  message,
  sessionId,
  history,
  selectedPacks,
  compareOnly,
  reviewOnly,
  onMeta,
  onText,
  onDone,
}: StreamOptions): Promise<void> {
  const response = await fetch("/api/oracle/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      history,
      selected_packs: selectedPacks,
      compare_only: compareOnly,
      review_only: reviewOnly,
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Oracle chat failed (${response.status})`);
  }

  if (!response.body) {
    throw new Error("Oracle chat stream was not available.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushBlock = (block: string) => {
    const lines = block.split("\n");
    let eventName = "message";
    const dataLines: string[] = [];

    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }

    const rawData = dataLines.join("\n");
    if (!rawData) return;

    if (eventName === "meta") {
      const payload = parseSsePayload(rawData);
      onMeta({
        status: typeof payload.status === "string" ? payload.status : undefined,
        selectedPacks: Array.isArray(payload.selected_packs)
          ? payload.selected_packs.filter((item): item is string => typeof item === "string")
          : undefined,
        compareOnly:
          typeof payload.compare_only === "boolean" ? payload.compare_only : undefined,
        reviewOnly:
          typeof payload.review_only === "boolean" ? payload.review_only : undefined,
      });
      return;
    }

    if (eventName === "text") {
      const payload = parseSsePayload(rawData);
      const text = typeof payload.text === "string" ? payload.text : rawData;
      if (text) onText(text);
      return;
    }

    if (eventName === "done") {
      const payload = parseSsePayload(rawData);
      onDone({
        sessionId: typeof payload.session_id === "string" ? payload.session_id : undefined,
        status: typeof payload.status === "string" ? payload.status : undefined,
        citations: Array.isArray(payload.citations)
          ? payload.citations.filter((item): item is string => typeof item === "string")
          : undefined,
        followUps: Array.isArray(payload.follow_ups)
          ? payload.follow_ups.filter((item): item is string => typeof item === "string")
          : undefined,
        selectedPacks: Array.isArray(payload.selected_packs)
          ? payload.selected_packs.filter((item): item is string => typeof item === "string")
          : undefined,
        compareOnly:
          typeof payload.compare_only === "boolean" ? payload.compare_only : undefined,
        reviewOnly:
          typeof payload.review_only === "boolean" ? payload.review_only : undefined,
        advisoryOnly:
          typeof payload.advisory_only === "boolean" ? payload.advisory_only : undefined,
      });
      return;
    }

    if (eventName === "error") {
      const payload = parseSsePayload(rawData);
      const detail = typeof payload.detail === "string" ? payload.detail : rawData;
      throw new Error(detail || "Oracle chat failed.");
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (block) flushBlock(block);
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      const remainder = buffer.trim();
      if (remainder) flushBlock(remainder);
      break;
    }
  }
}

function createId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function packLabel(pack: PackSummary): string {
  return pack.standard_id || pack.name || pack.slug;
}

export function OracleChatPanel({
  availablePacks,
  selectedPacks,
  onSelectPacks,
  onRefreshPacks,
  packsLoading,
}: OracleChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: createId("assistant"),
      role: "assistant",
      content:
        "Oracle can run in two modes: authority-grounded chat over selected packs, or review-only critique for draft requirements and specs.",
      advisoryOnly: true,
      followUps: AUTHORITY_STARTER_PROMPTS.slice(0, 3),
    },
  ]);
  const [draft, setDraft] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [compareOnly, setCompareOnly] = useState(false);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const selectedPackSet = useMemo(() => new Set(selectedPacks), [selectedPacks]);
  const selectedPackObjects = useMemo(
    () => availablePacks.filter((pack) => selectedPackSet.has(pack.slug)),
    [availablePacks, selectedPackSet],
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => {
    if (reviewOnly && compareOnly) {
      setCompareOnly(false);
    }
  }, [reviewOnly, compareOnly]);

  const starterPrompts = reviewOnly ? REVIEW_ONLY_STARTER_PROMPTS : AUTHORITY_STARTER_PROMPTS;

  const canSend =
    !streaming &&
    draft.trim().length > 0 &&
    (reviewOnly || selectedPacks.length > 0) &&
    (!compareOnly || selectedPacks.length >= 2);

  const togglePack = (slug: string) => {
    onSelectPacks(
      selectedPackSet.has(slug)
        ? selectedPacks.filter((item) => item !== slug)
        : [...selectedPacks, slug],
    );
  };

  const submitMessage = async (rawMessage: string) => {
    const message = rawMessage.trim();
    if (!message || streaming) return;
    if (!reviewOnly && selectedPacks.length === 0) {
      toast.error("Select at least one authority pack before chatting.");
      return;
    }
    if (reviewOnly && compareOnly) {
      toast.error("Review-only mode does not support pack comparison.");
      return;
    }
    if (compareOnly && selectedPacks.length < 2) {
      toast.error("Compare mode needs at least two selected packs.");
      return;
    }

    const userMessage: ChatMessage = {
      id: createId("user"),
      role: "user",
      content: message,
    };
    const assistantId = createId("assistant");

    setDraft("");
    setStreaming(true);
    setLiveStatus("RUNNING");
    setMessages((prev) => [
      ...prev,
      userMessage,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        isStreaming: true,
      },
    ]);

    const history = messages
      .filter((entry) => !entry.isStreaming)
      .map((entry) => ({
        role: entry.role,
        content: entry.content,
      }));

    try {
      await streamOracleChat({
        message,
        sessionId,
        history,
        selectedPacks,
        compareOnly,
        reviewOnly,
        onMeta: (meta) => {
          if (meta.status) setLiveStatus(meta.status);
        },
        onText: (chunk) => {
          setMessages((prev) =>
            prev.map((entry) =>
              entry.id === assistantId
                ? {
                    ...entry,
                    content: entry.content
                      ? `${entry.content}\n\n${chunk}`
                      : chunk,
                  }
                : entry,
            ),
          );
        },
        onDone: (payload) => {
          if (payload.sessionId) setSessionId(payload.sessionId);
          if (payload.status) setLiveStatus(payload.status);
          setMessages((prev) =>
            prev.map((entry) =>
              entry.id === assistantId
                ? {
                    ...entry,
                    isStreaming: false,
                    status: payload.status ?? null,
                    citations: payload.citations ?? [],
                    followUps: payload.followUps ?? [],
                    advisoryOnly: payload.advisoryOnly ?? true,
                    selectedPacks: payload.selectedPacks ?? selectedPacks,
                    reviewOnly: payload.reviewOnly ?? reviewOnly,
                  }
                : entry,
            ),
          );
        },
      });
    } catch (error) {
      const messageText =
        error instanceof Error ? error.message : "Oracle chat failed unexpectedly.";
      setMessages((prev) =>
        prev.map((entry) =>
          entry.id === assistantId
            ? {
                ...entry,
                isStreaming: false,
                status: "ERROR",
                advisoryOnly: true,
                content:
                  "Oracle could not complete that answer. Refresh the pack library or narrow the request and try again.",
              }
            : entry,
        ),
      );
      toast.error(messageText);
      setLiveStatus("ERROR");
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          Oracle Chat
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Switch between authority-grounded pack chat and review-only critique.
          Authority mode cites governing clauses from selected packs. Review-only mode
          inspects draft requirements and specs without claiming external authority.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[0.88fr_1.12fr]">
        <div className="space-y-6">
          <Card className="border-border">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-lg font-semibold tracking-tight">
                  Chat Scope
                </CardTitle>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void onRefreshPacks()}
                >
                  <RefreshCw className="h-3.5 w-3.5" data-icon="inline-start" />
                  Refresh
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-xl border border-border bg-muted/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      Source Mode
                    </div>
                    <p className="mt-1 text-sm text-foreground">
                      {reviewOnly
                        ? "Review-only critique for draft requirements, approval language, and spec wording."
                        : "Authority-grounded answers from the selected packs only."}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant={reviewOnly ? "outline" : "default"}
                      size="sm"
                      onClick={() => setReviewOnly(false)}
                    >
                      Authority
                    </Button>
                    <Button
                      type="button"
                      variant={reviewOnly ? "default" : "outline"}
                      size="sm"
                      onClick={() => setReviewOnly(true)}
                    >
                      Review Only
                    </Button>
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-border bg-muted/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      Compare Mode
                    </div>
                    <p className="mt-1 text-sm text-foreground">
                      {compareOnly
                        ? "Compare the first two selected packs side by side."
                        : reviewOnly
                          ? "Unavailable in review-only mode."
                          : "Stay anchored to one selected pack for precise clause lookup."}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant={compareOnly ? "default" : "outline"}
                    size="sm"
                    disabled={reviewOnly}
                    onClick={() => setCompareOnly((prev) => !prev)}
                  >
                    <ArrowRightLeft className="h-3.5 w-3.5" data-icon="inline-start" />
                    {compareOnly ? "Compare On" : "Compare Off"}
                  </Button>
                </div>
              </div>

              <div className="rounded-xl border border-border bg-muted/20 p-4">
                <div className="flex items-center gap-2">
                  <Library className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium text-foreground">
                    Selected Packs
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {selectedPackObjects.length > 0 ? (
                    selectedPackObjects.map((pack) => (
                      <Badge key={pack.slug} variant="secondary" className="gap-1">
                        {packLabel(pack)}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      No authority packs selected yet.
                    </span>
                  )}
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  {reviewOnly
                    ? "Review-only mode ignores pack selections. Keep packs selected here if you plan to switch back to authority mode."
                    : "Authority mode uses only the packs selected here."}
                </p>
              </div>

              <div className="space-y-3">
                {packsLoading ? (
                  <p className="text-sm text-muted-foreground">Loading pack library...</p>
                ) : availablePacks.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No packs available yet. Generate or import one from the Pack Library tab.
                  </p>
                ) : (
                  availablePacks.map((pack) => {
                    const selected = selectedPackSet.has(pack.slug);
                    return (
                      <button
                        key={pack.slug}
                        type="button"
                        onClick={() => togglePack(pack.slug)}
                        className={cn(
                          "w-full rounded-2xl border px-4 py-4 text-left transition-colors",
                          selected
                            ? "border-primary bg-primary/8"
                            : "border-border bg-card hover:bg-muted/20",
                        )}
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium text-foreground">
                                {pack.name}
                              </span>
                              <Badge variant={selected ? "default" : "outline"}>
                                {pack.status}
                              </Badge>
                              <Badge variant="outline">{pack.schema}</Badge>
                            </div>
                            <p className="mt-1 text-xs text-muted-foreground">
                              {pack.standard_id || "Custom pack"} • {pack.rule_count} rules
                            </p>
                          </div>
                          <Badge variant={selected ? "default" : "secondary"}>
                            {selected ? "Selected" : "Pick"}
                          </Badge>
                        </div>
                      </button>
                    );
                  })
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="border-border">
            <CardHeader>
              <CardTitle className="text-lg font-semibold tracking-tight">
                Starter Prompts
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {starterPrompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => void submitMessage(prompt)}
                  className="w-full rounded-xl border border-border bg-muted/20 px-4 py-3 text-left text-sm text-foreground transition-colors hover:bg-muted/35"
                >
                  <div className="flex items-start gap-3">
                    <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    <span>{prompt}</span>
                  </div>
                </button>
              ))}
            </CardContent>
          </Card>
        </div>

        <Card className="border-border">
          <CardHeader className="border-b border-border">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="text-lg font-semibold tracking-tight">
                  Oracle Chat
                </CardTitle>
                <p className="mt-1 text-sm text-muted-foreground">
                  {reviewOnly
                    ? "Review-only critique for draft requirements, scope changes, approval language, and missing acceptance criteria."
                    : "Research-only clause support with citations and follow-up prompts."}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">Status {liveStatus ?? "READY"}</Badge>
                <Badge variant="outline">{reviewOnly ? "Review Only" : "Authority"}</Badge>
                <Badge variant="outline">Advisory Only</Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent className="flex min-h-[44rem] flex-col gap-4 p-0">
            <div className="flex-1 space-y-4 overflow-y-auto px-6 py-6">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={cn(
                    "max-w-[88%] rounded-2xl border px-4 py-4",
                    message.role === "user"
                      ? "ml-auto border-primary/30 bg-primary text-primary-foreground"
                      : "border-border bg-card",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span
                      className={cn(
                        "text-[11px] font-semibold uppercase tracking-[0.2em]",
                        message.role === "user"
                          ? "text-primary-foreground/80"
                          : "text-muted-foreground",
                      )}
                    >
                      {message.role === "user" ? "Operator" : "Oracle"}
                    </span>
                    {message.advisoryOnly && message.role === "assistant" && (
                      <div className="flex items-center gap-2">
                        {message.reviewOnly && (
                          <span className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                            Review Only
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-[0.18em] text-amber-400">
                          <ShieldAlert className="h-3.5 w-3.5" />
                          Advisory
                        </span>
                      </div>
                    )}
                  </div>

                  <div
                    className={cn(
                      "mt-3 whitespace-pre-wrap text-sm leading-7",
                      message.role === "user"
                        ? "text-primary-foreground"
                        : "text-foreground",
                    )}
                  >
                    {message.content || (message.isStreaming ? "Oracle is reasoning..." : "")}
                  </div>

                  {message.citations && message.citations.length > 0 && (
                    <div className="mt-4">
                      <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        <Quote className="h-3.5 w-3.5" />
                        Citations
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {message.citations.map((citation) => (
                          <Badge key={citation} variant="outline">
                            {citation}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {message.followUps && message.followUps.length > 0 && (
                    <div className="mt-4 space-y-2">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        Next Moves
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {message.followUps.map((followUp) => (
                          <button
                            key={followUp}
                            type="button"
                            onClick={() => void submitMessage(followUp)}
                            className="rounded-full border border-border px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-muted/30"
                          >
                            {followUp}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            <div className="border-t border-border px-6 py-5">
              <form
                className="space-y-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitMessage(draft);
                }}
              >
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder={
                    reviewOnly
                      ? "Paste draft requirement text or ask Oracle to critique the wording."
                      : selectedPacks.length === 0
                      ? "Select a pack before chatting."
                      : compareOnly
                        ? "Ask Oracle to compare the selected standards on a specific topic."
                        : "Ask for a clause, table note, applicability check, or missing evidence."
                  }
                  rows={4}
                  className="w-full resize-none rounded-2xl border border-border bg-background px-4 py-3 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
                />
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-muted-foreground">
                    {reviewOnly
                      ? "Review-only mode is not authority-grounded. Paste the draft language you want critiqued."
                      : selectedPacks.length === 0
                      ? "Oracle chat is disabled until you select an authority pack."
                      : compareOnly && selectedPacks.length < 2
                        ? "Compare mode needs at least two selected packs."
                        : "Oracle responds from the selected pack scope only."}
                  </p>
                  <Button type="submit" disabled={!canSend}>
                    <Send className="h-4 w-4" data-icon="inline-start" />
                    Send
                  </Button>
                </div>
              </form>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
