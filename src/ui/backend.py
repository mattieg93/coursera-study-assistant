# src/ui/backend.py
from src.coursera_agent.coursera_agent import CourseraAgent
from src.study_system.study_system import StudyProcessor
from src.utils.config import load_config

class CourseraAssistant:
    def __init__(self, course_url):
        self.course_url = course_url
        self.agent = CourseraAgent(course_url)
        self.processor = StudyProcessor()
        
    def start_processing(self):
        content = self.agent.retrieve_course_content()
        self.processor.process(content)
        
    def get_results(self):
        return self.processor.get_output()