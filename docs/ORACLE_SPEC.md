# ORACLE Module Specification
## Orchestrated Review And Compliance Liaison Engine

**Version:** 1.3.0  
**Author:** Dr. Joseph Wilde / Beth (Claude Opus 4.6)  
**Date:** 2026-04-04  
**Classification:** BoundState Proprietary  
**Status:** DRAFT — Round 4 Revision  

---

## 1. Purpose

ORACLE is a standalone module that accepts any uploaded document (spec, pitch, code, proposal, regulatory filing) and runs it through multi-oracle adversarial review to convergence against user-selected rule packs. The killer feature: upload a new regulatory document (DFARS, cGMP, ISO, OSHA), ORACLE auto-generates a structured rule pack from it, adds it to a persistent library, and makes it available for all future reviews.

ORACLE unifies the existing oracle2 review engine, shall_extractor extraction pipeline, and GPCM/FAR rule pack builders into a single CLI with core commands: `generate-pack`, `review`, `list-packs`, and `promote-pack`.

---

## 2. Non-Goals

- ORACLE does not replace oracle2.py. It wraps it as the review engine. However, ORACLE depends on a defined return contract from `oracle2.run_review()` (see Section 7.3). If oracle2 does not currently expose this contract, an adapter layer within ORACLE will parse oracle2's output files to construct the required data.
- ORACLE does not replace shall_extractor.py or build_gpcm_rulepack.py. It imports and routes to them.
- ORACLE does not provide a web UI. CLI only. Web integration is a future concern.
- ORACLE does not store API keys. It reads from environment variables per existing oracle2 convention.
- ORACLE does not modify the reviewed document in-place. It produces a revised draft and findings report as outputs.

---

## 3. Architecture

### 3.1 Module Relationships

```
oracle.py (unified CLI)
    │
    ├── oracle2.py (review engine — unchanged)
    │     ├── Beth (Opus 4.8 high) — normalizer / bundler / spec revisor
    │     ├── Fran (GPT-5.4) — adversarial logic
    │     ├── Codex (GPT-5.4) — implementation feasibility
    │     ├── Grok (xAI) — contrarian
    │     ├── Gemini — broad-context review
    │     └── Sonnet (Claude Sonnet 4.6) — legacy ledger referee (`--workflow ledger`)
    │
    ├── oracle2_adapter.py (return contract adapter — NEW)
    │     └── Parses oracle2 output files into ReviewResult schema
    │
    ├── Pack Generation Pipeline
    │     ├── Route A: Tagged Standards (MPR/FCR)
    │     │     └── build_gpcm_rulepack.py → shall_extractor + gpcm_rulepack_adapter
    │     ├── Route B: FAR/DFARS Style
    │     │     └── shall_extractor → build_far_rulepack.py
    │     └── Route C: Generic (any regulation)
    │           └── Claude Sonnet chunked extraction (NEW)
    │
    ├── Pack Validator (NEW)
    │     └── JSON Schema validation for all pack types
    │
    └── Pack Library ($ORACLE_PACK_DIR or ~/.oracle/packs/)
          └── manifest.json + pack JSON files
```

### 3.2 Data Flow

```
                        ┌─────────────────┐
                        │  User uploads   │
                        │  regulation PDF │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │  Auto-detect    │
                        │  document type  │
                        │  (w/ confidence)│
                        └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
     ┌────────▼──────┐ ┌────────▼──────┐  ┌─────────▼───────┐
     │ Tagged Std    │ │ FAR/DFARS     │  │ Generic         │
     │ (MPR/FCR)    │ │ (Part.Section)│  │ (any regulation)│
     │              │ │               │  │                 │
     │ build_gpcm   │ │ shall_extract │  │ Claude chunked  │
     │ _rulepack.py │ │ + build_far   │  │ extraction      │
     └──────┬───────┘ └──────┬────────┘  └────────┬────────┘
            │                │                     │
            └────────────────┼─────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Validate against│
                    │  JSON Schema    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Rule Pack JSON │
                    │  (DRAFT status) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Register in    │
                    │  Pack Library   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  User reviews   │
                    │  & promotes     │
                    └─────────────────┘


                        ┌─────────────────┐
                        │  User uploads   │
                        │  document to    │
                        │  review         │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │  Select packs   │
                        │  from library   │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │  Render packs   │
                        │  to compliance  │
                        │  context text   │
                        │  (within token  │
                        │   budget)       │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │  oracle2.py     │
                        │  run_review()   │
                        │  w/ compliance  │
                        │  context        │
                        └────────┬────────┘
                                 │
                   ┌─────────────┼─────────────┐
                   │             │              │
          ┌────────▼───┐  ┌─────▼──────┐ ┌─────▼──────┐
          │ final_draft│  │ findings   │ │ metrics    │
          │ .md        │  │ _report.md │ │ .json      │
          └────────────┘  └────────────┘ └────────────┘
```

---

## 4. Pack Schemas

Three pack schemas exist. Each has a distinct structure but all produce text renderings that oracle2 consumes as `compliance_context`. All schemas are defined as normative JSON Schemas (see Section 4.4) and validated on generation and import.

All pack schemas include an `oracle_metadata` block (see Section 4.5) that stores ORACLE library management fields. This block enables faithful manifest reconstruction if the manifest is corrupted.

### 4.1 GPCM Schema (Tagged Standards)

Used for NASA standards with [MPR N] / [FCR N] tags.

```json
{
  "schema_version": "gpcm_rulepack/v1",
  "rule_pack_id": "gpcm-rulepack-nasa-std-6016c",
  "standard_id": "NASA-STD-6016C",
  "version": "1.0.0",
  "generated_at": "2026-04-04T...",
  "source_document": "path/to/pdf",
  "source_extract": "path/to/shall_statements.json",
  "extraction_status": "complete",
  "total_requirements": 67,
  "oracle_metadata": {
    "name": "NASA-STD-6016C Materials and Processes",
    "slug": "nasa_std_6016c",
    "description": "auto-generated or user-provided",
    "status": "draft",
    "added_at": "2026-04-04T...",
    "promoted_at": null,
    "promoted_by": null,
    "promotion_notes": null,
    "source_document_hash": null,
    "detection_override": null
  },
  "requirements": [
    {
      "id": "stmt-001",
      "source_tag": "MPR 1",
      "section": "4.1.1",
      "shall_text": "Programs shall identify all materials...",
      "subject": "Programs",
      "requirement": "identify all materials...",
      "context": "surrounding text",
      "page": 12,
      "justification": "rationale text if available",
      "keywords": ["materials", "identification"],
      "applies_to": ["all_programs"],
      "mua_relevant": false
    }
  ]
}
```

**Renderer:** Emits each requirement as `[<pack_id>:<id>] [MPR N] §X.X [SHALL]: text` (see Section 7.3 for citation rationale).

### 4.2 FAR Schema (Federal Acquisition Regulation)

Used for FAR, DFARS, NFS, GSAM.

```json
{
  "schema_version": "far_rulepack/v1",
  "rule_pack_id": "far-rulepack-complete",
  "standard_id": "FAR",
  "standard_title": "Federal Acquisition Regulation",
  "version": "1.0.0",
  "generated_at": "2026-04-04T...",
  "source_document": "path/to/far_document.pdf",
  "extraction_status": "complete",
  "total_binding_requirements": 1847,
  "parts_count": 42,
  "oracle_metadata": {
    "name": "Federal Acquisition Regulation (Complete)",
    "slug": "far_rulepack_complete",
    "description": "auto-generated or user-provided",
    "status": "draft",
    "added_at": "2026-04-04T...",
    "promoted_at": null,
    "promoted_by": null,
    "promotion_notes": null,
    "source_document_hash": null,
    "detection_override": null
  },
  "part_index": [
    {
      "part": 15,
      "title": "Contracting by Negotiation",
      "mandatory_count": 89,
      "prohibition_count": 12,
      "total_binding": 101,
      "section_count": 23,
      "sections_covered": ["15.101", "15.102", "..."]
    }
  ],
  "parts": {
    "15": [
      {
        "id": "far-15-001",
        "section": "15.304",
        "page": 42,
        "obligation_type": "mandatory",
        "obligation_keyword": "shall",
        "statement_text": "The contracting officer shall...",
        "subject": "The contracting officer",
        "requirement": "evaluate proposals...",
        "keywords": ["evaluation", "proposals"],
        "applies_to": ["contracting_officer"]
      }
    ]
  }
}
```

**Renderer:** Two tiers. Tier 1 = summary index (always included). Tier 2 = full requirements for user-specified Parts (via `--pack-parts`), each emitted as `[<pack_id>:<id>] §X.X [SHALL]: text`. Existing `render_for_oracle()` in `build_far_rulepack.py` handles the core rendering; ORACLE wraps it to prepend citation identifiers.

### 4.3 Generic Schema (Any Regulation)

Used for cGMP, ISO, OSHA, ITAR, export controls, any document with normative language that doesn't match the tagged or FAR patterns.

```json
{
  "schema_version": "oracle_generic/v1",
  "rule_pack_id": "generic-cgmp-211",
  "standard_id": "21 CFR Part 211",
  "standard_title": "cGMP for Finished Pharmaceuticals",
  "version": "1.0.0",
  "generated_at": "2026-04-04T...",
  "source_document": "path/to/pdf",
  "extraction_method": "claude_vision",
  "extraction_status": "complete|partial",
  "total_source_pages": 45,
  "extracted_pages": [1, 2, 3, "...", 45],
  "failed_page_ranges": [],
  "chunk_failures": [],
  "total_rules": 134,
  "oracle_metadata": {
    "name": "cGMP for Finished Pharmaceuticals (21 CFR 211)",
    "slug": "generic_cgmp_211",
    "description": "auto-generated or user-provided",
    "status": "draft",
    "added_at": "2026-04-04T...",
    "promoted_at": null,
    "promoted_by": null,
    "promotion_notes": null,
    "source_document_hash": null,
    "detection_override": null
  },
  "rules": [
    {
      "rule_id": "RULE-0001",
      "obligation_type": "mandatory",
      "obligation_keyword": "shall",
      "section": "211.22",
      "statement_text": "There shall be a quality control unit...",
      "subject": "quality control unit",
      "requirement": "have the authority to approve or reject...",
      "context": "Organization and Personnel",
      "severity": "critical",
      "keywords": ["quality_control", "authority"],
      "page": 5
    }
  ]
}
```

**`chunk_failures` Schema:**

The `chunk_failures` array records structured metadata for each chunk that failed extraction after retries:

```json
{
  "chunk_failures": [
    {
      "page_start": 21,
      "page_end": 25,
      "retries_used": 2,
      "final_error": "JSON parse failure after markdown fence stripping and re-prompt",
      "extraction_mode": "vision"
    }
  ]
}
```

This field is included in the normative JSON Schema (`oracle_generic_v1.schema.json`). The `failed_page_ranges` field is derived from `chunk_failures` for summary display.

**Severity Taxonomy:** The `severity` field uses a closed taxonomy assigned during extraction:

| Severity | Assignment Criteria |
|----------|-----------------------|
| `critical` | Obligation uses "shall" or "must" with safety, health, or legal consequence language; or obligation governs system-level controls (e.g., quality control authority, safety shutdowns) |
| `high` | Obligation uses "shall" or "must" for operational requirements without explicit consequence language |
| `medium` | Obligation uses "required" or conditional mandatory language ("shall, when applicable") |
| `low` | Prohibition ("shall not") for administrative or procedural matters |

The extraction prompt includes this taxonomy verbatim (see Section 5.4).

**Renderer:** Emits each rule as `[<pack_id>:<rule_id>] §X.X [SHALL] (SEVERITY): text`

### 4.4 Schema Validation

Normative JSON Schemas are maintained for each pack type (`gpcm_rulepack_v1.schema.json`, `far_rulepack_v1.schema.json`, `oracle_generic_v1.schema.json`) and for `manifest.json`. These schemas define:

- Required vs. optional fields
- Field types, formats, and enum constraints
- Minimum array lengths
- Schema version as the authoritative dispatch key
- The `oracle_metadata` block as required with its sub-fields
- The `chunk_failures` array structure (generic schema)

Validation is enforced at two points:
1. **generate-pack:** Output is validated before registration. Validation failure aborts registration with actionable errors.
2. **add-pack:** Imported JSON undergoes a **normalization-then-validation** flow:
   a. **Normalization:** If `oracle_metadata` is missing from the imported pack, it is auto-populated with defaults (slug derived from `rule_pack_id`, status `"draft"`, current timestamp for `added_at`, all promotion fields null).
   b. **Validation:** The normalized pack is validated against the canonical JSON Schema. Invalid packs are rejected with field-level error messages.
   
   This ordering ensures that externally-produced packs (which may lack ORACLE-specific metadata) can be imported while still enforcing full schema compliance after normalization.

### 4.5 Oracle Metadata Block

All pack schemas include an `oracle_metadata` block that stores ORACLE library management fields alongside the pack content. This serves two purposes:

1. **Manifest Rebuild:** If `manifest.json` is corrupted, the library can be faithfully rebuilt from pack files (see Section 13.5).
2. **Promotion Audit:** Promotion state, reviewer identity, and attestation notes are persisted in the pack file itself, not only in the manifest.

```json
{
  "oracle_metadata": {
    "name": "human-readable name",
    "slug": "filesystem-safe-slug",
    "description": "from pack data or user-provided",
    "status": "draft|promoted",
    "added_at": "2026-04-04T...",
    "promoted_at": null,
    "promoted_by": null,
    "promotion_notes": null,
    "source_document_hash": "sha256:... (of the source PDF, if available)",
    "detection_override": null
  }
}
```

The `oracle_metadata` block is updated in the pack file when `promote-pack` is executed. The manifest entry mirrors these fields.

The `detection_override` field is set to the `--force-type` value when document type detection was overridden during generation (see Section 5.1). It is `null` when detection proceeded normally. This field provides an audit trail for packs generated with manual type overrides.

---

## 5. Pack Generation Pipeline

### 5.1 Document Type Detection

Read the document using a two-pass strategy:

**Pass 1 (front matter):** Read the first 10 pages and apply pattern matching.  
**Pass 2 (body sampling):** If Pass 1 confidence is below threshold, sample 5 evenly-spaced pages from the remainder of the document.

| Pattern | Detection | Route |
|---------|-----------|-------|
| ≥3 `[MPR N]` or `[FCR N]` tags | `tagged_standard` | `build_gpcm_rulepack.py` |
| ≥3 FAR/DFARS/NFS section references (e.g., `FAR 15.304`) | `far_style` | `shall_extractor` + `build_far_rulepack.py` |
| CFR-style references (`XX CFR`, `Code of Federal Regulations`) | `cfr_style` | Route C (generic) |
| None of the above | `generic` | Route C (generic) |

**Confidence Scoring Formula:**

For each candidate route (except `generic`), the confidence score is computed as:

```
raw_score = match_count / required_threshold
distribution_factor = pages_with_matches / total_sampled_pages
confidence = min(1.0, raw_score × (0.5 + 0.5 × distribution_factor))
```

Where:
- `required_threshold` is 3 for all pattern types (the minimum match count in the detection table above)
- `match_count` is the total number of pattern matches across all sampled pages
- `pages_with_matches` is the number of distinct sampled pages containing at least one match for this route
- `total_sampled_pages` is the total number of pages sampled across both passes

The `0.5 + 0.5 × distribution_factor` term ensures that matches concentrated on a single page (distribution_factor near 0) are penalized, while matches spread across the document (distribution_factor near 1) receive full credit.

If no route scores above 0.0, the document is classified as `generic` with confidence 1.0 (`generic` is the catch-all route and is always valid).

**Tie-Break Rule:** If two routes produce identical confidence scores, prefer the more specific route: `tagged_standard` > `far_style` > `cfr_style`.

If the highest-confidence route scores below 0.7, the CLI prompts the user for confirmation before proceeding: `"Detected [type] with low confidence (0.XX). Proceed? [Y/n/override]"`.

**Non-Interactive Mode:** In non-interactive mode (`--non-interactive`), low-confidence detection (below 0.7) is a **hard error** unless `--force-type` is provided. The command exits with: `"Detection confidence too low (0.XX) for non-interactive mode. Use --force-type <type> to override."` This prevents automated pipelines from silently generating wrong-route packs that contaminate the persistent library.

**`--force-type` Override and Audit:** User can override detection with `--force-type`. When `--force-type` is used:
- Confidence scoring is skipped entirely.
- The forced type is recorded in the generated pack's `oracle_metadata.detection_override` field (e.g., `"detection_override": "generic"`).
- A log message is emitted: `"Detection overridden: --force-type [type] applied. Recorded in pack metadata."`

This provides an audit trail for packs generated with manual type overrides, enabling downstream consumers to identify packs that bypassed automatic detection.

### 5.2 Route A: Tagged Standard Pipeline

Delegates entirely to `build_gpcm_rulepack.run_pipeline()`:
1. `shall_extractor.extract_pass1()` — regex-based extraction of obligation statements
2. `gpcm_rulepack_adapter.run_adapter()` — PDF page correlation, tag block matching, justification extraction, deduplication
3. Optional: `--use-sonnet-vision` for targeted Sonnet Vision repair of weak extractions

**Dependencies:** `shall_extractor.py`, `build_gpcm_rulepack.py`, `gpcm_rulepack_adapter.py`, PyMuPDF.

### 5.3 Route B: FAR-Style Pipeline

1. `shall_extractor.extract_pass1()` — extract shall statements
2. Optional: `shall_extractor.enrich_with_sonnet()` — Sonnet Vision enrichment
3. `build_far_rulepack.build_rulepack()` — group by Part, build tiered index

**Dependencies:** `shall_extractor.py`, `build_far_rulepack.py`.

### 5.4 Route C: Generic Extraction Pipeline (NEW)

For regulations that don't match tagged or FAR patterns. Uses Claude Sonnet for extraction.

**Process:**
1. Open PDF with PyMuPDF
2. Process in overlapping chunks of 5 pages, with 1-page overlap between consecutive chunks (chunk 1 = pages 1–5, chunk 2 = pages 5–9, chunk 3 = pages 9–13, etc.). The overlap mitigates obligations spanning chunk boundaries.
3. For each chunk:
   - If `--vision` (default): render pages as PNG, send as images to Sonnet
   - If `--no-vision`: extract text, send as text to Sonnet
   - Prompt instructs Sonnet to extract all shall/must/required/prohibited statements
   - **Response validation:** Parse response as JSON. If parsing fails:
     a. Strip markdown fences and retry parse
     b. If still invalid, re-prompt with the malformed output and instruction to emit valid JSON only
     c. Maximum 2 retries per chunk. After exhaustion, mark chunk as failed and record structured failure metadata in `chunk_failures`.
   - Assign sequential `rule_id` per successfully parsed rule
4. Aggregate all rules from all chunks
5. **Deduplication:** Deduplicate using a composite key of `(section, normalized_statement_text)`. Rules with identical text but different section numbers are preserved as distinct obligations.
6. Validate output against `oracle_generic_v1.schema.json`
7. Save to output directory

**Extraction Prompt Contract:**

The prompt must instruct the model to:
- Only extract binding obligations (shall/must/required/prohibited)
- NOT extract recommendations (should/may)
- Return atomic rules (one obligation per entry)
- Preserve exact regulatory language
- Include section numbers when visible
- Assign severity using the closed taxonomy: `critical` (safety/health/legal consequence or system-level controls), `high` (operational shall/must without consequence language), `medium` (conditional mandatory), `low` (administrative prohibitions)
- Not invent or extrapolate
- Return valid JSON array, no markdown fences

**Cost Estimate:** ~$0.02-0.05 per page (Sonnet text mode), ~$0.05-0.10 per page (Sonnet vision mode). A 200-page regulation ≈ $4-20.

**Failure Handling:** If a chunk fails extraction after retries, log the error (including retry count and final failure reason) and continue to next chunk. The pack records `extraction_status: "partial"`, `failed_page_ranges`, `chunk_failures`, and `extracted_pages` in its metadata.

### 5.5 Registration

After generation, the pack undergoes validation and registration:

1. **Schema Validation:** The pack JSON is validated against its corresponding JSON Schema. Validation failure aborts registration with actionable field-level errors.
2. **Completeness Check:** If `extraction_status` is `"partial"`, registration requires `--allow-partial` flag. Without it, the command errors with a summary of failed pages.
3. **Draft Status:** All auto-generated packs are registered with `status: "draft"` in the `oracle_metadata` block. Draft packs display a prominent warning during review: `"⚠ Pack [name] is LLM-generated and unverified. Use promote-pack to mark as reviewed."`
4. **Source Document Hash:** If available, the SHA-256 hash of the source PDF is computed and stored in `oracle_metadata.source_document_hash`.
5. **File Copy:** The pack JSON file is copied to the pack library directory.
6. **Manifest Update:** The manifest is updated with metadata mirrored from the `oracle_metadata` block.

```json
{
  "name": "human-readable name",
  "slug": "filesystem-safe-slug",
  "file": "slug.json",
  "schema": "gpcm|far|generic",
  "standard_id": "from pack data",
  "description": "from pack data or user-provided",
  "rule_count": 134,
  "version": "1.0.0",
  "status": "draft|promoted",
  "extraction_status": "complete|partial",
  "failed_page_ranges": [],
  "content_hash": "sha256:abcdef...",
  "added_at": "2026-04-04T...",
  "promoted_at": null,
  "promoted_by": null,
  "source_document": "path/to/source/pdf",
  "source_document_hash": "sha256:..."
}
```

---

## 6. Pack Library

### 6.1 Storage

File-based. The library location is resolved in the following precedence order:

1. `--pack-dir <path>` CLI flag (per-command override)
2. `ORACLE_PACK_DIR` environment variable
3. Default: `~/.oracle/packs/`

Each pack is a standalone JSON file. The manifest (`manifest.json`) is the index.

**Why file-based, not DB:** Portability. Atlas can read/write. Git-friendly. No schema migrations. No connection strings.

**Why not alongside scripts:** Mutable state must not live in potentially read-only installation directories. The user data directory is writable across all deployment modes (pip, container, system package).

### 6.2 Operations

| Command | Action |
|---------|--------|
| `list-packs` | Read manifest, print table: name, rules, schema, standard, status, date |
| `add-pack <json>` | Normalize, validate against JSON Schema, copy JSON to library, register in manifest |
| `remove-pack <name>` | Delete JSON from library, remove from manifest |
| `show-pack <name>` | Load pack, print stats. With `-v`, render the oracle-facing text |
| `generate-pack <pdf>` | Full pipeline: detect → extract → validate → register (as draft) |
| `promote-pack <name>` | Mark a draft pack as reviewed/promoted (see promotion prerequisites below) |

**Promotion Prerequisites:**

`promote-pack` transitions a pack from `draft` to `promoted` status. Because `promoted` is surfaced as a trust signal in findings reports (Section 8), promotion enforces mandatory gates:

1. **Pack Summary Display:** The command prints the pack's standard_id, rule count, extraction status, chunk failures (if any), and source document hash.
2. **Extraction Completeness Gate:** If the pack's `extraction_status` is `"partial"`, promotion requires the `--allow-partial-promotion` flag. Without it, the command errors: `"Cannot promote pack with partial extraction (N chunks failed). Use --allow-partial-promotion to proceed."` When `--allow-partial-promotion` is used, the flag is recorded in `oracle_metadata.promotion_notes`.
3. **Source Hash Verification Gate:** If the source PDF is accessible at its recorded path, the command recomputes its SHA-256 and compares against `oracle_metadata.source_document_hash`. A mismatch is a **hard error** unless `--override-hash-mismatch` is provided: `"Source document hash mismatch. The source PDF has been modified since extraction. Use --override-hash-mismatch to promote anyway."` When overridden, the mismatch is recorded in `oracle_metadata.promotion_notes`. If the source PDF is not accessible, a warning is emitted but promotion proceeds.
4. **Reviewer Identity:** Required via `--reviewer <name>` flag. Recorded in `oracle_metadata.promoted_by` and the manifest.
5. **Attestation Notes:** Optional via `--notes <text>`. Recorded in `oracle_metadata.promotion_notes` (appended after any gate override notes). If omitted and no gate overrides were recorded, defaults to `"Reviewed and approved."`
6. **Explicit Confirmation:** Interactive `y/N` prompt after displaying the summary and any warnings.

**Non-Interactive Promotion:** Under `--non-interactive`, the interactive `y/N` confirmation is suppressed **only if** the `--yes` flag is also provided. Without `--yes`, the command errors: `"promote-pack requires interactive confirmation. Use --yes with --non-interactive to auto-confirm."` This prevents accidental automated promotion while enabling legitimate CI use.

The `oracle_metadata` block in the pack file is updated with `promoted_at`, `promoted_by`, and `promotion_notes`. The manifest entry is updated to mirror these fields.

### 6.3 Name Resolution

Pack names are slugified (lowercase, non-alphanumeric → underscore). Lookup supports fuzzy matching: if the user-provided name is a substring of exactly one registered slug, resolve to that pack. If ambiguous (multiple matches), error with the list of matches.

---

## 7. Review Integration

### 7.1 Document Ingestion

ORACLE must handle multiple input formats:

| Format | Method |
|--------|--------|
| `.md`, `.txt`, `.py`, `.json`, `.yaml` | Direct `read_text()` |
| `.pdf` | PyMuPDF text extraction (`page.get_text("text")`) with quality check |
| `.docx` | `pandoc` conversion to markdown (required) |

**PDF Text Quality Check:** After extraction, compute average characters per page. If the average is below 100 characters/page (indicating a scanned or image-only PDF), abort with a clear error: `"PDF appears to be scanned/image-only (avg N chars/page). Use --force-text-only to proceed with extracted text as-is, or convert to text-based PDF first."` This prevents silently reviewing empty documents.

**`--force-text-only`:** When provided, the review proceeds with whatever text was extracted from the PDF, even if quality is below threshold. A warning is emitted to stderr and recorded in session metadata: `"⚠ Low-quality PDF text extraction (avg N chars/page). Review may be incomplete."`

**DOCX Handling:** DOCX conversion requires `pandoc` to be installed. If `pandoc` is not available, the command errors with: `"DOCX conversion requires pandoc. Install pandoc (https://pandoc.org/installing.html) or convert the document to PDF/markdown first."` No silent fallback is attempted.

### 7.2 Pack Rendering and Token Budget

Each selected pack is rendered to text using a schema-specific renderer:

- **GPCM:** `[<pack_id>:<id>] [MPR N] §X.X [SHALL]: statement_text`
- **FAR:** Tier 1 summary always, Tier 2 full text for parts specified via `--pack-parts`, each as `[<pack_id>:<id>] §X.X [SHALL]: text`. Uses existing `render_for_oracle()` with ORACLE citation wrapper.
- **Generic:** `[<pack_id>:<rule_id>] §X.X [SHALL] (SEVERITY): statement_text`

All renderers prepend `pack_id` and canonical `rule_id` to each rule line, enabling reviewers to produce citations (see Section 7.3).

Multiple packs are joined with `---` separators and labeled `Authority 1: <pack_name> (pack_id: <pack_id>)`, `Authority 2: <pack_name> (pack_id: <pack_id>)`, etc.

**Token Budget Strategy:**

The compliance context is subject to a token budget that accounts for total prompt size, not just the compliance text in isolation.

1. **Effective Budget Calculation:** The total available context is the minimum context window across all configured reviewer models (per Section 10 model context-window table). The compliance context budget is:
   ```
   compliance_budget = min_model_context_window
                       - estimated_document_tokens
                       - system_prompt_reserve (fixed: 4,000 tokens)
                       - response_headroom (fixed: 8,000 tokens)
                       - per_round_overhead (fixed: 2,000 tokens)
   ```
   The `ORACLE_MAX_CONTEXT_TOKENS` environment variable sets an **upper cap** on the compliance budget (default: 80,000), but the effective budget is `min(ORACLE_MAX_CONTEXT_TOKENS, computed_budget)`. Token estimation uses a simple heuristic of 4 characters per token.

   If a configured model name is not found in the context-window table (Section 10), the command errors: `"Unknown model [name]. Context window size is required for token budget calculation. Add the model to the context-window configuration or set ORACLE_MAX_CONTEXT_TOKENS to use a fixed budget."` As a fallback, if `ORACLE_MAX_CONTEXT_TOKENS` is explicitly set, the per-model lookup is skipped and the fixed cap is used as the total budget (with document size and reserves still subtracted).

2. **If within budget:** Use full rendered text.
3. **If over budget:** Apply deterministic reduction in this order:
   a. For FAR packs without explicit `--pack-parts`: include Tier 1 summary only (drop Tier 2).
   b. For generic packs: include critical and high severity rules only, with a count of omitted medium/low rules appended.
   c. For GPCM packs: include MUA-relevant requirements first (`mua_relevant: true`), then include remaining requirements up to the available budget. Omitted non-MUA requirements are counted and appended as a summary line.
   d. If still over budget: truncate the lowest-priority pack (last in the `--packs` list) to its summary header + rule count, and emit a warning: `"⚠ Pack [name] truncated to summary. Specify --pack-parts or reduce pack count for full coverage."`
4. **Never silently truncate.** All reductions emit warnings to stderr and are recorded in session metadata.
5. **Budget Exhaustion:** If the document alone exceeds the available context window (after reserves), the command errors with: `"Document too large (est. N tokens) for the smallest configured model context window (M tokens). Reduce document size or increase model context capacity."`

**Per-Pack Part Scoping (FAR-family):**

The `--pack-parts` flag scopes part selection to a specific pack:

```
oracle review doc.md --packs far dfars --pack-parts far=15,19 --pack-parts dfars=252
```

If `--pack-parts` is provided without a pack prefix (e.g., `--pack-parts 15,19`), it applies only if exactly one FAR-family pack is selected. If multiple FAR-family packs are selected and `--pack-parts` has no prefix, the command errors with: `"Multiple FAR-family packs selected. Use --pack-parts <pack>=<parts> to specify per-pack."`

### 7.3 Oracle2 Invocation and Return Contract

The rendered compliance context is passed to `oracle2.run_review()` as the `compliance_context` parameter. Oracle2's existing mechanism injects this into the reviewer prompt under a "Compliance Rule Pack" header.

**Citation Strategy — No oracle2 Modification Required:**

Pack citations are enabled through the compliance_context text itself, not through oracle2 code changes:

1. **Renderer Augmentation:** All pack renderers emit `pack_id` and canonical `rule_id` on every rule line (see Section 7.2). This ensures the identifiers are visible to all reviewer oracles.
2. **Citation Instructions in Context:** The rendered compliance_context includes a header block instructing reviewers to reference rules by their `[pack_id:rule_id]` identifier when raising compliance findings. This instruction is part of the text payload, not an oracle2 code change.
3. **Best-Effort Citation Reconstruction:** The `oracle2_adapter` performs best-effort extraction of `[pack_id:rule_id]` references from the `evidence_text` field of normalized issues (see NormalizedIssue schema below). If a reviewer cites a rule by section number or text rather than identifier, the adapter attempts fuzzy matching against the rendered compliance context. Unresolvable citations are recorded as empty `pack_citations` arrays.

This approach preserves the non-goal of not modifying oracle2 while providing citation support through the existing `compliance_context` integration point. Citation quality depends on reviewer models following the embedded instructions.

**Return Contract (oracle2 → ORACLE):**

ORACLE requires the following data from oracle2 after a review completes. If oracle2 exposes a programmatic return value, it must conform to this schema. If not, the `oracle2_adapter` module parses oracle2's output files from the session directory.

```python
@dataclass
class ReviewResult:
    session_id: str
    session_dir: Path
    final_draft: str                    # The converged document text
    rounds: list[RoundData]             # Per-round structured data
    converged: bool                     # Whether review reached convergence
    total_rounds: int
    metrics: MetricsSummary             # Aggregated metrics for findings report

@dataclass
class MetricsSummary:
    accepted_by_severity: dict[str, int]  # {"critical": 2, "high": 5, ...}
    rejected_count: int
    preference_only_count: int
    unresolved_count: int
    duplicate_count: int                  # Issues merged by normalizer
    rounds_to_stability: int              # Last round in which a new critical/high
                                          # issue was accepted; 0 = stable from start
    total_issues_raised: int
    total_issues_accepted: int

@dataclass
class RoundData:
    round_number: int
    normalized_issues: list[NormalizedIssue]
    coordinator_decisions: list[CoordinatorDecision]
    revised_draft: str

@dataclass
class NormalizedIssue:
    issue_id: str                       # e.g., "R1-ISSUE-003"
    title: str
    severity: str                       # critical|high|medium|low
    category: str
    core_problem: str
    recommended_fix: str
    source_oracles: list[str]
    evidence_text: str                  # Original reviewer prose preserving citation-bearing language
    pack_citations: list[PackCitation]  # Ties findings to pack rules (best-effort)

@dataclass
class PackCitation:
    pack_id: str                        # rule_pack_id from the pack
    authority_label: str                # "Authority 1", "Authority 2", etc.
    rule_id: str                        # e.g., "RULE-0042", "far-15-001", "stmt-001"
    section: str                        # §X.X from the rule

@dataclass
class CoordinatorDecision:
    issue_id: str
    decision: str                       # accepted_defect|rejected_claim|preference_only|unresolved_question
    reason: str
```

**Adapter Preflight Check:**

Before parsing session files, the `oracle2_adapter` performs a structural preflight check of the session directory:

1. Verify that `session_summary.json` exists and contains `session_id` and `total_rounds` fields.
2. Verify that at least one normalized-issues file exists: `round*_sonnet_normalized.json` (ledger workflow) or `round*_beth_normalized.json` (manual workflow — the default).
3. Verify that `final_draft.md` exists.

Missing `session_summary.json` or `final_draft.md` is a **hard failure**; a missing normalized-issues file alone is a warning at preflight, because a non-converged session (e.g., every round invalid after a vendor outage) legitimately produces none. The hard guard runs after parsing instead: a session that **claims convergence** must yield at least one *readable* normalized-issues file (existence is not enough — a truncated file or an unrecognized shape counts as unreadable). If it does not, reconstruction fails with an out-of-sync error rather than silently reporting a clean review.

If preflight fails on the hard checks, the adapter emits an actionable error: `"oracle2 session directory structure is incompatible. Expected: [list of missing files]. Found: [list of actual files]. The oracle2_adapter may need updating for this version of oracle2."` This makes the oracle2 dependency explicit and fail-fast rather than producing cryptic parse errors during reconstruction.

**Adapter Strategy and File Schema Expectations:**

If oracle2 does not return a `ReviewResult` object directly, the `oracle2_adapter` module reconstructs it by parsing the known output files from the session directory. The adapter defines the following normative expectations for each file:

| File Pattern | Required Fields | Maps To |
|---|---|---|
| `round*_sonnet_normalized.json` | `normalized_issues[]` with: `issue_id`, `title`, `severity`, `category`, `core_problem`, `recommended_fix`, `source_oracles[]`, `best_evidence` (mapped to `evidence_text`) | `RoundData.normalized_issues` |
| `round*_beth_decisions.json` | `revision_decisions[]` with: `issue_id`, `decision`, `reason` | `RoundData.coordinator_decisions` |
| `round*_revised_draft.md` | Plain text (full revised document) | `RoundData.revised_draft` |
| `final_draft.md` | Plain text (full final document) | `ReviewResult.final_draft` |
| `session_summary.json` | `session_id`, `total_rounds`, `converged` | `ReviewResult.session_id`, `.total_rounds`, `.converged` |

The `evidence_text` field in `NormalizedIssue` is populated from the `best_evidence` field in the normalizer's output (or concatenated from `core_problem` + `recommended_fix` if `best_evidence` is absent). This field preserves the citation-bearing prose that the adapter scans for `[pack_id:rule_id]` patterns.

The adapter computes `MetricsSummary` by aggregating across all rounds: counting decisions by type, counting severity categories among accepted defects, and determining `rounds_to_stability` as the last round in which a new critical or high issue was accepted.

The adapter performs best-effort `pack_citations` extraction by scanning the `evidence_text` field of each normalized issue for `[pack_id:rule_id]` patterns and fuzzy-matching section references against the compliance context used for the session.

If any required file is missing or fails to parse (beyond the preflight check), the adapter emits an actionable error identifying the file and expected structure, and falls back to partial reconstruction (populating available fields, leaving others as empty/default).

### 7.4 Output Structure

```
oracle_reviews/<session_id>/
├── findings_report.md         ← NEW: formatted findings report
├── final_draft.md             ← canonical revised document (from oracle2)
├── session_summary.json       ← round-by-round stats (from oracle2)
├── metrics.json               ← QC scoring rubric (from oracle2)
├── compliance_context.txt     ← NEW: exact rendered compliance text used
├── pack_manifest_snapshot.json← NEW: selected packs with content hashes
├── round1_fran.json           ← per-oracle outputs (from oracle2)
├── round1_codex.json
├── round1_grok.json
├── round1_sonnet_normalized.json
├── round1_beth_decisions.json
├── round1_revised_draft.md
└── ... (additional rounds)
```

**Pack Snapshot:** `pack_manifest_snapshot.json` records the exact packs used for this review:

```json
{
  "packs_used": [
    {
      "slug": "nasa_std_6016c",
      "content_hash": "sha256:abcdef...",
      "version": "1.0.0",
      "status": "draft|promoted",
      "rule_count": 67
    }
  ],
  "compliance_context_hash": "sha256:123456...",
  "token_budget": 80000,
  "effective_budget": 62000,
  "document_token_estimate": 14000,
  "truncation_applied": false,
  "truncation_details": []
}
```

**Auditability:** The session directory preserves two artifacts that support audit and partial reproducibility:

1. **`compliance_context.txt`** — the exact rendered compliance text injected into reviewer prompts. This is the definitive record of what rules the reviewers saw, and is preserved regardless of subsequent pack modifications or overwrites.
2. **`pack_manifest_snapshot.json`** — content hashes identifying which pack versions were used. If a pack is later overwritten, the hash mismatch indicates the pack has changed, but the original pack JSON is not recoverable from the session directory alone.

The `compliance_context.txt` file ensures that the compliance rules used in a review are always recoverable. However, full reproducibility (re-running the same review with identical inputs) requires that the original pack files still exist unchanged. See Section 13.4 for overwrite limitations.

**Reproducibility Constraint:** The audit guarantees assume sequential, single-user operation of the CLI against the pack library. Concurrent `generate-pack`, `promote-pack`, or `remove-pack` operations can corrupt the manifest and invalidate content-hash audit trails. Multi-user environments must use separate pack directories or coordinate externally (see Section 14).

---

## 8. Findings Report Format

The findings report (`findings_report.md`) is a structured summary generated from the oracle session's `ReviewResult` (Section 7.3). It contains:

1. **Header:** Document name, session ID, round count, convergence status
2. **Authority Summary:** List of packs used, with content hashes and status (draft/promoted). If any draft pack was used, a prominent warning: `"⚠ This review used unverified (draft) rule packs. Findings should be validated against source regulations."` If any generic pack was used, a notice: `"ℹ Generic pack extraction may miss obligations spanning chunk boundaries. See pack metadata for extraction coverage."` If any pack was generated with `detection_override`, a notice: `"ℹ Pack [name] was generated with --force-type [type], bypassing automatic document type detection."`
3. **Metrics Summary:** Derived from `MetricsSummary` (Section 7.3): accepted defects by severity, rejected count, preference-only count, unresolved count, duplicate count, rounds to stability, total issues raised vs. accepted.
4. **Per-Round Detail:**
   - Normalized issues with severity, title, problem, fix, source oracles
   - Pack citations: for each compliance finding, the specific rule_id, section, and pack that triggered it (best-effort; may be empty if reviewers did not cite specific rules)
   - Coordinator decisions (accepted_defect, rejected_claim, preference_only, unresolved_question)
5. **Open Questions:** Unresolved tradeoffs that persisted through convergence

The report references findings by `issue_id` (e.g., `R1-ISSUE-003`) matching oracle2's internal tracking.

---

## 9. CLI Interface

```
oracle <command> [options]

Commands:
  review          Review a document against selected rule packs
  generate-pack   Generate a rule pack from a regulatory PDF
  list-packs      List all packs in the library
  add-pack        Import an existing rule pack JSON into the library
  remove-pack     Remove a pack from the library
  show-pack       Display pack contents and stats
  promote-pack    Mark a draft pack as reviewed/promoted

review:
  oracle review <document> [--packs <name> ...] [--pack-parts <pack>=<N,N> ...] [--max-rounds N] [--output-dir DIR] [--force-text-only]

generate-pack:
  oracle generate-pack <pdf> [--name NAME] [--output-dir DIR] [--no-vision] [--force-type TYPE] [--no-register] [--allow-partial] [--overwrite] [--non-interactive]

list-packs:
  oracle list-packs

add-pack:
  oracle add-pack <json_file> [--name NAME] [--description TEXT]

remove-pack:
  oracle remove-pack <name>

show-pack:
  oracle show-pack <name> [-v]

promote-pack:
  oracle promote-pack <name> --reviewer <name> [--notes <text>] [--allow-partial-promotion] [--override-hash-mismatch] [--yes]

Global:
  --verbose / -v      Verbose logging
  --pack-dir DIR      Override pack library location
  --non-interactive   Suppress confirmation prompts (use defaults)
```

**Notable behaviors:**
- `--packs` is optional. Without it, oracle2 runs without compliance_context (general-purpose review).
- `--pack-parts` scopes FAR Tier 2 detail to specific packs and parts (see Section 7.2).
- `--force-text-only` allows reviewing PDFs that fail the text quality check (see Section 7.1).
- `--overwrite` is required when `generate-pack` targets an existing pack name. Without it, the command errors: `"Pack [name] already exists. Use --overwrite to replace."`
- `--allow-partial` permits registration of packs with incomplete extraction (failed chunks).
- `--reviewer` is required for `promote-pack`. Identifies who reviewed and approved the pack.
- `--allow-partial-promotion` permits promoting packs with `extraction_status: "partial"` (see Section 6.2).
- `--override-hash-mismatch` permits promoting packs where the source document hash has changed (see Section 6.2).
- `--yes` auto-confirms the interactive `y/N` prompt. Required alongside `--non-interactive` for `promote-pack`.
- `--non-interactive` combined with low-confidence detection is a hard error unless `--force-type` is also provided (see Section 5.1).
- `--non-interactive` combined with `promote-pack` requires `--yes` to proceed (see Section 6.2).

---

## 10. Environment Variables and Model Configuration

### 10.1 Environment Variables

| Variable | Required For | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | All oracle calls + generic extraction | (none) |
| `OPENAI_API_KEY` | Review (Fran, Codex) | (none) |
| `XAI_API_KEY` | Review (Grok) | (none) |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Review (Gemini) | (none) |
| `ORACLE_WORKFLOW` | Review workflow | `manual` |
| `ORACLE_BETH_MODEL` | Review | `claude-opus-4-8` |
| `ORACLE_SONNET_MODEL` | Review | `claude-sonnet-4-6` |
| `ORACLE_FRAN_MODEL` | Review | `gpt-5.4` |
| `ORACLE_CODEX_MODEL` | Review | `gpt-5.4` |
| `ORACLE_GROK_MODEL` | Review | `grok-4.20` |
| `ORACLE_GEMINI_MODEL` | Review | `gemini-2.5-pro` |
| `ORACLE_VISION_MODEL` | Generic extraction | `claude-sonnet-4-6` |
| `ORACLE_TIMEOUT_SECONDS` | All calls | `600` |
| `ORACLE_PACK_DIR` | Pack library location | `~/.oracle/packs/` |
| `ORACLE_MAX_CONTEXT_TOKENS` | Upper cap on compliance context budget | `80000` |

### 10.2 Model Context-Window Table

The token budget calculation (Section 7.2) requires the context-window size for each configured reviewer model. ORACLE maintains the following authoritative mapping:

| Model ID | Context Window (tokens) | Used By |
|----------|------------------------|---------|
| `claude-opus-4-8` | 200,000 | Beth (manual normalizer / coordinator) |
| `claude-opus-4-6` | 200,000 | Beth fallback |
| `claude-sonnet-4-6` | 200,000 | Sonnet (referee), Vision extraction |
| `gpt-5.4` | 128,000 | Fran (adversarial), Codex (feasibility) |
| `grok-4.20` | 131,072 | Grok (contrarian) |
| `gemini-2.5-pro` | 1,048,576 | Gemini (broad-context reviewer) |

The minimum context window across all configured reviewer models determines the effective budget. For the default configuration, this is `min(200000, 200000, 128000, 128000, 131072, 1048576) = 128,000` tokens.

**Unknown Model Handling:** If a configured model name (via environment variable) is not present in this table, the behavior depends on `ORACLE_MAX_CONTEXT_TOKENS`:
- If `ORACLE_MAX_CONTEXT_TOKENS` is explicitly set: the fixed cap is used as the total budget, bypassing per-model lookup. A warning is emitted: `"Unknown model [name]. Using ORACLE_MAX_CONTEXT_TOKENS (N) as fixed budget."`
- If `ORACLE_MAX_CONTEXT_TOKENS` is not set (using default): the command errors: `"Unknown model [name]. Context window size is required for token budget calculation. Set ORACLE_MAX_CONTEXT_TOKENS or use a known model ID."`

**Updating the Table:** This table reflects model capabilities as of the spec date. When models are updated or new models are added, this table must be updated in the implementation. The model IDs are configurable via environment variables (Section 10.1), allowing operators to use different models without spec changes, provided `ORACLE_MAX_CONTEXT_TOKENS` is set for unknown models.

---

## 11. Dependencies

### 11.1 Python Packages (existing)

- `anthropic` — Anthropic API client
- `openai` — OpenAI API client (also used for xAI)
- `PyMuPDF (fitz)` — PDF processing
- `httpx` — HTTP client with timeout support
- `jsonschema` — JSON Schema validation (NEW)

### 11.2 System Dependencies

- `pandoc` — Required for DOCX-to-markdown conversion. Not needed if DOCX input is not used.

### 11.3 Internal Modules (existing, unchanged)

- `oracle2.py` — review engine
- `shall_extractor.py` — obligation extraction
- `build_gpcm_rulepack.py` — GPCM pipeline
- `build_far_rulepack.py` — FAR pipeline
- `gpcm_rulepack_adapter.py` — enrichment and vision repair

### 11.4 Internal Modules (NEW)

- `oracle2_adapter.py` — Parses oracle2 output files into `ReviewResult` schema (see Section 7.3 for preflight check and file expectations)
- `pack_validator.py` — JSON Schema validation for pack files

---

## 12. Testing / Acceptance Criteria

### 12.1 Pack Generation

| Test | Input | Expected |
|------|-------|----------|
| Tagged standard detection | NASA-STD-6016C PDF | `tagged_standard` detected, routes to GPCM pipeline |
| FAR detection | FAR PDF | `far_style` detected, routes to FAR pipeline |
| Generic detection | 21 CFR Part 211 PDF | `generic` detected, routes to Claude extraction |
| Low-confidence detection prompts user | Ambiguous PDF | Confidence < 0.7, user prompted for confirmation |
| Low-confidence non-interactive error | Ambiguous PDF with `--non-interactive` | Hard error: detection confidence too low |
| Low-confidence non-interactive with force-type | Ambiguous PDF with `--non-interactive --force-type generic` | Proceeds with generic pipeline |
| Confidence formula deterministic | PDF with 5 MPR tags across 3 of 10 pages | Score = min(1.0, (5/3) × (0.5 + 0.5 × 3/10)) = min(1.0, 1.667 × 0.65) = min(1.0, 1.083) = 1.0 |
| Confidence formula low-match | PDF with 2 MPR tags on 1 of 10 pages | Score = min(1.0, (2/3) × (0.5 + 0.5 × 1/10)) = min(1.0, 0.667 × 0.55) = 0.367 (below 0.7) |
| Tie-break specificity | PDF matching both tagged_standard and far_style at same score | tagged_standard selected (more specific) |
| Generic extraction against gold corpus | Fixture PDF with 20 known obligations | ≥90% recall against gold-standard extracted statements; precision ≥85% |
| Generic extraction retries malformed JSON | Fixture prompt that triggers malformed response | Retry occurs, logged, final result valid or chunk marked failed |
| Chunk failure metadata persisted | PDF with failing chunks | `chunk_failures` array populated with page_start, page_end, retries_used, final_error, extraction_mode |
| Pack registration as draft | Any generated pack | Appears in `manifest.json` with `status: "draft"`, file exists in pack library, `oracle_metadata` populated |
| Pack schema validation | Generated pack JSON | Validates against corresponding JSON Schema without errors |
| Force-type override | Any PDF with `--force-type generic` | Uses generic pipeline; `oracle_metadata.detection_override` = `"generic"` |
| Force-type audit trail | Pack generated with `--force-type` | `detection_override` field is non-null in pack file |
| No-vision mode | Any PDF with `--no-vision` | Text-only extraction, no image rendering |
| Partial pack requires flag | PDF with failing chunks, no `--allow-partial` | Registration aborted with summary of failed pages |
| Overwrite protection | Generate pack with existing name, no `--overwrite` | Error: pack already exists |
| Source document hash | Generated pack from PDF | `oracle_metadata.source_document_hash` contains SHA-256 of source PDF |

### 12.2 Pack Library

| Test | Action | Expected |
|------|--------|----------|
| List empty library | `list-packs` on fresh install | Prints "No packs in library" message |
| Add valid pack | `add-pack` with valid JSON | Schema validated, pack appears in manifest, file copied |
| Add valid pack without oracle_metadata | `add-pack` with valid JSON missing oracle_metadata | oracle_metadata auto-populated with defaults, then validated, pack registered |
| Add invalid pack | `add-pack` with malformed JSON | Rejected with field-level validation errors |
| Remove pack | `remove-pack` with valid name | Pack removed from manifest, file deleted |
| Show pack | `show-pack` with valid name | Stats printed including status (draft/promoted), no errors |
| Show pack verbose | `show-pack -v` | Rendered oracle-facing text printed with pack_id:rule_id identifiers |
| Fuzzy name match | `show-pack 6016` with `nasa_std_6016c` registered | Resolves to correct pack |
| Ambiguous name | `show-pack std` with multiple `*std*` packs | Error listing matches |
| Promote pack | `promote-pack <name> --reviewer "J. Smith"` on draft pack | Status changes to "promoted", `promoted_at` and `promoted_by` set in both manifest and pack file |
| Promote pack without reviewer | `promote-pack <name>` (no --reviewer) | Error: --reviewer is required |
| Promote partial pack without flag | `promote-pack <name> --reviewer "J. Smith"` on partial pack | Error: cannot promote partial extraction without --allow-partial-promotion |
| Promote partial pack with flag | `promote-pack <name> --reviewer "J. Smith" --allow-partial-promotion` | Promoted; override recorded in promotion_notes |
| Promote with hash mismatch | `promote-pack` when source PDF changed | Error: hash mismatch, requires --override-hash-mismatch |
| Promote with hash mismatch override | `promote-pack --override-hash-mismatch --reviewer "J. Smith"` | Promoted; mismatch recorded in promotion_notes |
| Promote non-interactive without --yes | `promote-pack <name> --reviewer "J. Smith" --non-interactive` | Error: --yes required for non-interactive promotion |
| Promote non-interactive with --yes | `promote-pack <name> --reviewer "J. Smith" --non-interactive --yes` | Promoted without interactive prompt |
| Manifest rebuild | Corrupt manifest.json | Manifest rebuilt from oracle_metadata in pack files |
| Custom pack dir | `--pack-dir /tmp/packs` | Library operations use specified directory |

### 12.3 Review Integration

| Test | Action | Expected |
|------|--------|----------|
| Review without packs | `review doc.md` (no `--packs`) | oracle2 runs without compliance_context |
| Review with one pack | `review doc.md --packs nasa_std_6016c` | Pack rendered with pack_id:rule_id identifiers, injected as compliance_context |
| Review with multiple packs | `review doc.md --packs pack1 pack2` | Both packs rendered, joined with separators and authority labels including pack_ids |
| FAR per-pack parts | `review doc.md --packs far dfars --pack-parts far=15,19 --pack-parts dfars=252` | Tier 2 detail scoped per pack |
| Ambiguous --pack-parts error | `review doc.md --packs far dfars --pack-parts 15,19` | Error: must specify pack prefix |
| Token budget overflow | Review with packs exceeding effective budget | Deterministic reduction applied, warnings emitted, no silent truncation |
| Token budget accounts for document size | Review with large document and packs | Effective budget reduced by document token estimate; compliance context sized accordingly |
| Token budget with unknown model | Review with unknown model ID, no ORACLE_MAX_CONTEXT_TOKENS | Error: unknown model, context window required |
| Token budget with unknown model and fixed cap | Review with unknown model ID, ORACLE_MAX_CONTEXT_TOKENS=100000 | Warning emitted, fixed cap used |
| Document too large | Review with document exceeding model context | Error: document too large for smallest configured model |
| PDF document input | `review document.pdf --packs ...` | PDF text extracted with quality check, review proceeds |
| Scanned PDF detection | `review scanned.pdf` (image-only) | Error: low text quality detected |
| Scanned PDF with force | `review scanned.pdf --force-text-only` | Proceeds with warning, review runs on sparse text |
| DOCX document input | `review document.docx --packs ...` | Pandoc converts, review proceeds |
| DOCX without pandoc | `review document.docx` (pandoc not installed) | Error: pandoc required for DOCX |
| Adapter preflight check passes | Review with valid oracle2 session | Preflight passes, ReviewResult constructed |
| Adapter preflight check fails | Review with missing session files | Actionable error listing expected vs. found files |
| Findings report generated | Any completed review | `findings_report.md` exists in output directory |
| Findings cite pack rules | Review with packs | Findings reference specific rule_ids from packs (best-effort) |
| Pack snapshot saved | Any completed review | `pack_manifest_snapshot.json` exists with content hashes and effective budget |
| Compliance context preserved | Any completed review | `compliance_context.txt` exists with exact rendered text |
| Draft pack warning | Review using draft pack | Warning in stderr and findings report |
| Generic pack notice | Review using generic pack | Notice about chunk boundary limitations in findings report |
| Force-type pack notice | Review using pack with detection_override | Notice in findings report about overridden detection |
| Missing pack name | `review doc.md --packs nonexistent` | Clear error listing available packs |

### 12.4 End-to-End

| Test | Workflow | Expected |
|------|----------|----------|
| Full cycle | `generate-pack regulation.pdf` → `promote-pack <name> --reviewer "J. Smith"` → `list-packs` → `review doc.md --packs <name>` | Pack generated as draft, promoted with reviewer identity, listed, review completes with compliance findings citing specific rules |
| Multi-pack review | Generate 2 packs → review against both | Findings reference requirements from both packs via pack_citations |
| Reproducibility audit | Complete a review, then re-examine session | `pack_manifest_snapshot.json` contains content hashes matching the packs used; `compliance_context.txt` preserves the exact compliance text |

---

## 13. Implementation Notes

### 13.1 oracle.py Does Not Modify oracle2.py

ORACLE imports `oracle2.run_review` and `oracle2.compute_metrics` as black-box functions. The primary integration point is the `compliance_context` parameter. Citation support is provided by embedding citation instructions and rule identifiers in the compliance_context text — no oracle2 code changes are required. For structured return data, the `oracle2_adapter` module parses oracle2's output files into the `ReviewResult` schema (Section 7.3). This adapter is the only component that depends on oracle2's file output format, and it performs a preflight check (Section 7.3) to fail fast on incompatible session directory structures.

### 13.2 Pack Library Is Stateless Per-Session

The manifest is read fresh on every command. No in-memory caching. No locking. If two processes write simultaneously, last-write-wins. This is acceptable for CLI usage. Multi-user environments should use separate pack directories or coordinate externally.

### 13.3 Generic Extraction Chunking

5 pages per chunk with 1-page overlap is the default. The overlap ensures obligations spanning page breaks at chunk boundaries are captured by at least one chunk. This adds ~20% more API calls but significantly reduces missed obligations. Deduplication using the composite key `(section, normalized_statement_text)` handles the resulting duplicates while preserving legally distinct obligations that share identical text across different sections.

Each chunk extraction includes bounded retry (max 2 retries) for malformed JSON responses. Retry counts and failure reasons are persisted in the `chunk_failures` array in the pack file (see Section 4.3).

**Known Limitation:** Obligations that span more than 1 page may still be missed at chunk boundaries. This is documented in pack metadata and surfaced in findings reports for all reviews using generic packs (see Section 8, Authority Summary).

### 13.4 Pack Versioning and Overwrite Protection

Packs have a `version` field and a `content_hash` (SHA-256 of the pack JSON content). Re-generating a pack with the same name requires the `--overwrite` flag. Without it, the command errors. When `--overwrite` is used, the previous pack file is replaced and the manifest entry is updated with new metadata.

Review sessions record `content_hash` values in `pack_manifest_snapshot.json`, enabling identification of which pack version was used for a given review.

**Limitation:** No version history is maintained in v1. When `--overwrite` replaces a pack, the previous pack content is permanently lost. The `content_hash` in past `pack_manifest_snapshot.json` files will identify that a different version was used, but the actual content of the overwritten pack cannot be recovered from the snapshot alone.

**Mitigation:** The `compliance_context.txt` file in each session directory (Section 7.4) preserves the exact rendered compliance text that was used for that review. This means the rules as presented to reviewers are always recoverable, even if the underlying pack is overwritten. However, full pack metadata (e.g., extraction status, chunk failures) is not preserved in the session directory.

Users requiring full auditability of pack evolution should name pack versions distinctly (e.g., `dfars_252_v1`, `dfars_252_v2`) rather than overwriting.

### 13.5 Error Recovery

- If a reviewer oracle fails during review, oracle2 marks the round as invalid and continues to the next round (existing behavior).
- If a chunk fails during generic extraction after retries, log the error (with retry count and failure reason) and continue to the next chunk. The pack records structured failure metadata in `chunk_failures` and summary data in `failed_page_ranges` and `extraction_status`.
- If the manifest is corrupted (JSON parse failure), back up the corrupt file as `manifest.json.corrupt.<timestamp>`, then rebuild the manifest by scanning the pack library directory, validating each pack JSON, and reconstructing manifest entries from the `oracle_metadata` block in each pack file. The `content_hash` is recomputed from the pack file content. The `source_document` path is recovered from the pack's top-level `source_document` field (present in all three schemas). Only fall back to an empty manifest if no valid pack files are found. Log the recovery action.

---

## 14. Future Considerations (Not In Scope for v1)

- **Web UI:** React frontend for pack management and review initiation
- **DOCX output:** Formatted findings report as Word document
- **Pack diffing:** Compare two versions of the same regulation's pack
- **Pack composition:** Create composite packs from multiple source packs
- **Incremental extraction:** Only re-extract pages that changed between regulation versions
- **Pack sharing:** Export/import packs between BoundState installations
- **FORGE integration:** ORACLE as a FORGE module for automated compliance review pipelines
- **OCR fallback:** Automatic OCR for scanned PDFs using Tesseract or cloud OCR services
- **Concurrency safety:** File locking or SQLite backend for multi-user shared library scenarios
- **Pack version archiving:** Automatic archival of previous pack versions on overwrite for full audit trails
- **GPCM severity field:** Add severity taxonomy to GPCM schema (v2) to align reduction strategy with generic packs
- **Externalized model config:** Move model context-window table to a config file for easier updates without spec changes
