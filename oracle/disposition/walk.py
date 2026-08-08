#!/usr/bin/env python3
"""
Module: oracle.disposition.walk
Purpose: TTY-interactive disposition interview CLI (Stage C shell).

Fails closed when stdin is not a TTY (unless io injection is provided for tests).
Optional --advisor uses DeterministicAdvisor (tests) or LiveAdvisor (opt-in).
Deterministic question priority and allowed-state computation.

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
from oracle.disposition.export import ExportError, export_all, stamp_meta
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


def _sub_ask(
    session: DispositionSession,
    io: IOBundle,
    uid: str,
    subkey: str,
    prompt: str,
    actor: str,
) -> Optional[str]:
    """AR3: sub-prompt discipline. Every follow-up answer is raw-logged
    (Stage A applies to citations/evidence/MI/EX/plan fields, not just the
    top-level question), and quit/EOF cancels the sub-flow instead of being
    stored as data — IOBundle.ask maps EOF to the literal 'quit', which
    previously leaked into scope_citation and evidence doc ids."""
    ans = io.ask(prompt).strip()
    session.record_answer(uid, subkey, ans, actor_name=actor)
    if ans.lower() in ("quit", "q"):
        return None
    return ans


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
        customer = next((o for o in orgs if o.role == "customer"), None)
        cust_name = customer.name if customer else "Customer"
        # AR3: intake answers are raw-logged under the SESSION pseudo-unit;
        # quit/EOF is a cancel, never data (a "quit" CEO name was storable).
        ans = _sub_ask(
            session, io, "SESSION", "intake.ceo_confirm",
            f"Confirm {cust_name} is the assumed CEO? [y/n/skip]: ", actor,
        )
        if ans is None:
            ans = "skip"
        if ans.lower() in ("y", "yes"):
            # FR1: identity recorded as an ASSUMPTION — never silently confirmed
            session.assert_fact(
                key="ceo.identity",
                statement=f"{cust_name}, assumed CEO (unconfirmed)",
                author=actor,
                assumed=True,
                owner=actor,
                confidence="low",
            )
        elif ans.lower() in ("n", "no"):
            # FR1: capture WHO the CEO actually is before anything is confirmed
            who = _sub_ask(
                session, io, "SESSION", "intake.ceo_identity",
                "Who is the CEO (cognizant engineering organization)?: ", actor,
            )
            if who is None:
                who = ""
            if who.strip() and who.strip().lower() not in ("skip", "unknown"):
                session.assert_fact(
                    key="ceo.identity",
                    statement=f"{who.strip()} is the CEO (operator-provided)",
                    author=actor,
                    confidence="high",
                )
                orgs = [
                    o.model_copy(update={"assumed_ceo": False}) if o.role == "customer" else o
                    for o in orgs
                ]
                from oracle.disposition.session import Organization

                orgs.append(
                    Organization(role="ceo", name=who.strip(), confirmed=True)
                )
            else:
                session.assert_fact(
                    key="ceo.identity",
                    statement="CEO identity unknown (customer input required)",
                    author=actor,
                    assumed=True,
                    owner=actor,
                    confidence="low",
                )
        else:
            session.assert_fact(
                key="ceo.identity",
                statement="CEO identity unresolved at intake",
                author=actor,
                assumed=True,
                owner=actor,
                confidence="low",
            )
    if ctx.hardware_process is None:
        proc = _sub_ask(
            session, io, "SESSION", "intake.hardware_process",
            "AM process (e.g. Cold spray) [skip]: ", actor,
        )
        if proc and proc.lower() != "skip":
            session.assert_fact(
                key="hardware.process",
                statement=proc,
                author=actor,
                confidence="high",
            )
    if ctx.classification.tbd:
        ans = _sub_ask(
            session, io, "SESSION", "intake.classification",
            "Primary classification known? [value/skip/unknown]: ", actor,
        )
        if ans is None:
            ans = "unknown"
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

    if st.applicability == "no":
        # FR3: N/A is terminal — actor/approval questions are moot for a row
        # that does not apply (citation was gathered at election).
        return ("done", "N/A recorded with citation. [enter to continue / quit]: ")

    # FR3: the actor/ownership question must fire even when the pack has no
    # machine-extracted candidate — otherwise org_responsibility stays TBD
    # forever and no label can complete (Fran F4, root cause).
    if st.applicability == "yes" and (
        (unit.actor_candidate and not unit.actor_candidate.confirmed)
        or st.obligated_actor is None
    ):
        key = f"actor.{unit.requirement_id}"
        if session.fact_for(key) is None:
            cand = (
                f"(candidate: {unit.actor_candidate.value!r} [machine-extracted]) "
                if unit.actor_candidate
                else ""
            )
            return (
                key,
                f"Confirm obligated actor {cand}"
                f"[program/ceo/producer/supplier/subtier/other/unknown]: ",
            )

    # M2 (Fran P0): who is obligated and whose job execution is are SEPARATE
    # questions — auto-setting owner mis-assigned CEO/program obligations.
    if st.applicability == "yes" and st.organization_responsibility == "tbd":
        hint = (
            " (obligated actor is external — likely external)"
            if st.obligated_actor in ("program", "ceo")
            else ""
        )
        return (
            f"responsibility.{unit.requirement_id}",
            f"Whose responsibility is execution for the evaluated org?{hint} "
            "[owner/support/external/unknown]: ",
        )

    # Model split: the contract ELECTION, then the execution FACT.
    if (
        st.applicability == "yes"
        and st.fulfillment_path == "tbd"
        and not st.split_elected
    ):
        return (
            f"fulfillment.{unit.requirement_id}",
            "How will this requirement be fulfilled contractually? "
            "[as_written/alternative/exception/open/unknown]: ",
        )

    if st.applicability == "yes" and st.execution_state == "tbd":
        return (
            f"execution.{unit.requirement_id}",
            "Where is implementation today? "
            "[not_started/partial/implemented/evidenced/verified/"
            "not_yet_due/unknown]: ",
        )

    if st.approval_state == "tbd":
        return (
            f"approval.{unit.requirement_id}",
            "Approval state? "
            "[not_required/required/draft/submitted/approved/rejected/unknown]: ",
        )

    return ("done", "All primary axes set for this unit. [enter to continue / quit]: ")


def _action_form(
    session: DispositionSession,
    io: IOBundle,
    uid: str,
    actor: str,
    *,
    default_id: str,
) -> Optional["ActionRecord"]:
    """FR3: closure-plan mini-form. Returns None when the operator cancels
    (including quit/EOF at any field — AR3)."""
    from oracle.disposition.actions import ActionRecord

    def _f(subkey: str, prompt: str) -> Optional[str]:
        return _sub_ask(session, io, uid, f"action.{subkey}", prompt, actor)

    aid = _f("id", f"Action id [{default_id}]: ")
    if aid is None:
        return None
    aid = aid or default_id
    title = _f("title", "Action title: ")
    if title is None or not title or title.lower() in ("cancel", "skip"):
        return None
    owner = _f("owner", "Owner (person/org accountable): ")
    if owner is None:
        return None
    deliverable = _f("deliverable", "Deliverable: ")
    if deliverable is None:
        return None
    exit_criteria = _f("exit_criteria", "Exit criteria (done-when): ")
    if exit_criteria is None:
        return None
    priority = _f("priority", "Priority [critical/high/medium/low, default medium]: ")
    if priority is None:
        return None
    priority = priority.lower()
    if priority not in ("critical", "high", "medium", "low"):
        priority = "medium"
    due = _f("due_or_trigger", "Due or trigger (free text, optional): ")
    if due is None:
        return None
    wp = _f("work_package", "Work package (optional): ")
    if wp is None:
        return None
    return ActionRecord(
        action_id=aid,
        title=title,
        owner=owner,
        deliverable=deliverable,
        exit_criteria=exit_criteria,
        priority=priority,  # type: ignore[arg-type]
        due_or_trigger=due,
        work_package=wp,
        affected_unit_ids=(uid,),
    )


def _gather_mi_fields(
    session: DispositionSession, io: IOBundle, uid: str, actor: str
) -> Optional[dict]:
    """FR3: Meets Intent requires intent + alternative control + class.
    Returns None on cancel (AR3). AR9: invalid class re-prompts — never a
    silent default; blank takes the announced default."""
    intent = _sub_ask(
        session, io, uid, "mi.intent_statement",
        "Meets Intent — intent statement (what the requirement intends): ", actor,
    )
    if intent is None:
        return None
    alt = _sub_ask(
        session, io, uid, "mi.alternative_control",
        "Alternative control (how intent is met instead): ", actor,
    )
    if alt is None:
        return None
    while True:
        cls = _sub_ask(
            session, io, uid, "mi.control_class",
            "Control class [integral/disclosed] (default integral): ", actor,
        )
        if cls is None:
            return None
        cls = cls.lower()
        if not cls:
            cls = "integral"
        if cls in ("integral", "disclosed"):
            break
        io.write(f"Invalid control class {cls!r} — enter integral or disclosed.")
    out: dict = {}
    if intent:
        out["intent_statement"] = intent
    if alt:
        out["alternative_control"] = alt
    out["control_class"] = cls
    return out


def _gather_ex_closure(
    session: DispositionSession, io: IOBundle, uid: str, actor: str
) -> Optional[dict]:
    """FR3: Exception requires basis + (closure action | permanent relief).
    Returns None on cancel (AR3)."""
    basis = _sub_ask(
        session, io, uid, "ex.exception_basis",
        "Exception basis (why as-written cannot be met): ", actor,
    )
    if basis is None:
        return None
    out: dict = {}
    if basis:
        out["exception_basis"] = basis
    choice = _sub_ask(
        session, io, uid, "ex.closure_choice",
        "Closure path — 'action' to record a closure action, or "
        "'relief <permanent-relief basis>': ", actor,
    )
    if choice is None:
        return None
    if choice.lower().startswith("relief"):
        relief = choice[len("relief"):].strip()
        if relief:
            out["permanent_relief_basis"] = relief
    else:
        act = _action_form(session, io, uid, actor, default_id=f"REL-{uid}")
        if act is not None:
            session.record_action(act, actor_name=actor)
            out["closure_path_action_id"] = act.action_id
    return out


def _gather_meet_evidence(
    session: DispositionSession, io: IOBundle, uid: str, actor: str
) -> bool:
    """M3: cited evidence REGISTERS at the claim (registry created on
    demand) and qualifies only when the registry gate passes — a typed
    citation alone never does. quit/EOF cancels (AR3)."""
    from oracle.disposition.session import EvidenceRef

    doc = _sub_ask(
        session, io, uid, "evidence.doc_id",
        "An evidence claim requires a citation — document id [or 'cancel']: ",
        actor,
    )
    if doc is None or not doc or doc.lower() in ("cancel", "skip"):
        return False
    rev = _sub_ask(session, io, uid, "evidence.revision", "Document revision: ", actor)
    if rev is None:
        return False
    rev = rev or "-"
    date = _sub_ask(
        session, io, uid, "evidence.date",
        "Approval/effective date [YYYY-MM-DD, required to qualify]: ", actor,
    )
    if date is None:
        return False
    session.attach_evidence(uid, EvidenceRef(doc_id=doc, revision=rev), actor)
    session.register_evidence(
        evidence_id=f"EV-{uid}-{doc}",
        doc_id=doc,
        revision=rev,
        unit_ids=(uid,),
        effective_date=date or None,
        approval_date=date or None,
    )
    ok = session.has_qualifying_meet_evidence(session.state.units[uid])
    if not ok:
        io.write(
            "Citation registered but does not QUALIFY (missing/expired "
            "approval date) — the claim stays unverified."
        )
    return ok


def _apply_answer(
    session: DispositionSession,
    unit: RequirementRecord,
    qkey: str,
    answer: str,
    actor: str,
    io: IOBundle,
) -> None:
    uid = unit.requirement_id
    ans = answer.strip().lower()

    if qkey == PAIRED_QUESTION_KEY:
        # FR5/AR5: a paired "no" is an N/A election for BOTH units — it needs
        # a real operator-supplied scope citation, not a synthesized one.
        citation: Optional[str] = None
        if ans in ("no", "n"):
            citation = _sub_ask(
                session, io, uid, f"{qkey}.citation",
                "Scope exclusion needs a positive citation "
                "(e.g. '6030 §1.2: no joining processes in crediting') "
                "[or 'tbd']: ", actor,
            )
            if citation is not None and citation.lower() in ("tbd", "skip", "unknown"):
                citation = None
            if not citation:
                io.write(
                    "No citation — both paired units record "
                    "TBD(scope_decision_not_made) instead of N/A."
                )
        session.apply_paired_answer(
            qkey, answer, actor,
            paired_unit_ids=tuple(PAIRED_UNIT_IDS),
            scope_citation=citation,
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
            # FR3: N/A requires a positive scope citation — gather it now
            citation = _sub_ask(
                session, io, uid, f"{qkey}.citation",
                "N/A requires a positive scope/trigger citation "
                "(e.g. '6030 §1.2: not flight hardware') [or 'tbd']: ", actor,
            )
            if not citation or citation.lower() in ("tbd", "skip", "unknown"):
                io.write("No citation — recording TBD(customer_input_missing) instead of N/A.")
                session.set_axes(
                    uid,
                    actor_name=actor,
                    applicability="tbd",
                    applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                )
                return
            session.set_axes(
                uid,
                actor_name=actor,
                applicability="no",
                implementation_state="not_reached",
                organization_responsibility="external",
                scope_citation=citation,
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
            # M2 (Fran P0): NEVER auto-set responsibility — a CEO/program
            # obligation is not the evaluated org's ownership. The
            # responsibility question follows.
            session.set_axes(uid, actor_name=actor, obligated_actor=actor_val)
        return

    if qkey.startswith("responsibility."):
        if ans in ("owner", "support", "external"):
            session.set_axes(
                uid, actor_name=actor, organization_responsibility=ans
            )
        else:
            session.set_axes(
                uid,
                actor_name=actor,
                organization_responsibility="tbd",
                org_responsibility_tbd_reason=TBDReason.AUTHORITY_UNIDENTIFIED,
            )
        return

    if qkey.startswith("fulfillment."):
        # Model split: the contract election (never execution)
        if ans in ("as_written", "meets_as_written", "cw"):
            session.set_axes(uid, actor_name=actor, fulfillment_path="as_written")
        elif ans in ("alternative", "alternative_intent", "alternate_proposed", "mi"):
            # FR3: Meets Intent fields gathered with the election
            fields = _gather_mi_fields(session, io, uid, actor)
            if fields is None:
                io.write("Cancelled — no fulfillment commitment recorded.")
                return
            session.set_axes(
                uid,
                actor_name=actor,
                fulfillment_path="alternative_intent",
                **fields,
            )
        elif ans in ("exception", "ex"):
            # basis + closure path gathered when approval completes the label
            session.set_axes(uid, actor_name=actor, fulfillment_path="exception")
        elif ans in ("open", "none", "not_met"):
            # explicit: no commitment elected (Open/Not Met once execution known)
            session.set_axes(uid, actor_name=actor, fulfillment_path="tbd")
        # unknown/skip: leave unelected; operator can skip the unit
        return

    if qkey.startswith("execution."):
        if ans in ("not_started", "partial", "implemented"):
            session.set_axes(uid, actor_name=actor, execution_state=ans)
        elif ans in ("evidenced", "verified"):
            # M3-adjacent: an evidence claim cites its evidence NOW; a
            # cancelled citation downgrades the claim to 'implemented'.
            if session.has_qualifying_meet_evidence(
                session.state.units[uid]
            ) or _gather_meet_evidence(session, io, uid, actor):
                session.set_axes(uid, actor_name=actor, execution_state=ans)
            else:
                io.write(
                    "No evidence cited — recording execution 'implemented' "
                    "(claim without citation)."
                )
                session.set_axes(
                    uid, actor_name=actor, execution_state="implemented"
                )
        elif ans in ("not_yet_due", "nyd"):
            # FR3: Not Yet Due — trigger/justification required
            just = _sub_ask(
                session, io, uid, f"{qkey}.nyd_justification",
                "Not Yet Due — justification (what trigger/phase defers it): ",
                actor,
            )
            if just is None:
                io.write("Cancelled — execution stays TBD (no Not Yet Due).")
                session.set_axes(uid, actor_name=actor, execution_state="tbd")
                return
            if not just:
                raise SessionError("Not Yet Due requires a justification")
            session.set_axes(
                uid,
                actor_name=actor,
                execution_state="not_started",
                not_yet_due=True,
                not_yet_due_justification=just,
            )
        else:
            session.set_axes(uid, actor_name=actor, execution_state="tbd")
        return

    if qkey.startswith("approval."):
        if ans in ("unknown", "skip", ""):
            session.set_axes(
                uid,
                actor_name=actor,
                approval_state="tbd",
                approval_tbd_reason=TBDReason.APPROVAL_NOT_EXERCISED,
            )
            return
        _apply_approval_with_completion(session, unit, uid, ans, actor, io)
        return


def _split_axes_payload(axes: dict) -> dict:
    """Convert a legacy proposal/suggestion axes dict to a split-axes
    election so accepting it fully decides the unit (no re-interview of a
    fulfillment the acceptance already elected)."""
    from oracle.disposition.codes import split_from_legacy

    out = dict(axes)
    impl = out.pop("implementation_state", None)
    if impl is not None and "fulfillment_path" not in out:
        ful, execu = split_from_legacy(
            impl, out.get("applicability", "tbd"), out.get("approval_state", "tbd")
        )
        out["fulfillment_path"] = ful
        out["execution_state"] = execu
    return out


def _would_be_label(session: DispositionSession, uid: str, **updates) -> Optional[str]:
    """Dry-run the §7.1 label a field update would produce (no state change).

    Model split: rebuild through model_validate — model_copy would skip the
    legacy→split conversion and probe with STALE split axes, making the dry
    label diverge from the real election (the exact risk Atlas verified
    against on the pre-split model).
    """
    assert session.state is not None
    try:
        unit = session.state.units[uid]
        data = unit.model_dump()
        data.update(updates)
        if "fulfillment_path" in updates or "execution_state" in updates:
            data["split_elected"] = True
            data.pop("implementation_state", None)
        elif "implementation_state" in updates or not data.get("split_elected"):
            data.pop("fulfillment_path", None)
            data.pop("execution_state", None)
        from oracle.disposition.session import UnitAxesState

        probe = UnitAxesState.model_validate(data)
        return probe.export_label().value
    except Exception:  # mapping may legitimately fail mid-interview
        return None


def _apply_approval_with_completion(
    session: DispositionSession,
    unit: RequirementRecord,
    uid: str,
    ans: str,
    actor: str,
    io: IOBundle,
) -> None:
    """FR3: the approval answer completes the label — gather what the label's
    gate demands (Meet evidence / EX basis+closure / MI fields) BEFORE electing,
    and offer the Not-Met plan form after an Open/Not Met election."""
    assert session.state is not None
    cur = session.state.units[uid]
    label = _would_be_label(session, uid, approval_state=ans)
    extra: dict = {}

    if (
        label == "Meet"
        and cur.execution_state in ("evidenced", "verified")
        and not session.has_qualifying_meet_evidence(cur)
    ):
        # Only an execution CLAIM needs a citation here — a CW commitment
        # with execution not started is AMR-106, handled by the plan offer.
        if not _gather_meet_evidence(session, io, uid, actor):
            io.write(
                "No evidence cited — commitment withdrawn (approval recorded; "
                "fulfillment back to open)."
            )
            session.set_axes(
                uid,
                actor_name=actor,
                approval_state=ans,
                fulfillment_path="tbd",
                execution_state=(
                    "implemented"
                    if cur.execution_state in ("evidenced", "verified")
                    else cur.execution_state
                ),
            )
            return
    elif label == "Exception":
        needs_basis = not (cur.exception_basis or "").strip()
        needs_closure = not (
            (cur.closure_path_action_id or "").strip()
            or (cur.permanent_relief_basis or "").strip()
        )
        if needs_basis or needs_closure:
            gathered = _gather_ex_closure(session, io, uid, actor)
            if gathered is None:
                # AR3: quit/EOF mid-gather cancels the election — the
                # commitment is withdrawn, not half-recorded.
                io.write("Cancelled — commitment withdrawn (fulfillment back to open).")
                session.set_axes(
                    uid,
                    actor_name=actor,
                    approval_state=ans,
                    fulfillment_path="tbd",
                )
                return
            extra = gathered
    elif label == "Meets Intent":
        missing = not (
            (cur.intent_statement or "").strip()
            and (cur.alternative_control or "").strip()
            and (cur.control_class or "")
        )
        if missing:
            gathered = _gather_mi_fields(session, io, uid, actor)
            if gathered is None:
                io.write("Cancelled — commitment withdrawn (fulfillment back to open).")
                session.set_axes(
                    uid,
                    actor_name=actor,
                    approval_state=ans,
                    fulfillment_path="tbd",
                )
                return
            extra = gathered

    session.set_axes(uid, actor_name=actor, approval_state=ans, **extra)

    # Model split: a CW/MI commitment with execution not started IS the
    # engagement's dominant pattern (AMR-106) — it needs a plan exactly
    # like Open/Not Met, or readiness stays TBD Verify.
    after = session.state.units[uid]
    needs_plan = label == "Open/Not Met" or (
        label in ("Meet", "Meets Intent")
        and after.execution_state in ("not_started", "partial")
    )
    if needs_plan:
        has_plan = any(
            a.is_plan_quality()
            for a in session.actions_for_unit(uid)
            if a.status == "open"
        )
        if not has_plan:
            # AR7: imported library action patterns were stored but never
            # consumed — offer a matching pattern before the blank form.
            if _offer_library_action_pattern(session, io, uid, actor):
                return
            p = _sub_ask(
                session, io, uid, "plan.offer",
                f"{label} with execution not complete — record a closure plan "
                "(owner + exit criteria) for Not-Met-with-Plan readiness? "
                "[y/n]: ", actor,
            )
            if p is not None and p.lower() in ("y", "yes"):
                act = _action_form(session, io, uid, actor, default_id=f"GAP-{uid}")
                if act is not None:
                    session.record_action(act, actor_name=actor)
                    io.write(f"Recorded {act.action_id}.")
            else:
                io.write("Without a plan-quality action, readiness stays TBD Verify.")


def _offer_library_action_pattern(
    session: DispositionSession, io: IOBundle, uid: str, actor: str
) -> bool:
    """AR7: offer an imported plan pattern for this unit; True when recorded."""
    from oracle.disposition.actions import ActionRecord

    assert session.state is not None
    pat = next(
        (
            p
            for p in session.state.library_action_patterns
            if uid in tuple(p.get("affected_unit_ids") or ())
        ),
        None,
    )
    if pat is None:
        return False
    io.write(
        f"Library plan pattern: {pat.get('title')} "
        f"(owner={pat.get('owner')}, exit={pat.get('exit_criteria')})"
    )
    acc = _sub_ask(
        session, io, uid, "plan.library_pattern",
        "Apply this library plan pattern? [y/n]: ", actor,
    )
    if acc is None or acc.lower() not in ("y", "yes"):
        return False
    try:
        act = ActionRecord(
            action_id=str(pat.get("action_id") or f"GAP-{uid}"),
            title=str(pat.get("title") or ""),
            owner=str(pat.get("owner") or ""),
            deliverable=str(pat.get("deliverable") or ""),
            exit_criteria=str(pat.get("exit_criteria") or ""),
            priority=(
                pat.get("priority")
                if pat.get("priority") in ("critical", "high", "medium", "low")
                else "medium"
            ),
            due_or_trigger=str(pat.get("due_or_trigger") or ""),
            work_package=str(pat.get("work_package") or ""),
            affected_unit_ids=(uid,),
            note=f"from library pattern (source: {pat.get('action_id')})",
        )
    except ValueError as e:
        io.write(f"Pattern invalid ({e}) — falling back to the plan form.")
        return False
    session.record_action(act, actor_name=actor)
    io.write(f"Recorded {act.action_id} from library pattern.")
    return True


def _present_unit(
    rec: RequirementRecord,
    session: DispositionSession,
    io: IOBundle,
    *,
    advisor: Optional[object] = None,
    actor_name: str = "operator",
) -> None:
    assert session.state is not None
    unit = session.state.units[rec.requirement_id]
    io.write("")
    io.write("=" * 72)
    io.write(f"UNIT {rec.requirement_id}")
    io.write("-" * 72)
    # §14.1: verbatim text + locator FIRST
    io.write("VERBATIM REQUIREMENT TEXT:")
    io.write(rec.shall_text)
    loc = rec.locator
    page = f" page {loc.page}" if loc.page else ""
    io.write(f"LOCATOR: {loc.standard} {loc.revision} §{loc.section}{page}")
    if advisor is not None:
        from oracle.disposition.advisor import build_context

        ctx = build_context(
            unit,
            rec,
            session.state.facts,
            has_evidence=session.has_qualifying_meet_evidence(unit),
        )
        try:
            exp = advisor.explain(ctx)  # type: ignore[attr-defined]
            session.record_advisor_output(
                "explain",
                exp.model_dump(mode="json"),
                actor_name=actor_name,
                unit_id=rec.requirement_id,
            )
            io.write("INTERPRETATION (*interpretation* — not the requirement text):")
            io.write(exp.interpretation)
            io.write(f"  [band={exp.band.value} basis={exp.basis}]")
        except Exception as e:
            io.write(f"Advisor explain unavailable: {e}")
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
        contract = unit.export_label().value
        io.write(f"Contract export label: {contract}")
    except Exception as e:
        io.write(f"Contract export label: <unmapped: {e}>")
    # Stage A readiness view
    try:
        from oracle.disposition.readiness import map_readiness
        from oracle.disposition.actions import migrate_string_action

        acts = session.actions_for_unit(rec.requirement_id)
        if not acts and unit.open_actions:
            acts = [
                migrate_string_action(t, unit_id=rec.requirement_id, index=i)
                for i, t in enumerate(unit.open_actions)
            ]
        rr = map_readiness(
            unit,
            acts,
            has_qualifying_evidence=session.has_qualifying_meet_evidence(unit),
        )
        io.write(f"Readiness label: {rr.label.value} ({'; '.join(rr.reasons)})")
    except Exception as e:
        io.write(f"Readiness label: <unavailable: {e}>")
    io.write(
        f"Live axes: app={unit.applicability} actor={unit.obligated_actor} "
        f"org={unit.organization_responsibility} impl={unit.implementation_state} "
        f"appr={unit.approval_state}"
    )


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


def _advisor_proposal_step(
    session: DispositionSession,
    rec: RequirementRecord,
    io: IOBundle,
    advisor: object,
    actor_name: str,
) -> None:
    """Render propose + optional suggest_closure; accept = election."""
    from oracle.disposition.advisor import build_context

    assert session.state is not None
    unit = session.state.units[rec.requirement_id]
    ctx = build_context(
        unit,
        rec,
        session.state.facts,
        has_evidence=session.has_qualifying_meet_evidence(unit),
        raw_answers=_unit_answers(session, rec.requirement_id),
        existing_actions=tuple(
            a.model_dump(mode="json")
            for a in session.actions_for_unit(rec.requirement_id)
        ),
    )
    prop = advisor.propose(ctx)  # type: ignore[attr-defined]
    session.record_advisor_output(
        "propose",
        prop.model_dump(mode="json"),
        actor_name=actor_name,
        unit_id=rec.requirement_id,
    )
    io.write(
        f"Advisor proposal: band={prop.band.value} basis={prop.basis}"
    )
    if prop.proposed_axes is None:
        io.write("  (no axis proposal — §8 LOW or insufficient pattern)")
        for q in prop.questions:
            io.write(f"  Question: {q}")
        return
    io.write(f"  proposed_label={prop.proposed_label}")
    for k, v in prop.proposed_axes.items():
        io.write(f"  {k}={v}")
    ans = _sub_ask(
        session, io, rec.requirement_id, "advisor.accept",
        "Accept proposal? [y=attest election / edit=skip axes / skip=TBD]: ",
        actor_name,
    )
    if ans is None:
        io.write("Cancelled — proposal not elected.")
        return
    if ans.lower() in ("y", "yes"):
        try:
            session.set_axes(
                rec.requirement_id,
                actor_name=actor_name,
                election=True,
                **_split_axes_payload(prop.proposed_axes),
            )
            io.write("Proposal elected.")
        except SessionError as e:
            io.write(f"Election refused (deterministic gate): {e}")
    elif ans.lower() in ("skip", "s"):
        session.set_axes(
            rec.requirement_id,
            actor_name=actor_name,
            enforce_decision=False,
            applicability="tbd",
            applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
        )
        io.write("Skipped proposal → TBD(customer_input_missing).")

def _unit_answers(
    session: DispositionSession, uid: str
) -> tuple[dict, ...]:
    assert session.state is not None
    return tuple(
        a for a in session.state.raw_answers if a.get("unit_id") == uid
    )


def _advisor_closure_step(
    session: DispositionSession,
    rec: RequirementRecord,
    io: IOBundle,
    advisor: object,
    actor_name: str,
) -> None:
    """M5 (Fran P1): closure runs AFTER the operator's elections, with the
    context the interview actually produced — answers, evidence, actions —
    never a stale pre-election snapshot."""
    from oracle.disposition.advisor import build_context

    assert session.state is not None
    unit = session.state.units[rec.requirement_id]
    if unit.execution_state not in ("not_started", "partial", "tbd"):
        return
    ctx = build_context(
        unit,
        rec,
        session.state.facts,
        has_evidence=session.has_qualifying_meet_evidence(unit),
        raw_answers=_unit_answers(session, rec.requirement_id),
        existing_actions=tuple(
            a.model_dump(mode="json")
            for a in session.actions_for_unit(rec.requirement_id)
        ),
    )
    clos = advisor.suggest_closure(ctx)  # type: ignore[attr-defined]
    session.record_advisor_output(
        "suggest_closure",
        clos.model_dump(mode="json"),
        actor_name=actor_name,
        unit_id=rec.requirement_id,
    )
    io.write("Closure suggestions (*proposed* — not committed):")
    for a in clos.actions:
        io.write(
            f"  {a.action_id}: {a.title} owner={a.owner} "
            f"exit={a.exit_criteria}"
        )
        conf = _sub_ask(
            session, io, rec.requirement_id,
            f"advisor.action.{a.action_id}",
            f"Record action {a.action_id}? [y/n]: ", actor_name,
        )
        if conf is None:
            break
        if conf.lower() in ("y", "yes"):
            session.record_action(a, actor_name=actor_name)
            io.write(f"  recorded {a.action_id}")


def _offer_library_suggestion(
    session: DispositionSession,
    rec: RequirementRecord,
    io: IOBundle,
    actor_name: str,
) -> None:
    """FR5: show an imported library disposition as a SUGGESTION with
    provenance; applying runs the normal gated election + attestation path."""
    assert session.state is not None
    sug = session.state.library_suggestions.get(rec.requirement_id)
    if not sug:
        return
    unit = session.state.units[rec.requirement_id]
    if unit.applicability != "tbd":  # already worked — don't re-offer
        return
    prov = (sug.get("provenance") or {}).get("session_id", "unknown")
    io.write(
        f"Library suggestion (from {prov}): label={sug.get('export_label')} "
        f"axes={sug.get('axes')}"
    )
    if sug.get("comment"):
        io.write(f"  prior comment: {sug['comment']}")
    ans = _sub_ask(
        session, io, rec.requirement_id, "library.accept",
        "Apply library suggestion as your election? [y/n]: ", actor_name,
    )
    if ans is None or ans.lower() not in ("y", "yes"):
        return
    axes = dict(sug.get("axes") or {})
    try:
        session.set_axes(
            rec.requirement_id, actor_name=actor_name, **_split_axes_payload(axes)
        )
        io.write("Library suggestion elected (attest as usual).")
    except (SessionError, ValueError) as e:
        io.write(f"Suggestion refused by deterministic gate ({e}).")
        # AR7: all-or-nothing made suggestions unusable — the gated axes
        # (Meet evidence, N/A citation, EX basis) rightly refuse, but the
        # ungated ones are still good context. Seed those and let the
        # interview gather the rest. N2: applicability is NEVER seeded —
        # the classification question only fires while it is TBD, so
        # seeding "yes" would skip a class-gated unit's interview.
        partial = {
            k: axes[k]
            for k in ("obligated_actor", "organization_responsibility")
            if axes.get(k) not in (None, "tbd")
        }
        if not partial:
            io.write("Continuing with the normal interview.")
            return
        try:
            session.set_axes(rec.requirement_id, actor_name=actor_name, **partial)
            io.write(
                f"Partial seed applied ({', '.join(sorted(partial))}) — "
                "interview continues for the gated axes."
            )
        except (SessionError, ValueError) as e2:
            io.write(
                f"Partial seed also refused ({e2}) — continuing with the "
                "normal interview."
            )


def run_walk(
    *,
    session_dir: Path | str,
    actor_name: str = "operator",
    unit_filter: Optional[list[str]] = None,
    export_dir: Optional[Path | str] = None,
    repin: bool = False,
    io: Optional[IOBundle] = None,
    max_units: Optional[int] = None,
    advisor: bool = False,
    live_advisor: bool = False,
    allow_builtin: bool = False,
) -> DispositionSession:
    """
    Interactive walkthrough. `io` may inject scripted stdin for tests.

    advisor=True enables DeterministicAdvisor (or LiveAdvisor if live_advisor).
    """
    io = io or IOBundle()
    if not _is_tty(io):
        raise SystemExit(
            "oracle disposition walk requires a TTY (fails closed non-TTY). "
            "Use injected IO in tests."
        )

    adv = None
    if advisor:
        from oracle.disposition.advisor import get_advisor

        adv = get_advisor(live=live_advisor)
        io.write(
            f"Advisor enabled: {getattr(adv, 'model_id', type(adv).__name__)} "
            "(outputs proposed-only until you attest)"
        )

    session = DispositionSession(session_dir)
    header = Path(session_dir) / "session.json"
    if header.exists():
        session.resume(
            actor_name=actor_name, repin=repin, allow_builtin=allow_builtin
        )
        io.write(f"Resumed session {session.state.session_id}")  # type: ignore[union-attr]
    else:
        session.open(
            actor_name=actor_name,
            repin=repin,
            seed_context=True,
            allow_builtin=allow_builtin,
        )
        io.write(f"Opened session {session.state.session_id}")  # type: ignore[union-attr]

    # H4/N3: walk the exact record set the session pinned at open/resume —
    # re-loading defaults here rendered curated text under a builtin pin.
    records_list = session.loaded_records
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
        _present_unit(
            rec, session, io, advisor=adv, actor_name=actor_name
        )
        _offer_library_suggestion(session, rec, io, actor_name)
        if adv is not None:
            try:
                _advisor_proposal_step(session, rec, io, adv, actor_name)
            except Exception as e:
                io.write(f"Advisor proposal step skipped: {e}")
        while True:
            qkey, prompt = _highest_value_question(rec, session)
            if qkey == "done":
                # M5: closure suggestions run AFTER elections, before the
                # comment — the advisor sees what the interview produced.
                if adv is not None:
                    try:
                        _advisor_closure_step(session, rec, io, adv, actor_name)
                    except Exception as e:
                        io.write(f"Advisor closure step skipped: {e}")
                # F5: comment accept/edit lives inside retry handling — §13.2
                # refusal re-prompts; unit stays open; walk continues.
                assert session.state is not None
                unit = session.state.units[rec.requirement_id]
                proposed = assemble_comment(
                    unit,
                    org_name="the evaluated organization",
                    facts=session.state.facts,
                )
                hits = prohibited_language_hits(proposed)
                io.write(f"Proposed comment (§13.1): {proposed}")
                if hits:
                    io.write(f"  (note: prohibited-language hits after soften: {hits})")
                while True:
                    edit = _sub_ask(
                        session, io, rec.requirement_id, "comment.review",
                        "Accept comment? [y/edit text/skip]: ", actor_name,
                    )
                    if edit is None:
                        # AR3: quit/EOF here is a cancel — never an edited
                        # comment reading "quit".
                        io.write("Cancelled — comment left unset.")
                        break
                    try:
                        if edit.lower() in ("y", "yes", ""):
                            session.set_axes(
                                rec.requirement_id,
                                actor_name=actor_name,
                                comment=proposed,
                                comment_status="accepted",
                                election=False,
                            )
                            break
                        if edit.lower() == "skip":
                            break
                        # free-text edit — §13.2 may refuse; re-prompt
                        session.set_axes(
                            rec.requirement_id,
                            actor_name=actor_name,
                            comment=edit,
                            comment_status="edited",
                            election=False,
                        )
                        break
                    except SessionError as e:
                        msg = str(e)
                        if "13.2" in msg or "prohibited" in msg.lower():
                            io.write(f"Comment refused ({msg}). Please edit again.")
                            continue
                        io.write(f"Could not store comment ({e}). Please try again.")
                        continue
                break

            ans = io.ask(prompt)
            # Stage A: retain raw answer before mapping
            session.record_answer(
                rec.requirement_id, qkey, ans, actor_name=actor_name
            )
            if ans.lower() in ("quit", "q", "exit"):
                # quit mid-unit → TBD with reason (never silence). N4: this
                # runs outside the retry loop — a refusal (e.g. carried
                # legacy comment) must not crash the walk teardown.
                try:
                    session.set_axes(
                        rec.requirement_id,
                        actor_name=actor_name,
                        applicability="tbd",
                        applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                        enforce_decision=False,
                    )
                    io.write("Quit mid-unit: recorded TBD(customer_input_missing).")
                except SessionError as e:
                    io.write(f"Quit mid-unit (TBD not recorded: {e}).")
                _progress_screen(session, io)
                return session
            if ans.lower() in ("skip",):
                try:
                    session.set_axes(
                        rec.requirement_id,
                        actor_name=actor_name,
                        applicability="tbd",
                        applicability_tbd_reason=TBDReason.CUSTOMER_INPUT_MISSING,
                        enforce_decision=False,
                    )
                    io.write("Skipped: TBD(customer_input_missing).")
                except SessionError as e:
                    io.write(f"Skipped (TBD not recorded: {e}).")
                break
            try:
                _apply_answer(session, rec, qkey, ans, actor_name, io)
            except (SessionError, ValueError) as e:
                # M2/F5: re-prompt on invalid free-text; no bare Exception
                io.write(f"Could not apply answer ({e}). Please try again.")
                continue
        done += 1

    _progress_screen(session, io)

    if export_dir:
        # F2 + Stage E: dual products when available. M4: the walk's export
        # is the operator's WORKING COPY — always DRAFT-watermarked; the
        # releasable path is `oracle disposition export` without
        # --include-draft, which refuses unaccepted rows.
        try:
            from oracle.disposition.export import export_dual_products

            paths = export_dual_products(
                session, records, export_dir, include_draft=True
            )
        except ExportError as e:
            io.write(f"Export refused: {e}")
            return session
        except Exception:
            try:
                paths = export_all(
                    session, records, export_dir, include_draft=True
                )
            except ExportError as e:
                io.write(f"Export refused: {e}")
                return session
        meta = stamp_meta(session)
        session.record_export(
            {**meta, "paths": {k: str(v) for k, v in paths.items()}}, actor_name
        )
        io.write(f"Exported matrix suite to {export_dir}")

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
        advisor=bool(getattr(args, "advisor", False)),
        live_advisor=bool(getattr(args, "live_advisor", False)),
        allow_builtin=bool(getattr(args, "allow_builtin", False)),
    )
