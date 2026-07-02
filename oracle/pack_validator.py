#!/usr/bin/env python3
"""
Module: pack_validator
Purpose: JSON Schema validation for ORACLE rule packs and manifest.

All three pack schemas (GPCM, FAR, Generic) and the manifest are validated
against normative JSON Schemas defined inline. This module enforces schema
compliance at two gates:
  1. generate-pack: output validated before registration
  2. add-pack: imported JSON validated after oracle_metadata normalization

The schemas serve as the authoritative definition of pack structure.
If a pack file doesn't validate, it doesn't enter the library.

Safety:
  __safety_critical__ = True  — invalid packs could cause false compliance findings

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True

import logging
import re
from typing import Any

LOGGER = logging.getLogger("oracle.pack_validator")

# ---------------------------------------------------------------------------
# We inline the schemas here rather than loading from external .json files.
# This ensures the validator is self-contained and the schemas travel with
# the code. Each schema defines required fields, types, and constraints
# per ORACLE_SPEC v1.3 Section 4.4.
# ---------------------------------------------------------------------------

# Shared oracle_metadata sub-schema — required in all pack types
_ORACLE_METADATA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["name", "slug", "status", "added_at"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "slug": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "status": {"type": "string", "enum": ["draft", "promoted"]},
        "added_at": {"type": "string"},
        "promoted_at": {"type": ["string", "null"]},
        "promoted_by": {"type": ["string", "null"]},
        "promotion_notes": {"type": ["string", "null"]},
        "source_document_hash": {"type": ["string", "null"]},
        "detection_override": {"type": ["string", "null"]},
    },
}

# ---------------------------------------------------------------------------
# GPCM Rule Pack Schema (gpcm_rulepack/v1)
# Used for NASA tagged standards with [MPR N] / [FCR N] markers
# ---------------------------------------------------------------------------
GPCM_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "GPCM Rule Pack",
    "type": "object",
    "required": [
        "schema_version", "rule_pack_id", "standard_id",
        "version", "generated_at", "total_requirements",
        "requirements", "oracle_metadata",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "gpcm_rulepack/v1"},
        "rule_pack_id": {"type": "string", "minLength": 1},
        "standard_id": {"type": "string", "minLength": 1},
        "version": {"type": "string"},
        "generated_at": {"type": "string"},
        "source_document": {"type": "string"},
        "source_extract": {"type": "string"},
        "extraction_status": {"type": "string", "enum": ["complete", "partial"]},
        "total_requirements": {"type": "integer", "minimum": 0},
        "oracle_metadata": _ORACLE_METADATA_SCHEMA,
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "shall_text"],
                "properties": {
                    "id": {"type": "string"},
                    "source_tag": {"type": "string"},
                    "section": {"type": "string"},
                    "shall_text": {"type": "string"},
                    "subject": {"type": "string"},
                    "requirement": {"type": "string"},
                    "context": {"type": "string"},
                    "page": {"type": "integer"},
                    "justification": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "applies_to": {"type": "array", "items": {"type": "string"}},
                    "mua_relevant": {"type": "boolean"},
                    # Per-field provenance: "vision_repaired" marks fields
                    # that contain model-INTERPRETED text rather than
                    # mechanically extracted text (AUDIT B3).
                    "field_provenance": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "string",
                            "enum": ["extracted", "vision_repaired"],
                        },
                    },
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# FAR Rule Pack Schema (far_rulepack/v1)
# Used for FAR, DFARS, NFS, GSAM regulation packs
# ---------------------------------------------------------------------------
FAR_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "FAR Rule Pack",
    "type": "object",
    "required": [
        "schema_version", "rule_pack_id", "standard_id",
        "version", "generated_at", "total_binding_requirements",
        "parts_count", "part_index", "parts", "oracle_metadata",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "far_rulepack/v1"},
        "rule_pack_id": {"type": "string", "minLength": 1},
        "standard_id": {"type": "string", "minLength": 1},
        "standard_title": {"type": "string"},
        "version": {"type": "string"},
        "generated_at": {"type": "string"},
        "source_document": {"type": "string"},
        "extraction_status": {"type": "string", "enum": ["complete", "partial"]},
        "total_binding_requirements": {"type": "integer", "minimum": 0},
        "parts_count": {"type": "integer", "minimum": 0},
        "oracle_metadata": _ORACLE_METADATA_SCHEMA,
        "part_index": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["part", "total_binding"],
                "properties": {
                    "part": {"type": "integer"},
                    "title": {"type": "string"},
                    "mandatory_count": {"type": "integer"},
                    "prohibition_count": {"type": "integer"},
                    "total_binding": {"type": "integer"},
                    "section_count": {"type": "integer"},
                    "sections_covered": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "parts": {
            "type": "object",
            # Keys are Part numbers as strings, values are arrays of requirements
            "additionalProperties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "statement_text"],
                    "properties": {
                        "id": {"type": "string"},
                        "section": {"type": "string"},
                        "page": {"type": "integer"},
                        "obligation_type": {"type": "string"},
                        "obligation_keyword": {"type": "string"},
                        "statement_text": {"type": "string"},
                        "subject": {"type": "string"},
                        "requirement": {"type": "string"},
                        "justification": {"type": "string"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "applies_to": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Generic Rule Pack Schema (oracle_generic/v1)
# Used for cGMP, ISO, OSHA, ITAR, export controls, any normative document
# ---------------------------------------------------------------------------
GENERIC_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Generic Rule Pack",
    "type": "object",
    "required": [
        "schema_version", "rule_pack_id", "standard_id",
        "version", "generated_at", "total_rules",
        "rules", "oracle_metadata",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "oracle_generic/v1"},
        "rule_pack_id": {"type": "string", "minLength": 1},
        "standard_id": {"type": "string", "minLength": 1},
        "standard_title": {"type": "string"},
        "version": {"type": "string"},
        "generated_at": {"type": "string"},
        "source_document": {"type": "string"},
        "extraction_method": {"type": "string"},
        "extraction_status": {"type": "string", "enum": ["complete", "partial"]},
        "total_source_pages": {"type": "integer", "minimum": 0},
        "extracted_pages": {"type": "array"},
        "failed_page_ranges": {"type": "array"},
        "chunk_failures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["page_start", "page_end", "retries_used", "final_error"],
                "properties": {
                    "page_start": {"type": "integer"},
                    "page_end": {"type": "integer"},
                    "retries_used": {"type": "integer"},
                    "final_error": {"type": "string"},
                    "extraction_mode": {"type": "string"},
                },
            },
        },
        "total_rules": {"type": "integer", "minimum": 0},
        "oracle_metadata": _ORACLE_METADATA_SCHEMA,
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["rule_id", "statement_text"],
                "properties": {
                    "rule_id": {"type": "string"},
                    "obligation_type": {"type": "string"},
                    "obligation_keyword": {"type": "string"},
                    "section": {"type": "string"},
                    "statement_text": {"type": "string"},
                    "subject": {"type": "string"},
                    "requirement": {"type": "string"},
                    "context": {"type": "string"},
                    "justification": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "page": {"type": "integer"},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Schema Dispatch
# ---------------------------------------------------------------------------

# Map schema_version strings to their JSON Schema definitions
_SCHEMA_MAP: dict[str, dict[str, Any]] = {
    "gpcm_rulepack/v1": GPCM_SCHEMA,
    "far_rulepack/v1": FAR_SCHEMA,
    "oracle_generic/v1": GENERIC_SCHEMA,
}


def detect_schema_version(pack_data: dict[str, Any]) -> str | None:
    """Detect the schema_version from pack data.

    Returns the schema_version string if recognized, None otherwise.
    Also handles packs without explicit schema_version by sniffing fields.
    """
    sv = pack_data.get("schema_version", "")
    if sv in _SCHEMA_MAP:
        return sv

    # Heuristic fallback: sniff fields to guess schema. isinstance guards:
    # imported packs are arbitrary JSON — a list of strings here must yield
    # a validation error downstream, not an AttributeError traceback.
    if pack_data.get("requirements") and any(
        isinstance(r, dict) and (r.get("source_tag") or r.get("shall_text"))
        for r in pack_data.get("requirements", [])
    ):
        return "gpcm_rulepack/v1"
    if pack_data.get("part_index") and pack_data.get("parts"):
        return "far_rulepack/v1"
    if pack_data.get("rules") and any(
        isinstance(r, dict) and r.get("rule_id") for r in pack_data.get("rules", [])
    ):
        return "oracle_generic/v1"

    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_pack(pack_data: dict[str, Any]) -> list[str]:
    """Validate a pack against its JSON Schema.

    Returns a list of validation error messages. Empty list = valid.

    Uses jsonschema if available, falls back to structural checks if not.
    This dual approach ensures ORACLE works even without the jsonschema
    package, while providing full validation when available.
    """
    errors: list[str] = []

    # Determine schema
    schema_version = detect_schema_version(pack_data)
    if not schema_version:
        errors.append(
            f"Unrecognized schema_version: '{pack_data.get('schema_version', '')}'. "
            f"Expected one of: {', '.join(_SCHEMA_MAP.keys())}"
        )
        return errors

    schema = _SCHEMA_MAP[schema_version]

    # Try jsonschema library first (full validation).
    # WHY the except covers ONLY the import: this gate is safety-critical.
    # An exception raised *during* validation (schema/library version
    # mismatch, malformed inline schema) must surface, not silently
    # downgrade full validation to the weaker structural fallback — that
    # would let an invalid pack into the library with a DEBUG-level log
    # as the only trace.
    try:
        import jsonschema
    except ImportError:
        LOGGER.debug("jsonschema not installed — using structural validation fallback")
    else:
        validator_cls = getattr(jsonschema, "Draft202012Validator", None)
        if validator_cls is None:
            validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema)
        for error in sorted(validator.iter_errors(pack_data), key=lambda e: list(e.path)):
            path = " → ".join(str(p) for p in error.absolute_path) or "(root)"
            errors.append(f"[{path}] {error.message}")
        return errors

    # Fallback: manual structural checks for required fields
    required = schema.get("required", [])
    for field_name in required:
        if field_name not in pack_data:
            errors.append(f"Missing required field: '{field_name}'")

    # Item-level required fields: without these checks a pack whose rules
    # lack the text fields the renderers depend on would pass the fallback
    # and produce empty compliance context lines at review time.
    _ITEM_REQUIRED = {
        "gpcm_rulepack/v1": ("requirements", ("shall_text",)),
        "oracle_generic/v1": ("rules", ("rule_id", "statement_text")),
    }
    item_spec = _ITEM_REQUIRED.get(schema_version)
    if item_spec:
        container_key, item_fields = item_spec
        for i, item in enumerate(pack_data.get(container_key, [])):
            if not isinstance(item, dict):
                errors.append(f"{container_key}[{i}] must be an object")
                continue
            for f in item_fields:
                if not item.get(f):
                    errors.append(f"{container_key}[{i}] missing required field: '{f}'")

    # Check oracle_metadata sub-fields
    if "oracle_metadata" in pack_data:
        meta = pack_data["oracle_metadata"]
        if not isinstance(meta, dict):
            errors.append("'oracle_metadata' must be an object")
        else:
            for req_field in ["name", "slug", "status", "added_at"]:
                if req_field not in meta:
                    errors.append(f"oracle_metadata missing required field: '{req_field}'")
            if meta.get("status") not in ("draft", "promoted", None):
                errors.append(
                    f"oracle_metadata.status must be 'draft' or 'promoted', "
                    f"got '{meta.get('status')}'"
                )

    # Check schema_version matches
    if pack_data.get("schema_version") != schema_version:
        errors.append(
            f"schema_version mismatch: pack has '{pack_data.get('schema_version')}', "
            f"expected '{schema_version}'"
        )

    return errors


def normalize_oracle_metadata(
    pack_data: dict[str, Any],
    slug: str | None = None,
) -> dict[str, Any]:
    """Ensure pack has a valid oracle_metadata block.

    If oracle_metadata is missing (e.g., externally-produced pack), populate
    defaults. If present, fill any missing optional fields.

    This is the normalization step that runs before validation in add-pack
    (Section 4.4 normalization-then-validation flow).

    Args:
        pack_data: The pack dict (modified in place AND returned).
        slug: Override slug. If None, derived from rule_pack_id.

    Returns:
        The same pack_data dict, with oracle_metadata populated.
    """
    from datetime import datetime, timezone
    import re

    if "oracle_metadata" not in pack_data:
        pack_data["oracle_metadata"] = {}

    meta = pack_data["oracle_metadata"]

    # Derive slug from rule_pack_id if not provided
    if not slug:
        raw = pack_data.get("rule_pack_id", pack_data.get("standard_id", "unnamed"))
        slug = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_") or "unnamed_pack"

    # Fill defaults for missing fields
    meta.setdefault("name", pack_data.get("standard_title", pack_data.get("standard_id", slug)))
    meta.setdefault("slug", slug)
    meta.setdefault("description", pack_data.get("standard_title", ""))
    meta.setdefault("status", "draft")
    meta.setdefault("added_at", datetime.now(timezone.utc).isoformat())
    meta.setdefault("promoted_at", None)
    meta.setdefault("promoted_by", None)
    meta.setdefault("promotion_notes", None)
    meta.setdefault("source_document_hash", None)
    meta.setdefault("detection_override", None)

    return pack_data


def normalize_pack_structure(pack_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy pack field types before schema validation.

    Older FAR-style pack builders sometimes emitted numeric rule ids and
    string page values like ``"4, 10"``. The current schemas require string
    ids and integer page values, so coerce these cases during registration.
    """
    schema_version = pack_data.get("schema_version")

    def _normalize_id_and_page(item: dict[str, Any]) -> None:
        if "id" in item and not isinstance(item["id"], str):
            item["id"] = str(item["id"])
        page = item.get("page")
        if page is None or isinstance(page, int):
            return
        if isinstance(page, str):
            match = re.search(r"\d+", page)
            if match:
                item["page"] = int(match.group(0))
            else:
                item.pop("page", None)
        else:
            item.pop("page", None)

    if schema_version == "gpcm_rulepack/v1":
        for requirement in pack_data.get("requirements", []):
            if isinstance(requirement, dict):
                _normalize_id_and_page(requirement)

    if schema_version == "far_rulepack/v1":
        for rules in pack_data.get("parts", {}).values():
            if not isinstance(rules, list):
                continue
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                _normalize_id_and_page(rule)

    if schema_version == "oracle_generic/v1":
        for rule in pack_data.get("rules", []):
            if isinstance(rule, dict) and "rule_id" in rule and not isinstance(rule["rule_id"], str):
                rule["rule_id"] = str(rule["rule_id"])

    return pack_data
