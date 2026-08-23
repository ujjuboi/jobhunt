"""
Settings screen for JobHunt application
"""
import asyncio

from textual.widgets import Static, Input, Button, Select, TextArea
from textual.containers import Container, Vertical

from .base import BaseScreen
from ...config import get_omlx_settings
from ...config.user_config import (
    ALLOWED_SOURCES,
    UserConfig,
    load_user_config,
    save_user_config,
)


class SettingsScreen(BaseScreen):
    """Settings screen for configuration (sources, model, scoring)."""

    def __init__(self):
        super().__init__(name="settings")

    def _get_content(self):
        return Container(
            Static("Settings", id="settings_title"),
            Vertical(
                Static("oMLX Configuration:", classes="section_title"),
                Static(id="base_url"),
                Static("API Key: [hidden]", id="api_key"),
                id="omlx_block",
            ),
            Vertical(
                Static("Application Settings:", classes="section_title"),
                Static("Enabled sources (comma-separated):"),
                Input(placeholder="greenhouse, lever, ashby", id="sources_input"),
                Static("Chat model:"),
                Input(placeholder="Qwen3-30B-A3B-6bit", id="model_input"),
                Static("Scoring mode:"),
                Select(
                    options=[
                        ("Hybrid (embedding + LLM confirm)", "hybrid"),
                        ("Embedding only", "embedding"),
                        ("LLM only", "llm"),
                    ],
                    id="score_mode_select",
                    value="hybrid",
                ),
                id="app_settings_block",
            ),
            Vertical(
                Static("LinkedIn login:", classes="section_title"),
                Static("Sign in through the browser once; the session is reused from cache."),
                Button("Login to LinkedIn", id="linkedin_login_btn"),
                Static("", id="linkedin_status"),
                id="linkedin_block",
            ),
            Vertical(
                Static("System prompt (shown on the Chat screen):", classes="section_title"),
                TextArea(id="system_prompt", show_line_numbers=False),
                id="prompt_block",
            ),
            Button("Save Config", id="save_config_btn"),
            Static("", id="settings_status"),
            id="settings_content",
        )

    def on_mount(self):
        settings = get_omlx_settings()
        self.query_one("#base_url", Static).update(f"Base URL: {settings.base_url}")

        config = load_user_config()

        sources = self.query_one("#sources_input", Input)
        sources.value = ", ".join(config.sources.enabled)

        self.query_one("#model_input", Input).value = config.model.chat
        self.query_one("#score_mode_select", Select).value = config.scoring.mode
        self.query_one("#system_prompt", TextArea).text = config.prompts.system
        self._toggle_linkedin_block()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Show/hide the LinkedIn login block based on the enabled sources."""
        if event.input.id == "sources_input":
            self._toggle_linkedin_block()

    def _toggle_linkedin_block(self) -> None:
        """Display the LinkedIn login block only when linkedin is a source."""
        sources_val = self.query_one("#sources_input", Input).value.lower()
        show = "linkedin" in sources_val
        self.query_one("#linkedin_block").display = "block" if show else "none"
        if not show:
            self.query_one("#linkedin_status", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        super().on_button_pressed(event)
        if event.button.id == "save_config_btn":
            self._save_config()
        elif event.button.id == "linkedin_login_btn":
            self._login_linkedin()

    def _login_linkedin(self) -> None:
        """Kick off a one-time LinkedIn browser login in the background."""
        status = self.query_one("#linkedin_status", Static)
        status.update("Launching browser for LinkedIn login...")
        self.query_one("#linkedin_login_btn", Button).disabled = True
        self.run_worker(self._async_linkedin_login, group="linkedin", exclusive=True)

    async def _async_linkedin_login(self) -> None:
        status = self.query_one("#linkedin_status", Static)
        try:
            await asyncio.to_thread(self._linkedin_login_blocking)
            status.update("LinkedIn logged in. Session saved for headless reuse.")
        except Exception as e:
            status.update(f"LinkedIn login failed: {e}")
        finally:
            self.query_one("#linkedin_login_btn", Button).disabled = False

    def _linkedin_login_blocking(self) -> bool:
        """Blocking Playwright login, run off the event loop."""
        from ...sources.linkedin import LinkedInAdapter

        adapter = LinkedInAdapter()
        adapter.login()
        return True

    def _save_config(self) -> None:
        status = self.query_one("#settings_status", Static)

        def _clean(value: str) -> str:
            return ",".join(piece.strip() for piece in value.split(",") if piece.strip())

        sources_raw = _clean(self.query_one("#sources_input", Input).value)
        sources = []
        for s in sources_raw.split(","):
            s = s.strip().lower()
            if s in ALLOWED_SOURCES and s not in sources:
                sources.append(s)

        model = self.query_one("#model_input", Input).value.strip()
        mode = str(self.query_one("#score_mode_select", Select).value)
        system_prompt = self.query_one("#system_prompt", TextArea).text

        config = load_user_config()
        config.sources.enabled = sources or config.sources.enabled
        if model:
            config.model.chat = model
        config.scoring.mode = mode
        config.prompts.system = system_prompt

        try:
            path = save_user_config(config)
            status.update(f"Saved config to {path}")
        except Exception as e:
            status.update(f"Failed to save config: {e}")