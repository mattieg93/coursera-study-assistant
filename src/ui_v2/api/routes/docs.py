# src/ui_v2/api/routes/docs.py
"""
Google Doc registry + user preferences routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend import (
    load_docs,
    save_docs,
    get_service_account_email,
    load_prefs,
    save_prefs,
)
from src.ui_v2.api.session import (  # noqa: E402
    SessionData,
    require_session,
    get_session,
    require_session_id,
)

router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────

class DocEntry(BaseModel):
    id: str
    name: str = ""


class PrefsUpdate(BaseModel):
    agent_model: str | None = None
    vision_model: str | None = None


# ── Docs registry ──────────────────────────────────────────────────────────

@router.get("")
async def list_docs():
    return {"docs": load_docs()}


@router.post("")
async def add_or_edit_doc(entry: DocEntry, session_id: str = Depends(require_session_id)):
    if not entry.id.strip():
        raise HTTPException(status_code=400, detail="Doc ID is required")
    docs = load_docs()
    docs = [d for d in docs if d["id"] != entry.id]
    docs.append({"id": entry.id.strip(), "name": entry.name.strip() or entry.id.strip()})
    save_docs(docs)
    # Update session's active doc
    sess = get_session(session_id)
    sess.agent_doc_id = entry.id.strip()
    return {"docs": docs, "active_id": sess.agent_doc_id}


@router.delete("/{doc_id}")
async def delete_doc(doc_id: str, session_id: str = Depends(require_session_id)):
    docs = load_docs()
    docs = [d for d in docs if d["id"] != doc_id]
    save_docs(docs)
    sess = get_session(session_id)
    if sess.agent_doc_id == doc_id:
        sess.agent_doc_id = docs[0]["id"] if docs else ""
    return {"docs": docs, "active_id": sess.agent_doc_id}


@router.post("/select/{doc_id}")
async def select_doc(doc_id: str, session_id: str = Depends(require_session_id)):
    """Set the active doc for this session (triggers db reinit on next query)."""
    sess = get_session(session_id)
    sess.agent_doc_id = doc_id
    return {"active_id": doc_id}


@router.get("/service-account-email")
async def service_account_email():
    return {"email": get_service_account_email()}


# ── Preferences ────────────────────────────────────────────────────────────

@router.get("/prefs")
async def get_prefs():
    return load_prefs()


@router.patch("/prefs")
async def update_prefs(update: PrefsUpdate):
    patch = {k: v for k, v in update.model_dump().items() if v is not None}
    if patch:
        save_prefs(patch)
    return load_prefs()
