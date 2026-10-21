"""
UI tests for jobs/fit screen pagination, text filtering, and per-page fit
ranking (issue #10).
"""
import asyncio
from datetime import datetime, timedelta

from jobhunt.app import JobHuntApp
from jobhunt.app.screens import fit as fit_module
from jobhunt.app.screens.fit import FitScreen
from jobhunt.app.screens.jobs import JobsScreen
from jobhunt.db import JobHuntDB
from jobhunt.models import FitScore, Job, Profile


def _seed_jobs(database: JobHuntDB, count: int, title: str = "Engineer") -> None:
    """Insert ``count`` jobs titled ``{title} {i}``, newest first."""
    base = datetime(2026, 8, 1, 12, 0, 0)
    for index in range(count):
        database.save_job(Job(
            id=f"job-{index:03d}",
            title=f"{title} {index}",
            company="Acme",
            location="Remote",
            description="Do the thing",
            url=f"https://example.com/jobs/{index}",
            posted_date=base - timedelta(minutes=index),
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


async def _settle_button(pilot, button) -> None:
    """Wait out a button's press animation so a follow-up click can land.

    Textual keeps the ``-active`` class on a pressed button for
    ``active_effect_duration`` (~0.3s); its CSS changes the button's border
    and hit region, so an immediate second ``pilot.click`` at the same spot
    misses. Real typing is far slower than the animation.

    Args:
        pilot: The running test pilot.
        button: The button widget that was just pressed.
    """
    await pilot.pause()
    await _wait_until(lambda: not button.has_class("-active"), attempts=20)


def test_jobs_screen_paginates_through_all_results(tmp_path):
    """The jobs table pages 20 rows at a time through the full result set."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 45)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.click("#jobs_btn")
            screen = app.screen
            assert isinstance(screen, JobsScreen)
            assert await _wait_until(
                lambda: "page 1 of 3" in str(screen.query_one("#jobs_status").content)
            )
            assert screen.query_one("#jobs_table").row_count == 20
            indicator = screen.query_one("#jobs_page_indicator")
            assert "Page 1 of 3" in str(indicator.content)
            assert screen.query_one("#prev_page_btn").disabled is True
            assert screen.query_one("#next_page_btn").disabled is False

            await pilot.click("#next_page_btn")
            await _settle_button(pilot, screen.query_one("#next_page_btn"))
            assert await _wait_until(
                lambda: "page 2 of 3" in str(screen.query_one("#jobs_status").content)
            )
            assert screen.query_one("#jobs_table").row_count == 20
            assert screen.query_one("#prev_page_btn").disabled is False

            await pilot.click("#next_page_btn")
            assert await _wait_until(
                lambda: "page 3 of 3" in str(screen.query_one("#jobs_status").content)
            )
            assert screen.query_one("#jobs_table").row_count == 5
            assert screen.query_one("#next_page_btn").disabled is True

    asyncio.run(run())


def test_jobs_screen_filter_narrows_results_and_resets_page(tmp_path):
    """Typing in the filter input narrows the table and returns to page 1."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "jobs.db"))
        _seed_jobs(database, 25, title="Engineer")
        for index in range(5):
            database.save_job(Job(
                id=f"des-{index:03d}",
                title=f"Designer {index}",
                company="Acme",
                location="Remote",
                description="Design the thing",
                url=f"https://example.com/design/{index}",
                posted_date=datetime(2026, 8, 2) - timedelta(minutes=index),
                tags=[],
                source="test",
            ))
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.click("#jobs_btn")
            screen = app.screen
            assert isinstance(screen, JobsScreen)
            assert await _wait_until(
                lambda: "page 1 of 2" in str(screen.query_one("#jobs_status").content)
            )

            filter_input = screen.query_one("#jobs_filter_input")
            filter_input.value = "designer"
            screen.on_input_changed(type("Ev", (), {"input": filter_input})())
            assert await _wait_until(
                lambda: "jobs matching" in str(screen.query_one("#jobs_status").content)
            )
            assert screen.query_one("#jobs_table").row_count == 5
            assert "Page 1 of 1" in str(screen.query_one("#jobs_page_indicator").content)
            assert screen.query_one("#next_page_btn").disabled is True

            filter_input.value = ""
            screen.on_input_changed(type("Ev", (), {"input": filter_input})())
            assert await _wait_until(
                lambda: "page 1 of 2" in str(screen.query_one("#jobs_status").content)
            )
            assert screen.query_one("#jobs_table").row_count == 20

    asyncio.run(run())


class _FakeScorePipeline:
    """Stand-in for ScorePipeline: later-listed jobs score higher."""

    batches = []

    def __init__(self, database, embedding_client, agent=None) -> None:
        pass

    def score(self, jobs, profile):
        job_ids = [job_entry.id for job_entry in jobs]
        _FakeScorePipeline.batches.append(job_ids)
        return [
            FitScore(job_id=job_id, score=float(index + 1), explanation="looks fine")
            for index, job_id in enumerate(job_ids)
        ]


def _row_keys(data_table):
    """Return a DataTable's row keys in display order.

    Args:
        data_table: The table widget to read.

    Returns:
        The string row keys top-to-bottom as displayed.
    """
    return [row.key.value for row in data_table.ordered_rows]


def test_fit_screen_ranks_each_page_once_and_reuses_cache(tmp_path, monkeypatch):
    """Analyze ranks the visible page; paging ranks the next batch once."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "fit.db"))
        _seed_jobs(database, 30)
        database.save_profile(Profile(name="Ada", email="ada@example.com", skills=["Python"]))
        app.database = database
        _FakeScorePipeline.batches = []
        monkeypatch.setattr(fit_module, "ScorePipeline", _FakeScorePipeline)
        monkeypatch.setattr(fit_module, "EmbeddingClient", lambda: None)

        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.click("#fit_btn")
            screen = app.screen
            assert isinstance(screen, FitScreen)
            assert await _wait_until(
                lambda: "jobs available" in str(screen.query_one("#fit_status").content)
            )
            assert screen.query_one("#fit_table").row_count == 20
            # Before scoring, rows keep posting order with posting-position ranks.
            assert _row_keys(screen.query_one("#fit_table"))[0] == "job-000"
            assert screen.query_one("#fit_table").get_row_at(0)[0] == "1"

            await pilot.click("#analyze_button")
            assert await _wait_until(
                lambda: "Scored 20 of 20" in str(screen.query_one("#fit_status").content)
            )
            assert _FakeScorePipeline.batches == [["job-%03d" % i for i in range(20)]]
            assert screen.query_one("#fit_loading").display is False
            # The filter input is locked only while scoring runs.
            assert screen.query_one("#fit_filter_input").disabled is False
            # Row selection still surfaces the cached breakdown.
            assert len(screen._fit_scores) == 20
            # Scored rows sort by score descending (later ids scored higher),
            # while the rank column keeps the posting position.
            fit_table = screen.query_one("#fit_table")
            assert _row_keys(fit_table) == [
                "job-%03d" % index for index in range(19, -1, -1)
            ]
            assert fit_table.get_row_at(0)[0] == "20"

            await pilot.click("#next_page_btn")
            # Paging auto-ranks the new page (10 remaining jobs).
            assert await _wait_until(
                lambda: "Scored 10 of 10" in str(screen.query_one("#fit_status").content)
            )
            assert _FakeScorePipeline.batches[1] == ["job-%03d" % i for i in range(20, 30)]
            assert screen.query_one("#fit_table").row_count == 10
            assert _row_keys(screen.query_one("#fit_table"))[0] == "job-029"

            # Going back to page 1 must not re-rank known scores.
            await pilot.click("#prev_page_btn")
            assert await _wait_until(
                lambda: "Page 1 of 2" in str(screen.query_one("#fit_page_indicator").content)
            )
            await asyncio.sleep(0.3)
            assert len(_FakeScorePipeline.batches) == 2
            assert screen.query_one("#fit_table").row_count == 20
            # Cached scores keep the page in score order on revisit.
            assert _row_keys(screen.query_one("#fit_table"))[0] == "job-019"

    asyncio.run(run())


def test_fit_screen_loading_locks_filter_input(tmp_path):
    """Toggling the ranking loading state locks/unlocks input and paging."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "fit.db"))
        _seed_jobs(database, 5)
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.click("#fit_btn")
            screen = app.screen
            assert isinstance(screen, FitScreen)
            assert await _wait_until(
                lambda: "jobs available" in str(screen.query_one("#fit_status").content)
            )
            filter_input = screen.query_one("#fit_filter_input")
            prev_button = screen.query_one("#prev_page_btn")
            next_button = screen.query_one("#next_page_btn")

            screen._set_loading(True)
            assert filter_input.disabled is True
            assert prev_button.disabled is True
            assert next_button.disabled is True

            screen._set_loading(False)
            assert filter_input.disabled is False
            assert prev_button.disabled is False
            assert next_button.disabled is False

    asyncio.run(run())


def test_jobs_in_display_order_puts_scored_first_by_score():
    """Scored jobs lead, sorted by score desc; unscored keep posting order."""
    base = datetime(2026, 8, 1, 12, 0, 0)
    jobs = [
        Job(
            id=f"j{index}",
            title=f"Engineer {index}",
            company="Acme",
            location="Remote",
            description="Do the thing",
            url=f"https://example.com/jobs/{index}",
            posted_date=base - timedelta(minutes=index),
            tags=[],
            source="test",
        )
        for index in range(4)
    ]
    screen = FitScreen(database=None)
    screen._fit_scores = {
        "j0": FitScore(job_id="j0", score=0.2, explanation="fine"),
        "j1": FitScore(job_id="j1", score=0.9, explanation="fine"),
        "j2": FitScore(job_id="j2", score=0.9, explanation="fine"),
    }
    ordered = [job_entry.id for job_entry in screen._jobs_in_display_order(jobs)]
    # j1/j2 tie at 0.9 and keep posting order; unscored j3 trails.
    assert ordered == ["j1", "j2", "j0", "j3"]


def test_fit_screen_filter_narrows_results(tmp_path):
    """The fit filter narrows the table; no profile means no ranking."""

    async def run():
        app = JobHuntApp()
        database = JobHuntDB(str(tmp_path / "fit.db"))
        _seed_jobs(database, 25, title="Engineer")
        for index in range(5):
            database.save_job(Job(
                id=f"des-{index:03d}",
                title=f"Designer {index}",
                company="Acme",
                location="Remote",
                description="Design the thing",
                url=f"https://example.com/design/{index}",
                posted_date=datetime(2026, 8, 2) - timedelta(minutes=index),
                tags=[],
                source="test",
            ))
        app.database = database
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.click("#fit_btn")
            screen = app.screen
            assert isinstance(screen, FitScreen)
            assert await _wait_until(
                lambda: "jobs available" in str(screen.query_one("#fit_status").content)
            )

            filter_input = screen.query_one("#fit_filter_input")
            filter_input.value = "designer"
            screen.on_input_changed(type("Ev", (), {"input": filter_input})())
            assert await _wait_until(
                lambda: screen.query_one("#fit_table").row_count == 5
            )
            assert "Page 1 of 1" in str(screen.query_one("#fit_page_indicator").content)
            # No profile -> scores stay unscored and no ranking kicks off.
            assert "No profile found" in str(screen.query_one("#fit_status").content)

    asyncio.run(run())
