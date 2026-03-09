# src/ui/frontend.py
import streamlit as st
from src.ui.backend import CourseraAssistant

def main():
    st.title("Coursera Study Assistant")
    
    # Input section
    with st.expander("Enter Coursera Course URL"):
        course_url = st.text_input("Course URL")
        submit_button = st.button("Start Processing")
    
    # Status section
    with st.expander("Processing Status"):
        status = st.empty()
        progress_bar = st.progress(0)
    
    # Output section
    with st.expander("Study Materials"):
        output = st.empty()
    
    if submit_button and course_url:
        assistant = CourseraAssistant(course_url)
        assistant.start_processing()
        
        # Update status
        status.text("Processing in progress...")
        progress_bar.progress(0.5)
        
        # Show results
        output.write(assistant.get_results())

if __name__ == "__main__":
    main()