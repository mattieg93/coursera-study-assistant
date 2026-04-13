# src/ui_v2/api/routes/agent.py
"""
Coursera Agent routes — URL queue management, async subprocess runner,
WebSocket streaming of real-time agent output.

NOTE: The subprocess launch intentionally does NOT use run_agent_subprocess()
from backend.py because that returns a synchronous subprocess.Popen.
Using it inside a WebSocket handler would block the entire asyncio event loop.
Instead we use asyncio.create_subprocess_exec with the same env vars and
stdin URL-write pattern.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.ui_v2.api.session import (
    SessionData,
    require_session,
    require_session_id,
    get_session,
)

router    = APIRouter()
ws_router = APIRouter()

_REPO_ROOT  = Path(__file__).parent.parent.parent.parent.parent
_AGENT_DIR  = _REPO_ROOT / "src" / "coursera_agent"
_PYTHON     = _REPO_ROOT / ".venv-1" / "bin" / "python3"
_AGENT_SCRIPT = _AGENT_DIR / "coursera_agent.py"

# ── Regex patterns for structured agent output (mirrors frontend v1) ───────
_ITEM_RE    = re.compile(r'[\U0001f4f9\U0001f4d6]\s*(VIDEO|READING)\s*(\d+)/(\d+):\s*(.+)')
_STAGE_RE   = re.compile(r'[\U0001f4fa\U0001f916\U0001f4be\U0001f4d6]\s*(\d+)/([34])\s+(.+)')
_DONE_RE    = re.compile(r'\u2713 Completed (video|reading) (\d+)/(\d+)')
_FOUND_RE   = re.compile(r'Found (\d+) course items')
_ALLDONE_RE = re.compile(r'\U0001f38a ALL ITEMS COMPLETE')

# ── In-process job store ───────────────────────────────────────────────────
# job_id → {"log": [str], "status": "running"|"done"|"error", "task": Task}
_jobs: dict[str, dict] = {}


# ── Pydantic models ────────────────────────────────────────────────────────

class AddUrlRequest(BaseModel):
    url: str


class RunRequest(BaseModel):
    all_videos: bool = True
    readings: bool = True
    doc_id: str = ""
    model: str = ""
    credentials_path: str = ""


# ── Queue endpoints ────────────────────────────────────────────────────────

@router.post("/queue/add")
async def queue_add(req: AddUrlRequest, sess: SessionData = Depends(require_session)):
    if "coursera.org" not in req.url:
        raise HTTPException(status_code=400, detail="URL must be from coursera.org")
    sess.agent_state.setdefault("queue", [])
    sess.agent_state["queue"].append({"url": req.url.strip(), "status": "pending"})
    return {"queue": sess.agent_state["queue"]}


@router.delete("/queue/{index}")
async def queue_remove(index: int, sess: SessionData = Depends(require_session)):
    q = sess.agent_state.get("queue", [])
    if not (0 <= index < len(q)):
        raise HTTPException(status_code=404, detail="Queue index out of range")
    if q[index]["status"] != "pending":
        raise HTTPException(status_code=400, detail="Can only remove pending items")
    q.pop(index)
    return {"queue": q}


@router.post("/queue/clear")
async def queue_clear(sess: SessionData = Depends(require_session)):
    sess.agent_state["queue"] = []
    return {"queue": []}


@router.get("/queue")
async def queue_get(sess: SessionData = Depends(require_session)):
    return {"queue": sess.agent_state.get("queue", [])}


# ── Run ────────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_agent(req: RunRequest, session_id: str = Depends(require_session_id)):
    sess = get_session(session_id)
    queue = sess.agent_state.get("queue", [])
    pending = [(i, item) for i, item in enumerate(queue) if item["status"] == "pending"]
    if not pending:
        raise HTTPException(status_code=400, detail="No pending URLs in queue")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"log": [], "status": "running", "task": None, "queue_snapshot": queue}

    task = asyncio.create_task(
        _run_queue(job_id, session_id, pending, req)
    )
    _jobs[job_id]["task"] = task
    return {"job_id": job_id}


async def _run_queue(
    job_id: str,
    session_id: str,
    pending: list[tuple[int, dict]],
    req: RunRequest,
):
    """Background asyncio task — processes each pending URL sequentially."""
    sess = get_session(session_id)
    log = _jobs[job_id]["log"]
    total = len(pending)

    for run_num, (i, _) in enumerate(pending, 1):
        url = sess.agent_state["queue"][i]["url"]
        sess.agent_state["queue"][i]["status"] = "running"
        log.append(f"\n{'='*60}\n>> [{run_num}/{total}] {url}\n{'='*60}")

        env = os.environ.copy()
        env["CSA_UI_MODE"]      = "true"
        env["CSA_ALL_VIDEOS"]   = "true" if req.all_videos else "false"
        env["CSA_READINGS"]     = "true" if req.readings   else "false"
        env["PYTHONUNBUFFERED"] = "1"
        if req.doc_id:
            env["CSA_DOC_ID"] = req.doc_id
        if req.model:
            env["CSA_MODEL"] = req.model
        if req.credentials_path:
            env["CSA_CREDENTIALS_PATH"] = req.credentials_path

        try:
            proc = await asyncio.create_subprocess_exec(
                str(_PYTHON), "-u", str(_AGENT_SCRIPT),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=str(_AGENT_DIR),
            )
            proc.stdin.write((url + "\n").encode())
            await proc.stdin.drain()
            proc.stdin.close()

            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace").rstrip()
                log.append(line)
                # Parse structured events and store for WS consumers
                _parse_and_store(job_id, line, run_num, total)

            await proc.wait()
            if proc.returncode == 0:
                sess.agent_state["queue"][i]["status"] = "done"
                log.append("✓ Finished successfully.")
            else:
                sess.agent_state["queue"][i]["status"] = "error"
                log.append(f"✗ Exited with code {proc.returncode}.")

        except Exception as exc:
            sess.agent_state["queue"][i]["status"] = "error"
            log.append(f"✗ Exception: {exc}")

    all_ok = all(
        sess.agent_state["queue"][i]["status"] == "done"
        for i, _ in pending
    )
    _jobs[job_id]["status"] = "done" if all_ok else "error"
    _jobs[job_id]["all_ok"] = all_ok


def _parse_and_store(job_id: str, line: str, run_num: int, total: int):
    """Parse a stdout line and append a structured event to the job's event list."""
    job = _jobs[job_id]
    job.setdefault("events", [])

    event: dict[str, Any] = {"line": line, "url_num": run_num, "total_urls": total}

    m = _ITEM_RE.search(line)
    if m:
        event.update({
            "type": "item",
            "itemType": m.group(1),            # VIDEO | READING
            "current": int(m.group(2)),
            "total": int(m.group(3)),
            "title": m.group(4).strip()[:65],
        })
    elif (m := _STAGE_RE.search(line)):
        event.update({
            "type": "stage",
            "stageNum": int(m.group(1)),
            "stageTotal": int(m.group(2)),
            "label": m.group(3).strip(),
        })
    elif (m := _DONE_RE.search(line)):
        event.update({
            "type": "done",
            "itemType": m.group(1),
            "current": int(m.group(2)),
            "total": int(m.group(3)),
        })
    elif (m := _FOUND_RE.search(line)):
        event.update({"type": "found", "count": int(m.group(1))})
    elif _ALLDONE_RE.search(line):
        event.update({"type": "alldone"})
    else:
        event["type"] = "log"
        event["text"] = line

    job["events"].append(event)


# ── Status + logs (polling fallback) ──────────────────────────────────────

@router.get("/status/{job_id}")
async def agent_status(job_id: str, session_id: str = Depends(require_session_id)):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    sess = get_session(session_id)
    queue = sess.agent_state.get("queue", [])
    return {
        "status": job["status"],
        "running": job["status"] == "running",
        "done_count": sum(1 for q in queue if q["status"] == "done"),
        "error_count": sum(1 for q in queue if q["status"] == "error"),
        "queue": queue,
        "all_ok": job.get("all_ok"),
    }


@router.get("/logs/{job_id}")
async def agent_logs(job_id: str, limit: int = 120):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"lines": _jobs[job_id]["log"][-limit:]}


# ── WebSocket stream ───────────────────────────────────────────────────────

@ws_router.websocket("/ws/agent/{job_id}")
async def agent_ws(websocket: WebSocket, job_id: str):
    """
    Stream structured events for a running (or completed) agent job.
    Sends each new event as JSON. Closes when job completes.
    """
    await websocket.accept()

    if job_id not in _jobs:
        await websocket.send_text(json.dumps({"error": "Job not found"}))
        await websocket.close()
        return

    sent_index = 0
    try:
        while True:
            job = _jobs[job_id]
            events = job.get("events", [])

            # Send any new events since last poll
            while sent_index < len(events):
                await websocket.send_text(json.dumps(events[sent_index]))
                sent_index += 1

            if job["status"] != "running":
                # Send a final event the frontend hook understands
                all_ok = job.get("all_ok", False)
                await websocket.send_text(json.dumps(
                    {"type": "alldone"} if all_ok
                    else {"type": "status", "status": "error"}
                ))
                break

            await asyncio.sleep(0.1)  # poll interval for new events

    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
