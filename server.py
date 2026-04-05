"""
Module: server
Purpose: FastAPI web server for ORACLE — serves the frontend API contract.

Endpoints:
  POST /oracle/analyze    — Upload a document, start review in background, return session_id
  GET  /oracle/stream/:id — SSE stream of live oracle2 log messages + final result
  POST /oracle/generate   — Generate polished output from a reviewed session
  GET  /oracle/download   — Download generated .docx/.pptx

__safety_critical__: bool = True

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

__safety_critical__: bool = True

import asyncio
import json
import logging
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
        return
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Session Store (in-memory for beta)
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Log Capture — intercepts oracle2 logger output per-session
# ---------------------------------------------------------------------------


class SessionLogHandler(logging.Handler):
    """Logging handler that routes oracle2 log records into a per-session queue."""

    def __init__(self, msg_queue: queue.Queue[str | None]) -> None:
        super().__init__()
        self._queue = msg_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._queue.put(msg)
        except Exception:
            pass


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
# Background Review Runner
# ---------------------------------------------------------------------------


def _run_review_background(
    session_id: str,
    draft_text: str,
    file_path: Path,
    mode: str,
    output_dir: Path,
    msg_queue: queue.Queue[str | None],
) -> None:
    """Run oracle2 review in a background thread, pushing log messages to queue."""

    # Attach log handler to capture oracle2 + httpx output
    handler = SessionLogHandler(msg_queue)
    handler.setFormatter(logging.Formatter("%(message)s"))

    oracle2_logger = logging.getLogger("oracle2")
    httpx_logger = logging.getLogger("httpx")
    oracle2_logger.addHandler(handler)
    httpx_logger.addHandler(handler)

    try:
        msg_queue.put("Extracting document content...")

        msg_queue.put(f"Document loaded — {len(draft_text):,} characters extracted")
        msg_queue.put(f"Mode: {mode} — starting Oracle review...")

        run_review(
            draft=draft_text,
            document_path=str(file_path),
            max_rounds=1 if mode == "polish" else 3,
            output_dir=output_dir,
        )

        msg_queue.put("Review complete — parsing results...")

        result = build_review_result(output_dir)

        # Build critique markdown
        critique_lines: list[str] = []
        for rd in result.rounds:
            for issue in rd.normalized_issues:
                severity_badge = f"**[{issue.severity.upper()}]**"
                critique_lines.append(
                    f"- {severity_badge} **{issue.title}**: {issue.core_problem}"
                )
                if issue.recommended_fix:
                    critique_lines.append(f"  - *Fix:* {issue.recommended_fix}")
        critique_md = "\n".join(critique_lines) if critique_lines else "No issues found."

        # Store session
        _sessions[session_id] = {
            "session_id": session_id,
            "mode": mode,
            "original_name": file_path.name,
            "file_path": str(file_path),
            "draft_text": draft_text,
            "review_result": result,
            "output_dir": str(output_dir),
            "critique": critique_md,
            "status": "complete" if mode in ("polish", "rewrite") else "ready_to_generate",
            "error": None,
        }

        msg_queue.put("All oracles have reported — finalizing...")

    except Exception as e:
        LOGGER.exception("oracle2 review failed")
        _sessions[session_id] = {
            "session_id": session_id,
            "mode": mode,
            "original_name": file_path.name,
            "status": "error",
            "error": str(e),
        }
        msg_queue.put(f"ERROR: {e}")

    finally:
        oracle2_logger.removeHandler(handler)
        httpx_logger.removeHandler(handler)
        msg_queue.put(None)  # Sentinel: stream is done


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/oracle/analyze")
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("review"),
):
    """Upload a document and start review in background.

    Returns session_id immediately. Client should connect to
    GET /oracle/stream/{session_id} for live progress.
    """
    await verify_api_key(request)

    if mode not in ("polish", "review", "rewrite"):
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

    session_id = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "document"
    file_path = session_dir / original_name
    content = await file.read()
    file_path.write_bytes(content)

    # Extract text before spawning thread (fast, validates file)
    try:
        draft_text = extract_text(file_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not draft_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from document")

    # Create message queue and start background thread
    msg_queue: queue.Queue[str | None] = queue.Queue()
    output_dir = session_dir / "oracle_output"

    # Store queue for the stream endpoint to read
    _sessions[session_id] = {
        "session_id": session_id,
        "mode": mode,
        "status": "processing",
        "msg_queue": msg_queue,
        "error": None,
    }

    thread = threading.Thread(
        target=_run_review_background,
        args=(session_id, draft_text, file_path, mode, output_dir, msg_queue),
        daemon=True,
    )
    thread.start()

    return {"session_id": session_id, "status": "processing"}


@app.get("/oracle/stream/{session_id}")
async def stream(request: Request, session_id: str):
    """SSE stream of live oracle2 progress messages.

    Events:
      event: log     — data: "human-readable log line"
      event: done    — data: JSON result (same shape as old /analyze response)
      event: error   — data: error message
    """
    await verify_api_key(request)

    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    msg_queue: queue.Queue[str | None] | None = session.get("msg_queue")

    async def event_generator():
        # If already finished before client connected, send result immediately
        if session.get("status") in ("complete", "ready_to_generate"):
            yield _format_done_event(session)
            return

        if session.get("status") == "error":
            yield f"event: error\ndata: {session.get('error', 'Unknown error')}\n\n"
            return

        if msg_queue is None:
            yield f"event: error\ndata: No message queue for session\n\n"
            return

        # Stream log messages as they arrive
        while True:
            try:
                msg = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: msg_queue.get(timeout=1.0)
                )
            except queue.Empty:
                # Send keepalive comment to prevent timeout
                yield ": keepalive\n\n"
                continue

            if msg is None:
                # Sentinel — review is done, send final result
                # Re-fetch session (background thread updated it)
                final = _sessions.get(session_id, {})
                if final.get("status") == "error":
                    yield f"event: error\ndata: {final.get('error', 'Unknown error')}\n\n"
                else:
                    yield _format_done_event(final)
                return

            # Clean up log line for display
            clean = _clean_log_message(msg)
            if clean:
                yield f"event: log\ndata: {clean}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_done_event(session: dict[str, Any]) -> str:
    """Format the final SSE 'done' event with the result payload."""
    session_id = session["session_id"]
    mode = session.get("mode", "review")
    status = session.get("status", "complete")
    critique = session.get("critique")

    result = {
        "session_id": session_id,
        "mode": mode,
        "status": status,
        "critique": critique if mode == "review" else None,
        "docx_url": f"/oracle/download/{session_id}/docx" if status in ("complete", "ready_to_generate") else None,
        "pptx_url": f"/oracle/download/{session_id}/pptx" if status in ("complete", "ready_to_generate") else None,
    }
    return f"event: done\ndata: {json.dumps(result)}\n\n"


def _clean_log_message(msg: str) -> str | None:
    """Clean and filter oracle2 log messages for frontend display."""
    if not msg or not msg.strip():
        return None

    # Skip noisy httpx lines but keep the useful part
    if "HTTP Request: POST" in msg:
        if "200 OK" in msg:
            # Extract which API was called
            if "openai.com" in msg:
                return "OpenAI responded"
            elif "x.ai" in msg or "xai" in msg.lower():
                return "xAI responded"
            elif "anthropic.com" in msg:
                return "Anthropic responded"
            return None
        return None

    # Skip internal framework noise
    skip_prefixes = ("INFO:httpx:", "DEBUG:", "INFO:httpcore")
    for prefix in skip_prefixes:
        if msg.startswith(prefix):
            return None

    # Strip logger prefixes for clean display
    clean = msg
    for prefix in ("INFO:oracle2:", "WARNING:oracle2:", "ERROR:oracle2:"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            break

    clean = clean.strip()

    # Skip empty separators
    if clean and all(c in "=- \n" for c in clean):
        return None

    return clean if clean else None


# ---------------------------------------------------------------------------
# Generate + Download (unchanged)
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    """Request body for the generate endpoint."""

    session_id: str
    approved: bool


@app.post("/oracle/generate")
async def generate(request: Request, body: GenerateRequest):
    """Generate polished output documents from a reviewed session."""
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
    """Download a generated document."""
    await verify_api_key(request)

    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    review_result = session.get("review_result")
    if not review_result:
        raise HTTPException(status_code=400, detail="Review not complete")

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
