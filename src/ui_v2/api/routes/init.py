# src/ui_v2/api/routes/init.py
"""
Bootstrap endpoint — returns docs, prefs, and Ollama model lists in one
round-trip so the Sidebar can populate without 4 separate requests.
"""
from __future__ import annotations

import asyncio
from fastapi import APIRouter

# sys.path is already set by main.py before routes are imported
from backend import load_docs, load_prefs, list_ollama_models, list_vision_models  # noqa: E402

router = APIRouter()


@router.get("")
async def app_init():
    """
    Single bootstrap call the frontend makes on mount.
    Returns everything needed to populate the sidebar selectors.
    """
    loop = asyncio.get_event_loop()
    # Both model-list calls hit Ollama HTTP; run off the event loop
    models, vision_models = await asyncio.gather(
        loop.run_in_executor(None, list_ollama_models),
        loop.run_in_executor(None, list_vision_models),
    )
    return {
        "docs":          load_docs(),
        "prefs":         load_prefs(),
        "models":        models,
        "vision_models": vision_models,
    }
