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
        # Only update stats if the DOM is mounted
        if self.is_mounted:
            self._update_stats()
        
    def _update_stats(self):
        """Update the dashboard statistics"""
        db_instance = self.database
        
        total_jobs = db_instance.count_jobs()
        total_applications = db_instance.count_applications()
        
        status_widget = self.query_one("#status", Static)
        status_widget.update(f"Total Jobs: {total_jobs} | Applications: {total_applications}")
        
        recent_jobs = db_instance.get_jobs(limit=3)
        activity_widget = self.query_one("#activity_title", Static)
        activity_container = self.query_one("#activity_container", Static)
        
        if recent_jobs:
            activity_widget.update("Recent Activity:")
            lines = []
            for i, job in enumerate(recent_jobs, 1):
                lines.append(f"{i}. {job.title} at {job.company}")
            activity_container.update("\n".join(lines))
        else:
            activity_widget.update("Recent Activity:")
            activity_container.update("- No recent activity")
    
    def _get_content(self):
        return Container(
            Static("Welcome to JobHunt - Local AI Job Search Harness", id="welcome"),
            Static(""),
            Static("Current Status: Ready", id="status"),
            Static(""),
            Static("Recent Activity:", id="activity_title"),
            Static("", id="activity_container"),
            Static(""),
            Static("Quick Actions:", id="actions_title"),
            Button("Search Jobs", id="search_jobs_btn"),
            Button("View Jobs", id="view_jobs_btn"),
            Button("Generate Resume", id="generate_resume_btn"),
            id="dashboard_content"
        )
    
    def on_button_pressed(self, event):
        """Handle button presses for navigation"""
        if event.button.id == "search_jobs_btn":
            self.app.switch_screen("search")
        elif event.button.id == "view_jobs_btn":
            self.app.switch_screen("jobs")
        elif event.button.id == "generate_resume_btn":
            self.app.switch_screen("resume")
        else:
            super().on_button_pressed(event)