# DUDE Trigger Calibration Engine — Spec v1 (founder source, verbatim)

Status: PRE-IMPLEMENTATION. Per §14, an ORACLE review of this design runs
first; implementation begins only after blocking findings are resolved.

---

We discovered a design flaw in DUDE's trigger system.

Current problem:
DUDE only fires on 7 pre-entered PTSD triggers. That is too brittle and too semantically shallow. Replace the fixed-trigger mechanism with a structured, personal Trigger Calibration Engine.

This is not a generic PTSD checklist and must not become one.

Core principle:
A trigger match may explain activation, urgency, certainty, attentional narrowing, or action pressure.
A trigger match may NEVER discount observations, reduce evidence weight, invalidate a concern, or imply that the current threat is imaginary.

Hard invariant:
TRIGGER_OVERLAP != EVIDENCE_AGAINST_CASE

Also preserve:
"Trauma does not invalidate telemetry."
"A real signal. An unknown cause. No access to the system."
"Historical pattern similarity is context, not corroboration."
"Repeated extraction is not repeated evidence."

==================================================
1. REPLACE STRING TRIGGERS WITH STRUCTURED OBJECTS
==================================================

Create a first-class trigger model.

Suggested entities:

TriggerFamily
- id
- slug
- label
- description
- status:
  - candidate
  - provisionally_supported
  - strongly_supported
  - contradicted
  - retired
- confidence
- created_at
- updated_at

TriggerFeature
- id
- trigger_family_id
- feature_type:
  - required
  - amplifier
  - reducer
  - exclusion
  - contextual
- feature_slug
- description
- weight_hint nullable
- provenance

PersonalTriggerProfile
- id
- user_id
- trigger_family_id
- confidence
- status
- notes
- first_observed_at
- last_calibrated_at

TriggerCalibrationResponse
- id
- user_id
- prompt_id
- raw_score
- declared_scale_min
- declared_scale_max
- raw_response_text
- context
- timestamp
- provenance

TriggerEvidence
- id
- user_id
- trigger_family_id
- source_type:
  - direct_user_report
  - calibration_response
  - matched_pair_contrast
  - repeated_case_pattern
  - assistant_hypothesis
  - clinician_input
- epistemic_status:
  - user_stated_fact
  - user_confirmed_pattern
  - working_hypothesis
  - assistant_interpretation
  - derived_summary
- support_direction:
  - supports
  - contradicts
  - ambiguous
- strength
- source_reference
- timestamp

CaseTriggerAssessment
- id
- case_id
- trigger_family_id
- matched_features
- missing_features
- amplifiers_present
- reducers_present
- confidence
- explanation
- model_run_id
- created_at

Never collapse provenance.
Never convert an assistant interpretation into a user fact.

==================================================
2. ADD MATCHED-PAIR CALIBRATION
==================================================

The major discovery is that broad labels are misleading.

Example:
"being misunderstood" is too broad.

User response:
- false motive attributed by person with no power = 1
- same false motive attributed by person controlling employment = 5

Therefore the likely mechanism is not generic misunderstanding.
It is closer to:
consequential_false_motive_attribution_by_power_holder

DUDE needs matched-pair calibration prompts that vary one dimension at a time:

- power vs no power
- clear rules vs arbitrary discretion
- clean exit vs constrained exit
- explicit scope vs unclear scope
- factual discussion of past vs permanent identity judgment
- success while invisible vs visibility to powerful people
- child danger with access vs child danger with blocked access
- fixed timeline vs moving opaque timeline

Implement:
CalibrationPrompt
CalibrationPair
CalibrationDimension
PairContrastResult

Do not average paired answers blindly.
Infer candidate latent mechanisms only when the contrast supports them.
Mark them as working hypotheses until sufficient calibration exists.

==================================================
3. SEED THESE CURRENT PERSONAL CANDIDATES
==================================================

These are derived from direct user self-ratings across two calibration rounds.

Do not treat causal origin as known.
Do not say childhood, Akashic, NASA, etc. "caused" a trigger merely because the story fits.

A. consequential_false_motive_attribution

Definition:
A person or institution with meaningful power assigns the user a harmful motive the user does not recognize as their own, and that interpretation can materially affect the user's life.

Evidence:
- "powerful person accuses you of a motive you do not have" = 4
- false motive, zero power over life = 1
- same false motive, controls employment = 5

Status:
strongly_supported

Required/contextual features:
- attributed motive
- user disputes motive

Major amplifiers:
- power asymmetry
- employment consequence
- institutional consequence
- no meaningful appeal
- ability to make interpretation operational

Reducers:
- no real power
- explanation invited
- evidence reviewed
- transparent appeal path

Important:
Do NOT label this generic "being misunderstood."

--------------------------------------------------

B. historical_event_used_as_fixed_identity

Definition:
A bounded past event is used as proof of permanent present character or untrustworthiness.

Evidence:
- old mistake used as evidence of who user is now = 4
- 1994 raised privately as factual concern with explanation allowed = 1
- 1994 used as proof user is fundamentally untrustworthy now = 5

Status:
strongly_supported

Important distinction:
discussion_of_past != identity_foreclosure

--------------------------------------------------

C. unclear_scope_authority_intrusion

Definition:
An authority enters, searches, inspects, accesses, or controls a personal/professional space while the limits of its authority are unclear to the user.

Evidence:
- someone searches belongings/space/phone/files/work = 4
- valid warrant, clear scope, counsel present = 1
- search while unsure what they may legally touch = 5

Status:
strongly_supported

Major feature:
unclear boundary of authority

Reducer:
clear scope + counsel + legible procedure

Do NOT model as generic privacy sensitivity.

--------------------------------------------------

D. constrained_exit

Definition:
The user cannot leave physically or functionally without serious loss.

Evidence:
- cannot leave without losing something important = 5
- physically trapped with trustworthy person = 3
- physically free to leave meeting but leaving could destroy career = 4

Status:
strongly_supported

Subtypes:
- physical
- occupational
- financial
- institutional
- relational

Do not assume all subtypes are equal.

--------------------------------------------------

E. arbitrary_power_without_legible_recourse

Definition:
Another person or institution has discretionary control over an important outcome without clear rules, limits, accountability, or meaningful recourse.

Evidence:
- dependent on someone who can arbitrarily withhold money/work/access/permission = 5
- boss can fire user but gives clear rules/direct feedback/appeal path = 0
- boss cannot fire user but can arbitrarily block work without explanation = 3
- "trust the process" without explaining process = 3

Status:
strongly_supported

Important:
authority itself is NOT the trigger.
Legible bounded authority may score zero.
Arbitrary opaque discretion is the relevant mechanism.

--------------------------------------------------

F. dependent_in_danger

Definition:
A child or dependent is in danger, being humiliated, falsely accused, harmed, or otherwise needs protection.

Evidence:
- son unexpectedly unreachable = 4
- son bullied/humiliated/falsely accused by authority = 4
- accused of failing as father = 4
- own actions may threaten family safety/home/future = 4
- child in trouble with full access and clear plan = 4

Status:
strongly_supported

Related amplifier:
blocked_protective_access

Evidence:
- child in trouble and authority controls whether user can reach/protect him = 5

Important:
Do not reduce the entire trigger to helplessness.
Child danger alone scored 4.

--------------------------------------------------

G. visibility_to_power / powerful_positive_attention

Definition:
The user becomes highly visible to powerful people or is singled out positively by them.

Evidence:
- highly successful but mostly invisible = 0
- highly visible and praised by powerful people = 5
- doing well/becoming visible and expecting something bad to follow = 4
- good thing happening but unable to relax because reversal expected = 3

Status:
provisionally_supported, high priority for further calibration

Critical distinction:
success itself scored 0 in the matched comparison.
Visibility to powerful people scored 5.

Do NOT label this generic fear_of_success.

Needs additional calibration:
- praised by peers
- praised by direct manager
- praised privately by executive
- praised publicly by executive
- featured by institution
- singled out by charismatic powerful person
- offered status/access
- asked to present upward
- anonymous success vs named visibility

--------------------------------------------------

H. consequential_suspended_outcome

Definition:
A meaningful outcome remains unresolved while another person or institution controls timing.

Evidence:
- another person controls whether life changes = 4
- forced to repeatedly prepare for moving threat = 4
- six-month wait with explicit rules/date/criteria = 3
- six-week wait with moving dates/no explanation = 4
- ordinary repeated delay = 2

Status:
provisionally_supported

Amplifier:
moving_or_opaque_timeline

Important:
waiting itself appears activating.
Opacity amplifies it.
Do not reduce this solely to ambiguity.

--------------------------------------------------

I. loss_of_agency_over_created_work

Definition:
The user loses attribution, control, access, or the ability to use work they created.

Evidence:
- someone takes credit for creation = 4
- invention used without credit but user retains use = 3
- someone gains control and can exclude user from invention = 4

Status:
provisionally_supported

Subdimensions:
- attribution
- ownership
- access
- exclusion
- control

Do not collapse them.

--------------------------------------------------

J. psychiatric_or_character_delegitimization

Definition:
A legitimate concern is dismissed through claims about PTSD, instability, toxicity, dangerousness, or irrationality rather than evaluated on evidence.

Evidence:
- legitimate concern attributed to PTSD instead of evaluated = 5
- implied dangerous/toxic/unstable without concrete examples = 4
- intensity treated as evidence of irrationality = 3
- spouse suggests PTSD may affect urgency but still examines evidence = 2
- authority says "just PTSD" and refuses evidence = 3

Status:
provisionally_supported

Important:
There is inconsistent intensity across wording/context.
Preserve that inconsistency.
Do not average it away.
Needs more calibration.

==================================================
4. PRESERVE LOW-SUPPORT / REJECTED BROAD THEORIES
==================================================

The system previously risked inventing a beautiful but wrong autobiographical model.

The following broad candidates were weak in current self-report and must NOT be promoted to core triggers without new evidence:

- ambiguous abandonment
- generic silence
- hidden-channel suspicion
- generic misunderstanding
- retaliation for leaving
- relationship rupture
- public embarrassment
- "truth will not protect me"
- consent followed by consequence

Examples of low scores:
- important person suddenly stops replying = 1
- sense people discuss user somewhere inaccessible = 1
- rules change after action = 1
- inaccurate paraphrase = 1
- leaving job/relationship/institution and expecting retaliation = 1
- public misunderstanding = 1
- truth itself may not protect user = 1
- consented without understanding consequences = 1

Store these as:
candidate_with_low_support
or
currently_contradicted

Do not delete them permanently.
New evidence may change the model.

Hard invariant:
A compelling narrative is not evidence.

==================================================
5. CASE ANALYSIS BEHAVIOR
==================================================

When a current case matches a personal trigger, output:

Trigger overlap:
- none / low / moderate / high

Matched trigger families:
- list only supported matches

Why:
- exact current event features that matched
- exact personal calibration evidence supporting the match

Then separate:

Signal status:
- real signal present?
- unknown?
- no signal observed?

Cause status:
- known
- partially supported
- unresolved

Possible amplification:
- urgency
- certainty
- action pressure
- attention narrowing
- need to identify hidden mechanism
- need to escape
- protector response

Evidence effect:
ALWAYS:
"Trigger overlap does not reduce the weight of observed evidence."

Example output:

REAL SIGNAL: yes
CAUSE: unresolved
TRIGGER OVERLAP: high
MATCHES:
- consequential false motive attribution
- arbitrary power without legible recourse

WHAT MAY BE AMPLIFIED:
- urgency
- certainty about motive
- pressure to act before more telemetry arrives

WHAT IS NOT DISCOUNTED:
- observed behavior
- direct communications
- timing
- documented events

==================================================
6. INTEGRATE WITH ORACLE
==================================================

Oracle must attack both errors:

Error A:
"The trigger means the threat is imaginary."

Error B:
"The trigger is irrelevant because the threat might be real."

Correct stance:
A real concern can activate an old trigger.
A trigger can distort urgency or causal certainty without making the signal false.

Oracle prompts should explicitly ask:

- What observed evidence survives even if trigger activation is high?
- What causal claims are unsupported even if the concern is real?
- Is the system using PTSD as a dismissal mechanism?
- Is the system ignoring trigger-driven urgency because it fears invalidating the user?
- What action remains robust across both possibilities?

==================================================
7. ACTION ENGINE RULES
==================================================

Trigger activation may affect action timing and reversibility analysis.

It may NOT insert an "emotional impulse penalty" into evidence or action scoring.

Allowed effects:
- favor reversible actions when urgency is high and evidence incomplete
- recommend a pause when no new data exists
- identify clean-exit options
- surface appeal/recourse paths
- seek scope clarification
- separate immediate protector action from speculative causal investigation

Not allowed:
- "user is triggered, therefore wait"
- "user has PTSD, therefore concern is probably false"
- "high activation means lower observation credibility"

==================================================
8. ADD TRIGGER CALIBRATION UI
==================================================

Add a Trigger Calibration section under Lab.

Support:
- single scenario rating
- matched-pair scenario rating
- raw score history
- confidence changes
- "why DUDE thinks this is a trigger"
- user correction
- retire trigger
- split trigger into narrower subtypes
- merge candidate triggers only with explicit provenance

Do not expose this as a giant clinical PTSD checklist.

Use language like:
"What shifts your state?"
"What changes when power enters the picture?"
"Which of these hits harder?"
"What part of this situation is actually hot?"

==================================================
9. ADD MAIN UX SUMMARY
==================================================

On the primary Reality screen, show:

REAL SIGNAL
CAUSE
TRIGGER OVERLAP
WHAT MAY BE AMPLIFIED
NEED TO ACT NOW
ROBUST NEXT MOVE

Example:

REAL SIGNAL: yes
CAUSE: unresolved
TRIGGER OVERLAP: high
WHAT MAY BE AMPLIFIED: urgency and certainty
DOES TRIGGER MAKE CONCERN FALSE? no
NEED TO ACT NOW: low
ROBUST MOVE: preserve evidence, avoid accusation, wait for new telemetry

==================================================
10. PRIVACY AND CROSS-CASE CONTAMINATION
==================================================

Personal trigger calibration is highly sensitive.

Requirements:
- local-first where possible
- encrypted at rest
- explicit user ownership
- no cross-user learning from personal trigger content
- no cross-case leakage
- no trigger retrieval from another user
- audit every trigger retrieval into a case
- trigger profile retrieval must be user-scoped before semantic search

Hard invariant:
semantic_similarity != personal_trigger_match

==================================================
11. MIGRATION
==================================================

Migrate the existing 7 fixed triggers into legacy structured TriggerFamily records.

Do not discard prior data.

Mark:
source_type = legacy_manual_trigger

Preserve:
- creation time
- prior matches
- provenance
- user edits

Do not automatically mark legacy triggers strongly supported.

==================================================
12. TESTS
==================================================

Add regression tests at minimum:

test_trigger_match_does_not_discount_observation_weight
test_trigger_match_does_not_reduce_evidence_confidence
test_power_changes_false_motive_activation
test_generic_misunderstanding_not_promoted_from_powered_false_attribution
test_clear_scope_search_reduces_intrusion_match
test_unclear_scope_search_matches_authority_intrusion
test_visibility_to_power_separate_from_success
test_invisible_success_does_not_match_visibility_trigger
test_old_event_discussion_separate_from_identity_foreclosure
test_child_threat_independent_of_blocked_access
test_blocked_protective_access_is_amplifier
test_legible_authority_separate_from_arbitrary_power
test_constrained_exit_supports_physical_and_consequential_subtypes
test_waiting_separate_from_opaque_moving_timeline
test_raw_scores_preserved_across_scale_versions
test_out_of_range_raw_score_preserved_not_silently_clamped
test_conflicting_calibration_not_averaged_away
test_low_score_candidate_not_promoted_to_core
test_trigger_origin_not_inferred_from_historical_similarity
test_assistant_interpretation_not_promoted_to_user_fact
test_trigger_profile_is_user_scoped
test_cross_case_trigger_contamination_blocked
test_cross_user_trigger_contamination_blocked
test_trigger_match_does_not_create_investigative_task
test_high_trigger_overlap_can_coexist_with_real_signal
test_oracle_attacks_both_trauma_dismissal_and_threat_certainty

==================================================
13. IMPORTANT RAW-DATA RULE
==================================================

Preserve raw calibration answers exactly.

Round 1 was originally presented as 0-4, but the user spontaneously used 5 for several items.
Do not silently clamp those values.
Store:
- declared scale
- raw score
- parser anomaly / out-of-range flag
- later clarification if any

Round 2 explicitly used 0-5.

This is a useful system requirement:
the user's raw answer is evidence.
Normalization is a derived transformation and must not overwrite it.

==================================================
14. DEFINITION OF DONE
==================================================

This is complete only when:

1. The old 7-trigger string matcher is no longer the primary mechanism.
2. Structured personal trigger families exist with provenance.
3. Matched-pair calibration works.
4. Current cases can be assessed against personal trigger structure.
5. Trigger overlap is shown separately from signal reality and causal confidence.
6. Oracle attacks both trauma-dismissal and trigger-denial errors.
7. Trigger matches never discount evidence.
8. Raw calibration data is preserved.
9. Existing legacy triggers migrate safely.
10. All regression tests pass.
11. Full repo test suite passes.
12. No UI language implies "PTSD artifact = false concern."

Before implementation:
Run an ORACLE review on this design and identify:
- ways the trigger engine could become a dismissal machine
- ways it could reinforce paranoia
- ways matched-pair inference could overfit
- ways historical case similarity could contaminate current evidence
- privacy failures
- cross-case contamination
- unsafe use in abuse/coercion contexts

Then implement only after resolving blocking findings.
