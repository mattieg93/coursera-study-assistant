# src/ui_v2/api/routes/kb.py
"""
Knowledge base management routes — add manual entries, sync from Google Doc, stats.
"""
from __future__ import annotations

import asyncio
import io
import contextlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import sync_notes, show_statistics
from src.ui_v2.api.session import (              # noqa: E402
    require_session_id,
    get_session,
    get_session_db,
)

router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────

class AddLectureRequest(BaseModel):
    title: str
    content: str
    tab: str = "Manual"


class SyncRequest(BaseModel):
    doc_id: str = ""


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/add")
async def add_lecture(req: AddLectureRequest, session_id: str = Depends(require_session_id)):
    if not req.title or not req.content:
        raise HTTPException(status_code=400, detail="title and content are required")
    db = get_session_db(session_id)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: db.add_lectures([{
        "tab": req.tab,
        "title": req.title,
        "content": req.content,
        "sections": {"summary": req.content},
    }]))
    return {"status": "added", "title": req.title}


@router.post("/sync")
async def sync_kb(req: SyncRequest, session_id: str = Depends(require_session_id)):
    sess = get_session(session_id)
    doc_id = req.doc_id or sess.agent_doc_id
    if not doc_id:
        raise HTTPException(status_code=400, detail="No doc_id provided or set in session")
    db = get_session_db(session_id)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: sync_notes(db, doc_id=doc_id))
    return {"status": "synced", "doc_id": doc_id}


@router.get("/stats")
async def kb_stats(session_id: str = Depends(require_session_id)):
    loop = asyncio.get_event_loop()
    def _stats() -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            show_statistics()
        return buf.getvalue()
    stats = await loop.run_in_executor(None, _stats)
    return {"stats": stats}
