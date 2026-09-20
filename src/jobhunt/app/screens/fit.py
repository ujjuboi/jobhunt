"""
Fit screen for the JobHunt TUI.

Ranks saved jobs against the user's profile and shows explainable fit
scores: a live score column plus a per-job breakdown of matched/missing
skills and suggested resume bullets.
"""
import asyncio
from typing import Dict, Optional

from textual.containers import Container
from textual.widgets import DataTable, Static

from ...config import get_scoring_mode
from ...db import JobHuntDB
from ...embeddings import EmbeddingClient
from ...models import FitScore
from ...scoring import ScorePipeline
from ..components import ActionButton, AgentUnavailableError, StatusText
from .base import BaseScreen


class FitScreen(BaseScreen):
    """Screen showing ranked, explainable job fit scores."""

    def __init__(self, database: Optional[JobHuntDB] = None) -> None:
        super().__init__(name="fit", database=database)
        self._fit_scores: Dict[str, FitScore] = {}

    def _get_content(self):
        """Compose the fit analysis body.

        Returns:
            A container with the page title, status line, scores table,
            the detail readout, and the Analyze button (ids preserved).
        """
        return Container(
            self._title("Job Fit Analysis", id="fit_title"),
            self._status("", id="fit_status"),
            DataTable(id="fit_table"),
            Static("Select a job to see the fit breakdown.", id="fit_detail"),
            ActionButton("Analyze", id="analyze_button"),
            id="fit_content"
        )

    def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        self._refresh_jobs()

    def on_screen_resume(self) -> None:
        """Reload the job list whenever the user returns to this screen."""
        if self.is_mounted:
            self._refresh_jobs()

    def on_button_pressed(self, event) -> None:
        """Handle button presses.

        Args:
            event: The button-pressed event; only ``analyze_button`` is
                handled, everything else is delegated to the base.
        """
        super().on_button_pressed(event)
        if event.button.id == "analyze_button":
            self._analyze()

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
        """Load the saved jobs into the table (unscored) in the background."""
        if self._is_busy("fit"):
            return
        self._run_worker(self._async_load_jobs, "fit-load")

    async def _async_load_jobs(self) -> None:
        """Run the unscored job load off the event loop."""
        try:
            jobs = await asyncio.to_thread(self._list_jobs)
            self.call_after_refresh(self._render_jobs, jobs)
        except Exception as error:
            self.call_after_refresh(self._update_status, f"Error loading jobs: {error}")

    def _render_jobs(self, jobs) -> None:
        """Render the job list (unscored) so the page is never an empty void.

        Args:
            jobs: The unscored jobs to display.
        """
        if self._is_busy("fit"):
            return
        data_table = self.query_one("#fit_table", DataTable)
        data_table.clear(columns=True)
        self._fit_scores = {}

        self._add_columns(data_table)
        if not jobs:
            data_table.add_column("Message", key="message", width=40)
            data_table.add_row("No jobs found. Run a search first, then Analyze.")
            self._update_status("No jobs in database.")
            return

        for rank, job_entry in enumerate(jobs, start=1):
            data_table.add_row(
                str(rank),
                job_entry.title[:30] + "..." if len(job_entry.title) > 30 else job_entry.title,
                job_entry.company[:20] + "..." if len(job_entry.company) > 20 else job_entry.company,
                job_entry.location or "N/A",
                "—",
                key=job_entry.id,
            )

        if not self.database or not self.database.get_profile():
            message = (
                f"{len(jobs)} jobs available. No profile found — "
                "save a profile (Resume screen) before scoring."
            )
        else:
            message = (
                f"{len(jobs)} jobs available (mode: {get_scoring_mode()}). "
                "Click Analyze to score."
            )
        self._update_status(message)

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
        """Kick off scoring of the saved jobs against the profile."""
        if self._is_busy("fit"):
            return
        if not self.database or not self.database.get_profile():
            self._update_status("Cannot analyze: no profile found.")
            return
        self._update_status("Scoring...")
        self._run_worker(self._async_analyze, "fit")

    async def _async_analyze(self) -> None:
        """Run the scoring pipeline off the event loop."""
        try:
            fit_scores = await asyncio.to_thread(self._run_analysis)
            self.call_after_refresh(self._render_results, fit_scores)
        except Exception as error:
            self.call_after_refresh(self._update_status, f"Error during scoring: {error}")

    def _run_analysis(self) -> list:
        """Blocking scoring helper, run off the event loop.

        Returns:
            The list of :class:`FitScore` results for the saved jobs.
        """
        profile = self.database.get_profile()
        jobs = self.database.get_jobs(limit=50)
        if not profile or not jobs:
            return []
        pipeline = ScorePipeline(self.database, EmbeddingClient(), agent=self.agent)
        return pipeline.score(jobs, profile)

    def _render_results(self, fit_scores: list) -> None:
        """Render the scored rows plus per-job breakdown availability.

        Args:
            fit_scores: The scored job results to display.
        """
        data_table = self.query_one("#fit_table", DataTable)
        data_table.clear(columns=True)
        self._fit_scores = {}

        if not fit_scores:
            try:
                self._render_jobs(self._list_jobs())
            except AgentUnavailableError as error:
                data_table.add_column("Error", key="error", width=40)
                data_table.add_row(str(error))
            self._update_status("Scoring produced no results — check profile and oMLX, then try again.")
            return

        self._add_columns(data_table)
        for rank, fit_score in enumerate(fit_scores, start=1):
            job_entry = self.database.get_job(fit_score.job_id)
            if not job_entry:
                continue
            data_table.add_row(
                str(rank),
                job_entry.title[:30] + "..." if len(job_entry.title) > 30 else job_entry.title,
                job_entry.company[:20] + "..." if len(job_entry.company) > 20 else job_entry.company,
                job_entry.location or "N/A",
                f"{fit_score.score:.2f}",
                key=fit_score.job_id,
            )
            self._fit_scores[fit_score.job_id] = fit_score

        self._update_status(f"Scored {len(self._fit_scores)} jobs (mode: {get_scoring_mode()}).")