#!/usr/bin/env python3
"""
Module: oracle.disposition.walk
Purpose: TTY-interactive disposition interview CLI (Stage D).

Fails closed when stdin is not a TTY (unless io injection is provided for tests).
No LLM calls. Deterministic question priority and allowed-state computation.

Safety Critical: advisory-only per D-1
__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, TextIO

from oracle.disposition.codes import TBDReason
from oracle.disposition.comments import assemble_comment, prohibited_language_hits
from oracle.disposition.export import export_csv, export_docx, stamp_meta
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.rulepack import (
    RequirementRecord,
    load_requirement_records,
    prerequisites_of,
)
from oracle.disposition.session import SessionError
from oracle.disposition.session import (
    DispositionSession,
    ProjectContext,
    seed_context_appendix_b,
    why_not_meet,
)

LOGGER = logging.getLogger("oracle.disposition.walk")

# Case 19: one scope question applied to multiple units
PAIRED_QUESTION_KEY = "scope.joining_in_crediting"
PAIRED_UNIT_IDS = frozenset({"AMR-21", "AMR-82"})


@dataclass
class IOBundle:
    """Injectable I/O for scripted tests (pexpect-style without pexpect)."""

    stdin: TextIO = field(default_factory=lambda: sys.stdin)
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    require_tty: bool = True

    def write(self, msg: str) -> None:
        self.stdout.write(msg)
        if not msg.endswith("\n"):
            self.stdout.write("\n")
        self.stdout.flush()

    def ask(self, prompt: str) -> str:
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if line == "":
            return "quit"
        return line.strip()


def _is_tty(io: IOBundle) -> bool:
    if not io.require_tty:
        return True
    return bool(getattr(io.stdin, "isatty", lambda: False)())


def _order_units(records: list[RequirementRecord]) -> list[RequirementRecord]:
    """Authority-dependent first (engine §4.2), then pack order."""
    auth = [r for r in records if r.authority_dependent]
    rest = [r for r in records if not r.authority_dependent]
    # Stable: preserve original order within each bucket
    return auth + rest


def _intake_wizard(session: DispositionSession, io: IOBundle, actor: str) -> None:
    assert session.state is not None
    ctx = session.state.context
    if ctx.intake_complete:
        io.write("Project context intake already complete — skipping.")
        return
    io.write("--- Project context intake (unanswered fields only) ---")
    orgs = list(ctx.organizations)
    if not any(o.confirmed for o in orgs if o.role == "customer"):
        ans = io.ask("Confirm customer is assumed CEO? [y/n/skip]: ")
        if ans.lower() in ("y", "yes"):
            # keep assumed_ceo
            pass
        elif ans.lower() in ("n", "no"):
            orgs = [
                o.model_copy(update={"assumed_ceo": False, "confirmed": True})
                if o.role == "customer"
                else o
                for o in orgs
            ]
    if ctx.hardware_process is None:
        proc = io.ask("AM process (e.g. Cold spray) [skip]: ")
        if proc and proc.lower() != "skip":
            session.assert_fact(
                key="hardware.process",
                statement=proc,
                author=actor,
                confidence="high",
            )
    if ctx.classification.tbd:
        ans = io.ask(
            "Primary classification known? [value/skip/unknown]: "
        )
        if ans.lower() in ("skip", "unknown", ""):
            session.assert_fact(
                key="classification.primary",
                statement="Classification not provided",
                author=actor,
                assumed=True,
                owner=actor,
                confidence="low",
            )
        elif ans.lower() != "skip":
            session.assert_fact(
                key="classification.primary",
                statement=ans,
                author=actor,
                confidence="high",
            )
            ctx = ctx.model_copy(
                update={
                    "classification": ctx.classification.model_copy(
                        update={"primary_class": ans, "tbd": False, "tbd_reason": None}
                    )
                }
            )
    # Mark intake complete
    new_ctx = ctx.model_copy(update={"organizations": tuple(orgs), "intake_complete": True})
    session.update_context(new_ctx, actor)


def _highest_value_question(
    unit: RequirementRecord,
    session: DispositionSession,
) -> tuple[str, str]:
    """
    Deterministic priority:
      applicability trigger facts → actor confirmation → implementation → approval
    Returns (question_key, prompt).
    """
    assert session.state is not None
    st = session.state.units[unit.requirement_id]

    # Paired question (case 19)
    if unit.requirement_id in PAIRED_UNIT_IDS:
        if PAIRED_QUESTION_KEY not in session.state.paired_answers:
            return (
                PAIRED_QUESTION_KEY,
                "Does joining/crediting scope apply to this program? [yes/no/unknown]: ",
            )

    if st.applicability == "tbd":
        # Prefer classification for class-gated units — never re-ask if ledger holds
        # any fact (including assumptions). Assumptions stay assumed until explicit
        # confirm_assumption promotion.
        class_fact = session.fact_for("classification.primary")
        if class_fact is None:
            if unit.requirement_id in {"AMR-17", "AMR-18"} or any(
                p.startswith("AMR-") for p in prerequisites_of(unit.requirement_id)
            ):
                return (
                    "classification.primary",
                    "Has the customer provided part classification / fracture-control "
                    "inputs? [value/unknown]: ",
                )
        elif class_fact.assumed and unit.requirement_id in {"AMR-17", "AMR-18"}:
            # Known assumption → land TBD(classification_unresolved) without re-asking
            session.set_axes(
                unit.requirement_id,
                actor_name=session.state.actor_name if session.state else "operator",
                applicability="tbd",
                applicability_tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
                implementation_state="tbd",
                implementation_tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
                election=False,
            )
            return (
                "done",
                "Classification assumed unresolved; axes set to TBD. [enter/quit]: ",
            )
        return (
            f"applicability.{unit.requirement_id}",
            f"Does {unit.requirement_id} apply to this program/hardware? [yes/no/unknown]: ",
        )

    if unit.actor_candidate and not unit.actor_candidate.confirmed:
        key = f"actor.{unit.requirement_id}"
        if session.fact_for(key) is None:
            return (
                key,
                f"Confirm obligated actor "
                f"(candidate: {unit.actor_candidate.value!r} [machine-extracted]) "
                f"[program/ceo/producer/supplier/subtier/other/unknown]: ",
            )

    if st.implementation_state == "tbd":
        return (
            f"implementation.{unit.requirement_id}",
            "Implementation state? "
            "[meets_as_written/alternate_proposed/partial/not_met/unknown]: ",
        )

    if st.approval_state == "tbd":
        return (
            f"approval.{unit.requirement_id}",
            "Approval state? "
            "[not_required/required/draft/submitted/approved/rejected/unknown]: ",
        )

    return ("done", "All primary axes set for this unit. [enter to continue / quit]: ")


def _apply_answer(
    session: DispositionSession,
    unit: RequirementRecord,
    qkey: str,
    answer: str,
    actor: str,
) -> None:
    uid = unit.requirement_id
    ans = answer.strip().lower()

    if qkey == PAIRED_QUESTION_KEY:
        session.record_paired_answer(qkey, answer, actor)
        # Apply to all paired units
        for pid in PAIRED_UNIT_IDS:
            if pid not in session.state.units:  # type: ignore[union-attr]
                continue
            if ans in ("yes", "y"):
                session.set_axes(
                    pid,
                    actor_name=actor,
                    applicability="yes",
                    applicability_tbd_reason=None,
                )
            elif ans in ("no", "n"):
                session.set_axes(
                    pid,
                    actor_name=actor,
                    applicability="no",
                    implementation_state="not_reached",
                    organization_responsibility="external",
                )
            else:
                session.set_axes(
                    pid,
                    actor_name=actor,
                    applicability="tbd",
                    applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                )
        return

    if qkey == "classification.primary":
        if ans in ("unknown", "skip", ""):
            session.assert_fact(
                key="classification.primary",
                statement="Classification not provided",
                author=actor,
                assumed=True,
                owner=actor,
                confidence="low",
                unit_ids=(uid,),
            )
            session.set_axes(
                uid,
                actor_name=actor,
                applicability="tbd",
                applicability_tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
                implementation_state="tbd",
                implementation_tbd_reason=TBDReason.CLASSIFICATION_UNRESOLVED,
            )
        else:
            session.assert_fact(
                key="classification.primary",
                statement=answer.strip(),
                author=actor,
                confidence="high",
                unit_ids=(uid,),
            )
        return

    if qkey.startswith("applicability."):
        if ans in ("yes", "y"):
            session.set_axes(uid, actor_name=actor, applicability="yes")
        elif ans in ("no", "n"):
            session.set_axes(
                uid,
                actor_name=actor,
                applicability="no",
                implementation_state="not_reached",
                organization_responsibility="external",
            )
        else:
            session.set_axes(
                uid,
                actor_name=actor,
                applicability="tbd",
                applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
            )
        return

    if qkey.startswith("actor."):
        if ans in ("unknown", "skip", ""):
            session.set_axes(
                uid,
                actor_name=actor,
                organization_responsibility="tbd",
                org_responsibility_tbd_reason=TBDReason.AUTHORITY_UNIDENTIFIED,
            )
        else:
            prior = session.fact_for(qkey)
            session.assert_fact(
                key=qkey,
                statement=ans,
                author=actor,
                confidence="high",
                unit_ids=(uid,),
                confirm_assumption=bool(prior and prior.assumed),
            )
            actor_val = ans if ans in {
                "program", "ceo", "producer", "supplier", "subtier", "other"
            } else "other"
            session.set_axes(
                uid,
                actor_name=actor,
                obligated_actor=actor_val,
                organization_responsibility="owner",
            )
        return

    if qkey.startswith("implementation."):
        if ans in ("unknown", "skip", ""):
            session.set_axes(
                uid,
                actor_name=actor,
                implementation_state="tbd",
                implementation_tbd_reason=TBDReason.EVIDENCE_ABSENT,
            )
        else:
            session.set_axes(uid, actor_name=actor, implementation_state=ans)
        return

    if qkey.startswith("approval."):
        if ans in ("unknown", "skip", ""):
            session.set_axes(
                uid,
                actor_name=actor,
                approval_state="tbd",
                approval_tbd_reason=TBDReason.APPROVAL_NOT_EXERCISED,
            )
        else:
            session.set_axes(uid, actor_name=actor, approval_state=ans)
        return


def _present_unit(
    rec: RequirementRecord,
    session: DispositionSession,
    io: IOBundle,
) -> None:
    assert session.state is not None
    unit = session.state.units[rec.requirement_id]
    io.write("")
    io.write("=" * 72)
    io.write(f"UNIT {rec.requirement_id}")
    io.write("-" * 72)
    io.write("VERBATIM REQUIREMENT TEXT:")
    io.write(rec.shall_text)
    loc = rec.locator
    page = f" page {loc.page}" if loc.page else ""
    io.write(f"LOCATOR: {loc.standard} {loc.revision} §{loc.section}{page}")
    if rec.actor_candidate:
        io.write(
            f"Actor candidate (machine-extracted, unconfirmed): "
            f"{rec.actor_candidate.value!r}"
        )
    if rec.trigger_candidates:
        io.write(
            "Trigger candidates (machine-extracted): "
            + ", ".join(repr(t.value) for t in rec.trigger_candidates)
        )
    blockers = session.blocked_by(rec.requirement_id)
    if blockers:
        io.write("Dependency state (blocked-by):")
        for b in blockers:
            io.write(f"  - {b}")
    else:
        io.write("Dependency state: no seed blockers.")
    meet_blockers = why_not_meet(unit, session)
    io.write("Why can't this be Meet:")
    if meet_blockers:
        for b in meet_blockers:
            io.write(f"  - {b}")
    else:
        io.write("  - (no deterministic blockers; axes may already allow Meet)")
    try:
        io.write(f"Current export label: {unit.export_label().value}")
    except Exception as e:
        io.write(f"Current export label: <unmapped: {e}>")


def _progress_screen(session: DispositionSession, io: IOBundle) -> None:
    assert session.state is not None
    from collections import Counter

    labels = Counter()
    tbd_reasons: Counter = Counter()
    for u in session.state.units.values():
        try:
            labels[u.export_label().value] += 1
        except Exception:
            labels["<unmapped>"] += 1
        if u.applicability == "tbd" and u.applicability_tbd_reason:
            tbd_reasons[str(u.applicability_tbd_reason)] += 1
    io.write("--- Progress ---")
    io.write("Export labels: " + ", ".join(f"{k}={v}" for k, v in sorted(labels.items())))
    io.write("TBD-by-reason (applicability): " + (
        ", ".join(f"{k}={v}" for k, v in sorted(tbd_reasons.items())) or "(none)"
    ))
    open_n = sum(len(u.open_actions) for u in session.state.units.values())
    io.write(f"Open actions: {open_n}")


def run_walk(
    *,
    session_dir: Path | str,
    actor_name: str = "operator",
    unit_filter: Optional[list[str]] = None,
    export_dir: Optional[Path | str] = None,
    repin: bool = False,
    io: Optional[IOBundle] = None,
    max_units: Optional[int] = None,
) -> DispositionSession:
    """
    Interactive walkthrough. `io` may inject scripted stdin for tests.
    """
    io = io or IOBundle()
    if not _is_tty(io):
        raise SystemExit(
            "oracle disposition walk requires a TTY (fails closed non-TTY). "
            "Use injected IO in tests."
        )

    session = DispositionSession(session_dir)
    header = Path(session_dir) / "session.json"
    if header.exists():
        session.resume(actor_name=actor_name, repin=repin)
        io.write(f"Resumed session {session.state.session_id}")  # type: ignore[union-attr]
    else:
        session.open(actor_name=actor_name, repin=repin, seed_context=True)
        io.write(f"Opened session {session.state.session_id}")  # type: ignore[union-attr]

    # H4: walk the same multi-pack set the session seeds (6030+6033)
    records_list, _ = load_rdw_default_packs(repin=True)
    records = {r.requirement_id: r for r in records_list}
    ordered = _order_units(records_list)
    if unit_filter:
        want = {u.upper() for u in unit_filter}
        ordered = [r for r in ordered if r.requirement_id.upper() in want]

    _intake_wizard(session, io, actor_name)

    done = 0
    for rec in ordered:
        if max_units is not None and done >= max_units:
            break
        _present_unit(rec, session, io)
        while True:
            qkey, prompt = _highest_value_question(rec, session)
            if qkey == "done":
                # Comment proposal
                assert session.state is not None
                unit = session.state.units[rec.requirement_id]
                comment = assemble_comment(
                    unit,
                    org_name="the evaluated organization",
                    facts=session.state.facts,
                )
                hits = prohibited_language_hits(comment)
                io.write(f"Proposed comment (§13.1): {comment}")
                if hits:
                    io.write(f"  (note: prohibited-language hits after soften: {hits})")
                edit = io.ask("Accept comment? [y/edit text/skip]: ")
                if edit.lower() in ("y", "yes", ""):
                    session.set_axes(
                        rec.requirement_id,
                        actor_name=actor_name,
                        comment=comment,
                        comment_status="accepted",
                        election=False,
                    )
                elif edit.lower() != "skip":
                    session.set_axes(
                        rec.requirement_id,
                        actor_name=actor_name,
                        comment=edit,
                        comment_status="edited",
                        election=False,
                    )
                break

            ans = io.ask(prompt)
            if ans.lower() in ("quit", "q", "exit"):
                # quit mid-unit → TBD with reason (never silence)
                session.set_axes(
                    rec.requirement_id,
                    actor_name=actor_name,
                    applicability="tbd",
                    applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    enforce_decision=False,
                )
                io.write("Quit mid-unit: recorded TBD(customer_input_missing).")
                _progress_screen(session, io)
                return session
            if ans.lower() in ("skip",):
                session.set_axes(
                    rec.requirement_id,
                    actor_name=actor_name,
                    applicability="tbd",
                    applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                    enforce_decision=False,
                )
                io.write("Skipped: TBD(customer_input_missing).")
                break
            try:
                _apply_answer(session, rec, qkey, ans, actor_name)
            except (SessionError, ValueError, Exception) as e:
                # M2: re-prompt on invalid free-text instead of crash
                io.write(f"Could not apply answer ({e}). Please try again.")
                continue

        done += 1

    _progress_screen(session, io)

    if export_dir:
        ed = Path(export_dir)
        ed.mkdir(parents=True, exist_ok=True)
        csv_path = ed / "supplier_matrix.csv"
        docx_path = ed / "supplier_matrix.docx"
        export_csv(session, records, csv_path)
        try:
            export_docx(session, records, docx_path)
        except Exception as e:
            io.write(f"DOCX export skipped: {e}")
        meta = stamp_meta(session)
        session.record_export({**meta, "csv": str(csv_path)}, actor_name)
        io.write(f"Exported CSV to {csv_path}")

    return session


def cmd_disposition_walk(args) -> None:
    """CLI entry used by oracle.cli subcommand registration."""
    logging.basicConfig(level=logging.INFO)
    run_walk(
        session_dir=args.session_dir,
        actor_name=args.actor,
        unit_filter=args.units.split(",") if getattr(args, "units", None) else None,
        export_dir=getattr(args, "export_dir", None),
        repin=bool(getattr(args, "repin", False)),
        max_units=getattr(args, "max_units", None),
    )
