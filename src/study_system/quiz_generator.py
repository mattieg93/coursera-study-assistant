"""
Quiz Generation Module for Coursera Study System
Generates practice quizzes from course notes using LLM
"""

import ollama
import random
import re
from typing import List, Dict, Optional

MODEL_NAME = "granite3.2:8b"


def generate_quiz(db, num_questions: int = 5, difficulty: str = "medium") -> List[Dict]:
    """Generate a quiz from course notes"""
    print(f"\n📝 Generating {num_questions}-question quiz ({difficulty} difficulty)...")
    
    # Get random lectures
    all_lectures = db.get_all_lectures()
    
    if not all_lectures:
        print("❌ No lectures found in database. Run: python study_system.py --sync")
        return []
    
    selected_lectures = random.sample(all_lectures, min(num_questions, len(all_lectures)))
    
    questions = []
    for i, lecture in enumerate(selected_lectures):
        print(f"   Generating question {i+1}/{num_questions}...", end="\r")
        question = generate_question_from_lecture(lecture, difficulty)
        if question:
            questions.append(question)
    
    print(f"   ✅ Generated {len(questions)} questions              ")
    return questions[:num_questions]


def generate_question_from_lecture(lecture: Dict, difficulty: str) -> Optional[Dict]:
    """Generate a single multiple-choice question"""
    prompt = f"""Create a {difficulty} difficulty multiple-choice question from this lecture.

Lecture: {lecture['title']}
Content: {lecture['content'][:800]}

Generate:
1. A clear question about a key concept
2. Four answer options (A, B, C, D)
3. The correct answer letter
4. A brief explanation

Format:
QUESTION: [question text]
A) [option]
B) [option]
C) [option]
D) [option]
CORRECT: [letter]
EXPLANATION: [why this answer is correct]"""
    
    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return parse_quiz_response(response["message"]["content"], lecture['title'])
    
    except Exception as e:
        print(f"\n⚠️  Error generating question: {e}")
        return None


def parse_quiz_response(text: str, source: str) -> Dict:
    """Parse LLM response into structured question"""
    question = {
        'source': source,
        'question': '',
        'options': {},
        'correct': '',
        'explanation': ''
    }
    
    # Extract question
    q_match = re.search(r'QUESTION:\s*(.+?)(?=\n[A-D]\))', text, re.DOTALL)
    if q_match:
        question['question'] = q_match.group(1).strip()
    
    # Extract options
    for letter in ['A', 'B', 'C', 'D']:
        opt_match = re.search(rf'{letter}\)\s*(.+?)(?=\n[A-D]\)|\nCORRECT:)', text, re.DOTALL)
        if opt_match:
            question['options'][letter] = opt_match.group(1).strip()
    
    # Extract correct answer
    correct_match = re.search(r'CORRECT:\s*([A-D])', text)
    if correct_match:
        question['correct'] = correct_match.group(1)
    
    # Extract explanation
    exp_match = re.search(r'EXPLANATION:\s*(.+)', text, re.DOTALL)
    if exp_match:
        question['explanation'] = exp_match.group(1).strip()
    
    return question


def run_quiz(questions: List[Dict]) -> tuple:
    """Interactive quiz session"""
    print("\n" + "="*60)
    print("🎓 COURSERA STUDY QUIZ")
    print("="*60 + "\n")
    
    score = 0
    
    for i, q in enumerate(questions):
        print(f"\nQuestion {i+1}/{len(questions)} [from: {q['source']}]")
        print(f"\n{q['question']}\n")
        
        for letter in ['A', 'B', 'C', 'D']:
            if letter in q['options']:
                print(f"{letter}) {q['options'][letter]}")
        
        # Get user answer
        while True:
            answer = input("\nYour answer (A/B/C/D): ").strip().upper()
            if answer in ['A', 'B', 'C', 'D']:
                break
            print("❌ Please enter A, B, C, or D")
        
        # Check answer
        if answer == q['correct']:
            print("✅ Correct!")
            score += 1
        else:
            print(f"❌ Incorrect. The correct answer is {q['correct']}")
        
        print(f"\n💡 Explanation: {q['explanation']}")
        print("-" * 60)
    
    # Final score
    percentage = (score / len(questions)) * 100
    print(f"\n🎯 Final Score: {score}/{len(questions)} ({percentage:.0f}%)")
    
    if percentage >= 80:
        print("🌟 Excellent work!")
    elif percentage >= 60:
        print("👍 Good job! Review the topics you missed.")
    else:
        print("📚 Keep studying! You'll get there.")
    
    return score, len(questions)
