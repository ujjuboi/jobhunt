"""
Textual TUI Application for JobHunt.
"""
from textual.app import App, AwaitComplete, SystemCommand
from textual.screen import Screen
from .screens.dashboard import DashboardScreen
from .screens.search import SearchScreen
from .screens.jobs import JobsScreen
from .screens.fit import FitScreen
from .screens.resume import ResumeScreen
from .screens.chat import ChatScreen
from .screens.settings import SettingsScreen
from .palette import JobHuntCommandsProvider
from ..logging import setup_logging


class JobHuntApp(App):
    """Main JobHunt application."""

    CSS_PATH = "app.tcss"

    COMMANDS = {JobHuntCommandsProvider}

    def get_system_commands(self, screen: Screen) -> list[SystemCommand]:
        """Return the system commands in a custom order.

        The palette displays commands in this order: Keys, Theme,
        Screenshot, Quit (Quit is always last).  The Maximize/Minimize
        command is omitted.

        Args:
            screen: The screen where the command palette was invoked from.

        Returns:
            A list of :class:`~textual.app.SystemCommand` instances in the
            desired display order.
        """
        commands: list[SystemCommand] = []

        if screen.query("HelpPanel"):
            commands.append(
                SystemCommand(
                    "Keys",
                    "Hide the keys and widget help panel",
                    self.action_hide_help_panel,
                )
            )
        else:
            commands.append(
                SystemCommand(
                    "Keys",
                    "Show help for the focused widget and a summary of available keys",
                    self.action_show_help_panel,
                )
            )

        commands.append(
            SystemCommand(
                "Theme", "Change the current theme", self.action_change_theme
            )
        )

        commands.append(
            SystemCommand(
                "Screenshot",
                "Save an SVG 'screenshot' of the current screen",
                lambda: self.set_timer(0.1, self.deliver_screenshot),
            )
        )

        commands.append(
            SystemCommand(
                "Quit",
                "Quit the application as soon as possible",
                self.action_quit,
            )
        )

        return commands

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        setup_logging()
        self.selected_job_id = None
        self.active_tab: str = "dashboard"
        # Initialize database
        from ..db import JobHuntDB
        self.database = JobHuntDB()

    def switch_screen(self, screen: "Screen | str") -> AwaitComplete:
        """Switch to a different screen and track the active tab.

        Args:
            screen: The target screen name (str) or :class:`Screen` instance.

        Returns:
            An :class:`~textual.app.AwaitComplete` for the screen switch.
        """
        self.active_tab = screen if isinstance(screen, str) else screen.name
        return super().switch_screen(screen)

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
        self.active_tab = "dashboard"
        self.push_screen("dashboard")


# For direct execution
if __name__ == "__main__":
    app = JobHuntApp()
    app.run()