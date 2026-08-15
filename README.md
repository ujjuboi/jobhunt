# JobHunt — Local AI Job Search Harness

A focused TUI app tuned for job hunting, running entirely against your local oMLX server.

## Features

- Scrapes job boards and scores job fit against your resume using local embeddings
- Generates ATS-friendly tailored resumes and cover letters
- Runs entirely locally with your oMLX server

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

## Quick Start

1. Install dependencies:

   ```bash
   brew install uv libreoffice
   ```

2. Sync the project (Python 3.12, per `.python-version`):

   ```bash
   uv sync
   ```

3. Run the smoke test to verify the oMLX connection
   (tool-call round-trip, structured JSON, embeddings):

   ```bash
   uv run python smoke.py
   ```

4. Launch the TUI:

   ```bash
   uv run jobhunt
   ```

See `plan/PLAN.md` for the full architecture and milestones.
