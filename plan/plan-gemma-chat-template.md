# Plan: Fix gemma-4 chat looping with a chat template (oMLX-side)

**Scope:** Root-cause and fix the chat repetition loop reported against the
default chat model `gemma-4-e4b-bf16` ("chat loops with assistant and user;
gemma is a robust model — investigate why it loops with this harness").

Status: **diagnosed, fix verified, not yet applied to the machine.**

## Root cause

The loop is a **prompt-rendering gap in oMLX**, not a model defect and not a
sampling parameter:

1. `gemma-4-e4b-bf16` ships **without a chat template**:
   `tokenizer_config.json` has no `chat_template` field (only `<bos>`/`<eos>`/
   `<pad>`), and no `chat_template.json` / `chat_template.jinja` sidecar exists
   next to the weights in `~/.omlx/models/mlx-community/gemma-4-e4b-bf16/`.
2. oMLX VLM engine handles a missing template with a plain-text fallback:
   `omlx/engine/vlm.py:3356-3376` → `mlx_vlm.prompt_utils.get_chat_template`
   → `_messages_to_plain_prompt()` (`mlx_vlm/prompt_utils.py:648-661`), which
   renders the conversation as a role-prefix transcript (`System:`, `User:`,
   `Assistant:` — note `role.capitalize()`).
3. On a fresh single turn this degrades but survives; on turn ≥2 the history
   already contains an `Assistant:` line, so the model auto-completes its own
   turn headers → `\nAssistant: hi\nAssistant: hi...` (or `hihihi...` without a
   system prompt). This matches the observed output exactly.

Evidence from `~/.config/jobhunt/logs/jobhunt.log` (2026-09-21):
`messages=2` → `stream done chunks=2 chars=17` (clean); then `messages=4`,
`messages=7`, `messages=8`, `messages=9` → `Chat reply abandoned: possible
repetition loop` or a manual interrupt. Single-turn generates and stops with
`finish_reason=stop`; multi-turn loops. Raising the harness temperature
(0.1 → 0.7) did not fix it — it only amplified an already-malformed prompt.

The correct gemma-4 protocol (Google spec: ai.google.dev/gemma/docs/core/
prompt-formatting-gemma4) is `<|turn>system\n...<turn|>\n<|turn>user\n...<turn|>
\n<|turn>model\n`; `assistant` history renders as `<|turn>model\n`, thinking is
gated by a leading `<|think|>` in the system turn, and tool history uses
`<|tool_call>` / `<|tool_response>`.

## Fix (oMLX-side — apply on this machine, not in the repo)

Create **`~/.omlx/models/mlx-community/gemma-4-e4b-bf16/chat_template.json`**
with the validated template below. `mlx_vlm/models/base.py:19-32`
(`load_chat_template`, reads `chat_template.json` first, then
`chat_template.jinja`) picks it up when the model loads (called from
`processing_gemma4.py:837`); with the template present, oMLX builds the proper
protocol prompt instead of the plain transcript. No jobhunt code change is
needed for the fix itself.

```json
{
  "chat_template": "{{- bos_token -}}\n{%- for message in messages -%}\n{%- set role = message['role'] -%}\n{%- if role == 'assistant' %}{%- set role = 'model' -%}{%- endif -%}\n{%- if role in ('system', 'developer') -%}\n<|turn>system\n{% if enable_thinking | default(false) %}<|think|>{% endif %}{{ message['content'] }}<turn|>\n\n{%- elif role == 'user' -%}\n<|turn>user\n{{ message['content'] }}<turn|>\n\n{%- elif role == 'model' -%}\n<|turn>model\n{% for tc in message.get('tool_calls', []) %}<|tool_call>{{ tc['id'] }}:{{ tc['function']['name'] }}{{ tc['function'].get('arguments','') }}<tool_call|>{% endfor %}{% for tr in message.get('tool_responses', []) %}<|tool_response>response:{{ tr['name'] }}{{ tr['response'] }}<tool_response|>{% endfor %}{{ message['content'] }}<turn|>\n\n{%- endif -%}\n{%- endfor -%}\n{%- if add_generation_prompt -%}\n<|turn>model\n\n{%- endif -%}"
}
```

Validated with `jinja2` (transformers-compatible) against canonical fixtures:
fresh prompt, prior assistant turn, thinking mode, and tool-call/tool-response
history all render to the expected `<|turn>`/`<|tool_call>` protocol.

## Verify

1. Reload gemma in oMLX (unload/reload the model in the oMLX app, or restart
   the server). `~/.omlx/logs/server.log` should still show
   `Output parser detected: gemma4 ...` for the reload.
2. `uv run jobhunt` → Chat → send `hi`, then 2–3 follow-up turns. In
   `~/.config/jobhunt/logs/jobhunt.log` every turn should log a reasonable
   `LLM stream done: ... chars=N` with **no** `possible repetition loop`.
3. Optional raw sanity: `curl http://127.0.0.1:8000/v1/chat/completions` with a
   2-turn `messages` payload and `stream: false`; confirm a sane, non-repeating
   reply.

## Guardrails

- Keep the client-side Stop/Esc interrupt, `_is_runaway` guard, and LLM
  request/response logging in jobhunt — correct defense-in-depth; harmless now
  that the prompt is fixed.
- This change lives in `~/.omlx/` (machine config), **not** the jobhunt repo.
  Do not commit secrets; the template file contains no credentials.
- Do not add `enable_thinking` for plain chat: the default renders
  `<|turn>model\n` with no `<|think|>`, matching how gemma-4-e4b
  (E2B/E4B-class) was trained.

## Note: unrelated secondary issue

`~/.omlx/logs/server.log` shows gemma being **aborted mid-request** when the
engine pool evicts it to page in `Qwen3.6-35B-A3B-MLX-8bit` under the
`admission soft target (46.66GB)`. That is a separate failure mode (request
aborts, not loops) — handle via oMLX memory/pinning settings if those aborts
matter; out of scope here.