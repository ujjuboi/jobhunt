# JobHunt Project Conventions

Local AI job-search harness: a Textual TUI over an OpenAI-compatible local server (oMLX), SQLite storage, resume tools, and job-board scrapers. Python 3.12, uv-managed, src-layout (`src/jobhunt/`).

## Commands

- Tests: `uv run pytest` (baseline ~91 passed, 1 skipped). Integration tests are opt-in and must not require network/config in CI -- guard them with the `integration` pytest marker (requires `JOBHUNT_INTEGRATION=1` to run).
- `uv run jobhunt` launches the TUI; `uv run jobhunt-smoke` exercises the live oMLX server.
- No linter/formatter is configured (no ruff/flake8/black/mypy). Verify with the test suite and `python -m compileall`.

## TUI screens

- `JobHuntApp` (`app/__init__.py`) installs the seven screens with `install_screen(ScreenName(database=self.database), name=...)` and pushes `"dashboard"` in `on_mount`. The app owns `self.database` and passes the same instance to every screen.
- Every screen subclasses `BaseScreen` (`app/screens/base.py`), which inherits `WorkerMixin` from `app/components.py`. Write a screen's body in `_get_content()`, NOT `compose()`.
- Use the shared components from `app/components.py` instead of hand-rolling: `ScreenTitle`, `StatusText` (one-line status, set via `set_message`), `ScrollableTextWindow` (read-only scrollable `TextArea`), `ActionButton` (action buttons only; nav buttons stay plain `Button`), `WorkerMixin`.
- Use `self._title(text, id=...)` and `self._status(text, id=...)` helpers from `BaseScreen`.
- CRITICAL: preserve widget IDs. Tests address widgets by ID (e.g. `#chat_messages`, `#fit_status`, `#status`, `#fit_table`, `#analyze_button`, `#jobs_status`, `#search_results`, `#sources_input`, `#linkedin_block`, `#settings_status`, `#nav_bar`, `#*_btn`). Never rename IDs during a refactor.
- Background work: never block the event loop. Dispatch blocking I/O via `self._run_worker(asyncio.to_thread(coro), group)` (started exclusively per `group`) and update the UI with `self.call_after_refresh(...)`. Guard re-entry with `self._is_busy(group)`.
- Input handlers delegate to the base first: `super().on_button_pressed(event)` (drives the nav bar), then handle action buttons by `event.button.id`.

## Agent (lazy) pattern

- `JobHuntAgent` is created lazily via the `agent` property on `WorkerMixin` and memoized (`_agent`). Test fakes are injected through the `agent` setter or by patching `jobhunt.app.components.JobHuntAgent`.
- Agent construction calls `get_omlx_settings()` and can fail when oMLX is unavailable/offline. On failure `agent` is `None` (the failure is only logged).
- Do NOT call methods on `self.agent` unguarded (that yields a `NoneType has no attribute` error), and do NOT silently return `[]` on failure (that hides the real cause behind an "empty" state). Call `self._require_agent()`, which raises `AgentUnavailableError` (from `app.components`) with a descriptive message; let screens surface it via their existing `except Exception → status update` paths.

## Naming

Descriptive names throughout. When refactoring, rename abbreviated identifiers (the `db`/`e`/`exc`/`job`/`table` style) to `database`/`error`/`job_entry`/`data_table`, etc.

Exceptions that stay as-is (do NOT rename):
- Module path `jobhunt.db`, class `JobHuntDB`, and accessor `get_db()`.
- Resume's `db_profile` / `to_db_profile` (domain terms, already descriptive).
- `JobHuntDB` constructor parameter is `database_path` (not `db_path`).

## Code style

- Google-style docstrings on every module, method, and function: `Args:`, `Returns:`, `Raises:`.
- Python 3.12 syntax is fine (`X | None`, `list[...]` / `dict[...]`).
- No comments unless they explain non-obvious "why"; docstrings carry the intent.
- Errors: surface the real cause with a descriptive message; do not swallow failures into empty states. (See the `AgentUnavailableError` pattern.)
- Chat: never append raw error strings into `self.messages` (they feed the model's context on the next turn). Log the error and store a neutral marker, e.g. `{"role": "assistant", "content": "[error: see logs]"}`.
- Logging: stdlib `logging.getLogger(__name__)`; no `print()` in library/app code (the CLI's deliberate `print` is the only exception).
- Streaming: yield from a worker thread into an `asyncio.Queue`; on a mid-stream drop the final attempt must complete and a dropped tail surfaces as an error line in the transcript.

## Tests

- All tests in `tests/`; pytest config lives in `pyproject.toml` (`testpaths = ["tests"]`, `addopts = "-ra"`, `integration` marker).
- Construct screens with `ScreenName(database=...)` and assert on `screen.database`. Patch the agent where it is actually built (`jobhunt.app.components.JobHuntAgent`) or inject a fake via the `agent` setter.
- Use small terminal sizes in `run_test(size=(140, 40))` so action buttons stay on-screen.
- Async UI assertions are race-prone: wait for background workers to settle before acting, then poll for the target status (see `test_fit_screen_analyze_without_profile_guides_user`). Avoid asserting on a single fixed sleep.