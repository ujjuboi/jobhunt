"""
Shared UI components for the JobHunt TUI.

Consolidates the repetitive ``Static`` titles, status lines, read-only
scrollable text areas, action buttons, and the copy-pasted worker plumbing
that previously lived in each screen:

* :class:`ScreenTitle` - labeled page headings.
* :class:`StatusText`  - one-line status widgets with a typed setter.
* :class:`ScrollableTextWindow` - read-only, scrollable multi-line output.
* :class:`ActionButton` - raised action buttons (nav buttons stay plain).
* :class:`WorkerMixin`  - lazy agent access plus worker/busy helpers.
"""
from __future__ import annotations

import logging
from typing import Optional

from textual.widgets import Button, Static, TextArea

from ..agent import JobHuntAgent

logger = logging.getLogger(__name__)


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
            The list of jobs from the database, or ``[]`` when no agent
            could be created (``JobHuntAgent.run_tool`` returns ``[]`` for
            a missing database).
        """
        return self.agent.run_tool("list_jobs") if self.agent else []


__all__ = [
    "ScreenTitle",
    "StatusText",
    "ScrollableTextWindow",
    "ActionButton",
    "WorkerMixin",
]