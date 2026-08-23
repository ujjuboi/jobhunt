"""
Fit screen for JobHunt application
"""
import asyncio
from typing import Optional, Dict

from textual.widgets import Static, Button, DataTable
from textual.containers import Container

from .base import BaseScreen
from ...agent import JobHuntAgent
from ...config import get_scoring_mode
from ...db import JobHuntDB
from ...embeddings import EmbeddingClient
from ...models import FitScore
from ...scoring import ScorePipeline


class FitScreen(BaseScreen):
    """Fit screen showing ranked, explainable job fit scores"""

    def __init__(self, db: Optional[JobHuntDB] = None):
        super().__init__(name="fit")
        self.db = db
        self.agent: Optional[JobHuntAgent] = None
        self._fits: Dict[str, FitScore] = {}

    def _get_content(self):
        return Container(
            Static("Job Fit Analysis", id="fit_title"),
            Static("", id="fit_status"),
            DataTable(id="fit_table"),
            Static("Select a job to see the fit breakdown.", id="fit_detail"),
            Button("Analyze", id="analyze_button"),
            id="fit_content"
        )

    def on_mount(self):
        """Initialize the screen when mounted"""
        self._refresh_jobs()

    def on_screen_resume(self):
        """Reload the job list whenever the user returns to this screen."""
        if self.is_mounted:
            self._refresh_jobs()

    def on_button_pressed(self, event):
        """Handle button presses"""
        super().on_button_pressed(event)
        if event.button.id == "analyze_button":
            self._analyze()

    def on_data_table_row_selected(self, event) -> None:
        """Show the fit breakdown for the selected job."""
        fit = self._fits.get(event.row_key.value)
        if not fit:
            return
        detail = (
            f"Score: {fit.score:.2f}\n\n"
            f"Explanation: {fit.explanation}\n\n"
            f"Matched: {', '.join(fit.matched_skills) if fit.matched_skills else 'None'}\n"
            f"Missing: {', '.join(fit.missing_skills) if fit.missing_skills else 'None'}\n\n"
            f"Suggested resume bullets:\n"
            + ("\n".join(f"- {b}" for b in fit.suggested_bullets) if fit.suggested_bullets else "- (none)")
        )
        self.query_one("#fit_detail", Static).update(detail)

    def _update_status(self, message: Optional[str] = None):
        if message is None:
            if not self.db:
                message = "No database available."
            elif not self.db.get_profile():
                message = "No profile found. Save a profile before scoring jobs."
            else:
                message = f"Mode: {get_scoring_mode()}. Click Analyze to score saved jobs."
        self.query_one("#fit_status", Static).update(message)

    def _is_busy(self) -> bool:
        return any(
            worker.group == "fit" and worker.is_running
            for worker in self.workers
        )

    def _refresh_jobs(self):
        """Load the saved jobs into the table (unscored) in the background."""
        if self._is_busy():
            return
        self.run_worker(self._async_load_jobs, group="fit-load", exclusive=True)

    async def _async_load_jobs(self):
        try:
            jobs = await asyncio.to_thread(self._list_jobs)
            self.call_after_refresh(self._render_jobs, jobs)
        except Exception as e:
            self.call_after_refresh(self._update_status, f"Error loading jobs: {e}")

    def _list_jobs(self):
        """Blocking job listing helper, run off the event loop."""
        if self.agent is None:
            self.agent = JobHuntAgent(self.db)
        return self.agent.run_tool("list_jobs")

    def _render_jobs(self, jobs):
        """Render the job list (unscored) so the page is never an empty void."""
        if self._is_busy():
            return
        table = self.query_one("#fit_table", DataTable)
        table.clear(columns=True)
        self._fits = {}

        self._add_columns(table)
        if not jobs:
            table.add_column("Message", key="message", width=40)
            table.add_row("No jobs found. Run a search first, then Analyze.")
            self._update_status("No jobs in database.")
            return

        for rank, job in enumerate(jobs, start=1):
            table.add_row(
                str(rank),
                job.title[:30] + "..." if len(job.title) > 30 else job.title,
                job.company[:20] + "..." if len(job.company) > 20 else job.company,
                job.location or "N/A",
                "—",
                key=job.id,
            )

        if not self.db or not self.db.get_profile():
            msg = (
                f"{len(jobs)} jobs available. No profile found — "
                "save a profile (Resume screen) before scoring."
            )
        else:
            msg = (
                f"{len(jobs)} jobs available (mode: {get_scoring_mode()}). "
                "Click Analyze to score."
            )
        self._update_status(msg)

    @staticmethod
    def _add_columns(table: DataTable):
        table.add_column("Rank", key="rank", width=6)
        table.add_column("Title", key="title", width=30)
        table.add_column("Company", key="company", width=20)
        table.add_column("Location", key="location", width=15)
        table.add_column("Score", key="score", width=8)

    def _analyze(self):
        if self._is_busy():
            return
        if not self.db or not self.db.get_profile():
            self._update_status("Cannot analyze: no profile found.")
            return
        self._update_status("Scoring...")
        self.run_worker(self._async_analyze, group="fit", exclusive=True)

    async def _async_analyze(self):
        try:
            fits = await asyncio.to_thread(self._run_analysis)
            self.call_after_refresh(self._render_results, fits)
        except Exception as e:
            self.call_after_refresh(self._update_status, f"Error during scoring: {e}")

    def _run_analysis(self) -> list:
        """Blocking scoring helper, run off the event loop."""
        profile = self.db.get_profile()
        jobs = self.db.get_jobs(limit=50)
        if not profile or not jobs:
            return []
        if self.agent is None:
            self.agent = JobHuntAgent(self.db)
        pipeline = ScorePipeline(self.db, EmbeddingClient(), agent=self.agent)
        return pipeline.score(jobs, profile)

    def _render_results(self, fits: list):
        table = self.query_one("#fit_table", DataTable)
        table.clear(columns=True)
        self._fits = {}

        if not fits:
            self._render_jobs(self._list_jobs())
            self._update_status("Scoring produced no results — check profile and oMLX, then try again.")
            return

        self._add_columns(table)
        for rank, fit in enumerate(fits, start=1):
            job = self.db.get_job(fit.job_id)
            if not job:
                continue
            table.add_row(
                str(rank),
                job.title[:30] + "..." if len(job.title) > 30 else job.title,
                job.company[:20] + "..." if len(job.company) > 20 else job.company,
                job.location or "N/A",
                f"{fit.score:.2f}",
                key=fit.job_id,
            )
            self._fits[fit.job_id] = fit

        self._update_status(f"Scored {len(self._fits)} jobs (mode: {get_scoring_mode()}).")
