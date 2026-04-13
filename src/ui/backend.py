# src/ui/backend.py
"""
Backend bridge: adds study_system to sys.path then re-exports its public API.
The coursera_agent is kept separate and launched as a subprocess (it owns Chrome
and is designed to run interactively in a terminal).
"""
import json
import os
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent.parent          # coursera-study-assistant/
_STUDY_SYSTEM = _REPO_ROOT / "src" / "study_system"
_AGENT_DIR = _REPO_ROOT / "src" / "coursera_agent"

# Load .env so CSA_DOC_ID, OLLAMA_MODELS, etc. are available regardless of
# how Streamlit was launched (direct or via launch.sh)
load_dotenv(_REPO_ROOT / ".env")

for _p in [str(_STUDY_SYSTEM), str(_AGENT_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Study System public API (imported here so frontend only needs backend) ────
from study_db import StudyDatabase           # noqa: E402
from study_system import (                   # noqa: E402
    answer_question,
    answer_questions_batch,
    generate_textbook_notes,
    sync_notes,
    show_statistics,
)
from ocr_utils import (                      # noqa: E402
    extract_text_from_image,
    parse_multiple_choice_questions,
    format_question_for_display,
    format_question_for_rag,
    extract_answer_letter,
    extract_answer_letters,
    detect_vision_model,
    extract_questions_with_vision_model,
)


# ── Ollama model discovery ────────────────────────────────────────────────────
def list_ollama_models() -> list[str]:
    """
    Return a list of locally available Ollama model names.
    Returns an empty list if Ollama is not running or not installed.
    """
    try:
        import ollama
        response = ollama.list()
        # ollama.list() returns a ListResponse with a .models attribute
        models = response.models if hasattr(response, "models") else response.get("models", [])
        names = []
        for m in models:
            # Each entry has a .model attribute (e.g. "granite3.2:8b")
            name = m.model if hasattr(m, "model") else m.get("model", "")
            if name:
                names.append(name)
        return sorted(names)
    except Exception:
        return []


_VISION_TAGS = ("-v:", "-v-", "vl:", "vl-", "vision", "minicpm", "llava", "moondream", "gemma4", "gemma3")

def list_vision_models() -> list[str]:
    """
    Return locally available Ollama models that support vision/multimodal input.
    Uses the same tag heuristic as detect_vision_model().
    Returns an empty list if none are found or Ollama is not running.
    """
    return [m for m in list_ollama_models() if any(tag in m.lower() for tag in _VISION_TAGS)]


# ── Coursera Agent launcher ───────────────────────────────────────────────────
def run_agent_subprocess(
    course_url: str,
    all_videos: bool = True,
    readings: bool = True,
    doc_id: str = "",
    model: str = "",
    credentials_path: str = "",
) -> subprocess.Popen:
    """
    Launch coursera_agent.py as a subprocess, feeding the URL via stdin.
    Config flags are forwarded as CSA_* env vars read by the agent at startup.
    Returns the Popen object; iterate proc.stdout for real-time log lines.
    """
    agent_script = str(_AGENT_DIR / "coursera_agent.py")
    python = str(_REPO_ROOT / ".venv-1" / "bin" / "python3")

    env = os.environ.copy()
    env["CSA_UI_MODE"]      = "true"
    env["CSA_ALL_VIDEOS"]   = "true" if all_videos else "false"
    env["CSA_READINGS"]     = "true" if readings   else "false"
    if doc_id:
        env["CSA_DOC_ID"]          = doc_id
    if model:
        env["CSA_MODEL"]           = model
    if credentials_path:
        env["CSA_CREDENTIALS_PATH"] = credentials_path
    env["PYTHONUNBUFFERED"] = "1"   # force line-by-line stdout; critical for streaming

    proc = subprocess.Popen(
        [python, "-u", agent_script],   # -u = unbuffered I/O
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(_AGENT_DIR),
    )
    proc.stdin.write(course_url + "\n")
    proc.stdin.flush()
    proc.stdin.close()
    return proc


# ── Docs registry ─────────────────────────────────────────────────────────────
_DOCS_FILE = _REPO_ROOT / "src" / "study_system" / "study_data" / "docs.json"
_CREDS_FILE = _AGENT_DIR / "credentials.json"


def load_docs() -> list[dict]:
    """Return saved docs list [{id, name}], empty list on missing/malformed file."""
    try:
        with open(_DOCS_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_docs(docs: list[dict]) -> None:
    """Persist docs list to disk."""
    _DOCS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_DOCS_FILE, "w") as f:
        json.dump(docs, f, indent=2)


_PREFS_FILE = _REPO_ROOT / "src" / "study_system" / "study_data" / "prefs.json"


def load_prefs() -> dict:
    """Return saved user preferences, empty dict on missing/malformed file."""
    try:
        with open(_PREFS_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_prefs(prefs: dict) -> None:
    """Persist user preferences to disk (merges with existing)."""
    _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = load_prefs()
    existing.update(prefs)
    with open(_PREFS_FILE, "w") as f:
        json.dump(existing, f, indent=2)


def get_service_account_email() -> str:
    """Read client_email from credentials.json, return empty string on failure."""
    creds_path = os.environ.get("CSA_CREDENTIALS_PATH", "") or str(_CREDS_FILE)
    try:
        with open(creds_path) as f:
            return json.load(f).get("client_email", "")
    except Exception:
        return ""


# ── Google Doc writer ─────────────────────────────────────────────────────────
def write_to_google_doc(doc_id: str, notes: str, credentials_path: str = "") -> str:
    """Append formatted notes to the last tab of a Google Doc.

    Uses the same formatting rules as the Coursera Agent:
      - First line (title): bold + 14pt
      - Lines containing 📊 or 💼: bold
      - Lines ending with ':' (section headers, >5 chars): bold
      - Numbered list items (1. Foo:): bold up to the colon

    Returns the tab title written to, or raises on failure.
    """
    import re as _re
    from google.oauth2.service_account import Credentials as _Creds
    from googleapiclient.discovery import build as _build

    creds_path = credentials_path or os.environ.get("CSA_CREDENTIALS_PATH", "") or str(_CREDS_FILE)
    creds = _Creds.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/documents"]
    )
    service = _build("docs", "v1", credentials=creds)

    doc = service.documents().get(documentId=doc_id, includeTabsContent=True).execute()

    # ── Select last tab ───────────────────────────────────────────────────
    tab_id = tab_title = None
    end_index = 1
    if "tabs" in doc and doc["tabs"]:
        last_tab = doc["tabs"][-1]
        props = last_tab.get("tabProperties", {})
        tab_id = props.get("tabId")
        tab_title = props.get("title", "Untitled")
        content = last_tab.get("documentTab", {}).get("body", {}).get("content", [])
        if content:
            end_index = content[-1].get("endIndex", 1) - 1
    else:
        content = doc.get("body", {}).get("content", [])
        if content:
            end_index = content[-1].get("endIndex", 1) - 1

    # ── Build requests ────────────────────────────────────────────────────
    text_to_insert = f"\n\n{notes}\n\n"
    def _loc(extra: dict) -> dict:
        base = {"index": end_index}
        if tab_id:
            base["tabId"] = tab_id
        return {**base, **extra}

    requests: list[dict] = [
        {"insertText": {"location": _loc({}), "text": text_to_insert}}
    ]

    start_pos = end_index + 2  # skip leading \n\n
    current_offset = start_pos
    is_first = True

    def _style(start: int, end: int, style: dict, fields: str) -> dict:
        rng = {"startIndex": start, "endIndex": end}
        if tab_id:
            rng["tabId"] = tab_id
        return {"updateTextStyle": {"range": rng, "textStyle": style, "fields": fields}}

    for line in notes.split("\n"):
        line_len = len(line) + 1
        stripped = line.strip()
        if stripped:
            ls = current_offset
            le = current_offset + len(line.rstrip())
            if is_first:
                requests.append(_style(ls, le, {"bold": True, "fontSize": {"magnitude": 14, "unit": "PT"}}, "bold,fontSize"))
                is_first = False
            elif "📊" in line or "💼" in line:
                requests.append(_style(ls, le, {"bold": True}, "bold"))
            elif stripped.endswith(":") and len(stripped) > 5 and not _re.match(r"^\d+\.", stripped):
                requests.append(_style(ls, le, {"bold": True}, "bold"))
            m = _re.match(r"^(\d+\.)([^:]+):", stripped)
            if m:
                colon_pos = line.find(":", line.find(m.group(1)))
                if colon_pos > 0:
                    requests.append(_style(ls, ls + colon_pos + 1, {"bold": True}, "bold"))
        current_offset += line_len

    service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    return tab_title or "document"