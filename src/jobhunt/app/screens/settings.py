"""
Settings screen for JobHunt application
"""
from textual.widgets import Static, Button
from textual.containers import Container

from .base import BaseScreen


class SettingsScreen(BaseScreen):
    """Settings screen for configuration"""

    def __init__(self):
        super().__init__(name="settings")

    def _get_content(self):
        return Container(
            Static("Settings", id="settings_title"),
            Static("oMLX Configuration:", id="omlx_config_title"),
            Static(id="base_url"),
            Static("API Key: [hidden]", id="api_key"),
            Static(""),
            Static("Application Settings:", id="app_settings_title"),
            Static("Current Company: Not set", id="current_company"),
            Button("Configure Company", id="configure_company_btn"),
            id="settings_content"
        )

    def on_mount(self):
        from ...config import get_omlx_settings

        settings = get_omlx_settings()
        self.query_one("#base_url", Static).update(f"Base URL: {settings.base_url}")
