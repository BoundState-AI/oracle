#!/usr/bin/env python3
"""
Module: dude.triggers.seed
Purpose: Import the local, git-excluded calibration source into the
         TriggerStore (trigger spec v1 §3–§4/§13, custody per v1.1 R6).

Split of responsibilities, by design:
  - Family SHAPES (slugs, labels, de-identified descriptions, features,
    pre-filter cues, statuses) are declared here — they are already
    public in the redacted spec.
  - RAW calibration material (scores, verbatim response lines) is parsed
    from the git-excluded local source at import time and lands ONLY in
    calibration response records. Family labels/descriptions carry no
    real-world anchors (R6a; machine-checked in the contract).

Raw-data rules (§13): round 1 was declared 0-4 and the user spontaneously
used 5 on several items — those are preserved verbatim, stamped
out_of_range, marked for re-ask, and never counted at face value. Round 2
was declared 0-5. Statuses seed at the Phase-1 cap: sources marked
strongly_supported seed as self_report_supported (R4), §4 low-support
candidates seed as candidate_with_low_support and are never promoted by
narrative alone.

Import is idempotent by family slug.

Safety Critical: False
Psychologically Critical: True — this file decides what the system
believes about the user's calibration; a parsing shortcut here silently
rewrites his answers.

Never-suppress-error: a missing source file or an unmatched evidence
line raises SeedError; nothing imports partially-silently.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from dude.pom.contracts import EpistemicStatus
from dude.triggers.contracts import (
    DEFAULT_USER_ID,
    CalibrationDimension,
    CalibrationPair,
    CalibrationPrompt,
    EvidenceSourceType,
    EvidenceStrength,
    PairContrastResult,
    PersonalTriggerProfile,
    SupportDirection,
    TriggerCalibrationResponse,
    TriggerEvidence,
    TriggerFamily,
    TriggerFamilyStatus,
    TriggerFeature,
)
from dude.triggers.store import TriggerStore

LOGGER = logging.getLogger("dude.triggers.seed")

LOCAL_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "pom"
    / "sources"
    / "local"
    / "calibration_source_v1_unredacted.md"
)

# A pair contrast supports a latent mechanism only when the effective
# scores differ by at least this much (v1 §2 — never averaged blindly).
CONTRAST_SUPPORT_DELTA = 2

_ROUND_SCALES = {"round_1": (0, 4), "round_2": (0, 5)}


class SeedError(Exception):
    """The local source is missing or unparseable. Refuse the import."""


@dataclass(frozen=True)
class _Feature:
    slug: str
    ftype: str  # FeatureType value
    prov: str  # ProvenanceClass value
    desc: str


@dataclass(frozen=True)
class _Prompt:
    slug: str
    text: str
    marker: str  # unique substring of the source evidence line
    negative_control: bool = False
    feature_slug: str | None = None


@dataclass(frozen=True)
class _Pair:
    slug: str
    dimension: CalibrationDimension
    high_prompt: str
    low_prompt: str


@dataclass(frozen=True)
class _Family:
    slug: str
    label: str
    description: str
    status: TriggerFamilyStatus
    session: str  # calibration round -> declared scale
    cues: tuple[str, ...]
    features: tuple[_Feature, ...] = ()
    prompts: tuple[_Prompt, ...] = ()
    pairs: tuple[_Pair, ...] = ()
    letter: str | None = None  # §3 section letter; None -> §4 chunk
    support: SupportDirection = SupportDirection.SUPPORTS
    strength: EvidenceStrength = EvidenceStrength.MODERATE


def _f(slug: str, ftype: str, prov: str, desc: str) -> _Feature:
    return _Feature(slug, ftype, prov, desc)


_IV = "institutional_verifiable"
_IP = "interpersonal_performed"
_SRS = TriggerFamilyStatus.SELF_REPORT_SUPPORTED
_CLS = TriggerFamilyStatus.CANDIDATE_WITH_LOW_SUPPORT

CORE_FAMILY_DEFS: tuple[_Family, ...] = (
    _Family(
        slug="consequential_false_motive_attribution",
        label="Consequential false motive attribution",
        description=(
            "A person or institution with meaningful power assigns the user "
            "a harmful motive the user does not recognize as their own, and "
            "that interpretation can materially affect the user's life. Not "
            "generic being-misunderstood."
        ),
        status=_SRS,
        session="round_1",
        cues=("motive", "accus", "intent", "claims i", "says i wanted"),
        features=(
            _f("attributed_motive", "required", _IP, "A motive is assigned to the user."),
            _f("user_disputes_motive", "required", _IV, "The user does not recognize the motive as their own."),
            _f("power_asymmetry", "amplifier", _IV, "The attributor holds meaningful power over the user."),
            _f("employment_consequence", "amplifier", _IV, "The interpretation can affect employment."),
            _f("institutional_consequence", "amplifier", _IV, "An institution can act on the interpretation."),
            _f("no_meaningful_appeal", "amplifier", _IV, "No meaningful appeal exists."),
            _f("operational_interpretation", "amplifier", _IV, "The interpretation can be made operational."),
            _f("no_real_power", "reducer", _IV, "The attributor has no real power over the user's life."),
            _f("explanation_invited", "reducer", _IP, "The user is invited to explain their side."),
            _f("evidence_reviewed", "reducer", _IP, "The evidence is actually examined."),
            _f("transparent_appeal_path", "reducer", _IV, "A documented, transparent appeal path exists."),
        ),
        prompts=(
            _Prompt("a_powerful_accusation", "A powerful person accuses you of a motive you do not have.", "powerful person accuses you of a motive"),
            _Prompt("a_no_power", "The same false motive, attributed by someone with zero power over your life.", "zero power over life", negative_control=True),
            _Prompt("a_controls_employment", "The same false motive, attributed by someone who controls your employment.", "controls employment"),
        ),
        pairs=(
            _Pair("a_power_pair", CalibrationDimension.POWER, "a_controls_employment", "a_no_power"),
        ),
        letter="A",
        strength=EvidenceStrength.STRONG,
    ),
    _Family(
        slug="historical_event_used_as_fixed_identity",
        label="Historical event used as fixed identity",
        description=(
            "A bounded past event is used as proof of permanent present "
            "character or untrustworthiness. Discussion of the past is not "
            "identity foreclosure."
        ),
        status=_SRS,
        session="round_1",
        cues=("who you really are", "untrustworthy", "never change", "held against", "years ago"),
        features=(
            _f("bounded_past_event", "required", _IV, "A specific, bounded past event is invoked."),
            _f("identity_foreclosure", "required", _IP, "The event is used as proof of permanent present character."),
            _f("no_explanation_allowed", "amplifier", _IP, "No explanation or context is permitted."),
            _f("explanation_allowed", "reducer", _IP, "Explanation is allowed and heard."),
            _f("private_factual_discussion", "exclusion", _IP, "The event is raised privately as a factual concern only."),
        ),
        prompts=(
            _Prompt("b_old_mistake_identity", "An old mistake is used as evidence of who you are now.", "old mistake used as evidence"),
            _Prompt("b_private_factual", "A bounded past event is raised privately as a factual concern with explanation allowed.", "raised privately as factual concern", negative_control=True),
            _Prompt("b_identity_proof", "The same bounded past event is used as proof you are fundamentally untrustworthy now.", "fundamentally untrustworthy now"),
        ),
        pairs=(
            _Pair("b_identity_pair", CalibrationDimension.PAST_VS_IDENTITY, "b_identity_proof", "b_private_factual"),
        ),
        letter="B",
        strength=EvidenceStrength.STRONG,
    ),
    _Family(
        slug="unclear_scope_authority_intrusion",
        label="Unclear-scope authority intrusion",
        description=(
            "An authority enters, searches, inspects, accesses, or controls "
            "a personal or professional space while the limits of its "
            "authority are unclear to the user. Not generic privacy "
            "sensitivity: the major feature is the unclear boundary."
        ),
        status=_SRS,
        session="round_1",
        cues=("search", "warrant", "inspect", "went through", "confiscat"),
        features=(
            _f("authority_access_event", "required", _IV, "An authority accesses a personal or professional space."),
            _f("unclear_authority_boundary", "required", _IV, "The limits of the authority are unclear to the user."),
            _f("clear_scope", "reducer", _IV, "The scope of the authority is explicit and documented."),
            _f("counsel_present", "reducer", _IV, "Counsel or an advocate is present."),
            _f("legible_procedure", "reducer", _IV, "The procedure is legible and rule-bound."),
        ),
        prompts=(
            _Prompt("c_generic_search", "Someone searches your belongings, space, phone, files, or work.", "searches belongings/space/phone/files/work"),
            _Prompt("c_clear_scope", "A search under a valid warrant with clear scope and counsel present.", "valid warrant, clear scope, counsel present", negative_control=True),
            _Prompt("c_unclear_scope", "A search while you are unsure what they may legally touch.", "unsure what they may legally touch"),
        ),
        pairs=(
            _Pair("c_scope_pair", CalibrationDimension.SCOPE_CLARITY, "c_unclear_scope", "c_clear_scope"),
        ),
        letter="C",
        strength=EvidenceStrength.STRONG,
    ),
    _Family(
        slug="constrained_exit",
        label="Constrained exit",
        description=(
            "The user cannot leave physically or functionally without "
            "serious loss. Subtypes (physical, occupational, financial, "
            "institutional, relational) are not assumed equal."
        ),
        status=_SRS,
        session="round_1",
        cues=("can't leave", "cannot leave", "trapped", "stuck", "no way out"),
        features=(
            _f("exit_blocked_or_costly", "required", _IV, "Leaving is impossible or carries serious loss."),
            _f("physical_exit_constraint", "contextual", _IV, "The constraint is physical."),
            _f("occupational_exit_constraint", "contextual", _IV, "The constraint is occupational."),
            _f("financial_exit_constraint", "contextual", _IV, "The constraint is financial."),
            _f("institutional_exit_constraint", "contextual", _IV, "The constraint is institutional."),
            _f("relational_exit_constraint", "contextual", _IV, "The constraint is relational."),
            _f("clean_exit_available", "reducer", _IV, "A clean, low-cost exit exists."),
        ),
        prompts=(
            _Prompt("d_constrained", "You cannot leave without losing something important.", "cannot leave without losing something important"),
            _Prompt("d_trapped_trustworthy", "You are physically trapped, but with a trustworthy person.", "physically trapped with trustworthy person"),
            _Prompt("d_career_exit", "You are physically free to leave a meeting, but leaving could destroy your career.", "leaving could destroy career"),
        ),
        pairs=(
            _Pair("d_exit_pair", CalibrationDimension.EXIT_CONSTRAINT, "d_constrained", "d_trapped_trustworthy"),
        ),
        letter="D",
        strength=EvidenceStrength.STRONG,
    ),
    _Family(
        slug="arbitrary_power_without_legible_recourse",
        label="Arbitrary power without legible recourse",
        description=(
            "Another person or institution has discretionary control over "
            "an important outcome without clear rules, limits, "
            "accountability, or meaningful recourse. Authority itself is "
            "not the trigger; legible bounded authority may score zero."
        ),
        status=_SRS,
        session="round_1",
        cues=("arbitrar", "no explanation", "without explanation", "trust the process", "no appeal", "discretion"),
        features=(
            _f("discretionary_control", "required", _IV, "Another party has discretionary control over an important outcome."),
            _f("no_legible_recourse", "required", _IV, "No clear rules, limits, or meaningful recourse exist."),
            _f("opaque_process", "amplifier", _IV, "The process is unexplained or unexplainable."),
            _f("clear_rules", "reducer", _IV, "Clear rules and criteria are documented."),
            _f("direct_feedback", "reducer", _IP, "Direct feedback is actually given."),
            _f("appeal_path", "reducer", _IV, "A real appeal path exists."),
            _f("legible_bounded_authority", "exclusion", _IV, "The authority is legible and bounded."),
        ),
        prompts=(
            _Prompt("e_arbitrary_withhold", "You depend on someone who can arbitrarily withhold money, work, access, or permission.", "arbitrarily withhold money/work/access/permission"),
            _Prompt("e_clear_rules_boss", "A boss can fire you but gives clear rules, direct feedback, and an appeal path.", "clear rules/direct feedback/appeal path", negative_control=True),
            _Prompt("e_arbitrary_block", "A boss cannot fire you but can arbitrarily block your work without explanation.", "arbitrarily block work without explanation"),
            _Prompt("e_trust_process", "You are told to trust the process, without the process being explained.", "trust the process"),
        ),
        pairs=(
            _Pair("e_rules_pair", CalibrationDimension.RULES_LEGIBILITY, "e_arbitrary_withhold", "e_clear_rules_boss"),
        ),
        letter="E",
        strength=EvidenceStrength.STRONG,
    ),
    _Family(
        slug="dependent_in_danger",
        label="Dependent in danger",
        description=(
            "A child or dependent is in danger, being humiliated, falsely "
            "accused, harmed, or otherwise needs protection. Not reducible "
            "to helplessness: danger to the dependent is hot on its own, "
            "and blocked protective access amplifies it."
        ),
        status=_SRS,
        session="round_1",
        cues=("my son", "my daughter", "my child", "my kid", "my boy", "dependent"),
        features=(
            _f("dependent_at_risk", "required", _IV, "A child or dependent is in danger or needs protection."),
            _f("blocked_protective_access", "amplifier", _IV, "An authority controls whether the user can reach or protect the dependent."),
            _f("authority_humiliation", "amplifier", _IP, "The dependent is humiliated or falsely accused by an authority."),
        ),
        prompts=(
            _Prompt("f_unreachable", "Your dependent is unexpectedly unreachable.", "unexpectedly unreachable"),
            _Prompt("f_bullied", "Your dependent is bullied, humiliated, or falsely accused by an authority.", "bullied/humiliated/falsely accused by authority"),
            _Prompt("f_failing_parent", "You are accused of failing as a parent.", "accused of failing as father"),
            _Prompt("f_own_actions", "Your own actions may threaten your family's safety, home, or future.", "own actions may threaten family"),
            _Prompt("f_full_access", "Your child is in trouble; you have full access and a clear plan.", "full access and clear plan"),
            _Prompt("f_blocked_access", "Your child is in trouble and an authority controls whether you can reach or protect him.", "authority controls whether user can reach", feature_slug="blocked_protective_access"),
        ),
        pairs=(
            _Pair("f_access_pair", CalibrationDimension.PROTECTIVE_ACCESS, "f_blocked_access", "f_full_access"),
        ),
        letter="F",
        strength=EvidenceStrength.STRONG,
    ),
    _Family(
        slug="visibility_to_power",
        label="Visibility to power",
        description=(
            "The user becomes highly visible to powerful people or is "
            "singled out positively by them. Not generic fear of success: "
            "success while invisible scored cold in the matched comparison."
        ),
        status=_SRS,
        session="round_2",
        cues=("praise", "spotlight", "visib", "singled out", "recognition", "featured"),
        features=(
            _f("visibility_to_powerful_people", "required", _IV, "The user is highly visible to powerful people."),
            _f("singled_out_by_power", "amplifier", _IP, "A powerful person singles the user out positively."),
            _f("public_praise_by_power", "amplifier", _IP, "Praise from power is public."),
            _f("anonymous_success", "exclusion", _IV, "The success is real but anonymous or invisible."),
        ),
        prompts=(
            _Prompt("g_invisible_success", "You are highly successful but mostly invisible.", "highly successful but mostly invisible", negative_control=True),
            _Prompt("g_visible_praised", "You are highly visible and praised by powerful people.", "highly visible and praised by powerful people"),
            _Prompt("g_expecting_bad", "You are doing well and becoming visible, and you expect something bad to follow.", "expecting something bad to follow"),
            _Prompt("g_cannot_relax", "A good thing is happening but you cannot relax because you expect a reversal.", "unable to relax because reversal expected"),
        ),
        pairs=(
            _Pair("g_visibility_pair", CalibrationDimension.VISIBILITY, "g_visible_praised", "g_invisible_success"),
        ),
        letter="G",
    ),
    _Family(
        slug="consequential_suspended_outcome",
        label="Consequential suspended outcome",
        description=(
            "A meaningful outcome remains unresolved while another person "
            "or institution controls the timing. Waiting itself appears "
            "activating; a moving or opaque timeline amplifies it."
        ),
        status=_SRS,
        session="round_2",
        cues=("waiting", "still no date", "timeline", "delay", "pending", "moved the date"),
        features=(
            _f("unresolved_outcome_controlled_by_other", "required", _IV, "Another party controls when a meaningful outcome resolves."),
            _f("moving_or_opaque_timeline", "amplifier", _IV, "The timeline moves or is unexplained."),
            _f("explicit_rules_date_criteria", "reducer", _IV, "Explicit rules, a date, and criteria are documented."),
        ),
        prompts=(
            _Prompt("h_other_controls", "Another person controls whether your life changes.", "another person controls whether life changes"),
            _Prompt("h_moving_threat", "You are forced to repeatedly prepare for a moving threat.", "repeatedly prepare for moving threat"),
            _Prompt("h_fixed_wait", "A six-month wait with explicit rules, a date, and criteria.", "six-month wait with explicit rules"),
            _Prompt("h_moving_wait", "A six-week wait with moving dates and no explanation.", "six-week wait with moving dates"),
            _Prompt("h_ordinary_delay", "An ordinary repeated delay.", "ordinary repeated delay"),
        ),
        pairs=(
            _Pair("h_timeline_pair", CalibrationDimension.TIMELINE_OPACITY, "h_moving_wait", "h_fixed_wait"),
        ),
        letter="H",
    ),
    _Family(
        slug="loss_of_agency_over_created_work",
        label="Loss of agency over created work",
        description=(
            "The user loses attribution, control, access, or the ability "
            "to use work they created. Subdimensions (attribution, "
            "ownership, access, exclusion, control) are not collapsed."
        ),
        status=_SRS,
        session="round_2",
        cues=("credit", "my work", "my invention", "ownership", "locked out", "took over"),
        features=(
            _f("created_work_agency_loss", "required", _IV, "The user loses agency over work they created."),
            _f("attribution_loss", "contextual", _IV, "Credit is taken or withheld."),
            _f("ownership_loss", "contextual", _IV, "Ownership shifts away from the user."),
            _f("access_loss", "contextual", _IV, "The user loses access to the work."),
            _f("exclusion_from_use", "contextual", _IV, "The user can be excluded from using the work."),
            _f("control_loss", "contextual", _IV, "Another party gains control over the work."),
        ),
        prompts=(
            _Prompt("i_credit_taken", "Someone takes credit for your creation.", "takes credit for creation"),
            _Prompt("i_no_credit_retain_use", "Your invention is used without credit, but you retain use of it.", "used without credit but user retains use"),
            _Prompt("i_excluded", "Someone gains control and can exclude you from your own invention.", "can exclude user from invention"),
        ),
        letter="I",
    ),
    _Family(
        slug="psychiatric_or_character_delegitimization",
        label="Psychiatric or character delegitimization",
        description=(
            "A legitimate concern is dismissed through claims about "
            "instability, toxicity, dangerousness, or irrationality rather "
            "than evaluated on evidence. Intensity across wordings is "
            "inconsistent; that inconsistency is preserved, not averaged."
        ),
        status=_SRS,
        session="round_2",
        cues=("ptsd", "unstable", "toxic", "irrational", "paranoid", "overreact", "crazy", "hysterical"),
        features=(
            _f("concern_dismissed_via_label", "required", _IP, "The concern is answered with a label instead of evidence."),
            _f("refusal_to_examine_evidence", "amplifier", _IP, "Evidence is refused, not weighed."),
            _f("authority_source", "amplifier", _IV, "The dismissal comes from an authority."),
            _f("evidence_still_examined", "reducer", _IP, "The label is raised but the evidence is still examined."),
        ),
        prompts=(
            _Prompt("j_label_instead", "A legitimate concern is attributed to a diagnosis instead of being evaluated.", "attributed to PTSD instead of evaluated"),
            _Prompt("j_implied_unstable", "You are implied to be dangerous, toxic, or unstable without concrete examples.", "implied dangerous/toxic/unstable"),
            _Prompt("j_intensity_irrational", "Your intensity is treated as evidence of irrationality.", "intensity treated as evidence of irrationality"),
            _Prompt("j_label_but_examined", "A partner suggests the diagnosis may affect your urgency but still examines the evidence.", "still examines evidence"),
            _Prompt("j_authority_refuses", "An authority dismisses the concern with the label and refuses to look at evidence.", "refuses evidence"),
        ),
        letter="J",
    ),
)

# §4 low-support candidates: preserved, never deleted, never promoted by
# narrative alone. Their weak scores are the evidence AGAINST them.
LOW_SUPPORT_FAMILY_DEFS: tuple[_Family, ...] = (
    _Family(
        slug="ambiguous_abandonment",
        label="Ambiguous abandonment",
        description="A broad abandonment theory; weak in current self-report.",
        status=_CLS, session="round_2",
        cues=("disappeared", "stopped talking", "cut me off", "ghosted"),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
    _Family(
        slug="generic_silence",
        label="Generic silence",
        description="Silence or non-reply as a broad trigger theory; weak in current self-report.",
        status=_CLS, session="round_2",
        cues=("no reply", "went quiet", "radio silence", "stopped responding", "no response"),
        prompts=(
            _Prompt("ls_stops_replying", "An important person suddenly stops replying.", "suddenly stops replying"),
        ),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
    _Family(
        slug="hidden_channel_suspicion",
        label="Hidden-channel suspicion",
        description="The sense of being discussed somewhere inaccessible; weak in current self-report.",
        status=_CLS, session="round_2",
        cues=("behind the scenes", "backchannel", "back channel", "hidden channel"),
        prompts=(
            _Prompt("ls_discussed_inaccessible", "You sense people discuss you somewhere you cannot access.", "somewhere inaccessible"),
        ),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
    _Family(
        slug="generic_misunderstanding",
        label="Generic misunderstanding",
        description="Being misunderstood as a broad theory; the calibrated mechanism is narrower (see consequential_false_motive_attribution).",
        status=_CLS, session="round_2",
        cues=("misunderstood", "paraphras", "misquoted"),
        prompts=(
            _Prompt("ls_inaccurate_paraphrase", "Someone paraphrases you inaccurately.", "inaccurate paraphrase"),
        ),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
    _Family(
        slug="retaliation_for_leaving",
        label="Retaliation for leaving",
        description="Expecting retaliation after leaving; weak in current self-report.",
        status=_CLS, session="round_2",
        cues=("retaliat", "after i left", "because i quit"),
        prompts=(
            _Prompt("ls_leaving_retaliation", "You leave a job, relationship, or institution and expect retaliation.", "expecting retaliation"),
        ),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
    _Family(
        slug="relationship_rupture",
        label="Relationship rupture",
        description="Rupture of a relationship as a broad trigger theory; weak in current self-report.",
        status=_CLS, session="round_2",
        cues=("falling out", "rupture", "ended our"),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
    _Family(
        slug="public_embarrassment",
        label="Public embarrassment",
        description="Public misunderstanding or embarrassment; weak in current self-report.",
        status=_CLS, session="round_2",
        cues=("embarrass", "humiliated in public", "in front of everyone"),
        prompts=(
            _Prompt("ls_public_misunderstanding", "You are misunderstood publicly.", "public misunderstanding"),
        ),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
    _Family(
        slug="truth_will_not_protect",
        label="Truth will not protect",
        description="The theory that truth itself offers no protection; weak in current self-report.",
        status=_CLS, session="round_2",
        cues=("truth won't", "truth will not", "no one believes"),
        prompts=(
            _Prompt("ls_truth_no_protection", "You believe the truth itself may not protect you.", "truth itself may not protect"),
        ),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
    _Family(
        slug="consent_followed_by_consequence",
        label="Consent followed by consequence",
        description="Consenting without understanding consequences, or rules changing after action; weak in current self-report.",
        status=_CLS, session="round_2",
        cues=("i agreed", "consented", "signed off", "rules changed"),
        prompts=(
            _Prompt("ls_rules_change", "The rules change after you have already acted.", "rules change after action"),
            _Prompt("ls_consented_unknowing", "You consented without understanding the consequences.", "consented without understanding consequences"),
        ),
        support=SupportDirection.CONTRADICTS, strength=EvidenceStrength.WEAK,
    ),
)

ALL_FAMILY_DEFS: tuple[_Family, ...] = CORE_FAMILY_DEFS + LOW_SUPPORT_FAMILY_DEFS


@dataclass
class SeedReport:
    families: int = 0
    profiles: int = 0
    prompts: int = 0
    responses: int = 0
    pairs: int = 0
    contrasts: int = 0
    evidence: int = 0
    skipped_existing: list[str] = field(default_factory=list)


# --- source parsing -----------------------------------------------------------


def _read_source(path: Path) -> str:
    if not path.exists():
        raise SeedError(
            f"Local calibration source not found at {path}; the seed import "
            "refuses to fabricate calibration data (R6)."
        )
    return path.read_text(encoding="utf-8")


def _section3_chunks(text: str) -> dict[str, str]:
    """Split §3 into per-letter chunks. Fails loudly on a missing letter."""
    start = text.find("3. SEED THESE CURRENT PERSONAL CANDIDATES")
    end = text.find("4. PRESERVE LOW-SUPPORT")
    if start < 0 or end < 0:
        raise SeedError("Source is missing §3/§4 section headers.")
    section = text[start:end]
    headers = list(re.finditer(r"^([A-J])\.\s", section, flags=re.MULTILINE))
    chunks: dict[str, str] = {}
    for index, match in enumerate(headers):
        stop = headers[index + 1].start() if index + 1 < len(headers) else len(section)
        chunks[match.group(1)] = section[match.start() : stop]
    missing = [c for c in "ABCDEFGHIJ" if c not in chunks]
    if missing:
        raise SeedError(f"Source §3 is missing families: {missing}")
    return chunks


def _low_support_chunk(text: str) -> str:
    start = text.find("Examples of low scores:")
    end = text.find("Store these as:")
    if start < 0 or end < 0:
        raise SeedError("Source §4 low-score block not found.")
    return text[start:end]


def _parse_evidence_line(chunk: str, marker: str) -> tuple[str, int]:
    """Find the evidence bullet containing `marker` and return the
    verbatim line (raw answer, preserved exactly) and its raw score."""
    for line in chunk.splitlines():
        stripped = line.strip()
        if stripped.startswith("-") and marker in stripped and "=" in stripped:
            left, _, right = stripped.rpartition("=")
            try:
                return stripped.lstrip("- ").strip(), int(right.strip())
            except ValueError as exc:
                raise SeedError(f"Unparseable score in line {stripped!r}.") from exc
    raise SeedError(f"No evidence line matching {marker!r} in source chunk.")


# --- import ------------------------------------------------------------------


def import_seed(
    store: TriggerStore,
    user_id: str = DEFAULT_USER_ID,
    source_path: Path = LOCAL_SOURCE,
) -> SeedReport:
    """Parse the local source and import families A-J plus the §4
    low-support candidates. Idempotent by family slug."""
    text = _read_source(source_path)
    chunks = _section3_chunks(text)
    low_chunk = _low_support_chunk(text)
    existing = set(store.load().families_by_slug())
    report = SeedReport()
    for definition in ALL_FAMILY_DEFS:
        if definition.slug in existing:
            report.skipped_existing.append(definition.slug)
            continue
        chunk = chunks[definition.letter] if definition.letter else low_chunk
        _seed_family(store, definition, chunk, user_id, report)
    LOGGER.info(
        "Seed import: %d families, %d responses, skipped %s",
        report.families,
        report.responses,
        report.skipped_existing,
    )
    return report


def _seed_family(
    store: TriggerStore,
    definition: _Family,
    chunk: str,
    user_id: str,
    report: SeedReport,
) -> None:
    family = TriggerFamily(
        slug=definition.slug,
        label=definition.label,
        description=definition.description,
        features=[
            TriggerFeature(
                feature_slug=f.slug,
                description=f.desc,
                feature_type=f.ftype,
                provenance_class=f.prov,
            )
            for f in definition.features
        ],
        prefilter_cues=list(definition.cues),
    )
    store.append(family)
    report.families += 1
    store.append(_seed_profile(definition, family, user_id))
    report.profiles += 1
    responses = _seed_prompts(store, definition, family, chunk, user_id, report)
    _seed_pairs(store, definition, responses, report)
    store.append(
        TriggerEvidence(
            user_id=user_id,
            trigger_family_id=family.id,
            family_slug=family.slug,
            source_type=EvidenceSourceType.CALIBRATION_RESPONSE,
            epistemic_status=EpistemicStatus.USER_STATED_FACT,
            support_direction=definition.support,
            strength=definition.strength,
            source_reference="calibration rounds 1-2 (calibration stream)",
        )
    )
    report.evidence += 1


def _seed_profile(
    definition: _Family, family: TriggerFamily, user_id: str
) -> PersonalTriggerProfile:
    # R4 cap: source statuses of strongly_supported seed at the cap,
    # visibly. provisionally_supported is the renamed self_report tier.
    reason = (
        "Seeded from calibration source at the Phase-1 cap (R4): "
        "self_report_supported is the ceiling."
        if definition.status is _SRS
        else "Seeded as low-support candidate (§4): weak in current "
        "self-report; preserved, not promoted."
    )
    return PersonalTriggerProfile(
        user_id=user_id,
        trigger_family_id=family.id,
        family_slug=family.slug,
        status=definition.status,
        evidence_source_types=[EvidenceSourceType.CALIBRATION_RESPONSE],
        status_reason=reason,
        last_calibrated_at=family.created_at,
    )


def _seed_prompts(
    store: TriggerStore,
    definition: _Family,
    family: TriggerFamily,
    chunk: str,
    user_id: str,
    report: SeedReport,
) -> dict[str, TriggerCalibrationResponse]:
    scale_min, scale_max = _ROUND_SCALES[definition.session]
    responses: dict[str, TriggerCalibrationResponse] = {}
    for prompt_def in definition.prompts:
        raw_text, raw_score = _parse_evidence_line(chunk, prompt_def.marker)
        prompt = CalibrationPrompt(
            prompt_slug=prompt_def.slug,
            text=prompt_def.text,
            family_slug=family.slug,
            feature_slug=prompt_def.feature_slug,
            is_negative_control=prompt_def.negative_control,
        )
        store.append(prompt)
        report.prompts += 1
        response = TriggerCalibrationResponse(
            user_id=user_id,
            prompt_id=prompt.id,
            session_id=definition.session,
            raw_score=raw_score,
            declared_scale_min=scale_min,
            declared_scale_max=scale_max,
            raw_response_text=raw_text,
            clarification=(
                "Re-ask required: raw score exceeds the declared scale; "
                "preserved verbatim, never counted at face value (§13/R4)."
                if raw_score > scale_max or raw_score < scale_min
                else ""
            ),
            provenance=f"seed_import:{definition.session}",
        )
        store.append(response)
        report.responses += 1
        responses[prompt_def.slug] = response
    return responses


def _seed_pairs(
    store: TriggerStore,
    definition: _Family,
    responses: dict[str, TriggerCalibrationResponse],
    report: SeedReport,
) -> None:
    """Matched pairs + derived contrasts (v1 §2). A latent mechanism is
    inferred only when the effective contrast supports it, and only as a
    working hypothesis."""
    for pair_def in definition.pairs:
        high = responses[pair_def.high_prompt]
        low = responses[pair_def.low_prompt]
        pair = CalibrationPair(
            family_slug=definition.slug,
            dimension=pair_def.dimension,
            high_arm_prompt_id=high.prompt_id,
            low_arm_prompt_id=low.prompt_id,
        )
        store.append(pair)
        report.pairs += 1
        delta = high.effective_score() - low.effective_score()
        supported = delta >= CONTRAST_SUPPORT_DELTA
        store.append(
            PairContrastResult(
                pair_id=pair.id,
                family_slug=definition.slug,
                high_response_id=high.id,
                low_response_id=low.id,
                high_effective=high.effective_score(),
                low_effective=low.effective_score(),
                contrast_supported=supported,
                inferred_mechanism_slug=definition.slug if supported else None,
            )
        )
        report.contrasts += 1
