"""Extraction-correctness corpus tests (spec §12.1 recall/precision bar).

A synthetic regulatory fixture with a known gold list of binding obligations
exercises the failure modes fixed in the extractor:
  - decimal section references ("19.202-1", "0.5 percent") no longer truncate
  - semicolon-joined compound duties are captured as one statement
  - mixed should/shall sentences classify by the STRONGEST keyword class
  - text repeated across different sections survives boilerplate dedup
  - prohibitions, passive "are required to" forms, NASA-STD-style references
  - non-obligations (recommendations, permissions, intent, definitions) are
    not counted as binding
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import fitz
import pytest

from oracle.shall_extractor import (
    OBLIGATION_PATTERN,
    ShallStatement,
    _classify_sentence_obligation,
    _dedupe_boilerplate,
    extract_pass1,
)

# ---------------------------------------------------------------------------
# Synthetic corpus fixture
# ---------------------------------------------------------------------------

# Each gold probe is a distinctive fragment of exactly one binding obligation
# sentence in the fixture (except the repeated-records sentence, which appears
# in two sections and is asserted separately for both).
GOLD_BINDING_PROBES = [
    "procedures in 19.202-1 and document the file",
    "monthly status reports; maintain configuration records; and notify the "
    "contracting officer within 5 days",
    "shall report all defects to the program office",
    "0.5 percent of the total contract value",
    "conform to NASA-STD-6001B",
    "must account for oxygen compatibility",
    "must not substitute alloys without written approval",
    "welding procedures are required to be qualified",
    "retained for three years after final payment",
    "submitted electronically through the approved portal",
    "may not assign this contract",
    "smoking is prohibited within 50 feet",
    "cadmium plating shall not be used",
    "proof tested to 1.5 times the maximum design pressure",
    "complete hazard training; refresher courses are required annually",
    "identify the inspector, the date, and the acceptance criteria",
    "nonconforming articles shall be segregated",
    "flow down these requirements to all subcontractors",
    "test failures must be reported to the contracting officer within 24 hours",
]

# Fragments of fixture sentences that are NOT binding obligations and must
# never appear in the mandatory/prohibition set.
NON_BINDING_PROBES = [
    "should review procedures quarterly",
    "may request additional protective equipment",
    "will provide facility access badges",
    "prescribes policies and procedures",
    "the term acceptance means",
]

_PAGE1 = """
1.0 General Provisions

This part prescribes policies and procedures for the acquisition of flight hardware.

In this standard, the term acceptance means the act of an authorized representative.

The contracting officer shall follow the procedures in 19.202-1 and document the file.

The contractor shall submit monthly status reports; maintain configuration records; and notify the contracting officer within 5 days of any anomaly.

The contractor should verify inputs and shall report all defects to the program office.

The offeror shall limit indirect fees to 0.5 percent of the total contract value.

2.0 Technical Requirements

Flammability testing shall conform to NASA-STD-6001B for all nonmetallic materials.

Materials selection must account for oxygen compatibility in pressurized systems.

The design agency must not substitute alloys without written approval.

Welding procedures are required to be qualified before production use.
"""

_PAGE2 = """
3.1 Records Management

Records shall be retained for three years after final payment.

3.2 Data Delivery

Deliverables are required to be submitted electronically through the approved portal.

The contractor may not assign this contract without the written consent of the government.

Smoking is prohibited within 50 feet of the test facility.

4.0 Safety

Cadmium plating shall not be used on any flight hardware surface.

Pressure vessels shall be proof tested to 1.5 times the maximum design pressure.

Each operator shall complete hazard training; refresher courses are required annually.

The safety officer should review procedures quarterly.

Personnel may request additional protective equipment.

The government will provide facility access badges.

5.0 Quality Assurance

Inspection records shall identify the inspector, the date, and the acceptance criteria.

Nonconforming articles shall be segregated pending disposition review.

7.2 Archived Records

Records shall be retained for three years after final payment.

The supplier shall flow down these requirements to all subcontractors.

Test failures must be reported to the contracting officer within 24 hours.
"""


def _wrap_page(raw: str, width: int = 88) -> str:
    lines: list[str] = []
    for line in raw.strip().splitlines():
        if not line.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(line, width=width) or [""])
    return "\n".join(lines)


def _build_corpus_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    for raw in (_PAGE1, _PAGE2):
        page = doc.new_page()
        page.insert_text((60, 60), _wrap_page(raw), fontsize=8)
    pdf_path = tmp_path / "corpus.pdf"
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


@pytest.fixture(scope="module")
def corpus_result(tmp_path_factory):
    pdf_path = _build_corpus_pdf(tmp_path_factory.mktemp("corpus"))
    return extract_pass1(pdf_path)


# ---------------------------------------------------------------------------
# §12.1 recall / precision bar
# ---------------------------------------------------------------------------


def _binding_statements(result) -> list:
    return [
        s for s in result.statements
        if s.obligation_type in ("mandatory", "prohibition")
    ]


def test_corpus_recall_at_least_90_percent(corpus_result):
    binding_texts = [_norm(s.statement_text) for s in _binding_statements(corpus_result)]
    matched = [
        probe for probe in GOLD_BINDING_PROBES
        if any(_norm(probe) in text for text in binding_texts)
    ]
    recall = len(matched) / len(GOLD_BINDING_PROBES)
    missing = sorted(set(GOLD_BINDING_PROBES) - set(matched))
    assert recall >= 0.90, f"recall={recall:.2%}; missing gold obligations: {missing}"


def test_corpus_precision_at_least_85_percent(corpus_result):
    binding = _binding_statements(corpus_result)
    assert binding, "no binding statements extracted at all"
    true_positives = [
        s for s in binding
        if any(_norm(probe) in _norm(s.statement_text) for probe in GOLD_BINDING_PROBES)
    ]
    precision = len(true_positives) / len(binding)
    false_positives = [
        s.statement_text for s in binding if s not in true_positives
    ]
    assert precision >= 0.85, (
        f"precision={precision:.2%}; false binding extractions: {false_positives}"
    )


def test_corpus_non_obligations_are_not_binding(corpus_result):
    binding_texts = [_norm(s.statement_text) for s in _binding_statements(corpus_result)]
    for probe in NON_BINDING_PROBES:
        assert not any(_norm(probe) in text for text in binding_texts), (
            f"non-obligation extracted as binding: {probe!r}"
        )


def test_corpus_repeated_text_survives_in_both_sections(corpus_result):
    """The verbatim records-retention duty appears in §3.1 and §7.2 — both
    copies are real obligations and both must survive (fix: section-blind
    boilerplate dedup deleted all copies of repeated text)."""
    repeats = [
        s for s in _binding_statements(corpus_result)
        if "retained for three years" in _norm(s.statement_text)
    ]
    assert len(repeats) == 2, [s.statement_text for s in repeats]
    assert {s.section for s in repeats} == {"3.1", "7.2"}


def test_corpus_semicolon_compound_is_one_statement(corpus_result):
    compounds = [
        s for s in _binding_statements(corpus_result)
        if "monthly status reports" in _norm(s.statement_text)
    ]
    assert len(compounds) == 1
    text = _norm(compounds[0].statement_text)
    assert "maintain configuration records" in text
    assert "notify the contracting officer within 5 days" in text


# ---------------------------------------------------------------------------
# Exact-case unit tests: fix 1 — sentence boundaries
# ---------------------------------------------------------------------------
# NOTE: these pin the FIXED behavior.  The previous OBLIGATION_PATTERN
# terminated the sentence body at ANY period or semicolon, so the decimal
# case captured only "...in 19" and the semicolon case dropped every clause
# after the first.


def test_pattern_does_not_break_at_decimal_section_reference():
    text = "The contracting officer shall follow the procedures in 19.202-1 and document the file."
    match = OBLIGATION_PATTERN.search(text)
    assert match is not None
    assert match.group(1) == (
        "The contracting officer shall follow the procedures in 19.202-1 "
        "and document the file"
    )


def test_pattern_does_not_break_at_decimal_number():
    text = "The offeror shall limit fees to 0.5 percent of the contract value."
    match = OBLIGATION_PATTERN.search(text)
    assert match is not None
    assert "0.5 percent of the contract value" in match.group(1)


def test_pattern_captures_semicolon_joined_compound_duty():
    text = (
        "The contractor shall submit reports; maintain records; "
        "and notify the CO within 5 days."
    )
    match = OBLIGATION_PATTERN.search(text)
    assert match is not None
    assert match.group(1) == (
        "The contractor shall submit reports; maintain records; "
        "and notify the CO within 5 days"
    )


def test_pattern_still_stops_at_real_sentence_boundary():
    text = "The contractor shall submit reports. The Government shall respond."
    captured = [m.group(1) for m in OBLIGATION_PATTERN.finditer(text)]
    assert captured == [
        "The contractor shall submit reports",
        "The Government shall respond",
    ]


def test_pattern_tolerates_common_abbreviations():
    text = "The contractor shall use approved materials, e.g. Teflon, in oxygen service."
    match = OBLIGATION_PATTERN.search(text)
    assert match is not None
    assert match.group(1).endswith("in oxygen service")


# NOTE: the following pin the FIXED behavior for citation abbreviations and
# lowercase sentence starts.  Previously "Pub. L. 95-507" truncated the
# obligation at "Pub" (missing stems, and no single-capital rule for "L."),
# and "…comply. the vendor must report." fused two duties into one statement
# because a boundary required a capital/digit after the period.


def test_pattern_captures_past_statutory_citation():
    text = "The contractor shall comply with Pub. L. 95-507 and shall report annually."
    match = OBLIGATION_PATTERN.search(text)
    assert match is not None
    assert match.group(1) == (
        "The contractor shall comply with Pub. L. 95-507 and shall report annually"
    )


def test_pattern_tolerates_citation_abbreviation_family():
    text = (
        "Work must conform to Ch. 137 and Stat. 657 plus Dept. of Defense "
        "guidance in Amdt. 4, Rev. A of Vol. II, per Fig. 3 and No. 12."
    )
    match = OBLIGATION_PATTERN.search(text)
    assert match is not None
    assert match.group(1).endswith("per Fig. 3 and No. 12")


def test_single_capital_letter_is_never_a_sentence_end():
    text = "Deliveries shall follow 15 U.S.C. 637 as approved by John Q. Public."
    match = OBLIGATION_PATTERN.search(text)
    assert match is not None
    assert match.group(1).endswith("as approved by John Q. Public")


def test_lowercase_sentence_start_splits_distinct_obligations():
    text = "the contractor shall comply. the vendor must report."
    captured = [m.group(1) for m in OBLIGATION_PATTERN.finditer(text)]
    assert captured == ["the contractor shall comply", "the vendor must report"]


def test_lowercase_split_does_not_break_para_reference():
    text = "The contractor shall proceed in accordance with para. (b) of this section."
    captured = [m.group(1) for m in OBLIGATION_PATTERN.finditer(text)]
    assert captured == [
        "The contractor shall proceed in accordance with para. (b) of this section"
    ]


def test_lowercase_split_suppressed_after_digit():
    # A digit before the period could be an enumerated list item ("5. the
    # next item"), so the lowercase-starter boundary must not fire there.
    text = "The contractor shall complete item 5. the next item is unrelated."
    captured = [m.group(1) for m in OBLIGATION_PATTERN.finditer(text)]
    assert captured == [
        "The contractor shall complete item 5. the next item is unrelated"
    ]


# ---------------------------------------------------------------------------
# Exact-case unit tests: fix 2 — strongest-keyword classification
# ---------------------------------------------------------------------------
# NOTE: pins the FIXED behavior.  Classification previously used the LEFTMOST
# keyword, so "should ... shall ..." was labeled recommendation and dropped
# by every mandatory-only filter.


def test_mixed_should_shall_classifies_as_mandatory():
    keyword, obligation_type = _classify_sentence_obligation(
        "The contractor should verify inputs and shall report all defects."
    )
    assert (keyword, obligation_type) == ("shall", "mandatory")


def test_prohibition_outranks_mandatory():
    keyword, obligation_type = _classify_sentence_obligation(
        "The contractor shall maintain records and shall not disclose them."
    )
    assert (keyword, obligation_type) == ("shall not", "prohibition")


def test_pure_recommendation_stays_recommendation():
    keyword, obligation_type = _classify_sentence_obligation(
        "The contractor should consider recycled materials."
    )
    assert (keyword, obligation_type) == ("should", "recommendation")


def test_no_keyword_returns_empty():
    assert _classify_sentence_obligation("Background information only.") == ("", "")


# ---------------------------------------------------------------------------
# Exact-case unit tests: fix 5 — section-aware boilerplate dedup
# ---------------------------------------------------------------------------


def _stmt(id_: int, text: str, section: str, page: int = 1) -> ShallStatement:
    return ShallStatement(
        id=id_,
        page=page,
        section=section,
        obligation_keyword="shall",
        obligation_type="mandatory",
        statement_text=text,
        subject="x",
        requirement=text,
        context="",
    )


def test_dedupe_removes_same_section_boilerplate_entirely():
    stmts = [_stmt(i, "This document shall be controlled per QP-100.", "") for i in range(6)]
    kept, removed = _dedupe_boilerplate(stmts)
    assert kept == []
    assert removed == 6


def test_dedupe_preserves_one_copy_per_distinct_section():
    # Same text repeated 6 times across 3 sections (2 each): one per section
    # survives — identical text in DIFFERENT sections is a real restated duty.
    stmts = [
        _stmt(i, "Records shall be retained for three years.", section)
        for i, section in enumerate(["3.1", "3.1", "5.2", "5.2", "7.2", "7.2"])
    ]
    kept, removed = _dedupe_boilerplate(stmts)
    assert [s.section for s in kept] == ["3.1", "5.2", "7.2"]
    assert removed == 3


def test_dedupe_leaves_below_threshold_repeats_alone():
    stmts = [
        _stmt(0, "Records shall be retained for three years.", "3.1"),
        _stmt(1, "Records shall be retained for three years.", "7.2"),
    ]
    kept, removed = _dedupe_boilerplate(stmts)
    assert len(kept) == 2
    assert removed == 0


# NOTE: the following pin the FIXED behavior for page furniture.  Footers
# inherit the page's CURRENT section at extraction time, so the section-aware
# keep previously resurrected one copy of an obligation-shaped footer per
# section context (~30 bogus "rules" on a 100-page PDF).  Spread across >= 5
# distinct pages now marks the text as furniture and removes ALL copies.


def test_dedupe_removes_page_furniture_despite_section_churn():
    stmts = [
        _stmt(i, "This document shall be used for official purposes only.",
              f"{i + 1}.0", page=i + 1)
        for i in range(6)
    ]
    kept, removed = _dedupe_boilerplate(stmts)
    assert kept == []
    assert removed == 6


def test_dedupe_low_page_spread_still_keeps_one_copy_per_section():
    # 6 copies but only 2 distinct pages across 3 sections: a genuine
    # cross-section restatement, not page furniture — one copy per section.
    stmts = [
        _stmt(i, "Records shall be retained for three years.", section, page=page)
        for i, (section, page) in enumerate(
            [("3.1", 1), ("3.1", 1), ("5.2", 1), ("5.2", 2), ("7.2", 2), ("7.2", 2)]
        )
    ]
    kept, removed = _dedupe_boilerplate(stmts)
    assert [s.section for s in kept] == ["3.1", "5.2", "7.2"]
    assert removed == 3


def test_footer_obligation_text_is_fully_removed_end_to_end(tmp_path):
    """Obligation-shaped footer text repeated on every page of a multi-page
    PDF must be removed entirely, while each page's unique real obligation
    survives (fix: boilerplate resurrection via section-aware keep)."""
    footer = "This document shall be used for official purposes only."
    doc = fitz.open()
    for i in range(6):
        page = doc.new_page()
        body = (
            f"{i + 1}.0 Section Title\n\n"
            f"The contractor shall deliver item {i + 1} on schedule.\n\n"
            f"{footer}\n"
        )
        page.insert_text((60, 60), body, fontsize=8)
    pdf_path = tmp_path / "footered.pdf"
    doc.save(pdf_path)
    doc.close()

    result = extract_pass1(pdf_path)
    texts = [_norm(s.statement_text) for s in result.statements]
    assert not any("official purposes only" in t for t in texts), texts
    assert sum(1 for t in texts if "deliver item" in t) == 6
