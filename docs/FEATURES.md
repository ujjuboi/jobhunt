# JobHunt — Feature Overview

**JobHunt** is a local AI job-search harness built around a Textual TUI. It runs entirely
against a local [oMLX](https://github.com) server, scraping job boards, scoring job fit
against your resume using a local embedding model, and generating ATS-friendly tailored
resumes (DOCX -> PDF) and cover letters.

## Source Layout

```
jobhunt/
  app/        # Textual screens: Dashboard, Search, Jobs, Fit, Resume, Chat, Settings
  agent/      # Tool registry + agent loop (streaming, structured output)
  sources/    # SourceAdapter interface + Greenhouse/Lever/Ashby/Playwright adapters
  models/     # Pydantic models: Job, Application, FitScore, Profile, Resume
  db/         # SQLite repository with embedding vector cache
  resume/     # Profile parsing, DOCX rendering, PDF conversion, cover letters
  scoring/    # Embedding client, vector cache, hybrid/embedding/llm scoring
  config/     # oMLX settings reader + user config.toml
```

## Feature List by Phase

### Phase 0 — Scaffold

- `uv` project with Python 3.12, dependencies locked in `uv.lock`
- oMLX settings reader: `~/.omlx/settings.json`, overridable via `OMLX_API_KEY` and `OMLX_BASE_URL`
- Smoke test: verify tool-call round-trip, structured JSON, and embeddings round-trip against oMLX
- `.gitignore`, initial README

### Phase 1 — Agent + TUI Skeleton

- Tool registry with 7 tools: `search_jobs`, `get_job_detail`, `score_fit`, `tailor_resume`,
  `generate_cover_letter`, `update_status`, `list_jobs`
- 7 Textual screens: Dashboard, Search, Jobs, Fit, Resume, Chat, Settings
- Persistent navigation bar on every screen (moved from App.compose into BaseScreen)
- Chat screen working end-to-end with the agent (lazy construction, background worker)

### Phase 2 — Data + First Source

- SQLite persistence: 5 tables (jobs, applications, embeddings, profiles, resumes)
- Greenhouse, Lever, Ashby API adapters — all normalize to a single `Job` model
- Search + Jobs/Tracker screens
- Target-company config (org slugs per source)
- Deduplicate jobs on ingest

### Phase 3 — Fit Scoring with Embeddings

- Embedding client for `bge-m3-mlx-fp16` via `/v1/embeddings` (1024-dim, normalized)
- Vector cache: SQLite `embeddings` table keyed by `(kind, entity_id)`
- Three scoring modes: `hybrid` (default), `embedding`, `llm`
- Hybrid pipeline: embedding cosine similarity over all jobs, then LLM confirm pass over top N
- Embedding-based deduplication (cosine > 0.95 = skip)
- "Similar jobs" nearest-neighbour lookup

### Phase 4 — Resume + Cover Letters

- Parse base resume DOCX into structured `Profile` (name, email, sections, skills, etc.)
- JSON cache for parsed profiles at `cache/resume/{filename}.json`
- LLM tailoring with heuristic fallback (keyword matching)
- Rebuild tailored DOCX from template
- PDF conversion via LibreOffice headless (`soffice --headless --convert-to pdf`)
- Cover letter generation (LLM-first with template fallback)
- Artifacts output to `outputs/{company}/{job}/` (DOCX, PDF, cover letter)

### Phase 5 — LinkedIn + Indeed

- Playwright (chromium) scrapers for Indeed and LinkedIn
- LinkedIn: headful first login, session persisted at `cache/linkedin_session.json`, headless reuse
- Polite delays, opt-in, feature-flagged, ToS-aware

### Phase 6 — Polish

- Retry policy for transient errors (429, 5xx, connection/timeout) with exponential backoff
- 60-second HTTP client timeouts
- Structured logging: stderr + file at `~/.config/jobhunt/logs/jobhunt.log`
- TOML user config at `~/.config/jobhunt/config.toml` with validation
- Settings screen as Config UI: sources, companies, model, scoring mode, system prompt
- Streaming chat: `chat_stream()` yields text deltas mid-reply
- Unit test suite: ~91 passing tests (opt-in integration tests)
- uv scripts: `jobhunt-smoke`, `jobhunt-test`, `jobhunt-check`

### Phase 7 — Close UX Gaps

- Profile auto-save: selecting a DOCX in the Resume screen syncs the profile to the DB for fit scoring
- Job selection: clicking a row in the Jobs screen sets `app.selected_job_id` for the Resume screen
- "Save to Outputs": generates and saves tailored resume/cover letter to `outputs/` directory
- Dashboard live counts: total jobs, total applications, recent activity list
- Multi-source search: iterates all enabled sources from config, dedupes results, tags by source

## Dev Commands

All commands run via `uv run`:

| Command | Description |
|---|---|
| `uv run jobhunt` | Launch the TUI |
| `uv run jobhunt-smoke` | Run oMLX smoke test (models, embeddings, tool-call round-trip) |
| `uv run jobhunt-test` | Run pytest suite (`pytest -q`) |
| `uv run jobhunt-check` | Run smoke test then test suite |
| `uv run pytest` | Plain pytest |
| `JOBHUNT_INTEGRATION=1 uv run pytest -m integration` | Opt-in live Greenhouse integration test |

Pytest configuration: `testpaths = ["tests"]`, `addopts = "-ra"`, `integration` marker for opt-in integration tests.

No linter/formatter is configured; verify with `python -m compileall` and the test suite.

## Stretch

- Reranker (`bge-reranker-v2-m3`) via `/v1/rerank` to refine the final top-k ordering of
  the fit-scoring pipeline in `src/jobhunt/scoring/__init__.py`.
