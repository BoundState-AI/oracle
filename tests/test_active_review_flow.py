"""The active review flow must not depend on Google credentials or models."""
import os
from unittest.mock import patch
from oracle import oracle2
from oracle.cli import _configured_review_models
from eval.live.run_live_eval import _check_keys


def test_active_models_exclude_dormant_gemini():
    assert oracle2.REQUIRED_REVIEWERS == ("fran", "codex", "grok")
    with patch.dict(oracle2.ORACLE_ROSTER, {"gemini": object()}):
        models = _configured_review_models()
    assert len(models) == 5


def test_live_eval_needs_no_google_key():
    with patch.dict(os.environ, {
        "ANTHROPIC_API_KEY": "fixture", "OPENAI_API_KEY": "fixture",
        "XAI_API_KEY": "fixture",
    }, clear=True):
        assert _check_keys() == []
