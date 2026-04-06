#!/usr/bin/env python3
"""
SENTINEL-TOCR Standalone Server
Minimal FastAPI server for TOCR — no MIRA backend dependencies.

Usage:
    python -m sentinel.tocr.server
    # Then open http://localhost:8099/tocr
"""

import tempfile
from pathlib import Path
from typing import List

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from sentinel.tocr.engine.conductor import TOCRConductor
from sentinel.tocr.models.config import ContractConfig
from sentinel.tocr.models.enums import ContractType, RevisionStatus
from sentinel.tocr.parsers.essca_parser import ESSCAParser

app = FastAPI(title="SENTINEL-TOCR", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _default_config() -> ContractConfig:
    return ContractConfig(
        contract_type=[ContractType.IDIQ, ContractType.TASK_ORDER],
        agency="NASA",
        center="MSFC",
        vehicle="ESSCA",
        local_policy_pack="ESSCA-MSFC",
        revision_status=RevisionStatus.RELEASED,
    )


def _parse_upload(upload: UploadFile):
    parser = ESSCAParser()
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        content = upload.file.read()
        tmp.write(content)
        tmp.flush()
        return parser.parse(Path(tmp.name))


def _report_to_dict(report) -> dict:
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
    if len(files) < 2:
        return {"error": "Review requires at least 2 files"}

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
    if len(files) < 1:
        return {"error": "Scan requires at least 1 file"}

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
        # Serve index.html for all non-API routes (SPA routing)
        file_path = _DIST_DIR / full_path
        if file_path.exists() and file_path.is_file():
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
    print("\n  SENTINEL-TOCR Server")
    print("  http://localhost:8099/tocr\n")
    uvicorn.run(app, host="0.0.0.0", port=8099)
