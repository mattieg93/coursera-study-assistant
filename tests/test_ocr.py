#!/usr/bin/env python3
"""
Quick OCR test script - Test image OCR extraction

Usage:
    python test_ocr.py <image_path>
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'study_system'))
from ocr_utils import extract_text_from_image, parse_multiple_choice_questions, format_question_for_display

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_ocr.py <image_path>")
        print("Example: python test_ocr.py screenshot.png")
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
    
    # Try to parse questions
    print("\n🎯 PARSING QUESTIONS:")
    print("-" * 80)
    questions = parse_multiple_choice_questions(extracted_text)
    
    if questions:
        print(f"✅ Found {len(questions)} question(s):\n")
        for q in questions:
            print(format_question_for_display(q))
            print("\n" + "-" * 80 + "\n")
    else:
        print("❌ No questions detected")
        print("\n💡 Tips:")
        print("   - Questions should be numbered: 1., 2., 3.")
        print("   - Options should be lettered: A), B), C), D)")
        print("   - Make sure text is clear and high contrast")

if __name__ == "__main__":
    main()
