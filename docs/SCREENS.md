# TUI Screens

JobHunt uses Textual for its terminal UI. There are **7 screens** installed on the main
`JobHuntApp`, plus a persistent navigation bar visible on every screen.

## Shared Chrome

Every screen subclasses `BaseScreen` (`app/screens/base.py`), which provides:

- **Header** — bold page title via `self._title(text, id=...)`; the `HeaderIcon` trigger
  (`⭘`) is restyled in `app.tcss` with a `$primary` background for visibility
- **Command palette** — `JobHuntCommandsProvider` (`app/palette.py`) replaces Textual's
  default provider; `App.get_system_commands` yields Keys, Theme, Screenshot, then Quit
  last (Maximize/Minimize is omitted), and the provider preserves that order without sorting
- **Navigation bar** — `#nav_bar` with 7 buttons (Dashboard, Search, Jobs, Fit, Resume, Chat, Settings)
- **Content area** — `#screen_content` container
- **Footer**
- **Status text** — one-line status message via `self._status(text, id=...)` and `set_message()`
- **Background work** — never block the event loop; use `self._run_worker(coro, group)` from `WorkerMixin` and update the UI with `self.call_after_refresh(...)`
- **Busy guard** — re-entry is prevented with `self._is_busy(group)`

CRITICAL: the nav bar was moved from `App.compose` into `BaseScreen` because Textual screens
fully replace the App body — a nav in `App.compose` would vanish after the first screen switch.

## Screen Details

### Dashboard (`dashboard`)

The starting screen (pushed in `on_mount`). Provides an overview and quick navigation.

| Widget ID | Type | Purpose |
|---|---|---|
| `#status` | StatusText | General status |
| `#activity_container` | Container | Recent activity area |
| `search_jobs_btn` | Button | Navigate to Search screen |
| `view_jobs_btn` | Button | Navigate to Jobs screen |
| `generate_resume_btn` | Button | Navigate to Resume screen |

**Live counts:** on mount, fetches total jobs (`db.count_jobs()`) and total applications
(`db.count_applications()`). Displays recent job titles in the activity area.

**Quick actions:** buttons call `self.app.switch_screen(...)` to navigate to the target screen.

---

### Search (`search`)

Config-driven multi-source job search with live filtering and deduplication.

| Widget ID | Type | Purpose |
|---|---|---|
| `#search_input` | Input | Search query text field |
| `#search_button` | Button | Trigger search |
| `#search_results` | ScrollableTextWindow | Display search results |
| `#jobs_status` | StatusText | Status messages |

**Behavior:** iterates all enabled sources from `config.toml` (`user_config.sources.enabled`).
For each keyword-search source (Indeed, LinkedIn), calls `search_jobs(query)`. For board
sources (Greenhouse, Lever, Ashby), searches within configured company slugs. Results are
merged and deduplicated by `(title, company)`. Each line is tagged with its `[source]`.

**Live filtering:** the `#search_input` text field doubles as a client-side filter as the user
types — results are filtered instantly without a server call.

---

### Jobs (`jobs`)

DataTable of saved jobs with row selection and refresh capability.

| Widget ID | Type | Purpose |
|---|---|---|
| `#jobs_table` | DataTable | Saved jobs table (top 20) |
| `#jobs_status` | StatusText | Status messages |
| `#refresh_button` | Button | Reload jobs from DB |

**Job selection:** clicking a row sets `self.app.selected_job_id` and updates the status bar
with "Selected: <title>". This selection is consumed by the Resume screen for tailored
resume/cover-letter generation.

**Auto-reload:** jobs are reloaded on mount, on resume of focus, and on refresh button press.

---

### Fit (`fit`)

Ranked fit-score table. Scores jobs against the user's profile using the scoring pipeline.

| Widget ID | Type | Purpose |
|---|---|---|
| `#fit_table` | DataTable | Ranked scored jobs |
| `#fit_status` | StatusText | Status messages |
| `#fit_detail` | ScrollableTextWindow | Per-job breakdown |
| `#analyze_button` | Button | Run fit analysis |

**Workflow:** loads all jobs from the DB, runs `ScorePipeline` in the configured mode
(hybrid/embedding/llm), and renders a ranked table. Selecting a row shows the detailed
breakdown: score, explanation, matched skills, missing skills, and suggested resume bullets.

**Profile requirement:** needs a `Profile` saved in the DB (auto-synced when selecting a
DOCX on the Resume screen). Without a profile, displays "No profile found".

---

### Resume (`resume`)

Resume generation, tailoring, and cover-letter workflow.

| Widget ID | Type | Purpose |
|---|---|---|
| `#resume_select` | Select | Pick a base DOCX from `../Resumes/` |
| `#resume_preview` | ScrollableTextWindow | Profile preview |
| `#resume_status` | StatusText | Status messages |
| `#generate_tailored_btn` | Button | Generate tailored resume |
| `#generate_cover_letter_btn` | Button | Generate cover letter |
| `#save_outputs_btn` | Button | Save artifacts to `outputs/` |

**DOCX parsing:** selects a `.docx` from `../Resumes/` (sibling to project root). Parses
into a structured `Profile`, JSON-caches at `cache/resume/{filename}.json`, and auto-saves
to the DB for fit scoring.

**Tailored resume:** combines profile + selected job description (via job selection from
Jobs screen). LLM-first with heuristic keyword-matching fallback. Rebuilds a tailored
DOCX from a template.

**Save to Outputs:** writes tailored resume (DOCX + PDF) and cover letter to
`outputs/{company}/{job}/` subdirectories.

---

### Chat (`chat`)

Streaming chat transcript with the JobHunt agent.

| Widget ID | Type | Purpose |
|---|---|---|
| `#chat_messages` | ScrollableTextWindow | Chat transcript |
| `#chat_input` | Input | User message |
| `#send_button` | Button | Send message |

**Streaming:** checks `hasattr(agent, "chat_stream")`. If available, streams text deltas
incrementally into the transcript via an `asyncio.Queue`. Falls back to non-streaming
(blocking) when streaming is unavailable.

**Error safety:** errors in the conversation are stored as neutral markers
(`[error: see logs]`) in the transcript — never as raw error strings (which would pollute
the model's context on subsequent turns).

**Busy guard:** prevents double-sends. A new message is not sent while the agent is still
responding.

---

### Settings (`settings`)

Configuration UI for sources, models, scoring, and system prompts.

| Widget ID | Type | Purpose |
|---|---|---|
| `#base_url` | Static | oMLX endpoint display (read-only) |
| `#api_key` | Static | API key display (masked, read-only) |
| `#sources_input` | Input | Comma-separated enabled source names |
| `#model_input` | Input | Chat model override |
| `#score_mode_select` | Select | Scoring mode: hybrid/embedding/llm |
| `#system_prompt` | TextArea | System prompt for the agent |
| `#linkedin_login_btn` | Button | Initiate LinkedIn browser login |
| `#save_config_btn` | Button | Save TOML config |
| `#settings_status` | StatusText | Status messages |
| `#linkedin_status` | StatusText | LinkedIn login status |

**Config save:** writes TOML to `~/.config/jobhunt/config.toml` (or `JOBHUNT_CONFIG`
override path). Updates sources, companies, prompts, model, scoring mode.

**LinkedIn login:** launches a headful browser window for interactive login. Session cookies
are persisted at `cache/linkedin_session.json` for subsequent headless reuse.

## Screen Navigation

- Initial screen: `"dashboard"` pushed via `push_screen("dashboard")` in `on_mount`
- Nav buttons call `self.app.switch_screen(name)` (safe only after mount)
- Dashboard quick-action buttons also use `self.app.switch_screen(...)` for navigation
