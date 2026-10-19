"""Tests for the sidebar log panel and its in-memory log handler."""
import asyncio
import logging
import threading

from textual.widgets import RichLog

from jobhunt.app import JobHuntApp
from jobhunt.app.components import LEVEL_STYLES, LogPanel
from jobhunt.logging import (
    TUILogHandler,
    get_tui_handler,
    redirect_logs_to_tui,
    restore_stderr_logging,
    setup_logging,
)


def _record(message: str, name: str = "jobhunt.test", level: int = logging.INFO) -> logging.LogRecord:
    """Build a bare log record for handler/formatting tests."""
    return logging.LogRecord(name, level, __file__, 1, message, None, None)


# ---------------------------------------------------------------------------
# TUILogHandler
# ---------------------------------------------------------------------------

def test_tui_handler_buffers_jobhunt_records_only():
    """Only records from the jobhunt namespace are retained."""
    handler = TUILogHandler(capacity=10)
    handler.emit(_record("hello"))
    handler.emit(_record("third-party noise", name="httpx"))

    records, cursor = handler.new_records_since(0)
    assert [record.getMessage() for record in records] == ["hello"]
    assert cursor == 1
    assert handler.sequence == 1


def test_tui_handler_cursor_advances_without_repeats():
    """A cursor from a previous read yields only newer records."""
    handler = TUILogHandler(capacity=10)
    handler.emit(_record("one"))
    first, cursor = handler.new_records_since(0)
    assert [record.getMessage() for record in first] == ["one"]

    handler.emit(_record("two"))
    second, cursor = handler.new_records_since(cursor)
    assert [record.getMessage() for record in second] == ["two"]

    empty, cursor = handler.new_records_since(cursor)
    assert empty == []


def test_tui_handler_eviction_keeps_cursor_valid():
    """Old records drop out of the ring buffer but cursors stay consistent."""
    handler = TUILogHandler(capacity=3)
    for index in range(5):
        handler.emit(_record(f"line-{index}"))

    records, cursor = handler.new_records_since(0)
    assert [record.getMessage() for record in records] == ["line-2", "line-3", "line-4"]
    assert cursor == 5

    # A cursor pointing at an evicted record only replays what remains.
    records, cursor = handler.new_records_since(3)
    assert [record.getMessage() for record in records] == ["line-3", "line-4"]


def test_tui_handler_is_thread_safe():
    """Concurrent emits from worker threads are all retained."""
    handler = TUILogHandler(capacity=1000)

    def emit_many() -> None:
        for _ in range(50):
            handler.emit(_record("concurrent"))

    threads = [threading.Thread(target=emit_many) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    records, cursor = handler.new_records_since(0)
    assert len(records) == 200
    assert cursor == 200
    assert handler.sequence == 200


# ---------------------------------------------------------------------------
# Logging setup / redirection
# ---------------------------------------------------------------------------

def test_setup_logging_registers_single_tui_handler():
    """setup_logging attaches the TUI handler once, even if called again."""
    setup_logging()
    root = logging.getLogger()
    handler = get_tui_handler()
    assert root.handlers.count(handler) == 1

    setup_logging()
    assert root.handlers.count(handler) == 1


def test_redirect_and_restore_stderr_handler():
    """redirect detaches stderr (idempotently); restore re-attaches it."""
    import jobhunt.logging as logging_module

    setup_logging()
    stderr_handler = logging_module._stderr_handler
    assert stderr_handler is not None
    root = logging.getLogger()

    try:
        redirect_logs_to_tui()
        assert stderr_handler not in root.handlers
        redirect_logs_to_tui()
        assert stderr_handler not in root.handlers
    finally:
        restore_stderr_logging()

    assert stderr_handler in root.handlers


def test_app_shutdown_restores_stderr_logging():
    """Running the TUI detaches stderr; closing it re-attaches stderr."""
    import jobhunt.logging as logging_module

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)):
            await asyncio.sleep(0.1)
            assert logging_module._stderr_handler not in logging.getLogger().handlers
        assert logging_module._stderr_handler in logging.getLogger().handlers

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Record formatting
# ---------------------------------------------------------------------------

def test_every_level_has_a_distinct_style():
    """Each standard level maps to its own color style."""
    assert set(LEVEL_STYLES) == {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert len(set(LEVEL_STYLES.values())) == len(LEVEL_STYLES)


def test_format_record_colors_the_level_and_includes_the_message():
    """Formatted lines carry the level style plus timestamp/logger/message."""
    deviation = LogPanel._format_record(_record("watch out", level=logging.WARNING))
    styles = {span.style for span in deviation.spans}
    assert LEVEL_STYLES["WARNING"] in styles
    assert "WARNING" in deviation.plain
    assert "jobhunt.test" in deviation.plain
    assert deviation.plain.endswith("watch out")

    critical = LogPanel._format_record(_record("boom", level=logging.CRITICAL))
    assert LEVEL_STYLES["CRITICAL"] in {span.style for span in critical.spans}

    info = LogPanel._format_record(_record("ok", level=logging.INFO))
    assert LEVEL_STYLES["INFO"] in {span.style for span in info.spans}


def test_error_records_render_the_message_in_red():
    """ERROR (and CRITICAL) messages themselves are red, not just the level tag."""
    failure = LogPanel._format_record(
        _record("Error fetching jobs from Lever", level=logging.ERROR)
    )
    message_span = failure.spans[-1]
    assert failure.plain[message_span.start:message_span.end] == "Error fetching jobs from Lever"
    assert message_span.style == "red"

    info = LogPanel._format_record(_record("all good", level=logging.INFO))
    assert info.spans[-1].style != "red"

    warning = LogPanel._format_record(_record("careful", level=logging.WARNING))
    assert warning.spans[-1].style != "red"


# ---------------------------------------------------------------------------
# Panel widget
# ---------------------------------------------------------------------------

def test_log_panel_present_on_every_screen():
    """The sidebar log panel is composed on every screen."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            for button_id in ("#dashboard_btn", "#jobs_btn", "#chat_btn"):
                await pilot.click(button_id)
                await asyncio.sleep(0.1)
                assert app.screen.query(LogPanel).first() is not None

    asyncio.run(run())


def test_log_record_appears_in_panel():
    """A jobhunt log record shows up in the panel after a poll."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            logging.getLogger("jobhunt.test.panel").info("panel-hello-marker")

            log_lines = app.screen.query_one("#log_lines", RichLog)
            for _ in range(50):
                if any("panel-hello-marker" in line.text for line in log_lines.lines):
                    break
                await asyncio.sleep(0.05)

            rendered = "\n".join(line.text for line in log_lines.lines)
            assert "panel-hello-marker" in rendered

    asyncio.run(run())


def test_ctrl_l_toggles_log_panel():
    """ctrl+l hides and re-shows the panel."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            assert app.screen.query_one(LogPanel).display is True

            await pilot.press("ctrl+l")
            await asyncio.sleep(0.1)
            assert app.screen.query_one(LogPanel).display is False

            await pilot.press("ctrl+l")
            await asyncio.sleep(0.1)
            assert app.screen.query_one(LogPanel).display is True

    asyncio.run(run())


def test_logs_persist_across_screen_switches():
    """The panel mirrors one persistent stream and cannot be cleared away."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            logging.getLogger("jobhunt.test.persist").warning("persist-marker")

            log_lines = app.screen.query_one("#log_lines", RichLog)
            for _ in range(50):
                if any("persist-marker" in line.text for line in log_lines.lines):
                    break
                await asyncio.sleep(0.05)
            assert any("persist-marker" in line.text for line in log_lines.lines)

            # Leave the screen and come back: the shared buffer is replayed.
            await pilot.click("#chat_btn")
            await asyncio.sleep(0.2)
            await pilot.click("#dashboard_btn")
            await asyncio.sleep(0.2)

            revisited = app.screen.query_one("#log_lines", RichLog)
            assert any("persist-marker" in line.text for line in revisited.lines)
            assert not app.screen.query("#clear_logs_btn")

    asyncio.run(run())


def test_scroll_position_is_remembered_across_screen_switches():
    """A scrolled-up panel restores its offset; a tailing panel stays at the end."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(120, 30)) as pilot:
            await asyncio.sleep(0.1)
            logger = logging.getLogger("jobhunt.test.scroll")
            for index in range(80):
                logger.info("scroll-line-%03d", index)
            await asyncio.sleep(1.2)

            log_lines = app.screen.query_one("#log_lines", RichLog)
            assert log_lines.max_scroll_y > 0
            assert log_lines.is_vertical_scroll_end

            # Scroll to the top; the next poll records the reading position.
            log_lines.scroll_to(y=0, animate=False)
            await asyncio.sleep(0.8)
            assert app.log_follow_tail is False

            await pilot.click("#chat_btn")
            await asyncio.sleep(0.8)
            await pilot.click("#dashboard_btn")
            await asyncio.sleep(0.8)

            revisited = app.screen.query_one("#log_lines", RichLog)
            assert revisited.scroll_y == 0
            assert not revisited.is_vertical_scroll_end

            # Following the tail again: a remount lands back at the bottom.
            revisited.scroll_end(animate=False)
            await asyncio.sleep(0.8)
            assert app.log_follow_tail is True

            await pilot.click("#chat_btn")
            await asyncio.sleep(0.8)
            await pilot.click("#dashboard_btn")
            await asyncio.sleep(0.8)

            assert app.screen.query_one("#log_lines", RichLog).is_vertical_scroll_end

    asyncio.run(run())
