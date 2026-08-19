"""
Base screen for JobHunt application
"""
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button
from textual.containers import Container, Horizontal

from ...config.user_config import keyword_search_available


class BaseScreen(Screen):
    """Base screen class with common layout"""

    NAV_BUTTONS = [
        ("dashboard_btn", "dashboard", "Dashboard"),
        ("search_btn", "search", "Search"),
        ("jobs_btn", "jobs", "Jobs"),
        ("fit_btn", "fit", "Fit"),
        ("resume_btn", "resume", "Resume"),
        ("chat_btn", "chat", "Chat"),
        ("settings_btn", "settings", "Settings"),
    ]

    def __init__(self, name: str):
        super().__init__(name=name)
        self.screen_name = name

    def compose(self):
        """Create the screen layout"""
        yield Header()

        nav_buttons = [
            Button(label, id=button_id)
            for button_id, screen, label in self.NAV_BUTTONS
            if screen != "search" or keyword_search_available()
        ]

        yield Horizontal(*nav_buttons, id="nav_bar")
        yield Container(
            Static(f"JobHunt - {self.screen_name.title()} Screen", id="screen_title"),
            self._get_content(),
            id="screen_content"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle navigation button presses"""
        button_id = event.button.id
        for btn_id, screen, _ in self.NAV_BUTTONS:
            if button_id == btn_id:
                if self.screen_name != screen:
                    self.app.switch_screen(screen)
                return

    def _get_content(self):
        """Override this in subclasses to provide specific content"""
        return Static("This is the base screen - content to be overridden")
