# src/ui/backend.py
"""
Backend bridge: adds study_system to sys.path then re-exports its public API.
The coursera_agent is kept separate and launched as a subprocess (it owns Chrome
and is designed to run interactively in a terminal).
"""
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
    sync_notes,
    show_statistics,
)
from ocr_utils import (                      # noqa: E402
    extract_text_from_image,
    parse_multiple_choice_questions,
    format_question_for_display,
    format_question_for_rag,
    extract_answer_letter,
)


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