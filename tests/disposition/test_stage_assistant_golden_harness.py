"""
115-row golden harness (Fran acceptance) — wired for 3-AMR golden now.

Full corpus loader ready when scrubbed engagement records land from operator.
Reconciliation targets (pending corpus):
  readiness 2 Met / 39 Not Met with Plan / 34 TBD / 18 program actions /
  21 Technical N/A / 1 Not Yet Due
  contract 85 CW / 6 MI / 7 EX / 17 NA
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from oracle.disposition.export import count_by_export_label, build_matrix_rows
from oracle.disposition.golden import run_golden_session
from oracle.disposition.packs import load_rdw_default_packs
from oracle.disposition.readiness import map_readiness, readiness_counts
from oracle.disposition.session import DispositionSession


def load_engagement_corpus(path: Path | str) -> Optional[dict[str, Any]]:
    """Loader for full 115-row scrubbed corpus when present; else None."""
    p = Path(path)
    if not p.is_file():
        return None
    import json

    return json.loads(p.read_text(encoding="utf-8"))


def test_three_amr_golden_harness(tmp_path):
    """Wire harness against 3-AMR golden; full corpus blocked pending operator data."""
    run_golden_session(tmp_path / "g", export_dir=tmp_path / "g-out")
    s = DispositionSession(tmp_path / "g")
    s.resume(actor_name="golden-operator", repin=True)
    for uid in list(s.units_needing_rereview()):
        s.clear_rereview(uid, actor_name="op")
    recs, _ = load_rdw_default_packs(repin=True)
    records = {r.requirement_id: r for r in recs}
    rows = build_matrix_rows(s, records)
    contract = count_by_export_label(rows)
    # Golden focuses AMR-1/14/17 labels
    labels = {
        uid: s.state.units[uid].export_label().value
        for uid in ("AMR-1", "AMR-14", "AMR-17")
    }
    assert labels["AMR-17"] == "TBD"
    assert labels["AMR-14"] == "Open/Not Met"
    assert labels["AMR-1"] == "Open/Not Met"

    readiness = []
    for uid in ("AMR-1", "AMR-14", "AMR-17"):
        readiness.append(
            map_readiness(
                s.state.units[uid],
                s.actions_for_unit(uid),
                has_qualifying_evidence=s.has_qualifying_meet_evidence(
                    s.state.units[uid]
                ),
            )
        )
    rc = readiness_counts(readiness)
    assert sum(rc.values()) == 3
    # Full corpus not present
    assert load_engagement_corpus(tmp_path / "missing_corpus.json") is None
    assert contract  # counts computed at render
