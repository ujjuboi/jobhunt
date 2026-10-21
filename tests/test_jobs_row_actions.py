"""
UI tests for the Jobs screen row actions (issue #12): the click context menu,
the job details card, the hand-off to the chat screen, and opening the
application URL in the browser.
"""
import asyncio
import webbrowser
from datetime import datetime

from jobhunt.app import JobHuntApp
from jobhunt.app.screens.chat import ChatScreen
from jobhunt.app.screens.fit import FitScreen
from jobhunt.app.screens.jobs import JobsScreen
from jobhunt.db import JobHuntDB
from jobhunt.models import FitScore, Job


def _seed_jobs(database: JobHuntDB, count: int, url: str | None = "https://example.com/jobs/{index}") -> None:
    """Insert ``count`` jobs titled ``Engineer {i}``.

    Args:
        database: The database to write to.
        count: How many jobs to insert.
        url: The URL template for the jobs; ``None`` inserts jobs without a
            URL.
    """
    base = datetime(2026, 8, 1, 12, 0, 0)
    for index in range(count):
        database.save_job(Job(
            id=f"job-{index:03d}",
            title=f"Engineer {index}",
            company="Acme",
            location="Remote",
            description="Do the thing",
            url=url.format(index=index) if url else None,
            posted_date=base,
            tags=["Engineering"],
            source="test",
        ))


async def _wait_until(predicate, attempts: int = 100) -> bool:
    """Poll ``predicate`` until it is true or the attempts run out.

    Args:
        predicate: Zero-argument callable polled between sleeps.
        attempts: How many 50ms polls to try.

    Returns:
        Whether the predicate became true in time.
    """
    for _ in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def _open_jobs_screen(pilot, database: JobHuntDB) -> JobsScreen:
    """Open the Jobs screen and wait for its table to fill.

    Args:
        pilot: The running test pilot.
        database: The database the app should use.

    Returns:
        The mounted :class:`JobsScreen`.
    """
    await pilot.click("#jobs_btn")
    screen = pilot.app.screen
    assert isinstance(screen, JobsScreen)
    assert await _wait_until(lambda: screen.query_one("#jobs_table").row_count > 0)
    return screen


def test_clicking_a_job_row_opens_the_context_menu(tmp_path):
    """A single click selects the job and opens its context menu."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 3)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _open_jobs_screen(pilot, database)
            table = screen.query_one("#jobs_table")
            menu = screen.query_one("#job_context_menu")
            assert menu.display is False

            await pilot.click("#jobs_table", offset=(5, table.header_height + 1))
            assert await _wait_until(lambda: menu.display is True)

            # The click selects the job for the Fit and Resume screens.
            assert app.selected_job_id == "job-001"
            assert "Engineer 1" in str(screen.query_one("#job_menu_title").content)

    asyncio.run(run())


def test_view_details_shows_the_job_card(tmp_path):
    """"View Details" fills the scrollable pane with the job's details."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 3)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _open_jobs_screen(pilot, database)
            details = screen.query_one("#job_details")
            assert details.display is False

            table = screen.query_one("#jobs_table")
            await pilot.click("#jobs_table", offset=(5, table.header_height + 1))
            assert await _wait_until(
                lambda: screen.query_one("#job_context_menu").display is True
            )
            await pilot.click("#view_details_btn")
            assert await _wait_until(lambda: details.display is True)

            card = str(details.text)
            assert "Engineer 1" in card
            assert "Acme" in card
            assert "job-001" in card
            assert "2026-08-01" in card
            assert "Remote" in card
            assert "https://example.com/jobs/1" in card
            assert "Do the thing" in card
            # The menu closes once an action was taken.
            assert screen.query_one("#job_context_menu").display is False

    asyncio.run(run())


def test_chat_about_job_preloads_context_and_switches_screen(tmp_path):
    """"Chat About This Job" loads the job into the chat and switches to it."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 3)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _open_jobs_screen(pilot, database)
            table = screen.query_one("#jobs_table")
            await pilot.click("#jobs_table", offset=(5, table.header_height + 1))
            assert await _wait_until(
                lambda: screen.query_one("#job_context_menu").display is True
            )
            await pilot.click("#chat_job_btn")
            assert await _wait_until(lambda: isinstance(pilot.app.screen, ChatScreen))

            chat_screen = pilot.app.screen
            assert isinstance(chat_screen, ChatScreen)
            # The job is in the conversation as context for the agent.
            assert any(
                "Engineer 1" in message["content"]
                for message in chat_screen.messages
            )
            assert any(
                message["role"] == "system" and "job-001" in message["content"]
                for message in chat_screen.messages
            )
            # The input is pre-filled with a starter question.
            assert str(chat_screen.query_one("#chat_input").value) == ChatScreen.JOB_CONTEXT_PROMPT

    asyncio.run(run())


def test_apply_opens_the_job_url_in_the_browser(tmp_path, monkeypatch):
    """"Apply" opens the job's application URL in the default browser."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 3)
        app.database = database
        opened: list[str] = []
        monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _open_jobs_screen(pilot, database)
            table = screen.query_one("#jobs_table")
            await pilot.click("#jobs_table", offset=(5, table.header_height + 1))
            assert await _wait_until(
                lambda: screen.query_one("#job_context_menu").display is True
            )
            await pilot.click("#apply_btn")
            assert await _wait_until(lambda: bool(opened))
            assert opened == ["https://example.com/jobs/1"]
            assert await _wait_until(
                lambda: "browser" in str(screen.query_one("#jobs_status").content)
            )

    asyncio.run(run())


def test_apply_without_url_reports_the_missing_url(tmp_path, monkeypatch):
    """A job without an application URL is reported instead of opened."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 3, url=None)
        app.database = database
        opened: list[str] = []
        monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _open_jobs_screen(pilot, database)
            table = screen.query_one("#jobs_table")
            await pilot.click("#jobs_table", offset=(5, table.header_height + 1))
            assert await _wait_until(
                lambda: screen.query_one("#job_context_menu").display is True
            )
            await pilot.click("#apply_btn")
            assert await _wait_until(
                lambda: "No application URL" in str(screen.query_one("#jobs_status").content)
            )
            assert opened == []

    asyncio.run(run())


def test_escape_dismisses_the_context_menu(tmp_path):
    """Escape closes the context menu without running an action."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 3)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _open_jobs_screen(pilot, database)
            menu = screen.query_one("#job_context_menu")
            table = screen.query_one("#jobs_table")
            await pilot.click("#jobs_table", offset=(5, table.header_height + 1))
            assert await _wait_until(lambda: menu.display is True)

            await pilot.press("escape")
            assert await _wait_until(lambda: menu.display is False)
            # No details were rendered by dismissing the menu.
            assert screen.query_one("#job_details").display is False

    asyncio.run(run())


def test_clicking_away_dismisses_the_context_menu(tmp_path):
    """A click outside the menu closes it without running an action."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 3)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _open_jobs_screen(pilot, database)
            menu = screen.query_one("#job_context_menu")
            table = screen.query_one("#jobs_table")
            await pilot.click("#jobs_table", offset=(5, table.header_height + 1))
            assert await _wait_until(lambda: menu.display is True)

            await pilot.click("#jobs_filter_input")
            assert await _wait_until(lambda: menu.display is False)
            assert screen.query_one("#job_details").display is False

    asyncio.run(run())


def test_the_context_menu_stays_inside_the_screen(tmp_path):
    """A menu opened on a bottom row is moved up to stay on screen."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 20)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _open_jobs_screen(pilot, database)
            menu = screen.query_one("#job_context_menu")
            table = screen.query_one("#jobs_table")
            await pilot.click(
                "#jobs_table",
                offset=(5, table.header_height + table.row_count - 1),
            )
            assert await _wait_until(lambda: menu.display is True)
            screen_height = app.screen.size.height
            assert await _wait_until(
                lambda: menu.region.y + menu.region.height <= screen_height
            )
            # The menu is still anchored to the clicked row.
            assert app.selected_job_id == "job-019"

    asyncio.run(run())


def test_fit_screen_shows_the_breakdown_when_a_row_is_clicked(tmp_path):
    """Clicking a fit row renders the score breakdown in the detail pane."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "fit.db"))
        _seed_jobs(database, 3)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.click("#fit_btn")
            screen = pilot.app.screen
            assert isinstance(screen, FitScreen)
            assert await _wait_until(
                lambda: screen.query_one("#fit_table").row_count == 3
            )
            screen._fit_scores = {
                "job-000": FitScore(
                    job_id="job-000",
                    score=0.9,
                    explanation="Great fit",
                    matched_skills=["Python"],
                    missing_skills=["Go"],
                    suggested_bullets=["Built a service"],
                )
            }
            table = screen.query_one("#fit_table")
            await pilot.click("#fit_table", offset=(5, table.header_height))
            assert await _wait_until(
                lambda: "Score: 0.90" in str(screen.query_one("#fit_detail").text)
            )
            detail = str(screen.query_one("#fit_detail").text)
            assert "Great fit" in detail
            assert "Python" in detail
            assert app.selected_job_id == "job-000"

    asyncio.run(run())
