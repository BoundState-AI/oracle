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
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from oracle.cli import (
    _load_manifest,
    _render_pack_for_oracle,
    _resolve_pack_dir,
    format_findings_report,
    generate_pack as cli_generate_pack,
    load_pack as cli_load_pack,
    promote_pack as cli_promote_pack,
    register_pack as cli_register_pack,
    remove_pack as cli_remove_pack,
    run_review as cli_run_review,
)
from oracle.chat_engine import answer_query as oracle_answer_query
from oracle.envutil import read_env_int
from oracle.oracle2 import compute_metrics
from oracle.oracle2_adapter import build_review_result
from oracle.redact import redact_secrets

from hearth import __version__ as HEARTH_VERSION
from hearth.audit.artifact import AuditWriteError, build_artifact, write_artifact
from hearth.core.scrubber.engine import refusal_run, scrub_document
from hearth.core.scrubber.extraction import MAX_DOCUMENT_BYTES, SUPPORTED_SUFFIXES
from hearth.packs.loader import BUILTIN_JURISDICTION_DIR, PackError, load_pack
from hearth.utils.render import LEGAL_BANNER, render_report

LOGGER = logging.getLogger("oracle.server")
logging.basicConfig(level=logging.INFO)


def _normalize_api_keys() -> None:
    """Strip surrounding whitespace from provider key env vars at boot.

    WHY: a trailing newline/space is a common artifact when a key is pasted
    into a deployment dashboard (e.g. Railway). The value is sent to the
    provider verbatim in the `x-api-key` header and comes back as an opaque
    `401 invalid x-api-key`, while every non-Anthropic oracle still succeeds —
    exactly the production failure mode for Beth. Normalizing once here fixes
    every downstream reader without touching the oracle2 black box.
    """
    for var in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY",
        "GOOGLE_API_KEY", "GEMINI_API_KEY", "ORACLE_API_KEY",
    ):
        raw = os.environ.get(var)
        if raw is not None and raw != raw.strip():
            os.environ[var] = raw.strip()
            LOGGER.warning("Stripped surrounding whitespace from %s", var)


# Run before any module-level env reads below (e.g. ORACLE_API_KEY for auth).
_normalize_api_keys()

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
    allow_methods=["POST", "GET", "DELETE"],
    # Why scoped headers: allow_headers=["*"] previously accepted any header.
    # We only need Content-Type (for JSON/form bodies) and X-API-Key (auth).
    allow_headers=["Content-Type", "X-API-Key"],
)

# ---------------------------------------------------------------------------
# API Key Auth — enforced via Depends() on the oracle router
# ---------------------------------------------------------------------------
# Why Depends() instead of manual calls: previously every endpoint called
# verify_api_key() manually.  If a new endpoint forgot the call, it was
# silently unauthenticated.  Router-level dependencies make auth the default.

API_KEY = os.environ.get("ORACLE_API_KEY", "")


async def verify_api_key(request: Request) -> None:
    """Verify X-API-Key header matches the configured key.

    Registered as a router-level dependency so ALL /oracle/* endpoints
    are protected by default.  No manual calls needed in endpoint bodies.
    """
    if not API_KEY:
        return
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# All /oracle/* endpoints go through this router, which enforces auth.
oracle_router = APIRouter(prefix="/oracle", dependencies=[Depends(verify_api_key)])

# ---------------------------------------------------------------------------
# Session Store (in-memory for beta, with eviction)
# ---------------------------------------------------------------------------
# Why TTL eviction: without it, _sessions grows unboundedly under sustained
# use.  Completed/errored sessions older than 2 hours are evicted on each
# new session creation.  In-progress sessions are never evicted.

import time as _time  # noqa: E402 — grouped with session store for locality

_SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 hours
_MAX_SESSIONS = 200

# WHY resolved once at module load: the deployment value cannot change
# mid-process, and re-parsing per chat request re-logged the same
# malformed-value warning on every single request forever.
_CHAT_MAX_SESSIONS = read_env_int("ORACLE_CHAT_MAX_SESSIONS", 500)

_sessions: dict[str, dict[str, Any]] = {}
_chat_sessions: dict[str, dict[str, Any]] = {}


def _evict_stale_sessions() -> None:
    """Remove completed/errored sessions older than TTL, keeping at most _MAX_SESSIONS."""
    now = _time.time()
    stale = [
        sid for sid, s in _sessions.items()
        if s.get("status") in ("completed", "error")
        and (now - s.get("created_at", now)) > _SESSION_TTL_SECONDS
    ]
    for sid in stale:
        _sessions.pop(sid, None)
    # Hard cap: if still over limit, drop oldest completed sessions
    if len(_sessions) > _MAX_SESSIONS:
        completed = sorted(
            [(sid, s) for sid, s in _sessions.items() if s.get("status") in ("completed", "error")],
            key=lambda x: x[1].get("created_at", 0),
        )
        for sid, _ in completed[:len(_sessions) - _MAX_SESSIONS]:
            _sessions.pop(sid, None)

# ---------------------------------------------------------------------------
# Log Capture — intercepts oracle2 logger output per-session
# ---------------------------------------------------------------------------


class SessionLogHandler(logging.Handler):
    """Logging handler that routes oracle2 log records into a per-session queue."""

    def __init__(
        self,
        msg_queue: queue.Queue[str | None],
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._queue = msg_queue
        self._on_log = on_log

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._queue.put(msg)
            if self._on_log:
                self._on_log(msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Document Extraction
# ---------------------------------------------------------------------------

SESSIONS_DIR = Path(os.environ.get("ORACLE_SESSIONS_DIR", "oracle_sessions"))
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
SESSION_STATE_FILE = "session_state.json"
MAX_LOG_MESSAGES = 200

# Hard ceiling for UI-driven reviews. Each round fans out to ~4 reviewer LLMs
# over the full document, so cost scales roughly linearly. The CLI can still
# exceed this; the cap applies only to requests that come through the HTTP API.
UI_MAX_ROUNDS_CEILING = 4


def _max_rounds_for_mode(mode: str) -> int:
    """Return the configured review budget for a given UI mode."""
    defaults = {
        "polish": 1,
        "review": 1,
        "rewrite": 1,
    }
    env_name = f"ORACLE_MAX_ROUNDS_{mode.upper()}"
    raw = os.environ.get(env_name)
    if not raw:
        return defaults[mode]
    try:
        parsed = int(raw)
    except ValueError:
        LOGGER.warning("Invalid %s=%r, falling back to %d", env_name, raw, defaults[mode])
        return defaults[mode]
    return max(1, min(UI_MAX_ROUNDS_CEILING, parsed))


def _clamp_user_rounds(requested: int | None, mode: str) -> int:
    """Clamp a user-supplied max_rounds value to the UI ceiling.

    Falls back to the mode default when not supplied. Values below 1 are
    coerced to 1; values above UI_MAX_ROUNDS_CEILING are coerced to the
    ceiling. The backend is the source of truth — the frontend cap is
    purely a UX hint.
    """
    if requested is None:
        return _max_rounds_for_mode(mode)
    if requested < 1:
        return 1
    if requested > UI_MAX_ROUNDS_CEILING:
        return UI_MAX_ROUNDS_CEILING
    return requested


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


def _session_dir(session_id: str) -> Path:
    return SESSIONS_DIR / session_id


def _session_state_path(session_id: str) -> Path:
    return _session_dir(session_id) / SESSION_STATE_FILE


def _session_manifest(session: dict[str, Any]) -> dict[str, Any]:
    """Return the JSON-serializable subset of a session."""
    return {
        "session_id": session["session_id"],
        "job_type": session.get("job_type", "review"),
        "mode": session.get("mode", "review"),
        "status": session.get("status", "processing"),
        "error": session.get("error"),
        "critique": session.get("critique"),
        "findings_report": session.get("findings_report"),
        "metrics": session.get("metrics"),
        "original_name": session.get("original_name"),
        "file_path": session.get("file_path"),
        "output_dir": session.get("output_dir"),
        "log_messages": session.get("log_messages", []),
        "pack_names": session.get("pack_names", []),
        "pack_parts": session.get("pack_parts", {}),
        "generated_pack": session.get("generated_pack"),
        "pack_manifest_snapshot": session.get("pack_manifest_snapshot"),
    }


def _persist_session_state(session: dict[str, Any]) -> None:
    """Persist session metadata so a restarted process can recover state."""
    session_id = session["session_id"]
    state_path = _session_state_path(session_id)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(_session_manifest(session), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_session_from_disk(session_id: str) -> dict[str, Any] | None:
    """Recover session metadata from disk when in-memory state was lost."""
    state_path = _session_state_path(session_id)
    if not state_path.exists():
        return None

    try:
        session = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("Failed to decode persisted state for session %s", session_id)
        return None

    session["session_id"] = session_id

    if session.get("status") == "processing":
        session["status"] = "error"
        session["error"] = (
            "Oracle session was interrupted by a server restart or redeploy. "
            "Please start the review again."
        )
        _persist_session_state(session)
        return session

    output_dir = session.get("output_dir")
    if output_dir and session.get("status") in ("complete", "ready_to_generate"):
        if session.get("job_type", "review") == "review":
            try:
                session["review_result"] = build_review_result(Path(output_dir))
            except Exception:
                LOGGER.exception("Failed to rebuild review result for session %s", session_id)

    return session


def _get_session(session_id: str) -> dict[str, Any] | None:
    """Return a live or recovered session."""
    session = _sessions.get(session_id)
    if session:
        return session

    recovered = _load_session_from_disk(session_id)
    if recovered:
        _sessions[session_id] = recovered
        return recovered

    return None


def _pack_dir() -> Path:
    return _resolve_pack_dir()


def _pack_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": entry.get("name") or entry.get("slug"),
        "slug": entry.get("slug"),
        "schema": entry.get("schema"),
        "status": entry.get("status"),
        "standard_id": entry.get("standard_id"),
        "description": entry.get("description"),
        "rule_count": entry.get("rule_count"),
        "version": entry.get("version"),
        "extraction_status": entry.get("extraction_status"),
        "failed_page_ranges": entry.get("failed_page_ranges", []),
        "added_at": entry.get("added_at"),
        "promoted_at": entry.get("promoted_at"),
        "promoted_by": entry.get("promoted_by"),
        "content_hash": entry.get("content_hash"),
        "source_document": entry.get("source_document"),
        "source_document_hash": entry.get("source_document_hash"),
    }


def _pack_detail(pack_name: str, verbose: bool = False) -> dict[str, Any]:
    pack_dir = _pack_dir()
    pack_data, resolved = cli_load_pack(pack_name, pack_dir)
    manifest = _load_manifest(pack_dir)
    entry = manifest["packs"].get(resolved, {})
    meta = pack_data.get("oracle_metadata", {})

    detail = {
        **_pack_summary(entry),
        "slug": resolved,
        "schema_version": pack_data.get("schema_version"),
        "standard_title": pack_data.get("standard_title"),
        "oracle_metadata": meta,
        "chunk_failures": pack_data.get("chunk_failures", []),
        "rule_pack_id": pack_data.get("rule_pack_id", resolved),
        "raw": pack_data if verbose else None,
        "rendered": (
            _render_pack_for_oracle(
                pack_data,
                pack_data.get("rule_pack_id", resolved),
            )
            if verbose
            else None
        ),
    }
    return detail


def _pack_snapshot(output_dir: Path) -> dict[str, Any] | None:
    snapshot_path = output_dir / "pack_manifest_snapshot.json"
    if not snapshot_path.exists():
        return None
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("Failed to decode pack manifest snapshot at %s", snapshot_path)
        return None


def _append_session_log(session_id: str, raw_message: str) -> None:
    """Persist a rolling tail of clean log messages for polling fallbacks.

    Redacted at this choke point because persisted session logs include
    raw exception text from provider SDKs/httpx, which can echo
    credentials (AUDIT C5).
    """
    clean = _clean_log_message(raw_message)
    if not clean:
        return
    clean = redact_secrets(clean)

    session = _sessions.get(session_id)
    if not session:
        return

    logs = list(session.get("log_messages", []))
    logs.append(clean)
    session["log_messages"] = logs[-MAX_LOG_MESSAGES:]
    _persist_session_state(session)


def _parse_json_string(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc


# ---------------------------------------------------------------------------
# Background Review Runner
# ---------------------------------------------------------------------------


def _run_review_background(
    session_id: str,
    file_path: Path,
    mode: str,
    output_dir: Path,
    msg_queue: queue.Queue[str | None],
    pack_names: list[str],
    pack_parts: dict[str, list[int]] | None,
    max_rounds: int,
) -> None:
    """Run CLI-backed oracle review in a background thread."""

    handler = SessionLogHandler(
        msg_queue,
        on_log=lambda msg: _append_session_log(session_id, msg),
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    oracle_logger = logging.getLogger("oracle")
    oracle2_logger = logging.getLogger("oracle2")
    httpx_logger = logging.getLogger("httpx")
    oracle_logger.addHandler(handler)
    oracle2_logger.addHandler(handler)
    httpx_logger.addHandler(handler)

    try:
        msg_queue.put(f"Mode: {mode} — starting Oracle review...")
        if pack_names:
            msg_queue.put(f"Authority packs: {', '.join(pack_names)}")
        msg_queue.put(f"Review budget: {max_rounds} round(s)")

        review_session = cli_run_review(
            document_path=file_path,
            pack_names=pack_names,
            pack_dir=_pack_dir(),
            pack_parts=pack_parts,
            max_rounds=max_rounds,
            output_dir=output_dir,
            force_text_only=False,
        )

        msg_queue.put("Review complete — parsing results...")

        # Write the findings report + metrics FIRST — these only need the
        # in-memory review_session and succeed for every terminal outcome.
        findings_report = format_findings_report(
            review_session,
            _pack_dir(),
            pack_names=pack_names,
            output_path=output_dir / "findings_report.md",
        )
        metrics = compute_metrics(review_session)
        (output_dir / "metrics.json").write_text(
            json.dumps(metrics, indent=2),
            encoding="utf-8",
        )

        # A "stop for human review" outcome legitimately omits a LOCKed
        # final_draft.md, so build_review_result()'s preflight raises ValueError.
        # That must NOT bury a completed review in status="error" (which nulls
        # every download URL and strands the user at the console). The review
        # ran; serve the findings report regardless of how rich the parse is.
        try:
            review_result = build_review_result(output_dir)
        except BaseException:
            LOGGER.exception(
                "rich review_result unavailable (e.g. human-review stop without a "
                "LOCKed final_draft); serving findings report only"
            )
            review_result = None

        _sessions[session_id] = {
            "session_id": session_id,
            "job_type": "review",
            "mode": mode,
            "original_name": file_path.name,
            "file_path": str(file_path),
            "review_result": review_result,
            "output_dir": str(output_dir),
            "log_messages": _sessions.get(session_id, {}).get("log_messages", []),
            "pack_names": pack_names,
            "pack_parts": pack_parts or {},
            "critique": findings_report,
            "findings_report": findings_report,
            "metrics": metrics,
            "pack_manifest_snapshot": _pack_snapshot(output_dir),
            "status": "complete" if mode in ("polish", "rewrite") else "ready_to_generate",
            "error": None,
        }
        _persist_session_state(_sessions[session_id])

        msg_queue.put("All oracles have reported — finalizing...")

    # WHY Exception, not BaseException: catching BaseException converted
    # KeyboardInterrupt/SystemExit during shutdown into a fake "review
    # error" session state (AUDIT F6). Those now propagate; the finally
    # block still detaches handlers and closes the stream.
    except Exception as e:
        LOGGER.exception("oracle review failed")
        error_text = redact_secrets(str(e))
        _sessions[session_id] = {
            "session_id": session_id,
            "job_type": "review",
            "mode": mode,
            "original_name": file_path.name,
            "file_path": str(file_path),
            "output_dir": str(output_dir),
            "log_messages": _sessions.get(session_id, {}).get("log_messages", []),
            "pack_names": pack_names,
            "pack_parts": pack_parts or {},
            "status": "error",
            "error": error_text,
        }
        _persist_session_state(_sessions[session_id])
        msg_queue.put(f"ERROR: {error_text}")

    finally:
        oracle_logger.removeHandler(handler)
        oracle2_logger.removeHandler(handler)
        httpx_logger.removeHandler(handler)
        msg_queue.put(None)  # Sentinel: stream is done


def _run_pack_generate_background(
    session_id: str,
    pdf_path: Path,
    output_dir: Path,
    msg_queue: queue.Queue[str | None],
    name: str | None,
    force_type: str | None,
    use_vision: bool,
    allow_partial: bool,
    overwrite: bool,
) -> None:
    """Generate and register a compliance pack in the background."""
    handler = SessionLogHandler(
        msg_queue,
        on_log=lambda msg: _append_session_log(session_id, msg),
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    oracle_logger = logging.getLogger("oracle")
    httpx_logger = logging.getLogger("httpx")
    oracle_logger.addHandler(handler)
    httpx_logger.addHandler(handler)

    try:
        msg_queue.put("Starting pack generation...")
        pack_slug = cli_generate_pack(
            pdf_path=pdf_path,
            name=name,
            output_dir=output_dir,
            pack_dir=_pack_dir(),
            use_vision=use_vision,
            force_type=force_type,
            register=True,
            allow_partial=allow_partial,
            overwrite=overwrite,
            non_interactive=True,
        )
        detail = _pack_detail(pack_slug, verbose=False)
        _sessions[session_id] = {
            "session_id": session_id,
            "job_type": "pack_generate",
            "status": "complete",
            "error": None,
            "original_name": pdf_path.name,
            "file_path": str(pdf_path),
            "output_dir": str(output_dir),
            "log_messages": _sessions.get(session_id, {}).get("log_messages", []),
            "generated_pack": detail,
        }
        _persist_session_state(_sessions[session_id])
        msg_queue.put(f"Pack generated: {pack_slug}")
    except BaseException as e:
        LOGGER.exception("pack generation failed")
        _sessions[session_id] = {
            "session_id": session_id,
            "job_type": "pack_generate",
            "status": "error",
            "error": str(e),
            "original_name": pdf_path.name,
            "file_path": str(pdf_path),
            "output_dir": str(output_dir),
            "log_messages": _sessions.get(session_id, {}).get("log_messages", []),
        }
        _persist_session_state(_sessions[session_id])
        msg_queue.put(f"ERROR: {e}")
    finally:
        oracle_logger.removeHandler(handler)
        httpx_logger.removeHandler(handler)
        msg_queue.put(None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@oracle_router.post("/analyze")
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("review"),
    packs: str = Form("[]"),
    pack_parts: str = Form("{}"),
    max_rounds: int | None = Form(None),
):
    """Upload a document and start review in background.

    Returns session_id immediately. Client should connect to
    GET /oracle/stream/{session_id} for live progress.
    """

    if mode not in ("polish", "review", "rewrite"):
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

    _evict_stale_sessions()
    session_id = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    pack_names = _parse_json_string(packs, [])
    parsed_pack_parts = _parse_json_string(pack_parts, {})
    if not isinstance(pack_names, list):
        raise HTTPException(status_code=400, detail="packs must be a JSON array")
    if not isinstance(parsed_pack_parts, dict):
        raise HTTPException(status_code=400, detail="pack_parts must be a JSON object")

    original_name = file.filename or "document"
    file_path = session_dir / original_name
    content = await file.read()
    file_path.write_bytes(content)

    # Create message queue and start background thread
    msg_queue: queue.Queue[str | None] = queue.Queue()
    output_dir = session_dir / "oracle_output"
    review_budget = _clamp_user_rounds(max_rounds, mode)

    # Store queue for the stream endpoint to read
    _sessions[session_id] = {
        "session_id": session_id,
        "job_type": "review",
        "mode": mode,
        "original_name": original_name,
        "file_path": str(file_path),
        "output_dir": str(output_dir),
        "log_messages": [],
        "pack_names": pack_names,
        "pack_parts": parsed_pack_parts,
        "status": "processing",
        "msg_queue": msg_queue,
        "error": None,
        "created_at": _time.time(),
    }
    _persist_session_state(_sessions[session_id])

    thread = threading.Thread(
        target=_run_review_background,
        args=(
            session_id,
            file_path,
            mode,
            output_dir,
            msg_queue,
            pack_names,
            parsed_pack_parts,
            review_budget,
        ),
        daemon=True,
    )
    thread.start()

    return {
        "session_id": session_id,
        "status": "processing",
        "job_type": "review",
    }


@oracle_router.get("/stream/{session_id}")
async def stream(request: Request, session_id: str):
    """SSE stream of live oracle2 progress messages.

    Events:
      event: log     — data: "human-readable log line"
      event: done    — data: JSON result (same shape as old /analyze response)
      event: error   — data: error message
    """

    session = _get_session(session_id)
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
                final = _get_session(session_id) or {}
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


@oracle_router.get("/session/{session_id}")
async def session_status(request: Request, session_id: str):
    """Return the latest session status/result payload for polling fallbacks."""

    session = _get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return _build_session_payload(session)


def _build_session_payload(session: dict[str, Any]) -> dict[str, Any]:
    """Build the JSON payload returned by done events and polling status."""
    session_id = session["session_id"]
    job_type = session.get("job_type", "review")
    mode = session.get("mode", "review")
    status = session.get("status", "complete")
    base = {
        "session_id": session_id,
        "job_type": job_type,
        "mode": mode,
        "status": status,
        "error": session.get("error"),
        "log_messages": session.get("log_messages", []),
    }

    if job_type == "pack_generate":
        return {
            **base,
            "pack": session.get("generated_pack"),
        }

    critique = session.get("critique")
    # Downloads follow the artifacts: a human-review stop is a valid terminal
    # state whose findings_report.md exists on disk even if the rich parse was
    # skipped, so don't gate the download links on the status enum alone.
    _output_dir = session.get("output_dir")
    _report_on_disk = bool(_output_dir and (Path(_output_dir) / "findings_report.md").exists())
    report_available = status in ("complete", "ready_to_generate") or _report_on_disk
    return {
        **base,
        "critique": critique if mode == "review" else None,
        "findings_report": session.get("findings_report"),
        "metrics": session.get("metrics"),
        "pack_names": session.get("pack_names", []),
        "pack_parts": session.get("pack_parts", {}),
        "pack_manifest_snapshot": session.get("pack_manifest_snapshot"),
        "docx_url": f"/oracle/download/{session_id}/docx" if report_available else None,
        "pptx_url": f"/oracle/download/{session_id}/pptx" if report_available else None,
        "report_url": f"/oracle/download/{session_id}/report.md" if report_available else None,
        "metrics_url": f"/oracle/download/{session_id}/metrics.json" if report_available else None,
        "compliance_context_url": (
            f"/oracle/download/{session_id}/compliance_context.txt" if report_available else None
        ),
        "pack_snapshot_url": (
            f"/oracle/download/{session_id}/pack_manifest_snapshot.json" if report_available else None
        ),
    }


def _format_done_event(session: dict[str, Any]) -> str:
    """Format the final SSE 'done' event with the result payload."""
    result = _build_session_payload(session)
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
# Oracle Chat
# ---------------------------------------------------------------------------


class OracleChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str


class OracleChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    session_id: str | None = None
    history: list[OracleChatMessage] = Field(default_factory=list)
    selected_packs: list[str] = Field(default_factory=list)
    compare_only: bool = False
    review_only: bool = False


def _split_chat_chunks(text: str) -> list[str]:
    chunks = [
        chunk.strip()
        for chunk in text.replace("\r\n", "\n").split("\n\n")
        if chunk.strip()
    ]
    return chunks or [text]


def _touch_chat_session(session_id: str) -> dict[str, Any]:
    """Return the chat session dict, marking it most-recently-used.

    WHY LRU + cap: _chat_sessions is an in-memory scope store that previously
    grew without bound — every anonymous request minted a new entry forever.
    Insertion order doubles as recency order (the session is re-inserted on
    each access), so evicting from the front drops the least-recently-used
    session. An evicted session only loses its remembered pack scope.
    """
    session = _chat_sessions.pop(session_id, None)
    if session is None:
        session = {}
    _chat_sessions[session_id] = session
    while len(_chat_sessions) > _CHAT_MAX_SESSIONS:
        evicted = next(iter(_chat_sessions))
        _chat_sessions.pop(evicted, None)
        LOGGER.info("Evicted least-recently-used Oracle chat session %s", evicted)
    return session


def _resolve_chat_scope(request: OracleChatRequest) -> tuple[str, list[str], bool, bool]:
    session_id = request.session_id or f"chat-{uuid.uuid4().hex[:8]}"
    session = _touch_chat_session(session_id)

    fields_set = getattr(request, "model_fields_set", set())
    if "selected_packs" in fields_set:
        selected_packs = list(request.selected_packs)
    else:
        selected_packs = list(session.get("selected_packs", []))

    review_only = bool(
        request.review_only if "review_only" in fields_set else session.get("review_only", False)
    )
    compare_requested = (
        request.compare_only if "compare_only" in fields_set else session.get("compare_only", False)
    )
    compare_only = bool(compare_requested and not review_only)

    session["selected_packs"] = list(selected_packs)
    session["compare_only"] = compare_only
    session["review_only"] = review_only
    return session_id, list(selected_packs), compare_only, review_only


@oracle_router.get("/chat/ping")
async def chat_ping(request: Request):
    return {"status": "ok", "domain": "oracle-chat", "advisory_only": True}


@oracle_router.post("/chat")
async def oracle_chat(request: Request, body: OracleChatRequest):
    session_id, selected_packs, compare_only, review_only = _resolve_chat_scope(body)
    # WHY to_thread: answer_query is synchronous and may make up to two
    # provider calls with 120s timeouts; running it inline would block the
    # event loop for every other request on the server.
    result = await asyncio.to_thread(
        oracle_answer_query,
        message=body.message,
        pack_names=selected_packs,
        pack_dir=_pack_dir(),
        compare_only=compare_only,
        review_only=review_only,
    )
    return {
        "session_id": session_id,
        **result,
    }


def _chat_done_payload(result: dict[str, Any], session_id: str) -> dict[str, Any]:
    return {
        "envelope_version": result.get("envelope_version"),
        "session_id": session_id,
        "status": result["status"],
        "answer_text": result.get("answer_text"),
        "evidence_assessment": result.get("evidence_assessment"),
        "citations": result["citations"],
        "follow_ups": result["follow_ups"],
        "selected_packs": result["selected_packs"],
        "compare_only": result["compare_only"],
        "review_only": result["review_only"],
        "advisory_only": result["advisory_only"],
        "diagnostics": result.get("diagnostics"),
        "stage_artifacts": result.get("stage_artifacts"),
    }


@oracle_router.post("/chat/stream")
async def oracle_chat_stream(request: Request, body: OracleChatRequest):
    session_id, selected_packs, compare_only, review_only = _resolve_chat_scope(body)

    async def _event_generator():
        try:
            # WHY to_thread: keeps slow provider calls off the event loop so
            # the SSE stream (and every other request) stays responsive.
            result = await asyncio.to_thread(
                oracle_answer_query,
                message=body.message,
                pack_names=selected_packs,
                pack_dir=_pack_dir(),
                compare_only=compare_only,
                review_only=review_only,
            )
            yield f"event: meta\ndata: {json.dumps({'status': result['status'], 'selected_packs': result['selected_packs'], 'compare_only': result['compare_only'], 'review_only': result['review_only']})}\n\n"
            yield "event: text_start\ndata: {}\n\n"
            for chunk in _split_chat_chunks(str(result["response"])):
                yield f"event: text\ndata: {json.dumps({'text': chunk})}\n\n"
                await asyncio.sleep(0)
            yield "event: text_end\ndata: {}\n\n"
            yield f"event: done\ndata: {json.dumps(_chat_done_payload(result, session_id))}\n\n"
        except Exception:
            # WHY generic detail: exception text can leak file paths, env
            # details, or provider internals to the client. Log the full
            # traceback server-side (never-suppress-error), send a stable
            # generic message outward.
            LOGGER.exception("Oracle chat stream failed for session %s", session_id)
            yield (
                "event: error\ndata: "
                f"{json.dumps({'detail': 'Oracle chat failed. See server logs for details.'})}\n\n"
            )

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Pack Library
# ---------------------------------------------------------------------------


class PromotePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str
    notes: str | None = None
    allow_partial_promotion: bool = False
    override_hash_mismatch: bool = False


@oracle_router.get("/packs")
async def list_packs(request: Request):
    manifest = _load_manifest(_pack_dir())
    packs = [
        _pack_summary(entry)
        for entry in sorted(
            manifest.get("packs", {}).values(),
            key=lambda item: item.get("slug", ""),
        )
    ]
    return {"packs": packs}


@oracle_router.post("/packs/import")
async def import_pack(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    description: str | None = Form(None),
    allow_partial: bool = Form(False),
    overwrite: bool = Form(False),
):

    session_dir = SESSIONS_DIR / f"pack-import-{uuid.uuid4().hex[:12]}"
    session_dir.mkdir(parents=True, exist_ok=True)
    file_path = session_dir / (file.filename or "rulepack.json")
    file_path.write_bytes(await file.read())

    try:
        pack_slug = cli_register_pack(
            file_path,
            _pack_dir(),
            name=name,
            description=description,
            allow_partial=allow_partial,
            overwrite=overwrite,
        )
        return {"status": "complete", "pack": _pack_detail(pack_slug, verbose=False)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@oracle_router.post("/packs/generate")
async def generate_pack_endpoint(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    force_type: str | None = Form(None),
    use_vision: bool = Form(True),
    allow_partial: bool = Form(False),
    overwrite: bool = Form(False),
):

    session_id = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "pack-source.pdf"
    file_path = session_dir / original_name
    file_path.write_bytes(await file.read())
    output_dir = session_dir / "pack_output"
    msg_queue: queue.Queue[str | None] = queue.Queue()

    _sessions[session_id] = {
        "session_id": session_id,
        "job_type": "pack_generate",
        "status": "processing",
        "error": None,
        "original_name": original_name,
        "file_path": str(file_path),
        "output_dir": str(output_dir),
        "log_messages": [],
        "msg_queue": msg_queue,
        "created_at": _time.time(),
    }
    _persist_session_state(_sessions[session_id])

    thread = threading.Thread(
        target=_run_pack_generate_background,
        args=(
            session_id,
            file_path,
            output_dir,
            msg_queue,
            name,
            force_type,
            use_vision,
            allow_partial,
            overwrite,
        ),
        daemon=True,
    )
    thread.start()

    return {"session_id": session_id, "status": "processing", "job_type": "pack_generate"}


@oracle_router.get("/packs/{name}")
async def show_pack(request: Request, name: str, verbose: bool = False):
    try:
        return _pack_detail(name, verbose=verbose)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@oracle_router.post("/packs/{name}/promote")
async def promote_pack_endpoint(request: Request, name: str, body: PromotePackRequest):
    try:
        cli_promote_pack(
            pack_name=name,
            pack_dir=_pack_dir(),
            reviewer=body.reviewer,
            notes=body.notes,
            allow_partial=body.allow_partial_promotion,
            override_hash_mismatch=body.override_hash_mismatch,
            auto_confirm=True,
        )
        return {"status": "complete", "pack": _pack_detail(name, verbose=False)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@oracle_router.delete("/packs/{name}")
async def delete_pack(request: Request, name: str):
    if not cli_remove_pack(name, _pack_dir()):
        raise HTTPException(status_code=404, detail=f"Pack not found: {name}")
    return {"status": "complete", "removed": name}


# ---------------------------------------------------------------------------
# Generate + Download
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    """Request body for the generate endpoint."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    approved: bool


def _review_status_label(review_result) -> str:
    """Honest convergence status for generated deliverables.

    WHY: non-converged runs were previously labeled "Maximum Reasoning",
    a euphemism that presented an unfinished (or entirely failed) review
    as a feature (AUDIT F2). The label must state what actually happened.
    """
    consensus_type = getattr(review_result, "consensus_type", "")
    if review_result.converged:
        if consensus_type == "stable_with_notes":
            return "Converged (unresolved notes remain — see findings report)"
        return "Converged"
    if consensus_type == "blocked":
        return "NOT CONVERGED — blocked, needs human review"
    return "NOT CONVERGED — review incomplete"


def _require_reviewed_result(session: dict):
    """Return the session's ReviewResult, refusing unreviewed content.

    WHY 409: a session whose every round was invalid (e.g., a vendor
    outage) has rounds=[] and a "final draft" identical to the unreviewed
    input. Generating a polished deliverable from it would ship an
    unreviewed document under a review banner (AUDIT C2 + F2).
    """
    review_result = session.get("review_result")
    if not review_result:
        raise HTTPException(status_code=400, detail="Review not complete")
    if not review_result.rounds:
        raise HTTPException(
            status_code=409,
            detail=(
                "No valid review rounds — the document was never successfully "
                "reviewed (all rounds failed). Nothing trustworthy to generate."
            ),
        )
    return review_result


@oracle_router.post("/generate")
async def generate(request: Request, body: GenerateRequest):
    """Generate polished output documents from a reviewed session."""

    session = _get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not body.approved:
        raise HTTPException(status_code=400, detail="Review not approved")

    _require_reviewed_result(session)

    return {
        "docx_url": f"/oracle/download/{body.session_id}/docx",
        "pptx_url": f"/oracle/download/{body.session_id}/pptx",
    }


@oracle_router.get("/download/{session_id}/{fmt}")
async def download(request: Request, session_id: str, fmt: str):
    """Download a generated document (polished formatting)."""

    session = _get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    original_name = session["original_name"]
    base_name = Path(original_name).stem
    output_dir = Path(session["output_dir"])

    if fmt == "report.md":
        report_path = output_dir / "findings_report.md"
        if not report_path.exists():
            raise HTTPException(status_code=404, detail="Findings report not found")
        return FileResponse(
            str(report_path),
            media_type="text/markdown; charset=utf-8",
            filename=f"{base_name}_findings_report.md",
        )

    if fmt == "metrics.json":
        metrics_path = output_dir / "metrics.json"
        if not metrics_path.exists():
            raise HTTPException(status_code=404, detail="Metrics not found")
        return FileResponse(
            str(metrics_path),
            media_type="application/json",
            filename=f"{base_name}_metrics.json",
        )

    if fmt == "compliance_context.txt":
        context_path = output_dir / "compliance_context.txt"
        if not context_path.exists():
            raise HTTPException(status_code=404, detail="Compliance context not found")
        return FileResponse(
            str(context_path),
            media_type="text/plain; charset=utf-8",
            filename=f"{base_name}_compliance_context.txt",
        )

    if fmt == "pack_manifest_snapshot.json":
        snapshot_path = output_dir / "pack_manifest_snapshot.json"
        if not snapshot_path.exists():
            raise HTTPException(status_code=404, detail="Pack snapshot not found")
        return FileResponse(
            str(snapshot_path),
            media_type="application/json",
            filename=f"{base_name}_pack_manifest_snapshot.json",
        )

    review_result = _require_reviewed_result(session)

    try:
        from oracle.document_generator import generate_docx, generate_pptx
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Document generation dependency missing: {exc.name}",
        ) from exc

    doc_title = f"{base_name} \u2014 Oracle Review"

    if fmt == "docx":
        out_path = output_dir / f"{base_name}_polished.docx"
        try:
            generate_docx(
                final_draft=review_result.final_draft,
                output_path=out_path,
                title=doc_title,
                subtitle=f"Oracle2 Multi-Oracle Review | {review_result.total_rounds} round(s) | {_review_status_label(review_result)}",
            )
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"DOCX generation dependency missing: {exc.name}",
            ) from exc
        return FileResponse(
            str(out_path),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{base_name}_polished.docx",
        )

    elif fmt == "pptx":
        out_path = output_dir / f"{base_name}_polished.pptx"
        try:
            generate_pptx(
                final_draft=review_result.final_draft,
                output_path=out_path,
                title=doc_title,
                subtitle=f"Oracle2 Multi-Oracle Review | {review_result.total_rounds} round(s) | {_review_status_label(review_result)}",
            )
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"PPTX generation dependency missing: {exc.name}",
            ) from exc
        return FileResponse(
            str(out_path),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=f"{base_name}_polished.pptx",
        )

    else:
        raise HTTPException(status_code=400, detail=f"Invalid format: {fmt}")


# ---------------------------------------------------------------------------
# HEARTH — buyer-side DocScrubber, mounted under /hearth (founder mode)
# ---------------------------------------------------------------------------
# Founder-directed post-P1 amendment (logged in BUILD_NOTES.md): HEARTH spec
# v0.3 §12 shipped Phase 1 as CLI-only; this router exposes the SAME
# findings-only pipeline over the existing single-tenant instance so it is
# reachable at <host>/hearth/*. Auth reuses the ORACLE_API_KEY gate (auth by
# default via router dependency). UPL posture is unchanged: findings-only,
# banners included, every run leaves an immutable audit artifact, and no
# BuyerPack material exists anywhere on this surface (spec §1.1).

hearth_router = APIRouter(prefix="/hearth", dependencies=[Depends(verify_api_key)])


def _hearth_audit_dir() -> Path:
    # Resolved per request (not at import) so deployments and tests can
    # point the audit trail without a process restart.
    return Path(os.environ.get("HEARTH_AUDIT_DIR", "hearth_audit"))


@app.get("/hearth/health")
async def hearth_health() -> dict[str, str]:
    """Liveness for the HEARTH organ. No auth required (matches /health)."""
    return {
        "status": "ok",
        "service": "hearth",
        "version": HEARTH_VERSION,
        "phase": "P1",
        "mode": "findings-only",
    }


@hearth_router.get("/packs")
async def hearth_list_packs() -> dict[str, Any]:
    """List installed JurisdictionPacks with their review posture."""
    packs = []
    for pack_file in sorted(BUILTIN_JURISDICTION_DIR.glob("*/pack.json")):
        loaded = load_pack(pack_file.parent.name)
        pack = loaded.pack
        packs.append(
            {
                "name": pack_file.parent.name,
                "pack_id": pack.pack_id,
                "status": pack.governance.status,
                "owner": pack.governance.owner,
                "rules": len(pack.rules),
                "provisional_rules": sum(
                    1 for rule in pack.rules if rule.status == "provisional"
                ),
            }
        )
    return {"packs": packs, "legal_banner": LEGAL_BANNER}


@hearth_router.post("/scrub")
async def hearth_scrub(
    file: UploadFile = File(...),
    pack: str = Form("CO-Larimer"),
    target_price: int | None = Form(None),
) -> dict[str, Any]:
    """Scrub an uploaded document — the CLI pipeline over HTTP.

    Semantics mirror `hearth scrub`: a refusal is a RESULT, not a transport
    error, so it returns 200 with refused=true (the CLI's exit-2 analogue).
    HTTP errors are reserved for transport-level problems: bad params (422),
    oversized upload (413), missing auth (401), unwritable audit trail (500
    — a run that cannot leave its §11 trail must not report success).
    """
    if target_price is not None and target_price <= 0:
        raise HTTPException(status_code=422, detail="target_price must be a positive integer")
    document_name = Path(file.filename or "upload").name  # strip path components
    suffix = Path(document_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported format '{suffix or '(none)'}'; "
            f"supported: {', '.join(SUPPORTED_SUFFIXES)}",
        )
    payload = await file.read()
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds the {MAX_DOCUMENT_BYTES:,}-byte scrub limit",
        )

    loaded = None
    try:
        loaded = load_pack(pack)
    except PackError as exc:
        LOGGER.error("hearth scrub: pack load failed closed: %s", exc)
        run = refusal_run(
            document_name,
            reason=f"jurisdiction pack unusable: {exc}",
            target_price_usd=target_price,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="hearth_scrub_") as workdir:
            document_path = Path(workdir) / document_name
            document_path.write_bytes(payload)
            run = scrub_document(
                document_path, loaded.pack, target_price_usd=target_price
            )

    rendered = render_report(run, loaded.pack if loaded else None)
    try:
        artifact = build_artifact(
            run, loaded, rendered, exit_code=2 if run.refused else 0
        )
        audit_path = write_artifact(artifact, _hearth_audit_dir())
    except AuditWriteError as exc:
        LOGGER.error("hearth scrub: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"audit artifact could not be written; result withheld (fail closed): {exc}",
        ) from exc

    rules_by_id = {rule.rule_id: rule for rule in loaded.pack.rules} if loaded else {}
    provisional = sum(
        1
        for finding in run.findings
        if rules_by_id.get(finding.jurisdiction_basis) is not None
        and rules_by_id[finding.jurisdiction_basis].status == "provisional"
    )
    return {
        "document": run.document_name,
        "document_sha256": run.document_sha256,
        "pack": run.pack_id,
        "run_date": run.run_date.isoformat(),
        "target_price_usd": run.target_price_usd,
        "refused": run.refused,
        "refusal_reason": run.refusal_reason,
        "findings": [finding.to_json_dict() for finding in run.findings],
        "provisional_findings": provisional,
        "rendered_report": rendered,
        "audit_artifact": str(audit_path),
        "legal_banner": LEGAL_BANNER,
    }


def _hearth_store():
    """Server-side evidence store (single-tenant, §1.1). Resolved per
    request so deployments/tests can point it without a restart."""
    from hearth.db.evidence_store import EvidenceStore

    return EvidenceStore(Path(os.environ.get("HEARTH_STORE_DIR", "hearth_store")))


@hearth_router.get("/properties")
async def hearth_properties() -> dict[str, Any]:
    """Stored identities with their join posture (§14 P3-C)."""
    from hearth.db.evidence_store import JOIN_CONFIDENCE_THRESHOLD, EvidenceStoreError

    store = _hearth_store()
    properties = []
    for identity in store.identities():
        joins_blocked = (
            identity.match_confidence < JOIN_CONFIDENCE_THRESHOLD
            and not identity.manual_override
        )
        fields: list[str] = []
        if not joins_blocked:
            try:
                fields = sorted({r.field for r in store.evidence_for(identity.property_uid)})
            except EvidenceStoreError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        properties.append(
            {
                "property_uid": identity.property_uid,
                "address": identity.address_normalized,
                "parcels": identity.parcels,
                "match_confidence": identity.match_confidence,
                "manual_override": identity.manual_override,
                "joins_blocked": joins_blocked,
                "evidence_fields": fields,
            }
        )
    return {"store": str(store.root), "properties": properties}


@hearth_router.post("/scan")
async def hearth_scan(
    property: str = Form(...),
    pack: str = Form("CO-Larimer"),
) -> dict[str, Any]:
    """Landmine scan over HTTP — refusals are results (200 + refused=true)."""
    from hearth.cli import _resolve_property_ref
    from hearth.core.signals.landmines import refusal_scan, scan_property
    from hearth.db.evidence_store import EvidenceStoreError
    from hearth.utils.render import render_scan_report

    loaded = None
    try:
        loaded = load_pack(pack)
        store = _hearth_store()
        uid = _resolve_property_ref(store, property)
    except PackError as exc:
        run = refusal_scan(property, reason=f"jurisdiction pack unusable: {exc}")
    except EvidenceStoreError as exc:
        run = refusal_scan(property, reason=str(exc), pack=loaded.pack if loaded else None)
    else:
        run = scan_property(uid, store, loaded.pack)

    rendered = render_scan_report(run, loaded.pack if loaded else None)
    from hearth.audit.artifact import build_scan_artifact

    try:
        artifact = build_scan_artifact(
            run,
            loaded,
            _hearth_store().root,
            rendered,
            2 if run.refused else 0,
        )
        audit_path = write_artifact(artifact, _hearth_audit_dir())
    except AuditWriteError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"audit artifact could not be written; result withheld (fail closed): {exc}",
        ) from exc
    return {
        "property_uid": run.property_uid,
        "pack": run.pack_id,
        "run_date": run.run_date.isoformat(),
        "refused": run.refused,
        "refusal_reason": run.refusal_reason,
        "alerts": [alert.to_json_dict() for alert in run.alerts],
        "rendered_report": rendered,
        "audit_artifact": str(audit_path),
        "legal_banner": LEGAL_BANNER,
    }


@hearth_router.post("/ingest")
async def hearth_ingest(
    file: UploadFile = File(...),
    adapter: str = Form(...),
) -> dict[str, Any]:
    """Bulk-export ingest over HTTP (§14 P3-C); refusals are results."""
    from hearth.core.identity.resolver import (
        property_uid as derive_uid,
        reconcile_identity,
        resolve_batches,
    )
    from hearth.data import PropertyEvidence
    from hearth.db.evidence_store import EvidenceStoreError
    from hearth.ingest import IngestError, get_adapter

    document_name = Path(file.filename or "upload").name
    payload = await file.read()
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="upload exceeds the scrub limit")
    try:
        source_adapter = get_adapter(adapter)
        with tempfile.TemporaryDirectory(prefix="hearth_ingest_") as workdir:
            source_file = Path(workdir) / document_name
            source_file.write_bytes(payload)
            batch = source_adapter.parse(source_file)
        store = _hearth_store()
        outcomes = {"created": 0, "kept": 0, "upgraded": 0, "conflict": 0}
        conflicts: list[str] = []
        for identity in resolve_batches([batch]):
            current = store.get_identity(identity.property_uid)
            merged, outcome = reconcile_identity(current, identity)
            outcomes[outcome] += 1
            if outcome == "conflict":
                conflicts.append(merged.property_uid)
            if merged is not current:
                store.upsert_identity(merged)
        rows = 0
        for record in batch.records:
            uid = derive_uid("CO", "Larimer", record.parcel_id)
            for field_name, value in record.fields.items():
                store.add_evidence(
                    PropertyEvidence(
                        property_uid=uid,
                        field=field_name,
                        value=value,
                        source=batch.rights.source,
                        retrieved=batch.retrieved,
                        confidence=batch.rights.confidence_tier,
                    )
                )
                rows += 1
    except (IngestError, EvidenceStoreError) as exc:
        LOGGER.error("hearth ingest failed closed: %s", exc)
        return {"refused": True, "reason": str(exc)}
    return {
        "refused": False,
        "source": batch.source_id,
        "outcomes": outcomes,
        "conflicts": conflicts,
        "evidence_rows": rows,
        "rights_verified": batch.rights.verified,
    }


@hearth_router.post("/wells")
async def hearth_wells(
    file: UploadFile = File(...),
    radius_ft: int = Form(2000),
) -> dict[str, Any]:
    """ECMC well-proximity computation over HTTP; refusals are results."""
    from hearth.core.signals.wells import (
        WellsError,
        compute_well_proximity,
        parse_wells_csv,
    )
    from hearth.db.evidence_store import EvidenceStoreError

    payload = await file.read()
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="upload exceeds the scrub limit")
    try:
        with tempfile.TemporaryDirectory(prefix="hearth_wells_") as workdir:
            wells_file = Path(workdir) / Path(file.filename or "wells.csv").name
            wells_file.write_bytes(payload)
            records = parse_wells_csv(wells_file)
        annotated = compute_well_proximity(
            _hearth_store(), records, radius_ft=radius_ft
        )
    except (WellsError, EvidenceStoreError) as exc:
        LOGGER.error("hearth wells failed closed: %s", exc)
        return {"refused": True, "reason": str(exc)}
    return {
        "refused": False,
        "wells_parsed": len(records),
        "identities_annotated": annotated,
        "radius_ft": radius_ft,
    }


@hearth_router.post("/radon")
async def hearth_radon(county: str = Form("Larimer")) -> dict[str, Any]:
    """Stamp the verified EPA radon zone; refusals are results."""
    from hearth.db.evidence_store import EvidenceStoreError
    from hearth.ingest.co_radon import EPA_RADON_ZONES, RadonError, stamp_radon_zone

    try:
        stamped = stamp_radon_zone(_hearth_store(), county)
    except (RadonError, EvidenceStoreError) as exc:
        LOGGER.error("hearth radon failed closed: %s", exc)
        return {"refused": True, "reason": str(exc)}
    return {
        "refused": False,
        "county": county,
        "zone": EPA_RADON_ZONES[county.strip().lower()],
        "identities_stamped": stamped,
    }


@hearth_router.post("/evidence")
async def hearth_add_evidence(
    property: str = Form(...),
    field: str = Form(...),
    value: str = Form(...),
    source_note: str = Form("founder observation"),
) -> dict[str, Any]:
    """Buyer-supplied evidence row (§4 tier 0.80); refusals are results."""
    from datetime import date as _date

    from hearth.cli import _resolve_property_ref
    from hearth.data import PropertyEvidence
    from hearth.db.evidence_store import EvidenceStoreError

    typed: int | float | str = value
    try:
        typed = int(value)
    except ValueError:
        try:
            typed = float(value)
        except ValueError:
            pass  # ratings/zones stay strings by design
    try:
        store = _hearth_store()
        uid = _resolve_property_ref(store, property)
        store.add_evidence(
            PropertyEvidence(
                property_uid=uid,
                field=field,
                value=typed,
                source=f"buyer-supplied: {source_note}",
                retrieved=_date.today(),
                confidence=0.8,
            )
        )
    except EvidenceStoreError as exc:
        LOGGER.error("hearth add-evidence failed closed: %s", exc)
        return {"refused": True, "reason": str(exc)}
    return {"refused": False, "property_uid": uid, "field": field, "value": typed}


@hearth_router.get("/pull-plan")
async def hearth_pull_plan() -> dict[str, Any]:
    """The §14 source registry + manual runbook, structured for the UI."""
    from hearth.ingest.fetch import SOURCES

    return {
        "sources": [
            {
                "source_id": s.source_id,
                "description": s.description,
                "format": s.file_format,
                "urls": list(s.urls),
                "manual_steps": list(s.manual_steps),
                "then": s.adapter_hint,
                "notes": s.notes,
            }
            for s in SOURCES.values()
        ]
    }


@hearth_router.get("/pack-status")
async def hearth_pack_status(pack: str = "CO-Larimer") -> dict[str, Any]:
    """Governance posture for the UI; refusals are results."""
    from hearth.packs.governance import GovernanceError, check_freshness

    try:
        loaded = load_pack(pack)
        freshness = check_freshness(loaded.pack, loaded.path.parent)
    except (PackError, GovernanceError) as exc:
        return {"refused": True, "reason": str(exc)}
    statuses: dict[str, int] = {}
    for rule in loaded.pack.rules:
        statuses[rule.status] = statuses.get(rule.status, 0) + 1
    return {
        "refused": False,
        "pack_id": loaded.pack.pack_id,
        "owner": loaded.pack.governance.owner,
        "rules_by_status": statuses,
        "fresh": freshness.fresh,
        "issues": [
            {"kind": i.kind, "source": i.source, "detail": i.detail}
            for i in freshness.issues
        ],
    }


# Mount the authenticated oracle + hearth routers onto the app
app.include_router(oracle_router)
app.include_router(hearth_router)


@app.get("/health")
async def health():
    """Health check endpoint for Railway. No auth required.

    Also reports non-sensitive provider-key fingerprints — presence and length
    only, never the value — so a key rotation can be verified against the LIVE
    process without shell access. If `keys.anthropic.present` is false the
    variable isn't reaching this service/environment (a Railway wiring issue,
    not a bad key); a length far from ~100 means the value is truncated.
    """
    def _fingerprint(var: str) -> dict[str, Any]:
        value = os.environ.get(var) or ""
        return {"present": bool(value), "length": len(value)}

    return {
        "status": "ok",
        "service": "oracle",
        "keys": {
            "anthropic": _fingerprint("ANTHROPIC_API_KEY"),
            "openai": _fingerprint("OPENAI_API_KEY"),
            "xai": _fingerprint("XAI_API_KEY"),
        },
    }
