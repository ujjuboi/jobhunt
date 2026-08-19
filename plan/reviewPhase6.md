# Review — Phase 6 Polish

Date: 2026-08-18
Scope: retry/timeouts/logging, streaming agent loop, config UI, tests, uv scripts, README

## Summary

Phase 6 delivers the polish milestone plus the streaming agent loop folded in from the
Phase 1 open item. Test suite grew from 45 to 67 passing tests (1 opt-in integration test
skipped by default). All work verified against the live oMLX server
(`uv run python smoke.py` green; `chat`, `chat_stream`, and `chat_with_agent` round-trips OK).

## What landed

### 1. Error/retry handling, timeouts, logging (`jobhunt/llm.py`, `jobhunt/logging.py`)
- `retry()` decorator with exponential backoff + jitter for transient errors
  (429/5xx/connection/timeout). Auth (401/403) and client 4xx are NOT retried.
- `complete()` / `stream()` wrappers; `stream()` restarts the request mid-stream on a
  transient drop (verified by `test_stream_restarts_after_mid_stream_drop`).
- OpenAI + httpx clients get a 60s timeout and SDK-level `max_retries=2`.
- `setup_logging()`: stderr + rotating-free file log at
  `~/.config/jobhunt/logs/jobhunt.log`; `JOBHUNT_LOG_LEVEL` override. Wired into
  `JobHuntApp.__init__`.
- All `print()`-based error paths in agent/db/sources/scoring/resume/config replaced with
  module loggers (verified no stray `print(` remains except the intentional CLI one).

### 2. Config UI (`config/user_config.py`, `app/screens/settings.py`)
- `UserConfig` pydantic model + TOML load/save (stdlib `tomllib`, no new deps).
- Config file: `~/.config/jobhunt/config.toml`, overridable via `JOBHUNT_CONFIG`.
- Fields: `sources.enabled`, `sources.companies`, `prompts.system/score`,
  `model.chat/embedding/confirm`, `scoring.mode`.
- `get_scoring_mode()` now prefers `JOBHUNT_SCORING_MODE`, then config, then hybrid.
- Settings screen edits sources, companies, chat model, scoring mode, system prompt and
  writes the TOML on Save. `test_settings.py` locks the behavior in.

### 3. Streaming agent loop (`agent`, `app/screens/chat.py`)
- `JobHuntAgent.chat_stream()` yields reply deltas; ChatScreen renders them incrementally
  via an `asyncio.Queue` fed from a worker thread. Falls back to non-streaming when the
  agent object lacks `chat_stream()` (keeps the Phase 1 fakes/tests compatible).

### 4. Tests
- New: `test_llm.py`, `test_user_config.py`, `test_chat_streaming.py`, `test_settings.py`.
- Opt-in live Greenhouse integration test: `tests/test_integration_greenhouse.py`
  (`JOBHUNT_INTEGRATION=1 uv run pytest -m integration`), skips by default.
- Source fixtures (mocked HTTP payloads) already existed in `test_sources.py`.

### 5. uv scripts + README
- `jobhunt-smoke`, `jobhunt-test`, `jobhunt-check` entry points (`jobhunt/cli.py`).
- README rewritten with config docs, dev commands, and integration-test instructions.

## Findings / notes

- **Normalized LLM confirm scores.** The real Qwen model returned `score: 85` (0-100);
  the pipeline assumed 0-1, which would have skewed hybrid ranking. `scoring/__init__.py`
  now clamps to 0..1 (divide by 100 when > 1).
- **Textual `Select` option order.** Textual 8.2.8 `Select` takes `(label, value)` tuples,
  not `(value, label)`. Initial settings screen used the wrong order and failed with
  `InvalidSelectValueError`; corrected and covered by tests.
- **Dead code removed** in `lever.py` / `ashby.py`: `get_job_detail` raised
  `NotImplementedError` inside a `try` that caught it immediately (always returned `None`);
  now logs and returns `None`.
- **Streaming partial-yield semantics.** On a mid-stream transient drop, deltas already
  emitted before the failure are consumed by the caller; the retry only guarantees the
  *final* attempt is complete. The ChatScreen surfaces an error line if the last attempt
  fails, so a dropped tail never silently truncates.
- Phase 4 review items (unused imports, `List` import, pdf_converter error propagation,
  duplicate resume-preview load) were verified fixed in the current code.

## Verification

- `uv run jobhunt-test` -> 67 passed, 1 skipped (integration).
- `uv run python smoke.py` -> all oMLX smoke tests passed against live server.
- Manual round-trips against live oMLX: `chat`, `chat_stream`, `chat_with_agent` (JSON).

## Post-review findings (2026-08-18)

Findings from a code review of the uncommitted Phase 6 changes, with a fix plan.

### 1. [Bug, High] `cli.py` resolves project root one level too high — `jobhunt-smoke`/`jobhunt-check` are broken
`src/jobhunt/cli.py:12` uses `Path(__file__).resolve().parents[3]`. For a module at
`src/jobhunt/cli.py`, `parents[3]` is the *parent* of the project root, so `smoke()`
runs `runpy.run_path(".../python/smoke.py")` -> `FileNotFoundError`. `resume/__init__.py:14`
uses the same idiom but sits one directory deeper (`jobhunt/resume/`), where it is correct.
The README/PLAN both document `uv run jobhunt-smoke`, so the documented path fails.
- **Fix:** `parents[2]`; add `tests/test_cli.py` asserting the resolved `PROJECT_ROOT/smoke.py` exists.

### 2. [Bug, Medium] Retry policy never matches the connect/timeout exceptions it claims to retry
`llm.py:29` sets `TRANSIENT_EXCEPTION_TYPES = (ConnectionError, TimeoutError, OSError)`.
Verified against installed openai 3.x and httpx: `openai.APIConnectionError`/`APITimeoutError`
inherit `APIError -> OpenAIError -> Exception` (no `status_code`), and `httpx.ConnectError`
subclasses `HTTPError`, not `OSError`. So `is_transient_error(None, exc)` is always `False`
for real transport failures:
- `llm.stream()`'s mid-stream restart only fires on 429/5xx (status-coded). A real
  connection drop surfaces as `APIConnectionError` and is re-raised, not restarted.
  `test_stream_restarts_after_mid_stream_drop` uses a fake `TransientError(status_code=503)`,
  so it cannot catch this.
- `complete()`'s `@retry` adds nothing for connect/timeout; only the SDK's `max_retries=2`
  covers them. Docstring + review text overstate the behavior.
- **Fix:** add `openai.APIConnectionError`, `openai.APITimeoutError`, `httpx.ConnectError`,
  `httpx.TimeoutException` to `TRANSIENT_EXCEPTION_TYPES`; add tests using the real classes.

### 3. [Bug, Medium] `stream()` restart duplicates text in the transcript
On a transient mid-stream error (`llm.py:172-182`) the loop re-issues the same request from
scratch and re-yields the **full** response from the beginning. The caller
(`ChatScreen._ask_agent_streaming`, `chat.py`) accumulates every chunk in `reply_parts`, so a
drop after "ab" + successful restart yields `"ab" + "ab..."` — duplicated text in the
transcript and in the assistant message appended to `self.messages` (sent back to the model on
the next turn). The partial-yield note in "Findings / notes" frames this as a truncated tail,
but it is a full re-run. The test's fake yields different content per attempt
(`["a"]` then `["cd"]`), hiding the duplication.
- **Fix options:** (a) restart only before the first delta is delivered; (b) on restart, have
  the caller truncate overlapping prefixes instead of concatenating; (c) accept the tail-drop
  semantics and surface an error line, updating the docs/tests to match. Recommended: (b)/(c).

### 4. [Low] `JOBHUNT_CHAT_MODEL` / `JOBHUNT_CONFIRM_MODEL` env overrides bypassed on agent paths
`JobHuntAgent._resolve_model` (`agent/__init__.py`) returns `config.model.chat` directly and
passes it explicitly to `llm.complete`/`llm.stream`, so `llm.get_default_model()` (which
implements the documented env -> config -> builtin precedence) is never consulted.
`config.model.confirm` passed via kwargs in `scoring/__init__.py` similarly bypasses
`JOBHUNT_CONFIRM_MODEL`. README lists these env vars as "highest precedence".
- **Fix:** have `_resolve_model` fall through to `llm.get_default_model("chat")` when no
  explicit model; resolve confirm via env -> config in scoring.

### 5. [Low] Settings screen attaches all companies to the first enabled source
`settings.py:_save_config` writes `{config.sources.enabled[0]: companies}`, but the UI label
says "per enabled source" and multiple sources are the default. With `greenhouse, ashby`
enabled, all typed companies go to `greenhouse`, and pre-existing entries for other sources
are wiped on save. `test_settings_save_writes_user_config` locks in the first-source-only
behavior, contradicting the label.
- **Fix:** map companies per source (per-source inputs), or keep a single list and update the
  label + test to document first-source-only behavior.

### 6. [Low] Error text pollutes assistant conversation history
`chat.py:_ask_agent` appends `{"role": "assistant", "content": str(e)}` on failure, so the
error string becomes model context on the next turn (both non-streaming and
`_ask_agent_streaming` paths).
- **Fix:** log the error and append a neutral marker (or nothing) to `self.messages`.

### Minor notes
- `_ask_agent_streaming` feeds `asyncio.Queue` via `put_nowait` from a worker thread
  (`chat.py`); `asyncio.Queue` is not thread-safe. Works in practice on CPython; the canonical
  pattern is `loop.call_soon_threadsafe`.
- No test covers `cli.py`, which is why finding #1 shipped.

### Fix priority
1. #1 (one-line fix + test) — breaks documented CLI.
2. #2, #3 — reconcile retry/streaming semantics before Phase 6 "DONE" is considered accurate.
3. #4, #5, #6 — lower severity, straightforward.
4. Minor — thread-safety and cli.py test coverage.
