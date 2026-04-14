#!/usr/bin/env python3
"""
Module: SENTINEL-TOCR Standalone Server
Purpose: Minimal FastAPI server for TOCR — no MIRA backend dependencies.

BoundState AI 2026
Classification: BoundState Proprietary

Usage:
    python -m sentinel.tocr.server
    # Then open http://localhost:8099/tocr
"""

import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import List

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import ContractType, RevisionStatus
from sentinel.tocr.models.report import ComplianceReport
from sentinel.tocr.parsers.essca_parser import ESSCAParser

LOGGER = logging.getLogger(__name__)

app = FastAPI(title="SENTINEL-TOCR", version="1.0.0")

# CORS: restrict to known origins in production, allow all in development.
# Why: TOCR may be embedded in MIRA or OCA frontends on different domains
# during development, but production deployments should pin origins.
_cors_origins = os.environ.get("TOCR_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


_ALLOWED_EXTENSIONS = {".docx", ".pdf", ".json"}
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB — generous for DOCX task orders


def _default_config() -> ContractConfig:
    return ContractConfig(
        contract_type=[ContractType.IDIQ, ContractType.TASK_ORDER],
        agency="NASA",
        center="MSFC",
        vehicle="ESSCA",
        local_policy_pack="ESSCA-MSFC",
        revision_status=RevisionStatus.RELEASED,
    )


@contextmanager
def _temp_upload(upload: UploadFile):
    """Write upload to a temp file, yield the path, then clean up.

    Why contextmanager: NamedTemporaryFile(delete=False) previously leaked
    files on every request.  This ensures cleanup even on exceptions.
    """
    suffix = Path(upload.filename or "upload").suffix or ".docx"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        content = upload.file.read()
        tmp.write(content)
        tmp.flush()
        tmp.close()
        yield Path(tmp.name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _validate_upload(upload: UploadFile) -> None:
    """Validate file type and size at the API boundary.

    Why boundary validation: parsers assume well-formed input.  Rejecting
    bad files here produces clear 422 errors instead of opaque parser tracebacks.
    """
    filename = upload.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{ext}'. Accepted: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )
    # Check content length if provided by client
    if upload.size is not None and upload.size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )


def _parse_upload(upload: UploadFile):
    """Parse an uploaded task order document.

    Returns a TaskOrder model on success; raises HTTPException on failure.
    """
    _validate_upload(upload)
    parser = ESSCAParser()
    with _temp_upload(upload) as tmp_path:
        try:
            return parser.parse(tmp_path)
        except Exception as exc:
            LOGGER.error("Failed to parse upload %s: %s", upload.filename, exc)
            raise HTTPException(
                status_code=422,
                detail=f"Could not parse '{upload.filename}': {type(exc).__name__}",
            ) from exc


def _report_to_dict(report: ComplianceReport) -> dict:
    """Serialize a ComplianceReport to a JSON-safe dict.

    Why manual serialization: ComplianceReport contains enums and nested
    models that need value extraction.  model_dump() would work but this
    gives us control over field truncation (evidence text capped at 500 chars)
    and stable API shape independent of model changes.
    """
    findings = []
    for f in report.findings:
        finding = {
            "finding_id": f.finding_id,
            "rule_id": f.rule_id,
            "rule_title": f.rule_title,
            "severity": f.severity.value,
            "review_priority": f.review_priority.value,
            "finding_text": f.finding_text,
            "guidance": f.guidance,
            "remediation": f.remediation,
        }
        if f.evidence:
            finding["evidence"] = {
                "field_path": f.evidence.field_path,
                "prior_text": f.evidence.prior_text[:500] if f.evidence.prior_text else "",
                "proposed_text": f.evidence.proposed_text[:500] if f.evidence.proposed_text else "",
                "change_type": f.evidence.change_type.value,
                "classification": f.evidence.classification.value,
            }
        findings.append(finding)

    remediation_plan = None
    if report.remediation_plan:
        steps = []
        for s in report.remediation_plan.steps:
            steps.append({
                "priority_order": s.priority_order,
                "finding_id": s.finding_id,
                "rule_id": s.rule_id,
                "rule_title": s.rule_title,
                "severity": s.severity.value,
                "field_path": s.field_path,
                "what_to_fix": s.what_to_fix,
                "how_to_fix": s.how_to_fix,
                "why_it_matters": s.why_it_matters,
                "owner": s.owner,
                "authority_basis": s.authority_basis,
            })
        remediation_plan = {
            "steps": steps,
            "total_steps": report.remediation_plan.total_steps,
            "critical_steps": report.remediation_plan.critical_steps,
            "high_steps": report.remediation_plan.high_steps,
            "medium_steps": report.remediation_plan.medium_steps,
            "low_steps": report.remediation_plan.low_steps,
            "estimated_owners": report.remediation_plan.estimated_owners,
        }

    score = report.score
    return {
        "report_id": report.report_id,
        "prior_revision": report.prior_revision or "",
        "proposed_revision": report.proposed_revision or "",
        "verdict": score.verdict.value if score else "UNKNOWN",
        "raw_score": score.raw_score if score else 0,
        "critical_count": score.critical_count if score else 0,
        "high_count": score.high_count if score else 0,
        "medium_count": score.medium_count if score else 0,
        "low_count": score.low_count if score else 0,
        "total_changes": report.total_changes_detected,
        "material_changes": report.material_changes_detected,
        "disclosed_changes": report.disclosed_changes,
        "undisclosed_changes": report.undisclosed_changes,
        "findings": findings,
        "remediation_plan": remediation_plan,
        "suppression_log": [
            {"rule_id": s["rule_id"], "reason": s["reason"]}
            for s in report.suppression_log
        ],
        "input_fingerprint": report.input_fingerprint or "",
        "assumptions": report.assumptions,
        "rules_evaluated": report.rules_evaluated,
        "rules_fired": report.rules_fired,
        "rules_suppressed": report.rules_suppressed,
    }


@app.post("/api/tocr/review")
async def review(
    files: List[UploadFile] = File(...),
    use_sonnet: str = Form("false"),
):
    """Compare two or more task order revisions and produce compliance findings."""
    if len(files) < 2:
        raise HTTPException(status_code=422, detail="Review requires at least 2 files")

    revisions = [_parse_upload(f) for f in files]
    conductor = TOCRConductor(config=_default_config())

    reports = []
    for i in range(len(revisions) - 1):
        if use_sonnet.lower() in ("true", "1"):
            report = await conductor.review_with_sonnet(revisions[i], revisions[i + 1])
        else:
            report = conductor.review(revisions[i], revisions[i + 1])
        reports.append(_report_to_dict(report))

    return reports if len(reports) > 1 else reports[0]


@app.post("/api/tocr/scan")
async def scan(
    files: List[UploadFile] = File(...),
    use_sonnet: str = Form("false"),
):
    """Scan a single task order for compliance issues without a prior revision."""
    if len(files) < 1:
        raise HTTPException(status_code=422, detail="Scan requires at least 1 file")

    to = _parse_upload(files[0])
    conductor = TOCRConductor(config=_default_config())

    if use_sonnet.lower() in ("true", "1"):
        report = await conductor.scan_with_sonnet(to)
    else:
        report = conductor.scan(to)

    return _report_to_dict(report)


# --- Serve the frontend from built dist or inline fallback ---

_DIST_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"

if _DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve index.html for all non-API routes (SPA routing).

        Why path validation: FastAPI/Starlette normalizes path components,
        but we resolve against _DIST_DIR and verify the result stays within
        the dist directory to prevent directory traversal.
        """
        file_path = (_DIST_DIR / full_path).resolve()
        if file_path.is_relative_to(_DIST_DIR) and file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_DIST_DIR / "index.html"))
else:
    @app.get("/")
    async def root():
        return HTMLResponse(
            "<h2>SENTINEL-TOCR</h2>"
            "<p>Frontend not built. Run <code>cd frontend && npm run build</code> first, "
            "or go to <a href='/docs'>/docs</a> to use the API directly.</p>"
        )


if __name__ == "__main__":
    LOGGER.info("SENTINEL-TOCR Server starting on http://localhost:8099/tocr")
    uvicorn.run(app, host="0.0.0.0", port=8099)
