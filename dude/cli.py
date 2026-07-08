#!/usr/bin/env python3
"""
Module: dude.cli
Purpose: Dogfood CLI for the DUDE core (spec v0.2; v0.1 §63).

Commands:
  dude new "<title>"                      — create a case
  dude cases                              — list cases
  dude capture <case> --text "..."        — Stage-1 capture (safety floor first)
  dude event <case> --desc "..." [--pattern-class X] [--silence]
  dude interpret <case> --statement "..."
  dude hypothesis <case> --title T --desc D [--archetype A] [--harm H] [--band B]
  dude trigger --name N --cues a,b,c [--calibration C]
  dude analyze <case>                     — run the pipeline
  dude status <case>                      — case state, gate, patterns, safety
  dude timeline <case>                    — chronological events

Exit codes: 0 success, 2 refusal (mirrors hearth). Print is allowed here:
the CLI is the presentation surface, not library code.

Safety Critical: True — this surface must render crisis resources and
refusals; swallowing either is the cardinal failure mode.
Psychologically Critical: True

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True
__psychologically_critical__: bool = True

import argparse
import logging
import sys
from datetime import datetime, timezone

from dude.core.state import waiting_for_data
from dude.data import (
    Case,
    ConfidenceBand,
    Event,
    HarmClass,
    Hypothesis,
    HypothesisArchetype,
    Interpretation,
    SourceType,
    TriggerCalibration,
    TriggerPattern,
)
from dude.pipeline.engine import analyze, capture
from dude.store.jsonl import CaseStore, StoreError

LOGGER = logging.getLogger("dude.cli")
EXIT_REFUSED = 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    try:
        store = CaseStore()
        return args.func(store, args)
    except StoreError as exc:
        # Never-suppress: a store failure is a refusal on the surface.
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dude", description=__doc__)
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("new", help="create a case")
    p.add_argument("title")
    p.set_defaults(func=_cmd_new)

    p = sub.add_parser("cases", help="list cases")
    p.set_defaults(func=_cmd_cases)

    p = sub.add_parser("capture", help="capture raw input")
    p.add_argument("case_id")
    p.add_argument("--text", required=True)
    p.set_defaults(func=_cmd_capture)

    p = sub.add_parser("event", help="add a confirmed event")
    p.add_argument("case_id")
    p.add_argument("--desc", required=True)
    p.add_argument("--pattern-class", default=None)
    p.add_argument("--silence", action="store_true", help="non-response checkpoint")
    p.set_defaults(func=_cmd_event)

    p = sub.add_parser("interpret", help="record a user interpretation")
    p.add_argument("case_id")
    p.add_argument("--statement", required=True)
    p.set_defaults(func=_cmd_interpret)

    p = sub.add_parser("hypothesis", help="add a hypothesis")
    p.add_argument("case_id")
    p.add_argument("--title", required=True)
    p.add_argument("--desc", required=True)
    p.add_argument(
        "--archetype",
        choices=[a.value for a in HypothesisArchetype],
        default=HypothesisArchetype.OTHER.value,
    )
    p.add_argument(
        "--harm", choices=[h.value for h in HarmClass], default=HarmClass.NONE.value
    )
    p.add_argument(
        "--band",
        choices=[b.value for b in ConfidenceBand],
        default=ConfidenceBand.UNRESOLVED.value,
    )
    p.set_defaults(func=_cmd_hypothesis)

    p = sub.add_parser("trigger", help="add a trigger pattern (active immediately)")
    p.add_argument("--name", required=True)
    p.add_argument("--cues", required=True, help="comma-separated cue substrings")
    p.add_argument(
        "--calibration",
        choices=[c.value for c in TriggerCalibration],
        default=TriggerCalibration.NEUTRAL.value,
    )
    p.set_defaults(func=_cmd_trigger)

    p = sub.add_parser("analyze", help="run analysis")
    p.add_argument("case_id")
    p.set_defaults(func=_cmd_analyze)

    p = sub.add_parser("status", help="case status")
    p.add_argument("case_id")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("timeline", help="chronological events")
    p.add_argument("case_id")
    p.set_defaults(func=_cmd_timeline)

    p = sub.add_parser("pom", help="Personal Operating Manual subsystem")
    pom_sub = p.add_subparsers(required=True)

    pi = pom_sub.add_parser("import", help="ingest a source document")
    pi.add_argument("--source", required=True, help="source title")
    pi.add_argument("--file", required=True, help="path to the document")
    pi.add_argument("--user", default="joseph")
    pi.set_defaults(func=_cmd_pom_import)

    pl = pom_sub.add_parser("items", help="list POM items")
    pl.set_defaults(func=_cmd_pom_items)

    pa = pom_sub.add_parser("audit", help="retrieval audit for a case")
    pa.add_argument("case_id")
    pa.set_defaults(func=_cmd_pom_audit)

    return parser


def _cmd_new(store: CaseStore, args: argparse.Namespace) -> int:
    case = Case(title=args.title)
    store.create_case(case)
    print(case.id)
    return 0


def _cmd_cases(store: CaseStore, args: argparse.Namespace) -> int:  # noqa: ARG001
    for case_id in store.list_case_ids():
        bundle = store.load_case(case_id)
        print(f"{case_id}  [{bundle.case.status.value}]  {bundle.case.title}")
    return 0


def _cmd_capture(store: CaseStore, args: argparse.Namespace) -> int:
    record, scan = capture(store, args.case_id, args.text)
    if scan.crisis:
        print(scan.user_facing_message)
        for resource in scan.resources:
            print(f"  {resource.name}: {resource.contact} — {resource.note}")
    print(f"captured {record.id}")
    return 0


def _cmd_event(store: CaseStore, args: argparse.Namespace) -> int:
    event = Event(
        case_id=args.case_id,
        description=args.desc,
        pattern_class=args.pattern_class,
        is_silence_checkpoint=args.silence,
        source_type=(
            SourceType.SILENCE_CHECKPOINT if args.silence else SourceType.USER_STATEMENT
        ),
        occurred_at=datetime.now(timezone.utc),
    )
    store.append(event)
    print(f"event {event.id}")
    return 0


def _cmd_interpret(store: CaseStore, args: argparse.Namespace) -> int:
    record = Interpretation(case_id=args.case_id, statement=args.statement)
    store.append(record)
    print(f"interpretation {record.id} (stored separately from observations)")
    return 0


def _cmd_hypothesis(store: CaseStore, args: argparse.Namespace) -> int:
    hypothesis = Hypothesis(
        case_id=args.case_id,
        title=args.title,
        description=args.desc,
        archetype=HypothesisArchetype(args.archetype),
        harm_class=HarmClass(args.harm),
        band=ConfidenceBand(args.band),
    )
    store.append(hypothesis)
    print(f"hypothesis {hypothesis.id} (lineage {hypothesis.lineage_id})")
    return 0


def _cmd_trigger(store: CaseStore, args: argparse.Namespace) -> int:
    trigger = TriggerPattern(
        name=args.name,
        cues=[c.strip() for c in args.cues.split(",") if c.strip()],
        calibration=TriggerCalibration(args.calibration),
        user_confirmed=True,
        active=True,
    )
    store.append_trigger(trigger)
    print(f"trigger {trigger.id}")
    return 0


def _cmd_analyze(store: CaseStore, args: argparse.Namespace) -> int:
    from dude.pipeline.live_passes import resolve_passes
    from dude.triggers.assess import resolve_assessor

    result = analyze(
        store, args.case_id, passes=resolve_passes(), assessor=resolve_assessor()
    )
    if result.served_prior:
        from dude.core.loop import mode_message
        from dude.data import GateMode

        print(mode_message(GateMode.NO_NEW_DATA))
    print(result.run.user_facing_summary)
    if result.recommendation:
        rec = result.recommendation
        print(f"\nCriterion: {rec.criterion}")
        for rank, action_id in enumerate(rec.ranked_action_ids, 1):
            print(f"  {rank}. {action_id}")
        for action_id, reason in rec.excluded_action_ids.items():
            print(f"  excluded {action_id}: {reason}")
    return 0


def _cmd_status(store: CaseStore, args: argparse.Namespace) -> int:
    bundle = store.load_case(args.case_id)
    print(f"{bundle.case.title}  [{bundle.case.status.value}]")
    if bundle.analysis_runs:
        last = bundle.analysis_runs[-1]
        waiting = waiting_for_data(last.mode)
        print(f"last run: {last.mode.value} (waiting for data: {waiting})")
        for pattern in last.cumulative_patterns:
            print(
                f"pattern {pattern.pattern_class}: {pattern.event_count} events, "
                f"cumulative {pattern.cumulative_band.value}"
            )
    if bundle.safety_events:
        print(f"safety events: {len(bundle.safety_events)}")
    return 0


def _cmd_timeline(store: CaseStore, args: argparse.Namespace) -> int:
    bundle = store.load_case(args.case_id)
    ordered = sorted(bundle.events, key=lambda e: e.occurred_at or e.recorded_at)
    for event in ordered:
        stamp = (event.occurred_at or event.recorded_at).strftime("%Y-%m-%d %H:%M")
        marker = " [silence]" if event.is_silence_checkpoint else ""
        print(f"{stamp}  {event.description}{marker}")
    return 0


def _cmd_pom_import(store: CaseStore, args: argparse.Namespace) -> int:
    from pathlib import Path

    from dude.pom.pipeline import ExtractionUnavailable, import_source
    from dude.pom.store import PomStore

    content = Path(args.file).read_text(encoding="utf-8")
    pom = PomStore(store)
    try:
        artifact, items = import_source(pom, args.user, args.source, content)
    except ExtractionUnavailable as exc:
        # The source is ingested and hashed; extraction refused visibly.
        print(f"REFUSED (extraction): {exc}", file=sys.stderr)
        print("Source ingested immutably; re-run extraction when a model is configured.")
        return EXIT_REFUSED
    print(f"artifact {artifact.id} sha256={artifact.content_sha256[:16]}…")
    print(f"{len(items)} items extracted (unconfirmed statuses stay unconfirmed)")
    return 0


def _cmd_pom_items(store: CaseStore, args: argparse.Namespace) -> int:  # noqa: ARG001
    from dude.pom.store import PomStore

    for item in PomStore(store).load().items:
        confirmed = "confirmed" if item.user_confirmed else "unconfirmed"
        print(
            f"{item.id}  [{item.category.value}/{item.epistemic_status.value}/"
            f"{confirmed}]  {item.statement}"
        )
    return 0


def _cmd_pom_audit(store: CaseStore, args: argparse.Namespace) -> int:
    from dude.pom.store import PomStore

    for record in PomStore(store).load().retrievals:
        if record.case_id == args.case_id:
            print(
                f"{record.retrieved_at:%Y-%m-%d %H:%M}  item={record.pom_item_id}  "
                f"use={record.allowed_use.value}  why={record.retrieval_reason}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
