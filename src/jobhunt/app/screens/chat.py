"""
Chat screen for the JobHunt TUI.

An interactive transcript with the agent, streaming reply text as chunks
arrive (when the agent exposes ``chat_stream``) or falling back to blocking
``chat`` replies, with errors surfaced in-line rather than polluting the
conversation history.
"""
import asyncio
import logging
import threading
from typing import List, Dict

from rich.markup import escape
from textual.containers import Container, Horizontal
from textual.widgets import Button, Input, RichLog

from ...config import get_user_config
from ...db import JobHuntDB
from ..components import ActionButton
from .base import BaseScreen

logger = logging.getLogger(__name__)


class ChatScreen(BaseScreen):
    """Screen for chatting with the JobHunt agent."""

    THINKING_TEXT = "[dim]Thinking...[/]\n"
    MAX_REPLY_CHARS = 20000
    LOOP_WINDOW = 80
    LOOP_MAX_PERIOD = 20

    BINDINGS = [("escape", "stop_chat", "Stop")]

    def __init__(self, database: JobHuntDB | None = None) -> None:
        super().__init__(name="chat", database=database)
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": get_user_config().prompts.system}
        ]
        self.transcript = ""
        self._generation_stop: threading.Event | None = None

    def _get_content(self):
        """Compose the chat body.

        Returns:
            A container with the page title, the scrolling ``RichLog`` transcript
            (renders Textual rich-markup; app-generated prefixes carry style tags
            while user and agent message text is escaped), the message input, and
            the Send button (ids preserved).
        """
        return Container(
            self._title("Agent Chat", id="chat_title"),
            RichLog(id="chat_messages", markup=True, wrap=True),
            Input(placeholder="Type your message...", id="chat_input"),
            Horizontal(
                ActionButton("Send", id="send_button"),
                ActionButton("Stop", id="stop_button", disabled=True),
            ),
            id="chat_content"
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Send the submitted input text.

        Args:
            event: The input-submitted event.
        """
        self._send(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the Send and Stop buttons.

        Args:
            event: The button-pressed event; ``send_button`` starts a chat
                turn and ``stop_button`` interrupts the in-flight reply,
                everything else is delegated to the base.
        """
        super().on_button_pressed(event)
        if event.button.id == "send_button":
            input_widget = self.query_one("#chat_input", Input)
            self._send(input_widget.value)
        elif event.button.id == "stop_button":
            self._stop_chat()

    def action_stop_chat(self) -> None:
        """Interrupt the in-flight chat reply (bound to the Esc key)."""
        self._stop_chat()

    def _stop_chat(self) -> None:
        """Cancel the in-flight reply so the conversation can continue.

        Best-effort: cancels the consumers in the ``chat`` and ``chat_stream``
        worker groups; an underlying network thread cannot be killed, but a
        looping stream stops producing between chunks.
        """
        if not self._is_busy("chat"):
            return
        if self._generation_stop is not None:
            self._generation_stop.set()
        for worker in list(self.workers):
            if worker.group in ("chat", "chat_stream"):
                worker.cancel()

    def _mark_stopped(self, note: str = "Stopped", suffix: str = "stopped") -> None:
        """Mark the transcript with a visible stop marker.

        Replaces the trailing ``Thinking...`` line when nothing was produced,
        otherwise appends a marker after the partial reply.

        Args:
            note: The marker text shown when no reply was produced.
            suffix: The trailing marker appended after a partial reply.
        """
        if self.transcript.endswith(self.THINKING_TEXT):
            self.transcript = self.transcript[: -len(self.THINKING_TEXT)] + (
                f"[yellow]{note}[/]\n"
            )
        else:
            self.transcript += f"[yellow] [{suffix}][/]\n"
        self._render_transcript()

    def _is_runaway(self, text: str) -> bool:
        """Return True when a reply looks like a degenerate repetition loop.

        Guards against models that stream an endless repeat (e.g.
        ``Assistant: hi`` forever): either the reply exceeds a hard length cap
        or the tail of the reply is a single repeating block of at most
        ``LOOP_MAX_PERIOD`` chars repeated across ``LOOP_WINDOW`` chars.

        Args:
            text: The accumulated reply text to inspect.

        Returns:
            True when the reply should be abandoned as a runaway.
        """
        if len(text) > self.MAX_REPLY_CHARS:
            return True
        window = text[-self.LOOP_WINDOW:]
        for period in range(1, self.LOOP_MAX_PERIOD + 1):
            if len(window) < period * 4:
                continue
            if all(
                window[i] == window[i - period]
                for i in range(period, len(window))
            ):
                return True
        return False

    def _mark_repetition_loop(self) -> None:
        """Mark the transcript for a runaway reply and log a warning."""
        logger.warning("Chat reply abandoned: possible repetition loop")
        self._mark_stopped(
            "Reply stopped - possible repetition loop. Try a different chat model in Settings.",
            "stopped: possible repetition loop",
        )

    def _set_stop_available(self, available: bool) -> None:
        """Enable or disable the Stop button.

        Args:
            available: True to enable the Stop button, False to disable it.
        """
        self.query_one("#stop_button", Button).disabled = not available

    def _send(self, text: str) -> None:
        """Queue a user message and ask the agent in the background.

        Args:
            text: The raw message text (stripped before sending).
        """
        text = text.strip()
        if not text or self._is_busy("chat"):
            return
        self.messages.append({"role": "user", "content": text})
        self._append_transcript(f"[bold blue]You:[/] {escape(text)}\n")
        input_widget = self.query_one("#chat_input", Input)
        input_widget.value = ""
        self._append_transcript(self.THINKING_TEXT)
        self._generation_stop = threading.Event()
        self._set_stop_available(True)
        self._run_worker(self._ask_agent, "chat")

    def _render_transcript(self) -> None:
        """Re-render the full transcript into the RichLog widget.

        Clears the widget and writes the entire ``self.transcript`` string so
        that rich-markup tags (``[bold]``, ``[green]``, ``[red]``, ``[dim]``)
        are properly styled rather than displayed verbatim. User and agent
        message text is escaped before it is embedded in the transcript, so
        bracket characters in message content render literally.
        """
        chat_log = self.query_one("#chat_messages", RichLog)
        chat_log.clear()
        chat_log.write(self.transcript)

    def _append_transcript(self, text: str) -> None:
        """Append ``text`` to the running transcript and re-render.

        Args:
            text: The text to append verbatim to the transcript.
        """
        self.transcript += text
        self._render_transcript()

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
        self._render_transcript()

    def _finish_streaming_line(self) -> None:
        """Add the newline after a completed streamed reply and re-render."""
        if not self.transcript.endswith("\n"):
            self.transcript += "\n"
        self._render_transcript()

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
                if self._is_runaway(reply):
                    self._mark_repetition_loop()
                    return
                self.messages.append({"role": "assistant", "content": reply})
                self._append_transcript(f"[green]Agent:[/] {escape(reply)}\n")
        except asyncio.CancelledError:
            # Interrupted by the user (Stop/Esc): never append the partial
            # reply to the model context, just mark the transcript and stop.
            self._mark_stopped()
            logger.info("Chat reply interrupted by user")
            raise
        except Exception as error:
            # Log error but don't append the error text to conversation history
            logger.warning("Agent chat failed: %s", error, exc_info=True)
            reply = f"[red]Error:[/] {escape(str(error))}"
            # Append a marker instead of the raw error text to keep it out of
            # the model's context budget.
            self.messages.append({"role": "assistant", "content": "[error: see logs]"})
            self._append_transcript(f"{reply}\n")
        finally:
            self._set_stop_available(False)

    async def _ask_agent_streaming(self) -> None:
        """Stream the agent reply, updating the transcript as chunks arrive."""
        queue: "asyncio.Queue[str | tuple[str, str] | None]" = asyncio.Queue()
        start = self._start_streaming_line()
        reply_parts: List[str] = []
        error: str | None = None
        stopped: bool = False

        def _produce() -> None:
            nonlocal error
            try:
                for piece in self.agent.chat_stream(list(self.messages)):
                    if self._generation_stop is not None and self._generation_stop.is_set():
                        break
                    queue.put_nowait(piece)
            except Exception as error:
                error = str(error)
                logger.warning("Agent streaming failed: %s", error, exc_info=True)
                queue.put_nowait(("error", "[error: see logs]"))
            finally:
                queue.put_nowait(None)

        self._run_worker(asyncio.to_thread(_produce), "chat_stream")

        while True:
            piece = await queue.get()
            if piece is None:
                break
            if isinstance(piece, tuple):
                if piece[0] == "error":
                    self._streaming_line(
                        start, f"[red]Error:[/] {escape(piece[1])}"
                    )
                continue
            reply_parts.append(piece)
            reply = "".join(reply_parts)
            if self._is_runaway(reply):
                self._mark_repetition_loop()
                if self._generation_stop is not None:
                    self._generation_stop.set()
                for worker in list(self.workers):
                    if worker.group == "chat_stream":
                        worker.cancel()
                stopped = True
                break
            self._streaming_line(start, escape(reply))

        if stopped:
            return
        if error:
            self.messages.append({"role": "assistant", "content": error})
            self._append_transcript("\n")
        else:
            self.messages.append({"role": "assistant", "content": "".join(reply_parts)})
            self._finish_streaming_line()