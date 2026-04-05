"""
Module: server
Purpose: FastAPI web server for ORACLE — serves the frontend API contract.

Endpoints:
  POST /oracle/analyze  — Upload a document, run oracle2 review
  POST /oracle/generate — Generate polished output documents from a reviewed session

__safety_critical__: bool = True

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

__safety_critical__: bool = True

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from oracle.oracle2 import run_review
from oracle.oracle2_adapter import build_review_result

LOGGER = logging.getLogger("oracle.server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="ORACLE API",
    version="1.0.0",
    description="Orchestrated Review And Compliance Liaison Engine",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.environ.get("FRONTEND_URL", "http://localhost:3000"),
    ],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API Key Auth
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("ORACLE_API_KEY", "")


async def verify_api_key(request: Request) -> None:
    """Verify X-API-Key header matches the configured key."""
    if not API_KEY:
        return  # No key configured = open (dev mode)
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Session Store (in-memory for beta)
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Document Extraction
# ---------------------------------------------------------------------------

SESSIONS_DIR = Path(os.environ.get("ORACLE_SESSIONS_DIR", "oracle_sessions"))
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def extract_text(file_path: Path) -> str:
    """Extract text content from .docx or .pptx files."""
    suffix = file_path.suffix.lower()

    if suffix == ".docx":
        try:
            from docx import Document

            doc = Document(str(file_path))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            LOGGER.warning("python-docx not installed, reading as raw text")
            return file_path.read_text(encoding="utf-8", errors="replace")

    elif suffix == ".pptx":
        try:
            from pptx import Presentation

            prs = Presentation(str(file_path))
            texts: list[str] = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        texts.append(shape.text_frame.text)
            return "\n\n".join(t for t in texts if t.strip())
        except ImportError:
            LOGGER.warning("python-pptx not installed, reading as raw text")
            return file_path.read_text(encoding="utf-8", errors="replace")

    else:
        raise ValueError(f"Unsupported file type: {suffix}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/oracle/analyze")
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("review"),
):
    """Upload a document, extract text, and run oracle2 review.

    Args:
        file: .docx or .pptx upload
        mode: 'polish' | 'review' | 'rewrite'

    Returns:
        JSON with session_id, mode, critique (if review), status, and download URLs.
    """
    await verify_api_key(request)

    if mode not in ("polish", "review", "rewrite"):
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

    # Save uploaded file
    session_id = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "document"
    file_path = session_dir / original_name
    content = await file.read()
    file_path.write_bytes(content)

    # Extract text
    try:
        draft_text = extract_text(file_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not draft_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from document")

    # Run oracle2 review
    output_dir = session_dir / "oracle_output"
    try:
        oracle_session = run_review(
            draft=draft_text,
            document_path=str(file_path),
            max_rounds=1 if mode == "polish" else 3,
            output_dir=output_dir,
        )
    except Exception:
        LOGGER.exception("oracle2 review failed")
        raise HTTPException(status_code=500, detail="Oracle review failed")

    # Parse results via adapter
    try:
        result = build_review_result(output_dir)
    except ValueError:
        LOGGER.exception("oracle2 adapter failed")
        raise HTTPException(status_code=500, detail="Oracle result parsing failed")

    # Store session
    _sessions[session_id] = {
        "session_id": session_id,
        "mode": mode,
        "original_name": original_name,
        "file_path": str(file_path),
        "draft_text": draft_text,
        "review_result": result,
        "output_dir": str(output_dir),
    }

    # Build critique markdown from normalized issues
    critique_lines: list[str] = []
    for rd in result.rounds:
        for issue in rd.normalized_issues:
            severity_badge = f"**[{issue.severity.upper()}]**"
            critique_lines.append(f"- {severity_badge} **{issue.title}**: {issue.core_problem}")
            if issue.recommended_fix:
                critique_lines.append(f"  - *Fix:* {issue.recommended_fix}")
    critique_md = "\n".join(critique_lines) if critique_lines else "No issues found."

    # For polish/rewrite, status is immediately complete
    if mode in ("polish", "rewrite"):
        return {
            "session_id": session_id,
            "mode": mode,
            "critique": None,
            "status": "complete",
            "docx_url": f"/oracle/download/{session_id}/docx",
            "pptx_url": f"/oracle/download/{session_id}/pptx",
        }

    # For review mode, return critique and wait for approval
    return {
        "session_id": session_id,
        "mode": mode,
        "critique": critique_md,
        "status": "ready_to_generate",
        "docx_url": None,
        "pptx_url": None,
    }


class GenerateRequest(BaseModel):
    """Request body for the generate endpoint."""

    session_id: str
    approved: bool


@app.post("/oracle/generate")
async def generate(request: Request, body: GenerateRequest):
    """Generate polished output documents from a reviewed session.

    Args:
        body: JSON with session_id and approved flag.

    Returns:
        JSON with download URLs for .docx and .pptx.
    """
    await verify_api_key(request)

    session = _sessions.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not body.approved:
        raise HTTPException(status_code=400, detail="Review not approved")

    return {
        "docx_url": f"/oracle/download/{body.session_id}/docx",
        "pptx_url": f"/oracle/download/{body.session_id}/pptx",
    }


@app.get("/oracle/download/{session_id}/{fmt}")
async def download(request: Request, session_id: str, fmt: str):
    """Download a generated document.

    Args:
        session_id: The session identifier.
        fmt: 'docx' or 'pptx'.
    """
    await verify_api_key(request)

    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    review_result = session["review_result"]
    original_name = session["original_name"]
    base_name = Path(original_name).stem

    if fmt == "docx":
        try:
            from docx import Document

            doc = Document()
            doc.add_heading(f"{base_name} — Polished", level=1)
            for paragraph in review_result.final_draft.split("\n\n"):
                if paragraph.strip():
                    doc.add_paragraph(paragraph.strip())

            out_path = Path(session["output_dir"]) / f"{base_name}_polished.docx"
            doc.save(str(out_path))

            from fastapi.responses import FileResponse

            return FileResponse(
                str(out_path),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                filename=f"{base_name}_polished.docx",
            )
        except ImportError:
            raise HTTPException(status_code=500, detail="python-docx not installed")

    elif fmt == "pptx":
        try:
            from pptx import Presentation
            from pptx.util import Inches

            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = f"{base_name} — Polished"

            body = slide.placeholders[1]
            body.text = review_result.final_draft[:3000]

            out_path = Path(session["output_dir"]) / f"{base_name}_polished.pptx"
            prs.save(str(out_path))

            from fastapi.responses import FileResponse

            return FileResponse(
                str(out_path),
                media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                filename=f"{base_name}_polished.pptx",
            )
        except ImportError:
            raise HTTPException(status_code=500, detail="python-pptx not installed")

    else:
        raise HTTPException(status_code=400, detail=f"Invalid format: {fmt}")


@app.get("/health")
async def health():
    """Health check endpoint for Railway."""
    return {"status": "ok", "service": "oracle"}
