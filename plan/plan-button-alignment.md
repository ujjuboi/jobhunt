# Plan: Align all action buttons to a single row on each page

**Scope:** Fix issue #5 — action buttons are scattered across different vertical
positions on various pages, creating an inconsistent and visually cluttered UI.
Wrap each page's buttons in a `Horizontal` container so they share a single row.

## Analysis

Every screen hands `ActionButton`s directly to its vertical `Container`
(default `layout: vertical`, see `textual/containers.py:22-28`), so multi-button
pages stack vertically:

- **Dashboard** — 3 quick-action buttons stacked (`dashboard.py:69-71`).
- **Resume** — 3 generation/save buttons stacked (`resume.py:49-51`).
- **Settings** — Login to LinkedIn inside the collapsible `#linkedin_block` and
  Save Config at the bottom (`settings.py:67`, `76`).
- **Chat / Search** — the Send / Search button sits on a row below its input.

Textual layout facts (verified against installed Textual 3.x):

- `Horizontal` defaults to `height: 1fr` (`containers.py:163-168`), so a shared
  row wrapper must override to `height: auto` or it collapses/expands the page.
- `Input` defaults to `width: 100%` (`_input.py:192`); inside a horizontal row it
  must be overridden to `width: 1fr` or it pushes the button off screen.
- `Button` is `height: auto`, `min-width: 16` (`_button.py:116-119`); three
  dashboard buttons fit even in the default `run_test` 80-col terminal (3×16 +
  margins ≈ 54).

## Step 1 — `src/jobhunt/app/components.py`: add shared `ButtonRow`

- Add `class ButtonRow(Horizontal)` next to `NavBar`.
- Document it as a single-row wrapper that lays a page's action buttons (and
  optional adjacent inputs) out on one line.
- Add `ButtonRow` to `__all__`.

## Step 2 — `src/jobhunt/app/app.tcss`: row styling

```css
ButtonRow {
    height: auto;
    margin-top: 1;
}
ButtonRow > Button {
    margin: 0 1 0 0;
}
ButtonRow > Button:last-child {
    margin-right: 0;
}
ButtonRow > Input {
    width: 1fr;
}
```

- Change `#chat_input`'s `margin-top: 1` to `margin-top: 0` (the `ButtonRow`
  owns the gap; otherwise the input's 3-line height is offset one line from the
  Send button). Keep the border/background rules and the placeholder styling.

## Step 3 — Wrap buttons in each screen (`_get_content`)

| Screen | Change |
|---|---|
| `dashboard.py` | `ButtonRow(search_jobs_btn, view_jobs_btn, generate_resume_btn)` |
| `search.py` | `ButtonRow(Input #search_input, ActionButton #search_button)` |
| `jobs.py` | `ButtonRow(ActionButton #refresh_button)` |
| `fit.py` | `ButtonRow(ActionButton #analyze_button)` |
| `resume.py` | `ButtonRow(generate_tailored_btn, generate_cover_letter_btn, save_outputs_btn)` |
| `chat.py` | `ButtonRow(Input #chat_input, ActionButton #send_button)` |
| `settings.py` | Move `#linkedin_login_btn` out of `#linkedin_block`; emit `ButtonRow(linkedin_login_btn, save_config_btn)` before `#settings_status`. |

All seven screens import `ButtonRow` from `..components`. All widget IDs are
preserved.

## Step 4 — Regression tests (`tests/test_app.py`)

- `test_dashboard_action_buttons_share_a_row`: mount at `(140, 40)`, assert the
  three quick-action buttons share one `region.y` and have increasing `region.x`.
- `test_chat_input_and_send_share_a_row`: navigate to chat, assert `#chat_input`
  and `#send_button` share one `region.y`.
- Existing tests (button clicks, `#linkedin_login_btn` flow, block toggle) pass
  unchanged — all IDs and `#linkedin_block` toggle semantics are preserved.

## Step 5 — `docs/SCREENS.md`

- Note the shared `ButtonRow` component under "Shared Chrome" and that action
  buttons are aligned on a single row per page.
- Note the Settings login button now sits in the bottom action row; the LinkedIn
  block shows the explanatory text and status only.

## Step 6 — Verify

- `uv run pytest` (baseline ~91 passed, 1 skipped; integration tests stay guarded).
- `python -m compileall src tests`.

## Guardrails

- Preserve all widget IDs (`#search_button`, `#analyze_button`, `#send_button`,
  `#linkedin_login_btn`, `#save_config_btn`, ...).
- Keep `#linkedin_block` display toggling and the `#chat_input` placeholder
  styling intact.
- Known tradeoff (per user choice): `#linkedin_login_btn` is now always visible
  on the Settings action row, not gated by the collapsible block.