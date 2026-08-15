"""
Jobs screen for JobHunt application
"""
from .base import BaseScreen
from textual.widgets import Static, Button, DataTable
from textual.containers import Container, Vertical
from .. import jobhunt_app


class JobsScreen(BaseScreen):
    """Jobs screen showing job listings"""
    
    def __init__(self):
        super().__init__(name="jobs")
        
    def _get_content(self):
        return Container(
            Static("Job Listings", id="jobs_title"),
            DataTable(id="jobs_table"),
            Button("Refresh", id="refresh_button"),
            id="jobs_content"
        )
    
    def on_mount(self):
        """Initialize the screen when mounted"""
        self._load_jobs()
        
    def on_button_pressed(self, event):
        """Handle button presses"""
        if event.button.id == "refresh_button":
            self._load_jobs()
    
    def _load_jobs(self):
        """Load jobs into the table"""
        # This is a placeholder implementation for now
        # Needs to be updated with actual job loading logic
        
        # For now, just update the table with placeholder data
        table = self.query_one("#jobs_table", DataTable)
        table.clear()
        
        # Add some columns
        table.add_column("ID", key="id", width=10)
        table.add_column("Title", key="title", width=30)
        table.add_column("Company", key="company", width=20)
        table.add_column("Location", key="location", width=15)
        table.add_column("Date", key="date", width=15)
        
        # Add some mock data
        table.add_row("12345", "Software Engineer", "Tech Corp", "San Francisco", "2024-01-01")
        table.add_row("12346", "Product Manager", "Innovate Inc", "New York", "2024-01-02")