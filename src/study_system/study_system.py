"""
Coursera Study System - Main CLI
RAG-based interactive study system for Coursera course notes
"""

import argparse
import json
import datetime
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import ollama

from study_db import StudyDatabase, parse_lectures_from_tab

# Configuration
CREDENTIALS_FILE = "../coursera_agent/credentials.json"
DOC_ID = "1mvwZchayzE7jhnoIa5ZkeHJuBtXc5-_CzkmkrRq_6EM"
MODEL_NAME = "granite3.2:8b"
STATS_FILE = "study_data/sessions/stats.json"


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


def answer_question(db: StudyDatabase, question: str) -> str:
    """Answer a question using RAG approach"""
    print(f"\n🔍 Searching notes for: {question}")
    
    # Step 1: Retrieve relevant context
    results = db.query(question, n_results=3)
    
    if not results['documents'] or not results['documents'][0]:
        return "❌ No relevant content found in notes. Try rephrasing your question."
    
    # Step 2: Build context from top results
    context_parts = []
    for i, doc in enumerate(results['documents'][0]):
        metadata = results['metadatas'][0][i]
        context_parts.append(f"[{metadata['title']}]\n{doc}\n")
    
    context = "\n---\n".join(context_parts)
    
    # Step 3: Generate answer with Ollama
    prompt = f"""You are a helpful AI tutor for IBM AI Engineering certification courses.

Use ONLY the following course notes to answer the student's question. If the answer isn't in the notes, say so.

Course Notes:
{context}

Student Question: {question}

Provide a clear, concise answer based on the notes above. Use technical terms from the course material."""
    
    print(f"🤖 Generating answer...")
    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}]
        )
        
        answer = response["message"]["content"]
        
        # Show sources
        sources = [f"• {results['metadatas'][0][i]['title']}" 
                   for i in range(len(results['documents'][0]))]
        
        return f"{answer}\n\n📚 Sources:\n" + "\n".join(sources)
    
    except Exception as e:
        return f"❌ Error generating answer: {e}\nMake sure Ollama is running: ollama serve"


def sync_notes(db: StudyDatabase) -> None:
    """Sync notes from Google Doc to local database"""
    print("📥 Fetching notes from Google Doc...")
    
    tabs_content = fetch_doc_content(DOC_ID)
    
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
