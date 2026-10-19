"""
Logging setup for JobHunt.

Configures root logging so the app's module loggers (jobhunt.*) surface
warnings/errors in the TUI console and optionally to a file under ~/.config/
jobhunt/logs/. While the TUI is running, :func:`redirect_logs_to_tui` moves
the console stream into an in-memory :class:`TUILogHandler` that feeds the
sidebar log panel instead of corrupting the terminal display.
"""
import logging
import os
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Optional

#: Root logger name whose records are shown in the TUI log panel.
TUI_LOG_NAMESPACE = "jobhunt"

#: Maximum number of records retained for the TUI log panel.
TUI_LOG_BUFFER_SIZE = 500

_tui_handler: Optional["TUILogHandler"] = None
_stderr_handler: Optional[logging.StreamHandler] = None


class TUILogHandler(logging.Handler):
    """In-memory, thread-safe ring buffer of log records for the TUI panel.

    Records may be emitted from worker threads while the panel reads them on
    the Textual event loop, so all buffer access is guarded by a lock. A
    monotonic sequence counter lets consumers track a read cursor that stays
    valid even after old records are evicted or the buffer is cleared.

    Only records from the ``jobhunt`` namespace are buffered, keeping the
    panel focused on application (primarily API) logs.

    Args:
        capacity: Maximum number of records to retain (ring-buffer style).
    """

    def __init__(self, capacity: int = TUI_LOG_BUFFER_SIZE) -> None:
        super().__init__()
        self._buffer: deque[logging.LogRecord] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._sequence = 0

    def emit(self, record: logging.LogRecord) -> None:
        """Append a record to the ring buffer.

        Args:
            record: The log record to retain, filtered to the
                ``jobhunt`` namespace.
        """
        try:
            if not record.name.startswith(TUI_LOG_NAMESPACE):
                return
            with self._lock:
                self._buffer.append(record)
                self._sequence += 1
        except Exception:
            self.handleError(record)

    @property
    def sequence(self) -> int:
        """The total number of records ever appended (monotonic counter)."""
        with self._lock:
            return self._sequence

    def new_records_since(self, cursor: int) -> tuple[list[logging.LogRecord], int]:
        """Return records appended after ``cursor`` and the new cursor value.

        Args:
            cursor: A sequence value previously returned by this method or
                :attr:`sequence`.

        Returns:
            A ``(records, new_cursor)`` tuple; records still in the buffer
            that were logged after ``cursor``.
        """
        with self._lock:
            records = list(self._buffer)
            start = max(0, len(records) - (self._sequence - cursor))
            return records[start:], self._sequence


def get_tui_handler() -> TUILogHandler:
    """Return the shared TUI log handler, creating it on first use.

    Returns:
        The process-wide :class:`TUILogHandler` singleton.
    """
    global _tui_handler
    if _tui_handler is None:
        _tui_handler = TUILogHandler()
    return _tui_handler


def redirect_logs_to_tui() -> None:
    """Move the console log stream into the TUI log panel.

    Detaches the stderr :class:`logging.StreamHandler` installed by
    :func:`setup_logging` so log output no longer corrupts the TUI display;
    records continue to flow to the file handler and to the
    :class:`TUILogHandler` consumed by the sidebar log panel. Idempotent.
    """
    global _stderr_handler
    root = logging.getLogger()
    if _stderr_handler is not None and _stderr_handler in root.handlers:
        root.removeHandler(_stderr_handler)


def restore_stderr_logging() -> None:
    """Re-attach the stderr handler removed by :func:`redirect_logs_to_tui`.

    Used when the TUI shuts down so plain-console runs (tests, CLI) log to
    stderr again. Idempotent.
    """
    global _stderr_handler
    root = logging.getLogger()
    if _stderr_handler is not None and _stderr_handler not in root.handlers:
        root.addHandler(_stderr_handler)


def setup_logging(level: int = logging.INFO, log_to_file: bool = True) -> None:
    """Configure root logging for JobHunt. Safe to call multiple times.

    Args:
        level: The root logging level (default ``INFO``).
        log_to_file: Whether to also write to ``~/.config/jobhunt/logs/``.
    """
    root = logging.getLogger()
    if getattr(root, "_jobhunt_configured", False):
        return

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
    )

    global _stderr_handler
    _stderr_handler = logging.StreamHandler(sys.stderr)
    _stderr_handler.setFormatter(formatter)
    root.addHandler(_stderr_handler)

    tui_handler = get_tui_handler()
    if tui_handler not in root.handlers:
        root.addHandler(tui_handler)

    if log_to_file:
        log_dir = Path.home() / ".config" / "jobhunt" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "jobhunt.log")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            pass

    root.setLevel(level)

    env_level = os.environ.get("JOBHUNT_LOG_LEVEL")
    if env_level:
        root.setLevel(getattr(logging, env_level.upper(), level))

    root._jobhunt_configured = True
    logging.getLogger("jobhunt").info("JobHunt logging initialized")
