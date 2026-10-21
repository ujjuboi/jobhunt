"""
Fit screen for the JobHunt TUI.

Ranks saved jobs against the user's profile and shows explainable fit
scores: a live score column plus a per-job breakdown of matched/missing
skills and suggested resume bullets. Jobs are paginated (20 per page) with
a text filter; each newly opened page is ranked on demand.
"""
import asyncio
import math
from typing import Dict, List, Optional, Tuple

from textual.containers import Container
from textual.widgets import DataTable, Input, LoadingIndicator, Static

from ...config import get_scoring_mode
from ...db import JobHuntDB
from ...embeddings import EmbeddingClient
from ...models import FitScore
from ...scoring import ScorePipeline
from ..components import ActionButton, ButtonRow, StatusText
from .base import BaseScreen

PAGE_SIZE = 20


class FitScreen(BaseScreen):
    """Screen showing ranked, explainable job fit scores."""

    def __init__(self, database: Optional[JobHuntDB] = None) -> None:
        super().__init__(name="fit", database=database)
        self._fit_scores: Dict[str, FitScore] = {}
        self._page = 0
        self._filter_text = ""
        self._page_jobs: List = []
        self._page_total = 0
        self._rank_on_render = False

    def _get_content(self):
        """Compose the fit analysis body.

        Returns:
            A container with the page title, the filter input, the status
            line, a loading indicator, the scores table, the detail readout,
            and the Analyze/pagination controls (ids preserved).
        """
        return Container(
            self._title("Job Fit Analysis", id="fit_title"),
            Input(placeholder="Filter by title, company, or location", id="fit_filter_input"),
            self._status("", id="fit_status"),
            LoadingIndicator(id="fit_loading"),
            DataTable(id="fit_table"),
            Static("Select a job to see the fit breakdown.", id="fit_detail"),
            ButtonRow(
                ActionButton("Prev", id="prev_page_btn"),
                ActionButton("Next", id="next_page_btn"),
                ActionButton("Analyze", id="analyze_button"),
                StatusText("Page 1 of 1", id="fit_page_indicator"),
            ),
            id="fit_content"
        )

    def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        self.query_one("#fit_loading", LoadingIndicator).display = False
        self._refresh_jobs()

    def on_screen_resume(self) -> None:
        """Reload the job list whenever the user returns to this screen."""
        if self.is_mounted:
            self._refresh_jobs()

    def on_button_pressed(self, event) -> None:
        """Handle button presses.

        Args:
            event: The button-pressed event; ``analyze_button`` scores the
                current page, ``prev_page_btn``/``next_page_btn`` move
                between pages (ranking each newly opened page), and
                everything else is delegated to the base.
        """
        super().on_button_pressed(event)
        if self._is_busy("fit"):
            return
        if event.button.id == "analyze_button":
            self._analyze()
        elif event.button.id == "prev_page_btn" and self._page > 0:
            self._page -= 1
            self._rank_on_render = True
            self._refresh_jobs()
        elif event.button.id == "next_page_btn":
            self._page += 1
            self._rank_on_render = True
            self._refresh_jobs()

    def on_input_changed(self, event) -> None:
        """Refilter the job list whenever the filter input changes.

        Args:
            event: The input-changed event; only ``fit_filter_input`` is
                handled, everything else is ignored.
        """
        if event.input.id != "fit_filter_input":
            return
        if self._is_busy("fit"):
            return
        self._filter_text = event.input.value
        self._page = 0
        self._rank_on_render = True
        self._refresh_jobs()

    def on_data_table_row_selected(self, event) -> None:
        """Show the fit breakdown for the selected job.

        Args:
            event: The row-selected event, whose ``row_key`` names the job
                whose fit score should be displayed.
        """
        fit_score = self._fit_scores.get(event.row_key.value)
        if not fit_score:
            return
        detail = (
            f"Score: {fit_score.score:.2f}\n\n"
            f"Explanation: {fit_score.explanation}\n\n"
            f"Matched: {', '.join(fit_score.matched_skills) if fit_score.matched_skills else 'None'}\n"
            f"Missing: {', '.join(fit_score.missing_skills) if fit_score.missing_skills else 'None'}\n\n"
            f"Suggested resume bullets:\n"
            + ("\n".join(f"- {bullet}" for bullet in fit_score.suggested_bullets) if fit_score.suggested_bullets else "- (none)")
        )
        self.query_one("#fit_detail", Static).update(detail)

    def _update_status(self, message: Optional[str] = None) -> None:
        """Refresh the fit status line.

        Args:
            message: The explicit status text, or ``None`` to derive one
                from the current database/profile/mode state.
        """
        if message is None:
            if not self.database:
                message = "No database available."
            elif not self.database.get_profile():
                message = "No profile found. Save a profile before scoring jobs."
            else:
                message = f"Mode: {get_scoring_mode()}. Click Analyze to score saved jobs."
        self.query_one("#fit_status", StatusText).set_message(message)

    def _refresh_jobs(self) -> None:
        """Load the current page of jobs (unscored) in the background."""
        if self._is_busy("fit"):
            return
        self._run_worker(self._async_load_jobs, "fit-load")

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
        """Run the unscored job load off the event loop."""
        try:
            jobs, total = await asyncio.to_thread(self._fetch_page)
            self.call_after_refresh(self._render_jobs, jobs, total)
        except Exception as error:
            self.call_after_refresh(self._update_status, f"Error loading jobs: {error}")

    def _render_jobs(self, jobs, total: int) -> None:
        """Render the current page of jobs so the page is never an empty void.

        Already-known fit scores are shown from the cache; unknown ones show
        an em dash. Within the page, scored jobs sort above unscored ones by
        score descending (unscored keep posting order); the rank column is
        the job's position in the full posting-ordered result set, so rank
        numbers are not sequential top-to-bottom. When the page was opened
        via pagination/filtering and a profile exists, the unscored jobs are
        ranked automatically.

        Args:
            jobs: The unscored jobs on the current page.
            total: The number of jobs matching the current filter.
        """
        self._page_jobs = jobs
        self._page_total = total

        # Clamp the page in case a filter change shrank the result set.
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        self._page = min(self._page, total_pages - 1)

        data_table = self.query_one("#fit_table", DataTable)
        data_table.clear(columns=True)

        if not jobs:
            data_table.add_column("Message", key="message", width=40)
            if self._filter_text:
                data_table.add_row(f"No jobs match '{self._filter_text}' — try a different filter.")
                self._update_status(f"0 jobs match '{self._filter_text}'.")
            else:
                data_table.add_row("No jobs found. Run a search first, then Analyze.")
                self._update_status("No jobs in database.")
            self._update_pagination_widgets(0)
            return

        self._add_columns(data_table)
        posting_positions = {
            job_entry.id: index for index, job_entry in enumerate(jobs)
        }
        for job_entry in self._jobs_in_display_order(jobs):
            fit_score = self._fit_scores.get(job_entry.id)
            data_table.add_row(
                str(self._page * PAGE_SIZE + posting_positions[job_entry.id] + 1),
                job_entry.title[:30] + "..." if len(job_entry.title) > 30 else job_entry.title,
                job_entry.company[:20] + "..." if len(job_entry.company) > 20 else job_entry.company,
                job_entry.location or "N/A",
                f"{fit_score.score:.2f}" if fit_score else "—",
                key=job_entry.id,
            )
        self._update_pagination_widgets(total_pages)

        if not self.database or not self.database.get_profile():
            message = (
                f"{total} jobs available. No profile found — "
                "save a profile (Resume screen) before scoring."
            )
        else:
            message = (
                f"{total} jobs available (mode: {get_scoring_mode()}). "
                "Click Analyze to score this page."
            )
        self._update_status(message)

        if self._rank_on_render:
            self._rank_on_render = False
            unscored = [j for j in jobs if j.id not in self._fit_scores]
            if unscored and self.database and self.database.get_profile():
                self._analyze()

    def _jobs_in_display_order(self, jobs: List) -> List:
        """Order a page's jobs for display: scored first, best score first.

        Args:
            jobs: The current page's jobs, in posting order.

        Returns:
            The same jobs with cached-scored ones first, sorted by score
            descending (stable, so ties keep posting order), followed by the
            unscored ones in posting order.
        """
        scored = [job_entry for job_entry in jobs if job_entry.id in self._fit_scores]
        unscored = [job_entry for job_entry in jobs if job_entry.id not in self._fit_scores]
        scored.sort(key=lambda job_entry: self._fit_scores[job_entry.id].score, reverse=True)
        return scored + unscored

    @staticmethod
    def _add_columns(data_table: DataTable) -> None:
        """Add the standard fit-scores columns to a table.

        Args:
            data_table: The table widget to attach the columns to.
        """
        data_table.add_column("Rank", key="rank", width=6)
        data_table.add_column("Title", key="title", width=30)
        data_table.add_column("Company", key="company", width=20)
        data_table.add_column("Location", key="location", width=15)
        data_table.add_column("Score", key="score", width=8)

    def _analyze(self) -> None:
        """Kick off scoring of the current page of jobs against the profile."""
        if self._is_busy("fit"):
            return
        if not self.database or not self.database.get_profile():
            self._update_status("Cannot analyze: no profile found.")
            return
        self._set_loading(True)
        self._update_status(f"Ranking page {self._page + 1} — this may take a moment...")
        self._run_worker(self._async_analyze, "fit")

    async def _async_analyze(self) -> None:
        """Run the scoring pipeline off the event loop."""
        try:
            fit_scores = await asyncio.to_thread(self._run_analysis)
            self.call_after_refresh(self._render_results, fit_scores)
        except Exception as error:
            self.call_after_refresh(self._ranking_failed, f"Error during scoring: {error}")

    def _run_analysis(self) -> list:
        """Blocking scoring helper, run off the event loop.

        Scores only the current page's jobs that are not already cached, so
        revisiting a page never re-ranks known scores.

        Returns:
            The list of :class:`FitScore` results for the unscored jobs.
        """
        profile = self.database.get_profile()
        jobs = self.database.get_jobs(
            limit=PAGE_SIZE,
            offset=self._page * PAGE_SIZE,
            search=self._filter_text or None,
        )
        unscored = [job_entry for job_entry in jobs if job_entry.id not in self._fit_scores]
        if not profile or not unscored:
            return []
        pipeline = ScorePipeline(self.database, EmbeddingClient(), agent=self.agent)
        return pipeline.score(unscored, profile)

    def _render_results(self, fit_scores: list) -> None:
        """Merge freshly scored results into the cache and re-render the page.

        Args:
            fit_scores: The scored job results to display.
        """
        for fit_score in fit_scores:
            self._fit_scores[fit_score.job_id] = fit_score
        self._set_loading(False)
        self._render_jobs(self._page_jobs, self._page_total)
        scored_on_page = sum(1 for j in self._page_jobs if j.id in self._fit_scores)
        if scored_on_page:
            self._update_status(
                f"Scored {scored_on_page} of {len(self._page_jobs)} jobs on this page "
                f"(mode: {get_scoring_mode()})."
            )
        elif fit_scores == []:
            self._update_status(
                "Scoring produced no results — check profile and oMLX, then try again."
            )

    def _ranking_failed(self, message: str) -> None:
        """Hide the loading state and surface a scoring failure.

        Args:
            message: The error text to show on the status line.
        """
        self._set_loading(False)
        self._render_jobs(self._page_jobs, self._page_total)
        self._update_status(message)

    def _set_loading(self, loading: bool) -> None:
        """Toggle the ranking loading state and the controls it locks.

        The filter input is locked too, so the text in the box cannot
        diverge from the filter a ranking run is scoring against.

        Args:
            loading: Whether a ranking run is in progress.
        """
        self.query_one("#fit_loading", LoadingIndicator).display = loading
        self.query_one("#fit_filter_input", Input).disabled = loading
        self._update_pagination_widgets_disabled(loading)

    def _update_pagination_widgets_disabled(self, disabled: bool) -> None:
        """Enable or disable the pagination buttons.

        Args:
            disabled: Whether the prev/next buttons should be disabled
                (used while a ranking run is in progress).
        """
        self.query_one("#prev_page_btn", ActionButton).disabled = disabled
        self.query_one("#next_page_btn", ActionButton).disabled = disabled

    def _update_pagination_widgets(self, total_pages: int) -> None:
        """Sync the page indicator and prev/next button states.

        Args:
            total_pages: The number of pages in the current result set.
        """
        self.query_one("#fit_page_indicator", StatusText).set_message(
            f"Page {self._page + 1} of {max(total_pages, 1)}"
        )
        self.query_one("#prev_page_btn", ActionButton).disabled = self._page <= 0
        self.query_one("#next_page_btn", ActionButton).disabled = (
            self._page >= total_pages - 1
        )
