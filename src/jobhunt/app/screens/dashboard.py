"""
Dashboard screen for the JobHunt TUI.

Shows an overview: total job/application counts, recent activity, and quick
links into the Search, Jobs, and Resume screens.
"""
from ...db import JobHuntDB
from ..components import ActionButton, StatusText
from .base import BaseScreen
from textual.containers import Container
from textual.widgets import Static
from typing import Optional


class DashboardScreen(BaseScreen):
    """Dashboard screen showing an overview of the user's activity."""

    def __init__(self, database: Optional[JobHuntDB] = None) -> None:
        super().__init__(name="dashboard", database=database)

    def on_mount(self) -> None:
        """Update the stats when the dashboard is mounted."""
        self._update_stats()

    def on_screen_resume(self) -> None:
        """Update the stats whenever the user returns to this screen."""
        if self.is_mounted:
            self._update_stats()

    def _update_stats(self) -> None:
        """Refresh the job/application counts and recent activity lines."""
        total_jobs = self.database.count_jobs() if self.database else 0
        total_applications = self.database.count_applications() if self.database else 0

        self.query_one("#status", StatusText).set_message(
            f"Total Jobs: {total_jobs} | Applications: {total_applications}"
        )

        recent_jobs = self.database.get_jobs(limit=3) if self.database else []
        activity_widget = self.query_one("#activity_title", Static)
        activity_container = self.query_one("#activity_container", Static)

        activity_widget.update("Recent Activity:")
        if recent_jobs:
            lines = [
                f"{i}. {job_entry.title} at {job_entry.company}"
                for i, job_entry in enumerate(recent_jobs, 1)
            ]
            activity_container.update("\n".join(lines))
        else:
            activity_container.update("- No recent activity")

    def _get_content(self):
        """Compose the dashboard body.

        Returns:
            A container with the welcome banner, status, recent activity,
            and quick-action buttons.
        """
        return Container(
            Static("Welcome to JobHunt - Local AI Job Search Harness", id="welcome"),
            Static(""),
            self._status("Current Status: Ready", id="status"),
            Static(""),
            self._title("Recent Activity:", id="activity_title"),
            Static("", id="activity_container"),
            Static(""),
            self._title("Quick Actions:", id="actions_title"),
            ActionButton("Search Jobs", id="search_jobs_btn"),
            ActionButton("View Jobs", id="view_jobs_btn"),
            ActionButton("Generate Resume", id="generate_resume_btn"),
            id="dashboard_content"
        )

    def on_button_pressed(self, event) -> None:
        """Handle button presses for navigation.

        Args:
            event: The button-pressed event; only in-screen quick actions are
                handled directly, everything else is delegated to the base.
        """
        if event.button.id == "search_jobs_btn":
            self.app.switch_screen("search")
        elif event.button.id == "view_jobs_btn":
            self.app.switch_screen("jobs")
        elif event.button.id == "generate_resume_btn":
            self.app.switch_screen("resume")
        else:
            super().on_button_pressed(event)