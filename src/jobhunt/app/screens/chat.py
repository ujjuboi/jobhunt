"""
Chat screen for the JobHunt TUI.

An interactive transcript with the agent, streaming reply text as chunks
arrive (when the agent exposes ``chat_stream``) or falling back to blocking
``chat`` replies, with errors surfaced in-line rather than polluting the
conversation history.
"""
import asyncio
import logging
from typing import List, Dict

from textual.containers import Container
from textual.widgets import Button, Input

from ...config import get_user_config
from ...db import JobHuntDB
from ..components import ActionButton, ScrollableTextWindow
from .base import BaseScreen

logger = logging.getLogger(__name__)


class ChatScreen(BaseScreen):
    """Screen for chatting with the JobHunt agent."""

    THINKING_TEXT = "[dim]Thinking...[/]\n"

    def __init__(self, database: JobHuntDB | None = None) -> None:
        super().__init__(name="chat", database=database)
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": get_user_config().prompts.system}
        ]
        self.transcript = ""

    def _get_content(self):
        """Compose the chat body.

        Returns:
            A container with the page title, the scrolling transcript, the
            message input, and the Send button (ids preserved).
        """
        return Container(
            self._title("Agent Chat", id="chat_title"),
            ScrollableTextWindow(id="chat_messages"),
            Input(placeholder="Type your message...", id="chat_input"),
            ActionButton("Send", id="send_button"),
            id="chat_content"
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Send the submitted input text.

        Args:
            event: The input-submitted event.
        """
        self._send(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the Send button.

        Args:
            event: The button-pressed event; only ``send_button`` is
                handled, everything else is delegated to the base.
        """
        super().on_button_pressed(event)
        if event.button.id == "send_button":
            input_widget = self.query_one("#chat_input", Input)
            self._send(input_widget.value)

    def _send(self, text: str) -> None:
        """Queue a user message and ask the agent in the background.

        Args:
            text: The raw message text (stripped before sending).
        """
        text = text.strip()
        if not text or self._is_busy("chat"):
            return
        self.messages.append({"role": "user", "content": text})
        self._append_transcript(f"[bold blue]You:[/] {text}\n")
        input_widget = self.query_one("#chat_input", Input)
        input_widget.value = ""
        self._append_transcript(self.THINKING_TEXT)
        self._run_worker(self._ask_agent, "chat")

    def _append_transcript(self, text: str) -> None:
        """Append ``text`` to the running transcript.

        Args:
            text: The text to append verbatim to the transcript.
        """
        self.transcript += text
        text_area = self.query_one("#chat_messages", ScrollableTextWindow)
        text_area.text = self.transcript

    def _start_streaming_line(self) -> int:
        """Mark the start of the streaming reply line.

        Returns:
            The transcript length at the start of the agent's reply.
        """
        thinking = self.THINKING_TEXT
        if self.transcript.endswith(thinking):
            self.transcript = self.transcript[: -len(thinking)] + "[green]Agent:[/] "
        else:
            self.transcript += "[green]Agent:[/] "
        return len(self.transcript)

    def _streaming_line(self, start: int, text: str) -> None:
        """Replace everything from ``start`` onward with ``text``.

        Args:
            start: Index into the transcript marking the reply start.
            text: The accumulated streamed reply text.
        """
        self.transcript = self.transcript[:start] + text
        text_area = self.query_one("#chat_messages", ScrollableTextWindow)
        text_area.text = self.transcript

    def _finish_streaming_line(self) -> None:
        """Add the newline after a completed streamed reply."""
        if not self.transcript.endswith("\n"):
            self.transcript += "\n"
        text_area = self.query_one("#chat_messages", ScrollableTextWindow)
        text_area.text = self.transcript

    async def _ask_agent(self) -> None:
        """Request a reply for the current conversation history."""
        try:
            agent = self.agent
            if agent is None:
                raise RuntimeError("oMLX unavailable — could not create chat agent")
            if hasattr(agent, "chat_stream"):
                await self._ask_agent_streaming()
            else:
                reply = await asyncio.to_thread(agent.chat, list(self.messages))
                self.messages.append({"role": "assistant", "content": reply})
                self._append_transcript(f"[green]Agent:[/] {reply}\n")
        except Exception as error:
            # Log error but don't append the error text to conversation history
            logger.warning("Agent chat failed: %s", error, exc_info=True)
            reply = f"[red]Error:[/] {error}"
            # Append a marker instead of the raw error text to keep it out of
            # the model's context budget.
            self.messages.append({"role": "assistant", "content": "[error: see logs]"})
            self._append_transcript(f"{reply}\n")

    async def _ask_agent_streaming(self) -> None:
        """Stream the agent reply, updating the transcript as chunks arrive."""
        queue: "asyncio.Queue[str | tuple[str, str] | None]" = asyncio.Queue()
        start = self._start_streaming_line()
        reply_parts: List[str] = []
        error: str | None = None

        def _produce() -> None:
            nonlocal error
            try:
                for piece in self.agent.chat_stream(list(self.messages)):
                    queue.put_nowait(piece)
            except Exception as error:
                error = str(error)
                logger.warning("Agent streaming failed: %s", error, exc_info=True)
                queue.put_nowait(("error", "[error: see logs]"))
            finally:
                queue.put_nowait(None)

        self.run_worker(asyncio.to_thread(_produce), group="chat_stream", exclusive=True)

        while True:
            piece = await queue.get()
            if piece is None:
                break
            if isinstance(piece, tuple):
                if piece[0] == "error":
                    self._streaming_line(start, f"[red]Error:[/] {piece[1]}")
                continue
            reply_parts.append(piece)
            self._streaming_line(start, "".join(reply_parts))

        if error:
            self.messages.append({"role": "assistant", "content": error})
            self._append_transcript("\n")
        else:
            self.messages.append({"role": "assistant", "content": "".join(reply_parts)})
            self._finish_streaming_line()