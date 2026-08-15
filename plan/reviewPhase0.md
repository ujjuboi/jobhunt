# Review — Phase 0 Scaffold

Date: 2026-08-15
Scope: Phase 0 deliverables in `jobhunt/` (per PLAN.md §4 Phase 0)

## Findings

### High severity

1. **Empty declared dependencies.** `jobhunt/pyproject.toml:7` has `dependencies = []`, but Phase 0 requires `textual, openai, httpx, python-docx, pydantic, rich`. A fresh `uv sync` installs nothing.

2. **Unimportable package layout.** `pyproject.toml` uses `uv_build` src-layout (`src/jobhunt/`), yet `app/ agent/ config/ db/ models/ sources/` sit at the project root with no parent package, while `agent/__init__.py:7`, `db/__init__.py:9`, `sources/__init__.py:6` use relative imports (`from ..config import …`, `from ..models import …`). These raise `ImportError: attempted relative import beyond top-level package`. Only `config/` and `models/` import standalone.

### Medium severity

3. **`smoke.py` misses the key Phase 0 checks.** It tests models list, embeddings, and a plain chat completion — but not tool-call round-trip nor `response_format={"type": "json_object"}` (the two checks that de-risk Qwen3 tool-call reliability). The structured-JSON call exists only in `agent/__init__.py:93-102` and is untested.

4. **`app.tcss` missing.** `app/__init__.py:13` sets `CSS_PATH = "app.tcss"`; the file does not exist. Textual fails the stylesheet read and aborts TUI startup.

### Low severity

5. **Hardcoded API key `'4526'`** in `config/__init__.py:29,37` and `smoke.py:23` — violates PLAN.md §2 ("Never hardcoded in the repo"). Env override is also inverted: `settings.json`'s `api_key` wins over `OMLX_API_KEY`, but the plan says the key is "overridable via `OMLX_API_KEY`".

6. **`smoke.py` re-implements config loading** (`smoke.py:13-23`) instead of importing `config.load_omlx_settings()`, so the config reader is never exercised and the two copies can drift.

7. **Console script is a placeholder.** `pyproject.toml:10` points at `src/jobhunt/__init__.py:main` ("Hello from jobhunt!"). The TUI lives in `app/__init__.py` and is only runnable via its `__main__` block.

8. Minor: `basic_smoke.py` is redundant with `smoke.py` and unreferenced; `smoke.py:25` prints the API key prefix.

## Fix plan

Decision (user): **keep src-layout** — move the six root modules under `src/jobhunt/`.

1. **Restructure to src-layout**
   - Move `app/ agent/ config/ db/ models/ sources/` → `src/jobhunt/`
   - Result: `src/jobhunt/{app,agent,config,db,models,sources}/__init__.py`; relative imports resolve.
   - `smoke.py` stays at project root and imports `jobhunt.*` (works via editable install).

2. **`pyproject.toml`**
   - `dependencies = ["textual", "openai", "httpx", "python-docx", "pydantic", "rich"]`
   - `[project.scripts] jobhunt = "jobhunt.app:main"`

3. **`config/__init__.py`**
   - Remove `'4526'` fallbacks (lines 29, 37); raise a clear error when no key is configured.
   - `OMLX_API_KEY` / `OMLX_BASE_URL` take precedence over `settings.json`.

4. **`app/__init__.py`**
   - Add `main()` that runs `JobHuntApp()`.
   - Add minimal `src/jobhunt/app/app.tcss` (CSS_PATH resolves relative to the app module).

5. **`smoke.py`**
   - Import `config.load_omlx_settings()`.
   - Add tool-call round-trip and structured JSON (`response_format={"type":"json_object"}`) checks.
   - Stop printing the API key prefix.
   - Delete `basic_smoke.py`.

6. **README.md** — update quick-start to `uv sync`, `uv run jobhunt`, `uv run python smoke.py`.

7. **Verify** — `uv sync`; `uv run python smoke.py` (oMLX running); `uv run jobhunt` launches the TUI.

## Round 2 (2026-08-15)

Round-1 fixes applied at the repo root (`pyproject.toml`, `smoke.py`, `src/jobhunt/`). Fixed since round 1: deps populated, hardcoded key removed (env precedence now correct), `app.tcss` exists, `jobhunt:main` runs the TUI, key printing removed, stale root module dirs gone. Re-review findings:

### High severity

9. **`import jobhunt` fails — `events.Button.Pressed` doesn't exist.** `src/jobhunt/app/__init__.py:38` annotates the handler `event: events.Button.Pressed`, but `textual.events` has no `Button` (annotations are evaluated at definition time). Because `src/jobhunt/__init__.py:4` eagerly imports `.app`, the whole package is unimportable → breaks the `jobhunt` console script and `import jobhunt` (verified `AttributeError`).

10. **Root `pyproject.toml` build fails / package not discoverable.** `readme = "README.md"` (line 12) but no root README exists → setuptools metadata error. Build backend switched to setuptools but there is no `[tool.setuptools]` config to map the `src/` layout, so the `jobhunt` package may not be discovered.

11. **`smoke.py` still misses the Phase 0 risk checks.** No tool-call round-trip test. The structured-JSON check (`smoke.py:96-107`) is wrapped in `try/except` that prints "may be expected" and the function still returns `True` / exits 0 → silent pass on the exact risk PLAN.md §5 flags. Also re-implements config loading (returns a dict, diverging from `OEMLXSettings`).

12. **No root `.gitignore` / `.python-version`.** Root tree has no ignore rules (only nested `jobhunt/.gitignore`), so `git add .` would stage `__pycache__`, `.venv` (~68MB), outputs, etc. No `uv.lock` (uv never run).

13. **Stale nested `jobhunt/` directory.** Duplicate project tree with the old bugs (empty deps, hardcoded `'4526'`, `api_key[:4]` print) and a README pointing at `cd jobhunt`. Delete it.

### Low severity

14. **Config loaded at import time with misleading error path.** `config/__init__.py:60` runs `load_omlx_settings()` at import; a missing key raises `ValueError` on plain `import jobhunt`. The raise inside the settings-file `try` (line 43) is caught by the broad `except` (line 46), printing "Could not load settings" even when the file loaded fine.

## Round 2 fix plan

1. **`app/__init__.py`** — fix the annotation to a valid type (`from textual.widgets import Button`; `event: Button.Pressed`), or drop it. Verify `import jobhunt`.
2. **Root `pyproject.toml`** — add `[tool.setuptools]` `package-dir = {"" = "src"}` + `packages.find.where = ["src"]`; add root `README.md`.
3. **`smoke.py`** — `from jobhunt.config import load_omlx_settings`; add tool-call round-trip (`tools=[...]`, parse `tool_calls`); make structured-JSON failure fail the run; exit 0 only when all checks pass.
4. **Root files** — add `.gitignore` (reuse nested `jobhunt/.gitignore`) and `.python-version` (`3.12`).
5. **Delete nested `jobhunt/`**.
6. **Config** — narrow the `except` and lazy-load (or make missing-key a deliberate import-time error).
7. **Environment + verify** — `brew install uv`; `uv sync`; `uv run python smoke.py` (oMLX up); `uv run jobhunt` launches TUI.

## Round 2 — execution log (2026-08-16)

All round-2 fixes applied and verified:

- `src/jobhunt/app/__init__.py` — annotation fixed to `Button.Pressed` (removed unused `events`/`Vertical`/`DataTable` imports). `import jobhunt` now succeeds.
- `pyproject.toml` — added `[tool.setuptools]` `package-dir = {"" = "src"}` + `packages.find.where = ["src"]`; root `README.md` added. `uv sync` installs `jobhunt==0.1.0` editable.
- `smoke.py` — uses `jobhunt.config.load_omlx_settings()`; added tool-call round-trip and structured-JSON checks that **fail** the run on error; no key printing.
- Root `.gitignore` (copied from old nested) and `.python-version` (`3.12`) added.
- Nested `jobhunt/` dir and stale empty root dirs (`agent/ app/ config/ db/ models/ resume/ sources/`) deleted.
- `uv` installed via Homebrew.

### Bugs found during execution

15. **oMLX key is under `auth.api_key`**, not top-level `api_key` — the config reader returned no key until `config/__init__.py` was updated to read `settings["auth"]["api_key"]` (with top-level fallback).

16. **oMLX serves its OpenAI-compat API under `/v1`**, and openai SDK 3.x no longer auto-appends `/v1` (hits `/models` → 404). `config/__init__.py` base_url now defaults to `http://127.0.0.1:8000/v1` and derives `http://{host}:{port}/v1` from `server` settings.

17. **Typo `omxl_settings` → `omlx_settings`** in `agent/__init__.py` import and usages (latent until round-2 import fix surfaced it).

### Verification results

- `uv sync` — OK (fresh venv, all deps, editable install).
- `import jobhunt` + all submodules — OK.
- `uv run python smoke.py` — **all passed**: models (6), embeddings round-trip (1024 dims), tool-call round-trip (`get_weather`), structured JSON (`colors` list).
- `uv run jobhunt` — TUI launches (header, welcome, nav buttons render; no stylesheet/import errors).

Deferred items (nav buttons hitting unregistered screens; LibreOffice for Phase 4) are recorded in
`plan/PLAN.md` (Phase 1 note + environment gaps line).
