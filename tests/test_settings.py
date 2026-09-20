"""
Settings screen / Config UI tests: mount, populate from config, save.
oMLX settings and config I/O are stubbed so these run offline.
"""
import asyncio
from pathlib import Path
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


def test_settings_saves_user_config(monkeypatch):
    captured = _stub_deps(monkeypatch)

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#settings_btn")
            await asyncio.sleep(0.1)
            app.screen.query_one("#sources_input").value = "greenhouse, linkedin"
            await pilot.click("#save_config_btn")
            await asyncio.sleep(0.1)

    asyncio.run(run())

    cfg = captured["config"]
    assert cfg.sources.enabled == ["greenhouse", "linkedin"]


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
                assert screen.query_one("#linkedin_block").display is False
                # Typing "linkedin" into the sources input reveals it.
                source_input = screen.query_one("#sources_input")
                source_input.value = "greenhouse, linkedin"
                screen.on_input_changed(type("Ev", (), {"input": source_input})())
                assert screen.query_one("#linkedin_block").display is True
                # Removing it hides the block again.
                source_input.value = "greenhouse"
                screen.on_input_changed(type("Ev", (), {"input": source_input})())
                assert screen.query_one("#linkedin_block").display is False
        asyncio.run(_run())
        return app

    run()


def test_linkedin_login_button_flows(monkeypatch):
    _stub_deps(monkeypatch)
    calls = {}

    class FakeLinkedInAdapter:
        def __init__(self, session_file=None):
            self.session_file = session_file

        def login(self):
            calls["logged_in"] = True
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
            await asyncio.sleep(0.1)
            await pilot.click("#linkedin_login_btn")
            await asyncio.sleep(0.5)
            assert "LinkedIn logged in" in screen.query_one("#linkedin_status").content
            assert screen.query_one("#linkedin_login_btn").disabled is False

    asyncio.run(run())

    assert calls["logged_in"] is True


def test_settings_save_writes_user_config(monkeypatch):
    captured = _stub_deps(monkeypatch)

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#settings_btn")
            await asyncio.sleep(0.1)
            app.screen.query_one("#sources_input").value = "greenhouse, ashby"
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
    assert cfg.model.chat == "ACustomModel"
    assert cfg.scoring.mode == "llm"
    assert cfg.prompts.system == "Be concise."


def test_linkedin_status_shows_not_signed_in(monkeypatch):
    _stub_deps(monkeypatch)
    monkeypatch.setattr(
        "jobhunt.sources.linkedin.LinkedInAdapter",
        lambda: SimpleNamespace(session_file=None),
    )

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#settings_btn")
            await asyncio.sleep(0.1)
            screen = app.screen
            source_input = screen.query_one("#sources_input")
            source_input.value = "greenhouse, linkedin"
            screen.on_input_changed(type("Ev", (), {"input": source_input})())
            status = screen.query_one("#linkedin_status")
            assert "Not signed in" in str(status.content)
            assert status.has_class("signed_out")

    asyncio.run(run())


def test_linkedin_status_shows_signed_in_email(monkeypatch, tmp_path):
    _stub_deps(monkeypatch)
    session = str(tmp_path / "linkedin_session.json")
    Path(session).write_text("{}")

    class FakeLinkedInAdapter:
        def __init__(self, session_file=session):
            self.session_file = session_file

        def session_email(self):
            return "me@example.com"

    monkeypatch.setattr("jobhunt.sources.linkedin.LinkedInAdapter", FakeLinkedInAdapter)

    async def run():
        app = JobHuntApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await asyncio.sleep(0.1)
            await pilot.click("#settings_btn")
            await asyncio.sleep(0.1)
            screen = app.screen
            screen.query_one("#sources_input").value = "greenhouse, linkedin"
            screen._refresh_linkedin_status()
            for _ in range(100):
                await asyncio.sleep(0.05)
                if "me@example.com" in str(screen.query_one("#linkedin_status").content):
                    break
            status = screen.query_one("#linkedin_status")
            assert "Signed in as me@example.com" in str(status.content)
            assert status.has_class("signed_in")

    asyncio.run(run())