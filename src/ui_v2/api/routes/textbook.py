# src/ui_v2/api/routes/textbook.py
"""
Textbook notes generation and Google Doc writing routes.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent

from backend import generate_textbook_notes, write_to_google_doc
from src.ui_v2.api.session import require_session_id              # noqa: E402

router = APIRouter()

_TEXTBOOKS_FILE = _REPO_ROOT / "textbooks.json"


def _load_textbooks() -> list[dict]:
    try:
        return json.loads(_TEXTBOOKS_FILE.read_text()).get("textbooks", [])
    except Exception:
        return []


def _find_textbook_for_doc(doc_id: str) -> dict | None:
    for tb in _load_textbooks():
        if doc_id and doc_id in tb.get("doc_ids", []):
            return tb
    return None


# ── Pydantic models ────────────────────────────────────────────────────────

class GenerateNotesRequest(BaseModel):
    topic: str
    doc_id: str = ""
    model: str = ""


class WriteToDocRequest(BaseModel):
    doc_id: str
    notes: str
    credentials_path: str = ""


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/list")
async def list_textbooks():
    return {"textbooks": _load_textbooks()}


@router.get("/for-doc/{doc_id}")
async def textbook_for_doc(doc_id: str):
    tb = _find_textbook_for_doc(doc_id)
    if not tb:
        return {"textbook": None}
    return {"textbook": tb}


@router.post("/generate-notes")
async def generate_notes(req: GenerateNotesRequest, _: str = Depends(require_session_id)):
    tb = _find_textbook_for_doc(req.doc_id)
    if not tb:
        raise HTTPException(
            status_code=404,
            detail="No textbook is associated with this doc ID. Add the doc ID to textbooks.json.",
        )
    loop = asyncio.get_event_loop()
    notes = await loop.run_in_executor(
        None,
        lambda: generate_textbook_notes(topic=req.topic, textbook=tb, model=req.model),
    )
    return {"notes": notes, "textbook": tb["full_title"]}


@router.post("/write-to-doc")
async def write_notes_to_doc(req: WriteToDocRequest, _: str = Depends(require_session_id)):
    if not req.doc_id:
        raise HTTPException(status_code=400, detail="doc_id is required")
    creds = req.credentials_path or os.environ.get("CSA_CREDENTIALS_PATH", "")
    loop = asyncio.get_event_loop()
    tab_name = await loop.run_in_executor(
        None,
        lambda: write_to_google_doc(req.doc_id, req.notes, creds),
    )
    return {"tab_name": tab_name}
