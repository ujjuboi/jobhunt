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
    **RESOLVED in Phase 6** (2026-08-18): `agent.chat_stream()` + streaming ChatScreen.

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
- Base resume DOCX lives in `../Resumes/` (sibling to project root); user selects a DOCX from that directory at startup
- Parse selected base resume DOCX -> structured Profile (sections, bullets, skills); cache as JSON
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

  Status: DONE 2026-08-18 (see `plan/reviewPhase6.md`).
  - New `jobhunt/llm.py`: retry policy (transient 429/5xx/connect/timeout), 60s client
    timeouts, default model resolution (env -> user config -> builtin), `complete()` +
    streaming `stream()` helpers with mid-stream restart.
  - New `config/user_config.py`: TOML user config (`~/.config/jobhunt/config.toml`,
    overridable via `JOBHUNT_CONFIG`) with sources.enabled, sources.companies, prompts
    (system/score), model (chat/embedding/confirm), scoring.mode. `get_scoring_mode()`
    now falls back to config (env still wins).
  - Agent `chat()`/`chat_with_agent()` route through the retrying LLM layer; new
    `chat_stream()` yields deltas. ChatScreen streams replies (falls back to non-streaming
    when the agent lacks `chat_stream`).
  - `EmbeddingClient` gets timeouts + transient retry; error `print()`s across agent/db/
    sources/scoring/resume replaced with module loggers; app initializes logging
    (stderr + `~/.config/jobhunt/logs/jobhunt.log`, `JOBHUNT_LOG_LEVEL`).
  - Settings screen is now a Config UI: sources, companies, model, scoring mode, system
    prompt, Save -> writes TOML.
  - Tests: `test_llm.py` (retry policy, streaming restart), `test_user_config.py`,
    `test_chat_streaming.py`, `test_settings.py`; opt-in live Greenhouse integration test
    (`tests/test_integration_greenhouse.py`, `JOBHUNT_INTEGRATION=1`). Suite: 67 passed.
  - uv scripts: `jobhunt-smoke`, `jobhunt-test`, `jobhunt-check` (`jobhunt/cli.py`);
    README updated.
  - Small correctness fix: LLM confirm scores are normalized to 0..1 (models may return
    0-100).

**Phase 7 — Close UX gaps (1 day, planned)**
- Resolve the UI wiring gaps flagged during USER_GUIDE review. The current gaps (G1–G5):
  - **G1 — No profile save path.** Fit scoring needs a `models.Profile` in the DB, but
    no screen ever calls `db.save_profile()`; the Fit screen can only ever report "No
    profile found".
  - **G2 — Resume generation has no job.** The Resume screen populates
    `_selected_job_description` / `_selected_company` / `_selected_job_id` nowhere, so
    the tailored-resume and cover-letter buttons always dead-end at "Select a job from
    the Jobs screen first" — and the Jobs screen has no way to select a job row.
  - **G3 — Save to Outputs is a stub.** The button only prints "Outputs feature coming
    soon" even though `ResumeManager.save_tailored_resume()` /
    `save_cover_letter_to_output()` already exist.
  - **G4 — Dashboard is static.** The quick-action buttons do nothing and the stats
    areas show hardcoded placeholders rather than live counts.
  - **G5 — Search hardcodes Greenhouse.** The Search screen always calls
    `run_tool("search_jobs", source="greenhouse", ...)`, ignoring the enabled sources
    configured in Settings/`config.toml`.

  ### A. Profile auto-save for Fit scoring (G1)
  **Problem:** nothing saves a `models.Profile`, so fit scoring can never find one (Fit
  screen shows "No profile found").

  1. Add converter `to_db_profile(resume_profile: resume.Profile) -> models.Profile`:
     - `resume/profile_parser.py` (or `resume/__init__.py`): map `name`, `email`, `phone`,
       `summary`, `skills`, `certifications` directly; `experience`/`education`/`projects`
       via `[{"title", "content", "bullets"}]` from `ResumeSection`; `location` and
       `linkedin_url` default `None`.
  2. In `ResumeScreen._update_resume_preview` (src/jobhunt/app/screens/resume.py:70), after
     `load_profile_from_docx` succeeds:
     - guard `self.db is None`;
     - `self.db.save_profile(to_db_profile(profile))`;
     - append a status note "Profile synced for Fit scoring".
  3. Tests:
     - `tests/test_resume.py`: `to_db_profile` round-trip (sections -> dicts).
     - `tests/test_resume_screen.py`: selecting a docx calls `save_profile` (mock db);
       `db=None` path does not raise.

  ### B. Wire job selection: Jobs -> Resume (G2)
  **Problem:** `_selected_job_description`/`_selected_company`/`_selected_job_id` are never
  populated, so the Resume screen can never generate.

  1. `JobHuntApp` (src/jobhunt/app/__init__.py): add `self.selected_job_id = None` in
     `__init__`.
  2. `JobsScreen` (src/jobhunt/app/screens/jobs.py):
     - in `_update_jobs_table`, pass `key=job.id` to `table.add_row(...)`;
     - add a `Static(id="jobs_status")` widget to `_get_content`;
     - add `on_data_table_row_selected(event)`: set `self.app.selected_job_id =
       event.row_key.value`; look up the job via `self.db.get_job(...)` and update
       `#jobs_status` with "Selected: <title>".
  3. `ResumeScreen`:
     - in `_generate_tailored_resume` and `_generate_cover_letter`, resolve the job first:
       read `self.app.selected_job_id`, `self.db.get_job(...)`; if missing, show "Select a
       job row in the Jobs screen first" and return; otherwise populate
       `_selected_job_description`, `_selected_company`, `_selected_job_id`.
  4. Tests:
     - `tests/test_app.py`: row-selection event sets `app.selected_job_id`.
     - `tests/test_resume_screen.py`: generation resolves description/company from app id
       + db; missing selection shows the guidance message.

  ### C. Implement "Save to Outputs" (G3)
  **Problem:** button prints "Outputs feature coming soon".

  1. `ResumeScreen`:
     - after successful generation, stash `self._last_tailored = tailored` / `self._last_cover_letter
       = cover_letter`;
     - `_save_outputs()`:
       - guard: a generation happened AND a job is selected (`_selected_company`,
         `_selected_job_id`); else status message;
       - call `self.resume_manager.save_tailored_resume(self._last_tailored, company,
         job_id)` and `self.resume_manager.save_cover_letter_to_output(self._last_cover_letter,
         company, job_id)`;
       - report returned paths in `#resume_status` (PDF may be `None` if LibreOffice is
         missing).
  2. Tests: `tests/test_resume_screen.py` — with mocked `ResumeManager`, `_save_outputs`
     passes the selected company/job id and surfaces artifact paths.

  ### D. Dashboard quick actions + live counts (G4)
  **Problem:** quick-action buttons are inert; banner is static.

  1. `JobHuntDB` (src/jobhunt/db/__init__.py): add `count_jobs()` and
     `count_applications()` (simple `SELECT COUNT(*)` wrappers).
  2. `JobHuntApp.on_mount`: install `DashboardScreen(db=self.database)`.
  3. `DashboardScreen` (src/jobhunt/app/screens/dashboard.py):
     - accept and store `db`; on `on_mount`, update stats: total jobs, total applications,
       last few job titles in the Recent Activity area;
     - add `on_button_pressed` that calls `super().on_button_pressed(event)` (nav) then
       maps `search_jobs_btn` -> "search", `view_jobs_btn` -> "jobs", `generate_resume_btn`
       -> "resume" via `self.app.switch_screen(...)`.
  4. Tests: `tests/test_app.py` — dashboard mount renders counts; quick-action buttons
     switch screens.

  ### E. Search across all enabled sources (G5)
  **Problem:** Search screen hardcodes `source="greenhouse"`.

  1. `SearchScreen._search` (src/jobhunt/app/screens/search.py:84):
     - iterate `get_user_config().sources.enabled`;
     - per source call `self.agent.run_tool("search_jobs", query=query, source=source,
       limit=10)` inside its own try/except, collecting a notes line for failures (e.g.
       LinkedIn without env creds);
     - merge results and dedupe by `(title, company)`;
     - render with a `[source]` tag per line.
  2. Tests: new `tests/test_search.py` — monkeypatch `agent.run_tool` to return stubs per
     source and assert aggregation/dedupe across multiple enabled sources and error
     handling for a failing source.

  ### F. Ship
  1. Run `uv run jobhunt-test` — existing 67 tests stay green plus the new ones.
  2. Update README feature list (search-all-sources, profile sync, job selection, assets
     saving, dashboard stats).
  3. Refresh the USER_GUIDE.md limitations section once written (items marked resolved).

**Stretch:** reranker (`bge-reranker-v2-m3`) via `/v1/rerank` to refine final top-k ordering.

## 5. Risks
- Qwen3 tool-call reliability -> verified in Phase 0 smoke test; fallback `Qwen3-Coder-30B`/7B.
- oMLX auth key -> read from `~/.omlx/settings.json`, never hardcoded.
- LinkedIn/Indeed anti-bot + ToS -> kept opt-in, feature-flagged.
- Large JDs -> 8K embedding ctx + 40K Qwen ctx sufficient; context capped in prompts.

## 6. Open confirmations
1. Project dir `~/Documents/Study/projects/python/jobhunt` — confirmed.
2. Sources: Greenhouse/Lever/Ashby first, LinkedIn/Indeed later — confirmed.
3. Base resume directory: `../Resumes/` (relative to project root) — user picks a DOCX from there at runtime.
