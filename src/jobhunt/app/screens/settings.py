"""
Settings screen for the JobHunt TUI.

Edits the user configuration (enabled sources, chat model, scoring mode,
system prompt), shows the oMLX endpoint, and provides the one-time LinkedIn
browser login flow.
"""
import asyncio

from textual.containers import Container, Vertical
from textual.widgets import Button, Input, Select, Static, TextArea

from ...config import get_omlx_settings
from ...config.user_config import (
    ALLOWED_SOURCES,
    UserConfig,
    load_user_config,
    save_user_config,
)
from ..components import ActionButton, StatusText
from .base import BaseScreen


class SettingsScreen(BaseScreen):
    """Settings screen for configuration (sources, model, scoring)."""

    def __init__(self, database=None) -> None:
        super().__init__(name="settings", database=database)

    def _get_content(self):
        """Compose the settings body.

        Returns:
            A container with the oMLX block, application settings, LinkedIn
            login block, system prompt editor, save button, and status line
            (ids preserved for compatibility).
        """
        return Container(
            self._title("Settings", id="settings_title"),
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
                Input(placeholder="gemma-4-e4b-bf16", id="model_input"),
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
                ActionButton("Login to LinkedIn", id="linkedin_login_btn"),
                self._status("", id="linkedin_status"),
                id="linkedin_block",
            ),
            Vertical(
                Static("System prompt (shown on the Chat screen):", classes="section_title"),
                TextArea(id="system_prompt", show_line_numbers=False),
                id="prompt_block",
            ),
            ActionButton("Save Config", id="save_config_btn"),
            self._status("", id="settings_status"),
            id="settings_content",
        )

    def on_mount(self) -> None:
        """Populate the form from the current oMLX and user config."""
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
        """Show/hide the LinkedIn login block based on the enabled sources.

        Args:
            event: The input-changed event; only ``sources_input`` is
                handled.
        """
        if event.input.id == "sources_input":
            self._toggle_linkedin_block()

    def _toggle_linkedin_block(self) -> None:
        """Display the LinkedIn login block only when linkedin is a source."""
        sources_value = self.query_one("#sources_input", Input).value.lower()
        show = "linkedin" in sources_value
        self.query_one("#linkedin_block").display = "block" if show else "none"
        if not show:
            self.query_one("#linkedin_status", StatusText).set_message("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the Save Config and LinkedIn login buttons.

        Args:
            event: The button-pressed event; only the two in-screen actions
                are handled, everything else is delegated to the base.
        """
        super().on_button_pressed(event)
        if event.button.id == "save_config_btn":
            self._save_config()
        elif event.button.id == "linkedin_login_btn":
            self._login_linkedin()

    def _login_linkedin(self) -> None:
        """Kick off a one-time LinkedIn browser login in the background."""
        status = self.query_one("#linkedin_status", StatusText)
        status.set_message("Launching browser for LinkedIn login...")
        self.query_one("#linkedin_login_btn", Button).disabled = True
        self._run_worker(self._async_linkedin_login, "linkedin")

    async def _async_linkedin_login(self) -> None:
        """Run the blocking LinkedIn login off the event loop."""
        status = self.query_one("#linkedin_status", StatusText)
        try:
            await asyncio.to_thread(self._linkedin_login_blocking)
            status.set_message("LinkedIn logged in. Session saved for headless reuse.")
        except Exception as error:
            status.set_message(f"LinkedIn login failed: {error}")
        finally:
            self.query_one("#linkedin_login_btn", Button).disabled = False

    def _linkedin_login_blocking(self) -> bool:
        """Blocking Playwright login, run off the event loop.

        Returns:
            True on success (the session storage state is persisted).
        """
        from ...sources.linkedin import LinkedInAdapter

        adapter = LinkedInAdapter()
        adapter.login()
        return True

    def _save_config(self) -> None:
        """Validate the form and write it to the user config TOML."""
        status = self.query_one("#settings_status", StatusText)

        def _clean(value: str) -> str:
            return ",".join(piece.strip() for piece in value.split(",") if piece.strip())

        sources_raw = _clean(self.query_one("#sources_input", Input).value)
        sources = []
        for source_name in sources_raw.split(","):
            source_name = source_name.strip().lower()
            if source_name in ALLOWED_SOURCES and source_name not in sources:
                sources.append(source_name)

        model = self.query_one("#model_input", Input).value.strip()
        mode = str(self.query_one("#score_mode_select", Select).value)
        system_prompt = self.query_one("#system_prompt", TextArea).text

        config: UserConfig = load_user_config()
        config.sources.enabled = sources or config.sources.enabled
        if model:
            config.model.chat = model
        config.scoring.mode = mode
        config.prompts.system = system_prompt

        try:
            path = save_user_config(config)
            status.set_message(f"Saved config to {path}")
        except Exception as error:
            status.set_message(f"Failed to save config: {error}")