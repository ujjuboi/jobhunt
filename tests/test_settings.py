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


def test_settings_saves_linkedin_credentials(monkeypatch):
    captured = _stub_deps(monkeypatch)

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#settings_btn")
            await asyncio.sleep(0.1)
            app.screen.query_one("#sources_input").value = "greenhouse, linkedin"
            app.screen.query_one("#linkedin_email").value = "alice@example.com"
            app.screen.query_one("#linkedin_password").value = "secret123"
            await pilot.click("#save_config_btn")
            await asyncio.sleep(0.1)

    asyncio.run(run())

    cfg = captured["config"]
    assert cfg.linkedin.email == "alice@example.com"
    assert cfg.linkedin.password == "secret123"


def test_linkedin_block_toggles_with_sources(monkeypatch):
    _stub_deps(monkeypatch)

    def run():
        app = JobHuntApp()
        async def _run():
            async with app.run_test(size=(140, 40)) as pilot:
                await asyncio.sleep(0.1)
                await pilot.click("#settings_btn")
                await asyncio.sleep(0.1)
                screen = app.screen
                # Default sources (greenhouse, lever, ashby) keep the block hidden.
                assert screen.query_one("#linkedin_block").display == "none"
                # Typing "linkedin" into the sources input reveals it.
                source_input = screen.query_one("#sources_input")
                source_input.value = "greenhouse, linkedin"
                screen.on_input_changed(type("Ev", (), {"input": source_input})())
                assert screen.query_one("#linkedin_block").display == "block"
                # Removing it hides the block again.
                source_input.value = "greenhouse"
                screen.on_input_changed(type("Ev", (), {"input": source_input})())
                assert screen.query_one("#linkedin_block").display == "none"
        asyncio.run(_run())
        return app

    run()


def test_linkedin_login_button_flows(monkeypatch):
    captured = _stub_deps(monkeypatch)
    calls = {}

    class FakeLinkedInAdapter:
        def __init__(self, email="", password="", session_file=None):
            self.email = email
            self.password = password

        def login(self, email="", password=""):
            calls["email"] = email
            calls["password"] = password
            return True

    monkeypatch.setattr("jobhunt.sources.linkedin.LinkedInAdapter", FakeLinkedInAdapter)

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#settings_btn")
            await asyncio.sleep(0.1)
            screen = app.screen
            screen.query_one("#sources_input").value = "greenhouse, linkedin"
            screen._toggle_linkedin_block()
            screen.query_one("#linkedin_email").value = "alice@example.com"
            screen.query_one("#linkedin_password").value = "secret123"
            await pilot.click("#linkedin_login_btn")
            await asyncio.sleep(0.5)
            assert "LinkedIn logged in" in screen.query_one("#linkedin_status").content
            assert screen.query_one("#linkedin_login_btn").disabled is False

    asyncio.run(run())

    assert calls["email"] == "alice@example.com"
    assert calls["password"] == "secret123"
    assert captured["config"].linkedin.email == "alice@example.com"


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
    # Companies are distributed round-robin across enabled sources
    assert cfg.sources.companies == {"greenhouse": ["stripe"], "ashby": ["ramp"]}
    assert cfg.model.chat == "ACustomModel"
    assert cfg.scoring.mode == "llm"
    assert cfg.prompts.system == "Be concise."