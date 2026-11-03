# Plan: Issue #12 — Context menu on job row click

**Status:** IMPLEMENTED (enhancement)
**Link:** [#12](https://github.com/anomalyco/opencode/issues/12)
**Resolution:** Floating popup menu anchored at the click position, dismissed with
Escape or a click elsewhere (user-approved, 22 Oct 2026)

## Problem

Clicking a job row in the Jobs screen did nothing useful: the screen only wrote
`"Selected job ID: <id>"` into the status line. There was no way to read a job's
posting, to ask the agent about it, or to open the posting in a browser.

## Root cause

The Jobs screen handled `DataTable.RowSelected`, but Textual's `DataTable` defaults
to `cursor_type="cell"`. In cell-cursor mode the first click only moves the cursor
and `RowSelected` is never posted (it is posted for Enter, or for a *second* click on
the already highlighted cell). The handler was therefore dead code — verified in
Textual 8.2.8 by clicking a row and observing that `app.selected_job_id` stayed
`None`.

Textual 8.2.8 also ships no `Menu`/`ContextMenu` widget, so the menu had to be
built from the shared components.

The Fit screen had the same dead `RowSelected` handler, and its `#fit_detail` pane
was a `Static` squeezed to a single line by the layout, so the breakdown was
invisible even when it was rendered.

## Changes

### 1. `src/jobhunt/app/components.py` — two shared components

- `RowClickTable(DataTable)`: posts a `RowClicked` message (row key, row index, and
  the click's screen coordinates) for every click on a data row. The message is
  posted from the public `on_click` handler on purpose: Textual resolves handlers
  per class in the MRO and prefers the private `_on_click` only *within* the same
  class, so the subclass handler runs first and `DataTable._on_click` still moves
  the cursor afterwards.
- `ContextMenu(Vertical)`: a floating menu of actions. It is an absolutely
  positioned overlay (`position: absolute; overlay: screen`), so it does not take
  part in the parent's layout and is painted on top of the table.
  `open_at(x, y, title)` converts screen coordinates into the offset the parent
  expects, `close()` hides it, `contains_point()` tells a click on a menu item
  apart from a click elsewhere, and `_keep_inside_screen()` shifts the menu up/left
  when it would overflow the terminal. `Escape` posts a `Dismissed` message.

### 2. `src/jobhunt/app/screens/jobs.py`

- `#jobs_table` is now a `RowClickTable`.
- New `#job_details` (a `ScrollableTextWindow`) shows the job card below the table:
  title, company, id, posting date, location, salary, remote flag, source, URL, and
  the full description.
- New `#job_context_menu` (`ContextMenu`) with `#job_menu_title`, `#view_details_btn`,
  `#chat_job_btn`, and `#apply_btn`.
- `on_row_click_table_row_clicked` opens the menu at the click position;
  `on_data_table_cell_selected` does the same for keyboard selection (anchored to
  the selected row).
- The three actions: *View Details* fills `#job_details`; *Chat About This Job*
  hands the job to the Chat screen and switches to it; *Apply* opens the posting in
  the default browser from a worker thread (`webbrowser.open` blocks).
- `on_click` dismisses the menu when the user clicks outside of it.
- `on_screen_resume` now calls `super().on_screen_resume()` so the nav bar keeps
  the correct highlight (the override used to skip the base implementation).

### 3. `src/jobhunt/app/screens/chat.py`

- `build_job_context(job)` renders a job for the model (metadata plus a
  description truncated to `MAX_JOB_CONTEXT_CHARS`).
- `set_job_context(job)` appends that text as a `system` message, echoes a
  "Job context" line in the transcript, and pre-fills `#chat_input` with
  `JOB_CONTEXT_PROMPT` ("What should I know about this job?"). The screen does not
  have to be open yet: the pending context is applied on mount.

### 4. `src/jobhunt/app/screens/fit.py`

- `#fit_table` is now a `RowClickTable` and `#fit_detail` a `ScrollableTextWindow`.
- Clicking (or keyboard-selecting) a row renders the score, explanation, matched
  and missing skills, and the suggested resume bullets; the clicked job also
  becomes `app.selected_job_id`.
- `on_screen_resume` calls `super().on_screen_resume()` (same nav-bar fix).

### 5. `src/jobhunt/app/app.tcss`

- `#jobs_table, #fit_table { height: 1fr; min-height: 4; }` — the tables flex so
  the panes below them stay on screen.
- `#job_details { display: none; height: 12; max-height: 40%; }` — hidden until a
  job is viewed, then a bounded slice of the page.
- `#fit_detail { height: 12; max-height: 40%; }` — the breakdown is readable.

### 6. `tests/test_jobs_row_actions.py` — 9 new tests

Menu opening, the details card, the chat hand-off, opening the application URL, the
missing-URL report, Escape dismissal, click-away dismissal, the menu staying inside
the screen, and the Fit breakdown on click.

## Verification

- `uv run pytest` — 185 passed, 1 skipped (the integration test stays opt-in).
- `uv run python -m compileall src`
- Manual probes: the menu renders above the table (compositor layer check), is
  anchored at the click position, is moved up when a bottom row is clicked, and the
  click-away/Escape paths close it.

## Out of scope

- No widget-id renames; `#jobs_table`, `#jobs_status`, the pagination widgets, and
  `#fit_table` keep their ids.
- The Dashboard screen still overrides `on_screen_resume` without calling the base
  implementation (same nav-highlight nit, untouched by this issue).
