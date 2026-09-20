# Plan: Global active-tab state + shared NavBar component

**Scope:** Fix issue #2 — the active tab highlight does not update when switching
between Search Jobs, View Jobs, and Generate Resume on the home screen.

## Analysis

All navigation flows through one choke point: `JobHuntApp.switch_screen()`
(`app/__init__.py`; called from `base.py:72` and `dashboard.py:83-87`), plus the
initial `push_screen("dashboard")` in `on_mount`. There is currently no
active-tab styling at all — the nav bar is built inline in
`BaseScreen.compose()` with no state and no highlight.

Design:

- **Global tab state**: `JobHuntApp.active_tab` — single source of truth,
  updated in one place via an overridden `switch_screen()` (plus a seed for the
  initial dashboard push).
- **Shared component**: `NavBar(Horizontal)` in `app/components.py`, imported by
  `BaseScreen.compose()` so every page renders the same navbar. Each `NavBar`
  reads `self.app.active_tab` at mount and applies an `active` class to the
  matching `#*_btn`.
- **Why the visible navbar is always correct**: the navbar shown on screen X
  belongs to screen X (Textual per-screen widget trees — an App-level nav bar
  vanishes after the first switch, see `docs/SCREENS.md:22-23`). Because
  `active_tab` always equals the currently visible screen (set by
  `switch_screen` before the new screen displays), each navbar highlights the
  right tab for nav clicks *and* home-screen quick actions.

## Step 1 — `src/jobhunt/app/__init__.py`: global state + navigation handler

- In `__init__`: `self.active_tab = "dashboard"`.
- Override `switch_screen(self, screen: Screen | str)`:
  set `self.active_tab = screen if isinstance(screen, str) else screen.name`,
  then `return super().switch_screen(screen)`.
- In `on_mount`, set `self.active_tab = "dashboard"` just before
  `push_screen("dashboard")` so the dashboard navbar highlights on first render.

## Step 2 — `src/jobhunt/app/components.py`: `NavBar` shared component

- Move the `NAV_BUTTONS` list from `BaseScreen` into the component:
  `(button_id, screen, label)`.
- `NavBar(Horizontal)` with `id="nav_bar"` (preserves `#nav_bar`; nav buttons
  keep `#*_btn` ids).
- `compose()` yields plain `Button` (nav buttons stay plain `Button`, not
  `ActionButton` — see `components.py:94-96`), gating the Search button on
  `keyword_search_available()` (import from `...config.user_config`).
- `on_mount()` → `_apply_active()`: add `active` class to the button whose
  screen equals `self.app.active_tab`, remove it from the others.
- Expose `set_active(screen_name)` to re-apply classes in place.
- Add `NavBar` to `__all__`.

## Step 3 — `src/jobhunt/app/screens/base.py`: use the component

- Delete the inline nav-button construction and the class-level `NAV_BUTTONS`.
- `compose()`: `yield NavBar()` (import from `..components`).
- `on_button_pressed()`: resolve the target screen via `NavBar.NAV_BUTTONS`;
  switching behavior unchanged.

## Step 4 — `src/jobhunt/app/app.tcss`: active-tab styling

Add (nav bar background is `$primary`):

```css
#nav_bar Button.active {
    background: $background;
    color: $primary;
    text-style: bold;
}
```

## Step 5 — `tests/test_app.py`: regression coverage

Add `test_active_nav_highlight_follows_screen`:

- Mount → assert `app.active_tab == "dashboard"` and `#dashboard_btn` has the
  `active` class.
- Click `#chat_btn` → assert `app.active_tab == "chat"` and the chat screen's
  `#chat_btn` carries `active`.
- Return to dashboard, click `#search_jobs_btn` (patch
  `SearchScreen._async_browse`, as in the existing
  `test_dashboard_quick_actions_switch_screens`) → assert
  `app.active_tab == "search"` and `#search_btn` carries `active`.

Existing tests are unaffected (all `#nav_bar` / `#*_btn` ids preserved).
Use `run_test(size=(140, 40))` so buttons stay on-screen.

## Step 6 — `docs/SCREENS.md`

Update the navigation-bar section: shared `NavBar` component, global
`app.active_tab`, active-tab highlight behavior.

## Step 7 — Verify

- `uv run pytest` (baseline ~91 passed).
- `python -m compileall`.

## Guardrails

- Preserve widget IDs (`#nav_bar`, `#*_btn`); never rename during the refactor.
- Nav buttons become plain `Button`, matching the intended component design.
- No secrets in scope.