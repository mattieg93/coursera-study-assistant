# src/ui_v2/api/session.py
"""
In-memory session store for single-user local app.
Session ID is a UUID stored in the browser's localStorage and sent via
the X-Session-ID header on every request.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure study_system is on path (backend.py may not have been imported yet)
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_STUDY_SYSTEM = _REPO_ROOT / "src" / "study_system"
if str(_STUDY_SYSTEM) not in sys.path:
    sys.path.insert(0, str(_STUDY_SYSTEM))

from study_db import StudyDatabase  # noqa: E402

from fastapi import Header, HTTPException


class SessionData:
    """All per-session mutable state."""

    def __init__(self) -> None:
        self.messages: list[dict] = []          # [{role, content}]
        self.last_quiz: dict | None = None       # {questions: [...]}
        self.agent_doc_id: str = ""              # desired doc for this session
        self.db_doc_id: str = ""                 # what self.db was built for
        self.db: StudyDatabase = StudyDatabase(doc_id="")
        self.agent_state: dict = {}              # keyed by job_id


# Global store — survives the process lifetime (single-user local app)
_store: dict[str, SessionData] = {}


def get_session(session_id: str) -> SessionData:
    """Return existing session or create a new one."""
    if session_id not in _store:
        _store[session_id] = SessionData()
    return _store[session_id]


def get_session_db(session_id: str) -> StudyDatabase:
    """Return the StudyDatabase for this session.

    Recreates the instance if agent_doc_id has changed since the db was
    last built — mirrors the db_doc_id guard in the Streamlit v1 frontend.
    """
    sess = get_session(session_id)
    if sess.db_doc_id != sess.agent_doc_id:
        sess.db = StudyDatabase(doc_id=sess.agent_doc_id)
        sess.db_doc_id = sess.agent_doc_id
    return sess.db


# ── FastAPI dependency ─────────────────────────────────────────────────────

def require_session(x_session_id: str = Header(...)) -> SessionData:
    """FastAPI dependency — resolves X-Session-ID header to a SessionData."""
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")
    return get_session(x_session_id)


def require_session_id(x_session_id: str = Header(...)) -> str:
    """FastAPI dependency — returns the raw session ID string."""
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")
    get_session(x_session_id)  # ensure it exists
    return x_session_id
