# JOBHUNT — Local AI Job-Search Harness (TUI)

## 1. Goal
A focused TUI app, tuned for job hunting, running entirely against your local **oMLX** server.
It scrapes job boards, scores job fit against your resume using a local embedding model, and
generates ATS-friendly tailored resumes (DOCX->PDF) and cover letters. Autonomy: **prep only,
I submit** — the app prepares materials, the user applies manually.

## 2. Environment (verified)
- macOS 26.5.2 · Apple Silicon (arm64) · 64GB RAM · Homebrew (`/opt/homebrew/bin/brew`) present.
- oMLX server running on `127.0.0.1:8000`, API key `4526` (read from `~/.omlx/settings.json` at
  runtime, overridable via `OMLX_API_KEY`). Never hardcoded in the repo.
- Models installed (auto-detected by oMLX):
  - `Qwen3-30B-A3B-6bit` — primary agent brain (max_model_len 40960)
  - `Qwen3-Coder-30B-A3B-Instruct-MLX-8bit` — fallback (262144)
  - `Qwen2.5-Coder-7B-Instruct-MLX` — backup (32768)
  - `bge-m3-mlx-fp16` — embeddings, 8194 ctx, served via `/v1/embeddings` (confirmed)
- oMLX endpoints: `/v1/models`, `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`,
  `/v1/rerank`, `/v1/messages` (Anthropic). Tool-call formats: JSON/Qwen/Gemma/GLM/MiniMax/Mistral/
  Kimi K2 (auto-detected). Supports embeddings (BERT/BGE-M3/ModernBERT) and rerankers
  (ModernBERT/XLM-RoBERTa).
- Gaps resolved in Phase 0 (2026-08-16, see `plan/reviewPhase0.md`): uv + Python 3.12 installed and
  locked (`uv.lock`); oMLX smoke test green (tool-call round-trip, structured JSON, embeddings).
  LibreOffice/soffice NOT installed — needed only in Phase 4 (DOCX->PDF); install with
  `brew install libreoffice` at the start of Phase 4.
- Phase 1 complete (2026-08-16, see `plan/reviewPhase1.md`): 7 screens wired with persistent nav,
  Chat end-to-end with the agent, pytest smoke tests (6). Textual 8.2.8 API notes that
  differ from earlier assumptions: `register_screen` does not exist (use `install_screen(screen,
  name)`); `switch_screen` inside `on_mount` raises `IndexError` (use `push_screen` there;
  `switch_screen(name)` is safe post-mount). Remaining Phase 1 gap: agent loop is not yet streaming.

## 3. Architecture
**Stack:** Python 3.12 (uv) · Textual TUI · `openai` SDK -> oMLX `/v1` · `python-docx` +
LibreOffice headless · `pydantic` + stdlib `sqlite3` · `httpx` (source APIs) · `playwright` (Phase 5).

```
jobhunt/
  app/        # Textual screens: Dashboard, Search, Jobs, Fit, Resume, Chat, Settings
  agent/      # tool registry + agent loop (streaming, JSON-schema structured output)
  sources/    # SourceAdapter interface + Greenhouse/Lever/Ashby/Playwright adapters
  models/     # pydantic: Job, Application, FitScore, Profile, Resume
  db/         # sqlite repository (incl. embeddings vector cache table)
  resume/     # profile extraction, DOCX renderer, PDF conversion, cover letters
  config/     # oMLX settings reader + user config.toml
```

**Core decisions**
- Agent loop: ReAct-style tool calling via OpenAI SDK; Qwen3 auto-format. Tool registry /
  skills: `search_jobs`, `get_job_detail`, `score_fit`, `tailor_resume`, `generate_cover_letter`,
  `update_status`, `list_jobs`. Same tools drive screens and chat.
- All sources normalize to one `Job` model behind a `SourceAdapter` interface.
- SQLite persistence: jobs, applications/status tracker, notes, artifacts, embeddings cache,
  search history.

## 4. Milestones

**Phase 0 — Scaffold (1/2 day)**
- `brew install uv libreoffice`
- uv project (Python 3.12), pyproject with deps: textual, openai, httpx, python-docx, pydantic, rich
- config reader: base_url + API key from `~/.omlx/settings.json`, overridable via env
- `smoke.py`: verify tool-call round-trip + structured JSON + embeddings round-trip against oMLX
- .gitignore, README

**Phase 1 — Agent + TUI skeleton (1 day)**
- Tool registry, streaming agent loop
- Textual shell with 7 screens (Dashboard, Search, Jobs, Fit, Resume, Chat, Settings)
- Chat screen working end-to-end with the agent

  Status: DONE 2026-08-16 (see `plan/reviewPhase1.md`).
  - 7 screens wired with persistent nav. **Deviation:** the nav bar was moved from the App
    `compose` into `BaseScreen`, so it stays visible on every screen (Textual screens fully
    replace the App body, so the old app-level nav vanished after the first switch).
  - Initial screen mounted via `push_screen("dashboard")` in `on_mount`; nav buttons call
    `switch_screen(name)` (post-mount). Textual 8.2.8: `register_screen` does not exist —
    use `install_screen(screen, name)`; `switch_screen` inside `on_mount` raises `IndexError`
    (default screen has no result callback), so the initial screen must be `push_screen`.
  - Chat screen works end-to-end: lazy `JobHuntAgent`, async worker (`asyncio.to_thread`) so the
    blocking oMLX call doesn't freeze the TUI, transcript log with error surfacing, busy guard.
  - **Deviation:** pytest + `tests/test_app.py` (mount, nav, tool registry, lazy config, chat
    round-trip/error) were added in Phase 1, ahead of the Phase 6 "unit tests" milestone.
  - **Deviation:** config is lazy (`get_omlx_settings()`, cached) — resolves the deferred "config
    loaded at import time" item from Phase 0; `import jobhunt.agent` no longer requires an oMLX key.
  - **Open item:** the "streaming agent loop" deliverable is NOT done — `agent.chat()` and
    `chat_with_agent()` are non-streaming (Chat works, but replies render only on completion).
    Fold streaming into Phase 6 (error/retry + timeouts) or a Phase 1 follow-up.

**Phase 2 — Data + first source (1-1.5 days)**
- SQLite schema + repository layer
- Greenhouse (`https://boards-api.greenhouse.io/v1/boards/{org}/jobs`), Lever
  (`https://api.lever.co/v0/postings/{org}?mode=json`), Ashby (POST
  `https://api.ashbyhq.com/posting-api/job-board/{org}`) — all open JSON APIs, no anti-bot
- Search + Jobs/Tracker screens; target-company config (org slugs)
- Dedupe jobs on ingest

**Phase 3 — Fit scoring with embeddings (1 day)**
- Embedding client -> `/v1/embeddings`, model `bge-m3-mlx-fp16`, 1024-dim normalized, batched
- Vector cache: SQLite `embeddings` table keyed by `(kind, entity_id)`; numpy cosine similarity
  (no external vector DB)
- Hybrid rank pipeline:
  1. Embedding stage (all jobs): cosine(JD vector, resume profile vector) -> semantic score.
     BGE prefix rule: short/resume text gets instruction prefix
     ("Represent this sentence for searching relevant passages: ..."), JDs embedded as plain docs.
  2. LLM confirm stage (top ~15-20): Qwen3-30B JSON-schema scoring -> breakdown, matched/missing
     skills, reasoning, suggested resume bullets
  - Config `scoring.mode = hybrid | embedding | llm` (default hybrid)
- Embeddings also power dedupe (cosine > ~0.95 = skip) and "similar jobs"
- Fit screen: ranked, scored, explainable

**Phase 4 — Resume + cover letters (1.5-2 days)**
- Parse base resume DOCX -> structured Profile (sections, bullets, skills); cache as JSON
- LLM tailors bullets to JD (ATS keyword emphasis, quantified)
- Rebuild DOCX from template; `soffice --headless --convert-to pdf`
- Cover letter generation (from Profile + JD)
- Artifacts -> `outputs/{company}/{job}/`; Resume workflow screen with preview, regenerate,
  tweakable instructions

**Phase 5 — LinkedIn + Indeed (2 days, opt-in)**
- Playwright (chromium) + persisted session cookie jar (headful first login), polite delays,
  ToS-aware, feature-flagged

**Phase 6 — Polish (1 day)**
- Error/retry handling (oMLX down), timeouts, logging
- Unit tests (fake LLM + source fixtures), integration test vs real Greenhouse
- Config UI (sources, companies, prompts, model)
- README + uv scripts

**Stretch:** reranker (`bge-reranker-v2-m3`) via `/v1/rerank` to refine final top-k ordering.

## 5. Risks
- Qwen3 tool-call reliability -> verified in Phase 0 smoke test; fallback `Qwen3-Coder-30B`/7B.
- oMLX auth key -> read from `~/.omlx/settings.json`, never hardcoded.
- LinkedIn/Indeed anti-bot + ToS -> kept opt-in, feature-flagged.
- Large JDs -> 8K embedding ctx + 40K Qwen ctx sufficient; context capped in prompts.

## 6. Open confirmations
1. Project dir `~/Documents/Study/projects/python/jobhunt` — confirmed.
2. Sources: Greenhouse/Lever/Ashby first, LinkedIn/Indeed later — confirmed.
3. Resume DOCX path needed in Phase 4 (user to provide).
