"""
Settings screen / Config UI tests: mount, populate from config, save.
oMLX settings and config I/O are stubbed so these run offline.
"""
import asyncio
from types import SimpleNamespace

from jobhunt.app import JobHuntApp
from jobhunt.app.screens import settings as settings_module
from jobhunt.config.user_config import UserConfig, get_default_user_config


def _stub_deps(monkeypatch, saved=None):
    captured = {}

    def fake_load(path=None):
        return get_default_user_config()

    def fake_save(config, path=None):
        captured["config"] = config
        return path or "/tmp/config.toml"

    monkeypatch.setattr(settings_module, "get_omlx_settings",
                        lambda: SimpleNamespace(base_url="http://omlx/v1", api_key="k"))
    monkeypatch.setattr(settings_module, "load_user_config", fake_load)
    monkeypatch.setattr(settings_module, "save_user_config", fake_save)
    return captured


def test_settings_screen_mounts_and_populates(monkeypatch):
    _stub_deps(monkeypatch)

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#settings_btn")
            await asyncio.sleep(0.1)
            from jobhunt.app.screens.settings import SettingsScreen
            assert isinstance(app.screen, SettingsScreen)
            assert app.screen.query_one("#base_url").content == "Base URL: http://omlx/v1"
            # Defaults populated
            assert "greenhouse" in app.screen.query_one("#sources_input").value

    asyncio.run(run())


def test_settings_save_writes_user_config(monkeypatch):
    captured = _stub_deps(monkeypatch)

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#settings_btn")
            await asyncio.sleep(0.1)
            app.screen.query_one("#sources_input").value = "greenhouse, ashby"
            app.screen.query_one("#companies_input").value = "  stripe , ramp "
            app.screen.query_one("#model_input").value = "ACustomModel"
            app.screen.query_one("#score_mode_select").value = "llm"
            app.screen.query_one("#system_prompt").text = "Be concise."
            await pilot.click("#save_config_btn")
            await asyncio.sleep(0.1)
            assert "Saved config" in app.screen.query_one("#settings_status").content

    asyncio.run(run())

    cfg = captured["config"]
    assert isinstance(cfg, UserConfig)
    assert cfg.sources.enabled == ["greenhouse", "ashby"]
    assert cfg.sources.companies == {"greenhouse": ["stripe", "ramp"]}
    assert cfg.model.chat == "ACustomModel"
    assert cfg.scoring.mode == "llm"
    assert cfg.prompts.system == "Be concise."