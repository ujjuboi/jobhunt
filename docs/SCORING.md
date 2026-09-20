# Scoring System

JobHunt's scoring system ranks jobs by their fit against the user's resume profile. It
supports three modes (`hybrid`, `embedding`, `llm`) and uses a local embedding model for
semantic similarity, with an optional LLM confirm pass.

## Scoring Modes

Set via `scoring.mode` in `config.toml` or `JOBHUNT_SCORING_MODE` environment variable.

| Mode | Description | Performance |
|---|---|---|
| `hybrid` (default) | Embedding similarity over all jobs, then LLM confirm pass over top N | Balanced |
| `embedding` | Pure semantic cosine similarity; no LLM calls | Fastest |
| `llm` | LLM scoring over all jobs | Slowest, most detailed |

Resolution order: `JOBHUNT_SCORING_MODE` env var > `user_config.scoring.mode` > `"hybrid"`.
Invalid values raise `ValueError`.

## ScorePipeline (`src/jobhunt/scoring/__init__.py`)

The `ScorePipeline` class orchestrates the full scoring workflow.

### Constants

| Constant | Value | Purpose |
|---|---|---|
| `DEDUPE_THRESHOLD` | 0.95 | Cosine similarity threshold for deduplication |
| `LLM_CONFIRM_TOP_N` | 15 | Number of top jobs for LLM confirm in hybrid mode |

### Pipeline Steps

**1. Profile embedding** (`ensure_profile_embedding`)
- Builds plain text from profile: summary, experience titles/companies/descriptions, skills
- Uses BGE query prefix for short text: `"Represent this sentence for searching relevant passages: ..."`
- Cached in DB via `db.save_embedding("profile", "default", vector)`

**2. Job embeddings** (`ensure_job_embeddings`)
- Builds plain text from each job: title + description (HTML stripped)
- Batch-embeds missing jobs for efficiency
- Cached per `(kind="job", entity_id=job_id)`

**3. Deduplication** (`_dedupe_jobs`)
- Drops near-duplicate jobs where embedding cosine similarity > 0.95
- Applies the BGE prefix rule: short texts get the instruction prefix, JDs embedded as plain docs

**4. Semantic scoring** (`_semantic_scores`)
- Computes cosine similarity of every job vector vs. the profile vector
- Results in a list of `(job_id, score)` pairs

**5. LLM confirm** (`_llm_confirm`)
- **Hybrid mode:** called on the top N jobs (default 15) from semantic scoring
- **LLM mode:** called on all jobs
- Sends structured JSON prompt using `config.prompts.score` template
- The prompt includes candidate profile info, job details, and instructions for the LLM
- Returns JSON with breakdown: matched skills, missing skills, reasoning, score
- **Score normalization:** models may return 0-100 or 0-1; all scores are normalized to 0..1

**6. Results assembly**
- In hybrid mode: LLM-scored jobs use the LLM result; others fall back to semantic score
- Results sorted by score descending
- Each result includes: job, score, explanation, matched skills, missing skills, suggested resume bullets

### Supporting Methods

| Method | Description |
|---|---|
| `run(profile, jobs)` | Execute the full pipeline, return sorted results |
| `similar_jobs(job_id, limit=10)` | Find nearest-neighbour jobs by embedding cosine similarity |

## Embedding Client (`src/jobhunt/embeddings/__init__.py`)

The `EmbeddingClient` wraps oMLX's `/v1/embeddings` endpoint.

### Configuration

- **Model:** `bge-m3-mlx-fp16` (1024-dimensional, normalized)
- **Timeout:** 60 seconds
- **Retry:** 3 retries on timeout/5xx/429 with exponential backoff

### BGE Prefix Rule

Resume and profile texts are short and function as queries: they receive the instruction
prefix `"Represent this sentence for searching relevant passages: "`. Job descriptions are
embedded as plain documents without any prefix.

### API Methods

| Method | Description |
|---|---|
| `embed_text(text)` | Embed a single text |
| `embed_batch(texts)` | Embed multiple texts in a single request |
| `_retry_post(func, max_retries=3)` | Internal helper with retry on transient errors |

### Normalization

All embeddings are normalized to unit vectors, enabling efficient dot-product (= cosine)
similarity computation.

## Vector Cache (`src/jobhunt/db/__init__.py`)

The `embeddings` SQLite table provides persistent storage for cached embeddings.

### Schema

```sql
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,          -- 'job', 'resume', 'profile'
    entity_id TEXT NOT NULL,
    embedding TEXT NOT NULL,     -- JSON-serialized float array
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kind, entity_id)
)
```

### Accessor Methods

| Method | Description |
|---|---|
| `save_embedding(kind, entity_id, vector)` | Store or replace an embedding |
| `get_embedding(kind, entity_id)` | Retrieve a cached embedding |
| `get_profile_embedding()` | Retrieve the user's profile embedding |
| `get_job_embeddings()` | Retrieve all job embeddings |
| `cosine_similarity(vec_a, vec_b)` | Compute cosine similarity (numpy-based) |

All database accessors wrap their operations in try/except blocks, returning `[]`, `None`,
or `False` on failure.

## Similar Jobs

`ScorePipeline.similar_jobs(job_id, limit=10)` finds the nearest-neighbour jobs for a given
job ID by computing cosine similarity between embeddings. Useful for discovering related
opportunities after finding a strong match.
