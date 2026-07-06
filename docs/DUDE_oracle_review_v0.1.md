# ORACLE Adversarial Review — DUDE Spec v0.1

**Review target:** `docs/DUDE_spec_v0.1.md`
**Date:** 2026-07-06
**Method:** Three independent adversarial passes with distinct lenses — (1) epistemics
and product logic, (2) safety / clinical / legal / abuse-of-product, (3) architecture,
data model, and MVP realism — followed by deterministic synthesis (dedup, severity
ranking). Per the spec's own §34 rule, every pass attacked in both directions: where
the design over-validates the user's fears AND where it institutionally gaslights a
user whose fears are correct.

**Engine note:** the live multi-oracle pipeline (`oracle review`) requires four
provider API keys, none of which were available in this environment. This review was
executed as three independent adversarial agent passes honoring the ORACLE contract
(attacks / missing hypotheses / unsupported links / strong points / recommended
revisions) with no reviewer certifying its own output.

---

## Verdict

**The constitution is good. The machinery contradicts it.**

The spec's philosophical core — observation ≠ inference, bidirectional adversary,
"trauma does not invalidate telemetry," robust action under uncertainty — survives
attack and is genuinely better than anything shipping in this space. But nearly every
*mechanism* proposed to implement that constitution violates it somewhere, and the
violations are not random: **every deterministic pressure in the system pushes in one
direction — toward discounting the user.** Trigger overlap only ever discounts (§8).
User memory only records over-fire tendencies (§42). Calibration's knowable outcomes
are adversely selected toward "it was nothing" (§60). The action engine penalizes
irreversibility, catastrophe, and emotional arousal — which is a description of every
safety-seeking action an abuse victim ever takes (§14). The loop detector attributes
motive ("you are recomputing because uncertainty hurts"). §34 promises symmetry; the
deterministic substrate is asymmetric by construction, and the Oracle agent is never
pointed at the system's own artifacts. The spec builds the institutional-gaslighting
machine it explicitly warns against, one reasonable-looking mechanism at a time.

The second meta-finding: **the red-team list (§50) is a list of named-but-unmechanized
failures.** Cases D, E, F, G, and H each identify a way the product kills someone's
safety, dignity, or legal position — and no section of the spec contains a mechanism
that resolves any of them. A red-team entry without a corresponding design section is
an open defect, not documentation.

The third: **the highest-severity defects are in the pseudocode, not the philosophy.**
§57 as written bypasses the Safety Gate whenever the evidence hash is unchanged,
loses safety events on partial failure, and lets the Synthesizer — a strong model —
compose the user-facing recommendation *after* every check has already run,
uncritiqued. The spec's own prime directive ("never let one model generate, critique,
score, and certify itself," §55) is violated by the last pass of its own pipeline.

Recommendation: **revise before building Week 1.** The observed/inferred/unknown
spine, the falsifiers field, and the Invariant Action Engine concept are keepers. The
evidence hash, the trigger discount, the safety control flow, and the scoring formula
all need redesign at the spec level — they are cheap to fix now and catastrophic to
fix after users exist.

---

## Attacks

Ranked by severity. Convergent findings (independently produced by 2–3 lenses) are
marked ⚡.

### SEV-1 — safety-critical control flow

**A1. ⚡ The NO_NEW_DATA early return bypasses the Safety Gate — §57 contradicts §17
by construction.** In the orchestration pseudocode, `safetyGate.run()` executes only
if the evidence hash changed. A user whose situation has escalated without a new
recorded event (emotional escalation with unchanged evidence is *explicitly listed in
§11* as a common pattern) gets "No new data, no new analysis" and the safety gate
never runs. Case G concrete failure: user re-opens the case at 2am with worsening
symptoms they haven't logged; the system's answer is the anti-rumination banner. §17
promises "DUDE must never delay action when immediate danger exists"; §57 guarantees
it will. Safety must run at capture time (P0), before any gate — including the
no-new-data gate.

**A2. ⚡ The Safety Gate has no control flow — it is a gate that gates nothing.** In
§57, `safetyGate.run()` output merely feeds the synthesizer. No branch, no halt, no
UI mode change, no escalation path, no resources (988, Crisis Text Line, DV hotline),
no deterministic keyword floor beneath the LLM judgment. The `safety_events` table
appears once in §29 and is never written or read anywhere in the design. And because
`persistAnalysis` runs only at pipeline end, a safety flag raised at P9 is *lost* if
P10 throws. The entire crisis response is one sentence of copy. Concrete
company-ending scenario: DV victim captures "he said if I leave he'll make sure I
regret it"; the LLM reads relationship ambiguity; trigger overlap is (correctly)
maximal; §16 emits "This action is irreversible and your trigger overlap is high.
Hold for 12 hours." That output is discoverable.

**A3. ⚡ The Invariant Action Engine is structurally biased toward inaction in
exactly the coercive-control cases where leaving is urgent (Case D — named in §50,
resolved nowhere).** The §14 formula penalizes `IrreversibilityPenalty`,
`CatastrophicDownside`, and `EmotionalImpulsePenalty`, and rewards
`OptionPreservation` (reversibility is counted twice). Leaving an abuser is the
paradigm irreversible, high-catastrophic-downside, maximally "impulse-contaminated"
action — it loses to "gather more evidence" under almost any weighting. When
hypotheses carry asymmetric catastrophic stakes, robustness-across-hypotheses is the
wrong decision criterion; the correct move is committing to the dangerous hypothesis
at moderate confidence. Meanwhile the mandatory boring-hypothesis quota (§7 Stage 6)
manufactures the abuser's own script ("I was just tired") as formal system output,
and §8's trigger discount delivers "you're overreacting" with an evidence table.
§17's bypass list is acute-event shaped (violence, fire, deadline) and structurally
cannot fire on slow-burn coercive control. Also: `InformationGain` is scored as an
unconditional bonus, but under adversarial hypotheses a "clarifying question" tips
off the abuser — observation is not free in every world.

**A4. ⚡ Constitutional Rules 2 and 3 are epistemically false for course-of-conduct
harms.** "Repetition does not create evidence" is wrong for stalking, harassment, and
coercive control — the pattern *is* the evidence; this is literally how
course-of-conduct statutes define the crime. Rule 3 + §12 will classify the
seventeenth same-class boundary violation as "recomputation, not learning."
Compounding it, §18's coarse confidence bands plus §19's per-event deltas mean drip
evidence (each item individually explainable, jointly damning) never crosses a band
boundary — the §20 screen reads "no material change" run after run while cumulative
support grows decisive. The constitution models causes as indifferent nature; abusers
are intelligent adversaries optimizing to stay under the evidence threshold. DUDE
tells the stalking victim "no new data" while a court-recognizable pattern
accumulates unaggregated.

**A5. Suicide/self-harm: highest-risk population, one line of design.** PTSD,
betrayal trauma, and high-conflict divorce carry elevated suicide risk; rumination —
the product's core engaged behavior — is an independent risk factor. Total spec
treatment: "suicidal crisis" in the §17 bullet list, "self-harm" in §38's checklist.
No response protocol, no safe-messaging compliance, no policy for a case *about the
user's own suicidality* — and §36 *requires* Agent 7 to generate a "high-risk action"
option in every case, which in a self-harm-adjacent case is directly dangerous.
"You are recomputing because uncertainty hurts," delivered to a suicidal user, is
dismissal at the worst possible moment. §49 has an eval category for every classifier
except the single highest-stakes one: §17 recall.

### SEV-2 — the asymmetric substrate (institutional gaslighting by math)

**A6. ⚡ The trigger discount (§8) is statistically unsound and one-directional.**
Trigger patterns are defined over *situation types* (institutional silence,
powerful-person ambiguity). Real threats in those domains produce the same cues, so
P(trigger match | interpretation correct) ≈ P(trigger match | interpretation false);
the likelihood ratio is ~1 and no Bayesian discount is licensed. The match proves the
user is in a domain where they have priors — not that the priors are wrong. The
spec's own §60 example concedes some triggers are *positively* predictive
("institutional tone changes have historically been real signals"), yet §8 has no
up-weight path. Self-fulfilling failure loop: user defines 7 broad triggers → every
case they'd ever bring matches several → permanent discount in domains where evidence
structurally cannot "improve" (silence, cooling). Case F names this failure; §8
mathematically guarantees it. Worse, *inferred* triggers (§9) mean consulting DUDE
about a topic eventually taxes your credibility on that topic.

**A7. ⚡ Discount stacking with no reconciliation.** Three channels can fire on the
same interpretation — trigger discount (§8), memory tendencies ("Joseph tends to
overinterpret silence," §42), calibration updates (§60) — with no de-duplication
rule. A single disposition is counted three times. No symmetric up-weight stack
exists anywhere. Net design pressure is uniformly toward disbelieving the user — the
exact outcome §34 says the Oracle exists to prevent, built into the substrate the
Oracle never reviews.

**A8. ⚡ Loop detection attributes motive, violates Rule 1 at the system level, and
its false-positive cost is unpriced.** "You are recomputing because uncertainty
hurts" is a psychological interpretation of the user's inner state — an inference
presented as observation, in the product's signature tone, to a population for whom
"you're being irrational" is the original wound. The spec's own example is
self-undermining: "Tawyna talked to Herald" vs "Herald called Tawyna" differ in
*initiator* — in a legal or institutional case that is a materially distinct
hypothesis, not a variant. §49 tests only whether loops are caught, never the
false-positive rate on genuinely distinct hypotheses — the eval measures one tail of
an asymmetric-cost error. And §55 files semantic-identity detection under
"deterministic code" when it is an embedding/LLM judgment by definition: model
inference wearing a determinism costume.

**A9. ⚡ `HypothesisWeight(h)` is a hidden probability oracle.** §14's
`Σ HypothesisWeight(h) × Utility(a,h)` requires a prior probability distribution over
hypotheses — exactly the object §5 and §18 forbid the product from stating. The spec
never says who assigns the weights. If an LLM assigns them, the top-line
recommendation is driven by invented probabilities the user never sees and cannot
contest — "avoid fake precision externally" becomes *hide* fake precision. Case D
scenario: the model quietly assigns the abuse hypothesis weight 0.15; every action
ranking downstream inherits it; "Best robust move" says stay. Calling the scoring
"deterministic" (§55) is authority theater — the *addition* is deterministic; every
operand is model-generated.

**A10. `EmotionalImpulsePenalty` directly contradicts §2.3.** Penalizing an action in
proportion to the user's inferred emotional state *is* treating distress as evidence
against the user's judgment. The Case A user (real retaliation) is maximally
activated precisely because the threat is real; their best action receives the
largest penalty at the moment it is most warranted. `hypothesisDependence` already
captures the legitimate concern. And §16's example "No resignation while trigger
score > 0.8" inverts Rule 5: a model-computed inference gets write access over the
user's real-world actions while the user's judgment gets proposal access —
weaponizable by anyone who keeps the user activated.

**A11. Case E (psychosis-adjacent) has a detector and no behavior — and the
archetype quota re-dignifies the persecution model every run.** §38 "checks
psychosis-like certainty escalation," then nothing: no escalation ladder, no analysis
mode change, no rate limit, no referral copy. Both failure directions are live:
(a) a real stalking victim ("neighbors coordinate surveillance" is *sometimes true*)
gets pathologized; (b) DUDE becomes a delusion amplifier with production values —
timelines, evidence tables, and the mandatory user-favored hypothesis slot (§7 Stage
6) give the persecution narrative formal standing and an evidence-mapping row every
single run. Structured logging of persecutory "evidence" is known to consolidate
delusional systems. "Preserve dignity" appears only in the red-team list; it is a
goal masquerading as a design.

### SEV-2 — core mechanism defects

**A12. ⚡ The evidence hash is keyed on the wrong things — it blocks the system's own
definition of learning and cannot stabilize.** Four independent failures:
(a) *New hypothesis over old evidence is real learning* — Bayesian updating has two
inputs, evidence and hypothesis space — but the hash covers only
`event_ids + observation_versions + artifact_versions`. A user who adds H_new via
`POST /cases/:id/hypotheses` (§56) and calls `/analyze` is told "you are recomputing
because uncertainty hurts." The system's own Oracle agent exists to generate
`missing_hypotheses` from unchanged evidence — the architecture's adversary does
professionally what Rule 3 forbids the user to do.
(b) *Silence is invisible to it.* Rule 6 admits silence as data; non-response and
elapsed time generate no events, so they can never change the hash. Case F user
waiting on a powerful institution: each passing unanswered deadline strengthens the
cooling hypothesis; the anti-rumination engine says nothing has changed —
institutional gaslighting implemented as a hashing decision.
(c) *LLM extraction is non-deterministic.* Observations are P1/P2 outputs;
re-extraction rewords or re-splits them, bumping `observation_versions` and firing a
full reanalysis with zero new user data — while a fresh voice capture not yet
extracted into events contributes nothing, so `analyzeCase` answers "no new data" to
a user who just gave it new data. "normalized_event_ids" is a name, not a design;
nothing mints stable IDs across runs.
(d) *Gameable in both directions.* Any manufactured micro-event ("logged: I feel
worse today") unlocks full deep re-analysis; a ruminating user learns the incantation
within a week. Rule 2 is enforced against thoughts but not against low-content event
logging.

**A13. ⚡ `reconcile()` and `favored_model` are unallocated authority; the
Synthesizer certifies itself.** §57's `reconcile(hypotheses, oracle)` — merging
adversarial attacks into revised causal models — is semantic judgment: either an
unlisted eleventh LLM pass (who critiques it?) or trivial string-appending (then the
adversarial architecture is theater). §41's system-emitted `favored_model` means the
system designates a favorite explanation — in tension with §5 ("not a truth machine")
and never defined as user-favored vs system-favored, which are opposite products. And
P10 — a strong model — composes everything the user actually reads *after* the Oracle
pass, the Robustness Evaluator, and the Safety Gate have all run, with no check on
its output. It can soften, rewrite, or contradict the safety verdict and the
robustness numbers in free prose. The last generation step is exactly the
generate-and-certify-itself pattern §55 forbids.

**A14. Calibration (§60) — the moat — trains on the worst data in the system.**
(a) In these domains outcomes are mostly never known (you rarely learn why the boss
went silent); the calibration set is tiny and *adversely selected* — revealed
outcomes over-represent benign-with-explanation cases, while successful manipulations
stay unlabeled, so the system systematically learns "the user overfires."
(b) Outcome labels are user-reported claims with no provenance requirement — the
`outcomes` table isn't even schemed — so "confirmed: they were coordinating" can
itself be inference promoted to fact, poisoning the calibration loop with the exact
failure the product intercepts at the object level.
(c) The §60 example draws a per-individual generalization from n=1.
§59 builds the business on this loop.

**A15. The state model has states but no machine.** Zero transitions defined: who
moves a case to RESOLVED? What sets ACTION_SELECTED? REOPENED is modeled as a state,
not an edge. WAITING_FOR_DATA is simultaneously *computed* (hash equality, §12) and
*stored* (`cases.status text`, §30) — dual source of truth that desynchronizes the
first time an event is added without an analysis run, after which the UI shows a
stale anti-rumination banner over real new evidence. §3 demands invariants live in
"deterministic application logic"; no such logic is specified and the schema cannot
enforce it (A16). WAITING_FOR_DATA also has no exit except new data — approaching
deadlines, expiring options, and new hypotheses are all legitimate re-analysis
triggers with no path.

### SEV-2 — legal, regulatory, and abuse surface

**A16. ⚡ "Not a therapist" does not survive the feature list.** Intended use is
determined by function and marketing, not disclaimers. The spec names PTSD/CPTSD,
anxiety, and betrayal trauma as target populations (§0, §4), maintains trigger
profiles with a `clinician_supplied` confidence enum (§9), performs crisis/psychosis/
self-harm detection (§17, §38), stores longitudinal behavioral profiles (§42, §59),
and plans a "Clinician-supported" tier (§58) — while §51 says "No clinicians." Under
FDA SaMD framing and EU MDR Rule 11 this is hard to keep in the general-wellness
bucket. Separately, building a Safety Gate creates a *negligent undertaking* problem:
having assumed the duty to detect crises, performing it badly is legally worse than
not having the feature. Plaintiff's counsel reads §38's checklist to the jury as an
assumed and breached duty.

**A17. ⚡ §48's third-party boundary is incoherent with the core product, and the
abuser-as-user problem is unaddressed.** Every worked example in the spec — Jerry,
Tawyna, Bennie, Chrissy, Herald, "boss," "spouse" — is an evidence dossier about a
named third party with hypothesis generation *about their motives*. The
allowed/dangerous line ("understand this email" vs "profile my coworker from 500
texts") is a difference of volume, not kind, and the roadmap (longitudinal cases,
cross-case patterns, timelines) scales the allowed use into the banned one. Point the
product at "why is my ex not replying": Agent 7 generates information-seeking actions
(a surveillance to-do list), the Timeline tab is a stalking log, loop detection
deduplicates the fixation. No mechanism distinguishes a betrayal-trauma victim from
an obsessed rejected partner — their inputs are textually near-identical. Third
parties whose emails/texts/photos are uploaded are GDPR data subjects with access and
erasure rights the architecture never mentions.

**A18. ⚡ The database is a weapon against its own user, and the trigger profile is a
manipulation manual.** High-conflict divorce is a *named target segment*. Cases,
timelines, decision journals, and §42 memory ("tolerates bad situations too long")
are discoverable in divorce, custody, and employment litigation; there is no
privilege, no litigation-hold guidance, no capture-time warning. §46 specifies only
at-rest/in-transit encryption — vendor-readable plaintext — and local-only is
deferred, so MVP ships the maximally sensitive configuration. The §9 trigger profile
(`cues`, `typicalInterpretations`, `typicalActions`, severity) is an exploit guide
for this specific person; combined with cases that name abusers and document escape
planning, a breach is a physical-safety event, not an identity-theft event. There is
no threat model for the adversary who most wants this data: the intimate partner with
device access (no duress PIN, no decoy mode). And §42/§59 contradict each other: "no
invisible psychoanalytic dossier" — but the moat is a vendor-held trigger map and
false-positive profile. Visibility is a UI property; subpoena, breach, insider access,
and acquisition risk are storage properties. Calibration additionally requires
long-horizon retention, in direct tension with "delete everything."

**A19. ⚡ The privacy architecture is decorative relative to the actual data flow.**
Every analysis run ships the full case — trauma narratives, named third parties,
legal disputes — to at least two strong-model vendors plus a cheap-model vendor plus
(unavoidably, see A21) an embedding vendor. Field-level encryption protects against
your own database, not against the pipeline that is the product. "No training on user
content by default" is a vendor-DPA clause, not an architectural property. §47
(local-first later) is directly contradicted by §59 (the moat requires longitudinal
cloud data) and §58's Private tier — three mutually undermining commitments presented
as compatible.

### SEV-3 — buildability

**A20. ⚡ §57 is unimplementable as written: full 10-pass recompute, sequential, no
partial-failure semantics, fronted by a synchronous endpoint.** Eight sequential
`await`s, no try/catch, no retry, no idempotency, no persisted intermediate state. If
P5 times out, does the run fail closed (nothing shown) or fail open (synthesis
without adversarial pass — violating §55)? Never specified. Wall-clock for 4–5
strong-model passes over monotonically growing case context: realistically 1–4
minutes — against §22's promise of conversational feel, with no streaming and no
capture-time cheap pass. Cost is O(case lifetime) per run because context is never
windowed: long cases get slower and more expensive exactly as they become most
valuable. `POST /cases/:id/analyze` (§56) is a synchronous HTTP endpoint fronting a
multi-minute pipeline — it times out at every proxy default. Transient 429 on P10 →
run discarded → user retries → hash unchanged → NO_NEW_DATA → the user can never get
an analysis of their own data. No concurrency control (two analyze calls interleave
against different snapshots; `case_snapshots` is undesigned), no per-user budget or
rate limit — and the natural behavior of the target user maximizes runs.

**A21. ⚡ The schema contradicts the product thesis, and pgvector "if needed" is
needed and is the privacy hole.** §30: no foreign keys; free-text status columns with
no CHECK/enum (the "deterministic invariants" have no enforcement point);
`source_event_ids uuid[]` carries no referential integrity ("no orphan facts" is
structurally unenforceable); **no version column on observations even though §12
hashes `observation_versions`** — the fingerprint's inputs don't exist in the schema;
the `inferences` table — "the product" per §7 Stage 4 — has no schema; `analysis_runs`,
`analysis_deltas`, `case_snapshots`, `evidence_links`, `decisions`, `outcomes`,
`safety_events` all undefined; rows are mutable in place with no audit/history, so a
re-extraction can silently overwrite a `user_confirmed` observation in a product
whose entire pitch is trustworthy provenance. §19/§20 diff hypotheses across runs
("Previous: plausible → Current: weakened") but nothing gives an LLM-regenerated
hypothesis a stable identity to diff against. Meanwhile §11's semantic loop detection
is an MVP feature and requires embeddings of the user's most sensitive utterances:
generated where, stored where (pgvector columns must be plaintext-equivalent to be
searchable — field-level encryption and vector similarity search are mutually
exclusive without engineering the spec doesn't mention), covered by "delete
everything"? Unaddressed.

**A22. The 4-week MVP is not buildable as scoped.** Inbound email forwarding (domain,
MX/inbound-parse, threading, spam, attachments) ≈ a week; conversational voice
capture (streaming ASR, barge-in, mobile permissions) another; screenshot OCR another;
a multi-provider model router with schema validation and retries another; then the
pipeline, the real schema, auth, and seven screens. Realistic estimate for one strong
engineer: 10–14 weeks. The trigger layer has a cold-start problem — new users have no
trigger corpus, so P6 does nothing for weeks; it is pure cost in the MVP window.

**A23. Unexamined surfaces.** `case_members` (§29) implies multi-user shared cases
with no design — an abuser as case member, or a spouse's counsel arguing joint
access, is catastrophic. No age gating (minors in abusive homes are natural users).
Child-danger detection (§17/§38) with no position on mandatory-reporting duties once
the vendor has recorded knowledge in `safety_events`. Case H is red-teamed but no
deadline field or reminder mechanism exists anywhere in §29–30. §53's "Supabase for
fast build" parks the most sensitive consumer dataset conceivable on a convenience
stack.

---

## Missing hypotheses / missing design elements

1. **Safety floor** (vs. the existing gate): deterministic always-on crisis layer
   beneath the LLM — keyword/classifier floor, 988 / Crisis Text Line / DV-hotline
   surfacing, jurisdiction-aware resources, a real pipeline *branch* that halts
   analysis and switches UI mode, `safety_events` written first and consumed by
   something. A written false-negative story.
2. **Pattern-of-conduct evidence class**: aggregation mechanism exempting
   DV/stalking/harassment from Rules 2–3 — repeated same-class events accrue weight
   and can *raise* alarm through the evidence hash, mirroring course-of-conduct law.
   Plus a cumulative-evidence review ("cumulative since case open" alongside "since
   last analysis") so drip patterns can cross confidence bands.
3. **Mandatory adversarial-cause hypothesis** in interpersonal cases ("a person is
   deliberately engineering this ambiguity") — otherwise the hypothesis menu is
   systematically kind to manipulators — with a Case-D scoring override: when it is
   live, safety-seeking actions are exempt from irreversibility/impulse penalties and
   safety-planning templates are injected. A chronic-danger pathway parallel to §17's
   acute list.
4. **Case-E escalation ladder** as numbered behavior: cap hypothesis regeneration,
   de-structure output, suggest human contact, clinician-reviewed dignity-preserving
   copy, defined exit criteria.
5. **Re-analysis triggers beyond new evidence**: new hypothesis, approaching
   deadline, expiring option, elapsed-time checkpoints — all with labeled modes
   (e.g. `NEW_HYPOTHESIS_REANALYSIS`), so legitimate re-analysis is never branded
   rumination.
6. **Representation of silence/elapsed time as data** (Rule 6 has no data-model
   backing): scheduled non-response checkpoint events that enter the hash.
7. **`HypothesisWeight` provenance** — or a prior-free criterion (minimax-regret,
   dominance filtering). Never model-assigned silent priors.
8. **User-appeal path for loop detection** ("I dispute that this is the same
   hypothesis") and a false-positive budget with §49 evals for near-miss distinct
   hypotheses.
9. **De-duplication rule across the three discount channels** (trigger, memory,
   calibration): one net adjustment, itemized, visible — with a symmetric up-weight
   path fed by calibration.
10. **Oracle pointed at the system's own artifacts**: each run must attack at least
    one trigger match, memory entry, loop verdict, or calibration update. §34's
    bidirectionality is currently prompt-level; make it pipeline-level. Track the
    system's own error rates (Oracle attack accuracy, loop-detection precision,
    trigger-matcher error) — currently only the *user's* calibration is measured.
11. **Abuse-of-product controls**: per-third-party case volume/velocity limits, a
    monitoring-pattern classifier, refusal states — or delete §48 and accept the
    exposure explicitly. Third-party data-subject handling (GDPR access/erasure),
    retention limits, subpoena policy.
12. **Suicide-specific design**: safe-messaging-compliant copy, suppression of §36's
    mandatory high-risk option in flagged contexts, protocol for cases about the
    user's own state, §17-recall eval category.
13. **Regulatory strategy section**: intended-use statement, claims review, wellness
    vs SaMD positioning; decide now whether `clinician_supplied` and the clinician
    tier exist in v1 (recommend: remove both).
14. **Intimate-partner threat model**: duress PIN, decoy mode, device-access
    considerations; capture-time discoverability notice for legal-adjacent cases;
    litigation-hold guidance.
15. **Engineering absences**: incremental analysis (pass-level dependency graph);
    capture-time cheap pass with streamed ack; LLM output validation layer (typed
    schemas, repair, retry, *fail-closed* policy); schemas for all §29 tables with
    append-only provenance; state-transition table; stable hypothesis identity
    (`lineage_id`); embedding lifecycle; outcome-capture flow with provenance bands
    (`verified` / `user_reported` / `assumed`) and minimum-n before generalization;
    materiality classifier (Rule 3 says "materially changed"; the hash tests exact
    change); deadline tracking; run budget/quota model; `case_members` decision
    (recommend: delete for MVP).

---

## Unsupported links

- **Disclaimer → absence of regulatory/legal duty.** Intended use is inferred from
  features and marketing; "not a therapist" carries near-zero weight against
  §8–9/§17/§38/§42/§58.
- **Trigger overlap → confidence should be discounted.** Requires a likelihood-ratio
  argument the spec doesn't make; its own §60 example contradicts it. Asymmetric by
  construction.
- **Same evidence hash → "recomputation, not learning."** False whenever the
  hypothesis set, action landscape, deadlines, or elapsed time changed; rising
  intensity without evidence change is itself clinically significant data being
  discarded — and same-class repetition can be substantive evidence (course of
  conduct).
- **"You are recomputing because uncertainty hurts."** A causal claim about the
  user's motives presented as system knowledge. The system cannot observe motive.
- **"Deterministic scoring" → trustworthiness.** Determinism of arithmetic confers
  no reliability on model-invented operands.
- **Robust-across-hypotheses → good move.** Holds only under roughly symmetric
  stakes; asserted universally; contradicted by the spec's own Case D.
- **"Outcomes become known" (§60).** The calibration premise, unsupported in exactly
  the domains (§1's examples) the product targets.
- **Multi-model separation (§55) → safety.** Prevents self-certification, not
  correlated failure — independent models share training-distribution blind spots on
  coercive control and psychosis. And the Synthesizer loophole breaks even the
  self-certification claim.
- **§12 → §11.** Hash equality detects byte-identical evidence, not semantic loops;
  §11's rephrased-hypothesis examples are invisible to the hash. The two sections
  describe different mechanisms; neither alone delivers Rule 3.
- **§22 → §32/§57.** "Conversational feel" is asserted; ten sequential passes with
  no streaming makes it impossible.
- **§46 → §32.** Field-level encryption asserted alongside a pipeline requiring
  plaintext at 3+ external vendors; never reconciled.
- **§48's allowed/dangerous distinction → enforceable boundary.** No detection or
  enforcement mechanism specified; the core workflow performs the "dangerous"
  activity at smaller scale.
- **Visible/editable memory (§42) → no dossier harm.** UI visibility does not change
  breach, subpoena, or insider exposure of vendor-held profiles.
- **§3 "invariants in deterministic application logic" → §30.** The named
  enforcement point does not exist in the design (no constraints, no state machine).
- **§63 (4 weeks) → §51/§52 scope.** No decomposition supports the timeline.

---

## Strong points

(What survives three-lens attack. Honest, not flattering.)

- **The observation/inference/unknown separation as the product is correct and
  genuinely novel.** §1's "inference promoted to fact" framing identifies the right
  intervention point; Stages 3–5, mandatory provenance ("no orphan facts"), and the
  Reality tab are the right product spine. All three reviewers independently ranked
  this the strongest element.
- **§25's falsifiers field ("What would change my view") is real epistemics** — it
  makes hypotheses falsifiable and is arguably *underused*: it should be the backbone
  of WAITING_FOR_DATA's exit criteria.
- **§34 is the best paragraph in the spec**: bidirectional adversary, "trauma does
  not invalidate telemetry," explicit naming of institutional gaslighting as a
  failure mode. Rare and correct. The defect is that the surrounding machinery
  (§8, §11, §14, §42, §60) doesn't obey it.
- **The Invariant Action Engine framing** — score actions across hypotheses rather
  than resolving the hypothesis — is the strongest *idea* in the spec and cheaply
  computable once inputs exist. It needs the asymmetric-stakes override, not
  replacement.
- **§18's banded confidence over fake percentages** is the right discipline for this
  population (the flaw is band quantization × per-event deltas, not banding).
- **§55's "never let one model generate, critique, score, and certify itself"** is
  architecturally sound — the spec just violates it at P10.
- **The red-team list (§50) and eval categories (§49) are unusually honest** — the
  spec names most of its own fatal cases. Named-but-unmechanized is a better starting
  position than denial.
- **§9's explicit-confirmation rule for inferred triggers**, §16 being
  user-configurable rather than forced, §5's non-goals, §42's
  visible/editable/deletable memory, §44's action templates, and §36's mandatory
  no-action/information-seeking options are all good instincts.
- **§46's privacy list** (local-only, no training, export/delete everything) is the
  right list — wrongly deprioritized.

---

## Recommended revisions

Priority-ordered. Items 1–6 are blocking for any build start; 7–12 are blocking for
any real user; 13–18 are blocking for scale.

1. **Fix the safety control flow.** Safety triage runs at capture time (P0), before
   the NO_NEW_DATA gate and before extraction. `safety_events` is written first,
   durable, and consumed by a defined crisis mode (halt pipeline, switch UI, surface
   988/CTL/DV-hotline and jurisdiction-aware resources, suppress all hold
   recommendations). Add a deterministic keyword floor beneath the LLM. Add a
   post-synthesis check: either the Synthesizer fills a deterministic template into
   which the safety verdict and robustness numbers are injected verbatim, or a
   verifier diffs its prose against them. Add §17-recall as a §49 eval category.
   Write the false-negative story down.
2. **Re-key the fingerprint and rename the concept.** Hash only user-contributed
   material: capture IDs, artifact content hashes, user-confirmed events, user
   interpretations. Stable event IDs minted at capture, never re-minted. Add
   `interpretation_hash` and an analysis-scope fingerprint
   (`evidence ∪ hypothesis_set ∪ action_landscape ∪ deadline_set ∪
   elapsed_time_bucket`). Replace hash-equality with a two-tier gate: exact hash for
   "literally nothing added," cheap materiality classifier for "added but
   immaterial" — that is what Rule 3 actually says. Labeled modes:
   `NEW_HYPOTHESIS_REANALYSIS` is legitimate and full-pipeline.
3. **Add the course-of-conduct exception to Rules 2–3.** Same-class repeated events
   aggregate; pattern accrual can escalate a case without new evidence *types*;
   scheduled non-response checkpoints make silence hashable (Rule 6 gets data-model
   backing). Add cumulative-since-case-open scoring to §20 so drip evidence can cross
   bands.
4. **Fix the action engine for asymmetric stakes.** Mandatory adversarial-cause
   hypothesis in interpersonal cases; when live, an explicit safety-dominant
   criterion replaces robustness-maximization at a stated evidence threshold, and
   safety-seeking actions are exempt from irreversibility/impulse penalties. Delete
   `EmotionalImpulsePenalty` (`hypothesisDependence` + no-action windows carry the
   legitimate content without penalizing the person). Merge the reversibility
   double-count. Condition `InformationGain` per-hypothesis (probing is not free in
   adversarial worlds). Define `HypothesisWeight` (uniform default, user-visible
   coarse bands, user-editable) or replace expected utility with minimax-regret /
   dominance filtering. Write the Case D policy into the spec, not the red-team list.
5. **Reframe the trigger layer as symmetric.** Trigger overlap widens uncertainty in
   *both* directions ("evidence requirements go up — harder to confirm AND harder to
   dismiss"), never one-way discount. Couple §8 to §60: calibration showing a trigger
   is predictive must up-weight it (per-domain tags: `overfires` / `neutral` /
   `historically accurate`). Cap and unify the three discount channels into one net,
   itemized, user-visible adjustment.
6. **Demote loop detection from verdict to question, and fix its voice.** "This looks
   like a variant of H1 — is it, or is the initiator/direction a new claim?" requires
   user confirmation before any rumination framing. All anti-rumination copy
   describes the *evidence state*, never the user's psychology: "The evidence set is
   unchanged since the last run" — yes; "you are recomputing because uncertainty
   hurts" — never. Add false-positive evals on near-miss distinct hypotheses.
7. **Close the §55 loopholes.** Declare `reconcile()` honestly (an LLM pass with a
   contract, or deterministic annotation-attachment — pick one and say so). Rename
   `favored_model` → `user_favored_model` or remove it; Model-Builder/Oracle
   disagreements surface to the user *as disagreements* (that's a feature). Point the
   Oracle at system artifacts each run (trigger matches, memory entries, loop
   verdicts, calibration updates) and track the system's own error rates.
8. **Case-E ladder as numbered behavior**: cap regeneration of the unsupported
   user-favored hypothesis across runs (relax the archetype quota generally — "no
   plausible boring hypothesis found" is itself reportable evidence), de-structure
   output, suggest human contact, clinician-reviewed copy, exit criteria.
9. **Suicide-specific design** per Missing #12, including suppressing §36's mandatory
   high-risk option in flagged contexts.
10. **Move client-side/E2E encryption and the intimate-partner threat model into MVP
    scope.** Duress PIN / disguise mode. Treat the trigger profile as the crown-jewel
    asset. Capture-time discoverability notice for legal-adjacent cases; subpoena
    policy; third-party data-subject handling; delete `case_members` for MVP. Resolve
    §47/§59/§58 honestly: either the moat is cloud-longitudinal (say so, drop
    local-first from the pitch) or design sync-encrypted local-first now. Write the
    privacy *data-flow diagram* (every external endpoint receiving plaintext: LLM
    vendors, ASR, OCR, embeddings) before the encryption list; decide in-house vs
    vendor embeddings now — it determines the Private tier's feasibility.
11. **Add the regulatory section.** Intended-use statement, marketing-claims review;
    remove `clinician_supplied` and the clinician tier from v1; counsel review before
    naming PTSD in any store listing.
12. **Spec `outcomes` with provenance** (`verified` / `user_reported` / `assumed`),
    confidence bands, and minimum-n before any per-person or per-domain calibration
    generalization. The moat cannot be built on inference promoted to fact at the
    meta-level.
13. **Split the pipeline: capture-time vs analysis-time.** Capture: P0 safety + P1
    extraction + streamed conversational ack, <5s. Analysis: async job (queue or
    Temporal *now*) with per-pass checkpointing, retries, idempotency keys, and a
    written failure policy — **fail closed on Oracle or Safety failure**; no
    synthesis without the adversarial pass. `/analyze` returns a run ID; add run
    status + SSE. This repo's own HEARTH fail-closed discipline is the model.
14. **Design incremental analysis**: pass-level dependency graph keyed on what
    changed (new event → P4+; new interpretation only → P5+; nothing → serve prior
    run). Also the only path to acceptable unit economics; add per-user run
    quotas tied to §58 tiers.
15. **Rewrite §30 as a real schema**: FKs, enum/CHECK statuses, junction tables (no
    uuid arrays), version columns that actually exist, append-only observation
    history (superseded-by chains — provenance products need append-only cores),
    schemas for all §29 tables, stable hypothesis `lineage_id` to make §19/§20 diffs
    possible, deadline fields (Case H), embedding lifecycle including deletion.
16. **Define the state machine as a transition table** (state, event, guard, actor,
    next-state); WAITING_FOR_DATA computed-only (a view, never a column).
17. **Cut the MVP honestly**: drop email forwarding, screenshots, and the trigger
    layer (cold-start dead weight) from v1; text capture first, voice second;
    collapse to 4 passes (extract+separate / hypotheses / Oracle /
    synthesize+actions) with deterministic action arithmetic. Re-estimate: 8–10 weeks
    for the cut scope, not 4.
18. **Adopt the cross-reference rule**: every §49 eval category and §50 red-team case
    must name the spec section that mechanizes it. A red-team entry without a
    mechanism is an open defect. (This single rule would have caught the majority of
    the findings above.)

---

## Closing

The one-sentence north star survives: *preserve valid intuition without letting
uncertainty, fear, or a compelling story seize control of consequential decisions.*
The mantra survives. The spine — observed / inferred / unknown / falsifiers / robust
moves — survives.

What does not survive is the assumption that one-directional skepticism is neutral.
As drafted, every mechanism that could err errs toward telling the user they're
recomputing, triggered, overfiring, or hedging-is-wise — and the populations this
product targets are precisely the ones for whom that error is the original injury and
occasionally lethal. §34 already states the fix: attack both directions. The revision
work is making the *machinery* obey the constitution it was given.

Fear may not deploy to production. Neither may this spec — yet. Revise and re-review.
