"""
Base screen for the JobHunt TUI.

Provides the shared chrome (header, nav bar, footer), the single ``database``
reference used by every screen, small widgets built from the shared
:mod:`jobhunt.app.components`, and the :class:`WorkerMixin` plumbing.
"""
from typing import Optional

from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ...db import JobHuntDB
from ..components import (
    ActionButton,
    LogPanel,
    NavBar,
    ScreenTitle,
    StatusText,
    WorkerMixin,
)


class BaseScreen(WorkerMixin, Screen):
    """Base class providing the common nav layout and shared plumbing.

    Args:
        name: The screen name used for routing and the page heading.
        database: The shared database instance (defaults to ``None`` for
            tests that only exercise the widget tree).
    """

    def __init__(self, name: str, database: Optional[JobHuntDB] = None) -> None:
        self.screen_name = name
        self.database = database
        super().__init__(name=name)

    def compose(self):
        """Create the screen layout: header, nav bar, content, footer, panel."""
        with Horizontal(id="screen_root"):
            with Vertical(id="screen_main"):
                yield Header()

                yield NavBar()
                yield Container(
                    self._title(
                        f"JobHunt - {self.screen_name.title()} Screen",
                        id="screen_title",
                    ),
                    self._get_content(),
                    id="screen_content"
                )
                yield Footer()
            yield LogPanel()

    def on_button_pressed(self, event) -> None:
        """Handle navigation button presses.

        Args:
            event: The button-pressed event, whose ``button.id`` selects the
                target screen.
        """
        button_id = event.button.id
        for btn_id, screen, _ in NavBar.NAV_BUTTONS:
            if button_id == btn_id:
                if self.screen_name != screen:
                    self.app.switch_screen(screen)
                return

    def on_screen_resume(self) -> None:
        """Re-apply the active-tab highlight whenever the screen is shown.

        The NavBar mounts once per screen, so re-applying on every resume keeps
        the highlight correct even for screens that are already mounted. The
        NavBar may not be mounted yet on the first visit; ``on_mount`` covers
        that case. Installed screens are suspended rather than unmounted when
        tabs switch, so the log panel is also asked to re-sync its reading
        position with the shared one.
        """
        nav_bar = self.query(NavBar).first()
        if nav_bar is not None:
            nav_bar.set_active(self.screen_name)
        log_panel = self.query(LogPanel).first()
        if log_panel is not None:
            log_panel.restore_shared_view()

    def _get_content(self):
        """Override this in subclasses to provide specific content.

        Returns:
            A Textual widget (typically a :class:`Container`) rendering the
            screen body; default shows a placeholder message.
        """
        return Static("This is the base screen - content to be overridden")

    def _title(self, text: str, id: Optional[str] = None) -> ScreenTitle:
        """Build a page-title widget from the shared component.

        Args:
            text: The heading text.
            id: Optional widget ID (preserves ``#*_title`` ids).

        Returns:
            A :class:`ScreenTitle` widget ready for composition.
        """
        return ScreenTitle(text, id=id)

    def _status(self, text: str = "", id: Optional[str] = None) -> StatusText:
        """Build a status widget from the shared component.

        Args:
            text: The initial status message (defaults to empty).
            id: Optional widget ID (preserves ``#*_status`` ids).

        Returns:
            A :class:`StatusText` widget ready for composition.
        """
        return StatusText(text, id=id)