# Plan: Smaller local models + Jev-style decision scoring

**Scope:** Replace the oversized chat/embedding models with small, task-appropriate
ones, and add a decision-model (Jev/D1A-class) fit-scoring path alongside the
existing `hybrid` / `embedding` / `llm` modes. All model choice becomes
config-driven; no weights are shipped in the repo.

**Status:** planned, not implemented. Prerequisites (model downloads) confirmed
against the machine on 2026-10-20.

---

## 1. Goal

1. Chat + resume generation run on a ~3 GB 4-bit model instead of the current
   bf16 Gemma 4 E4B (~15.9 GB on disk).
2. Embeddings move from BGE-M3 to Qwen3-Embedding-0.6B (~0.3 GB, same 1024 dims).
3. Fit scoring gains an optional **typed-decision** mode (D1A) that returns
   calibrated probabilities in one forward pass, instead of parsing
   `response_format={"type":"json_object"}` from an autoregressive model.
4. Every model is selected through user config, not a hardcoded constant.

---

## 2. Why the current models are wrong-sized

The app never uses OpenAI tool/function calling — tools are a local Python
registry (`src/jobhunt/agent/__init__.py`). The model is only ever called three
ways, and none need vision, tools, or coding:

| Call site | Shape | Real requirement |
|---|---|---|
| `agent.chat_stream` / `chat` | streamed multi-turn prose | conversation quality, speed |
| `scoring._llm_confirm` | `response_format=json_object`, tiny schema | reliable JSON |
| `resume/tailor.py`, `resume/cover_letter.py` | one-shot JSON | JSON + faithful rewriting |

`gemma-4-e4b` is a multimodal, embedding-heavy model; Google's own table puts
bf16 E4B at ~17.9 GB, and the machine's download record shows a completed
**15.9 GB** pull (`~/.omlx/hf_download_tasks.json`). Almost all of that is
capability these three call sites never touch.

---

## 3. Verified findings (2026-10-20)

**oMLX install:** v0.7.0; CLI launcher `/Users/Admin/.omlx/bin/omlx`
(`/opt/homebrew/bin/omlx` symlinks to it); package at
`/opt/homebrew/Cellar/omlx/0.6.4/libexec/lib/python3.11/site-packages/omlx/`.

**Models currently served** (`GET /v1/models`): `HiDream-O1-Image-Dev-mlx-bf16`,
`MiniMax-H3-FL2VA-MLX-Serve-4bit`, `Qwen2.5-Coder-7B-Instruct-MLX`,
`Qwen3.6-35B-A3B-MLX-8bit`, `bge-m3-mlx-fp16`, `gemma-4-e4b-it-bf16`.

**Bug found:** `src/jobhunt/llm.py:33` defaults to `gemma-4-e4b-bf16`, but oMLX
serves `gemma-4-e4b-it-bf16`. The default does not match any served model id.

**Bug found:** `resume/tailor.py:110` and `resume/cover_letter.py:67` hardcode
`Qwen3-30B-A3B-6bit`, which is **not downloaded** — so tailoring and cover
letters silently fall back to their heuristic/template paths today.

**oMLX model taxonomy** (`omlx/model_discovery.py:28-29`):

```python
ModelType  = Literal["llm", "vlm", "embedding", "reranker", "audio_stt", "audio_tts", "audio_sts"]
EngineType = Literal["batched", "vlm", "embedding", "reranker", "audio_stt", "audio_tts", "audio_sts"]
```

Engines on disk: `base, batched, dflash, distributed, embedding, reranker, sts,
stt, tts, vlm`. Routes (`omlx/server.py`): `/v1/chat/completions`,
`/v1/completions`, `/v1/embeddings`, `/v1/rerank`, `/v1/models`.

**Consequence:** oMLX can serve chat, VLM, embeddings **and rerankers**, but it
has **no decision/classification engine**. A Jev/D1A checkpoint dropped into
`~/.omlx/models/` would be discovered as a `gemma4` VLM/LLM and served through
the chat engine, ignoring its `head.safetensors` + `d1a_config.json`. Its only
contract (`POST /v1/systemone`) does not exist in oMLX. **D1A must run as its
own sidecar.**

**Machine:** Apple M1 Max, 64 GB unified memory, 672 GB free. `uv` 0.12.15 and
`uvx` present. No `hf` / `huggingface-cli` binary and no `huggingface_hub` in
the system Python. oMLX also discovers models from the HF cache
(`~/.cache/huggingface/hub`, `--hf-cache` default on).

**Serving model:** the repo is a thin client. `config/__init__.py:load_omlx_settings`
reads `base_url` + `auth.api_key` from `~/.omlx/settings.json` (overridable via
`OMLX_BASE_URL` / `OMLX_API_KEY`); `llm.py` and `embeddings/__init__.py` POST to
`/v1` and pass **model-name strings**. Weights live outside the repo, so nothing
model-related is committed.

---

## 4. Decisions (locked with the user)

| Task | Choice |
|---|---|
| Chat + fit-confirm JSON | `Qwen3.5-4B-MLX-4bit` |
| Resume tailoring + cover letter | same model, resolved from config (`model.resume`) |
| Embeddings (search, dedupe, semantic score) | `Qwen3-Embedding-0.6B-4bit-DWQ` |
| Fit scoring | **D1A** (`mlx-community/d1a-e4b-it-8bit@v0.6`) as a new `decision` mode |
| Refactor scope | all three call sites config-driven (no hardcoded model constants) |

---

## 5. Target model set

| Purpose | HF repo to fetch | Served id / runtime | Size |
|---|---|---|---|
| Chat, confirm, resume | `mlx-community/Qwen3.5-4B-MLX-4bit` | oMLX id `Qwen3.5-4B-MLX-4bit` | ~3.0 GB |
| Embeddings | `mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ` | oMLX id `Qwen3-Embedding-0.6B-4bit-DWQ` | ~0.3 GB |
| Fit decisions | `mlx-community/d1a-e4b-it-8bit` (`@v0.6`) | D1A server on `:8009` | ~7.5 GB |

Served id = the model directory basename, which is how `bge-m3-mlx-fp16` and
`gemma-4-e4b-it-bf16` already resolve.

Alternatives if quality/latency disappoints:
- Chat: `mlx-community/Qwen3-4B-Instruct-2507-4bit` (~2.3 GB, text-only).
- Decisions: `mlx-community/d1a-e2b-it-8bit` (~4.8 GB, ~2.9x faster, weaker).
- Embeddings: keep `bge-m3-mlx-fp16` (still installed) as the fallback.

---

## 6. Prerequisites

### 6.1 oMLX models (chat + embeddings)

Download via the oMLX desktop app's model browser (search the repo id ->
Download). This is how `gemma-4-e4b-it-bf16` arrived. CLI alternative:
`omlx serve mlx-community/Qwen3.5-4B-MLX-4bit` accepts repo ids and pulls them.

Confirm they appear:

```bash
python3 - <<'PY'
import json, os, subprocess
s = json.load(open(os.path.expanduser("~/.omlx/settings.json")))
key = (s.get("auth") or {}).get("api_key") or s.get("api_key")
print(subprocess.run(["curl","-s","-H",f"Authorization: Bearer {key}",
    "http://127.0.0.1:8000/v1/models"], capture_output=True, text=True).stdout)
PY
```

### 6.2 D1A runtime + weights (decisions)

Weights do **not** go through oMLX and must stay out of `~/.omlx/models/`.
Preferred path (from the D1A README):

```bash
git clone https://github.com/jonpol01/d1a.git
cd d1a
uv sync --extra serve
uv run --extra serve python -m d1a.serving.serve \
  --run mlx-community/d1a-e4b-it-8bit@v0.6 --port 8009
```

First run downloads ~7.5 GB into the HF cache. To pre-fetch only the weights
(no `hf` CLI on this machine, so `uvx` supplies it):

```bash
uvx --from "huggingface_hub[hf_xet]" hf download \
  mlx-community/d1a-e4b-it-8bit --revision v0.6
```

Notes: pin `@v0.6` / `--revision v0.6`; the mirror is byte-identical to
`JohnP1/d1a-e4b-it-mlx-q8@v0.6`; Apache-2.0, no token needed; `media/*` (0.9 GB)
is optional for text decisions.

Smoke test before wiring anything:

```bash
curl -s localhost:8009/v1/systemone -H 'content-type: application/json' -d '{
  "state": "Senior Python engineer, 6 years, Django and AWS.",
  "model": "d1a-latest",
  "questions": {
    "fit": {"type": "score", "instructions": "How well does this candidate fit a Python backend role?",
            "labels": ["poor", "fair", "good", "excellent"]}
  }
}'
```

### 6.3 Disk budget

oMLX additions ~3.3 GB; D1A ~7.5 GB. Not a constraint on 672 GB free.

---

## 7. Serving architecture (unchanged + one addition)

| Piece | Served by | In repo? |
|---|---|---|
| Chat / confirm / resume | oMLX `:8000` (`auto_start_on_launch`) | model-name strings only |
| Embeddings | oMLX `:8000` | model-name strings only |
| Fit decisions | new D1A sidecar `:8009` | base URL + question builder; no weights, no bundled package |

The decision client talks HTTP (like `EmbeddingClient` does), so `d1a` is **not**
added to `[project.dependencies]` — that would drag MLX/torch into a currently
light stack (`textual`, `openai`, `httpx`, `python-docx`, `pydantic`, `rich`,
`numpy`, `playwright`). The app must remain fully functional when `:8009` is down.

---

## 8. Implementation phases

### Phase 0 — baseline (no code changes)

- Label ~20-30 real jobs with a personal fit verdict.
- Record today's `embedding`-mode cosine ranking and `hybrid`/`llm` confirm
  output for them.
- Acceptance for later phases: a new path must beat this baseline. (Rationale:
  Open-Jev's own report shows a 2B decision model losing to plain BM25 on a
  routing trial — "newer model" is not automatically better.)

### Phase 1 — config plumbing + correct defaults

**`src/jobhunt/llm.py`**
- `DEFAULT_CHAT_MODEL` (line 33) -> `"Qwen3.5-4B-MLX-4bit"`.
- Add `DEFAULT_RESUME_MODEL = DEFAULT_CHAT_MODEL`.
- `DEFAULT_EMBEDDING_MODEL` (line 34) -> `"Qwen3-Embedding-0.6B-4bit-DWQ"`.
- Extend `get_default_model(kind)` to understand `resume` in addition to
  `chat` / `embedding` (env `JOBHUNT_{KIND}_MODEL` -> config -> builtin).

**`src/jobhunt/config/user_config.py`**
- `ModelConfig`: add `resume: str = DEFAULT_RESUME_MODEL`; keep `chat`,
  `embedding`, `confirm` (repoint `confirm` default at the new chat model).
- `ALLOWED_SCORING_MODES` (line ~20): add `"decision"`.
- Add a `DecisionConfig` model: `base_url: str = "http://127.0.0.1:8009"`,
  `timeout_seconds: float = 30.0`, `model: str = "d1a-latest"`.
- `_to_toml` (line ~184): emit `resume` under `[model]` and a new `[decision]`
  block.
- `_validate`: leave unknown scoring modes to fall back to `hybrid`.

**`src/jobhunt/config/__init__.py`**
- `VALID_SCORING_MODES` (line 92): add `"decision"`.
- Add a `get_decision_settings()` accessor mirroring `get_omlx_settings()`.

**`src/jobhunt/app/screens/settings.py`**
- Update the `#model_input` placeholder (line 51) to the new chat model id.
- Add fields for resume model and decision base URL; wire into `on_button_pressed`
  save flow (currently chat model + scoring mode + system prompt only).
- Preserve all existing widget IDs; add the `"decision"` option to
  `#score_mode_select`.

### Phase 2 — embeddings + cache correctness

**`src/jobhunt/embeddings/__init__.py`**
- Replace the single `BGE_QUERY_PREFIX` constant with a model-aware map, e.g.
  `QUERY_PREFIXES = {"bge-m3-mlx-fp16": BGE_QUERY_PREFIX, ...}` plus an
  `_prefix_for(model)` helper. Qwen3-Embedding uses an instruction prefix
  (`Instruct: <task>\nQuery: <query>`); plain models use none.
- Keep the `use_bge_prefix` parameter for call-site compatibility but resolve it
  against the active model internally (mark the old name deprecated in the
  docstring).

**`src/jobhunt/db/__init__.py`** (mandatory correctness fix)
- `embeddings` table (line ~73): add a `model TEXT NOT NULL DEFAULT ''` column and
  make the uniqueness `UNIQUE(kind, entity_id, model)`.
- Add a lightweight migration for existing DBs (check `PRAGMA table_info`, `ALTER
  TABLE ... ADD COLUMN`, rebuild the unique index).
- `save_embedding(kind, entity_id, embedding, model=None)` and
  `get_embedding(kind, entity_id, model=None)`; a model mismatch is a cache miss.
- `get_profile_embedding(model=None)` (line ~384) filters on the model too.
- `cosine_similarity` (line ~336): guard against length mismatch so stale vectors
  can never produce a silent wrong score.
- `ScorePipeline.ensure_profile_embedding` / `ensure_job_embeddings` pass the
  active model id.

Consequence: switching embedding models invalidates automatically and re-embeds
on the next pass, instead of mixing vector spaces.

### Phase 3 — decision scoring

**New `src/jobhunt/decision/__init__.py`**
- `DecisionClient(base_url, api_key=None, timeout=30)`, built like
  `EmbeddingClient`: `httpx.Client` + the shared retry helper from
  `embeddings/__init__.py`.
- `decide(state: str, questions: dict) -> dict` posting to `/v1/systemone`.
- `DecisionUnavailableError` (or reuse `AgentUnavailableError`) raised with a
  descriptive message when the sidecar is unreachable — never a silent `[]`.
- `build_fit_questions(profile, job) -> dict`:
  - `fit`: `{"type": "score", "labels": [...], "instructions": ...}` -> the
    returned distribution's expectation becomes `FitScore.score`.
  - `matched_skills` / `missing_skills`: batched `{"type": "noul", ...}` per
    skill, evaluated in the same forward pass (cheap).
  - `suggested_bullets`: still generative -> delegate to the chat model.

**`src/jobhunt/scoring/__init__.py`**
- `ScorePipeline.__init__`: accept an optional `decision_client`.
- Add `_decision_confirm(job, profile) -> FitScore | None`, sitting beside
  `_llm_confirm` (line ~187) and mapping the typed answers to `FitScore`.
- `score()` (line ~262): add a `"decision"` branch. Suggested behaviour:
  decision-confirm the top `LLM_CONFIRM_TOP_N` semantic candidates, semantic-score
  the remainder — i.e. "hybrid with a decision confirm instead of an LLM confirm".
- Rework the `confirm_model != DEFAULT_CHAT_MODEL` guard (line ~215) so it keeps
  working with config-driven defaults.

**Fallback:** on `DecisionUnavailableError`, log the real cause and fall back to
the configured `hybrid` path; the screen surfaces it through its existing
`except Exception -> status update` path.

### Phase 4 — preflight + docs

**`src/jobhunt/cli.py`** — extend `check()` (or add a `preflight` entry point) to:
- list `GET /v1/models` and warn if any configured chat/embedding/resume model id
  is absent;
- probe the D1A sidecar and report whether `decision` mode is available.
  Turn "you didn't download the model" into an explicit message instead of a
  timeout.

**Docs to update** (all currently name the old models):

| File | Line(s) |
|---|---|
| `README.md` | 23, 26, 86-88 |
| `USER_GUIDE.md` | 22, 25, 65-67 |
| `docs/AGENT_LLM.md` | 14 |
| `docs/DATABASE_AND_CONFIG.md` | 172-173 |
| `docs/FEATURES.md` | 49 |
| `docs/SCORING.md` | 77 (and the mode list) |
| `docs/SCREENS.md` | Resume/Settings model rows |
| `smoke.py` | 13-14 (`CHAT_MODEL`, `EMBEDDING_MODEL`) |

Add a "Local runtimes" section to `USER_GUIDE.md`: how to start oMLX, download
the two oMLX models, and run the D1A sidecar on `:8009` (with the caveat that the
app works without it).

---

## 9. Tests

| File | Change |
|---|---|
| `tests/test_user_config.py` | new `resume`/`decision` keys round-trip; `"decision"` accepted as a scoring mode; invalid modes still fall back to `hybrid` |
| `tests/test_settings.py` | settings save writes the new fields; `#model_input` placeholder updated |
| `tests/test_scoring.py` | `"decision"` mode with a fake `DecisionClient`; fallback path when it raises; update the `FakeEmbeddings` default model string |
| `tests/test_embedding_client.py` | per-model prefix selection; model-keyed cache miss |
| `tests/test_db.py` | `embeddings` migration adds `model`; model-scoped read/write; dim-mismatch guard |
| `tests/test_resume.py` | tailor/cover-letter resolve the model from config instead of the hardcoded constant |
| new `tests/test_decision_client.py` | `build_fit_questions` shape + typed-response -> `FitScore` mapping against a fake `httpx` transport (no network) |

Integration tests that need the real servers must carry the `integration` marker
(opt-in via `JOBHUNT_INTEGRATION=1`) so CI never needs a running oMLX/D1A.

---

## 10. Verification

1. `uv run pytest` — baseline ~91 passed / 1 skipped, plus the new tests.
2. `python -m compileall src` (no linter is configured).
3. `uv run jobhunt-smoke` against the live oMLX with the new models.
4. `uv run jobhunt`: send a 3-turn chat, run fit in `embedding` then `decision`
   mode, generate a tailored resume and a cover letter.
5. Check `~/.config/jobhunt/logs/jobhunt.log` for valid JSON, no repetition
   loops, and no fallback-to-heuristic warnings on the tailoring path.
6. Compare rankings on the Phase 0 labelled set; record RSS and first-token
   latency before/after for chat.

---

## 11. Risks and rollback

- **D1A is young** (v0.6, tiny project). Pin `@v0.6`, treat `decision` mode as
  opt-in, and keep `hybrid`/`embedding`/`llm` intact. Rollback = set
  `scoring.mode = "hybrid"`.
- **7.5 GB / slower decisions**: drop to `d1a-e2b-it-8bit` (~4.8 GB) or abandon
  in favour of a reranker (oMLX's `/v1/rerank`, which *is* supported).
- **Embedding swap quality**: keep `bge-m3-mlx-fp16`; reverting is a config
  string once the cache is model-keyed.
- **Second local server**: document it; degrade gracefully; never block the TUI
  on sidecar availability.
- **Do not** place D1A weights under `~/.omlx/models/` — oMLX would try to serve
  them as a chat model.

---

## 12. Out of scope

- Fixing the gemma-4 chat-template loop (tracked separately in
  `plan/plan-gemma-chat-template.md`; becomes moot once gemma is retired here).
- Training or fine-tuning any model.
- Vendoring weights or adding an MLX/torch dependency to the project.
- `suggested_bullets` generation from the decision model (stays generative).
