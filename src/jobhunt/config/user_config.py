"""
User configuration for JobHunt.

Reads a TOML file (default `~/.config/jobhunt/config.toml`, overridable via
JOBHUNT_CONFIG) into a validated :class:`UserConfig`. If the file does not
exist a builtin default is used, so the app starts without any user setup.
"""
import logging
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..llm import DEFAULT_CHAT_MODEL, DEFAULT_EMBEDDING_MODEL

logger = logging.getLogger("jobhunt.config")

ALLOWED_SOURCES = ("greenhouse", "lever", "ashby", "linkedin", "indeed")
ALLOWED_SCORING_MODES = ("hybrid", "embedding", "llm")

# Sources that support native keyword search (free-text queries).
# Greenhouse/Lever/Ashby only expose per-company boards; site-wide
# keyword search is not available on those platforms.
KEYWORD_SOURCES = ("indeed", "linkedin")


def keyword_search_available() -> bool:
    """Return True if at least one keyword-search source is enabled."""
    return any(s.lower() in KEYWORD_SOURCES for s in get_user_config().sources.enabled)


class SourceConfig(BaseModel):
    """Which sources are enabled and which company slugs to track per source."""
    enabled: List[str] = Field(default_factory=lambda: ["greenhouse", "lever", "ashby"])
    companies: Dict[str, List[str]] = Field(default_factory=dict)


class PromptConfig(BaseModel):
    """System/instructions prompts passed to the model."""
    system: str = "You are a helpful job-hunting assistant."
    score: str = (
        "Score how well this candidate profile fits this job posting. "
        'Respond with JSON only, using keys: "score" (0.0 to 1.0), '
        '"explanation" (short reason), "matched_skills" (list), '
        '"missing_skills" (list), "suggested_bullets" (list).'
    )


class ModelConfig(BaseModel):
    """Model names; env vars JOBHUNT_{CHAT,EMBEDDING,CONFIRM}_MODEL override."""
    chat: str = DEFAULT_CHAT_MODEL
    embedding: str = DEFAULT_EMBEDDING_MODEL
    confirm: str = DEFAULT_CHAT_MODEL


class ScoringConfig(BaseModel):
    """Fit-scoring mode; env JOBHUNT_SCORING_MODE overrides."""
    mode: str = "hybrid"


class UserConfig(BaseModel):
    """Validated user configuration.

    All fields have defaults so a missing/invalid file degrades gracefully.
    """
    sources: SourceConfig = Field(default_factory=SourceConfig)
    prompts: PromptConfig = Field(default_factory=PromptConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def source_enabled(self, source: str) -> bool:
        return source.lower() in [s.lower() for s in self.sources.enabled]

    def companies_for(self, source: str) -> List[str]:
        return list(self.sources.companies.get(source.lower(), []))


def config_path() -> Path:
    """Resolve the config file path (JOBHUNT_CONFIG -> XDG default)."""
    env = os.environ.get("JOBHUNT_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config" / "jobhunt" / "config.toml"


def get_default_user_config() -> UserConfig:
    """Return the builtin default configuration."""
    return UserConfig()


def _validate(config: UserConfig) -> UserConfig:
    """Normalize/sanitize a parsed config (drop unknown sources/modes)."""
    config.sources.enabled = [
        s for s in config.sources.enabled if s.lower() in ALLOWED_SOURCES
    ]
    if config.sources.companies:
        config.sources.companies = {
            k: v
            for k, v in config.sources.companies.items()
            if k.lower() in ALLOWED_SOURCES
        }
    if config.scoring.mode not in ALLOWED_SCORING_MODES:
        config.scoring.mode = "hybrid"
    return config


def load_user_config(path: Optional[str] = None) -> UserConfig:
    """Load and validate the user config; return defaults if unreadable/missing."""
    cfg_path = Path(path).expanduser() if path else config_path()
    if not cfg_path.exists():
        return get_default_user_config()
    try:
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
        return _validate(UserConfig.model_validate(data))
    except Exception:
        logger.warning("Could not load user config from %s; using defaults", cfg_path, exc_info=True)
        return get_default_user_config()


@lru_cache(maxsize=1)
def get_user_config() -> UserConfig:
    """Cached accessor for the user config."""
    return load_user_config()


def save_user_config(config: UserConfig, path: Optional[str] = None) -> Path:
    """Serialize the config to TOML (destructive on the target file). Return path."""
    out = Path(path).expanduser() if path else config_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write(_to_toml(config))
    get_user_config.cache_clear()
    return out


def _to_toml(config: UserConfig) -> str:
    """Render a UserConfig as a well-formed TOML document."""
    lines = []

    def _list(items: List[str]) -> str:
        if not items:
            return "[]"
        return "[" + ", ".join(f'"{i}"' for i in items) + "]"

    lines.append("[sources]")
    lines.append(f"enabled = {_list(config.sources.enabled)}")

    companies = config.sources.companies
    if companies:
        lines.append("[sources.companies]")
        for source, slugs in companies.items():
            lines.append(f'{source} = {_list(slugs)}')

    lines.append("")
    lines.append("[prompts]")
    lines.append(f'system = {_quote(config.prompts.system)}')
    lines.append(f'score = {_quote(config.prompts.score)}')

    lines.append("")
    lines.append("[model]")
    lines.append(f'chat = {_quote(config.model.chat)}')
    lines.append(f'embedding = {_quote(config.model.embedding)}')
    lines.append(f'confirm = {_quote(config.model.confirm)}')

    lines.append("")
    lines.append("[scoring]")
    lines.append(f'mode = {_quote(config.scoring.mode)}')

    return "\n".join(lines) + "\n"


def _quote(value: str) -> str:
    """Quote a string for TOML, escaping internal quotes/backslashes minimally."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'