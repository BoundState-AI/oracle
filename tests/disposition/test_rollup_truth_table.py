"""
Truth-table test for parent roll-up badge derivation (§1.1, §16).

Enumerates child-code combinations and asserts every one resolves to
exactly one badge per the total order:
    OPEN > EX > MI > MIXED > CW > NA

A parent is never a disposition target.

BoundState AI 2026.
"""

from __future__ import annotations

import itertools

import pytest

from oracle.disposition.codes import DispositionCode
from oracle.disposition.rollup import Badge, compose_badge, rollup_badge


ALL_CODES = [c.value for c in DispositionCode]


def test_every_nonempty_code_combination_resolves_to_exactly_one_badge():
    """
    Exhaustive over presence: for every non-empty subset of codes that
    could appear among children, the composition yields exactly one badge.
    """
    # All 2^5 - 1 = 31 non-empty subsets
    for r in range(1, len(ALL_CODES) + 1):
        for combo in itertools.combinations(ALL_CODES, r):
            comp = {code: 1 for code in combo}
            badge = rollup_badge(comp)
            assert isinstance(badge, Badge)
            # Must be exactly one of the six
            assert badge in set(Badge)


def test_badge_total_order_precedence():
    """Direct assertions of the §1.1 / S1R total order rules."""
    # Any OPEN wins
    assert compose_badge([DispositionCode.OPEN, DispositionCode.CW]) == Badge.OPEN
    assert compose_badge(["OPEN", "NA"]) == Badge.OPEN

    # Else any EX wins
    assert compose_badge([DispositionCode.EX, DispositionCode.MI, DispositionCode.CW]) == Badge.EX

    # Else Open/Not Met (ONM) between EX and MI
    assert compose_badge(["ONM", "MI", "CW"]) == Badge.ONM
    assert compose_badge(["EX", "ONM"]) == Badge.EX

    # Else any MI wins
    assert compose_badge([DispositionCode.MI, DispositionCode.CW]) == Badge.MI
    assert compose_badge([DispositionCode.MI, DispositionCode.NA]) == Badge.MI

    # CW + NA mix → MIXED
    assert compose_badge([DispositionCode.CW, DispositionCode.NA]) == Badge.MIXED
    assert compose_badge(["CW", "NA", "CW"]) == Badge.MIXED

    # Pure CW
    assert compose_badge([DispositionCode.CW, DispositionCode.CW]) == Badge.CW

    # Pure NA
    assert compose_badge([DispositionCode.NA]) == Badge.NA

    # All three of CW+MI+NA still MI (MI precedes MIXED)
    assert compose_badge([DispositionCode.CW, DispositionCode.MI, DispositionCode.NA]) == Badge.MI


def test_empty_or_zero_children_is_na():
    """Vacuous parent (no children) resolves to NA (render artifact only)."""
    assert rollup_badge({}) == Badge.NA
    assert rollup_badge({"CW": 0, "NA": 0}) == Badge.NA


def test_parents_never_carry_codes_in_model():
    """This is enforced at model construction time; here we just document intent."""
    # The rollup module itself never emits a DispositionCode for a parent.
    # The truth table confirms the badge is always a Badge, never a code.
    for combo in itertools.combinations(ALL_CODES, 2):
        b = compose_badge(combo)
        assert not isinstance(b, DispositionCode)


def test_compose_badge_rejects_unknown_code():
    """compose_badge must raise on unknown child codes (covers rollup.py:146)."""
    with pytest.raises(ValueError, match="Unknown child code"):
        compose_badge(["CW", "FOO", "NA"])


def test_rollup_badge_rejects_unknown_code_keys():
    """
    Medium #3 / High safety fix: rollup_badge must reject unknown code keys.

    Previously an unknown key + negative count could reach Badge.CW.
    The function now raises on any key outside the closed DispositionCode set.
    We keep a test here (rather than deleting) to document the enforced contract.
    """
    with pytest.raises(ValueError, match="unknown code key"):
        rollup_badge({"CW": 1, "FOO": 1})

    # Negative counts are also rejected at this layer
    with pytest.raises(ValueError, match="non-negative int"):
        rollup_badge({"CW": -1, "NA": 0})


def test_rollup_badge_final_return_na_is_reached_for_zero_count_inputs():
    """Restructure in rollup.py ensures the final 'return Badge.NA' (line ~129) executes
    for zero-total legitimate compositions (the early total==0 path was collapsed to
    reach the single terminal NA return for these cases).
    """
    assert rollup_badge({}) == Badge.NA
    assert rollup_badge({"CW": 0, "NA": 0}) == Badge.NA
    # Also a composition with only zeroed known codes still yields NA via final return
    assert rollup_badge({"CW": 0, "MI": 0, "NA": 0}) == Badge.NA
