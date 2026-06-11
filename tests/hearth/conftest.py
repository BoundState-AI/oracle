"""Shared fixtures for the HEARTH Phase-1 suite (spec v0.3 §12)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"

GREYROCK_FIXTURE = FIXTURES / "BDB24-6-24_greyrock_2026-06-11_SYNTHETIC.txt"
CANARY_BUYERPACK = FIXTURES / "buyerpack_canary.json"

# Stable date for engine runs so effective-window filtering is deterministic
# in tests regardless of when CI runs (Grey Rock document date, §2.5).
RUN_DATE = date(2026, 6, 11)


def make_rule(
    rule_id: str,
    category: str,
    payload: dict[str, Any],
    *,
    status: str = "provisional",
    effective_from: str = "2024-08-17",
    source: str = "synthetic test rule",
) -> dict[str, Any]:
    """Build a signed micro-rule dict for in-test packs."""
    from hearth.packs.signing import sign_rule_dict

    rule = {
        "rule_id": rule_id,
        "category": category,
        "status": status,
        "effective_from": effective_from,
        "effective_to": None,
        "source": source,
        "authority_review": None,
        "signature": "UNSIGNED",
        "payload": payload,
    }
    rule["signature"] = sign_rule_dict(rule)
    return rule


def make_pack(rules: list[dict[str, Any]], county: str = "TestCounty") -> "Any":
    """Build a validated in-memory JurisdictionPack from signed rule dicts."""
    from hearth.data import JurisdictionPack

    return JurisdictionPack.model_validate(
        {
            "jurisdiction": {"state": "CO", "county": county, "version": "2026.06"},
            "governance": {
                "owner": "Dr. Joseph Wilde",
                "monitored_sources": ["synthetic"],
                "update_sla_days": 30,
                "status": "provisional",
            },
            "rules": rules,
        }
    )


@pytest.fixture
def fee_rule_pack():
    """Smallest executable pack: one clause_regex fee rule."""
    return make_pack(
        [
            make_rule(
                "CO-TEST-FEE-001",
                "commission_norm",
                {
                    "summary": "Pre-filled buyer-broker fee percentage.",
                    "detection": {
                        "type": "clause_regex",
                        "all_of": [
                            r"(?:success fee|compensation|commission)",
                            r"(?P<fee_pct>\d+(?:\.\d+)?)\s*(?:%|percent)",
                        ],
                    },
                    "finding": {
                        "category": "fee",
                        "severity": "warn",
                        "default_analysis": "Compensation is negotiable and not set by law.",
                        "exposure": None,
                    },
                },
            )
        ]
    )
