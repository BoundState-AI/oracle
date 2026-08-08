"""Corpus intake + D-3 scrub helper (CS1-CS6). Keyless deterministic —
synthetic identifiers only, never real engagement data. BoundState AI 2026.
"""

from __future__ import annotations

import csv

import pytest

from oracle.disposition.corpus import CorpusError, load_corpus
from oracle.disposition.corpus_scrub import (
    CANONICAL_FIELDS,
    check,
    map_headers,
    parse_terms,
    read_raw,
    scrub,
)
from oracle.disposition.export import _write_xlsx_book

_RAW_HDR = ["Req ID", "Disposition", "Readiness", "Applicable", "Org",
            "Implementation", "Approval", "Comments", "WP", "Actions",
            "Internal Cost"]


def _raw_csv(tmp_path, rows, name="raw.csv", header=None):
    p = tmp_path / name
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header or _RAW_HDR)
        w.writerows(rows)
    return p


def _terms(tmp_path, lines, name="terms.txt"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


_CLEAN_ROW = ["AMR-1", "CW", "Met", "yes", "owner", "meets_as_written",
              "not_required", "controls documented", "WP-1", "", "$100"]


# ------------------------------------------------------------------- CS1


def test_cs1_header_mapping_synonyms_and_overrides(tmp_path):
    p = _raw_csv(tmp_path, [_CLEAN_ROW])
    headers, rows = read_raw(p)
    mapping, dropped = map_headers(headers)
    assert mapping[0] == "requirement_id"
    assert mapping[1] == "contract_label"
    assert mapping[2] == "readiness_label"
    assert "Internal Cost" in dropped  # extra column dropped, reported
    # explicit override wins over synonyms
    mapping2, _ = map_headers(["Weird"], {"Weird": "requirement_id"})
    assert mapping2[0] == "requirement_id"
    with pytest.raises(CorpusError, match="not a corpus field"):
        map_headers(["Weird"], {"Weird": "nope"})
    with pytest.raises(CorpusError, match="requirement_id"):
        map_headers(["Only", "Unknowable", "Columns"])


def test_cs1_xlsx_raw_intake(tmp_path):
    p = _write_xlsx_book(
        tmp_path / "raw.xlsx", [("Corpus", _RAW_HDR, [_CLEAN_ROW])]
    )
    headers, rows = read_raw(p)
    assert headers == _RAW_HDR
    assert rows[0][0] == "AMR-1"


# ------------------------------------------------------------------- CS2


def test_cs2_terms_parsing(tmp_path):
    p = _terms(tmp_path, ["# engagement words", "", "Acme Corp=Supplier",
                          "Widget", "Acme=Org-A"])
    terms = parse_terms(p)
    # longest first so "Acme Corp" wins over "Acme"
    assert terms[0] == ("Acme Corp", "Supplier")
    assert ("Widget", "[REDACTED]") in terms
    with pytest.raises(CorpusError, match="no usable entries"):
        parse_terms(_terms(tmp_path, ["# only a comment"], "empty.txt"))


# ------------------------------------------------------------------- CS3


def test_cs3_terms_replaced_and_clean_write(tmp_path):
    dirty = list(_CLEAN_ROW)
    dirty[7] = "Acme Corp will fix; Acme owns the WIDGET line"
    p = _raw_csv(tmp_path, [dirty])
    t = _terms(tmp_path, ["Acme Corp=Supplier", "Acme=Org-A", "Widget=Part-X"])
    rep = scrub(p, tmp_path / "out.csv", terms_path=t, apply=True)
    assert rep.written and not rep.violations
    assert rep.replacements >= 3
    out = (tmp_path / "out.csv").read_text(encoding="utf-8")
    assert "Acme" not in out and "WIDGET" not in out.upper().replace(
        "PART-X", ""
    )
    assert "Supplier will fix" in out
    assert "Org-A owns the Part-X line" in out


def test_cs3_pattern_hit_fails_closed(tmp_path):
    dirty = list(_CLEAN_ROW)
    dirty[7] = "per contract no. NNX99AB12C"
    p = _raw_csv(tmp_path, [dirty])
    rep = scrub(p, tmp_path / "out.csv", apply=True, allow_no_terms=True)
    assert not rep.written
    assert any(v.kind == "pattern" for v in rep.violations)
    assert not (tmp_path / "out.csv").exists()


def test_cs3_unreplaced_term_fails_closed(tmp_path):
    # term appears in a column the terms file misses nothing — simulate a
    # term list that only covers one spelling
    dirty = list(_CLEAN_ROW)
    dirty[7] = "AcmeCorporation retains data"
    p = _raw_csv(tmp_path, [dirty])
    t = _terms(tmp_path, ["AcmeCorporation"])
    rep = scrub(p, tmp_path / "out.csv", terms_path=t, apply=True)
    # replaced -> clean -> written
    assert rep.written
    # but a term NOT in the file stays a violation via pattern-free scan:
    dirty2 = list(_CLEAN_ROW)
    dirty2[7] = "cage: 1XYZ9 flowdown"
    p2 = _raw_csv(tmp_path, [dirty2], name="raw2.csv")
    rep2 = scrub(p2, tmp_path / "out2.csv", terms_path=t, apply=True)
    assert not rep2.written and rep2.violations


def test_cs3_dry_run_never_writes(tmp_path):
    p = _raw_csv(tmp_path, [_CLEAN_ROW])
    rep = scrub(p, tmp_path / "out.csv", apply=False)
    assert not rep.written and not rep.violations
    assert not (tmp_path / "out.csv").exists()
    # G1: a termless run says loudly that names are unscanned
    assert any("NOT scanned" in w for w in rep.warnings)


# ------------------------------------------------------------------- CS4


def test_cs4_output_loads_via_corpus_loader(tmp_path):
    p = _raw_csv(tmp_path, [_CLEAN_ROW])
    rep = scrub(p, tmp_path / "out.csv", apply=True, allow_no_terms=True)
    assert rep.written
    rows = load_corpus(tmp_path / "out.csv")
    assert rows[0].requirement_id == "AMR-1"
    assert rows[0].contract_label == "CW"
    with (tmp_path / "out.csv").open(encoding="utf-8") as f:
        assert next(csv.reader(f)) == list(CANONICAL_FIELDS)


# ------------------------------------------------------------------- CS5


# --------------------------------------------------- Atlas G1-G7 (round 1)


def test_g1_terms_required_for_apply(tmp_path):
    """Atlas critical: termless --apply wrote names unchanged."""
    p = _raw_csv(tmp_path, [_CLEAN_ROW])
    with pytest.raises(CorpusError, match="terms file is required"):
        scrub(p, tmp_path / "out.csv", apply=True)
    assert not (tmp_path / "out.csv").exists()
    rep = scrub(p, tmp_path / "out.csv", apply=True, allow_no_terms=True)
    assert rep.written  # explicit attestation is the only bypass


def test_g2_output_never_overwrites_inputs(tmp_path):
    p = _raw_csv(tmp_path, [_CLEAN_ROW])
    t = _terms(tmp_path, ["Acme=Org-A"])
    with pytest.raises(CorpusError, match="over the raw export"):
        scrub(p, p, terms_path=t, apply=True)
    with pytest.raises(CorpusError, match="over the terms file"):
        scrub(p, t, terms_path=t, apply=True)
    assert "Org-A" not in p.read_text(encoding="utf-8")
    assert "requirement_id" not in t.read_text(encoding="utf-8")


def test_g3_refusal_preserves_existing_output(tmp_path):
    p = _raw_csv(tmp_path, [_CLEAN_ROW])
    out = tmp_path / "out.csv"
    rep = scrub(p, out, apply=True, allow_no_terms=True)
    assert rep.written
    good = out.read_text(encoding="utf-8")
    dirty = list(_CLEAN_ROW)
    dirty[7] = "per contract no. NNX99AB12C"
    p2 = _raw_csv(tmp_path, [dirty], name="raw2.csv")
    rep2 = scrub(p2, out, apply=True, allow_no_terms=True)
    assert not rep2.written
    assert out.read_text(encoding="utf-8") == good  # untouched on refusal


def test_g4_explicit_map_wins_over_synonyms(tmp_path):
    """Atlas high: an earlier synonym column stole the overridden field."""
    mapping, dropped = map_headers(
        ["Req ID", "Authoritative Identifier", "Disposition"],
        {"Authoritative Identifier": "requirement_id"},
    )
    assert mapping[1] == "requirement_id"
    assert mapping[2] == "contract_label"
    assert "Req ID" in dropped
    with pytest.raises(CorpusError, match="not found in the raw export"):
        map_headers(["Req ID"], {"Missing Column": "comment"})


def test_g5_unloadable_output_refused(tmp_path):
    """Atlas high: scrub wrote CSV that load_corpus then rejected."""
    bad = list(_CLEAN_ROW)
    bad[1] = "PENDING"
    p = _raw_csv(tmp_path, [bad])
    rep = scrub(p, tmp_path / "out.csv", apply=True, allow_no_terms=True)
    assert not rep.written
    assert any("PENDING" in e for e in rep.format_errors)
    assert not (tmp_path / "out.csv").exists()


def test_g5_labels_normalized_in_output(tmp_path):
    row = list(_CLEAN_ROW)
    row[1] = "Comply as Written"
    p = _raw_csv(tmp_path, [row])
    rep = scrub(p, tmp_path / "out.csv", apply=True, allow_no_terms=True)
    assert rep.written
    rows = load_corpus(tmp_path / "out.csv")
    assert rows[0].contract_label == "CW"


def test_g8_normalization_cannot_introduce_blocked_terms(tmp_path):
    """Atlas round 2: 'Comply as Written' normalized to 'CW' AFTER the
    scan, writing a term the operator explicitly prohibited."""
    row = list(_CLEAN_ROW)
    row[1] = "Comply as Written"  # normalizes to CW
    p = _raw_csv(tmp_path, [row])
    t = _terms(tmp_path, ["CW=[REDACTED]"])
    rep = scrub(p, tmp_path / "out.csv", terms_path=t, apply=True)
    assert not rep.written
    assert any(
        v.kind == "term" and v.detail == "CW" for v in rep.violations
    )
    assert not (tmp_path / "out.csv").exists()


def test_g8_scan_covers_final_cells_not_raw(tmp_path):
    # a pattern hit surviving into the normalized row still refuses
    dirty = list(_CLEAN_ROW)
    dirty[7] = "cage: 1XYZ9 flowdown"
    p = _raw_csv(tmp_path, [dirty])
    rep = scrub(p, tmp_path / "out.csv", apply=True, allow_no_terms=True)
    assert not rep.written and any(v.kind == "pattern" for v in rep.violations)


def test_g7_replacement_text_is_literal(tmp_path):
    dirty = list(_CLEAN_ROW)
    dirty[7] = "PrivateCo stores builds"
    p = _raw_csv(tmp_path, [dirty])
    t = _terms(tmp_path, [r"PrivateCo=C:\Safe"])
    rep = scrub(p, tmp_path / "out.csv", terms_path=t, apply=True)
    assert rep.written
    out = (tmp_path / "out.csv").read_text(encoding="utf-8")
    assert r"C:\Safe stores builds" in out


def test_cs5_check_reports_tallies_and_all_coherence_errors(tmp_path):
    rows = [
        ["AMR-1", "CW", "Met", "yes", "owner", "not_met",  # Met incoherent
         "not_required", "", "WP-1", "", ""],
        ["AMR-2", "NA", "Technical N/A", "yes", "external",  # NA incoherent
         "not_reached", "not_required", "", "WP-2", "", ""],
    ]
    p = _raw_csv(tmp_path, rows)
    scrub(p, tmp_path / "c.csv", apply=True, allow_no_terms=True)
    rep = check(tmp_path / "c.csv")
    assert rep["rows"] == 2
    assert rep["reconciled"] is False
    assert len(rep["coherence_errors"]) == 2  # ALL errors, not just first
    # identity-first: tallies are computed reports, never targets
    assert rep["contract"] == {"CW": 1, "NA": 1}
    assert "contract_expected" not in rep
