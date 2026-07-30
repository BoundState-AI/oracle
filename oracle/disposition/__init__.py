#!/usr/bin/env python3
"""
Module: oracle.disposition
Purpose: Disposition data model and release state machine (S1 spine).

This subpackage is the pure, deterministic core for the Oracle disposition
module. All models use Pydantic v2 with extra="forbid". No I/O lives here.

Safety Critical: advisory-only per spec D-1

__safety_critical__: bool = False  # advisory-only per D-1 (S1 is pure data + state)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__version__ = "0.1.0"

# Re-exports for convenience at the slice boundary
from oracle.disposition.codes import (  # noqa: F401
    DispositionCode,
    ExportLabel,
    OPENSubReason,
    TBDReason,
)
from oracle.disposition.models import (  # noqa: F401
    AcceptanceRecord,
    CapabilityModelEntry,
    DispositionUnit,
    EvidenceEntry,
    LevyManifest,
    LevyManifestEntry,
    Locator,
    ScopeDeclaration,
    transition_unit,
    validate_locator_covered_by_manifest,
    validate_physical_impossibility_declaration,
    SCHEMA_VERSION,
    RULE_VERSION,
)
from oracle.disposition.rollup import (  # noqa: F401
    Badge,
    compose_badge,
    rollup_badge,
)
from oracle.disposition.state import (  # noqa: F401
    Actor,
    WorkflowState,
    apply_transition,
    is_machine_actor,
)
from oracle.disposition.export_map import (  # noqa: F401
    AxisSnapshot,
    map_axes_to_export_label,
    export_label_to_code,
)

# RDW product phases (0–5)
from oracle.disposition.graph import DependencyGraph  # noqa: F401
from oracle.disposition.packs import load_rdw_default_packs, DraftPackWorkspace  # noqa: F401
from oracle.disposition.decision import evaluate_unit  # noqa: F401
from oracle.disposition.evidence import EvidenceStore  # noqa: F401
from oracle.disposition.review import (  # noqa: F401
    Role as AttestationRole,
    ReviewState,
    LEGAL_ATTEST_TRANSITIONS,
)
from oracle.disposition.audit import build_lineage  # noqa: F401
from oracle.disposition.integrations import LocalEvidenceConnector  # noqa: F401
from oracle.disposition.golden import run_golden_session  # noqa: F401
from oracle.disposition.actions import ActionRecord  # noqa: F401
from oracle.disposition.readiness import map_readiness, ReadinessLabel  # noqa: F401
from oracle.disposition.advisor import DeterministicAdvisor, get_advisor  # noqa: F401
from oracle.disposition.library import export_library, import_library  # noqa: F401

# S1a deliverables (persistence, audit, release authority)
from oracle.disposition.identity import (  # noqa: F401
    ActorIdentity,
    Role,
    machine_identity,
    is_authorized_transition,
    require_authorized_transition,
    rejection_event_descriptor,
)
from oracle.disposition.eventlog import (  # noqa: F401
    Event,
    EventLog,
    EventLogError,
)
from oracle.disposition.store import (  # noqa: F401
    DispositionStore,
    PackageHeader,
    StoreError,
    ConcurrencyError,
    ReimportConflictError,
)
from oracle.disposition.release import (  # noqa: F401
    ReleaseContext,
    ReleaseRefusal,
    is_unit_release_eligible,
    evaluate_package_eligibility,
    mark_package_release_approved,
)
