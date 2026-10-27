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
- **Navigation bar** — shared `NavBar` component (`app/components.py`) with 7 buttons (Dashboard, Search, Jobs, Fit, Resume, Chat, Settings); the active tab is highlighted via the `active` CSS class, driven by the global `app.active_tab` state
- **Content area** — `#screen_content` container
- **Action rows** — every screen's action buttons are grouped in a shared `ButtonRow` component (`app/components.py`, a `Horizontal` with `height: auto`) so all in-screen actions on a page align on a single row. On Chat/Search the row also holds the message/query input next to its button.
- **Row-click tables** — `RowClickTable` (a `DataTable` subclass) posts a `RowClicked` message for every click on a data row, because Textual's `DataTable` only posts `RowSelected` in row-cursor mode
- **Context menus** — `ContextMenu` (a `Vertical` overlay) shows a floating menu of actions anchored at a screen position; it is dismissed with Escape or a click outside of it
- **Footer**
- **Status text** — one-line status message via `self._status(text, id=...)` and `set_message()`
- **Background work** — never block the event loop; use `self._run_worker(coro, group)` from `WorkerMixin` and update the UI with `self.call_after_refresh(...)`
- **Busy guard** — re-entry is prevented with `self._is_busy(group)`

Each screen yields a shared `NavBar` component (`app/components.py`) from its `compose()` method. The active tab is updated globally in `JobHuntApp.switch_screen()` before the new screen displays. The `NavBar` applies the `active` CSS class to the matching button at mount time (first visit, driven by `app.active_tab`) and re-applies it on every screen resume via `BaseScreen.on_screen_resume()` → `NavBar.set_active()`, so already-mounted screens keep the correct highlight across switches. `set_active()` also moves keyboard focus to the active tab's button when nothing is focused or focus is already on the nav bar; without this Textual auto-focuses the first focusable widget (the Dashboard button), which makes the focus highlight appear on the wrong tab. A focused widget such as an input keeps focus when a screen only resumes (for example after the command palette is dismissed).

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

Paginated DataTable of saved jobs (20 per page) with a text filter, a
row-click context menu, and refresh capability.

| Widget ID | Type | Purpose |
|---|---|---|
| `#jobs_filter_input` | Input | Live text filter (title, company, location) |
| `#jobs_table` | RowClickTable | Saved jobs for the current page (reports row clicks) |
| `#job_details` | ScrollableTextWindow | Full job card, shown below the table on demand |
| `#job_context_menu` | ContextMenu | Floating menu with the row actions |
| `#job_menu_title` | Static | Heading of the context menu (the job's title) |
| `#view_details_btn` | ActionButton | Show the job card in `#job_details` |
| `#chat_job_btn` | ActionButton | Hand the job to the Chat screen and switch to it |
| `#apply_btn` | ActionButton | Open the job's application URL in the browser |
| `#jobs_status` | StatusText | Status messages ("Showing X of Y jobs (page N of M)") |
| `#prev_page_btn` | Button | Previous page (disabled on first page) |
| `#next_page_btn` | Button | Next page (disabled on last page) |
| `#jobs_page_indicator` | StatusText | "Page N of M" indicator |
| `#refresh_button` | Button | Reload jobs from DB (returns to page 1) |

**Pagination:** pages are fetched with `database.get_jobs(limit=20, offset=page*20,
search=filter)`; `count_jobs(search=...)` drives the page count. Typing in the
filter input resets to page 1 and re-queries with a case-insensitive, literal
substring match against title, company, and location (Unicode-aware case
folding; `%` and `_` are not treated as `LIKE` wildcards).

**Row actions:** clicking a row selects the job (`self.app.selected_job_id`, which
the Resume screen consumes for tailored resume/cover-letter generation) and opens a
floating `ContextMenu` anchored at the click position. The menu offers three actions:
*View Details* (renders the job card — title, company, id, posting date, location,
salary, remote flag, source, URL, and the full description — into the scrollable
`#job_details` pane below the table), *Chat About This Job* (loads the job into the
Chat screen as context and switches to it), and *Apply* (opens the job's URL in the
default browser). Escape or a click outside the menu dismisses it; the menu is moved
up/left when it would overflow the screen.

**Click handling:** `#jobs_table` is a `RowClickTable` (a `DataTable` subclass), because
Textual's `DataTable` defaults to `cursor_type="cell"`: a single click only moves the
cursor and never posts `RowSelected`. `RowClickTable` posts a `RowClicked` message
(with the row key and the click's screen coordinates) for every click on a data row.
Keyboard users get the same menu through `CellSelected` (Enter), anchored to the
selected row.

**Auto-reload:** jobs are reloaded on mount, on resume of focus, and on refresh button press.

---

### Fit (`fit`)

Paginated DataTable of ranked fit scores (20 per page) with a text filter.
Scores jobs against the user's profile using the scoring pipeline.

| Widget ID | Type | Purpose |
|---|---|---|
| `#fit_filter_input` | Input | Live text filter (title, company, location); disabled while scoring |
| `#fit_status` | StatusText | Status messages |
| `#fit_loading` | LoadingIndicator | Shown while a ranking run is in progress |
| `#fit_table` | RowClickTable | Current page's jobs, scored rows first (score descending) |
| `#fit_detail` | ScrollableTextWindow | Per-job breakdown |
| `#prev_page_btn` | Button | Previous page (disabled on first page) |
| `#next_page_btn` | Button | Next page (disabled on last page) |
| `#fit_page_indicator` | StatusText | "Page N of M" indicator |
| `#analyze_button` | Button | Score the current page |

**Row order and rank column:** within a page, scored jobs sort above unscored
ones by score descending (unscored keep posting order). The Rank column is the
job's position in the full posting-ordered result set, so rank numbers are not
sequential top-to-bottom once scores land. Ordering is per page: a page-2 job
can out-score a page-1 job, since pages are scored on demand.

**Workflow:** loads the current page of jobs from the DB (20 per page, filtered by
`#fit_filter_input`); Analyze runs `ScorePipeline` on the visible page in the configured
mode (hybrid/embedding/llm). Opening a new page via Prev/Next (or changing the filter)
auto-ranks that page's unscored jobs — the `#fit_loading` indicator and a "Ranking page
N" status are shown while scoring runs, and pagination plus the filter input are
disabled until it finishes (so the text in the box cannot diverge from the filter
being scored). Scores are cached per job id, so revisiting a page never re-ranks
known scores. Clicking a row (or selecting it with the keyboard) shows the detailed
breakdown in the scrollable `#fit_detail` pane: score, explanation, matched skills,
missing skills, and suggested resume bullets; the clicked job also becomes the
current selection (`self.app.selected_job_id`).

**Profile requirement:** needs a `Profile` saved in the DB (auto-synced when selecting a
DOCX on the Resume screen). Without a profile, displays "No profile found".

---

### Resume (`resume`)

Resume generation, tailoring, and cover-letter workflow.

| Widget ID | Type | Purpose |
|---|---|---|
| `#resume_select` | Select | Pick a base DOCX from `../../Resumes/` |
| `#resume_preview` | ScrollableTextWindow | Profile preview (keeps a usable scroll viewport) |
| `#resume_status` | StatusText | Status messages |
| `#generate_tailored_btn` | Button | Generate tailored resume |
| `#generate_cover_letter_btn` | Button | Generate cover letter |
| `#save_outputs_btn` | Button | Save artifacts to `outputs/` |

**DOCX parsing:** selects a `.docx` from `../../Resumes/` (two levels up from project root). Parses
into a structured `Profile`, JSON-caches at `cache/resume/{filename}.json`, and auto-saves
to the DB for fit scoring.

**Preview scrolling:** `#resume_preview` is a read-only scrollable window that keeps a
minimum viewport height (`app.tcss`: `height: 1fr; min-height: 5`), because the resume
screen stacks more fixed-height chrome above it than other screens. On short terminals
`#resume_content` scrolls (`overflow-y: auto`) so the action buttons stay reachable
instead of being clipped.

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

**Job context:** the Jobs screen can hand a job over with "Chat About This Job". The job
is appended to the conversation as a `system` message (title, company, location, posting
date, id, URL, and a description truncated to 4,000 characters), echoed in the transcript
as a "Job context" line, and the input is pre-filled with the starter question
"What should I know about this job?". The context is applied even when the Chat screen
has not been opened yet: it is held until the screen is mounted.

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

**LinkedIn login:** the Login button shares the bottom action row with Save Config
(`#linkedin_login_btn` + `#save_config_btn` in one `ButtonRow`); the collapsible
`#linkedin_block` reports the current sign-in state: "Not signed in" when no session
exists, otherwise "Signed in as <account email>" (the email is resolved from the
persisted session on mount/resume and after login). Login launches a headful browser
window for interactive login. Session cookies are persisted at
`cache/linkedin_session.json` for subsequent headless reuse.

## Screen Navigation

- Initial screen: `"dashboard"` pushed via `push_screen("dashboard")` in `on_mount`
- Nav buttons call `self.app.switch_screen(name)` (safe only after mount)
- Dashboard quick-action buttons also use `self.app.switch_screen(...)` for navigation
