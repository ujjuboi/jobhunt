"""
Textual TUI Application for JobHunt
"""
from textual.app import App
from .screens.dashboard import DashboardScreen
from .screens.search import SearchScreen
from .screens.jobs import JobsScreen
from .screens.fit import FitScreen
from .screens.resume import ResumeScreen
from .screens.chat import ChatScreen
from .screens.settings import SettingsScreen
from .. import db


class JobHuntApp(App):
    """Main JobHunt application"""

    CSS_PATH = "app.tcss"

    def on_mount(self):
        """Called when the application is mounted"""
        # Initialize database
        self.database = db.JobHuntDB()
        
        self.install_screen(DashboardScreen(), name="dashboard")
        self.install_screen(SearchScreen(db=self.database), name="search")
        self.install_screen(JobsScreen(db=self.database), name="jobs")
        self.install_screen(FitScreen(db=self.database), name="fit")
        self.install_screen(ResumeScreen(db=self.database), name="resume")
        self.install_screen(ChatScreen(db=self.database), name="chat")
        self.install_screen(SettingsScreen(), name="settings")

        # Show the initial screen
        self.push_screen("dashboard")


# For direct execution
if __name__ == "__main__":
    app = JobHuntApp()
    app.run()
