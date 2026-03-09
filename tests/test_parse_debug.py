#!/usr/bin/env python3
"""More detailed debug - trace through parsing"""

import sys
import re

def parse_with_debug(text):
    """Parse with detailed debug output"""
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
        
        print(f"[Line {i}] Processing: '{line[:60]}...'")
        
        # Check for standalone number
        def is_standalone_number(text):
            match = re.match(r'^(\d+)[\.\)]?$', text)
            if match:
                return match.group(1)
            return None
        
        question_num = is_standalone_number(line)
        if question_num and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and len(next_line) > 5:
                line = f"{question_num}. {next_line}"
                i += 1
                print(f"  → Merged with next line: '{line[:60]}...'")
        
        # Check for standalone "A"
        if line == 'A' and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and len(next_line) > 5:
                line = next_line
                i += 1
                print(f"  → Merged 'A' with next line: '{line[:60]}...'")
            else:
                i += 1
                print(f"  → Skipped standalone 'A'")
                continue
        
        # Check if numbered question
        numbered_q = re.match(r'^(\d+)[\.\)]\s+(.+)', line)
        question_words = r'^(What|Which|How|Why|When|Where|Who|Does|Do|Is|Are|Can|Could|Would|Should)'
        is_question_line = re.match(question_words, line, re.IGNORECASE)
        
        is_new_question = False
        if numbered_q:
            is_new_question = True
            print(f"  → NEW QUESTION (numbered): Q{numbered_q.group(1)}")
        elif is_question_line and (not current_question or len(current_options) >= 3):
            is_new_question = True
            print(f"  → NEW QUESTION (keyword): Q{len(questions) + 1}")
        
        if is_new_question:
            if current_question and len(current_options) >= 1:
                print(f"  → Saving Q{current_question['number']} with {len(current_options)} options")
                questions.append(current_question)
            
            current_question = {
                'number': numbered_q.group(1) if numbered_q else str(len(questions) + 1),
                'text': numbered_q.group(2) if numbered_q else line,
                'options': []
            }
            current_options = []
            i += 1
            continue
        
        # Process as option or question continuation
        if current_question:
            if len(current_options) == 0:
                # Might be question continuation
                print(f"  → Checking if question continuation (no options yet)")
                is_clear_option = line.startswith(('To ', 'Transformers', 'Amechanism'))
                if not is_clear_option:
                    current_question['text'] += ' ' + line
                    print(f"  → Appended to question")
                    i += 1
                    continue
            
            # Process as option
            cleaned = line.strip('`_.:;\'')
            is_code_like = (
                bool(re.match(r'^[a-zA-Z_]+$', cleaned)) or
                '`' in line or
                '_' in cleaned or
                (len(cleaned) > 0 and cleaned[0].isupper() and not cleaned.isupper())
            )
            
            if len(current_options) < 4:
                if len(cleaned) > 5 or is_code_like:
                    current_options.append({'letter': '', 'text': cleaned})
                    print(f"  → OPTION {len(current_options)}: '{cleaned}' (code_like={is_code_like})")
                else:
                    print(f"  → Skipped (too short: {len(cleaned)} chars, not code-like)")
        
        i += 1
    
    # Save last question
    if current_question and len(current_options) >= 1:
        print(f"\n→ Saving LAST Q{current_question['number']} with {len(current_options)} options")
        current_question['options'] = current_options
        questions.append(current_question)
    
    return questions

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_parse_debug.py <image_path>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'study_system'))
    from ocr_utils import extract_text_from_image
    with open(image_path, 'rb') as f:
        text = extract_text_from_image(f)
    
    print("=" * 80)
    questions = parse_with_debug(text)
    print("\n" + "=" * 80)
    print(f"\nFINAL: {len(questions)} questions parsed")
    for q in questions:
        print(f"  Q{q['number']}: {q['text'][:40]}... ({len(q['options'])} options)")
