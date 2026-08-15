"""
Chat screen for JobHunt application
"""
import asyncio
from typing import List, Dict

from textual.widgets import Static, Input, Button, TextArea
from textual.containers import Container

from .base import BaseScreen
from ...agent import JobHuntAgent
from ...db import JobHuntDB


class ChatScreen(BaseScreen):
    """Chat screen for interacting with the agent"""

    def __init__(self, db: JobHuntDB | None = None):
        super().__init__(name="chat")
        self.db = db
        self.agent: JobHuntAgent | None = None
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": "You are a helpful job-hunting assistant."}
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

    async def _ask_agent(self) -> None:
        try:
            if self.agent is None:
                self.agent = JobHuntAgent(self.db)
            reply = await asyncio.to_thread(self.agent.chat, list(self.messages))
        except Exception as e:
            reply = f"[red]Error:[/] {e}"
        self.messages.append({"role": "assistant", "content": reply})
        self._append_transcript(f"[green]Agent:[/] {reply}\n")

    def _append_transcript(self, text: str) -> None:
        self.transcript += text
        text_area = self.query_one("#chat_messages", TextArea)
        text_area.text = self.transcript
