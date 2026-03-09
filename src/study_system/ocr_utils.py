# ocr_utils.py
"""OCR utilities for extracting quiz questions from screenshots"""

from PIL import Image, ImageEnhance, ImageOps
import re
import io
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
    """Format a question for RAG query"""
    # Create a clear question for the RAG system
    query = f"{question['text']}\n\nOptions:\n"
    for option in question['options']:
        query += f"{option['letter']}) {option['text']}\n"
    
    query += "\nWhich option is correct? Please start your answer with 'Answer: [LETTER]' (where LETTER is A, B, C, or D), then provide a detailed explanation."
    
    return query

def extract_answer_letter(rag_response):
    """Extract the answer letter (A, B, C, or D) from RAG response
    
    Args:
        rag_response: The RAG system's response text
        
    Returns:
        str: The answer letter (A, B, C, or D), or None if not found
    """
    import re
    
    # Look for "Answer: X" pattern at the start
    match = re.search(r'Answer:\s*([A-D])', rag_response, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Fallback: Look for "The correct answer is X" or "X is correct"
    match = re.search(r'(?:correct answer is|answer is)\s*([A-D])', rag_response, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Another fallback: "Option X is correct"
    match = re.search(r'Option\s*([A-D])\s*is\s*correct', rag_response, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    return None