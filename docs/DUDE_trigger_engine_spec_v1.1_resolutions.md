# Trigger Calibration Engine — v1.1 Binding Resolutions

Amends `DUDE_trigger_engine_spec_v1.md` per its §14 gate. Two ORACLE
reviews (epistemics/dismissal-machine lens; privacy/abuse lens) produced
nine blocking findings. Implementation follows THIS document where it
conflicts with v1. Reviews preserved in full in the session record.

## Blocking resolutions (binding)

**R1 — The action engine takes zero trigger-derived inputs.** (E-B1)
§7's "trigger activation may affect action timing and reversibility
analysis" is struck. All allowed effects recondition on evidence-state
predicates only (evidence incomplete; no new data; recourse path exists)
— all already computable trigger-blind. v0.2 I8 stands unamended.
Test: `test_action_ranking_invariant_under_trigger_overlap` (identical
evidence, overlap none vs high → byte-identical ranking).

**R2 — Safety outranks the trigger engine, always.** (E-B2, P-B3)
Precedence: safety floor + I9 safety-dominant override > every
trigger-engine effect. While a crisis flag or live catastrophic
hypothesis exists: no pause/reversible-favoring effects, overlap display
demoted below resources, and the summary states "trigger overlap does
not reduce this emergency." Danger-shaped families (dependent_in_danger,
blocked_protective_access) ESCALATE into the safety layer on match —
they may add urgency, never terminate as psychology. NEED TO ACT NOW is
computed from deadlines + safety state + evidence dynamics only; trigger
overlap is an illegal input. §9's worked example replaced with a
HIGH-overlap/act-now-HIGH case.
Tests: `test_high_overlap_abuse_case_still_ranks_safety_action_first`,
`test_need_to_act_now_independent_of_trigger_overlap`,
`test_child_danger_crisis_precedes_trigger_overlap_display`,
`test_semantic_danger_family_match_escalates_to_safety`.

**R3 — Distortion vocabulary is bidirectional and template-bound.** (E-B3)
The block renames to "WHAT OVERLAP CAN DISTORT — IN EITHER DIRECTION"
with paired candidates (amplification: urgency, certainty, action
pressure, attention narrowing / suppression: minimization, habituation,
self-doubt), all conditional, all from the vetted template registry
through `validate_copy`. "Need to escape" and "protector response" are
removed from renderable vocabulary. Renders only at overlap ≥ moderate.
Mirrored invariant added: NO_TRIGGER_MATCH != ACTIVATION_UNWARRANTED,
with vetted no-match copy ("no calibrated pattern matched; that says
nothing about whether your read is right"). (P-I3)
Tests: `test_amplification_copy_is_bidirectional_and_template_bound`,
`test_no_match_never_rendered_as_unexplained_activation`.

**R4 — Status discipline: cap, promote, demote.** (E-B4, P-B4)
Phase-1 status cap: `self_report_supported` (renamed from
provisionally_supported to carry provenance); nothing seeds higher.
Promotion requires: ≥2 calibration sessions with temporal separation,
≥1 passed negative control, ≥1 in-vivo confirmation (user tags a real
case post-hoc). Demotion: a quorum of contradicting TriggerEvidence
auto-demotes one level with visible reason; user retire always wins;
staleness decay without recalibration. Out-of-scale raw scores are
preserved verbatim (§13) but trigger a re-ask and never count at face
value in status math. `repeated_case_pattern` and `assistant_hypothesis`
evidence support at most candidate/working-hypothesis status; match
confidence excludes match-derived evidence (no closed loop). Every
trigger retrieval into a case routes through `policy.authorize()`
(AllowedUse.TRIGGER_CONTEXT — cross_case_corroboration raises
structurally) and writes a `RetrievalRecord`.
Tests: `test_status_demotes_on_contradicting_evidence`,
`test_single_session_cannot_reach_strongly_supported`,
`test_case_derived_evidence_cannot_raise_match_confidence`.

**R5 — The matcher proposes; the user disposes.** (E-B5, P-B2)
CaseTriggerAssessment is a PROPOSAL: matched/reducer features cite exact
case-text spans and require user confirm/deny before entering merge();
unconfirmed renders as "possible overlap (model-assessed, unconfirmed)".
Every TriggerFeature carries `provenance_class`
(institutional_verifiable | interpersonal_performed). Reducers bind only
to user-confirmed facts independent of counterparty statements; while an
adversarial-cause hypothesis is live, reducers sourced from that
person's behavior are suspended. Assessments are excluded from the
evidence fingerprint by construction; model_run_id pinned per case.
Tests: `test_assessment_requires_user_confirmation_before_merge`,
`test_performed_legibility_does_not_reduce_match`,
`test_reducer_from_adversary_suspended_when_adversarial_hypothesis_live`,
`test_injected_instructions_in_case_text_do_not_alter_assessment`,
`test_assessment_excluded_from_fingerprint`.

**R6 — Custody of the calibration map.** (P-B1) — OWNER DECISION REQUIRED
The map (scores + identifiers) is the most weaponizable artifact the
system will hold. Regardless of the owner's git decision:
(a) seed/calibration data enters via import, with real-world anchors
replaced by opaque slugs in family labels; (b) calibration bodies and
intensity scores NEVER appear in model prompts (slugs+descriptions only;
deterministic pre-filter decides candidate families before any LLM sees
anything; canary test in the HEARTH mold:
`test_calibration_text_never_in_model_prompt`); (c) intensity scores and
evidence bodies never render on default screens — families + one-line
why only; evidence behind an explicit audited reveal; (d) a revocation
primitive exists (supersede with reason; erasure path documented);
(e) calibration is text-only (never spoken via TTS); (f) calibration
captured while a crisis flag is active is quarantined
provisional-pending-reconfirmation, and every response stamps
state_at_capture. (P-I1, P-I4, P-M2)
Tests: `test_calibration_during_crisis_quarantined`,
`test_revoked_calibration_excluded_from_matching`.

## Important resolutions (binding)

**R7 — ATTEND survives.** Calibration tags carry onto families;
`case_resolution` evidence (resolved cases where the family flagged a
concern that proved real) feeds accuracy; WIDEN/ATTEND merge semantics
preserved. (E-I2)

**R8 — Discriminance.** Per-family fire-rate monitoring; a family
matching >60% of cases renders a low-diagnostic-value caveat and stops
counting toward HIGH. Overlap levels defined: none=0 confirmed matches,
low=1, moderate=2, high=≥3 confirmed family matches. (E-I3)

**R9 — One overlap statistic.** Legacy triggers migrate as `candidate`
with `superseded_by_family_id`; a superseded legacy trigger is inert
when its family is assessed; legacy historical matches are audit-only,
never TriggerEvidence. Family-level confirmed matches are the only
N-of-M feed. (E-I1, P-I5)

**R10 — Single source of truth.** Status/confidence live on
PersonalTriggerProfile only; families are shared shape definitions;
external rendering uses the I13 band vocabulary; features typed by
provenance (observed/user_reported/model_inferred) and world-shaped
families render as "your account resembles your calibrated pattern,"
never as bare situation-assertions. (E-I6, E-I4)

**R11 — §8 Lab copy runs through the banned-phrase validator; merge =
new family + supersedes pointers; render set defined (self_report
status and above render; candidate matches log as evidence, invisible).
(E-M1..M3)**

## Definition of done — additions
All tests named above join §12's list. §14 items each cross-reference
the test that mechanizes them. Full suite green before deploy.
