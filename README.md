# Coursera Study Assistant

A unified Streamlit application for processing Coursera courses and studying their content using local LLMs.

## Features

- **Study Assistant** — RAG-based chat interface; upload or paste quiz screenshots for automatic OCR + AI-answered multiple choice; correct AI mistakes in natural language
- **Coursera Agent** — URL queue runner that automates lecture transcript capture, summarisation via Ollama, and Google Docs note syncing; per-lecture progress bars
- **Expand Knowledge Base** — add supplementary material to the vector DB by pasting text or uploading a file
- **Sidebar** — one-click "View Notes" link to Google Doc, "Sync Notes" (pull latest doc into vector DB), Clear Chat History, and all settings in one place

## Setup

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) running locally with at least one model (default: `granite3.2:8b`)
- Chromium browser for Coursera automation
- Google Cloud service account credentials (`credentials.json`) in `src/coursera_agent/`

### Install & run

```bash
python -m venv .venv-1
source .venv-1/bin/activate
pip install -r requirements.txt
./launch.sh          # checks credentials → starts Ollama → launches Streamlit
```

### Environment variables (`.env` at repo root)

| Variable | Purpose | Default |
|---|---|---|
| `CSA_DOC_ID` | Google Doc ID for course notes | *(optional — falls back to first entry in docs.json)* |
| `CSA_MODEL` | Ollama model name | `granite3.2:8b` |
| `OLLAMA_MODELS` | Handles custom Ollama models directory | *(Ollama default)* |
| `CSA_CREDENTIALS_PATH` | Override path to `credentials.json` | `src/coursera_agent/credentials.json` |

---

## Changelog

### v0.4.0 — Multi-doc support, per-course vector DB, model propagation
- **Google Doc registry** — sidebar replaces plain Doc ID text input with a selectbox backed by `docs.json`; Add and Edit/Delete modals with service-account email hint
- **Per-course vector DB isolation** — `StudyDatabase(doc_id=...)` writes a separate `study_db_{doc_id}.pkl` per doc; the in-memory store reloads automatically when the active doc changes
- **Model selection propagates to RAG** — `answer_question()` now accepts a `model` parameter; the sidebar model selector applies to both the Coursera Agent subprocess and all Study Assistant queries
- **Ollama model auto-discovery** — sidebar model selector queries the local Ollama API and lists available models; falls back to text input if Ollama is not running
- **LLM prompt improvements** — BUSINESS APPLICATION section renamed to PRACTICAL APPLICATION; course-type label in prompt is now dynamic (`graduate-level data science course` vs `graduate-level course` when textbook context is present)
- `CSA_DOC_ID` is now optional: if unset, the first entry in `docs.json` is used
- **Custom Ollama sudo fix** - Launching /.launch.sh in a custom location resulted in conflicting calls when Ollama was in a custom location. This is fixed.


### v0.3.0 — Streamlit UI overhaul & 3-tab layout
- Restructured into three tabs: **Study Assistant**, **Coursera Agent**, **Expand Knowledge Base**
- Sidebar consolidates View Notes link, Sync Notes, Clear Chat History, and all settings (Doc ID, model, prerequisites)
- Applied **Plus Jakarta Sans** font via Google Fonts CSS injection
- Replaced Google Doc iframe (blocked by sign-in wall) with a `st.link_button` that opens in a new tab
- Coursera Agent tab: per-lecture progress bars (transcript → model summarising → notes saved) replacing raw log output
- Expand Knowledge Base tab: dropdown selector (Paste content / Upload document) with a single shared Title field; replaced previous two-column layout
- Added post-run sync prompt: after all URLs complete, user is offered a one-click "Sync new notes to Study Assistant"
- Settings (prerequisites, Doc ID, model) moved from main area to sidebar bottom expander — declutters primary workspace

### v0.2.0 — Backend bridge, .env system & credentials
- Created `src/ui/backend.py` as a thin bridge: adds study_system to `sys.path`, re-exports public API, and launches coursera_agent as a subprocess
- Added `python-dotenv` support; `.env` loaded from repo root in both `backend.py` and `coursera_agent.py`
- Introduced `CSA_*` env vars (`CSA_DOC_ID`, `CSA_MODEL`, `OLLAMA_MODELS`, `CSA_CREDENTIALS_PATH`, `CSA_UI_MODE`, `CSA_ALL_VIDEOS`, `CSA_READINGS`)
- Fixed credentials path resolution: `Path(__file__).parent / "credentials.json"` in agent; frontend reads same resolution so "No credentials found" false-positive is gone
- `run_agent_subprocess()`: launches agent with `-u` (unbuffered) + `PYTHONUNBUFFERED=1` + `bufsize=1` for true real-time stdout streaming
- `OLLAMA_MODELS` only flagged in Prerequisites if explicitly set in env
- Updated `launch.sh` to 3-step launcher: credentials check + setup links → Ollama start → Streamlit

### v0.1.0 — Initial UI & environment repair
- Rebuilt `.venv-1`; resolved all `ModuleNotFoundError` and `EOFError` (from `input()` calls in non-interactive subprocess)
- Created `src/ui/frontend.py` and `src/ui/backend.py` from scratch
- Initial 2-tab layout: Study Assistant (chat + quiz OCR) and Coursera Agent (URL queue)
- Quiz OCR: upload screenshot or paste from clipboard; auto-parses multiple-choice questions; AI answers via RAG; natural-language correction handler saves feedback to vector DB
- URL queue with Add/Remove; "All videos in module" and "Include readings" toggles inline
- Removed dead code and emoji output from agent stdout
- Removed `src/study_system/study_data/` from git tracking (large binary/data files)
