"""Token-budget reduction (§7.2) and review-guard tests.

Pins the WS3/WS5 fixes:
  - _apply_budget_reduction degrades per schema (generic → critical/high
    only, GPCM → MUA-relevant only, FAR → drop Tier 2) before dropping
    whole packs, and never truncates silently.
  - _compute_token_budget raises (never sys.exit) on unknown models and
    oversized documents — it runs inside server threads.
  - run_review validates max_rounds before any spend.
"""
from __future__ import annotations

import pytest

from oracle.cli import (
    _apply_budget_reduction,
    _compute_token_budget,
    _estimate_tokens,
    run_review,
)


def _generic_section(name: str = "gen", n_rules: int = 40) -> dict:
    rules = []
    for i in range(n_rules):
        # Alternate severities so reduction has something to drop
        sev = ("critical", "high", "medium", "low")[i % 4]
        rules.append({
            "rule_id": f"RULE-{i:04d}",
            "statement_text": f"The system shall satisfy requirement {i} " + "x" * 120,
            "severity": sev,
            "section": f"1.{i}",
            "obligation_keyword": "shall",
        })
    data = {
        "schema_version": "oracle_generic/v1",
        "rule_pack_id": f"generic-{name}",
        "standard_id": f"STD-{name}",
        "rules": rules,
    }
    from oracle.cli import _render_pack_for_oracle
    label = f"## Authority 1: STD-{name} (pack_id: generic-{name})"
    rendered = _render_pack_for_oracle(data, f"generic-{name}")
    return {
        "label": label,
        "text": f"{label}\n\n{rendered}",
        "data": data,
        "name": name,
        "pack_id": f"generic-{name}",
        "parts": None,
    }


def _gpcm_section(name: str = "gp", n_reqs: int = 40) -> dict:
    reqs = []
    for i in range(n_reqs):
        reqs.append({
            "id": f"stmt-{i:03d}",
            "source_tag": f"MPR {i}",
            "section": f"4.{i}",
            "shall_text": f"Programs shall perform activity {i} " + "y" * 120,
            "mua_relevant": i % 5 == 0,
        })
    data = {
        "schema_version": "gpcm_rulepack/v1",
        "rule_pack_id": f"gpcm-{name}",
        "standard_id": f"GSTD-{name}",
        "requirements": reqs,
    }
    from oracle.cli import _render_pack_for_oracle
    label = f"## Authority 2: GSTD-{name} (pack_id: gpcm-{name})"
    rendered = _render_pack_for_oracle(data, f"gpcm-{name}")
    return {
        "label": label,
        "text": f"{label}\n\n{rendered}",
        "data": data,
        "name": name,
        "pack_id": f"gpcm-{name}",
        "parts": None,
    }


# ---------------------------------------------------------------------------
# Graduated reduction (§7.2 a–d)
# ---------------------------------------------------------------------------

def test_within_budget_no_reduction():
    section = _generic_section(n_rules=4)
    combined, warnings = _apply_budget_reduction([section], budget_tokens=100_000)
    assert warnings == []
    assert "RULE-0003" in combined


def test_generic_reduces_to_critical_high_before_dropping():
    section = _generic_section(n_rules=40)
    full_tokens = _estimate_tokens(section["text"])
    # Budget fits roughly half the pack: severity reduction should suffice
    combined, warnings = _apply_budget_reduction([section], budget_tokens=full_tokens // 2 + 200)

    assert any("medium/low severity rules" in w for w in warnings)
    # Critical/high rules survive; medium/low are gone but ACCOUNTED for
    assert "RULE-0000" in combined            # critical
    assert "RULE-0002" not in combined        # medium
    assert "omitted" in combined.lower()      # never silent


def test_gpcm_reduces_to_mua_relevant():
    section = _gpcm_section(n_reqs=40)
    full_tokens = _estimate_tokens(section["text"])
    combined, warnings = _apply_budget_reduction([section], budget_tokens=full_tokens // 3 + 200)

    assert any("non-MUA" in w for w in warnings)
    assert "stmt-000" in combined             # mua_relevant (i % 5 == 0)
    assert "stmt-001" not in combined         # not MUA-relevant
    assert "omitted" in combined.lower()


def test_whole_pack_drop_keeps_stub_and_warns():
    from oracle.cli import _reduce_section

    sections = [_generic_section("first", 30), _gpcm_section("second", 60)]
    # Budget fits only pack 1's REDUCED form — even after per-schema
    # reduction, pack 2 cannot fit and must become a stub.
    reduced_first, _ = _reduce_section(sections[0])
    budget = _estimate_tokens(reduced_first) + 100
    combined, warnings = _apply_budget_reduction(sections, budget_tokens=budget)

    assert any("omitted from compliance context" in w for w in warnings)
    assert "OMITTED" in combined              # stub visible to reviewers
    assert "STD-first" in combined            # higher-priority pack retained


# ---------------------------------------------------------------------------
# Budget guard raises (not sys.exit)
# ---------------------------------------------------------------------------

def test_oversized_document_raises_value_error():
    huge = "word " * 3_000_000  # ~3.75M tokens, far over every window
    with pytest.raises(ValueError, match="too large"):
        _compute_token_budget(huge)


# ---------------------------------------------------------------------------
# max_rounds guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_rounds", [0, -1, 999])
def test_run_review_rejects_bad_max_rounds(tmp_path, bad_rounds):
    doc = tmp_path / "doc.md"
    doc.write_text("A spec.", encoding="utf-8")
    with pytest.raises(ValueError, match="max_rounds"):
        run_review(
            document_path=doc,
            pack_names=[],
            pack_dir=tmp_path,
            max_rounds=bad_rounds,
        )
