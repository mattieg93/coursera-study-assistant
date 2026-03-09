#!/usr/bin/env python3
"""Debug version of OCR test script"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'study_system'))
from ocr_utils import extract_text_from_image
import re

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_ocr_debug.py <image_path>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    print(f"🔍 Extracting text from: {image_path}")
    print("=" * 80)
    
    # Extract text
    with open(image_path, 'rb') as f:
        extracted_text = extract_text_from_image(f)
    
    print("\n📄 EXTRACTED TEXT:")
    print("-" * 80)
    print(extracted_text)
    print("-" * 80)
    
    # Manual parse with debug
    lines = extracted_text.split('\n')
    print(f"\n🔍 DEBUG: Found {len(lines)} lines total")
    
    question_lines = []
    for i, line in enumerate(lines):
        line_clean = line.strip()
        # Check if line is a question (numbered or starts with question word)
        if re.match(r'^\d+[\.\)]', line_clean) or re.match(r'^(What|Which|How|Why)', line_clean, re.IGNORECASE):
            question_lines.append((i, line_clean))
    
    print(f"\n🎯 DEBUG: Detected {len(question_lines)} potential question lines:")
    for idx, (line_num, text) in enumerate(question_lines):
        print(f"  Q{idx+1} at line {line_num}: {text[:60]}...")
    
    # Now run the actual parser
    from ocr_utils import parse_multiple_choice_questions
    questions = parse_multiple_choice_questions(extracted_text)
    
    print(f"\n✅ PARSED: {len(questions)} question(s)")
    for q in questions:
        print(f"  Q{q['number']}: {len(q['options'])} options")

if __name__ == "__main__":
    main()
