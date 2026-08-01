#!/usr/bin/env python3
"""
Module: oracle.disposition.golden
Purpose: Phase 1 golden session — scripted Appendix A/B replay (scrubbed).

Replays AMR-1, AMR-14, AMR-17 against seed context without spreadsheets.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from oracle.disposition.codes import TBDReason
from oracle.disposition.comments import assemble_comment
from oracle.disposition.decision import (
    apply_classification_tbd,
    apply_open_not_met_control_absent,
    evaluate_unit,
)
from oracle.disposition.export import export_all
from oracle.disposition.graph import DependencyGraph
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.session import DispositionSession

LOGGER = logging.getLogger("oracle.disposition.golden")


def run_golden_session(
    session_dir: Path | str,
    export_dir: Path | str | None = None,
    *,
    actor: str = "golden-operator",
) -> dict[str, Any]:
    """
    Deterministic golden replay (RDW Appendix A/B scrubbed):

    - Assumed CEO customer
    - AMR-17 → TBD(classification_unresolved)
    - AMR-14 → Open/Not Met (no EFCP)
    - AMR-1 → external approval responsibility / program applicable axes
    """
    root = Path(session_dir)
    if root.exists():
        # Fresh golden each run when dir provided empty; else open/resume
        pass
    session = DispositionSession(root)
    if (root / "session.json").exists():
        session.resume(actor_name=actor, repin=True)
    else:
        session.open(actor_name=actor, multi_pack=True, seed_context=True)

    assert session.state is not None

    # Appendix B assumptions
    session.assert_fact(
        key="ceo.identity",
        statement="Customer (prime) is assumed CEO",
        author=actor,
        assumed=True,
        owner=actor,
        confidence="low",
    )
    session.assert_fact(
        key="hardware.process",
        statement="Cold spray",
        author=actor,
        confidence="high",
    )
    session.assert_fact(
        key="classification.primary",
        statement="Classification not provided",
        author=actor,
        assumed=True,
        owner=actor,
        confidence="low",
    )
    # EFCP not present — do not confirm plan.EFCP

    # AMR-17
    session.set_axes(
        "AMR-17",
        actor_name=actor,
        enforce_decision=False,
        **apply_classification_tbd("AMR-17"),
    )
    u17 = session.state.units["AMR-17"]
    c17 = assemble_comment(u17, facts=session.state.facts)
    session.set_axes(
        "AMR-17",
        actor_name=actor,
        comment=c17,
        comment_status="accepted",
        election=False,
        enforce_decision=False,
    )

    # AMR-14 Open/Not Met
    session.set_axes(
        "AMR-14",
        actor_name=actor,
        enforce_decision=False,
        **apply_open_not_met_control_absent(),
    )
    session.set_axes(
        "AMR-14",
        actor_name=actor,
        open_actions=("Obtain EFCP / mapped 6033 control set",),
        comment="EFCP / 6033 matrix not present per current knowledge; control absent.",
        comment_status="accepted",
        election=False,
        enforce_decision=False,
    )

    # AMR-1 (AC-3): program-applicable; formal approval external → Open/Not Met
    # (not Exception — no local relief requested; review C2/AC-3)
    session.set_axes(
        "AMR-1",
        actor_name=actor,
        applicability="yes",
        obligated_actor="program",
        organization_responsibility="external",
        implementation_state="not_met",
        approval_state="required",
        comment=(
            "Requirement applies to the program. Formal approval responsibility "
            "is external to the evaluated organization; local control is not met."
        ),
        comment_status="accepted",
        election=False,
        enforce_decision=False,
    )

    labels = {
        uid: session.state.units[uid].export_label().value
        for uid in ("AMR-1", "AMR-14", "AMR-17")
    }

    export_paths = {}
    if export_dir:
        recs, _ = load_rdw_default_packs(repin=True)
        records = {r.requirement_id: r for r in recs}
        export_paths = {
            k: str(v)
            # M4: the golden replay is a verification artifact, not a
            # release — always the DRAFT-watermarked working copy.
            for k, v in export_all(
                session, records, export_dir, include_draft=True
            ).items()
        }
        session.record_export({"paths": export_paths, **labels}, actor)

    graph = DependencyGraph.from_seeds()
    # Simulate classification confirmed → re-review propagation
    session.assert_fact(
        key="classification.primary",
        statement="Class A",
        author=actor,
        confidence="high",
        confirm_assumption=True,
    )
    rereview = session.units_needing_rereview()

    result = {
        "session_id": session.state.session_id,
        "labels": labels,
        "amr17_tbd_reason": str(
            session.state.units["AMR-17"].applicability_tbd_reason
        ),
        "ceo_assumed": session.state.facts["ceo.identity"].assumed,
        "rereview_after_class_a": rereview,
        "export_paths": export_paths,
        "decision_amr14": evaluate_unit(
            session.state.units["AMR-14"],
            facts=session.state.facts,
            graph=graph,
        ).current_label,
    }
    LOGGER.info("Golden session complete: %s", result["labels"])
    return result
