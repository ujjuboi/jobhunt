"""
Phase 1 tests: app mount, navigation, tool registry, lazy config.
"""
import asyncio

from jobhunt.app import JobHuntApp
from jobhunt.app.screens import chat as chat_module
from jobhunt.app.screens.chat import ChatScreen
from jobhunt.app.screens.dashboard import DashboardScreen
from jobhunt.agent import ToolRegistry


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
        monkeypatch.setattr(chat_module, "JobHuntAgent", lambda: fake)
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
        monkeypatch.setattr(chat_module, "JobHuntAgent", lambda: fake)
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
