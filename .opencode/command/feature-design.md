---
description: Create a phase-aware implementation plan for a feature request or cited issue, following JobHunt's conventions. Usage: /feature-design <issue #N or short description>.
---

# Feature Design

Create an implementation plan for the requested feature, grounded in this repo's
conventions and existing architecture. The user cited: `$ARGUMENTS`.

If `$ARGUMENTS` is (or contains) an issue number (e.g. `#13`), pull the issue's
title/body with `gh issue view N` (fall back to the web fetch tool). If it is a
free-text description, treat that description as the requirement. If both are
given, reconcile them.

## Grounding

Before writing anything, research the codebase so the plan reflects reality:

1. Read `AGENTS.md` — commands, TUI screen conventions, agent (lazy) pattern,
   naming, code style, and test conventions. The plan must respect every
   "CRITICAL" rule (e.g. never rename widget IDs, use WorkerMixin, delegate to
   `super().on_button_pressed(...)` first).
2. Read `README.md` and `docs/FEATURES.md` (the project map; README points
   there for full layout and phase history). Note which module the feature
   belongs to and which existing patterns it should reuse.
3. Inspect the modules the change will touch (e.g. `src/jobhunt/app/*`,
   `src/jobhunt/db/__init__.py`) so each step names real files and real
   identifiers, not invented ones.
4. Check `plan/` for any unfinished sibling plans that overlap; flag overlap in
   the plan rather than duplicating.

## Output

Write the plan to `plan/plan-<feature-slug>.md` following the repo's plan
format exactly (`# Plan: <title>`, a `**Scope:**` line, `## Step N — ...`
sections, and a `## Guardrails` section). Model it on
`plan/plan-docs-cleanup.md`.

The plan must include:

- **Assumptions & decisions** — state the feature's acceptance criteria derived
  from the issue/description, and record any scope decisions made to keep it
  minimal.
- **Minimal-diff bias** — prefer the smallest change that meets the criteria:
  reuse existing helpers/components (`app/components.py`, db repository methods,
  config reader) instead of adding parallel ones. Only create a new module when
  the change is a distinct concern; then create a new file rather than bloating
  an existing one.
- **Phase splitting** — if the implementation touches **15 or more files**, do
  not write a single flat step list. Split the plan into ordered **Phases**,
  each with its own goal, file list, and verification, so each phase is an
  individually shippable unit with tests staying green at every boundary.
- **Tests** — every step names the tests that will prove it (construct screens
  with `ScreenName(database=...)`, patch `jobhunt.app.components.JobHuntAgent`,
  poll for status after workers settle). If none exists, say so.
- **Verification** — end with the repo's check commands (`uv run pytest`,
  `python -m compileall`; `uv run jobhunt-smoke` only if oMLX is involved).
- **Guardrails** — no widget-ID renames, no behavior changes outside scope, no
  secrets, doc/comment-level edits only where needed.

Constraints: never implement code in this step — the deliverable is the plan
file only. Do not edit unrelated files. Keep the plan concrete enough that a
follow-up session can execute each step without re-researching.