# Review — Phase 1 Agent + TUI Skeleton

Date: 2026-08-16
Scope: Phase 1 deliverables in `src/jobhunt/` (per PLAN.md §4 Phase 1)

## Summary

Phase 1 review found the app **unrunnable**: `on_mount` used `register_screen` (doesn't exist in
Textual 8.2.8) and the nav buttons called a no-op `show_screen` stub. All findings were fixed,
verified headlessly (Textual `run_test`), and locked in with pytest.

## Findings (all verified against Textual 8.2.8)

### Critical
1. **`register_screen` does not exist in Textual 8.2.8.** `app/__init__.py:71` raised
   `AttributeError` at mount — the app never rendered. Fixed: `install_screen(screen, name=...)`.
2. **`switch_screen("dashboard")` in `on_mount` raised `IndexError: pop from empty list`.**
   Textual pops the default screen and unconditionally calls `_pop_result_callback()`, which fails
   because the default screen has no result callback. Verified `push_screen` works in `on_mount`;
   `switch_screen(name)` is safe only post-mount.

### High
3. **Nav buttons never navigated** — `show_screen()` was a no-op stub (only updated the welcome
   text). Fixed by removing the stub and routing buttons through `switch_screen(name)`.
   **New finding during fix:** the nav bar lived in the App `compose`, which screens fully replace —
   nav disappeared after the first screen switch. Moved the nav into `BaseScreen` so it persists.

### Medium
4. **Chat screen was inert UI only** — no message handlers, no `JobHuntAgent` reference (Phase 1's
   core deliverable missing). Wired end-to-end: lazy agent, async worker, transcript, error display.
5. **Config side effect at import** — `config/__init__.py` ran `load_omlx_settings()` at module
   level, so `import jobhunt.agent` raised `ValueError` without an oMLX key (this also breaks the
   lazy-config test). Fixed with cached `get_omlx_settings()` (lazy).
6. **`test_phase1.py` gave false confidence** — checked imports/tool registration only, never
   mounted the app, so it passed a crashing TUI. Replaced with pytest + `tests/test_app.py`.

### Minor
7. Duplicate `#welcome` id (App compose + Dashboard) — removed the App-level copy.
8. `settings.py` hardcoded the base URL — now read from config.

## Deviations from PLAN.md

1. **Nav architecture** — PLAN's Phase 1 note assumed the nav stays in the App `compose`. Actual
   implementation moves it into `BaseScreen` (shared by all screens) because Textual screens replace
   the App body. PLAN.md §4 Phase 1 updated to reflect this.
2. **Textual 8.2.8 API facts** — `install_screen`/`push_screen`/`switch_screen` usage now recorded
   in PLAN.md so later phases don't repeat the mistakes.
3. **Tests added early** — pytest + `tests/test_app.py` landed in Phase 1; PLAN schedules unit
   tests for Phase 6. Kept in Phase 1 because they were needed to verify the mount fix.
4. **Config made lazy** — resolves deferred Phase 0 item 14 ("config loaded at import time").
5. **Streaming agent loop NOT implemented** — `agent.chat()`/`chat_with_agent()` are non-streaming.
   Recorded as an open Phase 1 item in PLAN.md (fold into Phase 6 or a follow-up).

## Verification

- `uv run pytest` — 6 passed (mount, nav switch, tool registry, lazy config, chat round-trip, chat
  error surfacing).
- Headless full smoke — all 7 nav buttons switch screens; chat round-trip with a fake agent renders
  `You: … / Agent: …` in the transcript.
- `uv run jobhunt` — TUI launches, Dashboard renders with persistent nav bar; killed cleanly.

## Files touched

- `src/jobhunt/app/__init__.py` — install/push screens, drop `show_screen` stub, nav removed from
  App compose.
- `src/jobhunt/app/screens/base.py` — persistent nav (Header + 7 buttons + content + Footer),
  `switch_screen` handler, nav-id guard.
- `src/jobhunt/app/screens/chat.py` — end-to-end agent chat via async worker.
- `src/jobhunt/app/screens/settings.py` — base URL from config.
- `src/jobhunt/agent/__init__.py` — plain-text `chat()`, lazy settings.
- `src/jobhunt/config/__init__.py` — cached `get_omlx_settings()`.
- `src/jobhunt/app/app.tcss` — compact nav styling + chat layout.
- `pyproject.toml` — `[dependency-groups] dev` (pytest).
- `tests/test_app.py` (new); `test_phase1.py` (deleted).

Deferred: streaming agent loop; remaining screens still show stub content (Search/Jobs/Fit/Resume
handlers arrive with Phases 2-4).
