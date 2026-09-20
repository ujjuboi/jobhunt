"""
Textual TUI Application for JobHunt.
"""
from textual.app import App
from .screens.dashboard import DashboardScreen
from .screens.search import SearchScreen
from .screens.jobs import JobsScreen
from .screens.fit import FitScreen
from .screens.resume import ResumeScreen
from .screens.chat import ChatScreen
from .screens.settings import SettingsScreen
from ..logging import setup_logging


class JobHuntApp(App):
    """Main JobHunt application."""

    CSS_PATH = "app.tcss"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        setup_logging()
        self.selected_job_id = None
        # Initialize database
        from ..db import JobHuntDB
        self.database = JobHuntDB()

    def on_mount(self):
        """Install and show the initial screen when the app is mounted."""
        self.install_screen(DashboardScreen(database=self.database), name="dashboard")
        self.install_screen(SearchScreen(database=self.database), name="search")
        self.install_screen(JobsScreen(database=self.database), name="jobs")
        self.install_screen(FitScreen(database=self.database), name="fit")
        self.install_screen(ResumeScreen(database=self.database), name="resume")
        self.install_screen(ChatScreen(database=self.database), name="chat")
        self.install_screen(SettingsScreen(database=self.database), name="settings")

        # Show the initial screen
        self.push_screen("dashboard")


# For direct execution
if __name__ == "__main__":
    app = JobHuntApp()
    app.run()