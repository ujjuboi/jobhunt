# Plan: Deterministic PR Checker + Provider Fallback

**Status:** PLAN
**Trigger:** CI free-tier quota exhaustion; PR #30.
**Scope:** Three phases — deterministic convention checker (Phase A), docs-in-sync rules (Phase B), free LLM provider fallback (Phase C).

---

## Problem

The PR Review workflow (`scripts/pr_review.py` driven by GitHub Actions) fails every run on the current branch with:

```
provider.free-limit: Free usage limit reached.
```

The error arrives ~5 s after session creation. Root cause: OpenCode's free tier is metered per account **and** per network. GitHub-hosted runners share a small pool of egress IPs, so the free quota is exhausted by other jobs on the same address. Switching models or increasing step budgets does not help.

Secondary constraint: on `pull_request` events from forks, `GITHUB_TOKEN` is read-only (max `read`). The review API returns 403 — no inline comments can be posted regardless of model availability.

**Conclusion:** any reviewer that must be always available in CI cannot depend on a model, free tier, or a write-scoped token.

---

## Why the "new mode" doesn't fix it

OpenCode 2.x introduced **Code Mode** (`execute`): the model writes one small JavaScript program that batches many tool calls into a single step. This cuts steps, tokens and latency — helpful for RPM/TPM rate limits, but it does not bypass hard quota exhaustion, because the first model request is what gets rejected.

Enabling Code Mode for the reviewer would require granting `execute` permission to an agent that reads untrusted PR text, which is a prompt-injection escalation path we deliberately closed (`.opencode/agents/pr-reviewer.md` denies `execute`). Recommendation: leave it denied.

---

## Solution: Three-phase approach

### Phase A — Convention checker (blocking, no model)

A stdlib-only checker encoding `AGENTS.md` and `docs/` as rules. No model, no network, no secrets, ~5 seconds.

**Files created:**
- `scripts/pr_check.py` — rules engine, reporting, CLI (stdlib only: `ast`, `re`, `tomllib`, `subprocess`, `argparse`)
- `tests/test_pr_check.py` — one positive/negative fixture per rule, parser tests, new-debt filtering test
- `.prcheck.toml` — suppression config: `disable`, `allow` (path/id patterns)

**Features:**
- `--base <sha> --head <sha>`, `--pr-number N`, or `--all` for full-repo runs
- New-debt-only filtering: rules run against base and head trees; only violations whose key `(rule, path, symbol)` is new are reported. Existing debt (`except: return None` in `profile_parser.py`, `except OSError: pass` in `logging.py`) does not block.
- Two severities: `blocking` (objective, CI fails) and `advisory` (informational).
- Deterministic output: findings sorted by `(path, line, rule)`, fixed message strings, no timestamps — snapshot-testable.
- Inline GitHub PR review comments via the existing payload builder. On a read-only token, degrades to `$GITHUB_STEP_SUMMARY` with a clear note (does not fail).
- Suppression: `# prcheck: ignore JH00X <reason>` on the line or above. Reason string is mandatory and every suppression is echoed into the review body.

**Rule catalogue (Phase A: JH001–JH012)**

| Rule | Source | Severity | Detection |
|---|---|---|---|
| `JH001` print-in-library | AGENTS.md · Logging | blocking | `print`/`pprint` call in `src/**` outside `cli.py` |
| `JH002` swallowed-error | AGENTS.md · Errors | blocking | handler body is only `pass` or `return []/None/False`; bare `except Exception` with no log/raise |
| `JH003` unguarded-agent | AGENTS.md · Agent pattern | blocking | `self.agent.<...>` in `app/**` not reached through `_require_agent()` |
| `JH004` compose-in-screen | AGENTS.md · TUI screens | blocking | `BaseScreen` subclass other than `BaseScreen` defines `compose()` |
| `JH005` chat-raw-error | AGENTS.md · Chat | blocking | `self.messages` append whose value interpolates an exception/error object |
| `JH006` blocking-io-in-async | AGENTS.md · Background work | blocking | `async def` containing `time.sleep`, `requests.*`, `subprocess.run`, or direct `self.database` I/O |
| `JH007` module-logger | AGENTS.md · Logging | advisory | `getLogger(<literal>)` instead of `__name__` in `src/**` |
| `JH008` abbreviated-names | AGENTS.md · Naming | advisory | new parameter/target named `db`, `e`, `exc`, `err`, `cfg`, `msg`, `req`, `res`, `tmp`, `tbl` |
| `JH009` db-path-kwarg | AGENTS.md · Naming | blocking | `JobHuntDB(db_path=…)` or `.get_db(db_path=…)` |
| `JH010` screen-db-kwarg | AGENTS.md · Tests | advisory | screen built with `db=` instead of `database=` |
| `JH011` fixed-sleep-tests | AGENTS.md · Tests | advisory | `time.sleep(` in a new test function body |
| `JH012` integration-marker | AGENTS.md · Commands | blocking | new test touching source adapters/oMLX/settings/config without `@pytest.mark.integration` |

### Phase B — Docs-in-sync rules

Enforce that code matches documentation. Verified against the current tree: all 50 widget `#ids` in `docs/SCREENS.md` resolve to code, and the five documented DB tables match `CREATE TABLE` exactly. Starting from zero findings.

**Rules added:**

| Rule | Source | Severity | Detection |
|---|---|---|---|
| `JH013` doc-widget-id | docs/SCREENS.md | blocking | every `#id` documented in `docs/SCREENS.md` absent from `app/**`; ids referenced by tests absent from source |
| `JH014` doc-db-schema | docs/DATABASE_AND_CONFIG.md | blocking | `CREATE TABLE` column sets vs doc's markdown tables differ |
| `JH015` doc-db-methods | docs/DATABASE_AND_CONFIG.md | blocking | documented `JobHuntDB` method missing from class |
| `JH016` doc-source-adapters | docs/SOURCES.md | advisory | documented adapter module / factory key missing from `sources/__init__.py` |
| `JH017` doc-scoring-weights | docs/SCORING.md | advisory | weight names in docs vs scoring constants |
| `JH018` agent-read-only | docs/PR_REVIEW.md | blocking | `pr-reviewer` agent drops an `edit`/`shell`/`webfetch` deny |
| `JH019` workflow-safety | docs/PR_REVIEW.md | blocking | `pull_request_target`, unpinned action, secret interpolated into `run:`, permissions broader than needed |
| `JH020` script-entrypoints | pyproject.toml | advisory | `[project.scripts]` target `module:attr` references missing |
| `JH021` docstrings | AGENTS.md · Docstrings | advisory → blocking later | new public module/class/function without docstring; missing `Args:`/`Returns:`/`Raises:` where AST says they apply |

### Phase C — Free LLM provider fallback (best effort)

A keyed provider chain that keeps the LLM review working when a free tier is available, while failing gracefully when it is not.

**Files modified:**
- `scripts/pr_review.py` — add `--provider {opencode|gemini|openrouter|local}`, `--api-key-env`, `--preflight` mode

**Provider options (ranked by CI reliability):**

| Provider | Cost | CI compatibility | Notes |
|---|---|---|---|
| Local oMLX | free | no (must run locally) | `uv run python scripts/pr_review.py --pr-number N --provider local` |
| Gemini API key | free tier per-project | yes (secret in CI) | OpenAI-compatible endpoint; not shared-runner-fragile |
| OpenRouter free models | ~50 req/day free | yes (secret in CI) | e.g. `nvidia/nemotron-3.5-lightning:free` (1M context), `recursive/flint-v1.0:free` |
| Groq / Cerebras | free tier | yes (secret in CI) | Different limits; same API-key pattern |

**`--preflight` mode:** exits `0` when a provider is ready, exits `78` (neutral/skip) when no key is configured, allowing the job to be skipped without failing.

**GitHub Actions secret limitation:** secrets cannot be read in `if:` conditionals. The fix: map the secret to a job-level `env:` variable, then gate with `if: env.GEMINI_API_KEY != ''`.

---

## Diff parser extension (prerequisite)

The existing `parse_unified_diff` in `scripts/pr_review.py` only tracks new-side (added/context) lines. Two extensions are needed:

1. **Added-line text.** Store the actual content of added lines per file so rules can inspect code (e.g., to check for `print(` without re-reading the file).
2. **`removed_lines` on `DiffHunk`.** Track deleted-line ranges and the left-file context so a finding on a deleted line can be placed on `LEFT` side.
3. **`PlacedFinding.side: str`.** Currently hardcoded to `"RIGHT"`; allow `"LEFT"` for deleted-line findings.

These changes are additive and backward-compatible. The 576-line existing test file (`tests/test_pr_review.py`) pins the current behaviour; the extension adds tests on top.

---

## CI workflow restructure

Current: a single `review` job that installs OpenCode, runs `pr_review.py`, and publishes the step summary.

New: three jobs:

| Job | Required | Secrets | Timeout |
|---|---|---|---|
| `conventions` | yes | none | 30 min |
| `tests` | yes | none | 15 min |
| `llm-review` | no (`continue-on-error`) | gated by secret env var | 12 min |

The `PR Review` required check then means "conventions + tests passed". The model review is optional.

---

## Build order

1. **Parser groundwork** (`scripts/pr_review.py`). Extend diff parser to keep added-line text, track `removed_lines`, support `side: "LEFT"`. Add tests. Keep existing 576-line test file green.
2. **`scripts/pr_check.py`**. Rules engine, CLI, new-debt filtering, deterministic sort, payload builder reuse. Structure: `CheckFinding` dataclass, `RULES` registry, `run_checks(base_root, head_root, files, config) -> list[CheckFinding]`.
3. **Rules JH001–JH012** (Phase A). AST-based: `print` in library, swallowed errors, unguarded agent, compose-in-screen, chat raw errors, blocking I/O, abbreviated names, wrong kwarg names, integration marker. One positive/negative fixture per rule.
4. **Rules JH013–JH021** (Phase B). Docs-sync: widget ids, DB schema, DB methods, source adapters, scoring weights, agent read-only, workflow safety, script entrypoints, docstrings. Verify against current tree: all green.
5. **`.prcheck.toml`**. Suppression config with `disable`, `allow` patterns. Mandatory reason strings.
6. **`tests/test_pr_check.py`**. Fixtures per rule, parser tests (including deletions), new-debt filtering test, golden test on real repo (zero expected findings today), snapshot test of report ordering.
7. **Workflow split**. `conventions` → `tests` → `llm-review` gated. Update `docs/PR_REVIEW.md` to reflect two-tier architecture.
8. **Provider fallback**. Add `--provider`, `--api-key-env`, `--preflight` to `pr_review.py`. Document local oMLX usage.

---

## Honest coverage limits

The checker is a convention-and-drift gate. It will catch:

- `print` in library code, swallowed exceptions, unguarded agent access
- `compose()` on screens, blocking I/O in async functions, raw error injection into chat
- Renamed/removed widget IDs, DB columns or tables not in docs, documented methods missing
- Workflow safety regressions, abbreviated naming

It will **not** catch logic bugs. Semantic bug review still needs a model, which is why the LLM job stays as an optional, non-blocking layer.

---

## Verification

At the end of implementation:

1. `uv run pytest` — baseline ~185 passed, 1 skipped, plus the new checker tests
2. `python -m compileall src scripts` — passes
3. `uv run python scripts/pr_check.py --all` — reports zero blocking findings on the current tree
4. Dry run against PR #30 (`--pr-number 30 --head <sha>`) — produces expected findings, posts inline comments (same-repo branch), degrades to step summary on fork branches
5. `uv run python scripts/pr_review.py --provider local --pr-number 30` — works locally against oMLX
