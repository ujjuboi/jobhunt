# Plan: Issue #3 — Visible placeholder in chat history prompt input

**Status:** OPEN (enhancement)
**Link:** [#3](https://github.com/anomalyco/opencode/issues/3)
**Resolution:** Accent palette (user-approved, 21 Sep 2026)

## Problem

Users cannot easily tell where to type their prompt in the chat history, as the
input field lacks a visually distinct placeholder.

`#chat_input` already sets `placeholder="Type your message..."`
(`src/jobhunt/app/screens/chat.py:46`), but Textual's default styles render the
placeholder in `$text-disabled` (very dim) on a `$surface` background with a
blurred border — indistinguishable from the transcript (`#chat_messages`) above
it. The fix is CSS, **not** code changes to widget ids or behaviour.

## Root cause

Textual 8.2.8 `Input` default CSS:

```css
Input {
    background: $surface;
    border: tall $border-blurred;
    ...
    &>.input--placeholder, &>.input--suggestion {
        color: $text-disabled;
    }
}
```

Verified in-memory that both of these app-level overrides cleanly win the CSS
cascade:
- `#chat_input { border: tall $secondary; background: $panel; }`
- `#chat_input > .input--placeholder { color: $primary; text-style: italic; }`

## Changes

### 1. `src/jobhunt/app/app.tcss`

Append rules for the chat input:

```css
/* Make the chat input area visually distinct from the transcript. */
#chat_input {
    margin-top: 1;
    background: $panel;
    border: tall $secondary;
    padding: 0 2;
}

#chat_input > .input--placeholder {
    color: $primary;
    text-style: italic;
}
```

- `border: tall $secondary` + `$panel` background sets the input apart from the
  transcript above it.
- `margin-top: 1` adds separation from `#chat_messages`.
- `$primary` (blue) + italic makes the placeholder prompt visibly contrasting.

### 2. `tests/test_app.py` — regression test

Follow the existing chat-navigation pattern (`await pilot.click("#chat_btn")`),
then assert on the chat screen:

- `query_one("#chat_input", Input).placeholder == "Type your message..."` —
  locks in the visible prompt text.
- `input.get_component_rich_style("input--placeholder")` resolves to
  `color is not None` and `italic is True` — proves the styled-placeholder
  override is applied (Textual's default is non-italic `$text-disabled`).

## Out of scope

- No change to the placeholder string (kept as `Type your message...`).
- No widget-id changes (`#chat_input` usage is preserved).
- No updates needed to `docs/SCREENS.md` (already documents `#chat_input`).

## Verification

- `uv run pytest` (full suite; no behaviour/id changes so existing tests stay
  green).
- `python -m compileall src`