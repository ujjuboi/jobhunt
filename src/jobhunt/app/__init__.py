"""
Textual TUI Application for JobHunt.
"""
from textual.app import App, AwaitComplete, SystemCommand
from textual.binding import Binding
from textual.screen import Screen
from .screens.dashboard import DashboardScreen
from .screens.search import SearchScreen
from .screens.jobs import JobsScreen
from .screens.fit import FitScreen
from .screens.resume import ResumeScreen
from .screens.chat import ChatScreen
from .screens.settings import SettingsScreen
from .components import LogPanel
from .palette import JobHuntCommandsProvider
from ..logging import redirect_logs_to_tui, restore_stderr_logging, setup_logging


class JobHuntApp(App):
    """Main JobHunt application."""

    CSS_PATH = "app.tcss"

    COMMANDS = {JobHuntCommandsProvider}

    BINDINGS = [Binding("ctrl+l", "toggle_log_panel", "Toggle logs")]

    def get_system_commands(self, screen: Screen) -> list[SystemCommand]:
        """Return the system commands in a custom order.

        The palette displays commands in this order: Keys, Toggle Logs,
        Theme, Screenshot, Quit (Quit is always last).  The
        Maximize/Minimize command is omitted.

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
                "Toggle Logs",
                "Show or hide the log panel",
                self.action_toggle_log_panel,
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
        redirect_logs_to_tui()
        self.selected_job_id = None
        self.active_tab: str = "dashboard"
        #: Whether the sidebar log panel is shown (read by :class:`LogPanel`).
        self.log_panel_visible: bool = True
        #: Whether the log panel is following the tail (shared across screens).
        self.log_follow_tail: bool = True
        #: Remembered log-panel scroll offset, restored when a screen remounts.
        self.log_scroll_y: int = 0
        # Initialize database
        from ..db import JobHuntDB
        self.database = JobHuntDB()

    def action_toggle_log_panel(self) -> None:
        """Show or hide the sidebar log panel on every mounted screen."""
        self.log_panel_visible = not self.log_panel_visible
        for screen in self.screen_stack:
            for panel in screen.query(LogPanel):
                panel.display = self.log_panel_visible

    def on_unmount(self) -> None:
        """Restore plain-console logging when the TUI shuts down."""
        restore_stderr_logging()

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