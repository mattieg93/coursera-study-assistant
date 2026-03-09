#!/usr/bin/env python3
"""
Test Apple Vision OCR - Quick accuracy check

Usage:
    python test_vision_ocr.py <image_path>
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from study_system.ocr_utils import USE_VISION, extract_text_from_image, parse_multiple_choice_questions, format_question_for_display

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_vision_ocr.py <image_path>")
        print("Example: python test_vision_ocr.py screenshot.png")
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    print("=" * 80)
    print("Apple Vision OCR Test")
    print("=" * 80)
    
    # Check which OCR engine is being used
    if USE_VISION:
        print("✅ Using Apple Vision Framework (native macOS OCR)")
    else:
        print("⚠️  Apple Vision not available, using fallback OCR")
    
    print(f"\n🔍 Extracting text from: {image_path}\n")
    
    # Extract text
    with open(image_path, 'rb') as f:
        extracted_text = extract_text_from_image(f)
    
    print("📄 RAW EXTRACTED TEXT:")
    print("-" * 80)
    print(extracted_text)
    print("-" * 80)
    
    # Try to parse questions
    print("\n🔎 PARSING QUESTIONS...")
    questions = parse_multiple_choice_questions(extracted_text)
    
    if questions:
        print(f"\n✅ Found {len(questions)} question(s):\n")
        for q in questions:
            print("=" * 80)
            print(format_question_for_display(q))
            print()
    else:
        print("\n❌ Could not parse any questions")
        print("💡 This might be due to:")
        print("   - OCR accuracy issues")
        print("   - Questions not numbered (1., 2., etc.)")
        print("   - Options not labeled (A), B), C), D)")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
