"""
Chat screen for JobHunt application
"""
import asyncio
import logging
from typing import List, Dict

from textual.widgets import Static, Input, Button, TextArea
from textual.containers import Container

from .base import BaseScreen
from ...agent import JobHuntAgent
from ...config import get_user_config
from ...db import JobHuntDB

logger = logging.getLogger(__name__)


class ChatScreen(BaseScreen):
    """Chat screen for interacting with the agent"""

    def __init__(self, db: JobHuntDB | None = None):
        super().__init__(name="chat")
        self.db = db
        self.agent: JobHuntAgent | None = None
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": get_user_config().prompts.system}
        ]
        self.transcript = ""

    def _get_content(self):
        return Container(
            Static("Agent Chat", id="chat_title"),
            TextArea(id="chat_messages", read_only=True, show_line_numbers=False),
            Input(placeholder="Type your message...", id="chat_input"),
            Button("Send", id="send_button"),
            id="chat_content"
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._send(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        super().on_button_pressed(event)
        if event.button.id == "send_button":
            input_widget = self.query_one("#chat_input", Input)
            self._send(input_widget.value)

    def _send(self, text: str) -> None:
        text = text.strip()
        if not text or self._is_busy():
            return
        self.messages.append({"role": "user", "content": text})
        self._append_transcript(f"[bold blue]You:[/] {text}\n")
        input_widget = self.query_one("#chat_input", Input)
        input_widget.value = ""
        self._append_transcript("[dim]Thinking...[/]\n")
        self.run_worker(self._ask_agent, group="chat", exclusive=True)

    def _is_busy(self) -> bool:
        return any(
            worker.group == "chat" and worker.is_running
            for worker in self.workers
        )

    def _append_transcript(self, text: str) -> None:
        self.transcript += text
        text_area = self.query_one("#chat_messages", TextArea)
        text_area.text = self.transcript

    def _start_streaming_line(self) -> int:
        """Mark the start of the streaming reply line, replacing 'Thinking...'."""
        thinking = "[dim]Thinking...[/]\n"
        if self.transcript.endswith(thinking):
            self.transcript = self.transcript[: -len(thinking)] + "[green]Agent:[/] "
        else:
            self.transcript += "[green]Agent:[/] "
        return len(self.transcript)

    def _streaming_line(self, start: int, text: str) -> None:
        """Append streamed text onto the agent line, keeping the prefix intact."""
        self.transcript = self.transcript[:start] + text
        text_area = self.query_one("#chat_messages", TextArea)
        text_area.text = self.transcript

    def _finish_streaming_line(self) -> None:
        """Add the newline after a completed streamed reply."""
        if not self.transcript.endswith("\n"):
            self.transcript += "\n"
        text_area = self.query_one("#chat_messages", TextArea)
        text_area.text = self.transcript

    async def _ask_agent(self) -> None:
        try:
            if self.agent is None:
                self.agent = JobHuntAgent(self.db)
            if hasattr(self.agent, "chat_stream"):
                await self._ask_agent_streaming()
            else:
                reply = await asyncio.to_thread(self.agent.chat, list(self.messages))
                self.messages.append({"role": "assistant", "content": reply})
                self._append_transcript(f"[green]Agent:[/] {reply}\n")
        except Exception as e:
            # Log error but don't append the error text to conversation history
            logger.warning("Agent chat failed: %s", e, exc_info=True)
            reply = f"[red]Error:[/] {e}"
            # Instead of appending the error text, we append a marker so it doesn't burden context
            self.messages.append({"role": "assistant", "content": "[error: see logs]"})
            self._append_transcript(f"{reply}\n")

    async def _ask_agent_streaming(self) -> None:
        """Stream the agent reply, updating the transcript as chunks arrive."""
        queue: "asyncio.Queue[str | tuple[str, str] | None]" = asyncio.Queue()
        start = self._start_streaming_line()
        reply_parts: List[str] = []
        error: str | None = None

        def _produce():
            nonlocal error
            try:
                for chunk in self.agent.chat_stream(list(self.messages)):
                    queue.put_nowait(chunk)
            except Exception as e:
                error = str(e)
                logger.warning("Agent streaming failed: %s", e, exc_info=True)
                queue.put_nowait(("error", "[error: see logs]"))
            finally:
                queue.put_nowait(None)

        self.run_worker(asyncio.to_thread(_produce), group="chat_stream", exclusive=True)

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, tuple):
                if item[0] == "error":
                    self._streaming_line(start, f"[red]Error:[/] {item[1]}")
                continue
            reply_parts.append(item)
            self._streaming_line(start, "".join(reply_parts))

        if error:
            self.messages.append({"role": "assistant", "content": error})
            self._append_transcript("\n")
        else:
            self.messages.append({"role": "assistant", "content": "".join(reply_parts)})
            self._finish_streaming_line()
