"""
Jobs screen for the JobHunt TUI.

Lists saved jobs in a paginated data table with a text filter, reloads on
mount/resume/refresh, and opens a context menu on the clicked row with the
actions that apply to a single job: show its details, discuss it with the
agent, or open its application page in the browser.
"""
import asyncio
import logging
import math
import webbrowser
from typing import List, Optional, Tuple

from textual.containers import Container
from textual.events import Click
from textual.widgets import Button, Input, Static

from ...db import JobHuntDB
from ...models import Job
from ..components import (
    ActionButton,
    ButtonRow,
    ContextMenu,
    RowClickTable,
    ScrollableTextWindow,
    StatusText,
)
from .base import BaseScreen

logger = logging.getLogger(__name__)

PAGE_SIZE = 20


def format_job_card(job_entry: Job) -> str:
    """Render a job as a human-readable card.

    Args:
        job_entry: The job to render.

    Returns:
        The job's metadata followed by its full description.
    """
    posted = (
        job_entry.posted_date.strftime("%Y-%m-%d")
        if job_entry.posted_date
        else "N/A"
    )
    lines = [
        f"Title:     {job_entry.title}",
        f"Company:   {job_entry.company}",
        f"Job ID:    {job_entry.id}",
        f"Posted:    {posted}",
        f"Location:  {job_entry.location or 'N/A'}",
    ]
    if job_entry.salary:
        lines.append(f"Salary:    {job_entry.salary}")
    if job_entry.remote is not None:
        lines.append(f"Remote:    {'yes' if job_entry.remote else 'no'}")
    if job_entry.source:
        lines.append(f"Source:    {job_entry.source}")
    lines.append(f"URL:       {job_entry.url or 'N/A'}")
    lines.append("")
    lines.append("Description")
    lines.append("-" * len("Description"))
    lines.append(job_entry.description or "No description available.")
    return "\n".join(lines)


class JobsScreen(BaseScreen):
    """Screen showing the saved job listings in a paginated table."""

    def __init__(self, database: Optional[JobHuntDB] = None) -> None:
        super().__init__(name="jobs", database=database)
        self._page = 0
        self._filter_text = ""
        self._selected_job: Optional[Job] = None

    def _get_content(self):
        """Compose the jobs body.

        Returns:
            A container with the page title, the filter input, the jobs
            table, the status line, pagination controls, a refresh button,
            the job details pane, and the row context menu (widget ids
            preserved for compatibility).
        """
        return Container(
            self._title("Job Listings", id="jobs_title"),
            Input(placeholder="Filter by title, company, or location", id="jobs_filter_input"),
            RowClickTable(id="jobs_table"),
            self._status("", id="jobs_status"),
            ButtonRow(
                ActionButton("Prev", id="prev_page_btn"),
                ActionButton("Next", id="next_page_btn"),
                ActionButton("Refresh", id="refresh_button"),
                StatusText("Page 1 of 1", id="jobs_page_indicator"),
            ),
            ScrollableTextWindow(id="job_details"),
            ContextMenu(
                Static("", id="job_menu_title", classes="context-menu--title"),
                ActionButton("View Details", id="view_details_btn"),
                ActionButton("Chat About This Job", id="chat_job_btn"),
                ActionButton("Apply", id="apply_btn"),
                id="job_context_menu",
            ),
            id="jobs_content"
        )

    def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        self._load_jobs()

    def on_screen_resume(self) -> None:
        """Reload jobs and close the context menu when the user returns."""
        super().on_screen_resume()
        self._close_job_menu()
        if self.is_mounted:
            self._load_jobs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the pagination, refresh, and job action buttons.

        Args:
            event: The button-pressed event; ``prev_page_btn``/``next_page_btn``
                move between pages, ``refresh_button`` returns to the first
                page, the remaining buttons act on the selected job, and
                everything else is delegated to the base.
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
        elif event.button.id == "view_details_btn":
            self._show_job_details()
        elif event.button.id == "chat_job_btn":
            self._chat_about_job()
        elif event.button.id == "apply_btn":
            self._apply_to_job()

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

    def on_click(self, event: Click) -> None:
        """Dismiss the context menu when the user clicks away from it.

        Args:
            event: The click event; clicks that land on the menu itself are
                left to the menu's own items.
        """
        menu = self.query_one("#job_context_menu", ContextMenu)
        if not menu.display:
            return
        screen_x = event.screen_x or 0
        screen_y = event.screen_y or 0
        if not menu.contains_point(screen_x, screen_y):
            self._close_job_menu()

    def on_row_click_table_row_clicked(self, event) -> None:
        """Open the context menu for the clicked job row.

        Args:
            event: The row-clicked event; its ``row_key`` names the job and
                its screen coordinates anchor the menu.
        """
        self._open_job_menu(event.row_key.value, event.screen_x, event.screen_y)

    def on_data_table_cell_selected(self, event) -> None:
        """Open the context menu when a row is selected with the keyboard.

        Args:
            event: The cell-selected event; its cell key names the job.
                The menu is anchored to the selected row because a keyboard
                selection carries no click coordinates.
        """
        table = self.query_one("#jobs_table", RowClickTable)
        anchor_x, anchor_y = self._row_anchor(table, event.coordinate.row)
        self._open_job_menu(event.cell_key.row_key.value, anchor_x, anchor_y)

    def _open_job_menu(self, job_id: str, x: int, y: int) -> None:
        """Select a job and open its context menu.

        Args:
            job_id: The id of the job the menu belongs to.
            x: The horizontal screen coordinate the menu is anchored at.
            y: The vertical screen coordinate the menu is anchored at.
        """
        self.app.selected_job_id = job_id
        job_entry = self.database.get_job(job_id) if self.database is not None else None
        if job_entry is None:
            self._selected_job = None
            self._set_status(f"Selected job ID: {job_id}")
            return
        self._selected_job = job_entry
        menu = self.query_one("#job_context_menu", ContextMenu)
        menu.open_at(x, y, job_entry.title)

    def _close_job_menu(self) -> None:
        """Hide the row context menu."""
        self.query_one("#job_context_menu", ContextMenu).close()

    def _row_anchor(self, table: RowClickTable, row_index: int) -> Tuple[int, int]:
        """Compute the screen position of a table row.

        Args:
            table: The table holding the row.
            row_index: The index of the row.

        Returns:
            The ``(x, y)`` screen coordinates of the row's first cell.
        """
        header_height = table.header_height if table.show_header else 0
        y = table.region.y + header_height + row_index - table.scroll_offset.y
        return (table.region.x + 1, y)

    def _show_job_details(self) -> None:
        """Render the selected job's card into the details pane."""
        job_entry = self._selected_job
        if job_entry is None:
            return
        details = self.query_one("#job_details", ScrollableTextWindow)
        details.text = format_job_card(job_entry)
        details.display = True
        self._close_job_menu()
        self._set_status(f"Showing details for: {job_entry.title}")

    def _chat_about_job(self) -> None:
        """Hand the selected job to the chat screen and switch to it."""
        job_entry = self._selected_job
        if job_entry is None:
            return
        from .chat import ChatScreen

        try:
            chat_screen = self.app.get_screen("chat", ChatScreen)
        except (KeyError, TypeError) as error:
            logger.warning("Chat screen is unavailable: %s", error)
            self._set_status("Chat screen is unavailable.")
            return
        chat_screen.set_job_context(job_entry)
        self._close_job_menu()
        self.app.switch_screen("chat")

    def _apply_to_job(self) -> None:
        """Open the selected job's application URL in the default browser."""
        job_entry = self._selected_job
        if job_entry is None:
            return
        self._close_job_menu()
        if not job_entry.url:
            self._set_status(f"No application URL for '{job_entry.title}'.")
            return
        self._run_worker(
            self._async_open_url(job_entry.url, job_entry.title),
            "apply",
            loading_message="Opening the job page…",
        )

    async def _async_open_url(self, url: str, title: str) -> None:
        """Open a URL in the default browser off the event loop.

        Args:
            url: The URL to open.
            title: The job title, used for the status message.
        """
        try:
            opened = await asyncio.to_thread(webbrowser.open, url)
        except Exception as error:
            logger.warning("Could not open %s: %s", url, error)
            self.call_after_refresh(
                self._set_status, f"Could not open '{title}' in a browser: {error}"
            )
            return
        if opened:
            self.call_after_refresh(self._set_status, f"Opened '{title}' in your browser.")
        else:
            self.call_after_refresh(
                self._set_status, f"Could not open '{title}' in a browser."
            )

    def _set_status(self, message: str) -> None:
        """Update the jobs status line.

        Args:
            message: The message to display.
        """
        self.query_one("#jobs_status", StatusText).set_message(message)

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
        data_table = self.query_one("#jobs_table", RowClickTable)
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

        data_table = self.query_one("#jobs_table", RowClickTable)
        data_table.clear(columns=True)

        if not jobs:
            data_table.add_column("Message", key="message", width=40)
            if self._filter_text:
                data_table.add_row(f"No jobs match '{self._filter_text}' — try a different filter.")
                self._set_status(f"0 of {total} jobs match '{self._filter_text}'")
            else:
                data_table.add_row("No jobs found. Run a search first, then Refresh.")
                self._set_status("0 jobs in database")
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
        self._set_status(status_message)
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
