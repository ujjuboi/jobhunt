# JobHunt — Local AI Job Search Harness

A focused TUI app tuned for job hunting, running entirely against your local oMLX server.

## Features

- Scrapes job boards and scores job fit against your resume using local embeddings
- Generates ATS-friendly tailored resumes and cover letters
- Runs entirely locally with your oMLX server
- **Supports multiple job board sources** including LinkedIn and Indeed (web scraping)

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

4. Run the smoke test to verify the oMLX connection
   (tool-call round-trip, structured JSON, embeddings):

   ```bash
   uv run python smoke.py
   ```

5. Launch the TUI:

   ```bash
   uv run jobhunt
   ```

See `plan/PLAN.md` for the full architecture and milestones.
