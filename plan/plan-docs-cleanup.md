# Plan: Docs directory + cleanup of implemented plans

**Scope:** `plan/` cleanup, new `docs/` directory, stale reference fixes.

## Step 1 — Delete fully implemented plans

`plan/issue8-refactor-plan.md`, `plan/reviewPhase0.md`, `plan/reviewPhase1.md`,
`plan/reviewPhase4.md`, `plan/reviewPhase6.md`, `plan/reviewPhase7.md`.

All verified implemented (see analysis): components/docstrings/rename issue #8;
Phases 0, 1, 4, 6, 7 reviews with every finding/fix applied in the working tree.
Recoverable via git history.

## Step 2 — Trim `plan/PLAN.md` to the stretch item

All milestones (Phases 0–7) are delivered. Replace PLAN.md with a short stub
preserving the single not-implemented item:

- Stretch: reranker (`bge-reranker-v2-m3`) via `/v1/rerank` to refine the final
  top-k ordering of the fit-scoring pipeline (`src/jobhunt/scoring/__init__.py`).

## Step 3 — Create `docs/` (feature documentation, from the plans)

Multi-file per topic:

- `docs/FEATURES.md` — overview, full feature list across all phases, source
  layout, dev commands (uv scripts, tests, smoke). Entry point.
- `docs/SCREENS.md` — the 7 TUI screens + persistent nav + Phase 7 UX wiring
  (profile auto-sync, Jobs→Resume job selection, Save to Outputs, live Dashboard
  counts, multi-source Search).
- `docs/AGENT_LLM.md` — ToolRegistry (7 tools), JobHuntAgent, streaming chat,
  retry/timeouts/logging, model resolution precedence.
- `docs/SCORING.md` — embedding client, vector cache, cosine dedupe,
  hybrid/embedding/llm modes, LLM confirm + score normalization, similar-jobs.
- `docs/RESUME.md` — profile parsing, DB profile sync, LLM tailoring with
  heuristic fallback, DOCX rebuild → PDF, cover letters, outputs layout.
- `docs/SOURCES.md` — Greenhouse/Lever/Ashby (API), Indeed/LinkedIn (Playwright,
  opt-in), LinkedIn browser login, per-source company config, keyword vs board
  sources, multi-source search + dedupe.
- `docs/DATABASE_AND_CONFIG.md` — SQLite repository/schema, config.toml +
  validation, env overrides, log/config paths.

## Step 4 — Fix stale `plan/PLAN.md` references

- `README.md:126` — point "See `plan/PLAN.md`" at `docs/FEATURES.md`.
- `src/jobhunt/sources/indeed.py:4` — reword the PLAN.md reference to
  `docs/SOURCES.md`.
- `src/jobhunt/sources/linkedin.py:4` — reword "Implements the Phase 5 plan"
  (Phase 5 is now a delivered feature).

No changes needed in `USER_GUIDE.md` / `ADAPTERS.md` (no plan references).

## Step 5 — Verify

- `rg` shows zero references to deleted plan paths.
- New `docs/` files render as valid markdown.
- Only doc/comment-level edits outside `docs/`/`plan/`.

## Guardrails

- Do not pre-announce anything; no runtime behavior changes.
- No secrets in scope.