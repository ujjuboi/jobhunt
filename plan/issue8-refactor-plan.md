# Plan: Fix Issue #8 — Shared components, full docstrings, descriptive names

**Scope:** whole `src/jobhunt` package (screens, agent, scoring, db, resume, config, llm).

**Critical constraint:** widget IDs must be preserved — `tests/test_app.py` and
`test_resume_screen.py` assert on `#chat_messages`, `#fit_status`, `#status`,
`#analyze_button`, `#chat_btn`, etc.

## Step 1 — New shared components module `src/jobhunt/app/components.py`

- **`ScreenTitle(Static)`** — `__init__(text, id=None)`; replaces the 6
  repetitive `Static("...", id="..._title")` widgets.
- **`StatusText(Static)`** — replaces `#jobs_status`, `#fit_status`,
  `#settings_status`, `#search_results_title`, `#resume_status`,
  `#linkedin_status`. Adds a typed `set_message(text)` helper.
- **`ScrollableTextWindow(TextArea)`** — defaults `read_only=True,
  show_line_numbers=False`, scroll enabled; replaces `#search_results`,
  `#chat_messages`, `#resume_preview`.
- **`ActionButton(Button)`** — used by all action buttons.
- **`WorkerMixin`** — consolidates copy-pasted plumbing across 5 screens:
  lazy `agent` property (fixes the `resume.py` property-vs-field split),
  `_is_busy(group)`, `_run_worker(coro, group)`, and `_list_jobs()`.
  `BaseScreen` inherits it.

## Step 2 — Refactor `app/screens/` to use the shared classes

- `base.py` — nav bar buttons become `ActionButton`s; gains `self.database`;
  adds `title`/`status` convenience helpers.
- The 7 screens (`dashboard`, `search`, `jobs`, `fit`, `resume`, `chat`,
  `settings`) — swap repetitive Static/TextArea/Button boilerplate for shared
  classes, **keeping all existing widget IDs**.
- Remove now-dead duplicates: `_list_jobs()` in `jobs.py:80`/`fit.py:97`,
  `_is_busy()` in `fit.py:78`/`chat.py:60`.
- `app/__init__.py` — constructors called with `database=` keyword;
  `self.database` becomes the single shared name.

## Step 3 — Rename abbreviated variables (whole package)

- Screens: `fit` → `fit_score`, `fits` → `fit_scores`, `job` → `job_entry`,
  `table` → `data_table`, `msg` → `message`, `q` → `lower_query`,
  `out` → `deduplicated`, `seen` → `seen_keys`, `key` → `dedupe_key`,
  `exc` → `error`, `item`/`chunk` → `piece`, shorthand loop vars → descriptive.
- `db` → `database` everywhere as a **variable/attribute/parameter**: screens,
  `agent/__init__.py` (`self.database`, `ToolRegistry(database, ...)`),
  `scoring/__init__.py` (`ScorePipeline.__init__(database, ...)`),
  `src/jobhunt/__init__.py` (module global → `_database`, keep public
  `get_db()`).
- `db/__init__.py`: `db_path` → `database_path`, `conn` → `connection`,
  `row` → `record`, etc.
- **Not renamed:** module path `jobhunt.db`, class `JobHuntDB`, accessor
  `get_db()`, and `db_profile`/`to_db_profile` (resume — already descriptive
  domain terms).

## Step 4 — JSDoc-style docstrings on every function

- Google style with `Args:`, `Returns:`, `Raises:` on **every** method and
  function in `src/jobhunt/` (screens, components, agent, scoring, db, resume,
  config, llm, embeddings, sources, cli, logging).
- Add module docstrings where missing; expand existing ones to
  Args/Returns/Raises.

## Step 5 — Update tests

- `tests/test_resume_screen.py` uses `ResumeScreen(db=None)` and asserts
  `screen.db` → use `database=` / `screen.database`.
- Fake `JobHuntAgent(lambda db=None: ...)` lambdas in `test_app.py` /
  `test_chat_streaming.py` → `lambda database=None: ...`.
- Renamed leaf params (`ScorePipeline(database=...)`, `ToolRegistry(database=...)`)
  call sites in `test_scoring.py` and others.

## Step 6 — Verify

- `uv run pytest` (16 test files) all green.
- Manual `python -m jobhunt` smoke check of navigation + one screen
  (`smoke.py` exists in repo — run it).
- Grep to confirm no `db` attribute/variable references remain (excluding
  `jobhunt.db` module imports and `*.db` filenames).

## Guardrails

- No secrets in scope; commit separately and deliberately
  (e.g. "Refactor screens to shared components with full docstrings").