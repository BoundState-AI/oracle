# DUDE Spec v0.2 — Production Build Contract (Phase 1 core)

**Supersedes:** `DUDE_spec_v0.1.md` where they conflict.
**Input:** `DUDE_oracle_review_v0.1.md` — every blocking finding (revisions 1–8,
12–16 of the review) is resolved here or explicitly deferred with a reason.
**Scope of this contract:** the DUDE core engine as a production Python system in
this repo (`dude/`), built to HEARTH discipline: fail closed, deterministic layers
fully tested, refusals instead of silent failures. Voice/UI/Postgres/multi-tenant
are later phases; nothing in this phase may foreclose them.

The v0.1 constitution stands (observation ≠ inference; robust action under
uncertainty; §34 bidirectionality; "trauma does not invalidate telemetry"). This
document changes the *machinery* so it obeys that constitution.

---

## 1. Non-negotiable invariants (tested before implemented)

I1. **Safety floor runs first, always.** The deterministic safety classifier runs
    on every capture and at the top of every analysis run — *before* the
    no-new-data gate, before extraction, before anything can throw. Its output is
    persisted before any other pipeline step executes. A store failure while
    persisting a safety event aborts the run with a refusal, never a silent skip.
    (Review A1/A2.)

I2. **No motive attribution, ever.** All user-facing engine copy describes the
    evidence state, never the user's psychology. "The evidence set is unchanged
    since the last run" — allowed. "You are recomputing because uncertainty
    hurts" — banned. Enforced by a machine-checked banned-phrase list plus a
    template registry: engine copy comes only from vetted templates. (A8.)

I3. **New hypothesis over old evidence is learning, not rumination.** The analysis
    gate keys on an analysis-scope fingerprint (evidence + hypothesis set +
    deadlines + elapsed-time bucket), not on evidence alone. A run triggered by a
    new hypothesis is labeled `NEW_HYPOTHESIS_REANALYSIS` and runs the full
    pipeline. (A12a.)

I4. **Silence is hashable.** Elapsed time enters the scope fingerprint in buckets,
    and explicit non-response checkpoints are first-class events, so Rule 6 has
    data-model backing and continued silence can legitimately reopen analysis.
    (A12b.)

I5. **The fingerprint hashes user-contributed material only.** Capture IDs,
    artifact content hashes, user-confirmed events, user interpretations. Never
    LLM-derived observation text or versions — re-extraction must not change any
    fingerprint. (A12c/d.)

I6. **Course-of-conduct accrual.** Same-pattern-class events accrue cumulative
    weight that is reported alongside per-run deltas and can escalate a case with
    no new evidence *types*. Repetition of incidents is evidence; repetition of
    thoughts is not. The two are distinguished structurally (events vs analysis
    requests), not by classifier judgment. (A4.)

I7. **Symmetric trigger layer.** A trigger match widens uncertainty in both
    directions ("evidence requirements go up — harder to confirm AND harder to
    dismiss"); it never one-way discounts. Per-trigger calibration tags
    (`overfires` / `neutral` / `historically_accurate`) can shift the adjustment,
    and all channels (trigger, memory, calibration) merge into ONE net, itemized,
    user-visible adjustment per interpretation. (A6/A7.)

I8. **No hidden priors.** The action engine uses prior-free criteria: dominance
    filtering and minimax regret across live hypotheses. There is no
    `HypothesisWeight`. There is no `EmotionalImpulsePenalty` — the user's
    emotional state is never a scoring input. Reversibility is a single field.
    Information gain is scored per-hypothesis (probing is not free in adversarial
    worlds). (A9/A10.)

I9. **Asymmetric-stakes override.** Interpersonal cases always carry an
    adversarial-cause hypothesis ("a person is deliberately engineering this
    ambiguity"). While any hypothesis whose harm class is catastrophic-to-user is
    live (not contradicted), the engine switches to a safety-dominant criterion:
    actions are first filtered for acceptability under that hypothesis, and
    safety-seeking actions are exempt from irreversibility penalties. Robustness
    hedging never recommends staying in a possibly-dangerous situation because
    leaving scores as "irreversible." (A3.)

I10. **The system holds no favored model.** `user_favored_hypothesis_id` exists;
     a system-favored model does not. When passes disagree (model builder vs
     adversary), the disagreement is surfaced as a disagreement. `reconcile` is
     deterministic annotation attachment — attacks are attached to hypotheses as
     annotations, never silently merged. (A13.)

I11. **Append-only store.** Records are immutable; corrections create a new
     record with a `supersedes` pointer. A `user_confirmed` record can never be
     overwritten by machine output. Provenance is mandatory on observations —
     no orphan facts. (A21, v0.1 §31.)

I12. **LLM passes are pluggable and fail closed.** Every model pass sits behind a
     typed protocol. In this phase all passes are stubs (no network, mirroring
     HEARTH's `ClauseAnalyzer`). A pass failure produces a refusal finding and a
     partial-run record — never a synthesis without the adversary pass, never a
     silent fail-open. (A20, §55.)

I13. **Confidence is banded everywhere externally.** `supported / plausible /
     weakly_supported / unresolved / contradicted`. Internal floats never render.
     Cumulative-since-open support is computed alongside per-run deltas so drip
     evidence can cross bands. (§18, A4.)

---

## 2. Resolved control flow (replaces v0.1 §57)

```
capture(raw_input):
    safety = safety_floor.scan(raw_input)          # I1: deterministic, first
    store.append(SafetyEvent) if safety.flags       # persisted before anything
    if safety.crisis:  -> crisis response (resources, no hold advice), continue capture
    store.append(Capture, Artifacts, user Events)   # stable IDs minted here, once

analyze(case):
    safety = safety_floor.scan(case.recent_material)   # I1 again, before gates
    store.append(SafetyEvent) if safety.flags
    scope = fingerprint(case)                          # I3/I4/I5
    mode = gate(scope, last_run)
    if mode == NO_NEW_DATA:
        return prior run + evidence-state message (I2) + cumulative view (I6)
        # crisis output, if any, is NEVER gated
    run pipeline passes (each fail-closed, I12):
        extract -> separate -> unknowns -> hypotheses (archetypes attempted,
        "no credible boring hypothesis" is reportable) -> adversary ->
        reconcile (annotation attachment, I10) -> triggers (symmetric, I7) ->
        actions -> evaluate (prior-free, I8/I9) -> synthesize (template-bound, I2)
    store.append(AnalysisRun with mode label, deltas, cumulative)
```

The synthesizer is template-bound: safety verdicts and action-evaluation values
are injected verbatim into fixed slots; free prose cannot contradict or omit them.

---

## 3. Analysis gate modes

| Mode | Trigger | Pipeline |
|---|---|---|
| `NEW_EVIDENCE` | evidence hash changed | full |
| `NEW_HYPOTHESIS_REANALYSIS` | hypothesis set changed, evidence unchanged | full, labeled |
| `SCOPE_CHANGE` | deadline set or elapsed-time bucket changed | full, labeled |
| `NO_NEW_DATA` | nothing above changed | serve prior run + cumulative view |

Elapsed-time buckets: 7-day granularity since last run. Deadlines are first-class
(`Deadline` on Case) — Case H is mechanized, not red-teamed.

## 4. Fingerprint definition

```
evidence_hash  = SHA256( sorted(capture_ids)
                       + sorted(artifact_sha256s)
                       + sorted(user_confirmed_event_ids)
                       + sorted(interpretation_ids + ":" + version) )
scope_hash     = SHA256( evidence_hash
                       + sorted(hypothesis_lineage_ids)
                       + sorted(deadline_isoformats)
                       + elapsed_bucket )
```

Event IDs are minted at capture and never re-minted. LLM-derived material is
excluded by construction.

## 5. Safety floor (deterministic layer under any future LLM gate)

Categories: `self_harm`, `violence_threat`, `child_danger`, `medical_emergency`,
`stalking_pattern`, `coercive_control`, `legal_deadline`. Pattern-based (regex /
keyword classes), tuned for recall; false positives surface resources, which is an
acceptable cost. Crisis output includes 988 Suicide & Crisis Lifeline, Crisis Text
Line (text HOME to 741741), National DV Hotline (1-800-799-7233), and 911
guidance. While a crisis flag is active: hold/wait recommendations are suppressed,
and the mandatory "high-risk action" option in the action generator is suppressed
(review Missing #12). Chronic categories (stalking_pattern, coercive_control) feed
the conduct accrual engine, not just the acute bypass — the chronic-danger pathway
exists (A3, Missing #3).

## 6. Deferred (with reasons)

- **Postgres schema** — the store is an interface; JSONL append-only implements it
  in Phase 1 (single-tenant dogfood). The Postgres adapter must add nothing the
  interface doesn't already require (FKs mirror the referential checks the JSONL
  store enforces in code).
- **Voice/ASR, screenshots, email ingest** — capture is text/file in Phase 1.
- **Embeddings / semantic loop detection** — Phase 1 loop status is deterministic
  (gate modes + run counting). Semantic similarity is an LLM/embedding inference
  and will be labeled as such when added; it will ask, never verdict.
- **Auth/multi-tenant, `case_members`** — deleted from scope (review A23).
- **Regulatory/marketing posture, clinician tier** — `clinician_supplied` enum
  value removed from contracts; no clinical claims in any Phase-1 surface.
- **Live LLM passes** — protocol stubs until keys + provider DPAs exist; the
  engine must be fully exercisable (and dogfoodable) without them.

## 7. Repo conventions

Package `dude/` beside `oracle/` and `hearth/`. Every module header carries
`Safety Critical:` and `Psychologically Critical:` fields with matching dunders
(`__safety_critical__`, `__psychologically_critical__`). Psychologically-critical
modules (safety floor, gate/fingerprint, loop copy, action engine, synthesizer
templates, store) follow the never-suppress-error pattern: failures are logged in
full and surfaced as refusals — an analysis that fails OPEN is the cardinal
failure mode. Logger namespace `dude.<module>`. All contracts inherit `DudeModel`
(`extra="forbid"`). Tests for the Section-1 invariants are written before the
features and live in `tests/dude/`.
