#!/usr/bin/env python3
"""
Module: oracle.tailor.cli
Purpose: Serve requirements one at a time, work with the user, record decisions.

    py -m oracle.tailor <pack.json> --session my.json --operator "j.wilde"
    py -m oracle.tailor --resume my.json

Safety Critical: no — advisory only, per spec D-1
Financially Critical: no

__safety_critical__: bool = False

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = False

import argparse
import logging
import sys
import textwrap
from pathlib import Path
from typing import Optional

from oracle.disposition.codes import DISPOSITION_CODES, DispositionCode, OPENSubReason
from oracle.tailor.advisor import Advisor, AdvisorError, AnthropicBackend, Proposal
from oracle.tailor.session import Requirement, TailorError, TailorSession

LOGGER = logging.getLogger("oracle.tailor.cli")

WRAP = 78
RULE = "─" * WRAP

HELP = """\
  CW | MI | EX | NA | OPEN   record that code (you'll be asked for the rationale)
  a                          accept the advisor's proposal and its draft rationale
  ?                          ask the advisor about this requirement
  n / p                      next / previous requirement
  g <id>                     go to a requirement (e.g. g AMR-45)
  s                          status — progress and tally
  u                          undo the decision on this requirement
  q                          save and quit
"""


def _p(text: str = "") -> None:
    """Write to stdout. WHY not logging: this is the user interface."""
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _wrap(text: str, indent: str = "  ") -> str:
    return "\n".join(
        textwrap.fill(line, WRAP, initial_indent=indent, subsequent_indent=indent)
        if line.strip()
        else ""
        for line in text.splitlines()
    )


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "q"


# ── rendering ───────────────────────────────────────────────────────────────


def show_requirement(s: TailorSession, req: Requirement) -> None:
    pos = s.cursor + 1
    decided = s.decisions.get(req.id)
    _p()
    _p(RULE)
    head = f"{req.tag or req.id}   §{req.section}"
    if req.page:
        head += f"   p.{req.page}"
    head += f"      [{pos}/{s.total}]"
    _p(head)
    _p(RULE)
    body = req.shall_text or f"{req.subject} shall {req.requirement}"
    _p(_wrap(body))
    if decided:
        _p()
        _p(f"  RECORDED: {decided.code}"
           + (f" ({decided.open_sub_reason})" if decided.open_sub_reason else ""))
        _p(_wrap(decided.rationale, indent="    "))


def show_proposal(pr: Proposal) -> None:
    _p()
    if pr.is_question:
        _p("  ADVISOR — cannot propose; this turns on a decision not yet made")
    else:
        _p(f"  ADVISOR — proposes {pr.code}"
           + (f" ({pr.open_sub_reason})" if pr.open_sub_reason else "")
           + f"   [{pr.band}]")
    if pr.basis:
        _p(_wrap(pr.basis, indent="    "))
    if pr.reasoning:
        _p()
        _p(_wrap(pr.reasoning, indent="    "))
    if pr.draft_rationale:
        _p()
        _p("    draft rationale:")
        _p(_wrap(pr.draft_rationale, indent="      "))
    if pr.questions:
        _p()
        _p("    needs an answer from you:")
        for q in pr.questions:
            _p(_wrap(f"- {q}", indent="      "))
    if pr.evidence_needed:
        _p()
        _p("    would settle it:")
        for e in pr.evidence_needed:
            _p(_wrap(f"- {e}", indent="      "))


def show_status(s: TailorSession) -> None:
    tally = s.tally()
    _p()
    _p(f"  {s.decided_count}/{s.total} decided"
       f"   ({s.total - s.decided_count} remaining)")
    _p("  " + "   ".join(f"{k} {v}" for k, v in tally.items() if v))
    remaining = [r.tag or r.id for r in s.undecided()][:8]
    if remaining:
        _p(f"  next up: {', '.join(remaining)}"
           + (" …" if s.total - s.decided_count > 8 else ""))


# ── recording ───────────────────────────────────────────────────────────────


def record_code(s: TailorSession, code_str: str, pr: Optional[Proposal]) -> bool:
    """Prompt for the rationale and record. Returns True if recorded."""
    try:
        code = DispositionCode(code_str.upper())
    except ValueError:
        _p(f"  not a code: {code_str}")
        return False

    sub = None
    if code is DispositionCode.OPEN:
        sub = _prompt_sub_reason(pr)
        if sub is None:
            return False

    default = pr.draft_rationale if pr and pr.code is code else ""
    if default:
        _p()
        _p("  draft rationale (enter to accept, or type your own):")
        _p(_wrap(default, indent="    "))
    rationale = _ask("  rationale> ").strip() or default
    if not rationale:
        _p("  a rationale is required — nothing recorded")
        return False

    try:
        s.record(code, rationale, open_sub_reason=sub)
        s.save()
    except TailorError as exc:
        _p(f"  {exc}")
        return False
    _p(f"  recorded {code}" + (f" ({sub})" if sub else ""))
    return True


def _prompt_sub_reason(pr: Optional[Proposal]) -> Optional[OPENSubReason]:
    """OPEN requires exactly one sub-reason — no free text, no default."""
    options = list(OPENSubReason)
    _p()
    _p("  OPEN requires a sub-reason:")
    for i, r in enumerate(options, 1):
        mark = " (advisor)" if pr and pr.open_sub_reason is r else ""
        _p(f"    {i}. {r}{mark}")
    raw = _ask("  number> ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    _p("  no sub-reason chosen — nothing recorded")
    return None


# ── loop ────────────────────────────────────────────────────────────────────


def run(s: TailorSession, advisor: Optional[Advisor], auto_advise: bool) -> int:
    _p()
    _p(f"  {s.standard_id} — {s.total} requirements, {s.decided_count} already decided")
    _p("  'h' for commands, 'q' to save and quit")

    proposal: Optional[Proposal] = None
    shown_for: Optional[str] = None

    while True:
        req = s.current()
        if req is None:
            _p()
            _p("  end of pack.")
            show_status(s)
            if _ask("  quit? [Y/n] ").lower() in ("", "y", "yes"):
                s.save()
                return 0
            s.seek(0)
            continue

        if shown_for != req.id:
            show_requirement(s, req)
            proposal = None
            shown_for = req.id
            if advisor and auto_advise and req.id not in s.decisions:
                proposal = _advise(s, advisor, req)

        cmd = _ask("\n  > ").strip()
        if not cmd:
            continue
        head, _, arg = cmd.partition(" ")
        head = head.lower()

        if head in ("q", "quit"):
            s.save()
            _p(f"  saved {s.session_path}  ({s.decided_count}/{s.total} decided)")
            return 0
        if head in ("h", "help", "?") and head != "?":
            _p(HELP)
        elif head == "?":
            if not advisor:
                _p("  no advisor configured (set ANTHROPIC_API_KEY, or --no-advisor)")
            else:
                proposal = _advise(s, advisor, req, question=arg or None)
        elif head == "a":
            if not proposal:
                _p("  no proposal to accept — press '?' first")
            elif proposal.is_question:
                _p("  the advisor is asking, not proposing — answer it or pick a code")
            elif record_code(s, proposal.code.value, proposal):
                s.advance_to_next_undecided()
                shown_for = None
        elif head.upper() in DISPOSITION_CODES:
            if record_code(s, head, proposal):
                s.advance_to_next_undecided()
                shown_for = None
        elif head == "n":
            s.seek(s.cursor + 1)
            shown_for = None
        elif head == "p":
            s.seek(s.cursor - 1)
            shown_for = None
        elif head == "g":
            if not s.seek_id(arg):
                _p(f"  no requirement matching {arg!r}")
            else:
                shown_for = None
        elif head == "s":
            show_status(s)
        elif head == "u":
            if s.clear(req.id):
                s.save()
                _p("  decision cleared")
                shown_for = None
            else:
                _p("  nothing recorded for this requirement")
        else:
            _p(f"  unknown command {head!r} — 'h' for help")


def _advise(
    s: TailorSession,
    advisor: Advisor,
    req: Requirement,
    question: Optional[str] = None,
) -> Optional[Proposal]:
    prior = tuple((uid, d.code.value) for uid, d in s.decisions.items())
    _p("  thinking…")
    try:
        pr = advisor.propose(req, prior)
    except AdvisorError as exc:
        # Never swallowed: an advisor failure must not look like "no opinion".
        _p(f"  advisor unavailable: {exc}")
        return None
    show_proposal(pr)
    return pr


# ── entry ───────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="oracle.tailor",
        description="Tailor a standard one requirement at a time.",
    )
    ap.add_argument("pack", nargs="?", type=Path, help="rule pack JSON")
    ap.add_argument("--session", type=Path, help="session file (default: <pack>.tailor.json)")
    ap.add_argument("--resume", type=Path, help="resume an existing session file")
    ap.add_argument("--operator", default="", help="who is deciding (recorded on every decision)")
    ap.add_argument("--scope", type=Path, help="text file describing the declared scope")
    ap.add_argument("--no-advisor", action="store_true", help="run without model proposals")
    ap.add_argument("--no-auto", action="store_true", help="don't auto-propose; press '?'")
    ap.add_argument("--model", default=None, help="override the advisor model")
    ap.add_argument("--effort", default=None, help="low|medium|high|xhigh|max")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    try:
        if args.resume:
            s = TailorSession.resume(args.resume)
        elif args.pack:
            session_path = args.session or args.pack.with_suffix(".tailor.json")
            operator = args.operator or _ask("  your name (recorded on decisions)> ")
            if not operator:
                _p("  an operator name is required")
                return 2
            s = TailorSession.start(args.pack, session_path, operator)
        else:
            ap.error("give a pack, or --resume a session")
            return 2
    except TailorError as exc:
        _p(f"  {exc}")
        return 1

    advisor = None
    if not args.no_advisor:
        scope = args.scope.read_text(encoding="utf-8") if args.scope else ""
        backend = AnthropicBackend(
            **{k: v for k, v in (("model", args.model), ("effort", args.effort)) if v}
        )
        advisor = Advisor(backend=backend, standard_id=s.standard_id, scope_notes=scope)

    s.advance_to_next_undecided()
    return run(s, advisor, auto_advise=not args.no_auto)


if __name__ == "__main__":
    sys.exit(main())
