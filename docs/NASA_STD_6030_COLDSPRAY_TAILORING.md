# NASA-STD-6030 Cold Spray Tailoring Assessment — PROVISIONAL

> **PROVISIONAL — NOT A COMPLIANCE DETERMINATION.** Every disposition below
> is a draft engineering position generated from the ORACLE
> `nasa_std_6030_rulepack` (115 AMRs extracted from the approved 2021-04-21
> standard) and requires: (1) review against the full standard text —
> the pack extracts shall statements, not the referenced Tables 2–21;
> (2) M&P review and approval by Dr. Wilde; (3) formal tailoring
> approval per **AMR 1** with Boeing concurrence and NASA M&P / delegated
> Technical Authority concurrence. Nothing here is releasable to Boeing
> until all three have happened.

**Status:** Draft for M&P review
**Author:** Dr. Joseph Wilde / Claude (Beth)
**Date:** 2026-07-16
**Trigger:** Boeing flow-down of NASA-STD-6030 to BoundState
**Source pack:** `oracle/builtin_packs/nasa_std_6030_rulepack.json` (115 AMRs, pack validates, bootstrap-registered)
**Companion workflow:** §5 — using ORACLE to assess "do we meet the intent"

---

## 1. Engineering posture

NASA-STD-6030's technical basis is melt-based AM (it grew out of
MSFC-STD-3716/3717 for laser powder bed fusion). Cold spray is solid-state:
powder particles accelerated supersonically bond through plastic deformation
— no melt pool, no solidification microstructure, no fusion porosity. The
correct posture is therefore **not** "6030 doesn't apply" and **not**
"comply blindly":

1. **Adopt the framework as-is.** Part classification, AMCP, QMP/PPP/QPP
   structure, witness testing, NDE coverage, statistical allowables, AMRR —
   all process-agnostic and adopted unchanged. This is ~73% of the standard.
2. **Substitute cold-spray physics where the text assumes melting.** KPV
   lists, defect taxonomy, restart criteria, in-situ monitoring, build-area
   concepts, feedstock reuse. Each substitution is a formal AMR-1 tailoring
   record with rationale. ~15% of the standard.
3. **Drop the polymer-specific block with rationale.** §6.11.5.x (AMR 83–96)
   is polymeric-material specific; BoundState cold spray is metallic. ~12%.

Two scope questions to settle **with Boeing before** dispositioning further
(they change which AMRs bite):

- **Structural deposition vs. repair.** 6030 governs AM *parts*. Cold spray
  used as dimensional restoration / repair on conventionally-made hardware
  is arguably a different contractual scope (AMR 22 territory, plus the
  repair specs Boeing flows separately). Get the intended scope in writing.
- **The companion-standard chain.** AMR 14 invokes NASA-STD-6033
  (equipment/facility control), AMR 63 invokes NASA-STD-6016 (MUA), AMR
  18/20 invoke NASA-STD-5009, AMR 15 invokes NASA-STD-5019. Confirm which
  of these Boeing has also flowed, and in what tailored form.

---

## 2. Disposition summary

| Disposition | Count | Meaning |
|---|---|---|
| **AS-IS** | 84 | Applies unchanged; cold-spray-specific content lands inside the documents the AMR already requires (QMP, PPP, MPS, AMCP) |
| **MOD** | 17 | Applies with a documented cold-spray modification (formal AMR-1 tailoring record) |
| **N/A-MAT** | 14 | Not applicable by material class (§6.11.5.x polymeric block) — retained with rationale, reinstated if polymer CS is ever used |

Engineering-attention flags within AS-IS (not tailorings — hard problems):
AMR 17/18 (NDE detectability), AMR 45 (HIP), AMR 69 (anisotropy), AMR 70
(no data borrowing), AMR 80 (fracture toughness). Detail in §4.

---

## 3. Per-AMR dispositions

### §4 — Program requirements (AMR 1–35)

| AMR | Disposition | Basis |
|---|---|---|
| 1 | AS-IS | The tailoring governance itself. This document is the input; approvals route through Boeing + NASA M&P per the flow-down. |
| 2 | AS-IS | AMCP required. The per-AMR conformance means for cold spray documented there, from this assessment. |
| 3 | AS-IS | AMCP-cited documents under QMS configuration control. |
| 4 | AS-IS | Flow-down to subtiers: powder suppliers, heat treat, HIP, NDE houses. |
| 5–6 | AS-IS | Classification is consequence-of-failure based — process-agnostic. |
| 7–11 | AS-IS | Class prohibitions (no polymeric Class A, no fasteners/printed threads) apply equally to CS deposits. Exempt/Class C criteria unchanged. |
| 12 | MOD | Secondary classification: structural-demand tables apply as-is; Table 4 *AM risk* criteria are melt-AM flavored — assess CS risk drivers (inter-particle bond quality, through-thickness anisotropy, substrate-interface integrity) against Table 4 intent and document the mapping. |
| 13 | AS-IS | AS9100 (or approved alternate) QMS. *Company-maturity gap check — §4.* |
| 14 | MOD | EFCP per NASA-STD-6033, which is written around melt-AM equipment. Map CS equipment (gas supply/heater, nozzle wear tracking, powder feeder, robot calibration) to 6033 control categories; confirm 6033 flow-down form with Boeing. |
| 15 | AS-IS | Fracture control per NASA-STD-5019 with 6030's limitations. |
| 16 | AS-IS | Unplanned interruption = nonconformance. CS interruptions are physically benign (no melt pool), but the record-keeping obligation stands. |
| 17–18 | AS-IS ⚠ | Class A quantitative NDE, full coverage, Special NDE per 5009. **Flag:** verifiable detection of critical initial flaw sizes in CS deposits (tight planar inter-particle debonds) is a known hard problem — see §4. |
| 19–20 | AS-IS | Class B NDE per 5009. |
| 21 | MOD | In-situ monitoring qualification clause adopted as-is, but the *technologies* differ: melt-pool monitoring has no CS meaning; CS analogs are particle velocimetry, gas-parameter telemetry, deposition profilometry — qualified under the same clause before use in acceptance. |
| 22 | AS-IS | Repair/rework provisions. **Scope note:** where cold spray *is* the repair process applied to non-AM hardware, governing scope must be agreed with Boeing (§1). |
| 23–24 | MOD | Witness specimens "integral to the build" → co-deposited companion coupons sprayed in the same run, same feedstock lot, same post-processing. Metals Tables 5/7 quantities adopted unchanged. |
| 25 | MOD | Continuous-build SPC eligibility adopted; machine-qualification criteria reference 6033 → CS equipment equivalents per AMR 14 mapping. |
| 26 | MOD | Serialization/traceability as-is; "location on the build area/platform" → deposition sequence / toolpath segment / substrate position. |
| 27–29 | AS-IS | Digital thread: cryptographic file fingerprinting, model integrity, build-file change control — process-agnostic. |
| 30–35 | AS-IS | Production engineering record, preproduction article, proof test, qualification test program, acceptance data / CoC — unchanged. |

### §5 — Qualified Material Process (AMR 36–60)

| AMR | Disposition | Basis |
|---|---|---|
| 36–37 | AS-IS | One QMP per unique control-category combination, under configuration control. CS categories: feedstock spec, gas/nozzle/motion build-process controls, post-processing. |
| 38 | AS-IS | Virgin powder feedstock controls (Table 9) apply — CS is powder-fed. CS-critical attributes (morphology, oxygen content, size distribution) are levied *within* the feedstock spec the AMR already requires. |
| 39 | MOD | Feedstock reuse protocol: proposed compliant implementation is **prohibition** — overspray/recaptured powder is excluded from structural CS (deformed, oxidized particles degrade bonding). A documented prohibition satisfies the protocol requirement trivially. |
| 40 | AS-IS | KPV list — this is where CS process physics lives: gas type/pressure/temperature, nozzle geometry + wear limits, standoff, spray angle, traverse speed, powder feed rate, particle-velocity window, substrate prep and temperature, carrier-gas dew point. |
| 41 | MOD | Restart criteria: no melt-pool re-establishment; CS restart interface = surface condition verification + first-pass bond quality at the restart boundary, defined in the QMP. |
| 42–44 | AS-IS | Post-processing definition, AMS2750 pyrometry, variation qualification by equivalence. Thermal post-processing is *central* to CS (ductility recovery from the cold-worked state). |
| 45 | AS-IS ⚠ | HIP required for metallic Class A/B1/B2. Default position: **comply** — HIP diffusion-bonds particle boundaries and closes inter-particle voids in CS. Any alternate thermal treatment is a formal AMR-1 tailoring needing equivalence data — see §4. |
| 46–47 | AS-IS | Customized material process identification; QMP-A/B/C qualification ladder. |
| 48 | MOD | Sub-QMP commonality: "same make/model of printer head hardware" → same nozzle model, gun, feeder, and motion configuration. |
| 49 | AS-IS | Standardized qualification build set — CS standardized deposit geometries. |
| 50 | MOD | "Multiple energy sources" has no CS meaning; nearest equivalent adopted: multiple spray guns/nozzles on one machine qualify independently. |
| 51–52 | MOD | Metallographic defect-freedom: magnification, area (≥6 cm²), and cross-section protocol adopted unchanged; the *defect taxonomy* is substituted — inter-particle debonds, oxide stringers/inclusions, inter-pass porosity, substrate-interface delamination replace lack-of-fusion and keyhole porosity. |
| 53–54 | AS-IS | Controlled microstructural evolution, as-built → final: for CS that is deformed/work-hardened → recovered/recrystallized through heat treat; acceptance criteria documented per state. |
| 55 | MOD | Reference-part locations "center / edge of build area" → CS process-sensitive locations: standoff extremes, spray-angle extremes, thin-to-thick transitions. |
| 56–60 | AS-IS | Surface texture measures (as-sprayed), mechanical property quantities (metals Tables 13–16), QMP qualification records and closure. |

### §6 — Material Property Suite (AMR 61–96)

| AMR | Disposition | Basis |
|---|---|---|
| 61–62 | AS-IS | MPS for Class A/B; Class C typical-basis properties via MUA or PPP. |
| 63 | AS-IS | MUA per NASA-STD-6016 — routes through the existing MIRA/MUA machinery. Confirm 6016 flow-down form (§1). |
| 64 | AS-IS | Characterization builds under a QMP with Class-B1-equivalent witness. |
| 65 | AS-IS | Lot-mature vs lot-provisional allowables per Table 18 metal lot counts. |
| 66 | MOD | Feedstock-reuse limits in the MPS: with reuse prohibited (AMR 39), satisfied by documented prohibition. |
| 67–68 | AS-IS | Influence-factor identification and design values. CS factor set: standoff, angle, substrate temperature, nozzle wear state, gas dew point, deposit thickness. |
| 69 | AS-IS ⚠ | Anisotropy support in the MPS. **Flag:** CS anisotropy is severe (bond-normal/through-thickness weakness); a bounding isotropic assumption is unlikely to be defensible — plan for orientation-specific allowables. §4. |
| 70 | AS-IS ⚠ | External data must come from a "fundamentally the same" process. **This cuts both ways:** no borrowing PBF/DED data for CS — and no borrowing conventional thermal-spray coating data either. CS allowables are built from CS data. §4. |
| 71–72 | AS-IS | PCRDs established and reevaluated with incoming witness data. |
| 73–76 | AS-IS | Allowables per §6.11, configuration-controlled, influence-factor statistics, Table 21 minimum CoV. |
| 77–78 | AS-IS | Metallic tension (E8) and secondary-property allowables at 99/95. |
| 79 | AS-IS | Fatigue allowables. CS note: fatigue is dominated by inter-particle bond quality and surface condition — captured as influence factors, not tailoring. |
| 80 | AS-IS ⚠ | Fracture toughness / FCGR in worst-case orientation. **Flag:** as-sprayed CS toughness is very low; properties must represent the final (post-HIP/HT) condition, and worst-case orientation for CS is bond-normal. §4. |
| 81–82 | AS-IS | Creep/stress-rupture where required; joined-AM-component properties. |
| 83–96 | N/A-MAT | §6.11.5.x is the polymeric AM material block (Tg, moisture, flexural, polymer joining, etc.). Not applicable to metallic cold spray; reinstated automatically if any polymer CS is ever proposed. **Intent note on AMR 84:** its <3% elongation notch-sensitivity screen is worth *voluntarily* applying to any as-sprayed-condition use, where CS elongation can be below 3%. |

### §7–8 — Part Production Plan, AMRR, QPP (AMR 97–115)

| AMR | Disposition | Basis |
|---|---|---|
| 97–101 | AS-IS | PPP per part; general info; classification rationale; integrated structural integrity rationale; production-step summary. |
| 102 | MOD | PPP witness description: layout "in the build volume" → co-deposited coupon placement per AMR 23/24 translation. |
| 103 | MOD | Planned interruptions: "allowable build height range(s)" → deposit thickness / pass-count checkpoints with restart-interface evaluation per AMR 41. |
| 104–106 | AS-IS | Process-sensitive post-build controls; preproduction article; EIDP acceptance list. |
| 107–108 | AS-IS | PPP revision triggers; new preproduction article on QMP change. |
| 109–111 | AS-IS | AM Readiness Review conduct and documentation. |
| 112–115 | AS-IS | QPP establishment, change/requalification methodology, traceable production record, digital thread. |

---

## 4. The hard problems (gaps needing data or decisions, not paperwork)

1. **NDE detectability in CS deposits (AMR 17/18).** Tight planar
   inter-particle debonds and substrate-interface delaminations are
   unfavorable for conventional UT/RT. Class A work needs a demonstrated
   Special-NDE capability (likely CT + surface methods + POD study) before
   conformance can be claimed. This is the single most likely
   long-lead item.
2. **HIP decision (AMR 45).** Default: comply. If process economics or part
   geometry drive an alternate thermal treatment, that is a formal tailoring
   requiring material-equivalence data — start the trade study early, not at
   AMRR.
3. **Allowables from scratch (AMR 70 + 77–80).** No borrowing from PBF, DED,
   or thermal-spray datasets. Budget the full lot-count program of Tables
   13–18 on CS material in the final heat-treated condition, orientation-
   specific per AMR 69.
4. **6033 mapping (AMR 14).** Equipment/facility control plan written for CS
   equipment against a standard drafted for melt machines — a documented
   category mapping, agreed with Boeing.
5. **QMS status (AMR 13).** AS9100 (or approved-alternate) certification is
   a company-maturity item that gates everything above it.
6. **Scope agreement with Boeing (§1).** Structural deposition vs. repair,
   part classes in scope, and the companion-standard flow-down chain.

---

## 5. Using ORACLE to answer "do we meet the intent"

The pack is live: `nasa_std_6030_rulepack` (115 AMRs) loads and validates
(bootstrap tests green). The intent assessment is a review run, executed
where vendor keys live:

1. **Review this tailoring first** — the ensemble adversarially critiques
   the tailoring against the pack it was derived from:
   `oracle review docs/NASA_STD_6030_COLDSPRAY_TAILORING.md --packs nasa_std_6030`
2. **Then review our own documents** against the pack, one at a time, as
   they exist or get drafted: AMCP draft, CS process specification / QMP
   drafts, quality manual. Each finding is an intent gap with a citation.
3. **Assemble the compliance matrix** from those findings: per AMR —
   *conforms / conforms-as-tailored (this document) / gap (owner, date)*.
   That matrix plus this tailoring record **is** the AMCP §conformance
   content Boeing reviews.
4. **Promotion gate as governance:** pack stays draft until promoted
   (`oracle promote-pack`), and this document stays PROVISIONAL until the
   AMR-1 approvals land.

What ORACLE cannot do: be the M&P authority. AMR 1 puts tailoring approval
with program management, NASA M&P, and the delegated Technical Authority —
ORACLE drafts, checks, and cites; Dr. Wilde signs.
