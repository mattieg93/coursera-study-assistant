# ocr_utils.py
"""OCR utilities for extracting quiz questions from screenshots"""

from PIL import Image, ImageEnhance, ImageOps
import re
import io
import base64
import json
import numpy as np
import sys

# Try to use Apple Vision (macOS native, best for typed text)
USE_VISION = True
if sys.platform == 'darwin':  # macOS only
    try:
        import Vision
        from Foundation import NSURL # type: ignore
        import Quartz
        USE_VISION = True
    except ImportError:
        pass

# Fallback to EasyOCR
if not USE_VISION:
    try:
        import easyocr
        USE_EASYOCR = True
        _reader = None
    except ImportError:
        USE_EASYOCR = False
        import pytesseract

def _get_easyocr_reader():
    """Lazy load EasyOCR reader"""
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(['en'], gpu=False) # type: ignore
    return _reader

def preprocess_image(image):
    """Preprocess image for better OCR results"""
    # Convert to RGB if needed
    if image.mode != 'RGB':
        image = image.convert('RGB')
    
    # Convert to numpy array
    img_array = np.array(image)
    
    # Check if image has dark background (inverted colors)
    # Calculate average brightness
    avg_brightness = img_array.mean()
    
    # If image is dark (black background with white text), invert it
    if avg_brightness < 127:
        image = ImageOps.invert(image)
    
    # Enhance contrast
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(2.0)
    
    # Enhance sharpness
    enhancer = ImageEnhance.Sharpness(image)
    image = enhancer.enhance(1.5)
    
    return image

def extract_text_with_vision(image):
    """Extract text using Apple Vision Framework (macOS only)"""
    try:
        import tempfile
        import os
        
        # Save image to temp file (Vision needs a file path)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            image.save(tmp.name, 'PNG')
            tmp_path = tmp.name
        
        try:
            # Create URL from file path
            url = NSURL.fileURLWithPath_(tmp_path) # type: ignore
            
            # Create image request handler
            request_handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None) # pyright: ignore[reportAttributeAccessIssue, reportPossiblyUnboundVariable]
            
            # Create text recognition request
            request = Vision.VNRecognizeTextRequest.alloc().init() # type: ignore
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate) # type: ignore
            request.setUsesLanguageCorrection_(True)
            
            # Perform request
            success = request_handler.performRequests_error_([request], None)
            
            if success[0]:
                # Extract text from results
                results = request.results()
                text_lines = []
                
                for observation in results:
                    # Get top candidate
                    text = observation.topCandidates_(1)[0].string()
                    text_lines.append(text)
                
                return '\n'.join(text_lines)
            else:
                return "Error: Vision request failed"
        finally:
            # Clean up temp file
            os.unlink(tmp_path)
            
    except Exception as e:
        return f"Error with Vision OCR: {e}"

# ── Vision-model quiz extraction (Ollama multimodal) ─────────────────────────

_VISION_PROMPT = """\
You are a verbatim quiz transcriber. Transcribe every question from this screenshot into JSON — character for character, exactly as printed.

Return ONLY a raw JSON array. No markdown fences. No commentary. Just the JSON.

[
  {
    "number": 1,
    "type": "single",
    "text": "Exact question text copied character-for-character from the image",
    "options": [
      {"letter": "A", "text": "Exact option text"},
      {"letter": "B", "text": "Exact option text"},
      {"letter": "C", "text": "Exact option text"},
      {"letter": "D", "text": "Exact option text"},
      {"letter": "E", "text": "Exact option text — include if visible"},
      {"letter": "F", "text": "Exact option text — include if visible"}
    ]
  }
]

MANDATORY rules — violating any of these is an error:
1. "type" field:
   - Use "multi" when the question uses CHECKBOXES (square □ boxes) or contains the words "Select all" / "Choose all" / "check all" / "all correct facts".
   - Use "single" for radio buttons (round ○ buttons) or when only one answer is possible.
2. Options: count EVERY option visible in the screenshot — there may be 5, 6, or more. Assign letters A, B, C, D, E, F, ... sequentially. You MUST NOT stop early; if you see 6 options, output all 6.
3. VERBATIM copy. Do not paraphrase, simplify, or reword anything — question text or option text.
4. Pseudocode / code blocks: include the full code as the question text, with line breaks represented as \\n. Copy every character: brackets, operators, indentation, semicolons.
   - Array indexing a[k], A[1..n], A[lo..hi] — copy exactly.
5. Math notation:
   - Superscripts rendered as small raised glyphs (n², n³): output as n^2, n^3.
   - Unicode Greek letters (Θ, Ω, Ω): keep as-is. Do NOT convert to LaTeX (\\Theta, \\Omega).
   - Complexity: O(n^2), Θ(n^2), Ω(n) — copy the symbol and argument verbatim.
   - Arithmetic: c1 + n*(c2+c3+c4) + c5, T(n) = T(n/2) + Θ(1) — copy exactly.
   - Subscripts: copy whichever form is visible (c1, c_1, c₁).
6. If options use checkboxes, bullets, or numbers instead of letters, still output "A"/"B"/"C"... in JSON, but copy option text verbatim.
"""


# Keep standard whitespace escapes (\n \r \t) and structural ones (\\ \" \/ \uXXXX).
# Strip \b (backspace) and \f (form-feed) — never intentional in quiz content but
# collide with LaTeX keywords \beta→\b+eta and \frac→\f+rac.
_JSON_ESCAPE_CHARS = set('"\\\/ nrt')


def _repair_json(raw: str) -> str:
    """Fix invalid backslash escapes that LLMs emit inside JSON strings.

    Vision models often output LaTeX (\frac, \omega) and pseudocode characters
    (\[, \*) inside JSON string values.  Strip the backslash so json.loads
    can parse the rest of the string cleanly.
    """
    result = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == '\\' and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in _JSON_ESCAPE_CHARS or nxt == 'u':
                # Valid JSON escape — keep as-is
                result.append(ch)
                result.append(nxt)
                i += 2
            else:
                # Invalid / LaTeX escape — drop the backslash, keep the character
                result.append(nxt)
                i += 2
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


# ── Post-parse math cleanup ───────────────────────────────────────────────────
_FRAC_RE = re.compile(r'r?ac\{([^{}]*)\}\{([^{}]*)\}')


def _clean_math(text: str) -> str:
    """Normalise LaTeX artifacts left in text after JSON parsing."""
    # frac{a}{b} or rac{a}{b} (\frac → frac after backslash stripped) → (a/b)
    text = _FRAC_RE.sub(lambda m: f'({m.group(1)}/{m.group(2)})', text)
    # n^{expr} → n^expr (simple int) or n^(expr)
    def _exp(m):
        inner = m.group(1)
        return f'^{inner}' if re.match(r'^[\w/]+$', inner) else f'^({inner})'
    text = re.sub(r'\^\{([^}]+)\}', _exp, text)
    # Greek/math keywords left bare after backslash stripping
    for src, dst in [
        ('Theta', 'Θ'), ('theta', 'θ'),
        ('Omega', 'Ω'), ('omega', 'ω'),
        ('Alpha', 'Α'), ('alpha', 'α'),
        ('Beta', 'Β'),  ('beta', 'β'),
        ('Gamma', 'Γ'), ('gamma', 'γ'),
        ('Delta', 'Δ'), ('delta', 'δ'),
        ('Sigma', 'Σ'), ('sigma', 'σ'),
        ('infty', '∞'), ('cdot', '·'),
        ('times', '×'), ('leq', '≤'), ('geq', '≥'),
        ('neq', '≠'), ('sqrt', '√'),
    ]:
        text = text.replace(src, dst)
    return text


def detect_vision_model(preferred: str = "minicpm-v") -> str | None:
    """Return the name of an available Ollama vision model, preferring `preferred`."""
    try:
        import ollama
        models = ollama.list().models or []
        names = [m.model for m in models if m.model]
        # Exact prefix match on preferred first
        for name in names:
            if name.startswith(preferred):
                return name
        # Any vision-capable model (common naming conventions)
        for name in names:
            lower = name.lower()
            if any(tag in lower for tag in ("-v:", "-v-", "vl:", "vl-", "vision", "minicpm", "llava", "moondream")):
                return name
        return None
    except Exception:
        return None


def extract_questions_with_vision_model(
    image_file, model: str | None = None
) -> list[dict] | None:
    """Use an Ollama vision model to extract structured quiz questions from a screenshot.

    Returns a list of question dicts compatible with parse_multiple_choice_questions output,
    or None if extraction fails (caller should fall back to OCR).
    """
    _model = model or detect_vision_model()
    if not _model:
        print("   ℹ️  No Ollama vision model available — falling back to OCR")
        return None

    try:
        import ollama

        # Read image bytes and encode to base64
        if hasattr(image_file, "read"):
            image_file.seek(0)
            img_bytes = image_file.read()
            image_file.seek(0)
        else:
            with open(image_file, "rb") as f:
                img_bytes = f.read()

        b64 = base64.b64encode(img_bytes).decode("utf-8")

        print(f"   🔬 Extracting questions via {_model}...")
        response = ollama.chat(
            model=_model,
            messages=[
                {
                    "role": "user",
                    "content": _VISION_PROMPT,
                    "images": [b64],
                }
            ],
        )
        raw = response["message"]["content"].strip()

        # Strip markdown fences — model sometimes wraps JSON anyway
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\n?```\s*$", "", raw)

        parsed = json.loads(_repair_json(raw))

        # Some models wrap the array: {"questions": [...]} or {"data": [...]}
        if isinstance(parsed, dict) and not isinstance(parsed, list):
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break

        if not isinstance(parsed, list) or not parsed:
            print(f"   ⚠️  Vision model returned empty or non-list JSON (raw preview: {raw[:200]!r})")
            return None

        questions = parsed

        # Normalise to the same shape parse_multiple_choice_questions produces
        _MULTI_RE = re.compile(
            r'select all'          # "select all that apply" / "select all correct"
            r'|choose all'         # "choose all that apply"
            r'|check all'          # "check all that apply"
            r'|all that apply'     # explicit
            r'|all correct facts'  # Coursera-specific phrasing
            r'|correct answers'    # plural "answers" — singular "answer" is single-choice
            r'|select.*correct.*(?:answers|facts)',  # catch wider Coursera variants
            re.IGNORECASE,
        )
        normalised = []
        for q in questions:
            opts = [
                {"letter": o.get("letter", ""), "text": _clean_math(o.get("text", ""))}
                for o in q.get("options", [])
            ]
            q_text = _clean_math(q.get("text", ""))
            # Override type from question text — vision models can't reliably
            # distinguish checkbox □ from radio ○ by shape alone.
            q_type = "multi" if _MULTI_RE.search(q_text) else q.get("type", "single")
            normalised.append({
                "number": q.get("number", len(normalised) + 1),
                "type": q_type,
                "text": q_text,
                "options": opts,
            })

        print(f"   ✓ Vision model extracted {len(normalised)} question(s)")
        return normalised

    except json.JSONDecodeError as e:
        print(f"   ⚠️  Vision model JSON parse error: {e} — falling back to OCR")
        return None
    except Exception as e:
        print(f"   ⚠️  Vision model extraction failed: {e} — falling back to OCR")
        return None


def extract_text_from_image(image_file):
    """Extract text from an image using OCR with preprocessing"""
    try:
        # Load image
        image = Image.open(image_file)
        
        # Preprocess for better OCR
        image = preprocess_image(image)
        
        # Run OCR - prioritize Vision on macOS
        if USE_VISION:
            text = extract_text_with_vision(image)
        elif USE_EASYOCR:
            reader = _get_easyocr_reader()
            result = reader.readtext(np.array(image), detail=0)
            # EasyOCR returns a list of strings when detail=0
            text = '\n'.join(str(line) for line in result)
        else:
            # Use pytesseract with better config
            custom_config = r'--oem 3 --psm 6'
            text = pytesseract.image_to_string(image, config=custom_config) # type: ignore
        
        return text.strip()
    except Exception as e:
        return f"Error extracting text: {e}"

def parse_multiple_choice_questions(text):
    """Parse multiple choice questions from extracted text (flexible format)"""

    # ── Fast path: "Select all that apply" / checkbox-style format ────────────
    # These questions have a code/prose block THEN an instruction line THEN
    # sentence-length options.  The generic parser mistakes code lines for options.
    select_all_match = re.search(
        r'(?:select all|choose all|check all|select the correct answers|please select(?:\s+all))[^\n]*',
        text,
        re.IGNORECASE,
    )
    if select_all_match:
        question_text = text[:select_all_match.start()].strip()
        after = text[select_all_match.end():].strip()

        # Group physical lines into options.
        # A new option starts with a checkbox/bullet marker (•, O/○/□ read by OCR, ●, etc.).
        # Lines that don't start with a marker are continuations of the previous option.
        _BULLET_RE = re.compile(r'^[O\u25a1\u25cb\u25cf\u2022\u25e6\*\-]\s+', re.UNICODE)
        raw_options = []
        current_parts: list[str] = []
        for raw_line in after.split('\n'):
            stripped = raw_line.strip()
            if not stripped:
                continue
            if _BULLET_RE.match(stripped):
                # New option — flush previous
                if current_parts:
                    raw_options.append(' '.join(current_parts))
                current_parts = [_BULLET_RE.sub('', stripped).strip()]
            elif not current_parts and len(stripped) > 15:
                # First option with no bullet marker
                current_parts = [stripped]
            elif current_parts and len(stripped) > 5:
                # Continuation of the current option
                current_parts.append(stripped)
        if current_parts:
            raw_options.append(' '.join(current_parts))

        # Filter out any very short fragments that slipped through
        raw_options = [o for o in raw_options if len(o) > 15]

        if raw_options:
            opts = [
                {'letter': chr(65 + idx), 'text': opt}
                for idx, opt in enumerate(raw_options[:8])
            ]
            return [{
                'number': '1',
                'type': 'multi',
                'text': question_text,
                'options': opts,
            }]
    # ── Generic parser (single-answer, lettered options) ─────────────────────
    questions = []
    lines = text.split('\n')
    
    current_question = None
    current_options = []
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Skip empty lines
        if not line:
            i += 1
            continue
        
        # Helper: Check if this line is just a number (with optional period/paren)
        # Example: "5", "5.", "5)"
        def is_standalone_number(text):
            match = re.match(r'^(\d+)[\.\)]?$', text)
            if match:
                return match.group(1)
            return None
        
        # Check for standalone number - this is likely a question number
        question_num = is_standalone_number(line)
        if question_num and i + 1 < len(lines):
            # Combine with next line to form the question
            next_line = lines[i + 1].strip()
            if next_line and len(next_line) > 5:
                line = f"{question_num}. {next_line}"
                i += 1  # Skip the next line since we consumed it
        
        # Check for standalone "A" (OCR artifact from radio buttons) - always merge with next line
        if line == 'A' and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and len(next_line) > 5:  # Must be substantial
                line = 'A ' + next_line  # Prepend "A " to preserve it!
                i += 1  # Skip the next line since we consumed it
            else:
                # If next line is empty or too short, skip this "A"
                i += 1
                continue
        
        # Check if this is a numbered question (e.g., "2. Which function...")
        numbered_q = re.match(r'^(\d+)[\.\)]\s+(.+)', line)
        
        # Check if this looks like a question (starts with question words)
        question_words = r'^(What|Which|How|Why|When|Where|Who|Does|Do|Is|Are|Can|Could|Would|Should)'
        is_question_line = re.match(question_words, line, re.IGNORECASE)
        
        # Detect new question
        is_new_question = False
        question_number = None
        question_text = None
        
        if numbered_q:
            # Numbered question like "2. Which function..."
            is_new_question = True
            question_number = numbered_q.group(1)
            question_text = numbered_q.group(2).strip()
        elif is_question_line and (not current_question or len(current_options) >= 3):
            # Question word at start, and either no current question or we already have 3+ options
            is_new_question = True
            question_number = str(len(questions) + 1)
            question_text = line
        
        if is_new_question:
            # Save previous question if it has options
            if current_question and len(current_options) >= 1:  # At least 1 option
                # Auto-assign letters to options (A, B, C, D)
                for idx, opt in enumerate(current_options[:4]):  # Max 4 options
                    opt['letter'] = chr(65 + idx)
                questions.append({
                    'number': current_question['number'],
                    'text': current_question['text'],
                    'options': current_options[:4]
                })
            
            # Start new question
            current_question = {
                'number': question_number,
                'text': question_text
            }
            current_options = []
            i += 1
            continue
        
        # If we have a current question but no options yet, this might be question continuation  
        if current_question and len(current_options) == 0:
            # Check if line is a bullet point option (•, -, *, etc.)
            is_bullet = line.strip().startswith(('•', '-', '*', '·', '∙'))
            
            if is_bullet:
                # This is an option, not question continuation
                # Strip the bullet and add as option
                cleaned = line.strip()
                for bullet in ['•', '-', '*', '·', '∙']:
                    if cleaned.startswith(bullet):
                        cleaned = cleaned[len(bullet):].strip()
                        break
                
                if len(cleaned) > 5:  # Must be substantial
                    current_options.append({'text': cleaned, 'letter': None})
                i += 1
                continue
            
            # Continue appending to question until we see a clear option start
            # Options typically start with:
            # - "To " (like "To perform...")
            # - "Transformers" (for transformer questions)
            # - "Amechanism", "Aprocess" (OCR errors for "A mechanism", "A process")
            # - "mechanism", "process" (partial detection)
            # - Code-like text: get_angles, Dense, MultiHeadAttention (function/class names)
            # - "A " with substantial text (like "A dropout technique")
            
            # Check if line looks like code (function/class name)
            cleaned_for_check = line.strip('`')
            is_code_like = (
                bool(re.match(r'^[a-zA-Z_]+$', cleaned_for_check)) or  # get_angles, Dense, MultiHeadAttention
                '_' in cleaned_for_check  # has_underscores
            )
            
            is_clear_option = (
                line.startswith(('To ', 'Transformers', 'Amechanism', 'Aprocess', 'mechanism where', 'process of', 'dropout technique')) or 
                (line.startswith('A ') and len(line) > 20) or
                is_code_like  # Recognize code as options!
            )
            
            # If not a clear option, continue the question
            if not is_clear_option:
                current_question['text'] += ' ' + line
                i += 1
                continue
        
        # If we have a current question, this line is likely an option
        if current_question:
            # Skip very short junk lines (single chars, backticks, etc.)
            if len(line) <= 2 or line in ['`', '_', '.', ';', ':']:
                i += 1
                continue
            
            # Clean up the line - remove trailing punctuation artifacts
            cleaned = line.strip('`_.:;\'')
            
            # Check if line is a bullet point option (•, -, *, etc.)
            is_bullet = cleaned.startswith(('•', '-', '*', '·', '∙'))
            if is_bullet:
                # Strip the bullet
                for bullet in ['•', '-', '*', '·', '∙']:
                    if cleaned.startswith(bullet):
                        cleaned = cleaned[len(bullet):].strip()
                        break
            
            # Fix common OCR errors where "A" gets stuck to the word (missing space)
            if cleaned.startswith(('Amechanism', 'Aprocess', 'Adropout')):
                cleaned = 'A ' + cleaned[1:]
            
            # For code-like options (function names, class names), be more lenient
            # Matches: get_angles, Dense, MultiHeadAttention, etc.
            is_code_like = (
                bool(re.match(r'^[a-zA-Z_]+$', cleaned)) or  # Pure alphanumeric/underscore
                '`' in line or                                # Has backticks
                '_' in cleaned or                             # Has underscores  
                (len(cleaned) > 0 and cleaned[0].isupper() and not cleaned.isupper())  # CamelCase
            )
            
            # Add option if: substantial text (>5 chars) OR code-like OR bullet point, and not already at 4 options
            if len(current_options) < 4:
                if len(cleaned) > 5 or is_code_like or is_bullet:
                    current_options.append({
                        'letter': '',
                        'text': cleaned
                    })
        
        i += 1
    
    # Don't forget the last question
    if current_question:  # Save even if only 1 option (better than losing the question)
        if len(current_options) >= 1:  # At least 1 option
            for idx, opt in enumerate(current_options[:4]):
                opt['letter'] = chr(65 + idx)
            questions.append({
                'number': current_question['number'],
                'text': current_question['text'],
                'options': current_options[:4]
            })
    
    return questions

def format_question_for_display(question):
    """Format a parsed question for display"""
    output = f"**Question {question['number']}:** {question['text']}\n\n"
    
    for option in question['options']:
        output += f"**{option['letter']})** {option['text']}\n\n"
    
    return output

def format_question_for_rag(question):
    """Format a question for RAG query, handling both single and multi-select."""
    is_multi = question.get("type", "single") == "multi"
    query = f"{question['text']}\n\nOptions:\n"
    for option in question['options']:
        query += f"{option['letter']}) {option['text']}\n"

    if is_multi:
        query += (
            "\nThis is a 'select all that apply' question. "
            "Which options are correct? "
            "Please start your answer with 'Answers: A, C' (listing every correct letter separated by commas), "
            "then provide a brief explanation for each correct option."
        )
    else:
        letters = ", ".join(
            o["letter"] for o in question.get("options", [])
        ) or "A, B, C, D"
        query += (
            f"\nWhich single option is correct? "
            f"Please start your answer with 'Answer: [LETTER]' (where LETTER is one of {letters}), "
            "then provide a detailed explanation."
        )
    return query

def extract_answer_letter(rag_response):
    """Extract a single answer letter from a RAG response."""
    # Look for "Answer: X" pattern
    match = re.search(r'Answer:\s*([A-F])', rag_response, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    # Fallback: "The correct answer is X" / "answer is X"
    match = re.search(r'(?:correct answer is|answer is)\s*([A-F])', rag_response, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    # "Option X is correct"
    match = re.search(r'Option\s*([A-F])\s*is\s*correct', rag_response, re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return None


def extract_answer_letters(rag_response):
    """Extract multiple answer letters from a multi-select RAG response.

    Returns a sorted list of unique uppercase letters, e.g. ['A', 'C', 'E'].
    """
    # "Answers: A, C, E" or "Answers: A/C/E"
    match = re.search(
        r'Answers?:\s*([A-F](?:\s*[,/]\s*[A-F])*)',
        rag_response,
        re.IGNORECASE,
    )
    if match:
        return sorted(set(re.findall(r'[A-F]', match.group(1).upper())))

    # Fallback: scan for "A is correct", "option C is correct", etc.
    hits = re.findall(
        r'(?:option\s*)?([A-F])\s+(?:is|are)\s+correct',
        rag_response,
        re.IGNORECASE,
    )
    if hits:
        return sorted(set(h.upper() for h in hits))

    return []