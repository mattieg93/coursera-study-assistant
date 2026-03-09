#!/bin/zsh
# launch.sh — Start the Coursera Study Assistant
# Steps: 1) Ensure Ollama is running with correct model path
#         2) Sync study data
#         3) Launch Streamlit UI

set -e

OLLAMA_MODELS_PATH="/Users/mattieg/Repos/ai_models"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL_NAME="granite3.2:8b"

echo "========================================="
echo "  Coursera Study Assistant — Launcher"
echo "========================================="
echo ""

# ── Step 1: Ollama ────────────────────────────────────────────────────────────
echo "▶ [1/3] Checking Ollama..."

if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    # Ollama is running — verify the model is accessible
    MODEL_FOUND=$(curl -s http://localhost:11434/api/tags | grep -c "$MODEL_NAME" || true)
    if [[ "$MODEL_FOUND" -gt 0 ]]; then
        echo "  ✓ Ollama is already running with $MODEL_NAME"
    else
        echo "  ⚠ Ollama is running but $MODEL_NAME is not visible."
        echo "  → The server may have been started without OLLAMA_MODELS=$OLLAMA_MODELS_PATH"
        echo "  → Stopping existing Ollama process..."
        sudo pkill -f "ollama serve" 2>/dev/null || true
        sleep 2
        echo "  → Restarting with correct model path (sudo required)..."
        sudo OLLAMA_MODELS="$OLLAMA_MODELS_PATH" ollama serve &>/tmp/ollama.log &
        disown
        echo "  ✓ Ollama restarted. Waiting for it to be ready..."
        sleep 4
    fi
else
    echo "  → Ollama is not running. Starting it now (sudo required)..."
    sudo OLLAMA_MODELS="$OLLAMA_MODELS_PATH" ollama serve &>/tmp/ollama.log &
    disown
    echo "  ✓ Ollama started. Waiting for it to be ready..."
    sleep 4
fi

# Final check
MODEL_FOUND=$(curl -s http://localhost:11434/api/tags | grep -c "$MODEL_NAME" || true)
if [[ "$MODEL_FOUND" -eq 0 ]]; then
    echo ""
    echo "  ✗ ERROR: $MODEL_NAME is still not available after startup."
    echo "    Check /tmp/ollama.log for details."
    echo "    Models path: $OLLAMA_MODELS_PATH"
    exit 1
fi
echo "  ✓ $MODEL_NAME is live"
echo ""

# ── Step 2: Sync study data ───────────────────────────────────────────────────
echo "▶ [2/3] Syncing study data..."
cd "$SCRIPT_DIR"

# Use the venv if it exists
VENV_PYTHON="/Users/mattieg/Repos/mattieg93.github.io/.venv-1/bin/python"
if [[ -f "$VENV_PYTHON" ]]; then
    "$VENV_PYTHON" study_system.py --sync
else
    python study_system.py --sync
fi
echo ""

# ── Step 3: Launch Streamlit ──────────────────────────────────────────────────
echo "▶ [3/3] Launching Study Chat UI..."
echo ""

VENV_STREAMLIT="/Users/mattieg/Repos/mattieg93.github.io/.venv-1/bin/streamlit"
if [[ -f "$VENV_STREAMLIT" ]]; then
    "$VENV_STREAMLIT" run study_chat_ui.py
else
    streamlit run study_chat_ui.py
fi
