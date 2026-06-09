# ORACLE Phase 1 Audit — Consensus Integrity & Engineering

**Scope:** `oracle/` package, `server.py`, `frontend/src` (read-only audit).
**Audited against the four philosophy rules:** (1) IDK beats lying, (2) retrieved ≠ interpreted,
(3) source tiering survives transformation, (4) the system never decides.

**Method note (IDK applies to me too):** no API keys are available in this environment, so every
consensus-dynamics finding below is *structural* — proven from code and prompts, not measured from
live runs. Findings marked ⚖ are prompt-design issues whose real-world magnitude cannot be measured
without the golden harness proposed in E1.

---

## Summary table

| ID | Sev | Area | One-line |
|----|-----|------|----------|
| A1 | CRITICAL | Consensus | Beth is instructed to *decide* disagreements, not surface them |
| A2 | CRITICAL | Consensus | Repeated unresolved tradeoffs are reported as **converged** |
| F1 | CRITICAL | Integration | Adapter reads files the default workflow never writes → severities silently degraded |
| E1 | CRITICAL | Evaluation | No golden-case harness exists (automatic CRITICAL per audit charter) |
| A3 | HIGH | Consensus | A single vendor model is the sole convergence authority, prompted toward convergence |
| A4 | HIGH | Consensus | Convergence allowed with 1 unresolved HIGH finding, not prominently surfaced |
| A5 | HIGH | Consensus | Cross-round anchoring + no sycophancy/drift detection; verdict signal collected then ignored |
| A6 | HIGH | Consensus | Fran and Codex are the same model — "4 reviewers" is 3 vendors; agreement counted naively |
| A7 | HIGH | Consensus | Semantic dedup & issue-ID continuity delegated to one model, unverified, drives convergence gate |
| A8 | HIGH | Consensus | Dissent fidelity loss: conflict_flag/weak_signal/dropped findings never surfaced |
| B1 | HIGH | Rule packs | Packs are not re-validated (or hash-checked) at review load time |
| B2 | HIGH | Parsing | Truncation recovery returns partial findings as a full success — unflagged degraded consensus input |
| C1 | HIGH | Vendors | No model pinning; actual model versions never recorded anywhere |
| C2 | HIGH | Vendors | One vendor down → loop burns all remaining rounds, then emits input-identical "final_draft.md" |
| D1 | HIGH | Observability | No tokens/cost/latency persisted; SDK usage objects discarded |
| D2 | HIGH | Observability | Runs not replayable: prompts, temps, model IDs, raw responses not persisted |
| F2 | HIGH | Reporting | Non-converged runs labeled "Maximum Reasoning" in generated .docx |
| F3 | HIGH | Testing | Zero tests on `_check_convergence`, `_run_round`, JSON recovery, and all of oracle2_adapter |
| A9 | MEDIUM | Consensus | Confidence + "speculative" uncertainty signals requested, then structurally discarded |
| A10 | MEDIUM | Consensus | Open Questions report shows the *first* round's questions, not the last |
| A11 | MEDIUM | Consensus | Repeated-tradeoff detection is exact-string matching |
| B3 | MEDIUM | Rule packs | Vision repair overwrites extracted text with model interpretation, no provenance flag |
| C3 | MEDIUM | Vendors | No 429/Retry-After handling; fixed 2/4/8s backoff; Anthropic retries disabled |
| C4 | MEDIUM | Vendors | Grok call has no structured-output enforcement |
| D3 | MEDIUM | Metrics | duplicate/unsupported rates are always 0.0 in default workflow but still reported |
| F4 | MEDIUM | Code | `_run_round` / `_run_manual_round` and OpenAI/xAI adapters are near-duplicates |
| F6 | MEDIUM | Errors | `except BaseException` in server review runner; assorted broad excepts |
| B4 | LOW | Rule packs | No pack version history; only content_hash snapshot |
| B5 | LOW | Rule packs | 500-char statement truncation in rendering with bare "..." |
| C5 | LOW | Security | Raw provider error bodies persisted/logged without key-shaped redaction |
| F5 | LOW | Docs | CLAUDE.md says 5 oracles (6 exist); docstring convergence criteria ≠ implementation; stale CLI epilog; dead import |

---

## A. Consensus integrity

### A1. CRITICAL ⚖ — The coordinator is instructed to resolve disagreements, not surface them
- `oracle/oracle2.py:122` — Beth's ledger prompt: *"If two reviewers disagree, identify the
  governing tradeoff **and decide**."*
- `oracle/oracle2.py:174-176` — manual prompt: *"Reject weak, speculative, stylistic,
  preference-only, or low-risk nitpicks"* — a single model discards findings pre-report.
- What survives to the user: Beth's per-issue decision + reason (truncated to 200 chars,
  `oracle/cli.py:2162`) and aggregate counts (`cli.py:2116-2117`). The *positions in conflict*
  (which oracles, what each claimed, at what severity) do not survive: by report time they've been
  merged (ledger) or bundled (manual) into one issue with one severity.
- This is philosophy rule #4's exact failure mode: resolution presented as review output, with
  dissent reduced to a rejection count. It is prompt-and-pipeline design, not a bug — which is why
  the charter says it's a defect "even if it looks like a feature."
- **Fix sketch:** change Beth's contract from "decide" to "classify and carry both positions";
  add a first-class `disagreements[]` artifact (oracle A said X / oracle B said Y / coordinator
  recommendation + rationale) that flows untruncated into the findings report.

### A2. CRITICAL — Persistent disagreement is reported as convergence
- `oracle/oracle2.py:1430-1435` (ledger workflow): if the same open questions appear in two
  consecutive valid rounds, `_check_convergence` returns
  `True, "Converged (repeated tradeoffs: …)"` → `session.converged = True`.
- The docstring (`oracle2.py:1394`) frames this as a *stop* criterion; the implementation labels it
  *consensus*. A document with a stable, unresolved architectural dispute is reported to the user
  as "Converged: Yes" (`frontend/src/components/CritiquePanel.tsx:38`, `cli.py:2077`).
- Stopping the loop here is correct; calling it convergence is a false-consensus defect.
- **Fix sketch:** return a three-state outcome (`converged | stalled_disagreement | max_rounds`);
  set `converged=False` with the repeated tradeoffs listed verbatim in the report header.

### A3. HIGH ⚖ — A single vendor model is the sole convergence authority, and it is prompted to converge
- Default workflow (`manual`, `oracle2.py:427`): Beth alone issues
  `LOCK | ONE_MORE_ROUND | HUMAN_REVIEW` (`oracle2.py:1547-1560`), and LOCK sets
  `session.converged = True` with no algorithmic cross-check.
- The prompt biases the judge: *"Favor convergence once serious defects are resolved"*,
  *"By Round 4, recommend either LOCK or HUMAN_REVIEW"* (`oracle2.py:183-187`), and round-context
  text repeats the pressure (`oracle2.py:1336-1338`).
- Meanwhile each reviewer's `overall_verdict` (`approve_with_minor_changes | revise |
  major_revision`) is collected in every response (`oracle2.py:81`, enforced in the OpenAI strict
  schema at `:574-581`) and **never read by any code path** — a unanimous `major_revision` from all
  four reviewers cannot block LOCK.
- **Fix sketch:** LOCK requires consistency with reviewer verdicts (e.g., any `major_revision` in
  the final round forces `HUMAN_REVIEW` or must be explicitly surfaced as overridden dissent).

### A4. HIGH — Convergence with an outstanding HIGH finding, quietly
- `oracle/oracle2.py:1408-1410`: ≤1 high finding passes the gate; the convergence reason only says
  `"Converged: 1 high, issue overlap 95%"` (`:1437`). Nothing forces that surviving high-severity
  issue into the report's headline; it sits inside per-round detail.
- **Fix sketch:** when converging with open high findings, list them by title in
  `convergence_reason` and the report header ("Converged WITH unresolved HIGH: …").

### A5. HIGH ⚖ — Round-1 is blind; every later round is anchored, and drift is undetectable
- Round 1 independence is real: reviewers run in parallel with identical, other-oracle-free
  prompts (`oracle2.py:1474-1480` manual, `:1617-1623` ledger). Good.
- Rounds 2+: reviewers re-review **Beth's revised draft** — the synthesis itself — with
  *"Focus your review on the changed sections"* (`oracle2.py:1230-1232`, ledger) or *"Do not raise
  … already-resolved concerns"* (`:1277-1281`, manual round 3+, where reviewers are never told
  what was "resolved"). This is structurally convergence-forcing: a reviewer who maintains its
  round-1 dissent is prompt-instructed to drop it.
- There is **no drift detection**: per-oracle positions across rounds are saved to disk
  (round files) but nothing compares them; a reviewer that silently abandons a critical finding
  without any draft change in that section is indistinguishable from a resolved finding.
- **Fix sketch:** persist per-oracle verdict + finding fingerprints per round; flag
  "finding disappeared with no corresponding draft change" as drift in the report.

### A6. HIGH — Vendor double-counting: agreement is treated as evidence regardless of source
- Fran and Codex are both `gpt-5.4` (`oracle2.py:474`, `:484`). The "4 independent reviewers"
  consensus pool is 3 vendors, and the same base model gets two votes.
- Nothing anywhere weights agreement vs. dissent asymmetrically: Sonnet merges by semantic
  similarity preserving only attribution (`merged_from`), Beth's prompts treat corroboration
  ("source_reviewers: [Fran, Gemini]", `oracle2.py:217`) as free-text context. Shared-training-data
  agreement (weak evidence) and cross-vendor dissent (strong evidence) are structurally identical.
- **Fix sketch:** record `provider` alongside oracle name in findings; annotate each merged issue
  as `cross_vendor` vs `same_vendor` corroboration; surface dissent count per issue in the report.

### A7. HIGH — The convergence gate's input is one model's unverified semantic judgment
- Ledger convergence criterion 3 (80% issue-ID overlap, `oracle2.py:1413-1419`) depends entirely on
  Sonnet voluntarily reusing prior issue IDs (`SONNET_REFEREE_PROMPT`, `:347-356`). No code checks
  that reuse happened or was correct; Sonnet re-minting IDs for the same issues reads as
  instability, and over-merging distinct issues reads as stability. Same-substance/different-words
  agreement detection (the audit's "semantic vs string" question) is thus delegated wholesale to
  one un-tested model call.
- Validation of referee output checks only that `issue_id` and `severity` exist
  (`oracle2.py:907-914`) — not that Beth's decisions reference real ledger IDs
  (`compute_metrics` joins on `issue_id` at `:1803-1809`; a dangling ID silently drops out of
  severity counts).
- **Fix sketch:** assert every Beth decision ID exists in the ledger (warn loudly otherwise);
  golden tests for referee dedup/ID-continuity (depends on E1).

### A8. HIGH — Dissent-bearing fields are requested from models and then thrown away
- Sonnet's output schema includes `conflict_flag` and `weak_signal` (`oracle2.py:375-376`) —
  **no code reads either field** (verified by grep: definitions only).
- `dropped_findings` (Sonnet's discards, with reasons) survive only as two scalar rates
  (`oracle2.py:1814-1835`); the dropped findings themselves never appear in any report.
- The adapter collapses merged findings to a name list (`oracle2_adapter.py:281-295`); original
  per-oracle severities and evidence are gone from `ReviewResult`.
- **Fix sketch:** propagate `conflict_flag=true` issues into a "Direct conflicts" report section;
  append dropped findings as an appendix table (oracle, title, drop reason).

### A9. MEDIUM — Uncertainty signals are structurally discarded ("IDK beats lying" violation)
- Every reviewer emits per-finding `confidence` (`oracle2.py:92`, required by the strict schema
  `:599-611`) — never consumed: not by Sonnet's normalized schema, not by convergence, not by the
  report (`cli.py:2135-2152` prints severity/title/problem/fix/sources only).
- `SHARED_CONTRACT` rule 7 (`oracle2.py:62`): *"If a concern is speculative, label it as
  speculative"* — but the OpenAI strict schema sets `additionalProperties: false` (`:569`) with no
  speculative field, so the only place the label can live is buried prose.
- **Fix sketch:** add `speculative: bool` to the finding schema; render confidence in the report;
  optionally weight convergence gates by confidence.

### A10. MEDIUM — Open Questions section shows the first round, not the last
- `oracle/cli.py:2166-2179`: the loop `break`s at the *first* valid round having open questions;
  the comment says "Only show from the last valid round." Final-round unresolved questions — the
  freshest dissent — are omitted whenever round 1 had any.
- **Fix sketch:** iterate `reversed(session.rounds)`.

### A11. MEDIUM — Repeated-tradeoff detection is exact string matching
- `oracle/oracle2.py:1431-1433`: set intersection over raw `open_questions` strings. The same
  tradeoff reworded across rounds is never detected (criterion silently inert); conversely, generic
  boilerplate questions repeating verbatim would flip the run to "converged" (see A2).
- **Fix sketch:** match on normalized text similarity or require Beth to emit stable tradeoff IDs.

**What's genuinely sound in this area:** round-1 blindness; parallel fan-out; failed reviewer
invalidates the round rather than silently proceeding 3-of-4 (`oracle2.py:1487-1490`); the
frontend reports "Converged: No" honestly when the flag is false; `compute_metrics` joins by
issue_id, not fuzzy title.

---

## B. Rule pack & schema robustness

### B1. HIGH — No validation or integrity check at review load time
- `load_pack` (`oracle/cli.py:492-507`) does a raw `json.loads` — no `validate_pack`, no
  comparison of the file's current hash to the manifest's `content_hash`. Validation gates exist
  only at generate/import (`cli.py:417`). A pack edited or corrupted on disk after registration
  (including a *promoted* one) feeds the consensus context unchecked; the review-time snapshot
  records the new hash (`cli.py:1979`) but compares it to nothing.
- **Fix sketch:** in `load_pack`, run `validate_pack` and compare hash to manifest; refuse or
  loudly warn on mismatch.

### B2. HIGH — Partial JSON recovery masquerades as full success in the consensus path
- `_recover_truncated_json` (`oracle/oracle2.py:1071-1149`) salvages as many findings as parse
  before the truncation point — by design ("a degraded round with N-1 findings is far less harmful
  than a failed round with zero", `:1077-1078`) — but sets **no degraded/recovered marker**.
  `call_oracle` then validates and returns it as an ordinary success (`:837-852`). A reviewer whose
  last 10 findings were cut off participates in convergence as if complete; nothing in the round
  files or report records that recovery happened.
- **Fix sketch:** set `result["recovered_partial"] = true` + count of salvaged elements; surface in
  the round file and report; consider invalidating the round when the salvage ratio is low.

### B3. MEDIUM — Vision repair mixes interpreted content into retrieved content without provenance
- `gpcm_rulepack_adapter.py:1212-1239` and `:1319-1342`: Sonnet-vision-extracted `shall_text` /
  `justification` / `section` overwrite the regex-extracted values in place; no field records which
  values were model-interpreted vs. mechanically retrieved. Philosophy rule #2 requires these to
  stay structurally separate; here the distinction is erased at build time, then promoted packs
  present both as equally retrieved.
- **Fix sketch:** add per-field provenance (`extracted | vision_repaired`) to the requirement dict;
  pack validator accepts it; promotion summary shows repair counts.

### B4. LOW — No pack version history
- Schema versions are fixed constants (`pack_validator.py:74,122,190`); packs carry only
  `content_hash` (spec §13.4). Regenerating a pack replaces it with no diffable history. The
  review-time snapshot (`cli.py:2018-2032`) mitigates per-run defensibility.
- **Fix sketch:** retain previous pack file under `packs/archive/<slug>@<hash>.json` on overwrite.

### B5. LOW — Silent statement truncation at render time
- `build_far_rulepack.py:248-249`: statements >500 chars truncated to 497 + `"..."` with no
  truncation marker distinguishable from prose ellipsis and no count in budget warnings.
- **Fix sketch:** use an explicit `[TRUNCATED]` suffix and tally into `budget_warnings`.

**Sound:** three JSON schemas with structural fallback validation; malformed-output handling
(strict schema for OpenAI, JSON mime for Gemini, balanced-brace extraction + retry for all);
fail-closed non-TTY promotion (`cli.py:643-654`); extraction-completeness and source-hash gates on
promotion (`cli.py:597-629`).

---

## C. Vendor adapter resilience

### C1. HIGH — No model pinning, no record of what model actually ran
- Defaults are floating aliases: `gpt-5.4`, `grok-4.20`, `gemini-2.5-pro`, `claude-opus-4-8`,
  `claude-sonnet-4-6` (`oracle2.py:465-511`) — not dated snapshots. The response's `model` field
  (which all four SDKs return) is discarded; neither configured nor actual model IDs appear in
  `session_summary.json` (`oracle2.py:1744-1768`) or any round file. Vendor-side model swaps are
  silent and retroactively unprovable.
- **Fix sketch:** persist `{oracle, provider, configured_model, response_model, temperature}` per
  call into the round files and session summary.

### C2. HIGH — Vendor outage: correctly flagged, but the loop burns money then emits ambiguous output
- A failed reviewer invalidates the round — good, no silent 3-of-4 (`oracle2.py:1487-1490`,
  `:1630-1633`). But `run_review` (`:1727-1740`) then starts the next round anyway: with one vendor
  hard-down for the whole run, all 4 rounds call the 3 healthy vendors (12 paid review calls) and
  produce nothing. Afterward `final_draft.md` is written **identical to the input** (`:1743`),
  `converged=False`, and `convergence_reason` may be empty (only set on stop paths) — and that file
  can flow into .docx generation (see F2).
- **Fix sketch:** abort after 2 consecutive invalid rounds; on zero valid rounds write a
  `REVIEW_FAILED` marker file and make downstream consumers (server `/generate`) refuse it.

### C3. MEDIUM — Naive retry strategy
- Uniform 3 attempts, 2/4/8s backoff, no jitter, no 429/`Retry-After` awareness
  (`oracle2.py:803-829`); the Anthropic client explicitly disables SDK retries
  (`max_retries=0`, `:532`). Only Gemini has a quota-fallback model (`:808-815`). Under
  rate-limiting, 3 fast failures invalidate a round (then see C2).
- **Fix sketch:** honor `Retry-After`; longer backoff for 429s; allow SDK-native retries.

### C4. MEDIUM — Grok has no structured-output contract
- `_call_xai` (`oracle2.py:689-713`) sends no `response_format`, unlike OpenAI (strict JSON schema,
  `:560-629`) and Gemini (`responseMimeType: application/json`, `:745`). Grok prose → brace-scrape →
  possible partial recovery (B2).
- **Fix sketch:** xAI's OpenAI-compatible endpoint accepts `response_format`; mirror the OpenAI
  reviewer schema.

### C5. LOW — Raw provider error bodies persisted/logged without redaction
- Keys themselves are only read from env and passed to SDKs (no direct logging found). But raw
  error bodies are kept: `result["raw"] = response.text[:2000]` (Gemini, `oracle2.py:764,773`) is
  written into round JSON files, and the server's per-session log handler stores raw exception
  strings with no key-shaped redaction (`server.py:439-450`, log cleaner at `:815-852` filters
  noise, not secrets).
- **Fix sketch:** regex-redact `sk-…`/`AIza…`-shaped substrings before persisting raws/logs.

---

## D. Observability & cost

### D1. HIGH — No cost/token/latency instrumentation
- Per-call elapsed time is logged transiently (`oracle2.py:835,851`) and lost. `response.usage`
  (OpenAI/xAI), Anthropic `usage`, and Gemini `usageMetadata` are never read. No per-vendor,
  per-round token or cost figures exist anywhere; the frontend's "$2–8/round" warning
  (`RoundsSelector.tsx`) is a hardcoded guess.
- **Fix sketch:** capture usage from each response into round files; aggregate into
  `session_summary.json` and `metrics.json`.

### D2. HIGH — Runs cannot be replayed or defended
- Persisted: parsed oracle outputs, revised drafts, final draft, summary, and (CLI path)
  `compliance_context.txt` + `pack_manifest_snapshot.json` (`cli.py:2013-2032` — genuinely good).
- Not persisted: the exact prompts sent (system + user), model IDs (C1), temperatures, reasoning
  effort, and **raw pre-parse responses** (after recovery, the original text is gone; only
  `raw[:2000]` survives on hard failures). For a system whose outputs may be defended in a
  compliance context, a run is not reconstructable.
- **Fix sketch:** write `run_manifest.json` (roster config, env-derived knobs, prompt hashes) and
  optionally a gzip'd raw-response archive per round.

### D3. MEDIUM — Metrics that are always zero are still reported
- In the default manual workflow, Beth's normalized payload has no `dropped_findings`
  (`oracle2.py:1518-1522`), so `duplicate_rate` and `unsupported_claim_rate`
  (`:1821-1835`) are constitutionally 0.0 — yet the findings report prints
  "Duplicate rate: 0.0%" (`cli.py:2118`) as if measured. Misleadingly precise.
- **Fix sketch:** emit "n/a (manual workflow)" when the source signal doesn't exist.

---

## E. Evaluation

### E1. CRITICAL (automatic per audit charter) — No golden-case harness
- Searched `tests/` (17 files, 91 tests), `docs/`, repo root: there are **no** known-flawed
  documents the system must flag, no known-sound documents it must pass, no seeded-defect
  regression corpus, and no scoring of detection performance. `tests/conftest.py` provides only a
  temp-dir fixture. The two workflow tests mock every oracle and assert plumbing, not judgment.
- Consequence: any change to prompts, convergence gates, model versions, or normalization is
  unverifiable — "significantly better" cannot currently be demonstrated, and neither could a
  vendor-side silent model swap (C1) be detected by behavior.
- **Fix sketch:** `eval/` directory: (a) 5–10 small specs with documented seeded defects +
  expected-finding assertions (severity floor, section match); (b) 2–3 known-sound specs with a
  max-false-positive budget; (c) runnable against mocked transcripts for CI and live vendors for
  release gating. This is the prerequisite for safely fixing A1–A8.

---

## F. General engineering

### F1. CRITICAL — Workflow/adapter filename mismatch silently degrades severity data
- Default `manual` workflow writes `round{N}_beth_normalized.json` (`oracle2.py:1537-1539`).
  The adapter — "the sole integration seam" (`oracle2_adapter.py:5-6`) — globs only
  `round*_sonnet_normalized.json` (`:166`, `:385`). Result, on every default-workflow server run
  (`server.py:458` passes no workflow → manual; `:470` builds the result):
  - every round's `normalized_issues` is empty; `total_issues_raised = 0`;
  - accepted defects lose their severity and **default to "medium"**
    (`oracle2_adapter.py:447`) — an accepted *critical* is recorded as medium in
    `ReviewResult.metrics`;
  - the preflight error is downgraded to a warning and parsing continues
    (`oracle2_adapter.py:355-368`) — fails open.
- The blast radius is bounded only by luck: the findings report and frontend metrics use the
  in-memory session instead (`cli.py:2056`, `server.py:477`), and `cli.py:2054` imports
  `build_review_result` without calling it. But `review_result` is persisted into session state and
  rebuilt on restart (`server.py:312`) for any consumer.
- **Fix sketch:** glob both filenames (or have both workflows write one canonical name); make the
  "no normalized files" preflight error fatal-or-flagged; regression test per workflow.

### F2. HIGH — "Maximum Reasoning": non-convergence euphemized in the deliverable
- `server.py:1228`: the generated .docx subtitle is
  `'Converged' if review_result.converged else 'Maximum Reasoning'`. A run that did not converge —
  including a C2-style total failure whose "final draft" is the unreviewed input — ships in a
  polished document labeled "Maximum Reasoning." Direct violation of "IDK beats lying" at the most
  outward-facing layer.
- **Fix sketch:** label honestly ("NOT CONVERGED — N unresolved issues; see findings report") and
  refuse generation when zero valid rounds exist.

### F3. HIGH — The convergence path has zero test coverage
- Untested: `_check_convergence` (all 4 criteria + the A2 inversion), `_last_valid_round` /
  `_last_two_valid_rounds`, `_run_round` (entire ledger path), `_parse_json`,
  `_recover_truncated_json` / `_recover_array_field`, and 100% of `oracle2_adapter.py`
  (preflight, parsing, citation extraction, metrics). The only convergence-adjacent tests mock Beth
  saying "LOCK" (`tests/test_oracle2_manual_workflow.py`).
- **Fix sketch:** pure-function unit tests first (`_check_convergence` is trivially testable with
  synthetic sessions), then adapter round-trip tests against fixture session dirs (doubles as the
  F1 regression test).

### F4. MEDIUM — Duplicated orchestration and adapter logic
- `_run_round` vs `_run_manual_round` (`oracle2.py:1440-1571` vs `:1574-1694`): ~120 lines of
  parallel-fan-out / write-files / update-session logic duplicated; the F1 filename divergence is
  this duplication's first casualty. `_call_openai` vs `_call_xai` (`:632-713`) duplicate the
  chat-completions flow minus the schema. `_with_system_prompt` (`:1195`) hand-copies dataclass
  fields (`dataclasses.replace` exists).
- **Fix sketch:** extract a shared round skeleton (fan-out, persist, validate) parameterized by
  the synthesis step; merge OpenAI-compatible callers.

### F6. MEDIUM — Over-broad exception handling at the server boundary
- `server.py:505`: `except BaseException` around the review runner — catches
  `KeyboardInterrupt`/`SystemExit`, converting shutdown into a "review error" session state.
  Assorted broad `except Exception → warn-and-continue` in pack bootstrap (`cli.py:163`) and chunk
  extraction (`cli.py:1165`) are defensible but uniformly silent.
- **Fix sketch:** narrow to `Exception`; re-raise `BaseException`.

### F5. LOW — Documentation drift (trust erosion, cheap to fix)
- `CLAUDE.md` says "5 oracles" — the roster has 6 (`oracle2.py:460-513`).
- Module docstring convergence criteria (`oracle2.py:13-17`: "Delta in accepted defects < 10%")
  do not match the implementation (`:1385-1437`: 80% issue-ID overlap).
- CLI epilog claims Grok default `grok-4` (`oracle2.py:1861`); actual default is `grok-4.20`
  (`:494`).
- Dead code: unused `build_review_result` import (`cli.py:2054`); `session._output_dir` hasattr
  check on an attribute that never exists (`cli.py:2060-2061`).

---

## Philosophy scorecard

| Rule | Status |
|------|--------|
| 1. IDK beats lying | **Violated** at the deliverable layer (F2), the convergence layer (A2, A4), and the signal layer (A9, B2, D3). Upheld well in the chat engine (refusal + INSUFFICIENT_DATA paths) and pack promotion gates. |
| 2. Retrieved ≠ interpreted | **Violated** in pack building (B3 vision repair). Upheld in the chat engine (citation-validated LLM output, deterministic fallback). |
| 3. Source tiering survives transformation | **Partially absent by design**: packs have draft/promoted status (with review-time warnings), but no tier concept exists for oracle findings (A6 — vendor provenance lost) or for rendered rules (uniform `[pack_id:rule_id]`). |
| 4. The system never decides | **Violated by design** in the review engine (A1, A3): Beth decides disagreements and convergence; dissent survives as counts and truncated reasons. The chat engine honors this rule rigorously (approval-refusal gate + grader). |

## What I could not determine (IDK)

1. Real-world *magnitude* of anchoring/sycophancy (A3, A5) and referee dedup quality (A7) — needs
   live runs against the E1 harness; the defects above are structural only.
2. Whether any production consumer currently reads the degraded `review_result.metrics` (F1) —
   I traced server code paths; external consumers of persisted session state are unknowable from
   the repo.
3. Whether xAI's endpoint accepts the strict `response_format` (C4 fix) for the configured model —
   needs a live call to verify.
4. Whether the unused `frontend` review_result fields are planned work or dead — spec says
   "CLI only," frontend exists; intent is undocumented.
