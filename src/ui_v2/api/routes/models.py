# src/ui_v2/api/routes/models.py
"""
Ollama model discovery routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from backend import list_ollama_models, list_vision_models

router = APIRouter()


@router.get("/list")
async def get_models():
    """All locally available Ollama models. Empty list if Ollama is down."""
    return {"models": list_ollama_models()}


@router.get("/vision-list")
async def get_vision_models():
    """Only vision-capable Ollama models. Empty list if none found."""
    return {"models": list_vision_models()}
