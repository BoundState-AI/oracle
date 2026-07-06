#!/usr/bin/env python3
"""
Module: dude.core.fingerprint
Purpose: The analysis-scope fingerprint and gate (spec v0.2 §3–4,
         invariants I3/I4/I5).

Replaces v0.1 §12's evidence hash, which the ORACLE review (A12) showed
was keyed on the wrong things. This fingerprint:
  - hashes user-contributed material only (capture IDs, artifact content
    hashes, user-confirmed events, user interpretations) — LLM-derived
    material is excluded by construction, so re-extraction can never
    change any fingerprint;
  - includes the hypothesis lineage set, so a new hypothesis over old
    evidence is labeled learning (NEW_HYPOTHESIS_REANALYSIS), never
    rumination;
  - includes deadlines and an elapsed-time bucket, so approaching
    deadlines and continued silence legitimately reopen analysis
    (Rule 6 gets data-model backing).

Safety Critical: False
Psychologically Critical: True — a wrong NO_NEW_DATA verdict tells a user
doing real epistemic work that they are ruminating.

Never-suppress-error: failures propagate as refusals, never as a silently
served stale run.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False
__psychologically_critical__: bool = True

import hashlib
import logging
from datetime import datetime, timezone

from dude.data.case import Case, ScopeFingerprint
from dude.data.enums import CreatedBy, GateMode
from dude.data.evidence import Artifact, Capture, Event, Interpretation
from dude.data.hypotheses import Hypothesis

LOGGER = logging.getLogger("dude.core.fingerprint")

# One bucket per 7 days since the last analysis run: continued silence
# eventually changes the scope hash and reopens analysis as SCOPE_CHANGE
# (v0.2 I4). Chosen coarse enough that the gate still blocks same-day
# re-runs on unchanged evidence.
ELAPSED_BUCKET_DAYS = 7


def evidence_hash(
    captures: list[Capture],
    artifacts: list[Artifact],
    events: list[Event],
    interpretations: list[Interpretation],
) -> str:
    """SHA-256 over user-contributed material only (v0.2 §4/I5)."""
    parts: list[str] = []
    parts.extend(sorted(c.id for c in captures))
    parts.extend(sorted(a.content_sha256 for a in artifacts))
    parts.extend(sorted(e.id for e in events if e.user_confirmed))
    parts.extend(
        sorted(
            f"{i.id}:{i.version}"
            for i in interpretations
            if i.created_by is CreatedBy.USER
        )
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def scope_fingerprint(
    case: Case,
    captures: list[Capture],
    artifacts: list[Artifact],
    events: list[Event],
    interpretations: list[Interpretation],
    hypotheses: list[Hypothesis],
    last_run_at: datetime | None,
    now: datetime | None = None,
) -> ScopeFingerprint:
    """Compute the full analysis-scope fingerprint (v0.2 §4)."""
    ev_hash = evidence_hash(captures, artifacts, events, interpretations)
    bucket = _elapsed_bucket(last_run_at, now or datetime.now(timezone.utc))
    parts = [ev_hash]
    parts.extend(sorted({h.lineage_id for h in hypotheses}))
    parts.extend(
        sorted(d.due_at.isoformat() for d in case.deadlines if not d.resolved)
    )
    parts.append(f"elapsed_bucket:{bucket}")
    scope = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return ScopeFingerprint(
        evidence_hash=ev_hash, scope_hash=scope, elapsed_bucket=bucket
    )


def gate(
    current: ScopeFingerprint, previous: ScopeFingerprint | None
) -> GateMode:
    """Decide the analysis mode (v0.2 §3).

    Precedence: new evidence > new hypothesis/scope. Evidence change is
    reported as NEW_EVIDENCE even if the hypothesis set also changed —
    the mode label tells the user the strongest reason the run is
    legitimate."""
    if previous is None:
        return GateMode.NEW_EVIDENCE
    if current.evidence_hash != previous.evidence_hash:
        return GateMode.NEW_EVIDENCE
    if current.scope_hash == previous.scope_hash:
        return GateMode.NO_NEW_DATA
    if current.elapsed_bucket != previous.elapsed_bucket:
        return GateMode.SCOPE_CHANGE
    # Same evidence, same elapsed bucket, different scope: the hypothesis
    # or deadline set changed. Deadline edits are rare; the dominant and
    # psychologically loaded path is a new hypothesis, and the label must
    # say learning, not rumination (v0.2 I3).
    return GateMode.NEW_HYPOTHESIS_REANALYSIS


def _elapsed_bucket(last_run_at: datetime | None, now: datetime) -> int:
    if last_run_at is None:
        return 0
    days = max(0, (now - last_run_at).days)
    return days // ELAPSED_BUCKET_DAYS
