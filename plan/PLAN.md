# JOBHUNT — Local AI Job-Search Harness (TUI)

## 1. Goal

A focused TUI app, tuned for job hunting, running entirely against your local **oMLX** server.
It scrapes job boards, scores job fit against your resume using a local embedding model, and
generates ATS-friendly tailored resumes (DOCX->PDF) and cover letters. Autonomy: **prep only,
I submit** — the app prepares materials, the user applies manually.

## 2. Environment

- macOS with Apple Silicon (arm64), Python 3.12, `uv` for dependency management.
- oMLX server running on `127.0.0.1:8000`, API key read from `~/.omlx/settings.json` at
  runtime, overridable via `OMLX_API_KEY`. Never hardcoded in the repo.
- Models served by oMLX: Qwen3-30B (chat), bge-m3 (embeddings), bge-reranker-v2-m3 (rerank).
- oMLX endpoints: `/v1/models`, `/v1/chat/completions`, `/v1/embeddings`, `/v1/rerank`.

## 3. Architecture

**Stack:** Python 3.12 (uv) · Textual TUI · `openai` SDK -> oMLX `/v1` · `python-docx` +
LibreOffice headless · `pydantic` + stdlib `sqlite3` · `httpx` (source APIs) · `playwright` (LinkedIn/Indeed).

```
jobhunt/
  app/        # Textual screens: Dashboard, Search, Jobs, Fit, Resume, Chat, Settings
  agent/      # tool registry + agent loop (streaming, JSON-schema structured output)
  sources/    # SourceAdapter interface + Greenhouse/Lever/Ashby/Playwright adapters
  models/     # pydantic: Job, Application, FitScore, Profile, Resume
  db/         # sqlite repository (incl. embeddings vector cache table)
  resume/     # profile extraction, DOCX renderer, PDF conversion, cover letters
  config/     # oMLX settings reader + user config.toml
  scoring/    # embedding client, vector cache, hybrid/embedding/llm scoring
```

## 4. All Phases Delivered

- **Phase 0** — Scaffold (uv project, config reader, smoke tests)
- **Phase 1** — Agent + TUI skeleton (7 screens, chat end-to-end)
- **Phase 2** — Data + first source (SQLite schema, Greenhouse/Lever/Ashby adapters)
- **Phase 3** — Fit scoring with embeddings (hybrid pipeline, vector cache)
- **Phase 4** — Resume + cover letters (DOCX parsing, LLM tailoring, PDF output)
- **Phase 5** — LinkedIn + Indeed (Playwright scrapers, session persistence)
- **Phase 6** — Polish (retry, logging, config UI, streaming chat, tests)
- **Phase 7** — Close UX gaps (profile auto-save, job selection, Save to Outputs, Dashboard counts, multi-source search)

## 5. Stretch

- Reranker (`bge-reranker-v2-m3`) via `/v1/rerank` to refine the final top-k ordering
  of the fit-scoring pipeline (`src/jobhunt/scoring/__init__.py`).

## 6. Feature Documentation

Full feature details, screen descriptions, agent/tool system, scoring, resume, sources,
and database/config: see [`docs/`](../docs/).
