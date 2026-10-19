"""
Shared UI components for the JobHunt TUI.

Consolidates the repetitive ``Static`` titles, status lines, read-only
scrollable text areas, action buttons, and the copy-pasted worker plumbing
that previously lived in each screen:

* :class:`ScreenTitle` - labeled page headings.
* :class:`StatusText`  - one-line status widgets with a typed setter.
* :class:`ScrollableTextWindow` - read-only, scrollable multi-line output.
* :class:`ActionButton` - raised action buttons (nav buttons stay plain).
* :class:`LogPanel` - docked right-side panel tailing the application log.
* :class:`WorkerMixin`  - lazy agent access plus worker/busy helpers.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, RichLog, Static, TextArea

from ..agent import JobHuntAgent
from ..logging import get_tui_handler

logger = logging.getLogger(__name__)

#: Rich styles applied to each log level in the panel.
LEVEL_STYLES: dict[str, str] = {
    "DEBUG": "dim",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold red reverse",
}

NAV_BUTTONS: list[tuple[str, str, str]] = [
    ("dashboard_btn", "dashboard", "Dashboard"),
    ("search_btn", "search", "Search"),
    ("jobs_btn", "jobs", "Jobs"),
    ("fit_btn", "fit", "Fit"),
    ("resume_btn", "resume", "Resume"),
    ("chat_btn", "chat", "Chat"),
    ("settings_btn", "settings", "Settings"),
]


class ScreenTitle(Static):
    """A bold page heading rendered at the top of a screen.

    Args:
        text: The heading text to display.
        id: Optional widget ID (preserves existing ``#*_title`` ids).
    """

    def __init__(self, text: str, id: Optional[str] = None) -> None:
        super().__init__(text, id=id)


class StatusText(Static):
    """A one-line status widget used across every screen.

    Provides :meth:`set_message` as a typed convenience wrapper around
    ``update`` so call sites do not reach into the Static API directly.

    Args:
        text: The initial status message.
        id: Optional widget ID (preserves existing ``#*_status`` ids).
    """

    def __init__(self, text: str = "", id: Optional[str] = None) -> None:
        super().__init__(text, id=id)

    def set_message(self, text: str) -> None:
        """Replace the current status message.

        Args:
            text: The new message to display.
        """
        self.update(text)


class ScrollableTextWindow(TextArea):
    """A read-only, scrollable window for multi-line output.

    Used for search results, the chat transcript, and the resume preview.
    Line numbers are hidden and editing is disabled by default; the widget
    still supports programmatic ``text`` assignment and scrolling.

    Args:
        text: The initial text content.
        id: Optional widget ID (preserves existing ``#*`` ids).
    """

    def __init__(self, text: str = "", id: Optional[str] = None) -> None:
        super().__init__(
            text,
            id=id,
            read_only=True,
            show_line_numbers=False,
        )


class AgentUnavailableError(RuntimeError):
    """Raised when an agent is required but could not be created.

    Surfaces oMLX configuration/availability failures as a descriptive
    error (instead of a bare ``AttributeError`` or a silent empty list) so
    callers can tell an empty database apart from unavailable processing.
    """


class ActionButton(Button):
    """A Button for actionable controls (not navigation).

    All in-screen actions (Search/Refresh, Analyze, Send, Save, ...) use
    :class:`ActionButton`; only the nav bar reuses the plain ``Button``.

    Args:
        *args: Positional arguments forwarded to :class:`Button`.
        **kwargs: Keyword arguments forwarded to :class:`Button`.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


class LogPanel(Vertical):
    """Docked right-side panel that tails the application log.

    Records are read from the shared
    :class:`~jobhunt.logging.TUILogHandler` on a short interval. The interval
    callback runs on the Textual event loop, so records emitted from worker
    threads are only touched through the handler's lock (no cross-thread UI
    calls). Each line is colored by level: DEBUG dim, INFO green, WARNING
    yellow, ERROR red (the message included), CRITICAL bold reversed red.

    The panel is a view over one application-wide stream: every screen replays
    the full buffered history on mount, so the log is persistent and identical
    across tabs. The reading position (following the tail, or a scrolled-up
    offset) is remembered on the app and restored when a screen remounts.

    Args:
        *args: Positional arguments forwarded to :class:`Vertical`.
        **kwargs: Keyword arguments forwarded to :class:`Vertical`.
    """

    #: Seconds between polls for new records.
    POLL_SECONDS = 0.5

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, id="log_panel", **kwargs)
        self._cursor = 0
        self._restore_pending = True
        self._log_lines: Optional[RichLog] = None

    def compose(self):
        """Yield the panel title and the log viewer."""
        yield Static("Logs", id="log_panel_title")
        yield RichLog(
            id="log_lines",
            min_width=1,
            wrap=True,
            highlight=False,
            markup=False,
            auto_scroll=False,
        )

    def on_mount(self) -> None:
        """Replay buffered history, then poll the handler for new records."""
        self.display = getattr(self.app, "log_panel_visible", True)
        self._log_lines = self.query_one("#log_lines", RichLog)
        self._drain()
        self.call_after_refresh(self._drain)
        self.set_interval(self.POLL_SECONDS, self._drain)

    def on_unmount(self) -> None:
        """Remember the reading position for when the screen is shown again."""
        log_lines = self._log_lines
        if log_lines is None:
            return
        if not (
            log_lines.size
            and log_lines.virtual_size.height
            and log_lines.container_size.height
        ):
            return
        self._remember_view(log_lines)

    def _drain(self) -> None:
        """Restore the remembered view, then append newly logged records."""
        log_lines = self._log_lines
        if log_lines is None:
            return

        if self._restore_pending and log_lines.virtual_size.height:
            self._apply_saved_view(log_lines)
            self._restore_pending = False

        records, cursor = get_tui_handler().new_records_since(self._cursor)
        self._cursor = cursor

        if not records:
            if not self._restore_pending:
                self._remember_view(log_lines)
            return

        if self._restore_pending:
            following = getattr(self.app, "log_follow_tail", True)
        else:
            following = log_lines.is_vertical_scroll_end

        for record in records:
            log_lines.write(self._format_record(record))
        if following:
            log_lines.scroll_end(animate=False)

        if not self._restore_pending:
            self._remember_view(log_lines)

    def _apply_saved_view(self, log_lines: RichLog) -> None:
        """Scroll the viewer to the position remembered across screens.

        Args:
            log_lines: The log viewer to position.
        """
        if getattr(self.app, "log_follow_tail", True):
            log_lines.scroll_end(animate=False)
        else:
            log_lines.scroll_to(y=getattr(self.app, "log_scroll_y", 0), animate=False)

    def _remember_view(self, log_lines: RichLog) -> None:
        """Store whether the viewer is following the tail and its offset.

        Args:
            log_lines: The log viewer whose position should be recorded.
        """
        setattr(self.app, "log_follow_tail", log_lines.is_vertical_scroll_end)
        setattr(self.app, "log_scroll_y", int(log_lines.scroll_y))

    @staticmethod
    def _format_record(record: logging.LogRecord) -> Text:
        """Render a log record as a level-colored :class:`~rich.text.Text`.

        Args:
            record: The log record to format.

        Returns:
            A styled ``Text`` line: ``HH:MM:SS LEVEL logger: message``.
        """
        timestamp = time.strftime("%H:%M:%S", time.localtime(record.created))
        level_style = LEVEL_STYLES.get(record.levelname, "")
        message_style = "red" if record.levelno >= logging.ERROR else ""
        text = Text()
        text.append(f"{timestamp} ", style="dim")
        text.append(f"{record.levelname:<8} ", style=level_style)
        text.append(f"{record.name}: ", style="dim cyan")
        text.append(record.getMessage(), style=message_style)
        return text


class WorkerMixin:
    """Reusable worker plumbing shared by the JobHunt screens.

    Consolidates the copy-pasted pieces every screen used to hand-roll:

    * a lazily-constructed :class:`JobHuntAgent` (``agent`` property),
    * a busy check over a worker group (``_is_busy``),
    * a single entry point for starting exclusive workers
      (``_run_worker``),
    * the blocking ``list_jobs`` helper (``_list_jobs``).

    Screens provide the ``database`` attribute (via :class:`BaseScreen`);
    this mixin only assumes ``self.database`` exists.
    """

    def __init__(self, *args, **kwargs) -> None:
        #: Memoized lazy agent instance; created on first ``agent`` access.
        self._agent = None
        super().__init__(*args, **kwargs)

    # ------------------------------------------------------------------
    # Lazy agent access
    # ------------------------------------------------------------------

    @property
    def agent(self) -> Optional[JobHuntAgent]:
        """The screen's agent, constructed lazily on first access.

        Returns:
            A :class:`JobHuntAgent`, or ``None`` when oMLX settings are
            unavailable (construction failures are logged, not raised).
        """
        if self._agent is None:
            self._agent = self._create_agent()
        return self._agent

    @agent.setter
    def agent(self, value: Optional[JobHuntAgent]) -> None:
        """Inject a pre-built agent (used heavily by tests).

        Args:
            value: The agent instance to store, or ``None`` to force the
                lazy property to rebuild on the next access.
        """
        self._agent = value

    def _create_agent(self) -> Optional[JobHuntAgent]:
        """Build a new agent bound to this screen's database.

        Returns:
            A configured :class:`JobHuntAgent`, or ``None`` when the
            constructor fails (typically oMLX being unavailable/offline).
        """
        try:
            return JobHuntAgent(database=self.database)
        except Exception:
            logger.warning("Could not create agent (oMLX may be unavailable)")
            return None

    def _require_agent(self) -> JobHuntAgent:
        """Return the memoized agent, raising when it could not be created.

        Returns:
            The memoized :class:`JobHuntAgent` instance.

        Raises:
            AgentUnavailableError: When no agent could be created (typically
                oMLX being unavailable/offline).
        """
        agent = self.agent
        if agent is None:
            raise AgentUnavailableError("oMLX unavailable — could not create agent")
        return agent

    # ------------------------------------------------------------------
    # Worker helpers
    # ------------------------------------------------------------------

    def _is_busy(self, group: str) -> bool:
        """Return True when a worker in ``group`` is still running.

        Args:
            group: The worker group name to check.

        Returns:
            True if at least one worker in the group is running.
        """
        return any(
            worker.group == group and worker.is_running
            for worker in self.workers
        )

    def _run_worker(self, coro, group: str) -> None:
        """Start an exclusive worker for ``coro`` in the given group.

        Args:
            coro: The coroutine to run in the background.
            group: The worker group name (exclusive within that group).
        """
        self.run_worker(coro, group=group, exclusive=True)

    def _list_jobs(self):
        """Blocking job listing helper, run off the event loop.

        Returns:
            The list of jobs from the database.

        Raises:
            AgentUnavailableError: When no agent could be created, so callers
                can distinguish an empty database from unavailable processing.
        """
        return self._require_agent().run_tool("list_jobs")


class ButtonRow(Horizontal):
    """A horizontal row holding a page's action buttons on a single line.

    Wraps the :class:`ActionButton` groups (and, on the Chat/Search screens,
    the adjacent input) so in-screen actions align at one vertical position
    instead of stacking. Height is left to the CSS (`height: auto`) so the row
    never consumes the page's remaining vertical space.

    Args:
        *args: Positional arguments forwarded to :class:`Horizontal`.
        **kwargs: Keyword arguments forwarded to :class:`Horizontal`.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


class NavBar(Horizontal):
    """Shared navigation bar rendered on every screen.

    The active tab is applied at mount time (first paint) by reading
    ``self.app.active_tab``, and re-applied on every screen resume via
    :meth:`set_active` (called from ``BaseScreen.on_screen_resume``).

    Args:
        *args: Positional arguments forwarded to :class:`Horizontal`.
        **kwargs: Keyword arguments forwarded to :class:`Horizontal`.
    """

    NAV_BUTTONS = NAV_BUTTONS

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, id="nav_bar", **kwargs)

    def compose(self):
        """Yield plain Buttons for every nav button, gating Search."""
        from jobhunt.config.user_config import keyword_search_available

        for button_id, screen, label in NAV_BUTTONS:
            if screen != "search" or keyword_search_available():
                yield Button(label, id=button_id)

    def on_mount(self) -> None:
        """Apply the active class to the current tab button."""
        self._apply_active()

    def _apply_active(self) -> None:
        """Add the ``active`` class to the matching button, remove from others.

        Reads ``self.app.active_tab`` to determine which button to highlight.
        """
        active = self.app.active_tab
        for button in self.query(Button):
            button.remove_class("active")
            button_id = button.id
            for btn_id, screen, _ in NAV_BUTTONS:
                if button_id == btn_id and screen == active:
                    button.add_class("active")
                    break

    def set_active(self, screen_name: str) -> None:
        """Update the active class to highlight ``screen_name`` in place.

        Called by ``BaseScreen.on_screen_resume`` so the highlight stays
        correct across screen switches even for already-mounted nav bars.

        Args:
            screen_name: The screen name to mark as active.
        """
        self.app.active_tab = screen_name
        self._apply_active()


__all__ = [
    "ScreenTitle",
    "StatusText",
    "ScrollableTextWindow",
    "ActionButton",
    "LogPanel",
    "LEVEL_STYLES",
    "AgentUnavailableError",
    "WorkerMixin",
    "ButtonRow",
    "NavBar",
    "NAV_BUTTONS",
]
