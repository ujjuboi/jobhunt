"""
User config tests: defaults, TOML load/save round-trip, validation, and the
scoring-mode fallback chain (env -> config -> hybrid).
"""
import os

import pytest

from jobhunt.config import get_scoring_mode
from jobhunt.config.user_config import (
    UserConfig,
    get_default_user_config,
    load_user_config,
    save_user_config,
    _to_toml,
)


@pytest.fixture(autouse=True)
def _clear_config_cache():
    from jobhunt.config.user_config import get_user_config
    get_user_config.cache_clear()
    yield
    get_user_config.cache_clear()


def test_defaults_are_sane():
    config = get_default_user_config()
    assert "greenhouse" in config.sources.enabled
    assert config.sources.enabled == ["greenhouse", "lever", "ashby"]
    assert config.scoring.mode == "hybrid"
    assert config.model.chat


def test_missing_file_returns_defaults(tmp_path):
    config = load_user_config(str(tmp_path / "nope.toml"))
    assert config == get_default_user_config()


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    config = get_default_user_config()
    config.sources.enabled = ["greenhouse"]
    config.sources.companies = {"greenhouse": ["stripe", "ramp"]}
    config.model.chat = "custom-model"
    config.scoring.mode = "llm"
    config.prompts.system = "You are a resume expert."
    saved = save_user_config(config, str(path))
    assert saved == path
    assert path.exists()

    reloaded = load_user_config(str(path))
    assert reloaded.sources.enabled == ["greenhouse"]
    assert reloaded.sources.companies == {"greenhouse": ["stripe", "ramp"]}
    assert reloaded.model.chat == "custom-model"
    assert reloaded.scoring.mode == "llm"
    assert reloaded.prompts.system == "You are a resume expert."


def test_invalid_sources_and_mode_are_pruned(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        _to_toml(get_default_user_config())
        + "[sources]\nenabled = [\"greenhouse\", \"bogus\"]\n\n[scoring]\nmode = \"nope\"\n"
    )
    config = load_user_config(str(path))
    assert "bogus" not in config.sources.enabled
    assert config.scoring.mode == "hybrid"


def test_source_helpers():
    config = get_default_user_config()
    assert config.source_enabled("Greenhouse")
    config.sources.enabled = ["ashby"]
    assert not config.source_enabled("greenhouse")
    config.sources.companies = {"ashby": ["acme"]}
    assert config.companies_for("ASHBY") == ["acme"]


def test_scoring_mode_from_config(tmp_path, monkeypatch):
    monkeypatch.delenv("JOBHUNT_SCORING_MODE", raising=False)
    path = tmp_path / "config.toml"
    config = get_default_user_config()
    config.scoring.mode = "embedding"
    save_user_config(config, str(path))
    monkeypatch.setenv("JOBHUNT_CONFIG", str(path))

    from jobhunt.config.user_config import get_user_config
    get_user_config.cache_clear()
    assert get_scoring_mode() == "embedding"


def test_scoring_mode_env_overrides_config(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_SCORING_MODE", "llm")
    path = tmp_path / "config.toml"
    save_user_config(get_default_user_config(), str(path))
    monkeypatch.setenv("JOBHUNT_CONFIG", str(path))

    from jobhunt.config.user_config import get_user_config
    get_user_config.cache_clear()
    assert get_scoring_mode() == "llm"


def test_invalid_scoring_env_still_raises(monkeypatch):
    monkeypatch.setenv("JOBHUNT_SCORING_MODE", "bogus")
    monkeypatch.delenv("JOBHUNT_CONFIG", raising=False)
    with pytest.raises(ValueError):
        get_scoring_mode()