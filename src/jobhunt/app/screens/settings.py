"""
Settings screen for JobHunt application
"""
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
    """Settings screen for configuration (sources, companies, model, scoring)."""

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
                Static("Company slugs (comma-separated, per enabled source):"),
                Input(placeholder="stripe, ramp", id="companies_input"),
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

        companies = []
        for source in config.sources.enabled:
            companies.extend(config.companies_for(source))
        self.query_one("#companies_input", Input).value = ", ".join(companies)

        self.query_one("#model_input", Input).value = config.model.chat
        self.query_one("#score_mode_select", Select).value = config.scoring.mode
        self.query_one("#system_prompt", TextArea).text = config.prompts.system

    def on_button_pressed(self, event: Button.Pressed) -> None:
        super().on_button_pressed(event)
        if event.button.id == "save_config_btn":
            self._save_config()

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

        companies_raw = _clean(self.query_one("#companies_input", Input).value)
        companies = [c.strip() for c in companies_raw.split(",") if c.strip()]

        model = self.query_one("#model_input", Input).value.strip()
        mode = str(self.query_one("#score_mode_select", Select).value)
        system_prompt = self.query_one("#system_prompt", TextArea).text

        config = load_user_config()
        config.sources.enabled = sources or config.sources.enabled
        # Handle companies per source instead of just the first source
        if companies and config.sources.enabled:
            companies_by_source = {}
            # Distribute companies across enabled sources in a round-robin fashion
            for i, company in enumerate(companies):
                source = config.sources.enabled[i % len(config.sources.enabled)]
                if source not in companies_by_source:
                    companies_by_source[source] = []
                companies_by_source[source].append(company)
            config.sources.companies = companies_by_source
        elif config.sources.enabled:
            # If no companies were provided but sources are enabled, keep current companies
            pass
        else:
            # Clear companies if no sources are enabled
            config.sources.companies = {}
        if model:
            config.model.chat = model
        config.scoring.mode = mode
        config.prompts.system = system_prompt

        try:
            path = save_user_config(config)
            status.update(f"Saved config to {path}")
        except Exception as e:
            status.update(f"Failed to save config: {e}")