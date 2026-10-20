"""
Tests for the shared loading bar (issue #11).

Covers the LoadingBar widget, the WorkerMixin show/hide wiring driven by
worker state changes, and the Resume screen's move from blocking
event-loop generation to background workers.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from textual.widgets import Button, LoadingIndicator, Select, Static

from jobhunt.app import JobHuntApp
from jobhunt.app.components import LoadingBar, StatusText
from jobhunt.app.screens.resume import ResumeScreen


def test_loading_bar_hidden_at_rest():
    """The bar must not occupy layout space when no worker is running."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(120, 40)):
            await asyncio.sleep(0.1)
            bar = app.screen.query_one("#loading_bar", LoadingBar)
            assert not bar.display

    asyncio.run(run())


def test_loading_bar_show_hide():
    """show() displays with the message; hide() clears both."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(120, 40)):
            await asyncio.sleep(0.1)
            bar = app.screen.query_one("#loading_bar", LoadingBar)
            bar.show("Working on it…")
            assert bar.display
            assert "Working on it…" in str(bar.query_one("#loading_message", Static).content)
            bar.hide()
            assert not bar.display
            assert str(bar.query_one("#loading_message", Static).content) == ""

    asyncio.run(run())


def test_loading_bar_spinner_present():
    """The bar contains a LoadingIndicator so every screen gets a spinner."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(120, 40)):
            await asyncio.sleep(0.1)
            assert app.screen.query_one("#loading_spinner", LoadingIndicator)

    asyncio.run(run())


def test_bar_shows_during_worker_and_hides_after():
    """A tracked worker (with a loading message) toggles the bar on/off."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await asyncio.sleep(0.1)
            screen = app.screen
            bar = screen.query_one("#loading_bar", LoadingBar)

            async def slow():
                await asyncio.sleep(0.3)

            screen._run_worker(slow(), "test-group", loading_message="Slow work…")
            await asyncio.sleep(0.1)
            assert bar.display
            assert "Slow work…" in str(bar.query_one("#loading_message", Static).content)

            await asyncio.sleep(0.5)
            assert not bar.display

    asyncio.run(run())


def test_bar_hidden_for_untracked_worker():
    """Workers started without a loading message must not show the bar
    (Chat relies on its streamed transcript as feedback instead)."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(120, 40)):
            await asyncio.sleep(0.1)
            screen = app.screen
            bar = screen.query_one("#loading_bar", LoadingBar)

            async def quick():
                await asyncio.sleep(0.2)

            screen._run_worker(quick(), "chat")
            await asyncio.sleep(0.1)
            assert not bar.display

            await asyncio.sleep(0.3)

    asyncio.run(run())


def test_bar_hides_after_worker_cancel():
    """Cancelling a tracked worker must not leave a stuck spinner."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(120, 40)):
            await asyncio.sleep(0.1)
            screen = app.screen
            bar = screen.query_one("#loading_bar", LoadingBar)

            async def forever():
                await asyncio.sleep(60)

            worker = screen._run_worker(
                forever(), "cancel-group", loading_message="Never ends…"
            )
            await asyncio.sleep(0.1)
            assert bar.display

            worker.cancel()
            # Wait for the cancellation to settle and the state message to land.
            for _ in range(50):
                await asyncio.sleep(0.05)
                if not bar.display:
                    break
            assert not bar.display

    asyncio.run(run())


def test_resume_generation_runs_in_worker():
    """Generation must not block the event loop: it starts a worker, disables
    the generate buttons, and reports through the status line and bar."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#resume_btn")
            await asyncio.sleep(0.1)
            screen = app.screen
            assert isinstance(screen, ResumeScreen)

            # Set up a selected resume and job so validation passes.
            screen.resume_manager = Mock()
            screen._selected_resume = "resume.docx"
            mock_job = SimpleNamespace(id="job-1", description="Job description", company="Acme")
            screen.database = Mock()
            screen.database.get_job.return_value = mock_job
            app.selected_job_id = "job-1"

            # threading.Event: the fake generation runs in a worker thread.
            import threading

            gate = threading.Event()

            def blocking_call(*args, **kwargs):
                gate.wait(timeout=5)
                return SimpleNamespace(
                    summary="Summary",
                    updated_skills=["Python"],
                    tailored_sections={"experience": ["Bullet"]},
                )

            screen.resume_manager.load_profile_from_docx.return_value = Mock()
            screen.resume_manager.generate_tailored_resume = blocking_call

            screen._generate_tailored_resume()
            await asyncio.sleep(0.1)

            # Worker started: controls disabled, status set, bar visible.
            assert screen._is_busy("resume")
            assert screen.query_one("#generate_tailored_btn", Button).disabled
            assert screen.query_one("#generate_cover_letter_btn", Button).disabled
            assert screen.query_one("#resume_select", Select).disabled
            status = str(screen.query_one("#resume_status", StatusText).content)
            assert "Generating tailored resume" in status
            bar = screen.query_one("#loading_bar", LoadingBar)
            assert bar.display

            # A second trigger while busy must be rejected with feedback.
            screen._generate_cover_letter()
            assert not screen.resume_manager.generate_cover_letter.called
            status = str(screen.query_one("#resume_status", StatusText).content)
            assert "Generation already in progress" in status

            # Let the worker finish and settle.
            gate.set()
            for _ in range(50):
                await asyncio.sleep(0.05)
                if not screen._is_busy("resume"):
                    break

            assert not screen.query_one("#generate_tailored_btn", Button).disabled
            assert not screen.query_one("#resume_select", Select).disabled
            status = str(screen.query_one("#resume_status", StatusText).content)
            assert "✓ Tailored resume generated" in status
            assert not bar.display

    asyncio.run(run())


def test_resume_generation_failure_reenables_buttons(caplog):
    """A failed generation surfaces the error, re-enables the controls, and
    logs the real traceback from inside the worker's except block."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#resume_btn")
            await asyncio.sleep(0.1)
            screen = app.screen

            screen.resume_manager = Mock()
            screen._selected_resume = "resume.docx"
            mock_job = SimpleNamespace(id="job-1", description="Job description", company="Acme")
            screen.database = Mock()
            screen.database.get_job.return_value = mock_job
            app.selected_job_id = "job-1"

            def boom(*args, **kwargs):
                raise RuntimeError("LLM offline")

            screen.resume_manager.load_profile_from_docx.return_value = Mock()
            screen.resume_manager.generate_cover_letter = boom

            screen._generate_cover_letter()

            for _ in range(50):
                await asyncio.sleep(0.05)
                if not screen._is_busy("resume"):
                    break

            status = str(screen.query_one("#resume_status", StatusText).content)
            assert "Error: LLM offline" in status
            assert not screen.query_one("#generate_tailored_btn", Button).disabled
            assert not screen.query_one("#generate_cover_letter_btn", Button).disabled
            assert not screen.query_one("#resume_select", Select).disabled

            # The traceback must come from the worker's except block.
            assert "Cover letter generation failed" in caplog.text
            assert "RuntimeError: LLM offline" in caplog.text

    asyncio.run(run())


def test_resume_generation_validation_blocks_worker():
    """Missing selections keep the buttons enabled and start no worker."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#resume_btn")
            await asyncio.sleep(0.1)
            screen = app.screen
            screen._selected_resume = "resume.docx"
            app.selected_job_id = None

            screen._generate_tailored_resume()
            await asyncio.sleep(0.1)

            assert not screen._is_busy("resume")
            status = str(screen.query_one("#resume_status", StatusText).content)
            assert status  # some validation message shown

    asyncio.run(run())
