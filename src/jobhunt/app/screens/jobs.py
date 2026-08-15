"""
Jobs screen for JobHunt application
"""
import asyncio
from typing import Optional

from textual.widgets import Static, Button, DataTable
from textual.containers import Container

from .base import BaseScreen
from ...agent import JobHuntAgent
from ...db import JobHuntDB


class JobsScreen(BaseScreen):
    """Jobs screen showing job listings"""
    
    def __init__(self, db: Optional[JobHuntDB] = None):
        super().__init__(name="jobs")
        self.db = db
        self.agent: Optional[JobHuntAgent] = None
        
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
        # Load jobs from database in background to prevent UI freezing
        self.run_worker(self._async_load_jobs, group="jobs", exclusive=True)
    
    async def _async_load_jobs(self):
        """Load jobs asynchronously"""
        try:
            # Get jobs using the agent's list_jobs tool (off the event loop)
            jobs = await asyncio.to_thread(self._list_jobs)
            
            # Update UI with job data
            self.call_after_refresh(self._update_jobs_table, jobs)
            
        except Exception as e:
            # Handle errors by updating with error message
            self.call_after_refresh(self._show_jobs_error, f"Error loading jobs: {e}")

    def _list_jobs(self):
        """Blocking job listing helper, run off the event loop."""
        if self.agent is None:
            self.agent = JobHuntAgent(self.db)
        return self.agent.run_tool("list_jobs")

    def _show_jobs_error(self, message: str):
        """Display an error message in the jobs table."""
        table = self.query_one("#jobs_table", DataTable)
        table.clear()
        table.add_column("Error", key="error", width=40)
        table.add_row(message)
    
    def _update_jobs_table(self, jobs):
        """Update the jobs table with loaded data"""
        # Clear existing table data
        table = self.query_one("#jobs_table", DataTable)
        table.clear()
        
        # Add columns
        table.add_column("ID", key="id", width=10)
        table.add_column("Title", key="title", width=30)
        table.add_column("Company", key="company", width=20)
        table.add_column("Location", key="location", width=15)
        table.add_column("Date", key="date", width=15)
        
        # Add rows from jobs
        for job in jobs[:20]:  # Show top 20 jobs
            table.add_row(
                job.id[:10] + "..." if len(job.id) > 10 else job.id,
                job.title[:30] + "..." if len(job.title) > 30 else job.title,
                job.company[:20] + "..." if len(job.company) > 20 else job.company,
                job.location or "N/A",
                job.posted_date.strftime("%Y-%m-%d") if job.posted_date else "N/A"
            )