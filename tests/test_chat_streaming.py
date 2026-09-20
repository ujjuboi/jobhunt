"""
Streaming chat tests: the ChatScreen must render agent chunks as they arrive
when the agent exposes chat_stream(), and still fall back gracefully when it
does not.
"""
import asyncio
import threading

from textual.widgets import Button, RichLog

from jobhunt.app import JobHuntApp
from jobhunt.app import components as components_module


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


class FakeBlockingStreamAgent:
    """Streaming agent that stalls mid-reply until the test releases it."""

    def __init__(self):
        self.calls = 0
        self.release = threading.Event()

    def chat_stream(self, messages, model=None):
        self.calls += 1
        yield "partial"
        self.release.wait(timeout=60)
        yield "never shown"


class FakeBlockingChatAgent:
    """Blocking agent that stalls inside chat() until the test releases it."""

    def __init__(self):
        self.calls = 0
        self.release = threading.Event()

    def chat(self, messages):
        self.calls += 1
        self.release.wait(timeout=60)
        return "never shown"


class FakeLoopingStreamAgent:
    """Streaming agent that produces a degenerate repetition loop."""

    def __init__(self, repeats=200):
        self.calls = 0
        self.repeats = repeats

    def chat_stream(self, messages, model=None):
        self.calls += 1
        for _ in range(self.repeats):
            yield "Assistant: hi\n"


def test_chat_streams_reply_incrementally(monkeypatch):
    async def run():
        fake = FakeStreamAgent()
        monkeypatch.setattr(components_module, "JobHuntAgent", lambda database=None: fake)
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
            transcript = app.screen.transcript
            assert "You:" in transcript
            assert "Hello world!" in transcript
            assert "Thinking..." not in transcript
            assert fake.calls == 1

    asyncio.run(run())


def test_chat_falls_back_when_no_stream(monkeypatch):
    """Agents without chat_stream must still work via the blocking chat()."""

    async def run():
        fake = FakeEagerAgent()
        monkeypatch.setattr(components_module, "JobHuntAgent", lambda database=None: fake)
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
            transcript = app.screen.transcript
            assert "eager reply" in transcript

    asyncio.run(run())


def test_chat_rendering_no_raw_markup_tokens(monkeypatch):
    """The RichLog must render style tags instead of displaying them verbatim."""

    async def run():
        fake = FakeStreamAgent()
        monkeypatch.setattr(components_module, "JobHuntAgent", lambda database=None: fake)
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
            await pilot.pause()

            # Read the widget's rendered output: no literal markup tokens, but
            # the expected words are still visible.
            chat_log = app.screen.query_one("#chat_messages", RichLog)
            rendered = "\n".join(
                "".join(segment.text for segment in strip) for strip in chat_log.lines
            )
            assert "[bold" not in rendered
            assert "[green" not in rendered
            assert "[red" not in rendered
            assert "[dim" not in rendered
            assert "[/]" not in rendered
            assert "You:" in rendered
            assert "Hello world!" in rendered

    asyncio.run(run())


def test_chat_renders_user_brackets_literally(monkeypatch):
    """Bracket characters in a user message must render literally and must
    never raise a MarkupError or wedge the chat."""

    async def run():
        fake = FakeStreamAgent()
        monkeypatch.setattr(components_module, "JobHuntAgent", lambda database=None: fake)
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#chat_btn")
            await asyncio.sleep(0.1)
            await pilot.click("#chat_input")
            for key in "check [/] dir":
                await pilot.press(key)
            await pilot.press("enter")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if "Hello world!" in app.screen.transcript:
                    break
            await pilot.pause()

            assert fake.calls == 1
            chat_log = app.screen.query_one("#chat_messages", RichLog)
            rendered = "\n".join(
                "".join(segment.text for segment in strip) for strip in chat_log.lines
            )
            assert "check [/] dir" in rendered
            assert "[bold" not in rendered

    asyncio.run(run())


def test_chat_stop_button_disabled_when_idle(monkeypatch):
    """The Stop button must start disabled and only enable during a reply."""

    async def run():
        monkeypatch.setattr(
            components_module, "JobHuntAgent", lambda database=None: FakeStreamAgent()
        )
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#chat_btn")
            await asyncio.sleep(0.1)
            assert app.screen.query_one("#stop_button", Button).disabled

    asyncio.run(run())


def test_chat_esc_interrupts_stalled_stream(monkeypatch):
    """Pressing Esc while a reply is streaming must stop it and free the chat."""

    async def run():
        fake = FakeBlockingStreamAgent()
        monkeypatch.setattr(components_module, "JobHuntAgent", lambda database=None: fake)
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
                if "partial" in app.screen.transcript:
                    break
            await asyncio.sleep(0.1)

            await pilot.press("escape")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if "[stopped]" in app.screen.transcript:
                    break

            fake.release.set()
            await asyncio.sleep(0.1)

            assert "[stopped]" in app.screen.transcript
            assert "partial" in app.screen.transcript
            assert not app.screen._is_busy("chat")
            assert app.screen.query_one("#stop_button", Button).disabled
            # The partial reply must not be recorded in the model context
            assert [m["role"] for m in app.screen.messages] == ["system", "user"]

            # The chat must remain usable for a fresh message
            app.screen.agent = FakeStreamAgent()
            await pilot.click("#chat_input")
            await pilot.press("a", "g", "a", "i", "n")
            await pilot.press("enter")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if "Hello world!" in app.screen.transcript:
                    break
            await asyncio.sleep(0.1)
            assert "Hello world!" in app.screen.transcript
            assert app.screen.query_one("#stop_button", Button).disabled

    asyncio.run(run())


def test_chat_stop_button_interrupts_blocked_fallback(monkeypatch):
    """Clicking Stop must also interrupt a blocking chat() reply."""

    async def run():
        fake = FakeBlockingChatAgent()
        monkeypatch.setattr(components_module, "JobHuntAgent", lambda database=None: fake)
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

            await pilot.click("#stop_button")
            for _ in range(100):
                await asyncio.sleep(0.05)
                if "Stopped" in app.screen.transcript:
                    break

            fake.release.set()
            await asyncio.sleep(0.1)

            assert "Stopped" in app.screen.transcript
            assert "Thinking..." not in app.screen.transcript
            assert not app.screen._is_busy("chat")
            assert app.screen.query_one("#stop_button", Button).disabled
            assert [m["role"] for m in app.screen.messages] == ["system", "user"]

    asyncio.run(run())


def test_chat_stops_repetition_loop(monkeypatch):
    """A stream that degenerates into repetition must be cut off cleanly."""

    async def run():
        fake = FakeLoopingStreamAgent()
        monkeypatch.setattr(components_module, "JobHuntAgent", lambda database=None: fake)
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
                if "possible repetition loop" in app.screen.transcript:
                    break
            await asyncio.sleep(0.1)

            assert "possible repetition loop" in app.screen.transcript
            assert not app.screen._is_busy("chat")
            assert app.screen.query_one("#stop_button", Button).disabled
            # The looped garbage must not reach the model context
            assistant_messages = [
                m["content"] for m in app.screen.messages if m["role"] == "assistant"
            ]
            assert assistant_messages == []

    asyncio.run(run())