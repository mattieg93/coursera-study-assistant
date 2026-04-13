# src/ui_v2/api/main.py
"""
FastAPI application entry point for Coursera Study Assistant v2.
Run from repo root:  .venv-1/bin/uvicorn src.ui_v2.api.main:app --reload
Dev:                 also run `npm run dev` in src/ui_v2/web/
"""
import os
import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────
# Make backend.py (in src/ui/) importable regardless of working directory.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent  # coursera-study-assistant/
_UI_V1 = _REPO_ROOT / "src" / "ui"
for _p in [str(_REPO_ROOT), str(_UI_V1)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.ui_v2.api.routes import chat, agent, docs, models, textbook, kb, init

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="Coursera Study Assistant v2", version="2.0.0")

# ── Upload size (10 MB) ────────────────────────────────────────────────────
class LimitUploadSizeMiddleware(BaseHTTPMiddleware):
    """Reject bodies larger than max_bytes before they hit route handlers."""
    def __init__(self, app, max_bytes: int = 10 * 1024 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                {"detail": f"Upload too large (max {self.max_bytes // 1024 // 1024} MB)"},
                status_code=413,
            )
        return await call_next(request)

app.add_middleware(LimitUploadSizeMiddleware)

# ── CORS — dev only ────────────────────────────────────────────────────────
if os.environ.get("DEV_MODE", "").lower() == "true":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── API routers ────────────────────────────────────────────────────────────
app.include_router(chat.router,     prefix="/api/chat",     tags=["chat"])
app.include_router(agent.router,    prefix="/api/agent",    tags=["agent"])
app.include_router(docs.router,     prefix="/api/docs",     tags=["docs"])
app.include_router(models.router,   prefix="/api/models",   tags=["models"])
app.include_router(textbook.router, prefix="/api/textbook", tags=["textbook"])
app.include_router(kb.router,       prefix="/api/kb",       tags=["kb"])
app.include_router(init.router,     prefix="/api/init",     tags=["init"])

# WebSocket router lives at /ws (no /api prefix)
app.include_router(agent.ws_router)

# ── Static + SPA catch-all (production) ───────────────────────────────────
_DIST = _REPO_ROOT / "src" / "ui_v2" / "web" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve index.html for all client-side wouter routes."""
        index = _DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"detail": "Frontend not built — run `npm run build` in src/ui_v2/web/"}
