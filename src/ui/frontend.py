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
    sync_notes,
    extract_text_from_image,
    parse_multiple_choice_questions,
    format_question_for_rag,
    extract_answer_letter,
    run_agent_subprocess,
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
    st.session_state.db = StudyDatabase()

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
    st.session_state.agent_model = os.environ.get("CSA_MODEL", "granite3.2:8b")

if "agent_sync_prompt" not in st.session_state:
    st.session_state.agent_sync_prompt = False  # show sync prompt after successful run

if "agent_progress_items" not in st.session_state:
    st.session_state.agent_progress_items = []  # completed item records from last run


# ── Helpers ───────────────────────────────────────────────────────────────────
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

    correction_text = (
        f"Quiz Correction:\nQuestion: {question_data['text']}\n\n"
        f"Correct Answer: {correct_answer}) {opts.get(correct_answer, 'Unknown')}\n\n"
        f"Note: Previously answered incorrectly as {question_data.get('ai_answer', 'Unknown')}. "
        f"The correct answer is {correct_answer}."
    )
    return {
        "tab": "Quiz Corrections",
        "title": f"Correction - Q{question_num}",
        "content": correction_text,
        "sections": {"summary": correction_text},
    }


def process_quiz_image(image_file):
    """Run OCR + RAG on an image and return (response_text, questions_list)."""
    extracted_text = extract_text_from_image(image_file)
    questions = parse_multiple_choice_questions(extracted_text)

    if not questions:
        debug = extracted_text[:500] if extracted_text else "(nothing)"
        return (
            f"Could not detect multiple choice questions.\n\n"
            f"**Debug — extracted text:**\n```\n{debug}...\n```\n\n"
            "*Tip: questions should be numbered (1. 2.) and options labelled A) B) C) D)*",
            [],
        )

    parts = []
    for q in questions:
        query = format_question_for_rag(q)
        answer = answer_question(st.session_state.db, query)
        letter = extract_answer_letter(answer)
        q["ai_answer"] = letter or "Unknown"

        parts.append(f"\n### Question {q['number']}: {q['text']}\n")
        for opt in q.get("options", []):
            marker = ">" if opt["letter"] == letter else " "
            parts.append(f"{marker} **{opt['letter']}**) {opt['text']}")
        parts.append(f"\n**Answer: {letter or '?'}**\n")
        parts.append(f"<details><summary>Explanation</summary>\n\n{answer}\n\n</details>\n")

    response = "\n".join(parts)
    response += "\n\n**Found an error?** Tell me in chat: *'Question 2 was wrong, answer is C'*"
    return response, questions


# ── Main tabs ─────────────────────────────────────────────────────────────────
tab_study, tab_agent, tab_kb = st.tabs(["Study Assistant", "Coursera Agent", "Expand Knowledge Base"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — STUDY ASSISTANT
# ════════════════════════════════════════════════════════════════════════════
with tab_study:
    # Render existing chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

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

    # ── Chat input ────────────────────────────────────────────────────────
    if prompt := st.chat_input("Ask a question about your course…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        q_num, correct_ans = parse_correction_message(prompt)
        if q_num and correct_ans and st.session_state.last_quiz:
            with st.chat_message("assistant"):
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
                st.markdown(response)
        else:
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    response = answer_question(st.session_state.db, prompt)
                st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})


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
        _STATUS_ICON = {"pending": "[ ]", "running": "[...]", "done": "[done]", "error": "[err]"}
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

    # ── Live status display ───────────────────────────────────────────────
    status_placeholder  = st.empty()   # friendly stage card
    progress_placeholder = st.empty()  # progress bar
    log_placeholder     = st.empty()   # scrolling raw log

    # Patterns to extract stage info from agent stdout (emoji chars used only for matching)
    import re as _re
    _ITEM_RE    = _re.compile(r'[\U0001f4f9\U0001f4d6]\s*(VIDEO|READING)\s*(\d+)/(\d+):\s*(.+)')
    _STAGE_RE   = _re.compile(r'[\U0001f4fa\U0001f916\U0001f4be\U0001f4d6]\s*(\d+/[34])\s+(.+)')
    _DONE_RE    = _re.compile(r'\u2713 Completed (video|reading) (\d+)/(\d+)')
    _FOUND_RE   = _re.compile(r'Found (\d+) course items')
    _CHROME_RE  = _re.compile(r'Connected to Chrome|Connecting to Chrome')
    _NAV_RE     = _re.compile(r'\U0001f4f1\s*https://')
    _OLLAMA_RE  = _re.compile(r'\U0001f50d Ollama')
    _ALLDONE_RE = _re.compile(r'\U0001f38a ALL ITEMS COMPLETE')

    def _parse_stage(line: str) -> str | None:
        """Return a clean one-liner for notable agent output lines, or None."""
        if _ALLDONE_RE.search(line):  return "All items complete."
        m = _ITEM_RE.search(line)
        if m:  return f"Item {m.group(2)}/{m.group(3)}: {m.group(4).strip()}"
        m = _DONE_RE.search(line)
        if m:  return f"{m.group(1).capitalize()} {m.group(2)}/{m.group(3)} done."
        m = _STAGE_RE.search(line)
        if m:  return f"Stage {m.group(1)} — {m.group(2).strip()}"
        m = _FOUND_RE.search(line)
        if m:  return f"Found {m.group(1)} items in module."
        if _CHROME_RE.search(line): return "Chrome connected."
        if _NAV_RE.search(line):    return "Navigated to lecture page."
        if _OLLAMA_RE.search(line): return "Checking Ollama model..."
        return None

    # ── Post-run sync prompt (shown only when all URLs completed successfully) ──
    if st.session_state.get("agent_sync_prompt") and not st.session_state.agent_running:
        st.success("All links processed successfully.")
        c_sync, c_skip = st.columns(2)
        if c_sync.button("Sync notes to study database", type="primary", use_container_width=True, key="post_sync_btn"):
            st.session_state.agent_sync_prompt = False
            with st.spinner("Syncing from Google Doc..."):
                try:
                    sync_notes(st.session_state.db)
                    st.success("Sync complete. Study Assistant is up to date.")
                except Exception as _e:
                    st.error(f"Sync failed: {_e}")
            st.rerun()
        if c_skip.button("Skip for now", use_container_width=True, key="post_sync_skip_btn"):
            st.session_state.agent_sync_prompt = False
            st.rerun()

    # Restore log from last run
    if st.session_state.agent_log_lines and not st.session_state.agent_running:
        log_placeholder.code(
            "\n".join(st.session_state.agent_log_lines[-80:]), language="bash"
        )
        if st.button("Clear log", key="clear_log_btn"):
            st.session_state.agent_log_lines = []
            st.rerun()

    # ── Main blocking processing loop ─────────────────────────────────────
    if start_processing and pending_urls:
        st.session_state.agent_running = True
        total = len(pending_urls)
        all_log = list(st.session_state.agent_log_lines)
        current_stage = "Starting…"

        for run_num, (i, _) in enumerate(pending_urls, 1):
            url = st.session_state.agent_queue[i]["url"]
            st.session_state.agent_queue[i]["status"] = "running"

            url_short = url.split("/")[-1].replace("-", " ")[:60] or url[:60]
            progress_placeholder.progress(
                (run_num - 1) / total,
                text=f"URL {run_num}/{total}",
            )
            status_placeholder.info(f"[{run_num}/{total}] Starting: {url_short}...")

            sep = "=" * 60
            all_log += [f"\n{sep}", f">> [{run_num}/{total}] {url}", sep]
            log_placeholder.code("\n".join(all_log[-80:]), language="bash")

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
                    friendly = _parse_stage(stripped)
                    if friendly:
                        current_stage = friendly
                        status_placeholder.info(f"[{run_num}/{total}] {current_stage}")
                    log_placeholder.code("\n".join(all_log[-80:]), language="bash")
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

            log_placeholder.code("\n".join(all_log[-80:]), language="bash")

        all_ok = all(
            st.session_state.agent_queue[i]["status"] == "done"
            for i, _ in pending_urls
        )
        progress_placeholder.progress(
            1.0,
            text=f"All {total} URL{'s' if total != 1 else ''} processed.",
        )
        status_placeholder.success("Done. Notes saved to Google Doc.")
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
                sync_notes(st.session_state.db)
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

    st.text_input(
        "Google Doc ID",
        key="agent_doc_id",
        placeholder="aBcDeFgHiJkLmNoPqRsTuVwXyZ1234",
        disabled=st.session_state.agent_running,
        help="From your Google Doc URL: docs.google.com/document/d/<DOC_ID>/edit",
    )
    st.text_input(
        "Ollama model",
        key="agent_model",
        placeholder="granite3.2:8b",
        disabled=st.session_state.agent_running,
        help="Model tag for note generation.",
    )

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