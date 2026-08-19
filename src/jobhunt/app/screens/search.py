"""
Search screen for JobHunt application
"""
import asyncio
import logging
from typing import List, Optional

from textual.widgets import Static, Input, Button, TextArea
from textual.containers import Container

from .base import BaseScreen
from ...agent import JobHuntAgent
from ...db import JobHuntDB
from ...config.user_config import (
    get_user_config,
    KEYWORD_SOURCES,
    keyword_search_available,
)
from ...models import Job

logger = logging.getLogger(__name__)


class SearchScreen(BaseScreen):
    """Search screen for job searching"""

    def __init__(self, db: Optional[JobHuntDB] = None):
        super().__init__(name="search")
        self.db = db
        self.agent: Optional[JobHuntAgent] = None
        self.all_jobs: List[Job] = []
        self.search_notes: list = []

    # ── layout ────────────────────────────────────────────────────────────

    def _get_content(self):
        return Container(
            Static("Job Search", id="search_title"),
            Static("Enter your search criteria:"),
            Input(placeholder="Job title, keywords, company...", id="search_input"),
            Button("Search / Refresh", id="search_button"),
            Static("", id="search_results_title"),
            TextArea(id="search_results", read_only=True, show_line_numbers=False),
            id="search_content"
        )

    # ── lifecycle ─────────────────────────────────────────────────────────

    def on_mount(self):
        if not keyword_search_available():
            self._set_status("Search requires Indeed or LinkedIn — enable one in Settings.")
            return

        self._set_status("Searching configured sources…")
        self.all_jobs = []
        self._disable_button(True)
        self.run_worker(self._async_browse, group="search", exclusive=True)

    # ── events ────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        super().on_button_pressed(event)
        if event.button.id == "search_button":
            self._disable_button(True)
            self._set_status("Refreshing…")
            self.run_worker(self._async_browse, group="search", exclusive=True)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search_input":
            return
        self._render(event.input.value)

    # ── browse (network) ──────────────────────────────────────────────────

    def _async_browse(self):
        """Async wrapper: runs blocking browse off the event loop."""
        try:
            jobs = asyncio.to_thread(self._browse)
            self.all_jobs = jobs
            query = self.query_one("#search_input", Input).value
            self.call_after_refresh(self._render, query)
        except Exception as exc:
            self.call_after_refresh(self._set_status, f"Error: {exc}")
        finally:
            self.call_after_refresh(self._disable_button, False)

    def _browse(self) -> List[Job]:
        """Blocking config-driven browse, run off the event loop."""
        if self.agent is None:
            self.agent = JobHuntAgent(self.db)

        config = get_user_config()

        if not config.sources.enabled:
            return []

        self.search_notes = []
        all_jobs: List[Job] = []

        for source in config.sources.enabled:
            try:
                if source.lower() in KEYWORD_SOURCES:
                    source_jobs = self.agent.run_tool(
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
                            slug_jobs = self.agent.run_tool(
                                "search_jobs",
                                query="",
                                source=source,
                                company=slug,
                                limit=50,
                                raise_errors=True,
                            )
                            all_jobs.extend(slug_jobs)
                        except Exception as exc:
                            self.search_notes.append(f"{source}/{slug}: {exc}")
            except Exception as exc:
                self.search_notes.append(f"{source}: {exc}")

        all_jobs = self._dedupe(all_jobs)

        if self.search_notes:
            logger.warning("Search notes: %s", self.search_notes)

        return all_jobs

    # ── filtering & rendering ─────────────────────────────────────────────

    def _render(self, query: str) -> None:
        """Filter all_jobs by query and update the results area."""
        filtered = self._filter(self.all_jobs, query) if query else self.all_jobs
        total = len(self.all_jobs)
        text = self._build_text(filtered, query, total)

        self.query_one("#search_results", TextArea).text = text

        if query:
            self._set_status(
                f"Narrowed to {len(filtered)} of {total} jobs"
            )
        else:
            self._set_status(
                f"{total} jobs found"
                + (f" ({len(self.search_notes)} note{'s' if len(self.search_notes) != 1 else ''})"
                   if self.search_notes else "")
            )

    def _filter(self, jobs: List[Job], query: str) -> List[Job]:
        q = query.lower()
        return [
            job for job in jobs
            if self._matches(job, q)
        ]

    @staticmethod
    def _matches(job: Job, q: str) -> bool:
        """Case-insensitive substring check across key fields."""
        haystack = " ".join([
            job.title or "",
            job.company or "",
            job.location or "",
            job.description or "",
            " ".join(job.tags) if job.tags else "",
        ]).lower()
        return q in haystack

    @staticmethod
    def _dedupe(jobs: List[Job]) -> List[Job]:
        seen: set = set()
        out: List[Job] = []
        for job in jobs:
            title = (job.title or "").lower()
            company = (job.company or "").lower()
            key = (title, company) if (title or company) else getattr(job, "id", None)
            if key is not None and key not in seen:
                seen.add(key)
                out.append(job)
        return out

    # ── display helpers ───────────────────────────────────────────────────

    def _build_text(self, jobs: List[Job], query: str, total: int) -> str:
        lines: List[str] = []

        if query:
            lines.append(f"Results for: {query}\n")
        else:
            lines.append("All jobs from configured sources\n")

        if jobs:
            for i, job in enumerate(jobs, 1):
                tag = f" [{job.source}]" if job.source else ""
                lines.append(f"{i}. {job.title} at {job.company}{tag}")
                lines.append(f"   Location: {job.location or 'N/A'}")
                lines.append(f"   URL: {job.url or 'N/A'}")
                lines.append(f"   Posted: {job.posted_date or 'N/A'}\n")
        else:
            lines.append("No jobs found.\n")

        if self.search_notes:
            lines.append("Notes:")
            for note in self.search_notes:
                lines.append(f"  - {note}")

        return "\n".join(lines)

    def _disable_button(self, disabled: bool) -> None:
        self.query_one("#search_button", Button).disabled = disabled

    def _set_status(self, msg: str) -> None:
        self.query_one("#search_results_title", Static).update(msg)
