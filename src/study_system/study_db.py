"""
Vector Database for Coursera Study System
Simple in-memory vector store using sentence-transformers
Avoids ChromaDB/Pydantic dependency conflicts
"""

import numpy as np
import pickle
import re
from pathlib import Path


class StudyDatabase:
    """Simple in-memory vector store for course notes"""
    
    def __init__(self, persist_dir="./study_data/chromadb"):
        """Initialize vector store"""
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        # Lazy load sentence-transformers model
        self.model = None
        
        # In-memory storage
        self.documents = []
        self.metadatas = []
        self.embeddings = []
        self.ids = []
        
        # Try to load persisted data
        self._load_from_disk()
    
    def _get_model(self):
        """Lazy load sentence-transformers model"""
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            print("🔄 Loading embedding model (first time only)...")
            self.model = SentenceTransformer("all-MiniLM-L6-v2")
        return self.model
    
    def _save_to_disk(self) -> None:
        """Save database to disk"""
        data = {
            'documents': self.documents,
            'metadatas': self.metadatas,
            'embeddings': self.embeddings,
            'ids': self.ids
        }
        with open(self.persist_dir / "study_db.pkl", 'wb') as f:
            pickle.dump(data, f)
    
    def _load_from_disk(self) -> None:
        """Load database from disk if it exists"""
        db_file = self.persist_dir / "study_db.pkl"
        if db_file.exists():
            try:
                with open(db_file, 'rb') as f:
                    data = pickle.load(f)
                    self.documents = data['documents']
                    self.metadatas = data['metadatas']
                    self.embeddings = data['embeddings']
                    self.ids = data['ids']
                    print(f"✅ Loaded {len(self.documents)} documents from disk")
            except Exception as e:
                print(f"⚠️  Could not load persisted data: {e}")
    
    def add_lectures(self, lectures: list) -> None:
        """Add parsed lectures to vector database"""
        model = self._get_model()
        
        new_documents = []
        new_metadatas = []
        new_ids = []
        
        for i, lecture in enumerate(lectures):
            # Store full lecture
            doc_id = f"{lecture['tab']}_{i}"
            new_documents.append(lecture['content'])
            new_metadatas.append({
                'tab': lecture['tab'],
                'title': lecture['title'],
                'type': 'full_lecture'
            })
            new_ids.append(doc_id)
            
            # Also store individual sections for better retrieval
            for section_type, section_content in lecture['sections'].items():
                if section_content:
                    section_id = f"{doc_id}_{section_type}"
                    new_documents.append(section_content)
                    new_metadatas.append({
                        'tab': lecture['tab'],
                        'title': lecture['title'],
                        'type': section_type
                    })
                    new_ids.append(section_id)
        
        # Generate embeddings
        print(f"🔄 Generating embeddings for {len(new_documents)} documents...")
        new_embeddings = model.encode(new_documents, show_progress_bar=True)
        
        # Add to store
        self.documents.extend(new_documents)
        self.metadatas.extend(new_metadatas)
        self.embeddings.extend(new_embeddings.tolist())
        self.ids.extend(new_ids)
        
        # Save
        self._save_to_disk()
        print(f"✅ Added {len(new_documents)} documents to database")
    
    def query(self, question: str, n_results: int = 5) -> dict:
        """Semantic search for relevant content"""
        if not self.documents:
            return {'documents': [[]], 'metadatas': [[]]}
        
        model = self._get_model()
        
        # Encode question
        query_embedding = model.encode([question])[0]
        
        # Compute similarities
        similarities = []
        for doc_embedding in self.embeddings:
            # Cosine similarity
            sim = np.dot(query_embedding, doc_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding) + 1e-10
            )
            similarities.append(sim)
        
        # Get top n_results
        top_indices = np.argsort(similarities)[-n_results:][::-1]
        
        top_docs = [self.documents[i] for i in top_indices]
        top_metadatas = [self.metadatas[i] for i in top_indices]
        
        return {
            'documents': [top_docs],
            'metadatas': [top_metadatas]
        }
    
    def get_all_lectures(self) -> list:
        """Get all unique lectures (for quiz generation)"""
        lectures = []
        seen_titles = set()
        
        for i, metadata in enumerate(self.metadatas):
            if metadata.get('type') == 'full_lecture':
                title = metadata['title']
                if title not in seen_titles:
                    lectures.append({
                        'title': title,
                        'content': self.documents[i],
                        'tab': metadata['tab']
                    })
                    seen_titles.add(title)
        
        return lectures


def parse_lectures_from_tab(tab_name: str, content: str) -> list:
    """Split tab content into individual lectures"""
    # Notes format: Title, then emoji sections
    # Split on pattern: word characters followed by newlines then emoji
    lecture_pattern = r'([^\n]+)\n\n📊'
    
    lectures = []
    parts = re.split(lecture_pattern, content)
    
    for i in range(1, len(parts), 2):
        if i+1 < len(parts):
            title = parts[i].strip()
            body = '📊' + parts[i+1]
            
            lectures.append({
                'tab': tab_name,
                'title': title,
                'content': body,
                'sections': parse_sections(body)
            })
    
    return lectures


def parse_sections(content: str) -> dict:
    """Split lecture into semantic sections"""
    sections = {}
    
    # Extract sections by emoji markers
    if '📊 TECHNICAL SUMMARY' in content:
        sections['summary'] = extract_between(content, '📊 TECHNICAL SUMMARY', 'Key Features')
    
    if 'Key Features' in content:
        sections['features'] = extract_between(content, 'Key Features', 'Key Concepts')
    
    if 'Key Concepts' in content:
        sections['concepts'] = extract_between(content, 'Key Concepts', '💼 BUSINESS APPLICATION')
    
    if '💼 BUSINESS APPLICATION' in content:
        sections['business'] = extract_after(content, '💼 BUSINESS APPLICATION')
    
    return sections


def extract_between(text: str, start: str, end: str) -> str:
    """Extract text between two markers"""
    start_idx = text.find(start)
    end_idx = text.find(end, start_idx)
    if start_idx != -1 and end_idx != -1:
        return text[start_idx:end_idx].strip()
    return ""


def extract_after(text: str, marker: str) -> str:
    """Extract text after a marker"""
    idx = text.find(marker)
    if idx != -1:
        return text[idx:].strip()
    return ""
