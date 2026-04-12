"""Tests for explicit obligation keyword capture, including passive-voice forms."""

from oracle.shall_extractor import OBLIGATION_PATTERN, _extract_subject_requirement


def test_obligation_pattern_matches_plural_required_passive_phrase():
    text = "Supplier records are required to be retained for three years."

    match = OBLIGATION_PATTERN.search(text)

    assert match is not None
    assert match.group(2).lower() == "are required to"
    subject, requirement = _extract_subject_requirement(match.group(1), match.group(2).lower())
    assert subject == "Supplier records"
    assert requirement == "be retained for three years"


def test_obligation_pattern_matches_plural_prohibition_passive_phrase():
    text = "Cadmium-plated tools are prohibited in crew or vacuum environments."

    match = OBLIGATION_PATTERN.search(text)

    assert match is not None
    assert match.group(2).lower() == "are prohibited"
    subject, requirement = _extract_subject_requirement(match.group(1), match.group(2).lower())
    assert subject == "Cadmium-plated tools"
    assert requirement == "in crew or vacuum environments"
