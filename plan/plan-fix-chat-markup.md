# Plan: Fix chat rendering raw style markup (issue #4)

**Scope:** Fix issue #4 — chat messages display raw style markup like
`[bold blue]` instead of properly formatted text.

## Root cause

`ChatScreen` builds its transcript as a string full of Textual rich-markup tags
(`[bold blue]You:[/]`, `[green]Agent:[/]`, `[red]Error:[/]`,
`[dim]Thinking...[/]`) but renders it through `ScrollableTextWindow`, which is a
`TextArea`. In Textual 8.2.8, `TextArea` renders **plain text only** (no
`ContentType.rich_markup` support), so the literal tags show verbatim
(`chat.py:45,81,94`).

Design:

- **Fix the chat transcript widget, not the shared `ScrollableTextWindow`.** The
  other consumers (`#search_results`, `#resume_preview`) feed untrusted plain
  text (job descriptions, generated cover letters) that can legitimately contain
  `[...]`; switching the shared `TextArea` to markup rendering would break those
  screens.
- **Use `RichLog`** (`textual.widgets.RichLog`) for `#chat_messages`: renders
  `Text.from_markup()` when `markup=True`, auto-scrolls to the end, and is
  read-only by design — matches the chat use case exactly. `wrap=True` for long
  LLM lines.
- **Re-render the whole transcript on each update** (`clear()` + `write()`) —
  the raw markup string stays as the single source of truth on the screen.

## Step 1 — `src/jobhunt/app/screens/chat.py`

- Import `RichLog` from `textual.widgets`; drop the now-unused
  `ScrollableTextWindow` import (the `components` import keeps `ActionButton`).
- `_get_content()`: `RichLog(id="chat_messages", markup=True, wrap=True)` —
  **preserve the `#chat_messages` id** (AGENTS.md CRITICAL).
- Add a private `_render_transcript()` helper: `query_one("#chat_messages",
  RichLog)` → `clear()` → `write(self.transcript)`.
- Replace the three `text_area.text = ...` sites (`chat.py:94,118,125`) with
  `self._render_transcript()`. Keep the existing transcript-string APIs
  (`_append_transcript`, `_start_streaming_line`, `_streaming_line`,
  `_finish_streaming_line`) intact — the markup stays in `self.transcript`; only
  the rendering path changes.
- Update the module/`_get_content` docstrings to note the markup-rendering log.

## Step 2 — Tests

Existing tests read `query_one("#chat_messages").text`, which `RichLog` does not
expose; the plain-text source already lives on the screen as
`app.screen.transcript` (used at `test_chat_streaming.py:47`).

- `tests/test_chat_streaming.py:50,78` and `tests/test_app.py:141,167`: read
  `app.screen.transcript` instead of `#chat_messages.text`. Existing assertions
  (`"You:"`, `"canned reply"`, `"Hello world!"`, `"Error:"`,
  `"Thinking..." not in`) still hold on the raw source string.
- Add a rendering regression test (`tests/test_chat_streaming.py`): after a
  round trip, read the `#chat_messages` widget's rendered lines
  (`RichLog.lines`, joining each strip's `segment.text`) and assert the rendered
  text contains the words but **no literal markup tokens** (`"[bold"`,
  `"[green"`, `"[/]"`, `"[dim"` not present), with a `pilot.pause()` before
  reading so deferred writes flush. Baby-check: asserting on `Text.from_markup`
  of the transcript string alone would pass pre-fix — assert on the widget.
- Add a second regression test sending message text containing brackets
  (`check [/] dir`): assert the agent still completes (no `MarkupError` wedge)
  and the rendered output shows the literal typed text.

## Step 3 — Verify

- `uv run pytest` (baseline ~91 passed, 1 skipped).
- `python -m compileall`.

## Guardrails

- Preserve widget IDs (`#chat_messages`, `#chat_input`, `#send_button`).
- Other screens keep `ScrollableTextWindow` (plain-text data with possible
  `[...]` content) — untouched.
- User and agent message text is escaped (`rich.markup.escape`) before being
  embedded in the transcript, so bracket characters in message content render
  literally and can never be read as markup (which would otherwise consume
  balanced pairs like `df[col]` or raise `MarkupError` on an unmatched `[/]`).
- Streaming/fallback/error paths (incl. the `[error: see logs]` marker, never
  appended to `self.messages`) unchanged.
- Google-style docstrings; no new comments.