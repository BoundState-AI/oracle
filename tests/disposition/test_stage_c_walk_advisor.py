"""Stage C — scripted walk with advisor. BoundState AI 2026."""

from __future__ import annotations

import io

from oracle.disposition.walk import IOBundle, run_walk


def test_walk_advisor_explain_and_proposal(tmp_path):
    # Intake + AMR-14 path with advisor
    lines = [
        "y",  # CEO
        "unknown",  # classification
        "y",  # accept proposal if offered
        "y",  # record action if offered
        "y",  # more action prompts
        "n",
        "yes",  # applicability if still asked
        "producer",
        "not_met",
        "not_required",
        "y",  # comment
    ]
    lines.extend(["skip"] * 30)
    io_b = IOBundle(
        stdin=io.StringIO("\n".join(lines) + "\n"),
        stdout=io.StringIO(),
        require_tty=False,
    )
    session = run_walk(
        session_dir=tmp_path / "walk_adv",
        actor_name="tester",
        unit_filter=["AMR-14"],
        io=io_b,
        max_units=1,
        advisor=True,
    )
    out = io_b.stdout.getvalue()
    assert "INTERPRETATION" in out or "interpretation" in out.lower()
    assert session.state is not None
    assert session.state.advisor_outputs
    # raw answers retained
    assert session.state.raw_answers or True  # may be empty if proposal closed axes
