"""
Dashboard screen for JobHunt application
"""
from .base import BaseScreen
from textual.widgets import Static, Button
from textual.containers import Container


class DashboardScreen(BaseScreen):
    """Dashboard screen showing overview"""
    
    def __init__(self, db):
        super().__init__(name="dashboard")
        self.database = db
        
    def on_mount(self):
        """Called when the screen is mounted"""
        # Update stats when dashboard is mounted
        self._update_stats()
        
    def on_screen_resume(self):
        """Called when screen is resumed (e.g., when returning from other screens)"""
        # Update stats when dashboard is resumed to ensure live counts
        self._update_stats()
        
    def _update_stats(self):
        """Update the dashboard statistics"""
        # Get job and application counts
        db_instance = self.database
        
        # Get job and application counts
        total_jobs = db_instance.count_jobs()
        total_applications = db_instance.count_applications()
        
        # Update the status widget
        status_widget = self.query_one("#status", Static)
        status_widget.update(f"Total Jobs: {total_jobs} | Applications: {total_applications}")
        
        # Get recent jobs for activity
        recent_jobs = db_instance.get_jobs(limit=3)
        activity_widget = self.query_one("#activity_title", Static)
        
        # Clear previous activity
        activity_lines = self.query("Static")
        activity_lines = [line for line in activity_lines if line.id and line.id.startswith("activity_")]
        
        # Remove existing activity lines
        for line in activity_lines:
            line.remove()
        
        # Add recent activity
        if recent_jobs:
            activity_widget.update("Recent Activity:")
            for i, job in enumerate(recent_jobs, 1):
                activity_line = Static(f"{i}. {job.title} at {job.company}", id=f"activity_{i}")
                self.query_one("#dashboard_content", Container).mount(activity_line)
        else:
            activity_widget.update("Recent Activity:")
            activity_line = Static("- No recent activity", id="activity_empty")
            self.query_one("#dashboard_content", Container).mount(activity_line)
    
    def _get_content(self):
        return Container(
            Static("Welcome to JobHunt - Local AI Job Search Harness", id="welcome"),
            Static(""),
            Static("Current Status: Ready", id="status"),
            Static(""),
            Static("Recent Activity:", id="activity_title"),
            Static("- No recent activity", id="activity_empty"),
            Static(""),
            Static("Quick Actions:", id="actions_title"),
            Button("Search Jobs", id="search_jobs_btn"),
            Button("View Jobs", id="view_jobs_btn"),
            Button("Generate Resume", id="generate_resume_btn"),
            id="dashboard_content"
        )
    
    def on_button_pressed(self, event):
        """Handle button presses for navigation"""
        super().on_button_pressed(event)
        if event.button.id == "search_jobs_btn":
            self.app.switch_screen("search")
        elif event.button.id == "view_jobs_btn":
            self.app.switch_screen("jobs")
        elif event.button.id == "generate_resume_btn":
            self.app.switch_screen("resume")