# Oracle Adversarial Review — joseph_pom_dataset_v1.json

Reviewer: Oracle (per `docs/DUDE_POM_build_instruction.md` §14).
Scope: 180 compiled PomItems vs immutable source `joseph_operating_manual_v1.md` and contract `dude/pom/contracts.py`.
Objective: prove the "model of Joseph" will hurt Joseph; fix what would.

Automated pre-checks (all clean before manual attack):
- No item carries any PROHIBITED_USES member.
- No `assistant_interpretation` / `working_hypothesis` / `derived_summary` item carries `user_confirmed: true` (contract validator also enforces this).
- No unconfirmed-status item carries `confidence_band: supported`.
- All 23 `historical_case_context` items have `case_ref`, `temporal: historical`, and `allowed_uses == [case_retrieval]` exactly — no `uncertainty_widening` appears on any case item (the arguable case flagged in the brief does not occur; nothing to decide).

## Attacks

1. **"Grounding fact: Leo is safe." / "Grounding fact: Jim is safe."** → A current-state claim was frozen as a `durable` `user_stated_fact` (supported) carrying `safety_context`. Failure mode: a genuinely live safety question about a son gets pre-answered or suppressed by a stored "safe" fact from months ago — biography overriding a current observation. → **Fixed:** `allowed_uses` reduced to `grounding` only (safety_context stripped), `temporal: windowed`, metadata note requiring re-verification and forbidding use against a live safety question.

2. **"Working formulation for the ex-workplace ambiguity: Joseph is probably not imagining the change in others' behavior…"** (working_model, no case_ref) → This is the single most dangerous sentence in the dataset: it asserts a probability about external reality ("the change is real"), it is not fenced to the NASA/Amentum case, and retrieval-by-cue ("people are acting differently toward me") would surface it into any future case as quasi-corroboration that something external is really happening. → **Fixed:** `case_ref: nasa_amentum` added plus a why_note stating it may never be retrieved as support that a behavioral change or hostile cause is real in this or any other case; statement kept verbatim-close to source (the second half — "may be overestimating his ability to infer its cause" — is the protective half and must travel with it).

3. **Grounding phrase "Your PTSD may be accurately detecting that something changed while being unable to know what changed."** → Direction-2 hazard (§14): surfaced next to a live suspicion, "accurately detecting" reads as validation of the suspicion. Status was already correctly `working_hypothesis` with grounding/uncertainty_widening only. → **Fixed:** both-directions guard added in metadata: the phrase asserts signal-without-content and may never be surfaced as validation of any specific current suspicion.

4. **Costco dual-national item** → Blend of a user quote and assistant interpretive instruction ("interpret this as his relief at leaving clearance-sensitive professional life…") marked `user_stated_fact` + `user_confirmed: true` — an assistant reading promoted to confirmed user fact. → **Fixed:** reworded to attribute the quote to Joseph and the reading to the source; reclassified `derived_summary`, `plausible`, `user_confirmed` removed.

5. **IQ-145-revision item ("…Joseph actively supplies deflationary evidence against flattering estimates")** → One reported episode editorialized into a present-tense standing pattern; a pattern-is-active statement is exactly what cue-based retrieval smuggles as corroboration ("he self-deflates, so his self-report is reliable"). → **Fixed:** softened to the single episode ("in that episode Joseph himself supplied the deflationary evidence…").

6. **Troy/Jav calibration item ("this distinction is real evidence about his formal mathematical ability")** → "Is real evidence" wording inside a confirmed `user_stated_fact` creates evidence-vocabulary inside the POM. Scope is internal calibration, but the wording invites evidentiary reuse. → **Fixed:** reworded — calibration context only, "not an input to any external-world hypothesis"; the user-stated facts (500-level courses, calculus three times) retained verbatim.

7. **Dr. Chem item "Character evidence: Joseph uses technology to make consequences survivable…"** → Same defect: assistant interpretation self-labelled as "evidence". → **Fixed:** relabelled "Interpretation (not evidence for any external hypothesis):". Status was already `assistant_interpretation`/plausible.

8. **Workplace/MIRA working models missing case anchors** — "The correct model of Joseph's workplace history is real structural vulnerability plus PTSD amplification" (→ `case_ref: nasa_amentum`), "Joseph may not have built MIRA to become indispensable; he may have built it because he was already trapped" (→ `case_ref: mira`), "MIRA must not be reduced to a trauma response…" (→ `case_ref: mira`). Defect: NASA/MIRA-derived material floating without case anchor, retrievable by cue into unrelated cases. Categories stay `working_model` (they model Joseph, not the case) and uses stay uncertainty/communication/grounding — no evidence capability. → **Fixed:** case_refs added.

9. **Tawyna-letter items missing case anchors** — the standing no-send position (decision_preference, windowed) and the "skinny boy from Flint asking a witness" interpretation (trigger_pattern). Both are NASA/Amentum-situation material without `case_ref`. → **Fixed:** `case_ref: nasa_amentum` on both; window note added to the no-send item ("windowed without valid_to").

10. **All 11 `windowed` items lacked `valid_to` and any metadata window note** (SpaceX interview ×4, Low-Fi/Costco consideration, pension step-down, financial bridge conclusion, Jim's target bargain, Leo's Dr. Chem debt work-off, Slovak citizenship packet, Tawyna letter position). Failure mode: stale becomes current — DUDE asserts a long-dead interview or an expired bargain as live fact. → **Fixed:** explicit `window_note` metadata on every windowed item requiring currency re-verification (per brief: windowed-without-valid_to acceptable only if the window is noted).

11. **Pension step-down item ("around July next year")** → Relative date anchored to unknown source-writing time; retrieved later it silently shifts the step-down year (it may already be in the past). → **Fixed:** additional `relative_date_note` requiring resolution to an absolute date from connected Finances before bridge-planning use. Financial snapshots themselves were already correctly `historical` with `allowed_uses: []` — no change needed there (verified: retirement pool, mortgage, Wells Fargo, pension amount, SSA figures, burn targets, car obligations all excluded from operational retrieval).

12. **Stale ages: "Leo turns 19 on 8/14…" and "Jim is 16 and graduates high school at 16"** marked durable → age is source-year-relative. → **Fixed:** metadata age notes (birthday durable, age not; recompute at retrieval).

13. **safety_context sprayed across 12 family biographical items** (Leo's birthday/ACT/Miata, Jim's age/bargain, CrossFit, house layout, magic-board-adjacent accident items, Chrissy-is-wife, "no fucking way am I leaving my boys"). Failure mode: over-retrieval — a car-payment detail surfaces into a safety analysis because it carries the safety use; every extra use is an extra retrieval door into biography. → **Fixed:** safety_context stripped from all 12; retained only on "Joseph's deepest mission is protecting Leo and Jim" and the "us vs world leaking into the boys" caution, which are genuinely safety-relevant.

14. **Reputational third-party case items at `sensitivity: normal`** — 13 items naming Herald (×5 incl. smear hypothesis and "weak middle manager" characterization), Tawyna (×3 incl. hug/genius/LinkedIn behavior), Vann, JJ/Wooley/Burlingame, Bennie (×2). These carry allegations and characterizations of named real people; leaking them is reputational and legal exposure for Joseph. → **Fixed:** all set `sensitivity: high` (uses remain `case_retrieval` only).

15. **Fran's §27 character assessments at `sensitivity: normal`** ("sometimes arrogant… deeply wounded… vulnerable to brilliant overinterpretation") → intimate character material with normal sensitivity is an over-retrieval hazard. Statuses were already correctly `assistant_interpretation`/plausible/unconfirmed with communication_adaptation only. → **Fixed:** all 3 set `sensitivity: high`.

16. **Herald "shiny objects" characterization marked `user_reported_event` + `user_confirmed`** → attack considered: is this an assistant motive-attribution promoted to fact? **No change needed:** the statement reports *Joseph's* characterization and says so explicitly ("this is Joseph's characterization"); the event being recorded is his stated view, fenced to case_retrieval. Same verdict for Tawyna behavior list, Vann "lit the fuse" (attributed as Joseph's framing), Bennie non-reply (records only the non-reply and forbids the "toxic" conversion), and JJ/Wooley "responded coldly" (hedged: "cause remains unknown").

17. **Tawyna compartmentalization and Chrissy "Joe is coming home" motive attributions** → attack considered: third-party mental-state inference as fact. **No change needed:** both are `assistant_interpretation`, band plausible, unconfirmed; the Chrissy item explicitly states "her actual mental state is not established"; Tawyna item is fenced to case_retrieval on the nasa_amentum case and states "not proof of hostility".

18. **"He can be wrong brilliantly" / "conscripted problem-solving system" / silence-trigger structure items** → attack considered: trauma-as-discounting (direction 1). **No change needed:** these carry only `uncertainty_widening` / `communication_adaptation` / `trigger_context` / `grounding` — the sanctioned non-evidence channels; none can lower the weight of a current observation under the policy vocabulary, and the silence item's statement itself forbids the conspiracy use. `uncertainty_widening` widens both tails; it is not discounting.

19. **"The strongest evidence of Joseph's goodness…" (§28)** → "evidence" wording, but the object is Joseph's own character (internal), status `assistant_interpretation`, uses grounding/relationship_context. **No change needed** — flagged here for the record; it cannot reach an external hypothesis through any allowed use.

20. **Childhood trauma items (Bill, snow, scams, drugs, Norm, extortion)** → attack considered: over-retrieval of cue-rich trauma into unrelated cases. **No change needed:** all are `sensitivity: high` with uses limited to trigger_context/communication_adaptation/uncertainty_widening/grounding — the §4 example policy for PTSD history exactly; that is their designed function.

## Both-directions check (§14, explicit)

- **Direction 1 — "Joseph has PTSD, therefore his threat perception is probably wrong":** No item encodes this in statement wording, allowed_uses, or confidence bands. PTSD/trauma items carry only trigger_context/communication_adaptation/uncertainty_widening/grounding; `discount_current_observation` and both `infer_current_threat_*` names are absent everywhere; no statement says his perception is unreliable — the strongest formulations ("wrong brilliantly", "coherence is not proof") license uncertainty widening only and are derived/interpretation status, plausible band.
- **Direction 2 — "Joseph has accurately detected institutional danger before, therefore his current suspicion is probably right":** No item asserts prior accurate threat detection as a validator. The two items that could be bent that way were hardened: the "probably not imagining the change" formulation (attack 2: case_ref fenced + never-retrievable-as-support note) and the "PTSD may be accurately detecting that something changed" grounding phrase (attack 3: signal-without-content guard). The real structural events (predecessor sabotage, Herald blocking, Amentum back-down) are all historical_case_context, case_retrieval-only, so they cannot corroborate a new case; the "forced out because of labor-replacement AI" causal claim is `working_hypothesis`, unresolved band, explicitly "not independently established".
- Verdict: **both directions are structurally blocked** — by the use vocabulary (no evidence class exists), by statement wording after fixes, and by bands (no unconfirmed item exceeds plausible).

## Residual risks

1. **Notes are metadata, not machine policy.** The both-directions guards on attacks 2–3 and the window notes are `metadata` strings; nothing in `PomItem` executes them. The policy engine / retrieval layer must (a) treat `windowed` + no `valid_to` as expired-until-reverified, (b) enforce case_ref scoping for `case_retrieval`, and (c) surface why_notes with the item. Import-blocking tests exist in the §16 list; they must cover metadata-noted items too.
2. **Grounding phrases are cue-rich by design** ("The boys are not barefoot in the snow", "Bill is dead"). Category + grounding-only use is the fence; if retrieval ever ranks by raw semantic similarity without the policy filter, these will surface into unrelated emotional contexts. Mitigated by architecture (§11), not by this dataset.
3. **"Joseph is in Huntsville"** remains a durable grounding fact; location can change. Low risk (grounding-only), left as-is deliberately.
4. **"The financial spreadsheets showed 'You can survive'"** (durable derived_summary, grounding/strategic) echoes a time-of-writing financial conclusion; the operational conclusion item itself is windowed+noted, and the finance decision_preference item forces a live Finances query, so the residual is the psychological framing only.
5. **Confidence "supported" on user-reported third-party events** (e.g. "Herald lost 3 of 5 people") means "supported as Joseph's report", not "independently established". The statements say "Joseph reports/says", but a consumer collapsing band into truth would over-trust. Consider a future band convention for reported-vs-established.
6. **Item 65's source-verbatim "probably not imagining"** was retained (softening further would rewrite the source's own protective formulation); its safety now depends on the case_ref fence and the retrieval layer honoring the why_note.

## Counts

- Items reviewed: 180. Items changed: **50**. Items deleted: 0.
- By defect class (an item may appear in more than one class):
  - stale-data-became-current (window/age/relative-date notes, Leo/Jim-safe re-windowing): **15**
  - over-retrieval / sensitivity upgrades (named third parties, Fran §27 assessments): **16**
  - over-broad allowed_uses (safety_context stripped): **12**
  - historical-case leak (missing case_ref added): **6**
  - biography-as-evidence (safety_context on stored "safe" facts): **2**
  - semantic-similarity-as-corroboration (pattern-asserting statement fenced): **1**
  - direction-2 validation hazard (guard note): **1**
  - assistant-interpretation-as-fact (Costco item downgraded): **1**
  - provenance/editorializing (statements softened): **3**
- Post-fix validation: `180 items OK` (`PomItem.model_validate` over the full array).
