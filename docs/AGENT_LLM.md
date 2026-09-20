# Agent and LLM Integration

JobHunt's agent system provides a shared toolset that drives both the chat interface and
the TUI screens. All components communicate with a local oMLX server via the OpenAI SDK.

## LLM Access Layer (`src/jobhunt/llm.py`)

### Model Resolution

`get_default_model(kind)` resolves model names with this precedence:

1. Environment variable: `JOBHUNT_{KIND}_MODEL` (e.g., `JOBHUNT_CHAT_MODEL`)
2. User config (`config.toml`): `model.{kind}`
3. Builtin defaults: `gemma-4-e4b-bf16` for chat, `bge-m3-mlx-fp16` for embedding

### Retry Policy

The `@retry(max_retries=3, base_delay=0.5, jitter=0.1)` decorator wraps LLM calls with
exponential backoff on transient errors only.

**Transient errors:** HTTP 429, 500, 502, 503, 504; `ConnectionError`, `TimeoutError`,
`openai.APIConnectionError`, `openai.APITimeoutError`, `httpx.ConnectError`,
`httpx.TimeoutException`.

**Non-transient errors:** authentication failures, 4xx errors — re-raised immediately.

### HTTP Client

`_build_client()` creates an `OpenAI` client with:
- `timeout=60.0` seconds (60-second client timeouts for all requests)
- `max_retries=2`
- Base URL and API key from oMLX settings (lazy-loaded, cached)

### Core Functions

| Function | Description |
|---|---|
| `complete(messages, model, **kwargs)` | Wrapped in `@retry`. Returns plain-text reply. |
| `stream(messages, model, **kwargs)` | Iterator yielding text deltas. Survives mid-stream drops via restart with dedup. |

### Streaming Restart

On mid-stream connection drop, `stream()` restarts the request and deduplicates already-seen
content by tracking `seen_content`. The final attempt completes the stream normally, and a
dropped tail surfaces as an error line in the transcript.

## Tool Registry (`src/jobhunt/agent/__init__.py`)

`ToolRegistry` registers **7 tools** that are available to both the agent and the screens:

| Tool | Parameters | Description |
|---|---|---|
| `search_jobs` | `query, source, company, limit, raise_errors` | Searches a source, deduplicates, saves results to DB |
| `get_job_detail` | `job_id` | Looks up a stored job from the DB |
| `score_fit` | `job_id, profile` | Runs `ScorePipeline` in hybrid mode for a single job |
| `tailor_resume` | `job_id, profile` | Delegates to `ResumeManager.generate_tailored_resume()` |
| `generate_cover_letter` | `job_id, profile` | Delegates to `ResumeManager.generate_cover_letter()` |
| `update_status` | `job_id, status` | Creates/saves an Application entry with the given status |
| `list_jobs` | *(none)* | Returns all stored jobs |

**Internal dedup:** `_dedupe_jobs(jobs)` removes duplicates by job ID and by `(title, company)`
composite key.

## JobHuntAgent (`src/jobhunt/agent/__init__.py`)

The main agent class, constructed lazily via the `agent` property on `WorkerMixin`.

### Construction

- Creates an `OpenAI` client and a `ToolRegistry(database, agent=self)`
- On failure (oMLX unavailable, config missing), `agent` is set to `None`
- `_require_agent()` raises `AgentUnavailableError` with a descriptive message (never silently
  returns empty states)

### Agent Methods

| Method | Description |
|---|---|
| `run_tool(tool_name, **kwargs)` | Dispatches a tool call to the registry |
| `chat(messages, model)` | Non-streaming chat via `llm.complete()` |
| `chat_stream(messages, model)` | Streaming chat — yields text deltas |
| `chat_with_agent(messages, model)` | Structured JSON response (uses `response_format={"type": "json_object"}`) |
| `_resolve_model(model)` | Resolves model: explicit -> env -> config -> default |

## Streaming Chat (`app/screens/chat.py`)

The ChatScreen implements the streaming UI:

1. **Mode detection:** checks `hasattr(agent, "chat_stream")` to choose between streaming and blocking.
2. **Streaming pipeline** (`_ask_agent_streaming`):
   - A background worker thread iterates `agent.chat_stream()` into an `asyncio.Queue`
   - The UI thread polls the queue, appending deltas to `#chat_messages` incrementally
   - Error tuples `("error", marker)` from the queue produce `[error: see logs]` entries
3. **Error safety:** error messages are never appended raw into the transcript (raw error
   strings would feed into the model's context on the next turn). A neutral marker is stored
   instead.
4. **Busy guard:** `_is_busy("chat")` prevents sending a new message while the agent is
   still responding to the previous one.

## Logging

Module-level loggers via `logging.getLogger(__name__)`. The app initializes logging on
startup:
- **stderr:** for immediate visibility
- **File:** `~/.config/jobhunt/logs/jobhunt.log`
- **Level:** controlled by `JOBHUNT_LOG_LEVEL` environment variable

No `print()` statements are used in library/app code.
