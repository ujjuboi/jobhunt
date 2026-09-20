# Plan: Customize command palette + header trigger

**Scope:** Local tweaks to Textual's built-in command palette and header widget,
addressing issue #1 (visibility of the palette-trigger dot) and issue #13
(palette menu contents and ordering).

## Background

- The palette-trigger dot is Textual's `HeaderIcon` (default glyph `⭘`), rendered
  by the `Header()` yielded in `BaseScreen.compose()` (`src/jobhunt/app/screens/base.py:45`);
  clicking it opens the command palette. The footer `^P` is the built-in
  `ctrl+p` binding to `action_command_palette`.
- Palette contents come from `App.COMMANDS = {get_system_commands_provider}`
  (`SystemCommandsProvider`), which discovers via `App.get_system_commands()`:
  Theme, Quit, Keys, Maximize/Minimize (when a focused widget can maximize),
  Screenshot. Discovery is **sorted alphabetically by name**, so Quit is not last.
- Decision (recorded with user): restyle the header dot, keep the `⭘` glyph;
  provider lives in a new `src/jobhunt/app/palette.py`.

## Step 1 — Palette menu contents & ordering (issue #13)

- New file `src/jobhunt/app/palette.py`:
  - `JobHuntCommandsProvider(Provider)` mirroring `SystemCommandsProvider`'s
    `discover`/`search` logic (uses `self.matcher`, `matcher.highlight`), but
    **does not sort** — yields `self.app.get_system_commands(self.screen)` in
    the given order.
- `src/jobhunt/app/__init__.py` (`JobHuntApp`):
  - Add class var `COMMANDS = {JobHuntCommandsProvider}` (replaces the default
    system-commands provider).
  - Override `get_system_commands(screen)` to yield, in order: `Keys`, `Theme`,
    `Screenshot`, then `Quit` last — and **omit the Maximize/Minimize branch**.

Result: palette's initial list shows Keys → Theme → Screenshot → Quit at the
bottom; "Maximize" no longer appears.

## Step 2 — Header dot visibility (issue #1)

- `src/jobhunt/app/app.tcss`: add a `HeaderIcon` rule keeping the `⭘` glyph but
  enlarging its footprint/contrast:
  ```css
  HeaderIcon {
      width: 9;
      padding: 0 2;
      text-style: bold;
      background: $primary;
      color: $background;
  }
  ```
  (`$primary` matches the existing `#nav_bar` accent so header + nav read as one
  palette-trigger region.)

## Step 3 — Tests

- Unit test `JobHuntApp.get_system_commands(...)`: names are
  `["Keys", "Theme", "Screenshot", "Quit"]`; no `Maximize`.
- Unit test `JobHuntCommandsProvider.discover()` preserves that order (Quit last).
- No existing palette/header tests; existing widget IDs are untouched.

## Step 4 — Verify

- `uv run pytest` (baseline ~91 passed) stays green.
- `python -m compileall` over the changed modules.

## Guardrails

- No runtime behavior changes beyond palette contents/order and header styling.
- No widget-ID renames; `Header()`/`Footer()` stay in `BaseScreen.compose()`.
- No secrets in scope.