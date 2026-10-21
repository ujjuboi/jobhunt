"""
Jobs screen for the JobHunt TUI.

Lists saved jobs in a paginated data table with a text filter, reloads on
mount/resume/refresh, and lets the user select a row to remember the chosen
job for later screens.
"""
import asyncio
import math
from typing import List, Optional, Tuple

from textual.containers import Container
from textual.widgets import Button, DataTable, Input

from ...db import JobHuntDB
from ..components import ActionButton, ButtonRow, StatusText
from .base import BaseScreen

PAGE_SIZE = 20


class JobsScreen(BaseScreen):
    """Screen showing the saved job listings in a paginated table."""

    def __init__(self, database: Optional[JobHuntDB] = None) -> None:
        super().__init__(name="jobs", database=database)
        self._page = 0
        self._filter_text = ""

    def _get_content(self):
        """Compose the jobs body.

        Returns:
            A container with the page title, the filter input, the jobs
            table, a status line, pagination controls, and a refresh button
            (widget ids preserved for compatibility).
        """
        return Container(
            self._title("Job Listings", id="jobs_title"),
            Input(placeholder="Filter by title, company, or location", id="jobs_filter_input"),
            DataTable(id="jobs_table"),
            self._status("", id="jobs_status"),
            ButtonRow(
                ActionButton("Prev", id="prev_page_btn"),
                ActionButton("Next", id="next_page_btn"),
                ActionButton("Refresh", id="refresh_button"),
                StatusText("Page 1 of 1", id="jobs_page_indicator"),
            ),
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
        """Handle the pagination and refresh buttons.

        Args:
            event: The button-pressed event; ``prev_page_btn``/``next_page_btn``
                move between pages, ``refresh_button`` returns to the first
                page, and everything else is delegated to the base.
        """
        super().on_button_pressed(event)
        if event.button.id == "refresh_button":
            self._page = 0
            self._load_jobs()
        elif event.button.id == "prev_page_btn" and self._page > 0:
            self._page -= 1
            self._load_jobs()
        elif event.button.id == "next_page_btn":
            self._page += 1
            self._load_jobs()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refilter the jobs whenever the filter input changes.

        Args:
            event: The input-changed event; only ``jobs_filter_input`` is
                handled, everything else is ignored.
        """
        if event.input.id != "jobs_filter_input":
            return
        self._filter_text = event.input.value
        self._page = 0
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
        """Load the current page of jobs into the table without freezing the UI."""
        self._run_worker(
            self._async_load_jobs,
            "jobs",
            loading_message="Loading saved jobs…",
        )

    def _fetch_page(self) -> Tuple[List, int]:
        """Fetch one page of jobs plus the matching total count.

        Runs off the event loop.

        Returns:
            A ``(jobs, total)`` pair for the current page and filter.
        """
        if self.database is None:
            raise RuntimeError("No database available")
        jobs = self.database.get_jobs(
            limit=PAGE_SIZE,
            offset=self._page * PAGE_SIZE,
            search=self._filter_text or None,
        )
        total = self.database.count_jobs(search=self._filter_text or None)
        return jobs, total

    async def _async_load_jobs(self) -> None:
        """Run the job load off the event loop and re-render the table."""
        try:
            jobs, total = await asyncio.to_thread(self._fetch_page)
            self.call_after_refresh(self._update_jobs_table, jobs, total)
        except Exception as error:
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

    def _update_jobs_table(self, jobs, total: int) -> None:
        """Update the jobs table with the current page of data.

        Args:
            jobs: The job objects to render (one page, already sliced).
            total: The number of jobs matching the current filter.
        """
        # Clamp the page in case a filter change shrank the result set.
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        self._page = min(self._page, total_pages - 1)

        data_table = self.query_one("#jobs_table", DataTable)
        data_table.clear(columns=True)

        if not jobs:
            data_table.add_column("Message", key="message", width=40)
            if self._filter_text:
                data_table.add_row(f"No jobs match '{self._filter_text}' — try a different filter.")
                self.query_one("#jobs_status", StatusText).set_message(
                    f"0 of {total} jobs match '{self._filter_text}'"
                )
            else:
                data_table.add_row("No jobs found. Run a search first, then Refresh.")
                self.query_one("#jobs_status", StatusText).set_message("0 jobs in database")
            self._update_pagination_widgets(0)
            return

        # Add columns
        data_table.add_column("ID", key="id", width=10)
        data_table.add_column("Title", key="title", width=30)
        data_table.add_column("Company", key="company", width=20)
        data_table.add_column("Location", key="location", width=15)
        data_table.add_column("Date", key="date", width=15)

        # Add rows from the current page (row key = full job id for selection)
        for job_entry in jobs:
            data_table.add_row(
                job_entry.id[:10] + "..." if len(job_entry.id) > 10 else job_entry.id,
                job_entry.title[:30] + "..." if len(job_entry.title) > 30 else job_entry.title,
                job_entry.company[:20] + "..." if len(job_entry.company) > 20 else job_entry.company,
                job_entry.location or "N/A",
                job_entry.posted_date.strftime("%Y-%m-%d") if job_entry.posted_date else "N/A",
                key=job_entry.id  # Add job ID as key for row selection
            )

        if self._filter_text:
            status_message = (
                f"Showing {len(jobs)} of {total} jobs matching "
                f"'{self._filter_text}' (page {self._page + 1} of {total_pages})"
            )
        else:
            status_message = (
                f"Showing {len(jobs)} of {total} jobs "
                f"(page {self._page + 1} of {total_pages})"
            )
        self.query_one("#jobs_status", StatusText).set_message(status_message)
        self._update_pagination_widgets(total_pages)

    def _update_pagination_widgets(self, total_pages: int) -> None:
        """Sync the page indicator and prev/next button states.

        Args:
            total_pages: The number of pages in the current result set.
        """
        self.query_one("#jobs_page_indicator", StatusText).set_message(
            f"Page {self._page + 1} of {max(total_pages, 1)}"
        )
        self.query_one("#prev_page_btn", ActionButton).disabled = self._page <= 0
        self.query_one("#next_page_btn", ActionButton).disabled = (
            self._page >= total_pages - 1
        )
