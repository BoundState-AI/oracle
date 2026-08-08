"""Stage C: session / fact ledger / event-log replay. BoundState AI 2026."""

from __future__ import annotations

import pytest

from oracle.disposition.eventlog import EventLogError
from oracle.disposition.session import DispositionSession, SessionError


def test_replay_equals_in_memory_state(tmp_path):
    s = DispositionSession(tmp_path / "s1")
    st = s.open(actor_name="alice")
    s.assert_fact(
        key="hardware.process",
        statement="Cold spray",
        author="alice",
        confidence="high",
    )
    s.set_axes(
        "AMR-1",
        actor_name="alice",
        applicability="yes",
        obligated_actor="program",
        organization_responsibility="external",
        implementation_state="not_met",
        approval_state="required",
    )
    snap_facts = dict(s.state.facts)
    snap_units = {k: v.model_dump() for k, v in s.state.units.items() if k == "AMR-1"}

    s2 = DispositionSession(tmp_path / "s1")
    st2 = s2.resume(actor_name="alice")
    assert st2.session_id == st.session_id
    assert s2.state.facts["hardware.process"].statement == snap_facts["hardware.process"].statement
    assert s2.state.units["AMR-1"].applicability == snap_units["AMR-1"]["applicability"]
    assert s2.state.units["AMR-1"].implementation_state == "not_met"


def test_hash_chain_detects_tampering(tmp_path):
    s = DispositionSession(tmp_path / "s2")
    s.open(actor_name="bob")
    s.assert_fact(key="k", statement="v", author="bob")
    log_path = tmp_path / "s2" / "events.jsonl"
    text = log_path.read_text(encoding="utf-8")
    # Tamper a middle character in the first non-empty line's payload
    lines = text.splitlines(True)
    assert lines
    lines[0] = lines[0].replace("session_opened", "session_OPENED")
    log_path.write_text("".join(lines), encoding="utf-8")
    s3 = DispositionSession(tmp_path / "s2")
    with pytest.raises(EventLogError):
        s3.resume(actor_name="bob")


def test_assumption_never_auto_confirms(tmp_path):
    s = DispositionSession(tmp_path / "s3")
    s.open(actor_name="carol")
    s.assert_fact(
        key="ceo.identity",
        statement="Customer is CEO",
        author="carol",
        assumed=True,
        owner="carol",
    )
    with pytest.raises(SessionError, match="assumption"):
        s.assert_fact(
            key="ceo.identity",
            statement="Customer is CEO",
            author="carol",
            assumed=False,
        )
    # Explicit promotion
    f = s.assert_fact(
        key="ceo.identity",
        statement="Customer is CEO (confirmed)",
        author="carol",
        assumed=False,
        confirm_assumption=True,
    )
    assert f.confirmed is True
    assert f.supersedes is not None


def test_supersession_chain(tmp_path):
    s = DispositionSession(tmp_path / "s4")
    s.open(actor_name="dave")
    f1 = s.assert_fact(key="x", statement="one", author="dave")
    f2 = s.assert_fact(key="x", statement="two", author="dave")
    assert f2.supersedes == f1.fact_id
    assert s.state.facts["x"].statement == "two"
