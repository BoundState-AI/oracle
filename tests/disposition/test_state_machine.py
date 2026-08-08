"""Tests for oracle.disposition.state (workflow_state machine per §7.1). BoundState AI 2026.

Lightweight header per repo convention for test modules.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oracle.disposition.models import DispositionUnit, Locator, SCHEMA_VERSION, RULE_VERSION, transition_unit
from oracle.disposition.state import Actor, apply_transition, is_machine_actor


def test_machine_actor_restriction():
    """Machine actors may set only 'proposed'."""
    machine = Actor(name="proposal-bot", is_machine=True)

    # Legal: machine proposes
    new_state = apply_transition("proposed", "proposed", machine)
    assert new_state == "proposed"

    # Illegal: machine cannot confirm, approve, or reject
    for target in ("human_confirmed", "release_approved", "rejected"):
        with pytest.raises(ValueError, match="Machine actor"):
            apply_transition("proposed", target, machine)  # type: ignore[arg-type]


def test_human_transitions_legal():
    """Named human actors can perform every legal transition."""
    human = Actor(name="j.wilde")

    # proposed → human_confirmed
    assert apply_transition("proposed", "human_confirmed", human) == "human_confirmed"

    # human_confirmed → release_approved
    assert apply_transition("human_confirmed", "release_approved", human) == "release_approved"

    # proposed → rejected
    assert apply_transition("proposed", "rejected", human) == "rejected"

    # human_confirmed → rejected
    assert apply_transition("human_confirmed", "rejected", human) == "rejected"


def test_illegal_transitions_raise():
    """Every illegal transition raises ValueError."""
    human = Actor(name="reviewer")

    illegal = [
        ("human_confirmed", "proposed"),
        ("release_approved", "proposed"),
        ("release_approved", "human_confirmed"),
        ("rejected", "proposed"),
        ("rejected", "human_confirmed"),
        ("rejected", "release_approved"),
        ("proposed", "release_approved"),  # must go through human_confirmed
    ]
    for cur, tgt in illegal:
        with pytest.raises(ValueError, match="Illegal transition"):
            apply_transition(cur, tgt, human)  # type: ignore[arg-type]


def test_terminal_states_have_no_outbound():
    """release_approved and rejected are terminal."""
    human = Actor(name="ops")
    for terminal in ("release_approved", "rejected"):
        with pytest.raises(ValueError, match="Illegal transition|terminal"):
            apply_transition(terminal, "proposed", human)  # type: ignore[arg-type]


def test_human_must_have_name():
    """Human actors require a non-empty name (enforced at construction)."""
    # Actor construction itself rejects empty/whitespace names.
    with pytest.raises(ValueError, match="non-empty string"):
        Actor(name="   ", is_machine=False)

    with pytest.raises(ValueError, match="non-empty string"):
        Actor(name="", is_machine=False)

    # A constructed nameless machine is also rejected (belt-and-suspenders)
    with pytest.raises(ValueError, match="non-empty string"):
        Actor(name="", is_machine=True)


def test_is_machine_actor_helper():
    assert is_machine_actor(Actor("bot", is_machine=True)) is True
    assert is_machine_actor(Actor("human", is_machine=False)) is False


def test_apply_transition_returns_target_for_all_legal_human_paths():
    """Explicitly assert the returned state to ensure the final 'return target' (state.py) executes."""
    human = Actor(name="reviewer-7")
    assert apply_transition("proposed", "human_confirmed", human) == "human_confirmed"
    assert apply_transition("human_confirmed", "release_approved", human) == "release_approved"
    assert apply_transition("proposed", "rejected", human) == "rejected"
    assert apply_transition("human_confirmed", "rejected", human) == "rejected"


def test_apply_transition_machine_proposed_success_path_hits_return():
    """Machine-proposed path must also execute the terminal return."""
    machine = Actor(name="ingest-bot-01", is_machine=True)
    result = apply_transition("proposed", "proposed", machine)
    assert result == "proposed"


def test_apply_transition_human_name_belt_inside_function_is_exercised():
    """Force a post-construction empty name on a frozen Actor to hit the belt-and-suspenders
    human name check inside apply_transition (the block after the illegal-transition guard).
    """
    human = Actor(name="temp-reviewer")
    # Bypass frozen + __post_init__ to simulate a name that becomes falsy after the Actor was accepted.
    # This exercises the defensive runtime check inside apply_transition for humans.
    object.__setattr__(human, "name", "   ")
    with pytest.raises(ValueError, match="non-empty name"):
        apply_transition("proposed", "human_confirmed", human)  # type: ignore[arg-type]


def test_apply_transition_unknown_current_state_raises():
    """Directly exercises the 'Unknown current state' guard (state.py:93)."""
    human = Actor(name="ops")
    with pytest.raises(ValueError, match="Unknown current state"):
        apply_transition("not_a_state", "proposed", human)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------
# High #3 regression (Atlas R2): unit_boundary_confirmed_by required at construction
# ----------------------------------------------------------------------------

def test_boundary_confirmation_required_at_construction_high3():
    """High #3 (Atlas R2) / §7.3: a non-rollup unit carrying a code must have
    non-blank unit_boundary_confirmed_by at construction time.

    Per §7.3, boundaries must be confirmed before any disposition is proposed.
    The model validator enforces this on every non-rollup DispositionUnit with a code.
    Roll-ups are exempt (they carry no code and are never disposition targets).
    """
    from oracle.disposition.codes import DispositionCode

    loc = Locator(
        standard="NASA-STD-6030",
        revision="Baseline",
        section="4.2",
        page=17,
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )

    # Construction without a non-blank confirmer must fail
    with pytest.raises(ValidationError, match="unit_boundary_confirmed_by is required"):
        DispositionUnit(
            unit_id="AMR-X1",
            requirement_text="The supplier shall ...",
            locator=loc,
            code=DispositionCode.CW,
            proposer="oracle/proposal-v1",
            schema_version=SCHEMA_VERSION,
            rule_version=RULE_VERSION,
            # intentionally omitted
        )

    # Supplying a non-blank confirmer succeeds and the unit can then transition
    u = DispositionUnit(
        unit_id="AMR-X1",
        requirement_text="The supplier shall ...",
        locator=loc,
        code=DispositionCode.CW,
        proposer="oracle/proposal-v1",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
        unit_boundary_confirmed_by="extractor-human-42",
    )
    human = Actor(name="reviewer-9")
    u2 = transition_unit(u, "human_confirmed", human)
    assert u2.workflow_state == "human_confirmed"

    # Roll-ups remain exempt (no code)
    u_roll = DispositionUnit(
        unit_id="AMR-50",
        is_rollup=True,
        code=None,
        composition_vector={"CW": 2},
        requirement_text="rollup",
        locator=loc,
        proposer="oracle/proposal-v1",
        schema_version=SCHEMA_VERSION,
        rule_version=RULE_VERSION,
    )
    assert u_roll.is_rollup is True
    assert u_roll.code is None