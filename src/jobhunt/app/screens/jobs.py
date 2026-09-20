"""
Jobs screen for the JobHunt TUI.

Lists saved jobs in a data table, reloads on mount/resume/refresh, and lets
the user select a row to remember the chosen job for later screens.
"""
import asyncio
from typing import Optional

from textual.containers import Container
from textual.widgets import Button, DataTable

from ...db import JobHuntDB
from ..components import ActionButton, StatusText
from .base import BaseScreen


class JobsScreen(BaseScreen):
    """Screen showing the saved job listings in a table."""

    def __init__(self, database: Optional[JobHuntDB] = None) -> None:
        super().__init__(name="jobs", database=database)

    def _get_content(self):
        """Compose the jobs body.

        Returns:
            A container with the page title, the jobs table, a status line,
            and a refresh button (widget ids preserved for compatibility).
        """
        return Container(
            self._title("Job Listings", id="jobs_title"),
            DataTable(id="jobs_table"),
            self._status("", id="jobs_status"),
            ActionButton("Refresh", id="refresh_button"),
            id="jobs_content"
        )

    def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        self._load_jobs()

    def on_screen_resume(self) -> None:
        """Reload jobs whenever the user returns to this screen."""
        if self.is_mounted:
            self._load_jobs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the refresh button.

        Args:
            event: The button-pressed event; only ``refresh_button`` is
                handled, everything else is delegated to the base.
        """
        super().on_button_pressed(event)
        if event.button.id == "refresh_button":
            self._load_jobs()

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection events.

        Args:
            event: The row-selected event; stores the job id on the app and
                reflects the selection in the status line.
        """
        if event.row_key is not None:
            job_id = event.row_key.value
            self.app.selected_job_id = job_id
            # Get the job details for display
            if self.database is not None:
                job_entry = self.database.get_job(job_id)
                if job_entry:
                    status_text = f"Selected: {job_entry.title}"
                else:
                    status_text = f"Selected job ID: {job_id}"
            else:
                status_text = f"Selected job ID: {job_id}"
            self.query_one("#jobs_status", StatusText).set_message(status_text)

    def _load_jobs(self) -> None:
        """Load jobs into the table without freezing the UI."""
        self._run_worker(self._async_load_jobs, "jobs")

    async def _async_load_jobs(self) -> None:
        """Run the job load off the event loop and re-render the table."""
        try:
            # Get jobs using the agent's list_jobs tool (off the event loop)
            jobs = await asyncio.to_thread(self._list_jobs)

            # Update UI with job data
            self.call_after_refresh(self._update_jobs_table, jobs)

        except Exception as error:
            # Handle errors by updating with error message
            self.call_after_refresh(self._show_jobs_error, f"Error loading jobs: {error}")

    def _show_jobs_error(self, message: str) -> None:
        """Display an error message in the jobs table.

        Args:
            message: The error text to render in place of the table body.
        """
        data_table = self.query_one("#jobs_table", DataTable)
        data_table.clear(columns=True)
        data_table.add_column("Error", key="error", width=40)
        data_table.add_row(message)

    def _update_jobs_table(self, jobs) -> None:
        """Update the jobs table with the loaded data.

        Args:
            jobs: The job objects to render (up to the first 20).
        """
        # Clear existing table data (including columns for a clean re-render)
        data_table = self.query_one("#jobs_table", DataTable)
        data_table.clear(columns=True)

        if not jobs:
            data_table.add_column("Message", key="message", width=40)
            data_table.add_row("No jobs found. Run a search first, then Refresh.")
            self.query_one("#jobs_status", StatusText).set_message("0 jobs in database")
            return

        # Add columns
        data_table.add_column("ID", key="id", width=10)
        data_table.add_column("Title", key="title", width=30)
        data_table.add_column("Company", key="company", width=20)
        data_table.add_column("Location", key="location", width=15)
        data_table.add_column("Date", key="date", width=15)

        # Add rows from jobs
        for job_entry in jobs[:20]:  # Show top 20 jobs
            data_table.add_row(
                job_entry.id[:10] + "..." if len(job_entry.id) > 10 else job_entry.id,
                job_entry.title[:30] + "..." if len(job_entry.title) > 30 else job_entry.title,
                job_entry.company[:20] + "..." if len(job_entry.company) > 20 else job_entry.company,
                job_entry.location or "N/A",
                job_entry.posted_date.strftime("%Y-%m-%d") if job_entry.posted_date else "N/A",
                key=job_entry.id  # Add job ID as key for row selection
            )
        total = self.database.count_jobs() if self.database else len(jobs)
        self.query_one("#jobs_status", StatusText).set_message(
            f"Showing {min(len(jobs), 20)} of {total} jobs"
        )