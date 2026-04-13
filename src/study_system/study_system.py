"""
Coursera Study System - Main CLI
RAG-based interactive study system for Coursera course notes
"""

import argparse
import json
import datetime
import sys
from pathlib import Path

# Ensure this module's directory is on sys.path so bare-module siblings resolve
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import ollama

from study_db import StudyDatabase, parse_lectures_from_tab

# Configuration — all paths are absolute relative to this file's location
_HERE = Path(__file__).parent
CREDENTIALS_FILE = str(_HERE.parent / "coursera_agent" / "credentials.json")
DOC_ID = "1mvwZchayzE7jhnoIa5ZkeHJuBtXc5-_CzkmkrRq_6EM"
import os
MODEL_NAME = os.environ.get("CSA_MODEL", "granite3.2:8b")

# ── Textbook context ──────────────────────────────────────────────────────────
_TEXTBOOKS_FILE = Path(__file__).parent.parent.parent / "textbooks.json"
try:
    with open(_TEXTBOOKS_FILE) as _f:
        TEXTBOOKS = json.load(_f).get("textbooks", [])
except (FileNotFoundError, json.JSONDecodeError) as _e:
    print(f"⚠️  textbooks.json not loaded: {_e}")
    TEXTBOOKS = []
STATS_FILE = str(_HERE / "study_data" / "sessions" / "stats.json")


def fetch_doc_content(doc_id: str) -> dict:
    """Fetch all text content from Google Doc with tabs"""
    try:
        creds = Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=['https://www.googleapis.com/auth/documents.readonly']
        )
        service = build('docs', 'v1', credentials=creds)
        
        doc = service.documents().get(
            documentId=doc_id,
            includeTabsContent=True
        ).execute()
        
        # Extract text from all tabs
        tabs_content = {}
        if 'tabs' in doc:
            for tab in doc['tabs']:
                tab_title = tab.get('tabProperties', {}).get('title', 'Untitled')
                content = extract_text_from_body(tab.get('documentTab', {}).get('body', {}))
                tabs_content[tab_title] = content
        
        return tabs_content
    
    except FileNotFoundError:
        print("❌ Error: credentials.json not found")
        return {}
    except Exception as e:
        print(f"❌ Error fetching document: {e}")
        return {}


def extract_text_from_body(body: dict) -> str:
    """Recursively extract text from document body structure"""
    text = []
    for element in body.get('content', []):
        if 'paragraph' in element:
            for text_run in element['paragraph'].get('elements', []):
                if 'textRun' in text_run:
                    text.append(text_run['textRun']['content'])
    return ''.join(text)


def generate_textbook_notes(topic: str, textbook: dict, model: str = "") -> str:
    """Generate comprehensive notes on a textbook topic/chapter using the model's
    parametric knowledge of the specified textbook.

    Parameters
    ----------
    topic : str
        Free-text description of the chapter/section, e.g. "Chapter 10: Sorting"
    textbook : dict
        Entry from textbooks.json (keys: full_title, authors, ...)
    model : str
        Ollama model name; falls back to MODEL_NAME env var.
    """
    title = topic.strip()
    prompt = f"""You are creating comprehensive professional study notes for a graduate-level course.

The notes are drawn from: {textbook['full_title']} by {textbook['authors']}.
You have deep parametric knowledge of this textbook. Draw on it fully and accurately.

Topic / Chapter requested: {title}

Create notes with this EXACT structure:

FIRST LINE — output the topic title exactly as provided above:
{title}

Then continue with the sections below. Use plain text - NO bold markers, asterisks, or other formatting symbols:

📊 TECHNICAL SUMMARY:
[3-5 sentences explaining what this chapter/section covers, its role in the broader subject, and why it matters]

Key Concepts:
[Include EVERY distinct concept, definition, theorem, algorithm, or formula in this chapter. Do not truncate. Each entry must be detailed enough that a student can answer a quiz or exam question about it.]
1. [Concept / Theorem / Algorithm name]: [Full explanation. Include formal definitions where they exist.]
2. [Concept name]: [Full explanation]
[Continue for all concepts...]

Mathematical Foundations:
[Include ALL relevant formulas, recurrences, proofs, and notation used in this chapter. Write math in plain text, e.g. T(n) = 2T(n/2) + Θ(n). If the chapter has no math, omit this section.]
1. [Formula or recurrence name]: [Statement and meaning]
   Derivation / Proof sketch: [Key steps if non-trivial]
2. [Next formula...]

Key Features / Algorithms:
[For each algorithm or technique: describe inputs/outputs, step-by-step logic, time complexity, space complexity, and any important edge cases.]
1. [Algorithm name]:
   • What it does: ...
   • Time complexity: ...
   • Space complexity: ...
   • Key insight / why it works: ...
2. [Next algorithm...]

Common Misconceptions / Exam Traps:
[List subtle distinctions, common errors, and tricky edge cases from this chapter. Include any "gotchas" a student might miss.]
• [Misconception or trap]
• [Another if present]

💼 PRACTICAL APPLICATION:
[3-5 sentences on real-world use cases, when to choose one algorithm/method over another, and connections to other chapters or fields.]

CRITICAL RULES:
- MUST start with the exact topic title as the first line
- NO bold markers (**), asterisks (*), or other formatting symbols
- Use • for bullets
- Be exhaustive: these notes feed a quiz/test knowledge base — omitting a concept means the AI cannot answer questions about it
- Output ONLY the notes content, nothing else"""

    response = ollama.chat(
        model=model or MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
    )
    notes = response["message"]["content"]

    # Ensure title is first line
    if title not in notes.split("\n")[0]:
        notes = f"{title}\n\n{notes}"

    return notes


def answer_question(db: StudyDatabase, question: str, model: str = "", doc_id: str = "", options: list[str] | None = None) -> str:
    """Answer a question using RAG approach"""
    print(f"\n🔍 Searching notes for: {question}")

    # Step 1: Retrieve relevant context
    # C: multi-query — combine results from the full question + each option text
    if options:
        seen_keys: set[str] = set()
        combined_docs: list[str] = []
        combined_metas: list[dict] = []
        stem = question.split("\n")[0]
        queries = [question] + [f"{stem} {opt}" for opt in options[:4]]
        for _q in queries:
            _r = db.query(_q, n_results=3)
            for _doc, _meta in zip(_r["documents"][0], _r["metadatas"][0]):
                _key = _meta["title"] + _doc[:60]
                if _key not in seen_keys:
                    seen_keys.add(_key)
                    combined_docs.append(_doc)
                    combined_metas.append(_meta)
            if len(combined_docs) >= 8:
                break
        results = {"documents": [combined_docs[:8]], "metadatas": [combined_metas[:8]]}
    else:
        results = db.query(question, n_results=5)  # D: bumped from 3

    if not results['documents'] or not results['documents'][0]:
        return "❌ No relevant content found in notes. Try rephrasing your question."

    # Step 2: Build context from top results
    context_parts = []
    for i, doc in enumerate(results['documents'][0]):
        metadata = results['metadatas'][0][i]
        context_parts.append(f"[{metadata['title']}]\n{doc}\n")

    context = "\n---\n".join(context_parts)

    # Step 3: Inject textbook context if the active doc maps to a known textbook
    _textbook_line = ""
    for _tb in TEXTBOOKS:
        if doc_id and doc_id in _tb.get("doc_ids", []):
            _textbook_line = (
                f"The course material is drawn from {_tb['full_title']} "
                f"by {_tb['authors']}. Use your knowledge of this textbook "
                f"to supplement the notes when relevant.\n\n"
            )
            break

    # Step 4: Generate answer with Ollama
    # A: primary source = notes, but general knowledge allowed as supplement
    # B: per-option chain-of-thought before committing to a final answer
    prompt = f"""You are an expert AI tutor for IBM AI Engineering certification courses.
{_textbook_line}
Your permitted knowledge sources, in priority order:
1. The course notes provided below (primary — always prefer these)
2. The course textbook listed above, if any (secondary)
3. Your general training knowledge (last resort only — if and ONLY if sources 1 and 2 are insufficient)

IMPORTANT: If you rely on source 3 for any part of your answer, you MUST add the line:
⚠️ Outside knowledge used: <brief note on what came from general training>

Course Notes:
{context}

---

{question}

Before giving your final answer, briefly evaluate each option (one sentence per option: CORRECT or INCORRECT and why). Then state your final answer in the format requested above."""

    print(f"🤖 Generating answer...")
    try:
        response = ollama.chat(
            model=model or MODEL_NAME,
            messages=[{"role": "user", "content": prompt}]
        )

        answer = response["message"]["content"]

        # Show sources
        sources = [f"• {results['metadatas'][0][i]['title']}"
                   for i in range(len(results['documents'][0]))]

        return f"{answer}\n\n📚 Sources:\n" + "\n".join(sources)

    except Exception as e:
        return f"❌ Error generating answer: {e}\nMake sure Ollama is running: ollama serve"


def answer_questions_batch(
    db: StudyDatabase,
    questions: list[dict],
    model: str = "",
    doc_id: str = "",
) -> list[str] | None:
    """Answer all quiz questions in a single LLM call.

    Does per-question RAG retrieval (CPU, fast), then sends one combined prompt
    with all questions + their contexts.  Returns a list of answer strings
    (same order/length as `questions`), or None if the call or parsing fails
    (caller falls back to per-question answering).
    """
    if not questions:
        return []

    # ── Per-question RAG retrieval ─────────────────────────────────────────
    q_blocks: list[str] = []
    for q in questions:
        opts = [o["text"] for o in q.get("options", [])]
        stem = q["text"].split("\n")[0]
        seen_keys: set[str] = set()
        combined_docs: list[str] = []
        combined_metas: list[dict] = []
        for _qry in [q["text"]] + [f"{stem} {opt}" for opt in opts[:4]]:
            _r = db.query(_qry, n_results=3)
            for _doc, _meta in zip(_r["documents"][0], _r["metadatas"][0]):
                _key = _meta["title"] + _doc[:60]
                if _key not in seen_keys:
                    seen_keys.add(_key)
                    combined_docs.append(_doc)
                    combined_metas.append(_meta)
            if len(combined_docs) >= 6:
                break
        ctx = "\n---\n".join(
            f"[{m['title']}]\n{d}"
            for d, m in zip(combined_docs[:6], combined_metas[:6])
        )
        is_multi = q.get("type", "single") == "multi"
        opts_text = "\n".join(f"{o['letter']}) {o['text']}" for o in q.get("options", []))
        letters = ", ".join(o["letter"] for o in q.get("options", []))
        instruction = (
            "Select ALL correct options. Start your answer line with: Answers: A, C"
            if is_multi else
            f"Choose ONE correct option from {letters}. Start your answer line with: Answer: X"
        )
        q_blocks.append(
            f"===== QUESTION {q['number']} =====\n"
            f"Course notes:\n{ctx}\n\n"
            f"Question: {q['text']}\nOptions:\n{opts_text}\n\n"
            f"{instruction}\n"
            f"Briefly evaluate each option (one sentence each: CORRECT or INCORRECT and why), then give your final answer."
        )

    # ── Textbook hint ──────────────────────────────────────────────────────
    _textbook_line = ""
    for _tb in TEXTBOOKS:
        if doc_id and doc_id in _tb.get("doc_ids", []):
            _textbook_line = (
                f"The course material is drawn from {_tb['full_title']} "
                f"by {_tb['authors']}. Apply your knowledge of this textbook too.\n\n"
            )
            break

    # ── Single combined LLM call ───────────────────────────────────────────
    prompt = (
        "You are an expert AI tutor for IBM AI Engineering certification courses.\n"
        f"{_textbook_line}"
        "Your permitted knowledge sources, in priority order:\n"
        "1. The course notes provided with each question (primary — always prefer these)\n"
        "2. The course textbook listed above, if any (secondary)\n"
        "3. Your general training knowledge (last resort ONLY — use only when sources 1 and 2 are insufficient)\n\n"
        "IMPORTANT: If you rely on source 3 for any part of an answer, you MUST add the line:\n"
        "⚠️ Outside knowledge used: <brief note on what came from general training>\n\n"
        "Answer every question below. For each one respond with:\n"
        "===== ANSWER <number> =====\n"
        "<per-option reasoning>\n"
        "<final answer line>\n"
        "[⚠️ Outside knowledge used: ... — only if applicable]\n\n"
        + "\n\n".join(q_blocks)
    )

    print(f"🤖 Batch-answering {len(questions)} question(s) in one call...")
    try:
        response = ollama.chat(
            model=model or MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response["message"]["content"]

        # Parse ===== ANSWER N ===== sections
        parts = re.split(r"=====\s*ANSWER\s+(\d+)\s*=====", raw, flags=re.IGNORECASE)
        answer_map: dict[int, str] = {}
        for i in range(1, len(parts) - 1, 2):
            try:
                answer_map[int(parts[i])] = parts[i + 1].strip()
            except (ValueError, IndexError):
                pass

        if len(answer_map) < len(questions):
            print(f"   ⚠️  Batch parse yielded {len(answer_map)}/{len(questions)} answers — falling back")
            return None

        results = []
        for q in questions:
            ans = answer_map.get(q["number"])
            if not ans:
                print(f"   ⚠️  Missing batch answer for Q{q['number']} — falling back")
                return None
            results.append(ans)
        return results

    except Exception as e:
        print(f"   ⚠️  Batch answering failed ({e}) — will answer per-question")
        return None


def sync_notes(db: StudyDatabase, doc_id: str = "") -> None:
    """Sync notes from Google Doc to local database"""
    print("📥 Fetching notes from Google Doc...")
    
    tabs_content = fetch_doc_content(doc_id or DOC_ID)
    
    if not tabs_content:
        print("❌ Failed to fetch document content")
        return
    
    print(f"✅ Retrieved {len(tabs_content)} tabs")
    
    all_lectures = []
    for tab_name, content in tabs_content.items():
        lectures = parse_lectures_from_tab(tab_name, content)
        all_lectures.extend(lectures)
        print(f"   • {tab_name}: {len(lectures)} lectures")
    
    print(f"\n📚 Total lectures: {len(all_lectures)}")
    print("💾 Adding to vector database...")
    
    db.add_lectures(all_lectures)

    # E: re-index saved corrections so they survive re-syncs
    _fb_file = _HERE / "study_data" / "quiz_feedback.json"
    if _fb_file.exists():
        try:
            with open(_fb_file) as _fb_f:
                _fb_data = json.load(_fb_f)
            _correction_lectures = []
            for _c in _fb_data.get("corrections", []):
                _opts = _c.get("options", {})
                _opts_lines = "\n".join(f"{k}) {v}" for k, v in _opts.items())
                _ts = _c.get("timestamp", "")[:19].replace(":", "-").replace("T", "_")
                _corr_text = (
                    f"Quiz Correction:\nQuestion: {_c['question_text']}\n\n"
                    f"Options:\n{_opts_lines}\n\n"
                    f"Correct Answer: {_c['correct_answer']}) {_c.get('correct_option_text', '')}\n\n"
                    f"Note: Previously answered incorrectly as {_c.get('ai_answer', 'Unknown')}. "
                    f"The correct answer is {_c['correct_answer']}."
                )
                _correction_lectures.append({
                    "tab": "Quiz Corrections",
                    "title": f"Correction - Q{_c['question_number']} ({_ts})",
                    "content": _corr_text,
                    "sections": {"summary": _corr_text},
                })
            if _correction_lectures:
                db.add_lectures(_correction_lectures)
                print(f"✅ Re-indexed {len(_correction_lectures)} saved correction(s)")
        except Exception as _fb_e:
            print(f"⚠️  Could not re-index quiz corrections: {_fb_e}")

    print("✅ Sync complete!\n")
    log_study_session('sync', lectures_count=len(all_lectures))


def log_study_session(session_type: str, **kwargs) -> None:
    """Log study activity for statistics"""
    Path(STATS_FILE).parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing stats
    if Path(STATS_FILE).exists():
        with open(STATS_FILE, 'r') as f:
            stats = json.load(f)
    else:
        stats = {'sessions': []}
    
    # Add new session
    session = {
        'type': session_type,
        'timestamp': datetime.datetime.now().isoformat(),
        **kwargs
    }
    stats['sessions'].append(session)
    
    # Save
    with open(STATS_FILE, 'w') as f:
        json.dump(stats, f, indent=2)


def show_statistics() -> None:
    """Display study statistics"""
    if not Path(STATS_FILE).exists():
        print("No study sessions recorded yet.")
        return
    
    with open(STATS_FILE, 'r') as f:
        stats = json.load(f)
    
    sessions = stats['sessions']
    
    print("\n📊 STUDY STATISTICS\n")
    print(f"Total sessions: {len(sessions)}")
    
    # Count by type
    qa_count = sum(1 for s in sessions if s['type'] == 'qa')
    quiz_count = sum(1 for s in sessions if s['type'] == 'quiz')
    sync_count = sum(1 for s in sessions if s['type'] == 'sync')
    
    print(f"Sync sessions: {sync_count}")
    print(f"Q&A sessions: {qa_count}")
    print(f"Quizzes taken: {quiz_count}")
    
    # Quiz statistics
    if quiz_count > 0:
        quiz_sessions = [s for s in sessions if s['type'] == 'quiz']
        total_score = sum(s.get('score', 0) for s in quiz_sessions)
        total_questions = sum(s.get('total', 0) for s in quiz_sessions)
        
        if total_questions > 0:
            avg_percentage = (total_score / total_questions) * 100
            print(f"\nQuiz Performance:")
            print(f"  Average score: {avg_percentage:.1f}%")
            print(f"  Total questions answered: {total_questions}")
            print(f"  Total correct: {total_score}")
    
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Coursera Study System - Learn with AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python study_system.py --sync
  python study_system.py --ask "What is transfer learning?"
  python study_system.py --quiz 5 --difficulty medium
  python study_system.py --stats
        """
    )
    parser.add_argument('--sync', action='store_true', help='Sync notes from Google Doc')
    parser.add_argument('--ask', type=str, help='Ask a question about course material')
    parser.add_argument('--quiz', type=int, nargs='?', const=5, help='Take a quiz (optional: number of questions)')
    parser.add_argument('--difficulty', choices=['easy', 'medium', 'hard'], default='medium', help='Quiz difficulty')
    parser.add_argument('--stats', action='store_true', help='View study statistics')
    
    args = parser.parse_args()
    
    # Initialize database
    db = StudyDatabase()
    
    if args.sync:
        sync_notes(db)
    
    elif args.ask:
        answer = answer_question(db, args.ask)
        print(f"\n💡 Answer:\n{answer}\n")
        log_study_session('qa', question=args.ask)
    
    elif args.quiz is not None:
        from quiz_generator import generate_quiz, run_quiz
        questions = generate_quiz(db, num_questions=args.quiz, difficulty=args.difficulty)
        if questions:
            score, total = run_quiz(questions)
            log_study_session('quiz', score=score, total=total, difficulty=args.difficulty)
    
    elif args.stats:
        show_statistics()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
