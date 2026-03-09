# Study System

RAG-based study assistant with OCR quiz screenshot support.

## Features
- 📸 **OCR Quiz Parsing** - Upload quiz screenshots and get AI-powered answers
- 💬 **Chat Interface** - Ask questions about course materials
- 🧠 **RAG System** - Retrieval-Augmented Generation with ChromaDB
- 📚 **Knowledge Base** - Add lecture notes, PDFs, and more

## Prerequisites

### 1. Install Ollama
Download and install Ollama from [ollama.ai](https://ollama.ai)

**macOS:**
```bash
# Download from https://ollama.ai/download
# Or use Homebrew
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

**Windows:**
Download the installer from [ollama.ai](https://ollama.ai/download)

### 2. Start Ollama Service
```bash
# Standard installation
ollama serve

# OR with custom model directory (if you store models elsewhere)
sudo OLLAMA_MODELS=/Users/mattieg/Repos/ai_models ollama serve
```

**Tip:** Keep this running in a separate terminal window, or run it as a background service.

**Note for Mac users with custom model paths:** 
- If your models are stored in a custom location like `/Users/mattieg/Repos/ai_models/`, use the `OLLAMA_MODELS` environment variable
- Make sure the directory exists: `mkdir -p /Users/mattieg/Repos/ai_models`

### 3. Pull the Required Model
```bash
# Download the granite3.2:8b model (used by this system)
ollama pull granite3.2:8b
```

### 4. Verify Ollama is Running
```bash
# Check if Ollama is running
ollama ps

# Test the model
ollama run granite3.2:8b "Hello, are you working?"
```

### 5. Install Python Dependencies
```bash
# From the study_system directory
# Core dependencies
pip install streamlit chromadb pillow numpy opencv-python ollama google-auth google-api-python-client

# OCR Engine (choose one):
# Option 1: Apple Vision (macOS native, RECOMMENDED - best accuracy)
pip install pyobjc-framework-Vision pyobjc-framework-Quartz

# Option 2: EasyOCR (cross-platform fallback)
pip install easyocr
```

## Quick Start

```bash
# Make sure Ollama is running first!
# Standard:
ollama serve  # In a separate terminal

# OR with custom model directory:
sudo OLLAMA_MODELS=/Users/mattieg/Repos/ai_models ollama serve

# Then launch the study assistant
cd study_system
streamlit run study_chat_ui.py
```

## Components

- **study_chat_ui.py** - Main Streamlit UI
  - Two-tab quiz upload (File Upload, Clipboard Paste)
  - Chat interface for Q&A
  - Sidebar for adding content to knowledge base

- **ocr_utils.py** - OCR and parsing engine
  - **Apple Vision Framework** (macOS native, best accuracy for typed text)
  - EasyOCR fallback for non-macOS systems
  - Image preprocessing (inversion, contrast, sharpness)
  - Question parsing with multi-line and code-like option support
  - Answer letter extraction from RAG responses

- **study_system.py** - RAG query system
  - Retrieves relevant context from vector DB
  - Formats prompts for Claude/Ollama
  - Session stats tracking

- **study_db.py** - ChromaDB vector database
  - Stores and retrieves course materials
  - Section-based chunking
  - Similarity search

- **quiz_generator.py** - Quiz generation tools

- **clipboard_to_base64.py** - Helper for clipboard screenshots

## Usage

### 1. Add Course Materials
Use the sidebar "Paste Content" or "Upload PDF" options to add your lecture notes.

### 2. Upload Quiz Screenshot
Take a screenshot (Cmd+Shift+4 on Mac), then use either:
- **Upload File** tab - Drag & drop or browse
- **Paste from Clipboard** tab - Use `python clipboard_to_base64.py` then paste

### 3. Get Answers
The system will:
1. Extract questions using OCR
2. Query the knowledge base
3. Display answers with explanations and sources

## Testing

```bash
# Test Apple Vision OCR (recommended for macOS)
python ../tests/test_vision_ocr.py path/to/screenshot.png

# Test OCR accuracy (legacy)
python ../tests/test_ocr.py path/to/screenshot.png

# Debug OCR detection
python ../tests/test_ocr_debug.py path/to/screenshot.png

# Debug parsing logic
python ../tests/test_parse_debug.py path/to/screenshot.png
```

## Data Storage

- **study_data/chromadb/** - Vector database
- **study_data/sessions/** - Session statistics
- **study_data/raw/** - Raw uploaded files

## Troubleshooting

### "Error generating answer: Make sure Ollama is running"
1. Check if Ollama is running: `ollama ps`
2. If not running, start it: `ollama serve`
3. Verify the model is installed: `ollama list`
4. If granite3.2:8b is missing, pull it: `ollama pull granite3.2:8b`

### OCR Not Detecting Questions
- Make sure questions are numbered (1., 2., 3.)
- Options should be labeled (A), B), C), D)
- Take clear, high-contrast screenshots
- Zoom in on the quiz if needed (but try to fit all questions in one shot)
- White backgrounds work best (dark backgrounds are auto-inverted)

### Poor OCR Accuracy
**macOS users:** Make sure Apple Vision Framework is installed for best results:
```bash
pip install pyobjc-framework-Vision pyobjc-framework-Quartz
```

Check which OCR engine is being used:
```bash
python -c "from study_system.ocr_utils import USE_VISION; print('Vision' if USE_VISION else 'Fallback')"
```

**Expected:** Should show "Vision" on macOS for optimal accuracy

**Alternative:** If Vision has issues, you can force EasyOCR:
```bash
pip install easyocr
# Vision will be used first if available, EasyOCR as fallback
```

### Streamlit Connection Error
```bash
# Kill any existing Streamlit processes
pkill -f streamlit

# Restart with a different port
streamlit run study_chat_ui.py --server.port 8502
```

### Import Errors
Make sure you're running from the `study_system` directory:
```bash
cd /path/to/quick_tools/study_system
streamlit run study_chat_ui.py
```

## Tips for Best Results

1. **Add Quality Content** - The better your notes in the knowledge base, the better the answers
2. **Clear Screenshots** - Use Cmd+Shift+4 (Mac) or Win+Shift+S (Windows) for clean screenshots
3. **One Quiz at a Time** - Upload 3-5 questions per screenshot for best OCR accuracy
4. **Ask Follow-ups** - Use the chat interface to dive deeper into topics

## Video Tutorial

Perfect for YouTube! Here's the demo flow:
1. Show Ollama installation and setup
2. Pull the model and verify it's running
3. Launch Streamlit
4. Add course notes to knowledge base
5. Take quiz screenshot
6. Upload and get instant answers with explanations
7. Show chat interface for follow-up questions
