# coursera-study-assistant/launch.sh
#!/bin/zsh
# coursera-study-assistant — Start the Study Assistant UI

set -e

echo "========================================="
echo "  Coursera Study Assistant — Launcher"
echo "========================================="
echo ""

# Check dependencies
echo "▶ Checking dependencies..."
command -v streamlit >/dev/null 2>&1 || { 
    echo >&2 "Streamlit is required. Installing now..."
    pip install streamlit
}

# Start the UI
echo "▶ Starting UI..."
streamlit run src/ui/frontend.py --server.port 8501

# Optional: Add error handling and cleanup
trap "echo 'Stopping UI...'; pkill -f 'streamlit run'; exit" SIGINT SIGTERM