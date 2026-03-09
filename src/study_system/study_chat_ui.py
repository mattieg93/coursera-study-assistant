# study_chat_ui.py
import streamlit as st
import json
import re
import os
from datetime import datetime
from study_system import answer_question, sync_notes
from study_db import StudyDatabase, parse_sections
from ocr_utils import extract_text_from_image, parse_multiple_choice_questions, format_question_for_display, format_question_for_rag, extract_answer_letter

st.set_page_config(page_title="Coursera Study Assistant", page_icon="🎓")
st.title("🎓 Coursera Study Assistant")

# Initialize database
if 'db' not in st.session_state:
    st.session_state.db = StudyDatabase()

# Chat history
if 'messages' not in st.session_state:
    st.session_state.messages = []

# Store last quiz for corrections
if 'last_quiz' not in st.session_state:
    st.session_state.last_quiz = None

def parse_correction_message(message):
    """
    Parse natural language correction messages.
    Returns: (question_num, correct_answer) or (None, None)
    
    Examples:
    - "Question 2 was wrong, answer is C"
    - "Q3 is incorrect, the correct answer is B"
    - "Fix question 1, it should be A"
    - "#4 wrong, it's D"
    """
    message = message.lower().strip()
    
    # Pattern 1: "question X ... answer is Y" or "q X ... answer Y"
    match = re.search(r'(?:question|q)\s*[#]?\s*(\d+).+?(?:answer\s*(?:is|:|=)?\s*)?([a-d])(?:[\)\.]|\s|$)', message)
    if match:
        return int(match.group(1)), match.group(2).upper()
    
    # Pattern 2: "#X wrong/incorrect ... Y" or "X is wrong ... Y"
    match = re.search(r'[#]?\s*(\d+)\s*(?:is|was)?\s*(?:wrong|incorrect|false).+?([a-d])(?:[\)\.]|\s|$)', message)
    if match:
        return int(match.group(1)), match.group(2).upper()
    
    # Pattern 3: "fix/correct X ... Y"
    match = re.search(r'(?:fix|correct)\s*(?:question|q)?\s*[#]?\s*(\d+).+?([a-d])(?:[\)\.]|\s|$)', message)
    if match:
        return int(match.group(1)), match.group(2).upper()
    
    return None, None

def save_quiz_feedback(question_num, correct_answer, question_data):
    """
    Save quiz correction feedback to study_data/quiz_feedback.json
    """
    feedback_file = os.path.join('study_data', 'quiz_feedback.json')
    
    # Load existing feedback
    if os.path.exists(feedback_file):
        with open(feedback_file, 'r') as f:
            feedback_data = json.load(f)
    else:
        feedback_data = {"corrections": []}
    
    # Convert options list to dict for lookup
    options_dict = {opt['letter']: opt['text'] for opt in question_data.get('options', [])}
    
    # Create correction entry
    correction = {
        "timestamp": datetime.now().isoformat(),
        "question_number": question_num,
        "question_text": question_data['text'],
        "options": options_dict,
        "ai_answer": question_data.get('ai_answer', 'Unknown'),
        "correct_answer": correct_answer,
        "correct_option_text": options_dict.get(correct_answer, 'Unknown')
    }
    
    feedback_data["corrections"].append(correction)
    
    # Save back to file
    os.makedirs('study_data', exist_ok=True)
    with open(feedback_file, 'w') as f:
        json.dump(feedback_data, f, indent=2)
    
    # Optionally add correction to knowledge base for future reference
    correction_text = f"""Quiz Correction:
Question: {question_data['text']}

Correct Answer: {correct_answer}) {options_dict.get(correct_answer, 'Unknown')}

Note: This question was previously answered incorrectly as {question_data.get('ai_answer', 'Unknown')}. The correct answer is {correct_answer}.
"""
    
    lecture = {
        'tab': 'Quiz Corrections',
        'title': f"Correction - Q{question_num}",
        'content': correction_text,
        'sections': [{'heading': f'Question {question_num}', 'content': correction_text}]
    }
    
    return lecture

# Display chat
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Image upload for quiz screenshots
st.markdown("---")

# Tabs for upload vs paste
tab1, tab2 = st.tabs(["📁 Upload File", "📋 Paste from Clipboard"])

with tab1:
    quiz_image = st.file_uploader("Drag & drop or browse for image", type=['png', 'jpg', 'jpeg'], key="quiz_upload", label_visibility="collapsed")
    if quiz_image and st.button("Extract & Answer", key="upload_btn"):
        st.session_state.messages.append({"role": "user", "content": "📸 *Uploaded quiz screenshot*"})
        
        with st.spinner("🔍 Extracting questions from image..."):
            extracted_text = extract_text_from_image(quiz_image)
            questions = parse_multiple_choice_questions(extracted_text)
            
            if questions:
                response_parts = []
                for q in questions:
                    # Get the answer from RAG
                    query = format_question_for_rag(q)
                    answer = answer_question(st.session_state.db, query)
                    
                    # Extract the answer letter
                    answer_letter = extract_answer_letter(answer)
                    
                    # Store AI's answer with the question
                    q['ai_answer'] = answer_letter if answer_letter else 'Unknown'
                    
                    # Build clean response
                    response_parts.append(f"\n### 📝 Question {q['number']}: {q['text']}\n")
                    
                    if answer_letter:
                        # Find the option text for the answer
                        option_text = next((opt['text'] for opt in q['options'] if opt['letter'] == answer_letter), "")
                        response_parts.append(f"**✅ Answer: {answer_letter}) {option_text}**\n")
                    else:
                        response_parts.append(f"**⚠️ Could not extract answer letter**\n")
                    
                    # Show the explanation
                    response_parts.append(f"\n**💡 Explanation:**\n{answer}\n")
                    response_parts.append("\n---\n")
                
                # Store quiz in session state for corrections
                st.session_state.last_quiz = {
                    'questions': questions,
                    'raw_text': extracted_text
                }
                
                response = "\n".join(response_parts)
                response += "\n\n💬 **Found an error?** Just tell me in chat! Example: *'Question 2 was wrong, answer is C'*"
            else:
                response = f"⚠️ Could not detect any multiple choice questions in the image.\n\n**Debug: Extracted Text:**\n```\n{extracted_text[:500]}...\n```\n\n*Tip: Make sure questions are numbered (1., 2.) and options are labeled (A), B), etc.)*"
            
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()

with tab2:
    st.caption("📸 Quick Clipboard Paste:")
    st.code("python clipboard_to_base64.py", language="bash")
    st.caption("1️⃣ Take screenshot (Cmd+Shift+Ctrl+4) • 2️⃣ Run command above • 3️⃣ Paste output below")
    
    # Use data_editor for paste support
    import base64
    import io
    
    pasted_data = st.text_area(
        "Paste base64 image data here",
        height=120,
        placeholder="Paste the base64 string from clipboard_to_base64.py output...",
        key="paste_area",
        label_visibility="collapsed"
    )
    
    if st.button("Extract & Answer", key="paste_btn") and pasted_data:
        try:
            # Try to decode as base64
            if pasted_data.startswith('data:image'):
                # Remove data URL prefix
                pasted_data = pasted_data.split(',')[1]
            
            image_bytes = base64.b64decode(pasted_data)
            quiz_image = io.BytesIO(image_bytes)
            
            st.session_state.messages.append({"role": "user", "content": "📸 *Pasted quiz screenshot*"})
            
            with st.spinner("🔍 Extracting questions from image..."):
                extracted_text = extract_text_from_image(quiz_image)
                questions = parse_multiple_choice_questions(extracted_text)
            
            if questions:
                # Build response message
                response_parts = []
                
                for q in questions:
                    # Get the answer from RAG
                    query = format_question_for_rag(q)
                    answer = answer_question(st.session_state.db, query)
                    
                    # Extract the answer letter
                    answer_letter = extract_answer_letter(answer)
                    
                    # Store AI's answer with the question
                    q['ai_answer'] = answer_letter if answer_letter else 'Unknown'
                    
                    # Build clean response
                    response_parts.append(f"\n### 📝 Question {q['number']}: {q['text']}\n")
                    
                    if answer_letter:
                        # Find the option text for the answer
                        option_text = next((opt['text'] for opt in q['options'] if opt['letter'] == answer_letter), "")
                        response_parts.append(f"**✅ Answer: {answer_letter}) {option_text}**\n")
                    else:
                        response_parts.append(f"**⚠️ Could not extract answer letter**\n")
                    
                    # Show the explanation
                    response_parts.append(f"\n**💡 Explanation:**\n{answer}\n")
                    response_parts.append("\n---\n")
                
                # Store quiz in session state for corrections
                st.session_state.last_quiz = {
                    'questions': questions,
                    'raw_text': extracted_text
                }
                
                response = "\n".join(response_parts)
                response += "\n\n💬 **Found an error?** Just tell me in chat! Example: *'Question 2 was wrong, answer is C'*"
            else:
                response = f"⚠️ Could not detect any multiple choice questions in the image.\n\n**Debug: Extracted Text:**\n```\n{extracted_text[:500]}...\n```"
            
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()
        except Exception as e:
            st.error(f"Error processing pasted data: {str(e)}")
            st.info("💡 Tip: Use the 'Upload File' tab instead, or paste base64 encoded image data")

# Chat input
if prompt := st.chat_input("Ask a question about your course..."):
    # User message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Check if this is a quiz correction
    question_num, correct_answer = parse_correction_message(prompt)
    
    if question_num and correct_answer and st.session_state.last_quiz:
        # This is a correction message
        with st.chat_message("assistant"):
            if 1 <= question_num <= len(st.session_state.last_quiz['questions']):
                question = st.session_state.last_quiz['questions'][question_num - 1]
                
                # Convert options list to dict for display
                options_dict = {opt['letter']: opt['text'] for opt in question.get('options', [])}
                
                # Save the correction
                correction_lecture = save_quiz_feedback(question_num, correct_answer, question)
                st.session_state.db.add_lectures([correction_lecture])
                
                correct_text = options_dict.get(correct_answer, 'Option not found')
                response = f"✅ **Correction saved!**\n\n**Question {question_num}:** {question['text']}\n\n**Correct Answer:** {correct_answer}) {correct_text}\n\n💾 This correction has been added to your knowledge base and will help improve future answers."
            else:
                response = f"⚠️ Question {question_num} not found in the last quiz. The quiz had {len(st.session_state.last_quiz['questions'])} question(s)."
            
            st.markdown(response)
    else:
        # Regular question - use RAG system
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = answer_question(st.session_state.db, prompt)
            st.markdown(response)
    
    st.session_state.messages.append({"role": "assistant", "content": response})

# Sidebar with add content feature
with st.sidebar:
    st.header("📚 Knowledge Base")
    
    # Option 1: Paste text
    with st.expander("✍️ Paste Content"):
        title = st.text_input("Content Title", placeholder="e.g., Transfer Learning Tips")
        pasted_text = st.text_area("Paste your content here", height=200)
        
        if st.button("Add Pasted Content"):
            if title and pasted_text:
                with st.spinner("Adding to knowledge base..."):
                    lecture = {
                        'tab': 'Custom Content',
                        'title': title,
                        'content': pasted_text,
                        'sections': parse_sections(pasted_text)
                    }
                    st.session_state.db.add_lectures([lecture])
                st.success(f"✅ Added: {title}")
            else:
                st.error("Please provide both title and content")
    
    # Option 2: Upload file
    with st.expander("📁 Upload File"):
        uploaded_file = st.file_uploader("Choose a text file", type=['txt', 'md'])
        file_title = st.text_input("File Title", placeholder="e.g., Week 3 Notes")
        
        if uploaded_file and file_title:
            if st.button("Add File Content"):
                with st.spinner("Processing file..."):
                    content = uploaded_file.read().decode('utf-8')
                    lecture = {
                        'tab': 'Custom Content',
                        'title': file_title,
                        'content': content,
                        'sections': parse_sections(content)
                    }
                    st.session_state.db.add_lectures([lecture])
                st.success(f"✅ Added: {file_title}")
    
    st.divider()
    
    # Sync notes from Google Doc
    st.subheader("🔄 Sync Notes")
    if st.button("Sync from Google Doc", use_container_width=True):
        with st.spinner("Syncing notes from Google Doc... (this may take a minute)"):
            try:
                sync_notes(st.session_state.db)
                st.success("✅ Sync complete!")
            except Exception as e:
                st.error(f"❌ Sync failed: {e}")
    
    st.divider()
    
    # Clear chat button
    if st.button("🗑️ Clear Chat History"):
        st.session_state.messages = []
        st.rerun()