#!/usr/bin/env python3
"""
Module: dude.triggers.migrate
Purpose: Legacy TriggerPattern migration into structured families
         (trigger spec v1 §11, amended by v1.1 R9).

Every legacy trigger maps to a family and gets a LegacyTriggerLink with
superseded_by_family_id. Eight map onto seeded calibration families;
three (inactivity, unsolicited help, fatigue) have no calibrated family
and become NEW candidate families carrying their legacy cues. Nothing is
discarded: the legacy records stay in the root triggers stream, keep
matching whenever their family is NOT assessed on a case (R9 inertness
is per-case, not global), and their creation time and provenance are
preserved on the link and the migration evidence.

Legacy triggers migrate as CANDIDATE-tier support — never automatically
self_report_supported (v1 §11) — and legacy HISTORICAL matches are
audit-only: this module never converts a past TriggerMatch into
TriggerEvidence. The historically_accurate calibration tag carries onto
the family profile so ATTEND survives migration (R7).

Safety Critical: False
Psychologically Critical: True — a lossy migration here silently drops
patterns the user explicitly entrusted to the system.

Never-suppress-error: an unmappable legacy trigger raises MigrationError;
nothing is skipped silently.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import logging

from dude.data.enums import TriggerCalibration
from dude.data.triggers import TriggerPattern
from dude.pom.contracts import EpistemicStatus
from dude.store.jsonl import CaseStore
from dude.triggers.contracts import (
    EvidenceSourceType,
    EvidenceStrength,
    LegacyTriggerLink,
    PersonalTriggerProfile,
    SupportDirection,
    TriggerEvidence,
    TriggerFamily,
    TriggerFamilyStatus,
)
from dude.triggers.store import TriggerStore

LOGGER = logging.getLogger("dude.triggers.migrate")


class MigrationError(Exception):
    """A legacy trigger could not be migrated. Fail loudly, never skip."""


# Legacy name -> seeded family slug. WHY these mappings: each legacy
# trigger's cue set names the same mechanism a calibrated family narrowed
# to (or a §4 low-support candidate the calibration data demoted —
# migration must not silently re-promote what calibration scored low).
DEFAULT_LEGACY_FAMILY_MAP: dict[str, str] = {
    "Ambiguity from powerful people": "generic_silence",
    "Trusted people suddenly disappearing": "ambiguous_abandonment",
    "Someone rewriting my motives": "consequential_false_motive_attribution",
    "Hidden authority": "hidden_channel_suspicion",
    "Loss of control over my work": "loss_of_agency_over_created_work",
    "Institutional silence": "arbitrary_power_without_legible_recourse",
    "Being framed as the problem": "psychiatric_or_character_delegitimization",
    "Public praise or visibility": "visibility_to_power",
}

# Legacy triggers with no calibrated family become new candidate families
# (de-identified labels; raw user phrasing stays on the legacy record).
NEW_FAMILY_DEFS: dict[str, tuple[str, str, str]] = {
    "Inactivity as threat": (
        "inactivity_as_threat",
        "Inactivity as threat",
        "Enforced idleness or visible unproductivity reads as danger "
        "rather than rest.",
    ),
    "Being helped or cared for": (
        "unsolicited_help",
        "Unsolicited help",
        "Another person doing things on the user's behalf, unprompted, "
        "reads as a cost rather than care.",
    ),
    "Fatigue amplification": (
        "fatigue_amplification",
        "Fatigue amplification",
        "A somatic amplifier, not a situational pattern: under fatigue, "
        "certainty in BOTH directions is worth less than usual.",
    ),
}


def migrate_legacy(
    trigger_store: TriggerStore, case_store: CaseStore, user_id: str
) -> list[LegacyTriggerLink]:
    """Idempotent migration of every legacy TriggerPattern. Returns the
    links created in this call."""
    bundle = trigger_store.load()
    already = {link.legacy_trigger_id for link in bundle.legacy_links}
    by_slug = bundle.families_by_slug()
    created: list[LegacyTriggerLink] = []
    for legacy in case_store.load_triggers():
        if legacy.id in already:
            continue
        family = _family_for(trigger_store, legacy, by_slug, user_id)
        link = LegacyTriggerLink(
            legacy_trigger_id=legacy.id,
            legacy_name=legacy.name,
            superseded_by_family_id=family.id,
            superseded_by_family_slug=family.slug,
            legacy_recorded_at=legacy.recorded_at,
            note=f"Migrated from legacy pattern {legacy.name!r} (v1 §11).",
        )
        trigger_store.append(link)
        trigger_store.append(_migration_evidence(legacy, family, user_id))
        _carry_calibration_tag(trigger_store, legacy, family, user_id)
        created.append(link)
        LOGGER.info("Migrated legacy trigger %r -> %s", legacy.name, family.slug)
    return created


def _family_for(
    trigger_store: TriggerStore,
    legacy: TriggerPattern,
    by_slug: dict[str, TriggerFamily],
    user_id: str,
) -> TriggerFamily:
    slug = DEFAULT_LEGACY_FAMILY_MAP.get(legacy.name)
    if slug is not None:
        family = by_slug.get(slug)
        if family is None:
            raise MigrationError(
                f"Legacy trigger {legacy.name!r} maps to family {slug!r}, "
                "which is not seeded; run the seed import first."
            )
        return family
    definition = NEW_FAMILY_DEFS.get(legacy.name)
    if definition is None:
        raise MigrationError(
            f"Legacy trigger {legacy.name!r} has no family mapping; add one "
            "explicitly — nothing migrates silently."
        )
    new_slug, label, description = definition
    if new_slug in by_slug:
        return by_slug[new_slug]
    family = TriggerFamily(
        slug=new_slug,
        label=label,
        description=description,
        prefilter_cues=list(legacy.cues),
    )
    trigger_store.append(family)
    trigger_store.append(
        PersonalTriggerProfile(
            user_id=user_id,
            trigger_family_id=family.id,
            family_slug=family.slug,
            # v1 §11: never automatically strongly supported. Candidate
            # until the calibration lab earns more.
            status=TriggerFamilyStatus.CANDIDATE,
            calibration=legacy.calibration,
            evidence_source_types=[EvidenceSourceType.LEGACY_MANUAL_TRIGGER],
            status_reason="Migrated legacy trigger; candidate pending calibration.",
            first_observed_at=legacy.recorded_at,
        )
    )
    by_slug[new_slug] = family
    return family


def _migration_evidence(
    legacy: TriggerPattern, family: TriggerFamily, user_id: str
) -> TriggerEvidence:
    """One evidence record per legacy trigger, provenance preserved. The
    legacy trigger's historical MATCHES are deliberately not converted —
    they are audit-only (R9)."""
    return TriggerEvidence(
        user_id=user_id,
        trigger_family_id=family.id,
        family_slug=family.slug,
        source_type=EvidenceSourceType.LEGACY_MANUAL_TRIGGER,
        epistemic_status=(
            EpistemicStatus.USER_STATED_FACT
            if legacy.user_confirmed
            else EpistemicStatus.ASSISTANT_INTERPRETATION
        ),
        support_direction=SupportDirection.SUPPORTS,
        strength=EvidenceStrength.WEAK,
        source_reference=legacy.id,
        timestamp=legacy.recorded_at,
    )


def _carry_calibration_tag(
    trigger_store: TriggerStore,
    legacy: TriggerPattern,
    family: TriggerFamily,
    user_id: str,
) -> None:
    """R7: ATTEND survives — a historically_accurate legacy tag carries
    onto the family profile via a superseding record."""
    if legacy.calibration is not TriggerCalibration.HISTORICALLY_ACCURATE:
        return
    profile = trigger_store.load().profile_for_family(user_id, family.slug)
    if profile is None or profile.calibration is TriggerCalibration.HISTORICALLY_ACCURATE:
        return
    trigger_store.append(
        profile.model_copy(
            update={
                "id": _new_id(),
                "supersedes": profile.id,
                "calibration": TriggerCalibration.HISTORICALLY_ACCURATE,
                "notes": (
                    f"{profile.notes} Calibration tag carried from legacy "
                    f"trigger {legacy.name!r} (R7)."
                ).strip(),
            }
        )
    )


def _new_id() -> str:
    import uuid

    return uuid.uuid4().hex
