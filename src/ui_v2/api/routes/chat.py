# src/ui_v2/api/routes/chat.py
"""
Chat routes — Q&A, quiz extraction, per-answer SSE streaming, corrections.
"""
from __future__ import annotations

import io
import json
import re
import asyncio
import base64
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── path for data files ───────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent

import backend  # noqa: E402 — sets up study_system path too
from backend import (
    answer_question,
    extract_text_from_image,
    parse_multiple_choice_questions,
    format_question_for_rag,
    extract_answer_letter,
    extract_answer_letters,
    extract_questions_with_vision_model,
)
from src.ui_v2.api.session import (  # noqa: E402
    SessionData,
    require_session,
    require_session_id,
    get_session_db,
    get_session,
)

router = APIRouter()

# ── Correction regex (mirrors frontend v1 parse_correction_message) ────────
_CORRECTION_RE = [
    re.compile(r'(?:question|q)\s*[#]?\s*(\d+).+?(?:answer\s*(?:is|:|=)?\s*)?([a-d])(?:[\)\.]|\s|$)', re.I),
    re.compile(r'[#]?\s*(\d+)\s*(?:is|was)?\s*(?:wrong|incorrect|false).+?([a-d])(?:[\)\.]|\s|$)', re.I),
    re.compile(r'(?:fix|correct)\s*(?:question|q)?\s*[#]?\s*(\d+).+?([a-d])(?:[\)\.]|\s|$)', re.I),
]


def _parse_correction(msg: str) -> tuple[int | None, str | None]:
    for pat in _CORRECTION_RE:
        m = pat.search(msg)
        if m:
            return int(m.group(1)), m.group(2).upper()
    return None, None


# ── Pydantic models ────────────────────────────────────────────────────────

class AnswerRequest(BaseModel):
    query: str
    model: str = ""
    doc_id: str = ""


class AnswerStreamRequest(BaseModel):
    model: str = ""
    doc_id: str = ""


class CorrectRequest(BaseModel):
    question_num: int
    correct_answer: str


class Base64ImageRequest(BaseModel):
    data: str          # raw base64 or "data:image/...;base64,..." URI
    vision_model: str = ""
    model: str = ""
    doc_id: str = ""


# ── GET /history ───────────────────────────────────────────────────────────

@router.get("/history")
async def get_history(sess: SessionData = Depends(require_session)):
    return {"messages": sess.messages}


# ── DELETE /history ────────────────────────────────────────────────────────

@router.delete("/history")
async def clear_history(sess: SessionData = Depends(require_session)):
    sess.messages = []
    return {"status": "cleared"}


# ── POST /answer ───────────────────────────────────────────────────────────

@router.post("/answer")
async def answer(req: AnswerRequest, session_id: str = Depends(require_session_id)):
    sess = get_session(session_id)

    # Update doc_id if provided
    if req.doc_id:
        sess.agent_doc_id = req.doc_id
    db = get_session_db(session_id)

    # Check for correction pattern first
    q_num, correct_ans = _parse_correction(req.query)
    if q_num and correct_ans and sess.last_quiz:
        questions = sess.last_quiz.get("questions", [])
        if 1 <= q_num <= len(questions):
            # Return structured correction signal — caller handles save
            return {
                "type": "correction",
                "question_num": q_num,
                "correct_answer": correct_ans,
                "question_data": questions[q_num - 1],
            }

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: answer_question(db, req.query, model=req.model, doc_id=req.doc_id),
    )
    return {"type": "answer", "answer": response}


# ── POST /correct ──────────────────────────────────────────────────────────

@router.post("/correct")
async def save_correction(
    req: CorrectRequest,
    session_id: str = Depends(require_session_id),
):
    sess = get_session(session_id)
    db = get_session_db(session_id)

    if not sess.last_quiz:
        raise HTTPException(status_code=400, detail="No quiz in session to correct")

    questions = sess.last_quiz.get("questions", [])
    if not (1 <= req.question_num <= len(questions)):
        raise HTTPException(status_code=400, detail=f"Question {req.question_num} not found")

    q_data = questions[req.question_num - 1]
    opts = {o["letter"]: o["text"] for o in q_data.get("options", [])}

    # Persist to quiz_feedback.json
    feedback_file = _REPO_ROOT / "src" / "study_system" / "study_data" / "quiz_feedback.json"
    feedback_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(feedback_file.read_text()) if feedback_file.exists() else {"corrections": []}
    except Exception:
        data = {"corrections": []}

    data["corrections"].append({
        "timestamp": datetime.now().isoformat(),
        "question_number": req.question_num,
        "question_text": q_data["text"],
        "options": opts,
        "ai_answer": q_data.get("ai_answer", "Unknown"),
        "correct_answer": req.correct_answer,
        "correct_option_text": opts.get(req.correct_answer, "Unknown"),
    })
    feedback_file.write_text(json.dumps(data, indent=2))

    # Add correction lecture to KB
    _opts_lines = "\n".join(f"{k}) {v}" for k, v in opts.items())
    _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    correction_text = (
        f"Quiz Correction:\nQuestion: {q_data['text']}\n\nOptions:\n{_opts_lines}\n\n"
        f"Correct Answer: {req.correct_answer}) {opts.get(req.correct_answer, 'Unknown')}\n\n"
        f"All other options are incorrect. "
        f"Note: Previously answered incorrectly as {q_data.get('ai_answer', 'Unknown')}. "
        f"The correct answer is {req.correct_answer}."
    )
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: db.add_lectures([{
        "tab": "Quiz Corrections",
        "title": f"Correction - Q{req.question_num} ({_ts})",
        "content": correction_text,
        "sections": {"summary": correction_text},
    }]))

    return {
        "message": (
            f"Correction saved — Q{req.question_num} answer is "
            f"{req.correct_answer}) {opts.get(req.correct_answer, 'Unknown')}"
        )
    }


# ── POST /extract-quiz — multipart upload ────────────────────────────────

@router.post("/extract-quiz")
async def extract_quiz(
    file: UploadFile = File(...),
    vision_model: str = Form(""),
    session_id: str = Depends(require_session_id),
):
    image_bytes = await file.read()
    return await _run_extraction(session_id, io.BytesIO(image_bytes), vision_model)


# ── POST /extract-quiz-b64 — base64 body (clipboard paste path) ──────────

@router.post("/extract-quiz-b64")
async def extract_quiz_b64(req: Base64ImageRequest, session_id: str = Depends(require_session_id)):
    raw = req.data
    if "," in raw:                        # strip data URI prefix
        raw = raw.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image data")
    return await _run_extraction(session_id, io.BytesIO(image_bytes), req.vision_model)


async def _run_extraction(session_id: str, image_file: io.BytesIO, vision_model: str) -> dict:
    loop = asyncio.get_event_loop()
    vm = None if vision_model in ("", "Auto-detect") else vision_model

    questions = await loop.run_in_executor(
        None,
        lambda: extract_questions_with_vision_model(image_file, model=vm),
    )
    extraction_method = "vision model"

    if not questions:
        extraction_method = "OCR fallback"
        image_file.seek(0)
        text = await loop.run_in_executor(None, lambda: extract_text_from_image(image_file))
        questions = await loop.run_in_executor(None, lambda: parse_multiple_choice_questions(text))

    if not questions:
        raise HTTPException(status_code=422, detail="No multiple-choice questions detected in image")

    # Store in session for answer-stream and correction
    sess = get_session(session_id)
    sess.last_quiz = {"questions": questions}

    return {"questions": questions, "extraction_method": extraction_method}


# ── POST /answer-stream — SSE, one event per question ────────────────────
# NOTE: uses answer_question() N times sequentially — intentionally does NOT
# use answer_questions_batch(), which would return all answers at once and
# defeat the streaming UX.

@router.post("/answer-stream")
async def answer_stream(
    req: AnswerStreamRequest,
    session_id: str = Depends(require_session_id),
):
    sess = get_session(session_id)
    if req.doc_id:
        sess.agent_doc_id = req.doc_id
    db = get_session_db(session_id)

    if not sess.last_quiz:
        raise HTTPException(status_code=400, detail="No quiz in session — extract a quiz image first")

    questions = sess.last_quiz["questions"]
    model = req.model
    doc_id = req.doc_id
    loop = asyncio.get_event_loop()

    async def event_generator():
        for i, q in enumerate(questions):
            query = format_question_for_rag(q)
            options = [o["text"] for o in q.get("options", [])]
            answer = await loop.run_in_executor(
                None,
                lambda q=q, query=query, options=options: answer_question(
                    db, query, model=model, doc_id=doc_id, options=options
                ),
            )
            is_multi = q.get("type", "single") == "multi"
            if is_multi:
                letters = extract_answer_letters(answer)
                q["ai_answer"] = ", ".join(letters) if letters else "Unknown"
            else:
                letter = extract_answer_letter(answer)
                q["ai_answer"] = letter or "Unknown"

            payload = json.dumps({
                "index": i,
                "answer": answer,
                "question": q,
            })
            yield f"data: {payload}\n\n"

        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
