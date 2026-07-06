"""Model-router and live-pass invariants (spec v0.1 §55, v0.2 I5/I9/I10/I12).

Fake chat models exercise the full JSON-contract path — no network, no
monkeypatching. Load-bearing: the adversary can never share a provider
with the builder, malformed model output becomes a refusal (never
partial silent output), invented citations are rejected visibly, and
model records stay out of the evidence fingerprint.
"""

from __future__ import annotations

import json

import pytest

from dude.data import (
    Case,
    CreatedBy,
    GateMode,
    Hypothesis,
    HypothesisArchetype,
)
from dude.pipeline.engine import analyze, capture
from dude.pipeline.live_passes import (
    LiveAdversary,
    LiveHypotheses,
    LiveSeparator,
    build_live_passes,
)
from dude.pipeline.passes import PassSet
from dude.pipeline.router import ModelRouter
from dude.store.jsonl import CaseStore


class FakeChat:
    """Scripted ChatModel: returns queued replies in order."""

    def __init__(self, provider: str, replies: list[str]) -> None:
        self.provider = provider
        self.replies = list(replies)
        self.calls = 0

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        self.calls += 1
        return self.replies.pop(0) if self.replies else "{}"


def _bundle(tmp_path, text="Jerry replied. Gabig emailed two hours later."):
    store = CaseStore(root=tmp_path / "dude_home")
    case = Case(title="t")
    store.create_case(case)
    capture(store, case.id, text)
    return store, store.load_case(case.id)


class TestRouterIndependence:
    def test_same_provider_adversary_is_refused_at_construction(self) -> None:
        """v0.1 §55: no same-provider self-certification, structurally."""
        primary = FakeChat("anthropic", [])
        adversary = FakeChat("anthropic", [])
        with pytest.raises(ValueError, match="different provider"):
            ModelRouter(primary=primary, adversary=adversary)

    def test_single_provider_leaves_adversary_as_visible_stub(self, tmp_path) -> None:
        separator_json = json.dumps({"observations": [], "interpretations": []})
        unknowns_json = json.dumps({"unknowns": []})
        hypotheses_json = json.dumps({"hypotheses": []})
        primary = FakeChat(
            "anthropic", [separator_json, unknowns_json, hypotheses_json]
        )
        passes = build_live_passes(ModelRouter(primary=primary, adversary=None))
        store, bundle = _bundle(tmp_path)
        result = analyze(store, bundle.case.id, passes=passes)
        assert "adversary" in {r.pass_name for r in result.run.refusals}


class TestJsonContracts:
    def test_malformed_output_becomes_refusal_after_retry(self, tmp_path) -> None:
        """v0.2 I12: fail closed — two bad replies, zero fabricated output."""
        chat = FakeChat("anthropic", ["not json at all", "{still: bad"])
        _store, bundle = _bundle(tmp_path)
        output = LiveSeparator(chat).run(bundle)
        assert chat.calls == 2  # exactly one corrective retry
        assert not output.observations
        assert any("invalid JSON" in r.reason for r in output.refusals)

    def test_invented_citation_is_rejected_visibly(self, tmp_path) -> None:
        """No orphan facts, enforced against the model itself."""
        _store, bundle = _bundle(tmp_path)
        real_id = bundle.captures[0].id
        reply = json.dumps(
            {
                "observations": [
                    {"statement": "real", "source_capture_id": real_id},
                    {"statement": "invented", "source_capture_id": "fabricated"},
                ],
                "interpretations": ["Jerry told Gabig"],
            }
        )
        output = LiveSeparator(FakeChat("anthropic", [reply])).run(bundle)
        assert [o.statement for o in output.observations] == ["real"]
        assert any("unknown sources" in r.reason for r in output.refusals)
        assert all(o.created_by is CreatedBy.MODEL for o in output.observations)

    def test_model_records_do_not_change_the_fingerprint(self, tmp_path) -> None:
        """v0.2 I5 end-to-end: a live pass writing model records must not
        re-trigger analysis by itself."""
        reply = json.dumps(
            {"observations": [], "interpretations": ["a model inference"]}
        )
        passes = PassSet(separator=LiveSeparator(FakeChat("anthropic", [reply])))
        store, bundle = _bundle(tmp_path)
        first = analyze(store, bundle.case.id, passes=passes)
        assert first.run.mode is GateMode.NEW_EVIDENCE
        second = analyze(store, bundle.case.id, passes=PassSet())
        assert second.served_prior  # model interpretation didn't move the hash

    def test_missing_adversarial_archetype_is_flagged(self, tmp_path) -> None:
        """v0.2 I9: the hypothesis set must attempt adversarial_cause."""
        reply = json.dumps(
            {
                "hypotheses": [
                    {
                        "title": "boring",
                        "description": "d",
                        "archetype": "boring",
                    }
                ]
            }
        )
        _store, bundle = _bundle(tmp_path)
        output = LiveHypotheses(FakeChat("anthropic", [reply])).run(bundle)
        assert len(output.hypotheses) == 1
        assert any("adversarial-cause" in r.reason for r in output.refusals)


class TestAdversaryAnnotations:
    def test_attacks_supersede_without_rewriting(self, tmp_path) -> None:
        """v0.2 I10: annotation attachment preserves lineage and content."""
        store, bundle = _bundle(tmp_path)
        hypothesis = Hypothesis(
            case_id=bundle.case.id,
            title="Seemann contacted Gabig",
            description="original text",
            archetype=HypothesisArchetype.USER_FAVORED,
        )
        store.append(hypothesis)
        bundle = store.load_case(bundle.case.id)
        reply = json.dumps(
            {
                "attacks": [
                    {
                        "hypothesis_id": hypothesis.id,
                        "attack": "timing alone is correlation, not transmission",
                        "unsupported_links": ["contact between the two"],
                    },
                    {"hypothesis_id": "unknown-id", "attack": "x"},
                ]
            }
        )
        output = LiveAdversary(FakeChat("openai", [reply])).run(bundle)
        assert len(output.hypotheses) == 1
        revised = output.hypotheses[0]
        assert revised.supersedes == hypothesis.id
        assert revised.lineage_id == hypothesis.lineage_id
        assert revised.description == "original text"  # content untouched
        assert len(revised.annotations) == 1
        assert any("unknown hypothesis ids" in r.reason for r in output.refusals)
