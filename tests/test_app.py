"""
Phase 1 tests: app mount, navigation, tool registry, lazy config.
"""
import asyncio

from textual.widgets import Static

from jobhunt.app import JobHuntApp
from jobhunt.app.screens import chat as chat_module
from jobhunt.app.screens.chat import ChatScreen
from jobhunt.app.screens.dashboard import DashboardScreen
from jobhunt.agent import ToolRegistry
from jobhunt.db import JobHuntDB


def test_app_mounts_to_dashboard():
    """The app must mount the Dashboard as the initial screen."""

    async def run():
        app = JobHuntApp()
        async with app.run_test() as pilot:
            await asyncio.sleep(0.1)
            assert isinstance(app.screen, DashboardScreen)

    asyncio.run(run())


def test_nav_switches_screen():
    """Clicking a nav button must switch to the target screen."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#chat_btn")
            await asyncio.sleep(0.1)
            assert isinstance(app.screen, ChatScreen)

    asyncio.run(run())


def test_fit_screen_analyze_without_profile_guides_user():
    """Fit screen with an empty DB must explain that a profile is needed."""

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#fit_btn")
            await asyncio.sleep(0.1)
            from jobhunt.app.screens.fit import FitScreen
            assert isinstance(app.screen, FitScreen)
            await pilot.click("#analyze_button")
            await asyncio.sleep(0.1)
            status = app.screen.query_one("#fit_status").content
            assert "profile" in str(status).lower()

    asyncio.run(run())


def test_tool_registry_registers_all_tools():
    expected = [
        "search_jobs",
        "get_job_detail",
        "score_fit",
        "tailor_resume",
        "generate_cover_letter",
        "update_status",
        "list_jobs",
    ]
    registry = ToolRegistry()
    tools = registry.list_tools()
    assert all(tool in tools for tool in expected)


def test_agent_settings_are_lazy(monkeypatch):
    """Importing agent/registry must not require oMLX settings; only construction does."""
    import jobhunt.agent as agent_module

    def no_settings():
        raise ValueError("No oMLX settings available")

    monkeypatch.setattr(agent_module, "get_omlx_settings", no_settings)

    assert ToolRegistry().list_tools()

    try:
        agent_module.JobHuntAgent()
    except ValueError:
        pass
    else:
        raise AssertionError("JobHuntAgent should require settings to construct")


class FakeAgent:
    def __init__(self, reply="canned reply", error=None):
        self.reply = reply
        self.error = error
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


def test_chat_round_trip(monkeypatch):
    """Sending a message must produce a user + assistant transcript."""

    async def run():
        fake = FakeAgent()
        monkeypatch.setattr(chat_module, "JobHuntAgent", lambda db=None: fake)
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#chat_btn")
            await asyncio.sleep(0.1)
            await pilot.click("#chat_input")
            await pilot.press("h", "i")
            await pilot.press("enter")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if fake.calls:
                    break
            await asyncio.sleep(0.2)
            assert fake.calls == 1
            transcript = app.screen.query_one("#chat_messages").text
            assert "You:" in transcript
            assert "canned reply" in transcript

    asyncio.run(run())


def test_chat_surfaces_agent_error(monkeypatch):
    """A failed agent call must show the error in the transcript, not crash."""

    async def run():
        fake = FakeAgent(error=RuntimeError("oMLX down"))
        monkeypatch.setattr(chat_module, "JobHuntAgent", lambda db=None: fake)
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#chat_btn")
            await asyncio.sleep(0.1)
            await pilot.click("#chat_input")
            await pilot.press("h", "i")
            await pilot.press("enter")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if fake.calls:
                    break
            await asyncio.sleep(0.2)
            assert "Error:" in app.screen.query_one("#chat_messages").text

    asyncio.run(run())


def test_dashboard_mount_renders_counts():
    """Dashboard should render job and application counts on mount."""
    
    async def run():
        app = JobHuntApp()
        # Mock the database to return specific counts
        app.database = JobHuntDB()
        # Create some test data
        from jobhunt.models import Job, Application
        # Add test job
        test_job = Job(
            id="test_job",
            title="Test Job",
            company="Test Corp",
            location="Test Location",
            description="Test job description",
            url="http://test.com",
            source="test",
            posted_date="2023-01-01"
        )
        app.database.save_job(test_job)
        # Add test application
        test_application = Application(
            job_id="test_job",
            status="applied",
            applied_date="2023-01-01"
        )
        app.database.save_application(test_application)
        
        async with app.run_test() as pilot:
            await asyncio.sleep(0.1)
            # Check that dashboard is displayed
            assert isinstance(app.screen, DashboardScreen)
            # Check that status shows the counts
            status_widget = app.screen.query_one("#status", Static)
            status_content = status_widget.content
            assert "Total Jobs: 1" in str(status_content)
            assert "Applications: 1" in str(status_content)
            
    asyncio.run(run())


def test_dashboard_quick_actions_switch_screens():
    """Dashboard quick action buttons should switch screens."""
    
    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            # Click search jobs button
            await pilot.click("#search_jobs_btn")
            await asyncio.sleep(0.1)
            # Should be on search screen
            from jobhunt.app.screens.search import SearchScreen
            assert isinstance(app.screen, SearchScreen)
            
            # Go back to dashboard
            await pilot.click("#dashboard_btn")
            await asyncio.sleep(0.1)
            
            # Click view jobs button
            await pilot.click("#view_jobs_btn")
            await asyncio.sleep(0.1)
            # Should be on jobs screen
            from jobhunt.app.screens.jobs import JobsScreen
            assert isinstance(app.screen, JobsScreen)
            
            # Go back to dashboard
            await pilot.click("#dashboard_btn")
            await asyncio.sleep(0.1)
            
            # Click generate resume button
            await pilot.click("#generate_resume_btn")
            await asyncio.sleep(0.1)
            # Should be on resume screen
            from jobhunt.app.screens.resume import ResumeScreen
            assert isinstance(app.screen, ResumeScreen)

    asyncio.run(run())
