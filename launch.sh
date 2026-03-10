#!/bin/zsh
# launch.sh — Start the Coursera Study Assistant (unified UI)
# Steps: 1) Check Google credentials  2) Ensure Ollama running  3) Launch Streamlit

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env if present
[[ -f "$REPO_DIR/.env" ]] && set -a && source "$REPO_DIR/.env" && set +a

# Fallbacks if not set in .env
OLLAMA_MODELS_PATH="${OLLAMA_MODELS:-}"
MODEL_NAME="${CSA_MODEL:-granite3.2:8b}"
VENV_PYTHON="$REPO_DIR/.venv-1/bin/python3"
VENV_STREAMLIT="$REPO_DIR/.venv-1/bin/streamlit"
DEFAULT_CREDS="$REPO_DIR/src/coursera_agent/credentials.json"

echo "========================================="
echo "  Coursera Study Assistant — Launcher"
echo "========================================="
echo ""

# ── Step 1: Google credentials check ─────────────────────────────────────────
echo "▶ [1/3] Checking Google credentials..."

# Resolve credentials path: env var → default location
CREDS_PATH="${CSA_CREDENTIALS_PATH:-$DEFAULT_CREDS}"

if [[ -f "$CREDS_PATH" ]]; then
    echo "  ✓ Credentials found: $CREDS_PATH"
    export CSA_CREDENTIALS_PATH="$CREDS_PATH"
else
    echo ""
    echo "  ✗ Credentials file not found."
    echo ""
    echo "  The Coursera Agent needs a Google service account credentials JSON"
    echo "  to write notes to your Google Doc."
    echo ""
    printf "  Do you have a credentials JSON file already? [y/n]: "
    read HAS_CREDS

    if [[ "$HAS_CREDS" =~ ^[Yy] ]]; then
        printf "  Enter the full path to your credentials JSON file: "
        read CREDS_INPUT
        # Strip surrounding quotes if present
        CREDS_INPUT="${CREDS_INPUT#\'}" ; CREDS_INPUT="${CREDS_INPUT%\'}"
        CREDS_INPUT="${CREDS_INPUT#\"}" ; CREDS_INPUT="${CREDS_INPUT%\"}"
        # Expand ~ manually
        CREDS_INPUT="${CREDS_INPUT/#\~/$HOME}"

        if [[ -f "$CREDS_INPUT" ]]; then
            export CSA_CREDENTIALS_PATH="$CREDS_INPUT"
            # Persist to .env so this isn't asked again
            if [[ -f "$REPO_DIR/.env" ]]; then
                # Update existing CSA_CREDENTIALS_PATH line or append
                if grep -q "^CSA_CREDENTIALS_PATH=" "$REPO_DIR/.env"; then
                    sed -i '' "s|^CSA_CREDENTIALS_PATH=.*|CSA_CREDENTIALS_PATH=$CREDS_INPUT|" "$REPO_DIR/.env"
                else
                    echo "CSA_CREDENTIALS_PATH=$CREDS_INPUT" >> "$REPO_DIR/.env"
                fi
            fi
            echo "  ✓ Credentials set and saved to .env"
        else
            echo "  ✗ File not found at: $CREDS_INPUT"
            echo "  Start again and provide a valid path."
            exit 1
        fi
    else
        echo ""
        echo "  You'll need to create a Google service account and share your"
        echo "  Google Doc with it (as Editor) before the agent can write notes."
        echo ""
        echo "  Step 1 — Create a service account + download credentials JSON:"
        echo "    https://cloud.google.com/iam/docs/service-accounts-create"
        echo ""
        echo "  Step 2 — Share your Google Doc with the service account as Editor:"
        echo "    https://docs.conveyor.com/docs/sharing-files-with-your-google-drive-service-account"
        echo ""
        echo "  Once done, re-run this script with your credentials JSON ready."
        exit 1
    fi
fi
echo ""

# ── Step 2: Ollama ───────────────────────────────────────────────────────────
echo "▶ [2/3] Checking Ollama..."

if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    MODEL_FOUND=$(curl -s http://localhost:11434/api/tags | grep -c "$MODEL_NAME" || true)
    if [[ "$MODEL_FOUND" -gt 0 ]]; then
        echo "  ✓ Ollama running with $MODEL_NAME"
    else
        echo "  ⚠ Ollama running but $MODEL_NAME not visible — restarting with correct model path..."
        sudo pkill -f "ollama serve" 2>/dev/null || true
        sleep 2
        if [[ -n "$OLLAMA_MODELS_PATH" ]]; then
            sudo OLLAMA_MODELS="$OLLAMA_MODELS_PATH" ollama serve &>/tmp/ollama.log &
        else
            ollama serve &>/tmp/ollama.log &
        fi
        disown
        sleep 4
    fi
else
    echo "  → Starting Ollama..."
    if [[ -n "$OLLAMA_MODELS_PATH" ]]; then
        sudo OLLAMA_MODELS="$OLLAMA_MODELS_PATH" ollama serve &>/tmp/ollama.log &
    else
        ollama serve &>/tmp/ollama.log &
    fi
    disown
    sleep 4
fi

MODEL_FOUND=$(curl -s http://localhost:11434/api/tags | grep -c "$MODEL_NAME" || true)
if [[ "$MODEL_FOUND" -eq 0 ]]; then
    echo "  ✗ ERROR: $MODEL_NAME still not available."
    echo "    If using a custom models path, ensure OLLAMA_MODELS is set in .env"
    echo "    Check /tmp/ollama.log for details"
    exit 1
fi
echo "  ✓ $MODEL_NAME is live"
echo ""

# ── Step 3: Launch unified Streamlit UI ──────────────────────────────────────
echo "▶ [3/3] Launching unified Study Assistant UI..."
echo ""
cd "$REPO_DIR"

if [[ -f "$VENV_STREAMLIT" ]]; then
    "$VENV_STREAMLIT" run src/ui/frontend.py --server.port 8501
else
    echo "  ✗ ERROR: venv not found at $REPO_DIR/.venv-1"
    echo "    Run: python3 -m venv .venv-1 && .venv-1/bin/python3 -m pip install -r requirements.txt"
    exit 1
fi