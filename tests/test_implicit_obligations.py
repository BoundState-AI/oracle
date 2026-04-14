"""Tests for Pass 1c: implicit obligation detection."""

from unittest.mock import MagicMock, patch

import pytest

from oracle.shall_extractor import (
    ExtractionResult,
    ShallStatement,
    _normalize_for_dedup,
    _overlaps_existing,
    detect_implicit_obligations,
)


# ---------------------------------------------------------------------------
# Unit tests for dedup helpers
# ---------------------------------------------------------------------------


def test_normalize_for_dedup_lowercases_and_strips():
    assert _normalize_for_dedup("  The System SHALL   operate  ") == "the system shall operate"


def test_normalize_for_dedup_removes_punctuation():
    assert _normalize_for_dedup("reports are due, quarterly.") == "reports are due quarterly"


def test_overlaps_existing_detects_match():
    existing = {"reports are due quarterly"}
    assert _overlaps_existing("Reports are due quarterly.", existing) is True


def test_overlaps_existing_allows_novel_text():
    existing = {"the system shall operate at 5v"}
    assert _overlaps_existing("Personnel hold a SECRET clearance", existing) is False


def test_overlaps_existing_handles_empty_new_text():
    existing = {"something"}
    assert _overlaps_existing("", existing) is True


def test_overlaps_existing_handles_empty_existing():
    existing: set[str] = set()
    assert _overlaps_existing("Novel requirement text here", existing) is False


def test_overlaps_existing_partial_overlap_below_threshold():
    existing = {"the contractor shall submit weekly status reports to the government"}
    # Shares some words but not 60%+
    assert _overlaps_existing("the contractor uses automated tools", existing) is False


# ---------------------------------------------------------------------------
# Integration test for detect_implicit_obligations
# ---------------------------------------------------------------------------


def _make_result(statements=None) -> ExtractionResult:
    return ExtractionResult(
        source_file="test.pdf",
        total_pages=2,
        extraction_date="2026-01-01",
        total_statements=len(statements or []),
        by_type={},
        statements=statements or [],
    )


def _make_statement(id: int, text: str, page: int = 1) -> ShallStatement:
    return ShallStatement(
        id=id,
        page=page,
        section="1.1",
        obligation_keyword="shall",
        obligation_type="mandatory",
        statement_text=text,
        subject="contractor",
        requirement=text,
        context="",
    )


@patch("oracle.shall_extractor._preprocess_page_text", return_value="Testing follows MIL-STD-810.")
@patch("oracle.shall_extractor.fitz")
def test_detect_implicit_adds_new_statements(mock_fitz, mock_preprocess):
    """Test that implicit detection appends new statements to the result."""
    import json

    # Setup mock PDF
    mock_doc = MagicMock()
    mock_doc.__len__ = lambda self: 1
    mock_page = MagicMock()
    mock_page.get_text.return_value = "Testing follows MIL-STD-810. The system operates at 5V."
    mock_doc.__getitem__ = lambda self, idx: mock_page
    mock_fitz.open.return_value = mock_doc

    # Setup mock Anthropic client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = json.dumps({
        "obligations": [
            {
                "statement_text": "Testing follows MIL-STD-810",
                "requirement": "Contractor shall test per MIL-STD-810",
                "subject": "contractor",
                "section": "3.2",
                "confidence": 0.8,
                "keywords": ["testing", "MIL-STD-810"],
                "context": "Implies mandatory test standard compliance",
            }
        ]
    })
    mock_client.messages.create.return_value = mock_response

    existing = [_make_statement(1, "The contractor shall deliver reports monthly")]
    result = _make_result(existing)

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = detect_implicit_obligations(
            result,
            "test.pdf",
            api_key="test-key",
        )

    assert result.total_statements == 2
    implicit_stmts = [s for s in result.statements if s.obligation_type == "implicit"]
    assert len(implicit_stmts) == 1
    assert implicit_stmts[0].obligation_keyword == "(implicit)"
    assert implicit_stmts[0].confidence == 0.8
    assert "MIL-STD-810" in implicit_stmts[0].statement_text


@patch("oracle.shall_extractor._preprocess_page_text", return_value="The contractor shall deliver reports monthly.")
@patch("oracle.shall_extractor.fitz")
def test_detect_implicit_deduplicates_against_existing(mock_fitz, mock_preprocess):
    """Implicit obligations that overlap existing statements are skipped."""
    import json

    mock_doc = MagicMock()
    mock_doc.__len__ = lambda self: 1
    mock_page = MagicMock()
    mock_page.get_text.return_value = "The contractor shall deliver reports monthly."
    mock_doc.__getitem__ = lambda self, idx: mock_page
    mock_fitz.open.return_value = mock_doc

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = json.dumps({
        "obligations": [
            {
                "statement_text": "The contractor shall deliver reports monthly",
                "requirement": "Deliver reports monthly",
                "subject": "contractor",
                "section": "1.1",
                "confidence": 0.9,
                "keywords": ["reports"],
                "context": "duplicate",
            }
        ]
    })
    mock_client.messages.create.return_value = mock_response

    existing = [_make_statement(1, "The contractor shall deliver reports monthly")]
    result = _make_result(existing)

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = detect_implicit_obligations(
            result,
            "test.pdf",
            api_key="test-key",
        )

    # Should still be 1 — the duplicate was skipped
    assert result.total_statements == 1
    assert all(s.obligation_type == "mandatory" for s in result.statements)


@patch("oracle.shall_extractor._preprocess_page_text", return_value="Some text about procedures.")
@patch("oracle.shall_extractor.fitz")
def test_detect_implicit_respects_min_confidence(mock_fitz, mock_preprocess):
    """Low-confidence obligations are filtered when min_confidence is set."""
    import json

    mock_doc = MagicMock()
    mock_doc.__len__ = lambda self: 1
    mock_page = MagicMock()
    mock_page.get_text.return_value = "Some ambiguous text about procedures."
    mock_doc.__getitem__ = lambda self, idx: mock_page
    mock_fitz.open.return_value = mock_doc

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = json.dumps({
        "obligations": [
            {
                "statement_text": "Procedures follow standard practice",
                "requirement": "Follow standard practice",
                "subject": "contractor",
                "section": "2.1",
                "confidence": 0.3,
                "keywords": ["procedures"],
                "context": "Low confidence",
            },
            {
                "statement_text": "All personnel hold SECRET clearance",
                "requirement": "Staff only cleared personnel",
                "subject": "contractor",
                "section": "2.2",
                "confidence": 0.85,
                "keywords": ["clearance", "SECRET"],
                "context": "High confidence",
            },
        ]
    })
    mock_client.messages.create.return_value = mock_response

    result = _make_result([])

    with patch("anthropic.Anthropic", return_value=mock_client):
        result = detect_implicit_obligations(
            result,
            "test.pdf",
            api_key="test-key",
            min_confidence=0.5,
        )

    # Only the high-confidence one should make it through
    assert result.total_statements == 1
    assert result.statements[0].confidence == 0.85


def test_detect_implicit_updates_by_type():
    """After detection, by_type should include 'implicit' count."""
    result = _make_result([
        _make_statement(1, "Contractor shall deliver X"),
    ])
    result.by_type = {"mandatory": 1}

    # Simulate adding an implicit statement
    implicit = ShallStatement(
        id=2,
        page=1,
        section="3.1",
        obligation_keyword="(implicit)",
        obligation_type="implicit",
        statement_text="Testing follows MIL-STD-810",
        subject="contractor",
        requirement="Test per MIL-STD-810",
        context="",
        confidence=0.8,
    )
    result.statements.append(implicit)
    result.total_statements = 2
    result.by_type["implicit"] = 1

    assert result.by_type["implicit"] == 1
    assert result.total_statements == 2


# ---------------------------------------------------------------------------
# Test mandatory_only filter includes implicit
# ---------------------------------------------------------------------------


def test_build_gpcm_filter_includes_implicit():
    """filter_mandatory_only should keep implicit obligations."""
    from oracle.build_gpcm_rulepack import filter_mandatory_only

    result = _make_result([
        _make_statement(1, "Shall do X"),
        ShallStatement(
            id=2, page=1, section="1.1",
            obligation_keyword="(implicit)",
            obligation_type="implicit",
            statement_text="Reports are due quarterly",
            subject="contractor",
            requirement="Submit reports quarterly",
            context="", confidence=0.8,
        ),
        ShallStatement(
            id=3, page=1, section="1.2",
            obligation_keyword="should",
            obligation_type="recommendation",
            statement_text="Should consider X",
            subject="contractor",
            requirement="Consider X",
            context="", confidence=1.0,
        ),
    ])

    filter_mandatory_only(result)

    assert len(result.statements) == 2
    types = {s.obligation_type for s in result.statements}
    assert "mandatory" in types
    assert "implicit" in types
    assert "recommendation" not in types
