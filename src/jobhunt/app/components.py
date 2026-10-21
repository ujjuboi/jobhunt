"""
Shared UI components for the JobHunt TUI.

Consolidates the repetitive ``Static`` titles, status lines, read-only
scrollable text areas, action buttons, and the copy-pasted worker plumbing
that previously lived in each screen:

* :class:`ScreenTitle` - labeled page headings.
* :class:`StatusText`  - one-line status widgets with a typed setter.
* :class:`ScrollableTextWindow` - read-only, scrollable multi-line output.
* :class:`ActionButton` - raised action buttons (nav buttons stay plain).
* :class:`RowClickTable` - data table that reports single row clicks.
* :class:`ContextMenu` - floating menu of actions shown over a screen.
* :class:`LoadingBar` - spinner + message shown while a worker runs.
* :class:`LogPanel` - docked right-side panel tailing the application log.
* :class:`WorkerMixin`  - lazy agent access plus worker/busy helpers.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from rich.text import Text
from textual.app import ScreenStackError
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.widgets import (
    Button,
    DataTable,
    LoadingIndicator,
    RichLog,
    Static,
    TextArea,
)
from textual.worker import Worker

from ..agent import JobHuntAgent
from ..logging import TUI_LOG_BUFFER_SIZE, get_tui_handler

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


class LoadingBar(Horizontal):
    """One-line spinner plus message shown while a background worker runs.

    Mounted on every screen by :class:`~jobhunt.app.screens.base.BaseScreen`
    (id ``#loading_bar``) and toggled by
    :meth:`WorkerMixin.on_worker_state_changed`. Hidden at rest so screens
    keep their exact layout; when shown it occupies a single line above the
    footer.

    Args:
        *args: Positional arguments forwarded to :class:`Horizontal`.
        **kwargs: Keyword arguments forwarded to :class:`Horizontal`.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, id="loading_bar", **kwargs)
        self.display = False

    def compose(self):
        """Yield the spinner and the message label."""
        yield LoadingIndicator(id="loading_spinner")
        yield Static("", id="loading_message")

    def set_message(self, text: str) -> None:
        """Replace the message shown next to the spinner.

        Args:
            text: The new message to display.
        """
        self.query_one("#loading_message", Static).update(text)

    def show(self, message: str = "") -> None:
        """Display the bar with an optional message.

        Args:
            message: The message to show next to the spinner.
        """
        if message:
            self.set_message(message)
        self.display = True

    def hide(self) -> None:
        """Hide the bar and clear the message."""
        self.display = False
        self.set_message("")


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


class RowClickTable(DataTable):
    """A :class:`~textual.widgets.DataTable` that reports row clicks.

    Textual's ``DataTable`` defaults to ``cursor_type="cell"``, so a single
    click only moves the cursor: ``RowSelected`` is posted for Enter (or for
    a *second* click on the already highlighted cell), never for the first
    click on a row. Screens that need a click to act on a row use this
    subclass, which posts a :class:`RowClickTable.RowClicked` message for
    every click on a data row.

    The message is posted from the public ``on_click`` handler on purpose:
    Textual walks the MRO and prefers the private ``_on_click`` only within
    the same class, so this handler runs first and ``DataTable._on_click``
    still moves the cursor afterwards. Both details are Textual 8.2
    behaviours, so they are called out here for future maintainers.

    Args:
        *args: Positional arguments forwarded to :class:`DataTable`.
        **kwargs: Keyword arguments forwarded to :class:`DataTable`.
    """

    class RowClicked(Message):
        """Posted when one of the table's data rows is clicked.

        Args:
            table: The table that was clicked.
            row_key: The key of the clicked row.
            row_index: The index of the clicked row.
            screen_x: The horizontal screen coordinate of the click.
            screen_y: The vertical screen coordinate of the click.
        """

        def __init__(
            self,
            table: "RowClickTable",
            row_key,
            row_index: int,
            screen_x: int,
            screen_y: int,
        ) -> None:
            super().__init__()
            self.table = table
            """The table that was clicked."""
            self.row_key = row_key
            """The key of the clicked row."""
            self.row_index = row_index
            """The index of the clicked row."""
            self.screen_x = screen_x
            """The horizontal screen coordinate of the click."""
            self.screen_y = screen_y
            """The vertical screen coordinate of the click."""

        @property
        def control(self) -> "RowClickTable":
            """The table that sent the message."""
            return self.table

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def on_click(self, event: Click) -> None:
        """Post a :class:`RowClickTable.RowClicked` message for a clicked row.

        Args:
            event: The click event; clicks that miss the data rows (the
                header, or the empty space below the last row) are ignored.
        """
        style = event.style
        if style is None:
            return
        meta = style.meta
        if "row" not in meta or "column" not in meta:
            return
        row_index = meta["row"]
        rows = self.ordered_rows
        if not (0 <= row_index < len(rows)):
            return
        self.post_message(
            self.RowClicked(
                self,
                rows[row_index].key,
                row_index,
                int(event.screen_x or 0),
                int(event.screen_y or 0),
            )
        )


class ContextMenu(Vertical):
    """A floating menu of actions shown over the current screen.

    The menu is an absolutely positioned overlay: it does not take part in
    the layout of its parent and is painted on top of it, so it can be
    anchored to the spot the user clicked without pushing the page around.
    ``open_at`` takes *screen* coordinates and converts them to the offset
    the parent expects.

    Args:
        *args: Positional arguments forwarded to :class:`Vertical`.
        **kwargs: Keyword arguments forwarded to :class:`Vertical`.
    """

    DEFAULT_CSS = """
    ContextMenu {
        position: absolute;
        overlay: screen;
        display: none;
        width: 34;
        height: auto;
        background: $panel;
        border: round $primary;
        padding: 0 1;
    }
    ContextMenu > .context-menu--title {
        color: $text-muted;
        text-style: bold;
    }
    ContextMenu > Button {
        width: 1fr;
        margin: 0;
    }
    """

    BINDINGS = [("escape", "dismiss", "Dismiss menu")]

    class Dismissed(Message):
        """Posted when the menu is dismissed without picking an action."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.display = False
        self._offset: tuple[int, int] = (0, 0)

    def open_at(self, x: int, y: int, title: str = "") -> None:
        """Show the menu anchored at a screen position.

        Args:
            x: The horizontal screen coordinate to anchor the menu at.
            y: The vertical screen coordinate to anchor the menu at.
            title: Optional heading shown above the menu items.
        """
        if title:
            title_widget = self.query(".context-menu--title").first()
            if title_widget is not None:
                title_widget.update(title)
        self.display = True
        self._offset = self._offset_for(x, y)
        self.styles.offset = self._offset
        self.call_after_refresh(self._keep_inside_screen)
        first_button = self.query(Button).first()
        if first_button is not None:
            first_button.focus()

    def close(self) -> None:
        """Hide the menu without posting a message."""
        self.display = False

    def contains_point(self, x: int, y: int) -> bool:
        """Whether a screen position lies inside the menu.

        Screens use this to tell a click on a menu item apart from a click
        somewhere else on the page (which dismisses the menu).

        Args:
            x: The horizontal screen coordinate.
            y: The vertical screen coordinate.

        Returns:
            ``True`` when the position is inside the menu's region.
        """
        region = self.region
        return (
            region.x <= x < region.x + region.width
            and region.y <= y < region.y + region.height
        )

    def action_dismiss(self) -> None:
        """Close the menu and report the dismissal."""
        self.close()
        self.post_message(self.Dismissed())

    def _offset_for(self, x: int, y: int) -> tuple[int, int]:
        """Convert screen coordinates into an offset for the parent.

        Args:
            x: The horizontal screen coordinate.
            y: The vertical screen coordinate.

        Returns:
            The ``(x, y)`` offset to apply to the menu, relative to the
            content origin of its parent container.
        """
        parent = self.parent
        if parent is None:
            return (x, y)
        origin = parent.content_region
        return (x - origin.x, y - origin.y)

    def _keep_inside_screen(self) -> None:
        """Shift the menu up/left when it would overflow the screen."""
        region = self.region
        if not (region.width and region.height):
            return
        x, y = self._offset
        screen_width, screen_height = self.screen.size
        if region.y + region.height > screen_height:
            y -= region.y + region.height - screen_height
        if region.x + region.width > screen_width:
            x -= region.x + region.width - screen_width
        if (x, y) != self._offset:
            self._offset = (x, y)
            self.styles.offset = self._offset


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
    offset) is shared through the app: only the panel on the visible screen
    records it, and it is re-applied whenever a screen becomes visible again.

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
            max_lines=TUI_LOG_BUFFER_SIZE,
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

    def restore_shared_view(self) -> None:
        """Re-apply the app-wide reading position after this panel is shown.

        Installed screens are suspended rather than unmounted when tabs
        switch, so the panel is not rebuilt and its ``on_mount`` restore does
        not run again. Screens call this from their resume handler to keep the
        panel in sync with the shared reading position.
        """
        self._restore_pending = True
        self._drain()

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

        Only the panel on the currently visible screen records, so a suspended
        screen cannot overwrite the shared reading position from the panel it
        keeps mounted.

        Args:
            log_lines: The log viewer whose position should be recorded.
        """
        if not self._is_active():
            return
        setattr(self.app, "log_follow_tail", log_lines.is_vertical_scroll_end)
        setattr(self.app, "log_scroll_y", int(log_lines.scroll_y))

    def _is_active(self) -> bool:
        """Whether this panel belongs to the screen currently on display.

        Returns:
            ``True`` when this panel's screen is the app's active screen, and
            ``False`` while the app is shutting down (the screen stack can be
            empty while the poll interval is still firing).
        """
        try:
            return self.app.screen is self.screen
        except ScreenStackError:
            return False

    @staticmethod
    def _format_record(record: logging.LogRecord) -> Text:
        """Render a log record as a level-colored :class:`~rich.text.Text`.

        Args:
            record: The log record to format.

        Returns:
            A styled ``Text`` line: ``HH:MM:SS LEVEL logger: message``, with
            any exception traceback appended after the message.
        """
        timestamp = time.strftime("%H:%M:%S", time.localtime(record.created))
        level_style = LEVEL_STYLES.get(record.levelname, "")
        message_style = "red" if record.levelno >= logging.ERROR else ""
        text = Text()
        text.append(f"{timestamp} ", style="dim")
        text.append(f"{record.levelname:<8} ", style=level_style)
        text.append(f"{record.name}: ", style="dim cyan")
        text.append(record.getMessage(), style=message_style)
        if record.exc_info:
            text.append("\n")
            text.append(
                logging.Formatter().formatException(record.exc_info),
                style=message_style,
            )
        return text


class WorkerMixin:
    """Reusable worker plumbing shared by the JobHunt screens.

    Consolidates the copy-pasted pieces every screen used to hand-roll:

    * a lazily-constructed :class:`JobHuntAgent` (``agent`` property),
    * a busy check over a worker group (``_is_busy``),
    * a single entry point for starting exclusive workers
      (``_run_worker``).

    Screens provide the ``database`` attribute (via :class:`BaseScreen`);
    this mixin only assumes ``self.database`` exists.
    """

    def __init__(self, *args, **kwargs) -> None:
        #: Memoized lazy agent instance; created on first ``agent`` access.
        self._agent = None
        #: Map of worker group to the loading message shown while it runs.
        self._loading_messages: dict[str, str] = {}
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

    def _run_worker(self, coro, group: str, loading_message: str | None = None):
        """Start an exclusive worker for ``coro`` in the given group.

        Args:
            coro: The coroutine to run in the background.
            group: The worker group name (exclusive within that group).
            loading_message: When given, the shared :class:`LoadingBar`
                shows this message while the group's worker runs.

        Returns:
            The started :class:`~textual.worker.Worker` instance.
        """
        if loading_message is not None:
            self._loading_messages[group] = loading_message
        else:
            self._loading_messages.pop(group, None)
        return self.run_worker(coro, group=group, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Show or hide the shared loading bar as tracked workers run.

        The bar's visibility is recomputed from the live worker list rather
        than refcounted, so cancelled or failed workers cannot leave a stuck
        spinner behind. Groups started without a ``loading_message`` (for
        example Chat, whose streamed transcript is its own feedback) are
        never tracked and never show the bar.

        Args:
            event: The worker state-change message; ignored directly because
                any state change (start, success, error, cancel) may affect
                visibility, so the live worker list is recomputed.
        """
        loading_bar = self.query(LoadingBar).first()
        if loading_bar is None:
            return
        running = [
            worker
            for worker in self.workers
            if worker.is_running and worker.group in self._loading_messages
        ]
        if running:
            loading_bar.show(self._loading_messages[running[-1].group])
        else:
            loading_bar.hide()


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
    :meth:`set_active` also moves keyboard focus to the active button so the
    focus highlight matches the current tab instead of the first nav button,
    but only when nothing else has focus or focus is already on this nav bar.

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
        Also moves keyboard focus to the active button: Textual otherwise
        auto-focuses the first focusable widget of the new screen (the
        Dashboard button), leaving the focus highlight on the wrong tab.

        Args:
            screen_name: The screen name to mark as active.
        """
        self.app.active_tab = screen_name
        self._apply_active()
        self._focus_active()

    def _focus_active(self) -> None:
        """Move keyboard focus to the active tab's button when appropriate.

        Focus is only moved when nothing is focused or focus is already on
        this nav bar. A screen also resumes when a screen pushed on top of it
        is dismissed (for example the command palette), and in that case a
        focused input must keep focus instead of being replaced by the nav
        bar.
        """
        focused = self.app.focused
        if focused is not None and not any(
            focused is button for button in self.query(Button)
        ):
            return
        active_button = self.query(Button).filter(".active").first()
        if active_button is not None and active_button.can_focus:
            active_button.focus()


__all__ = [
    "ScreenTitle",
    "StatusText",
    "ScrollableTextWindow",
    "ActionButton",
    "RowClickTable",
    "ContextMenu",
    "LoadingBar",
    "LogPanel",
    "LEVEL_STYLES",
    "AgentUnavailableError",
    "WorkerMixin",
    "ButtonRow",
    "NavBar",
    "NAV_BUTTONS",
]
