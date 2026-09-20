# JobHunt — Local AI Job Search Harness

A focused TUI app tuned for job hunting, running entirely against your local oMLX server.

## Features

- Scrapes job boards and scores job fit against your resume using local embeddings
- Generates ATS-friendly tailored resumes and cover letters
- Runs entirely locally with your oMLX server
- Supports multiple job board sources including LinkedIn and Indeed (web scraping)
- Streaming agent chat with retry/timeout handling when oMLX is briefly unavailable
- Config UI for sources, target companies, prompts, model, and scoring mode

## Requirements

- macOS with Apple Silicon
- Homebrew
- oMLX server running on `127.0.0.1:8000` (API key read from `~/.omlx/settings.json`,
  overridable via `OMLX_API_KEY`)
- Models installed on oMLX:
  - `Qwen3-30B-A3B-6bit` (primary)
  - `Qwen3-Coder-30B-A3B-Instruct-MLX-8bit` (fallback)
  - `Qwen2.5-Coder-7B-Instruct-MLX` (backup)
  - `bge-m3-mlx-fp16` (embeddings)

## Supported Job Board Sources

- **API-based sources**: Greenhouse, Lever, Ashby (require API keys)
- **Web scraping sources**: LinkedIn, Indeed (scraping violates ToS, for educational use only)

> ⚠️ **Disclaimer**: LinkedIn and Indeed scraping implementations use web scraping which violates their Terms of Service. These implementations are provided for educational purposes only and should be used with caution.

## Quick Start

1. Install dependencies:

   ```bash
   brew install uv libreoffice
   ```

2. Sync the project (Python 3.12, per `.python-version`):

   ```bash
   uv sync
   ```

3. Install the Playwright browser used by the LinkedIn/Indeed scrapers (opt-in
   sources — run only if you plan to use them):

   ```bash
   uv run playwright install chromium
   ```

4. Verify the oMLX connection (tool-call round-trip, structured JSON, embeddings):

   ```bash
   uv run jobhunt-smoke
   ```

5. Launch the TUI:

   ```bash
   uv run jobhunt
   ```

## Configuration

The app reads a user config from `~/.config/jobhunt/config.toml`
(`JOBHUNT_CONFIG` overrides the path). If absent, sensible defaults are used and
a file is created when you **Save Config** from the Settings screen.

The Settings screen edits the active sources, chat model,
scoring mode, and the system prompt. You can also edit the TOML by hand:

```toml
[sources]
enabled = ["greenhouse", "lever", "ashby"]

[prompts]
system = "You are a helpful job-hunting assistant."
score = 'Score how well this candidate profile fits this job posting. Respond with JSON only, using keys: "score" (0.0 to 1.0), "explanation" (short reason), "matched_skills" (list), "missing_skills" (list), "suggested_bullets" (list).'

[model]
chat = "Qwen3-30B-A3B-6bit"
embedding = "bge-m3-mlx-fp16"
confirm = "Qwen3-30B-A3B-6bit"

[scoring]
mode = "hybrid"
```

Environment overrides (highest precedence):
- `OMLX_API_KEY`, `OMLX_BASE_URL` — oMLX credentials/endpoint
- `JOBHUNT_CHAT_MODEL`, `JOBHUNT_EMBEDDING_MODEL`, `JOBHUNT_CONFIRM_MODEL`
- `JOBHUNT_SCORING_MODE` (hybrid | embedding | llm)
- `JOBHUNT_LOG_LEVEL`

Logs go to stderr and `~/.config/jobhunt/logs/jobhunt.log`.

## Development

```bash
# Run the full test suite
uv run jobhunt-test

# Smoke test the oMLX connection, then run the suite
uv run jobhunt-check

# Also available as plain uv commands
uv run pytest tests/
uv run python smoke.py
```

### Integration tests

API-based source tests use mocked payloads so the default suite runs offline.
A live integration test against the real Greenhouse board API is opt-in:

```bash
# Default org is a large public Greenhouse customer; override with GREENHOUSE_ORG
JOBHUNT_INTEGRATION=1 uv run pytest -m integration
```

## Project Layout

See [`docs/FEATURES.md`](docs/FEATURES.md) for the full feature list, source
layout, dev commands, and phase-by-phase history.