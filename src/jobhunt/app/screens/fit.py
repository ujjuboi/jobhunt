"""
Fit screen for JobHunt application
"""
from .base import BaseScreen
from textual.widgets import Static, Button, DataTable
from textual.containers import Container, Vertical


class FitScreen(BaseScreen):
    """Fit screen showing job fit analysis"""
    
    def __init__(self):
        super().__init__(name="fit")
        
    def _get_content(self):
        return Container(
            Static("Job Fit Analysis", id="fit_title"),
            Static("Select a job to analyze fit:", id="fit_prompt"),
            DataTable(id="fit_table"),
            Button("Analyze", id="analyze_button"),
            id="fit_content"
        )