"""
Search screen for the JobHunt TUI.

Config-driven browse: fetches jobs from every enabled source (company-only
boards via slug, site-wide keyword search for Indeed/LinkedIn), deduplicates
them, and renders them with live client-side filtering as the user types.
"""
import asyncio
import logging
from typing import List, Optional

from textual.containers import Container
from textual.widgets import Button, Input, Static

from ...config.user_config import (
    KEYWORD_SOURCES,
    get_user_config,
    keyword_search_available,
)
from ...db import JobHuntDB
from ...models import Job
from ..components import ActionButton, ButtonRow, ScrollableTextWindow, StatusText
from .base import BaseScreen

logger = logging.getLogger(__name__)


class SearchScreen(BaseScreen):
    """Screen for browsing job boards and filtering results locally."""

    def __init__(self, database: Optional[JobHuntDB] = None) -> None:
        super().__init__(name="search", database=database)
        self.all_jobs: List[Job] = []
        self.search_notes: List[str] = []

    # ── layout ────────────────────────────────────────────────────────────

    def _get_content(self):
        """Compose the search body.

        Returns:
            A container with the page title, query input, action button,
            the status line, and the scrolling results window.
        """
        return Container(
            self._title("Job Search", id="search_title"),
            Static("Enter your search criteria:"),
            ButtonRow(
                Input(placeholder="Job title, keywords, company...", id="search_input"),
                ActionButton("Search / Refresh", id="search_button"),
            ),
            self._status("", id="search_results_title"),
            ScrollableTextWindow(id="search_results"),
            id="search_content"
        )

    # ── lifecycle ─────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        """Auto-browse the configured sources when the screen mounts."""
        if not keyword_search_available():
            self._set_status("Search requires Indeed or LinkedIn — enable one in Settings.")
            return

        self._set_status("Searching configured sources…")
        self.all_jobs = []
        self._disable_button(True)
        self._run_worker(self._async_browse, "search")

    # ── events ────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the refresh button.

        Args:
            event: The button-pressed event; only ``search_button`` is
                handled, everything else is delegated to the base.
        """
        super().on_button_pressed(event)
        if event.button.id == "search_button":
            self._disable_button(True)
            self._set_status("Refreshing…")
            self._run_worker(self._async_browse, "search")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter the results as the user types.

        Args:
            event: The input-changed event; only ``search_input`` is
                handled.
        """
        if event.input.id != "search_input":
            return
        self._render_results(event.input.value)

    # ── browse (network) ──────────────────────────────────────────────────

    async def _async_browse(self) -> None:
        """Async wrapper: runs blocking browse off the event loop."""
        try:
            self.all_jobs = await asyncio.to_thread(self._browse)
            query = self.query_one("#search_input", Input).value
            self.call_after_refresh(self._render_results, query)
        except Exception as error:
            self.call_after_refresh(self._set_status, f"Error: {error}")
        finally:
            self.call_after_refresh(self._disable_button, False)

    def _browse(self) -> List[Job]:
        """Blocking config-driven browse, run off the event loop.

        Returns:
            The deduplicated list of jobs across all enabled sources.
        """
        config = get_user_config()

        if not config.sources.enabled:
            return []

        agent = self._require_agent()

        self.search_notes = []
        all_jobs: List[Job] = []

        for source in config.sources.enabled:
            try:
                if source.lower() in KEYWORD_SOURCES:
                    source_jobs = agent.run_tool(
                        "search_jobs",
                        query="",
                        source=source,
                        company="",
                        limit=50,
                        raise_errors=True,
                    )
                    all_jobs.extend(source_jobs)
                else:
                    companies = config.companies_for(source)
                    if not companies:
                        self.search_notes.append(
                            f"{source}: no companies configured — "
                            "add company slugs in Settings to browse this board."
                        )
                        continue
                    for slug in companies:
                        try:
                            slug_jobs = agent.run_tool(
                                "search_jobs",
                                query="",
                                source=source,
                                company=slug,
                                limit=50,
                                raise_errors=True,
                            )
                            all_jobs.extend(slug_jobs)
                        except Exception as error:
                            self.search_notes.append(f"{source}/{slug}: {error}")
            except Exception as error:
                self.search_notes.append(f"{source}: {error}")

        all_jobs = self._dedupe(all_jobs)

        if self.search_notes:
            logger.warning("Search notes: %s", self.search_notes)

        return all_jobs

    # ── filtering & rendering ─────────────────────────────────────────────

    def _render_results(self, query: str) -> None:
        """Filter ``all_jobs`` by query and update the results area.

        Args:
            query: The current filter text (empty shows everything).
        """
        filtered = self._filter(self.all_jobs, query) if query else self.all_jobs
        total = len(self.all_jobs)
        text = self._build_text(filtered, query, total)

        self.query_one("#search_results", ScrollableTextWindow).text = text

        if query:
            self._set_status(
                f"Narrowed to {len(filtered)} of {total} jobs"
            )
        else:
            message = f"{total} jobs found"
            if self.search_notes:
                note_count = len(self.search_notes)
                plural = "" if note_count == 1 else "s"
                message += f" ({note_count} note{plural})"
            self._set_status(message)

    def _filter(self, jobs: List[Job], query: str) -> List[Job]:
        """Return only the jobs matching the query.

        Args:
            jobs: The full job list to filter.
            query: The lower-cased search text.

        Returns:
            The subset of ``jobs`` whose key fields contain the query.
        """
        lower_query = query.lower()
        return [
            job_entry for job_entry in jobs
            if self._matches(job_entry, lower_query)
        ]

    @staticmethod
    def _matches(job: Job, lower_query: str) -> bool:
        """Case-insensitive substring check across key fields.

        Args:
            job: The job to test.
            lower_query: The lower-cased search text.

        Returns:
            True when the query appears in the job's title, company,
            location, description, or tags.
        """
        haystack = " ".join([
            job.title or "",
            job.company or "",
            job.location or "",
            job.description or "",
            " ".join(job.tags) if job.tags else "",
        ]).lower()
        return lower_query in haystack

    @staticmethod
    def _dedupe(jobs: List[Job]) -> List[Job]:
        """Remove duplicate jobs across sources by (title, company).

        Args:
            jobs: The combined job list, possibly with duplicates.

        Returns:
            A list with one entry per distinct (title, company); jobs with
            an empty title and company fall back to their ID for the key.
        """
        seen_keys: set = set()
        deduplicated: List[Job] = []
        for job_entry in jobs:
            title = (job_entry.title or "").lower()
            company = (job_entry.company or "").lower()
            dedupe_key = (title, company) if (title or company) else getattr(job_entry, "id", None)
            if dedupe_key is not None and dedupe_key not in seen_keys:
                seen_keys.add(dedupe_key)
                deduplicated.append(job_entry)
        return deduplicated

    # ── display helpers ───────────────────────────────────────────────────

    def _build_text(self, jobs: List[Job], query: str, total: int) -> str:
        """Render the filtered jobs as display text.

        Args:
            jobs: The jobs to display after filtering.
            query: The active filter text.
            total: The unfiltered job count.

        Returns:
            A human-readable listing of the matching jobs.
        """
        lines: List[str] = []

        if query:
            lines.append(f"Results for: {query}\n")
        else:
            lines.append("All jobs from configured sources\n")

        if jobs:
            for index, job_entry in enumerate(jobs, 1):
                tag = f" [{job_entry.source}]" if job_entry.source else ""
                lines.append(f"{index}. {job_entry.title} at {job_entry.company}{tag}")
                lines.append(f"   Location: {job_entry.location or 'N/A'}")
                lines.append(f"   URL: {job_entry.url or 'N/A'}")
                lines.append(f"   Posted: {job_entry.posted_date or 'N/A'}\n")
        else:
            lines.append("No jobs found.\n")

        if self.search_notes:
            lines.append("Notes:")
            for note in self.search_notes:
                lines.append(f"  - {note}")

        return "\n".join(lines)

    def _disable_button(self, disabled: bool) -> None:
        """Enable or disable the search button.

        Args:
            disabled: True to disable the button, False to re-enable it.
        """
        self.query_one("#search_button", Button).disabled = disabled

    def _set_status(self, message: str) -> None:
        """Update the status line under the results window.

        Args:
            message: The new status message to display.
        """
        self.query_one("#search_results_title", StatusText).set_message(message)