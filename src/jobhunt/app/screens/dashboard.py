"""
Dashboard screen for JobHunt application
"""
from .base import BaseScreen
from textual.widgets import Static, Button
from textual.containers import Container, Vertical


class DashboardScreen(BaseScreen):
    """Dashboard screen showing overview"""
    
    def __init__(self):
        super().__init__(name="dashboard")
        
    def _get_content(self):
        return Container(
            Static("Welcome to JobHunt - Local AI Job Search Harness", id="welcome"),
            Static(""),
            Static("Current Status: Ready", id="status"),
            Static(""),
            Static("Recent Activity:", id="activity_title"),
            Static("- No recent activity"),
            Static(""),
            Static("Quick Actions:", id="actions_title"),
            Button("Search Jobs", id="search_jobs_btn"),
            Button("View Jobs", id="view_jobs_btn"),
            Button("Generate Resume", id="generate_resume_btn"),
            id="dashboard_content"
        )