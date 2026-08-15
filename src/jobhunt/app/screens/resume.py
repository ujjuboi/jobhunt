"""
Resume screen for JobHunt application
"""
from .base import BaseScreen
from textual.widgets import Static, Button, TextArea
from textual.containers import Container, Vertical


class ResumeScreen(BaseScreen):
    """Resume screen for resume management"""
    
    def __init__(self):
        super().__init__(name="resume")
        
    def _get_content(self):
        return Container(
            Static("Resume Management", id="resume_title"),
            Static("Current Resume: Not configured"),
            TextArea(id="resume_text", read_only=True, show_line_numbers=False),
            Button("Generate New Resume", id="generate_resume_btn"),
            Button("View Template", id="view_template_btn"),
            id="resume_content"
        )