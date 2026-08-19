"""
Streaming chat tests: the ChatScreen must render agent chunks as they arrive
when the agent exposes chat_stream(), and still fall back gracefully when it
does not.
"""
import asyncio

from jobhunt.app import JobHuntApp
from jobhunt.app.screens import chat as chat_module


class FakeStreamAgent:
    def __init__(self, chunks=("Hello ", "world", "!")):
        self.chunks = chunks
        self.calls = 0

    def chat_stream(self, messages, model=None):
        self.calls += 1
        yield from self.chunks


class FakeEagerAgent:
    """Non-streaming agent used to prove the fallback path."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return "eager reply"


def test_chat_streams_reply_incrementally(monkeypatch):
    async def run():
        fake = FakeStreamAgent()
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
                if "Hello world!" in app.screen.transcript:
                    break
            await asyncio.sleep(0.1)
            transcript = app.screen.query_one("#chat_messages").text
            assert "You:" in transcript
            assert "Hello world!" in transcript
            assert "Thinking..." not in transcript
            assert fake.calls == 1

    asyncio.run(run())


def test_chat_falls_back_when_no_stream(monkeypatch):
    """Agents without chat_stream must still work via the blocking chat()."""

    async def run():
        fake = FakeEagerAgent()
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
            await asyncio.sleep(0.1)
            transcript = app.screen.query_one("#chat_messages").text
            assert "eager reply" in transcript

    asyncio.run(run())