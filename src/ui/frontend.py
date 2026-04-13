# src/ui/frontend.py
"""
Unified frontend: Study Assistant + Coursera Agent.
Entry point: streamlit run src/ui/frontend.py  (from repo root)
"""
import os
import re
import io
import json
import base64
import sys
from datetime import datetime
from pathlib import Path

# Ensure repo root and src/ui are on sys.path regardless of how Streamlit was launched
_UI_DIR = Path(__file__).parent
_REPO_ROOT = _UI_DIR.parent.parent
for _p in [str(_REPO_ROOT), str(_UI_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st

from backend import (
    StudyDatabase,
    answer_question,
    answer_questions_batch,
    generate_textbook_notes,
    write_to_google_doc,
    sync_notes,
    extract_text_from_image,
    parse_multiple_choice_questions,
    format_question_for_rag,
    extract_answer_letter,
    extract_answer_letters,
    run_agent_subprocess,
    list_ollama_models,
    list_vision_models,
    load_docs,
    save_docs,
    load_prefs,
    save_prefs,
    get_service_account_email,
    detect_vision_model,
    extract_questions_with_vision_model,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Coursera Study Assistant", layout="wide")

# ── Global font override ──────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap');
/* Target text elements only — never icon/glyph containers */
html, body,
p, span:not(.material-icons):not(.material-icons-sharp):not([data-testid="stIconMaterial"]),
div[data-testid="stMarkdownContainer"],
div[data-testid="stText"],
label, .stTextInput input, .stTextArea textarea,
button[kind], .stButton > button,
.stTab > button, .stTabs [role="tab"],
.stSidebar, .stSidebar label,
h1, h2, h3, h4, h5, h6,
code, pre, .stCodeBlock {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
}
h1, h2, h3 { font-weight: 700 !important; }
</style>
""", unsafe_allow_html=True)

st.title("Coursera Study Assistant")

# ── Shared session state ──────────────────────────────────────────────────────
if "db" not in st.session_state:
    st.session_state.db = StudyDatabase(doc_id=st.session_state.get("agent_doc_id", ""))
    st.session_state.db_doc_id = st.session_state.get("agent_doc_id", "")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "last_quiz" not in st.session_state:
    st.session_state.last_quiz = None

# Agent tab state
if "agent_queue" not in st.session_state:
    st.session_state.agent_queue = []          # list of {url, status}

if "agent_url_counter" not in st.session_state:
    st.session_state.agent_url_counter = 0     # forces input widget re-creation on clear

if "agent_log_lines" not in st.session_state:
    st.session_state.agent_log_lines = []

if "agent_running" not in st.session_state:
    st.session_state.agent_running = False

if "agent_doc_id" not in st.session_state:
    # Seed from .env / environment so user doesn't have to re-enter it
    st.session_state.agent_doc_id = os.environ.get("CSA_DOC_ID", "")

if "agent_model" not in st.session_state:
    _prefs = load_prefs()
    st.session_state.agent_model = (
        _prefs.get("agent_model")
        or os.environ.get("CSA_MODEL", "granite3.2:8b")
    )

if "vision_model" not in st.session_state:
    _prefs = load_prefs()
    st.session_state.vision_model = _prefs.get("vision_model", "Auto-detect")

if "agent_sync_prompt" not in st.session_state:
    st.session_state.agent_sync_prompt = False  # show sync prompt after successful run

if "agent_progress_items" not in st.session_state:
    st.session_state.agent_progress_items = []  # completed item records from last run

if "tb_notes_mode" not in st.session_state:
    st.session_state.tb_notes_mode = False   # True = Textbook Notes mode active

if "pending_notes" not in st.session_state:
    st.session_state.pending_notes = None    # generated notes awaiting user confirmation


# ── Helpers ───────────────────────────────────────────────────────────────────

_TEXTBOOKS_FILE = Path(__file__).parent.parent.parent / "textbooks.json"
try:
    with open(_TEXTBOOKS_FILE) as _f:
        _TEXTBOOKS = json.load(_f).get("textbooks", [])
except Exception:
    _TEXTBOOKS = []


def _find_textbook_for_doc(doc_id: str) -> dict | None:
    """Return the textbooks.json entry whose doc_ids list contains doc_id, or None."""
    for tb in _TEXTBOOKS:
        if doc_id and doc_id in tb.get("doc_ids", []):
            return tb
    return None


@st.dialog("Google Doc")
def doc_modal(mode: str, existing: dict | None = None):
    """Add or edit a saved Google Doc entry."""
    _sa_email = get_service_account_email()
    if _sa_email:
        st.warning(
            f"Make sure to add the service account as an **Editor** in Google Drive:\n\n"
            f"`{_sa_email}`",
            icon="⚠️",
        )

    _default_name = existing["name"] if existing else ""
    _default_id   = existing["id"]   if existing else ""

    _name = st.text_input("Friendly name", value=_default_name, placeholder="e.g. CU - MSDS - Prereqs")
    _id   = st.text_input(
        "Google Doc ID",
        value=_default_id,
        placeholder="aBcDeFgHiJkLmNoPqRsTuVwXyZ1234",
        help="Found in your Doc URL: docs.google.com/document/d/**<DOC_ID>**/edit",
    )

    _col_save, _col_delete = st.columns([3, 1]) if mode == "edit" else (st, None)

    with _col_save:
        if st.button("Save", type="primary", use_container_width=True):
            _id = _id.strip()
            _name = _name.strip()
            if not _id:
                st.error("Doc ID is required.")
                st.stop()
            _docs = load_docs()
            # Upsert: replace existing entry with same id, or append
            _docs = [d for d in _docs if d["id"] != _id]
            _docs.append({"id": _id, "name": _name or _id})
            save_docs(_docs)
            st.session_state.agent_doc_id = _id
            st.rerun()

    if mode == "edit" and _col_delete:
        with _col_delete:
            if st.button("Delete", type="secondary", use_container_width=True):
                _docs = load_docs()
                _docs = [d for d in _docs if d["id"] != _default_id]
                save_docs(_docs)
                if st.session_state.get("agent_doc_id") == _default_id:
                    st.session_state.agent_doc_id = ""
                st.rerun()


def parse_correction_message(message: str):
    """Return (question_num, correct_answer) or (None, None)."""
    msg = message.lower().strip()
    m = re.search(r'(?:question|q)\s*[#]?\s*(\d+).+?(?:answer\s*(?:is|:|=)?\s*)?([a-d])(?:[\)\.]|\s|$)', msg)
    if m:
        return int(m.group(1)), m.group(2).upper()
    m = re.search(r'[#]?\s*(\d+)\s*(?:is|was)?\s*(?:wrong|incorrect|false).+?([a-d])(?:[\)\.]|\s|$)', msg)
    if m:
        return int(m.group(1)), m.group(2).upper()
    m = re.search(r'(?:fix|correct)\s*(?:question|q)?\s*[#]?\s*(\d+).+?([a-d])(?:[\)\.]|\s|$)', msg)
    if m:
        return int(m.group(1)), m.group(2).upper()
    return None, None


def save_quiz_feedback(question_num: int, correct_answer: str, question_data: dict):
    """Persist a correction and build a correction lecture for the KB."""
    from pathlib import Path
    feedback_file = Path(__file__).parent.parent / "study_system" / "study_data" / "quiz_feedback.json"
    feedback_file.parent.mkdir(parents=True, exist_ok=True)

    if feedback_file.exists():
        with open(feedback_file) as f:
            data = json.load(f)
    else:
        data = {"corrections": []}

    opts = {o["letter"]: o["text"] for o in question_data.get("options", [])}
    data["corrections"].append({
        "timestamp": datetime.now().isoformat(),
        "question_number": question_num,
        "question_text": question_data["text"],
        "options": opts,
        "ai_answer": question_data.get("ai_answer", "Unknown"),
        "correct_answer": correct_answer,
        "correct_option_text": opts.get(correct_answer, "Unknown"),
    })
    with open(feedback_file, "w") as f:
        json.dump(data, f, indent=2)

    _opts_lines = "\n".join(f"{k}) {v}" for k, v in opts.items())
    _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    correction_text = (
        f"Quiz Correction:\nQuestion: {question_data['text']}\n\n"
        f"Options:\n{_opts_lines}\n\n"
        f"Correct Answer: {correct_answer}) {opts.get(correct_answer, 'Unknown')}\n\n"
        f"All other options are incorrect. "
        f"Note: Previously answered incorrectly as {question_data.get('ai_answer', 'Unknown')}. "
        f"The correct answer is {correct_answer}."
    )
    return {
        "tab": "Quiz Corrections",
        "title": f"Correction - Q{question_num} ({_ts})",
        "content": correction_text,
        "sections": {"summary": correction_text},
    }


def process_quiz_image(image_file):
    """Extract questions from a quiz screenshot and answer via RAG.

    Extraction priority:
      1. Ollama vision model (minicpm-v or any detected multimodal model)
      2. Apple Vision OCR + regex parser (fallback)
    """
    # ── Step 1: extract questions ─────────────────────────────────────────
    extraction_method = "vision model"
    _vm_choice = st.session_state.get("vision_model", "Auto-detect")
    _vm = None if (_vm_choice in (None, "Auto-detect")) else _vm_choice
    questions = extract_questions_with_vision_model(image_file, model=_vm)

    if not questions:
        extraction_method = "OCR fallback"
        extracted_text = extract_text_from_image(image_file)
        questions = parse_multiple_choice_questions(extracted_text)

    if not questions:
        debug = locals().get("extracted_text", "")[:500] or "(vision model returned nothing)"
        return (
            f"Could not detect multiple choice questions.\n\n"
            f"**Debug — extracted text:**\n```\n{debug}...\n```\n\n"
            "*Tip: questions should be numbered (1. 2.) and options labelled A) B) C) D)*",
            [],
        )

    # ── Step 2: answer all questions in one batch call ──────────────────
    parts = [f"*Extracted via {extraction_method}*\n"]
    _model = st.session_state.get("agent_model", "")
    _doc_id = st.session_state.get("agent_doc_id", "")
    batch_answers = answer_questions_batch(
        st.session_state.db, questions, model=_model, doc_id=_doc_id
    )

    for i, q in enumerate(questions):
        is_multi = q.get("type", "single") == "multi"

        if batch_answers and i < len(batch_answers):
            answer = batch_answers[i]
        else:
            query = format_question_for_rag(q)
            answer = answer_question(
                st.session_state.db, query, model=_model, doc_id=_doc_id,
                options=[o["text"] for o in q.get("options", [])],
            )

        if is_multi:
            letters = extract_answer_letters(answer)
            q["ai_answer"] = ", ".join(letters) if letters else "Unknown"
            answer_label = f"**Answers: {q['ai_answer']}**"
        else:
            letter = extract_answer_letter(answer)
            q["ai_answer"] = letter or "Unknown"
            answer_label = f"**Answer: {letter or '?'}**"
            letters = [letter] if letter else []

        parts.append(f"\n### Question {q['number']}: {q['text']}\n")
        if is_multi:
            parts.append("*Select all that apply*\n")
        option_lines = []
        for opt in q.get("options", []):
            icon = "✅" if opt["letter"] in letters else "⬜"
            option_lines.append(f"- {icon} **{opt['letter']}**) {opt['text']}")
        parts.append("\n".join(option_lines))
        parts.append(f"\n{answer_label}\n")
        parts.append(f"<details><summary>Explanation</summary>\n\n{answer}\n\n</details>\n")

    response = "\n".join(parts)
    response += "\n\n**Found an error?** Tell me in chat: *'Question 1 answer should be A, C, E'*"
    return response, questions


# ── Main tabs ─────────────────────────────────────────────────────────────────
tab_study, tab_agent, tab_kb = st.tabs(["Study Assistant", "Coursera Agent", "Expand Knowledge Base"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — STUDY ASSISTANT
# ════════════════════════════════════════════════════════════════════════════
with tab_study:
    # Render existing chat history in a fixed-height scrollable container
    with st.container(height=450, border=False):
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"], unsafe_allow_html=True)

    # ── Quiz image upload area ────────────────────────────────────────────
    st.markdown("---")
    upload_tab, paste_tab = st.tabs(["Upload Screenshot", "Paste from Clipboard"])

    with upload_tab:
        quiz_image = st.file_uploader(
            "Drag & drop quiz screenshot", type=["png", "jpg", "jpeg"],
            key="quiz_upload", label_visibility="collapsed"
        )
        if quiz_image and st.button("Extract & Answer", key="upload_btn"):
            st.session_state.messages.append({"role": "user", "content": "*Uploaded quiz screenshot*"})
            with st.spinner("Extracting questions..."):
                response, questions = process_quiz_image(quiz_image)
            if questions:
                st.session_state.last_quiz = {"questions": questions, "raw_text": ""}
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()

    with paste_tab:
        st.caption("Quick Clipboard Paste:")
        st.code("python src/study_system/clipboard_to_base64.py", language="bash")
        st.caption("1. Take screenshot (Cmd+Shift+Ctrl+4)  2. Run command above  3. Paste output below")
        pasted_data = st.text_area(
            "Paste base64 image data", height=120,
            placeholder="Paste the base64 string from clipboard_to_base64.py…",
            key="paste_area", label_visibility="collapsed",
        )
        if st.button("Extract & Answer", key="paste_btn") and pasted_data:
            try:
                raw = pasted_data.split(",")[1] if pasted_data.startswith("data:image") else pasted_data
                image_file = io.BytesIO(base64.b64decode(raw))
                st.session_state.messages.append({"role": "user", "content": "*Pasted quiz screenshot*"})
                with st.spinner("Extracting questions..."):
                    response, questions = process_quiz_image(image_file)
                if questions:
                    st.session_state.last_quiz = {"questions": questions, "raw_text": ""}
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()
            except Exception as e:
                st.error(f"Error processing pasted data: {e}")
                st.info("Try the Upload File tab instead.")

    # ── Mode switcher + chat input ────────────────────────────────────────
    _mode_col, _input_col = st.columns([1, 5])
    with _mode_col:
        _tb_mode = st.toggle(
            "📖 Textbook Notes",
            value=st.session_state.tb_notes_mode,
            key="tb_mode_toggle",
            help="Switch to Textbook Notes mode to generate and write chapter notes to your Google Doc.",
        )
        if _tb_mode != st.session_state.tb_notes_mode:
            st.session_state.tb_notes_mode = _tb_mode
            st.session_state.pending_notes = None
            st.rerun()

    with _input_col:
        _placeholder = (
            "Describe the chapter or topic (e.g. 'Chapter 10: Elementary Data Structures')…"
            if st.session_state.tb_notes_mode
            else "Ask a question about your course…"
        )
        prompt = st.chat_input(_placeholder)

    # ── Pending notes confirmation banner ─────────────────────────────────
    if st.session_state.pending_notes:
        st.info(
            "📋 **Notes are ready above.** Review them, then choose:",
            icon="📖",
        )
        _w_col, _d_col = st.columns(2)
        with _w_col:
            if st.button("✅ Write to Google Doc", use_container_width=True, key="tb_write_btn"):
                _doc_id = st.session_state.get("agent_doc_id", "")
                _creds = os.environ.get("CSA_CREDENTIALS_PATH", "")
                try:
                    with st.spinner("Writing to Google Doc…"):
                        _tab_name = write_to_google_doc(_doc_id, st.session_state.pending_notes, _creds)
                    with st.spinner("Resyncing knowledge base…"):
                        sync_notes(st.session_state.db, doc_id=_doc_id)
                    _msg = (
                        f"✅ **Notes written to tab '{_tab_name}'** and knowledge base resynced.\n\n"
                        f"You can manage the notes directly in your Google Doc."
                    )
                except Exception as _e:
                    _msg = f"❌ Write failed: {_e}"
                st.session_state.pending_notes = None
                st.session_state.messages.append({"role": "assistant", "content": _msg})
                st.rerun()
        with _d_col:
            if st.button("❌ Discard", use_container_width=True, key="tb_discard_btn"):
                st.session_state.pending_notes = None
                st.session_state.messages.append({"role": "assistant", "content": "Notes discarded."})
                st.rerun()

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})

        # ── Textbook Notes mode ───────────────────────────────────────────
        if st.session_state.tb_notes_mode:
            _doc_id = st.session_state.get("agent_doc_id", "")
            _tb = _find_textbook_for_doc(_doc_id)
            if not _tb:
                response = (
                    "⚠️ **No textbook is associated with the active Google Doc.**\n\n"
                    "Add the doc's ID to a textbook entry in `textbooks.json` and restart."
                )
            else:
                with st.spinner(f"Generating notes from *{_tb['full_title']}*…"):
                    notes = generate_textbook_notes(
                        topic=prompt,
                        textbook=_tb,
                        model=st.session_state.get("agent_model", ""),
                    )
                st.session_state.pending_notes = notes
                response = (
                    f"📖 **Textbook: {_tb['full_title']}**\n\n"
                    f"Here are the generated notes — please review carefully:\n\n"
                    f"---\n\n```\n{notes}\n```\n\n"
                    f"---\n\n"
                    f"*Use the **Write to Google Doc** / **Discard** buttons below to proceed.*"
                )

        # ── Study mode (normal Q&A + correction handling) ─────────────────
        else:
            q_num, correct_ans = parse_correction_message(prompt)
            if q_num and correct_ans and st.session_state.last_quiz:
                quiz_qs = st.session_state.last_quiz["questions"]
                if 1 <= q_num <= len(quiz_qs):
                    q_data = quiz_qs[q_num - 1]
                    lecture = save_quiz_feedback(q_num, correct_ans, q_data)
                    st.session_state.db.add_lectures([lecture])
                    opts = {o["letter"]: o["text"] for o in q_data.get("options", [])}
                    response = (
                        f"**Correction saved!**\n\n"
                        f"**Question {q_num}:** {q_data['text']}\n\n"
                        f"**Correct Answer:** {correct_ans}) {opts.get(correct_ans, '')}\n\n"
                        "Added to knowledge base to improve future answers."
                    )
                else:
                    response = (
                        f"Question {q_num} not found — the last quiz had "
                        f"{len(quiz_qs)} question(s)."
                    )
            else:
                with st.spinner("Thinking..."):
                    response = answer_question(st.session_state.db, prompt, model=st.session_state.get("agent_model", ""), doc_id=st.session_state.get("agent_doc_id", ""))

        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — EXPAND KNOWLEDGE BASE
# ════════════════════════════════════════════════════════════════════════════
with tab_kb:
    st.subheader("Expand Knowledge Base")
    st.caption(
        "Add supplementary material — paste text or upload a file. "
        "Everything added here becomes searchable by the Study Assistant."
    )
    st.markdown("---")

    kb_source = st.selectbox(
        "Source type",
        ["Paste content", "Upload document"],
        key="kb_source_type",
        label_visibility="collapsed",
    )

    kb_entry_title = st.text_input(
        "Title",
        placeholder="e.g., Transfer Learning Tips",
        key="kb_entry_title",
    )

    if kb_source == "Paste content":
        kb_text = st.text_area("Content", height=320, key="kb_paste_text", label_visibility="collapsed",
                               placeholder="Paste your notes or course material here…")
        if st.button("Add to Knowledge Base", use_container_width=True, key="kb_paste_btn"):
            if kb_entry_title and kb_text:
                with st.spinner("Adding…"):
                    st.session_state.db.add_lectures([{
                        "tab": "Manual",
                        "title": kb_entry_title,
                        "content": kb_text,
                        "sections": {"summary": kb_text},
                    }])
                st.success(f"Added: {kb_entry_title}")
            else:
                st.error("Provide both a title and content.")
    else:
        uploaded_file = st.file_uploader(
            "File", type=["txt", "md"], key="kb_file_upload", label_visibility="collapsed"
        )
        if st.button("Add to Knowledge Base", use_container_width=True, key="kb_file_btn"):
            if kb_entry_title and uploaded_file:
                with st.spinner("Processing…"):
                    content = uploaded_file.read().decode("utf-8", errors="replace")
                    st.session_state.db.add_lectures([{
                        "tab": "Uploaded",
                        "title": kb_entry_title,
                        "content": content,
                        "sections": {"summary": content},
                    }])
                st.success(f"Added: {kb_entry_title}")
            else:
                st.error("Provide a title and select a file.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — COURSERA AGENT
# ════════════════════════════════════════════════════════════════════════════
with tab_agent:
    _agent_doc_id_display = st.session_state.get("agent_doc_id", "")
    _hdr_left, _hdr_right = st.columns([5, 1])
    with _hdr_left:
        st.subheader("Coursera Agent")
        st.caption(
            "Automates Coursera videos to Granite 3.2 notes to Google Doc. "
            "Add one or more lecture URLs to the queue then hit Process. "
            "Configure Doc ID and model in Settings (sidebar)."
        )
    with _hdr_right:
        if _agent_doc_id_display:
            st.markdown("<div style='margin-top:22px'/>" , unsafe_allow_html=True)
            st.link_button(
                "Open Google Doc",
                f"https://docs.google.com/document/d/{_agent_doc_id_display}/edit",
                use_container_width=True,
            )

    if not _agent_doc_id_display:
        st.warning(
            "No Google Doc ID set. Open the sidebar and enter it under **Agent Settings**."
        )

    st.markdown("---")

    # ── URL Queue ─────────────────────────────────────────────────────────
    _ql, _qt1, _qt2 = st.columns([3, 1, 1])
    with _ql:
        st.markdown("**URL Queue**")
    with _qt1:
        agent_all_videos = st.toggle(
            "All videos", value=True,
            key="agent_all_videos",
            disabled=st.session_state.agent_running,
            help="ON = process every remaining video in the module; OFF = current video only",
        )
    with _qt2:
        agent_readings = st.toggle(
            "Readings", value=True,
            key="agent_readings",
            disabled=st.session_state.agent_running,
            help="ON = also process Ungraded Plugin reading items",
        )

    col_input, col_add = st.columns([5, 1])
    with col_input:
        new_url = st.text_input(
            "url-input",
            placeholder="https://www.coursera.org/learn/…/lecture/…",
            key=f"agent_url_input_{st.session_state.agent_url_counter}",
            label_visibility="collapsed",
            disabled=st.session_state.agent_running,
        )
    with col_add:
        add_clicked = st.button(
            "Add", use_container_width=True, key="add_url_btn",
            disabled=st.session_state.agent_running,
        )

    if add_clicked:
        url_stripped = new_url.strip()
        if url_stripped and "coursera.org" in url_stripped:
            st.session_state.agent_queue.append({"url": url_stripped, "status": "pending"})
            st.session_state.agent_url_counter += 1   # clears the input widget
            st.rerun()
        elif url_stripped:
            st.warning("That doesn't look like a Coursera URL — check and try again.")

    # ── Queue display ─────────────────────────────────────────────────────
    if not st.session_state.agent_queue:
        st.info("Queue is empty — add at least one Coursera lecture URL above.")
    else:
        _STATUS_ICON = {"pending": "○", "running": "◉", "done": "✓", "error": "✗"}
        for i, item in enumerate(st.session_state.agent_queue):
            c_icon, c_url, c_btn = st.columns([0.04, 0.82, 0.14])
            c_icon.markdown(_STATUS_ICON.get(item["status"], "-"))
            display = item["url"] if len(item["url"]) <= 74 else item["url"][:71] + "…"
            c_url.code(display)
            if item["status"] == "pending" and not st.session_state.agent_running:
                if c_btn.button("x", key=f"rm_{i}_{st.session_state.agent_url_counter}", help="Remove"):
                    st.session_state.agent_queue.pop(i)
                    st.rerun()

    # ── Action buttons ────────────────────────────────────────────────────
    pending_urls = [
        (i, q) for i, q in enumerate(st.session_state.agent_queue)
        if q["status"] == "pending"
    ]
    col_run, col_clear = st.columns([2, 1])
    with col_run:
        start_processing = st.button(
            f"Process {len(pending_urls)} URL{'s' if len(pending_urls) != 1 else ''}",
            disabled=len(pending_urls) == 0 or st.session_state.agent_running,
            use_container_width=True, type="primary", key="process_queue_btn",
        )
    with col_clear:
        if st.button(
            "Clear queue",
            disabled=st.session_state.agent_running,
            use_container_width=True, key="clear_queue_btn",
        ):
            st.session_state.agent_queue = []
            st.rerun()

    st.markdown("---")

    # ── Progress placeholders ─────────────────────────────────────────────
    overall_bar_ph = st.empty()   # queue-level progress bar
    item_bar_ph    = st.empty()   # per-item stage progress bar
    summary_ph     = st.empty()   # post-run summary / status

    # Regex patterns for structured agent output
    import re as _re
    _ITEM_RE    = _re.compile(r'[\U0001f4f9\U0001f4d6]\s*(VIDEO|READING)\s*(\d+)/(\d+):\s*(.+)')
    _STAGE_RE   = _re.compile(r'[\U0001f4fa\U0001f916\U0001f4be\U0001f4d6]\s*(\d+)/([34])\s+(.+)')
    _DONE_RE    = _re.compile(r'\u2713 Completed (video|reading) (\d+)/(\d+)')
    _FOUND_RE   = _re.compile(r'Found (\d+) course items')
    _ALLDONE_RE = _re.compile(r'\U0001f38a ALL ITEMS COMPLETE')

    _STAGE_LABELS = {
        1: "Extracting content",
        2: "Summarising with Ollama",
        3: "Writing to Google Doc",
    }

    # ── Post-run sync prompt (shown only when all URLs completed successfully) ──
    if st.session_state.get("agent_sync_prompt") and not st.session_state.agent_running:
        st.success("All links processed successfully.")
        c_sync, c_skip = st.columns(2)
        if c_sync.button("Sync notes to study database", type="primary", use_container_width=True, key="post_sync_btn"):
            st.session_state.agent_sync_prompt = False
            with st.spinner("Syncing from Google Doc..."):
                try:
                    sync_notes(st.session_state.db, doc_id=st.session_state.get("agent_doc_id", ""))
                    st.success("Sync complete. Study Assistant is up to date.")
                except Exception as _e:
                    st.error(f"Sync failed: {_e}")
            st.rerun()
        if c_skip.button("Skip for now", use_container_width=True, key="post_sync_skip_btn"):
            st.session_state.agent_sync_prompt = False
            st.rerun()

    # ── Post-run summary & collapsed log ─────────────────────────────────
    if st.session_state.agent_log_lines and not st.session_state.agent_running:
        done_count  = sum(1 for q in st.session_state.agent_queue if q["status"] == "done")
        error_count = sum(1 for q in st.session_state.agent_queue if q["status"] == "error")
        total_ran   = done_count + error_count
        if total_ran:
            if error_count == 0:
                summary_ph.success(f"Last run: {done_count}/{total_ran} items completed successfully.")
            else:
                summary_ph.warning(f"Last run: {done_count} succeeded, {error_count} failed.")
        with st.expander("View raw log", expanded=False):
            st.code("\n".join(st.session_state.agent_log_lines[-120:]), language="bash")
            if st.button("Clear log", key="clear_log_btn"):
                st.session_state.agent_log_lines = []
                st.rerun()

    # ── Main blocking processing loop ─────────────────────────────────────
    if start_processing and pending_urls:
        st.session_state.agent_running = True
        total_urls = len(pending_urls)
        all_log = list(st.session_state.agent_log_lines)

        for run_num, (i, _) in enumerate(pending_urls, 1):
            url = st.session_state.agent_queue[i]["url"]
            st.session_state.agent_queue[i]["status"] = "running"

            overall_bar_ph.progress(
                (run_num - 1) / total_urls,
                text=f"URL {run_num} of {total_urls}",
            )
            item_bar_ph.progress(0.02, text="Connecting to Chrome…")

            all_log.append(f"\n{'='*60}\n>> [{run_num}/{total_urls}] {url}\n{'='*60}")

            # Per-item tracking state
            item_title = ""
            item_num   = 0
            item_total = 0

            try:
                proc = run_agent_subprocess(
                    url,
                    all_videos=st.session_state.get("agent_all_videos", True),
                    readings=st.session_state.get("agent_readings", True),
                    doc_id=st.session_state.get("agent_doc_id", ""),
                    model=st.session_state.get("agent_model", ""),
                    credentials_path=os.environ.get("CSA_CREDENTIALS_PATH", ""),
                )
                for line in proc.stdout:
                    stripped = line.rstrip()
                    all_log.append(stripped)

                    m = _ITEM_RE.search(stripped)
                    if m:
                        item_num   = int(m.group(2))
                        item_total = int(m.group(3))
                        item_title = m.group(4).strip()[:65]
                        item_bar_ph.progress(
                            0.05,
                            text=f"Item {item_num}/{item_total}: {item_title} — Starting…",
                        )
                        continue

                    m = _STAGE_RE.search(stripped)
                    if m:
                        stage_num = int(m.group(1))
                        stage_lbl = _STAGE_LABELS.get(stage_num, f"Stage {stage_num}")
                        # 0.3 → 0.6 → 0.9 for stages 1 / 2 / 3
                        frac  = 0.3 * stage_num
                        label = (
                            f"Item {item_num}/{item_total}: {item_title} — {stage_lbl}"
                            if item_title else stage_lbl
                        )
                        item_bar_ph.progress(min(frac, 0.95), text=label)
                        continue

                    m = _DONE_RE.search(stripped)
                    if m:
                        done_n = int(m.group(2))
                        done_t = int(m.group(3))
                        item_bar_ph.progress(
                            1.0,
                            text=f"Item {done_n}/{done_t}: {item_title} — Done ✓",
                        )
                        continue

                    m = _FOUND_RE.search(stripped)
                    if m:
                        overall_bar_ph.progress(
                            (run_num - 1) / total_urls,
                            text=f"URL {run_num} of {total_urls} — found {m.group(1)} items",
                        )

                proc.wait()

                if proc.returncode == 0:
                    st.session_state.agent_queue[i]["status"] = "done"
                    all_log.append("Finished successfully.")
                else:
                    st.session_state.agent_queue[i]["status"] = "error"
                    all_log.append(f"Exited with code {proc.returncode}.")

            except Exception as exc:
                st.session_state.agent_queue[i]["status"] = "error"
                all_log.append(f"Exception: {exc}")

        all_ok = all(
            st.session_state.agent_queue[i]["status"] == "done"
            for i, _ in pending_urls
        )
        overall_bar_ph.progress(
            1.0,
            text=f"All {total_urls} URL{'s' if total_urls != 1 else ''} processed.",
        )
        st.session_state.agent_log_lines = all_log
        st.session_state.agent_running = False
        if all_ok:
            st.session_state.agent_sync_prompt = True
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — Knowledge Base management (shared across both tabs)
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("Knowledge Base")

    _sidebar_doc_id = st.session_state.get("agent_doc_id", "")
    if _sidebar_doc_id:
        st.link_button(
            "View Notes",
            f"https://docs.google.com/document/d/{_sidebar_doc_id}/edit",
            use_container_width=True,
        )

    if st.button("Sync from Google Doc", use_container_width=True):
        with st.spinner("Syncing from Google Doc…"):
            try:
                sync_notes(st.session_state.db, doc_id=st.session_state.get("agent_doc_id", ""))
                st.success("Sync complete.")
            except Exception as e:
                st.error(f"Sync failed: {e}")

    st.divider()
    if st.button("Clear Chat History"):
        st.session_state.messages = []
        st.rerun()

    # ── Agent Settings ────────────────────────────────────────────────────
    st.divider()
    st.subheader("Agent Settings")

    _creds_path = os.environ.get("CSA_CREDENTIALS_PATH", "") or str(
        Path(__file__).parent.parent / "coursera_agent" / "credentials.json"
    )
    _creds_ok = bool(_creds_path and Path(_creds_path).exists())

    # ── Google Doc selector ───────────────────────────────────────────────
    st.caption("Google Doc")
    _saved_docs = load_docs()
    _active_id  = st.session_state.get("agent_doc_id", "")

    if _saved_docs:
        _doc_options = {d["name"] or d["id"]: d["id"] for d in _saved_docs}
        # Find index of currently active doc
        _active_name = next((d["name"] or d["id"] for d in _saved_docs if d["id"] == _active_id), None)
        _select_index = list(_doc_options.keys()).index(_active_name) if _active_name in _doc_options else 0

        _sel_col, _edit_col = st.columns([5, 1])
        with _sel_col:
            _chosen_name = st.selectbox(
                "Active doc",
                options=list(_doc_options.keys()),
                index=_select_index,
                label_visibility="collapsed",
                disabled=st.session_state.agent_running,
            )
        with _edit_col:
            if st.button("✏️", help="Edit this doc", disabled=st.session_state.agent_running):
                _chosen_entry = next((d for d in _saved_docs if (d["name"] or d["id"]) == _chosen_name), None)
                doc_modal("edit", existing=_chosen_entry)

        # Propagate selection to session state
        _chosen_id = _doc_options[_chosen_name]
        if _chosen_id != _active_id:
            st.session_state.agent_doc_id = _chosen_id
            st.rerun()
    else:
        st.info("No docs saved yet.")

    if st.button("＋ Add new doc", use_container_width=True, disabled=st.session_state.agent_running):
        doc_modal("add")

    # Re-init DB when active doc changes
    if st.session_state.get("db_doc_id") != st.session_state.get("agent_doc_id", ""):
        st.session_state.db = StudyDatabase(doc_id=st.session_state.get("agent_doc_id", ""))
        st.session_state.db_doc_id = st.session_state.get("agent_doc_id", "")

    # ── Ollama model selector ─────────────────────────────────────────────
    _available_models = list_ollama_models()
    _current_model = st.session_state.get("agent_model") or os.environ.get("CSA_MODEL", "granite3.2:8b")

    if _available_models:
        # Ensure the current model appears in the list (e.g. set via .env)
        _model_options = _available_models
        if _current_model and _current_model not in _model_options:
            _model_options = [_current_model] + _model_options
        # Seed session state so the selectbox pre-selects the right model
        if st.session_state.get("agent_model") not in _model_options:
            st.session_state["agent_model"] = _current_model
        st.selectbox(
            "Ollama model",
            options=_model_options,
            key="agent_model",          # commits to session state before next run
            disabled=st.session_state.agent_running,
            help="Models available in your local Ollama installation.",
            on_change=lambda: save_prefs({"agent_model": st.session_state.get("agent_model")}),
        )
    else:
        st.text_input(
            "Ollama model",
            key="agent_model",
            placeholder="granite3.2:8b",
            disabled=st.session_state.agent_running,
            help="Ollama not detected — enter a model tag manually.",
        )
        st.caption("⚠️ Ollama not running — start it to see available models.")

    # ── Vision model selector ─────────────────────────────────────────────
    _vision_models = list_vision_models()
    if _vision_models:
        _vision_options = ["Auto-detect"] + _vision_models
        if st.session_state.get("vision_model") not in _vision_options:
            st.session_state["vision_model"] = "Auto-detect"
        st.selectbox(
            "Vision model",
            options=_vision_options,
            key="vision_model",
            disabled=st.session_state.agent_running,
            help="Multimodal model used to read quiz screenshots. 'Auto-detect' picks the first available vision model.",
            on_change=lambda: save_prefs({"vision_model": st.session_state.get("vision_model")}),
        )
    else:
        st.caption("No vision models found — pull `llava` or `minicpm-v` for screenshot extraction.")

    st.divider()
    with st.expander("Setup & Prerequisites"):
        st.markdown(
            "**Ollama**\n"
            "- Install: [ollama.com/download](https://ollama.com/download)\n"
            "- Recommended model: `granite3.2:8b`\n"
            "- Models load from Ollama's default location. Set `OLLAMA_MODELS` in `.env` only if yours are stored elsewhere.\n\n"
            "**Chromium**\n"
            "- Required at `/Applications/Chromium.app/Contents/MacOS/Chromium`\n\n"
            "**Google credentials**\n"
            "- [Create a service account](https://cloud.google.com/iam/docs/service-accounts-create)\n"
            "- [Share your Doc with the service account as Editor](https://docs.conveyor.com/docs/sharing-files-with-your-google-drive-service-account)\n"
            "- Set `CSA_CREDENTIALS_PATH=/path/to/file.json` in `.env`, or run `./launch.sh`."
        )
        if _creds_ok:
            st.success(f"Credentials found: `{_creds_path}`")
        else:
            st.error("No credentials file found. Run `./launch.sh` to be guided through setup.")


if __name__ == "__main__":
    pass  # Streamlit entry point — run via: streamlit run src/ui/frontend.py