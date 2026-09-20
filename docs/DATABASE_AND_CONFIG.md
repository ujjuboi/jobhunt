# Database and Configuration

JobHunt uses SQLite for persistent storage and TOML for user configuration. The system is
designed for zero external dependencies — all data lives in a single database file.

## SQLite Database (`src/jobhunt/db/__init__.py`)

### JobHuntDB Class

```python
JobHuntDB(database_path="jobhunt.db")
```

Default path is `jobhunt.db` in the current working directory. All accessor methods wrap
their operations in try/except blocks, returning `[]`, `None`, or `False` on failure.

### Tables

#### jobs

| Column | Type | Description |
|---|---|---|
| `id` | TEXT (PK) | Unique job identifier |
| `title` | TEXT | Job title |
| `company` | TEXT | Company name |
| `location` | TEXT | Job location |
| `description` | TEXT | Full job description (HTML stripped) |
| `url` | TEXT | Application URL |
| `posted_date` | TEXT | Posting date |
| `salary` | TEXT | Salary range (if available) |
| `remote` | BOOLEAN | Remote status |
| `tags` | TEXT | Comma-separated tags |
| `source` | TEXT | Source name (greenhouse, lever, etc.) |
| `fit_score` | REAL | Last computed fit score |
| `fit_explanation` | TEXT | Last computed fit explanation |
| `created_at` | TEXT | Ingestion timestamp |

Upsert via `INSERT OR REPLACE`.

#### applications

| Column | Type | Description |
|---|---|---|
| `job_id` | TEXT (PK) | Reference to jobs.id |
| `status` | TEXT | Application status |
| `applied_date` | TEXT | Application date |
| `notes` | TEXT | Application notes |
| `cover_letter` | TEXT | Cover letter text |
| `resume_version` | TEXT | Resume version used |
| `created_at` | TEXT | Creation timestamp |
| `updated_at` | TEXT | Last update timestamp |

Tracks application workflow state per job.

#### embeddings

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER (auto PK) | Auto-incrementing ID |
| `kind` | TEXT | Entity type: 'job', 'resume', 'profile' |
| `entity_id` | TEXT | Entity identifier |
| `embedding` | TEXT | JSON-serialized float array |
| `created_at` | TEXT | Creation timestamp |

`UNIQUE(kind, entity_id)` — one embedding per entity.

#### profiles

| Column | Type | Description |
|---|---|---|
| `id` | TEXT (PK) | Unique profile identifier |
| `name` | TEXT | Full name |
| `email` | TEXT | Email address |
| `phone` | TEXT | Phone number |
| `location` | TEXT | Location |
| `summary` | TEXT | Professional summary |
| `experience` | TEXT | JSON-serialized list of experience dicts |
| `education` | TEXT | JSON-serialized list of education dicts |
| `skills` | TEXT | JSON-serialized list of skills |
| `linkedin_url` | TEXT | LinkedIn profile URL |
| `created_at` | TEXT | Creation timestamp |

Stores the user's resume profile for fit scoring.

#### resumes

| Column | Type | Description |
|---|---|---|
| `id` | TEXT (PK) | Unique resume identifier |
| `job_id` | TEXT | Associated job ID |
| `content` | TEXT | Generated resume content |
| `path` | TEXT | File path to the generated DOCX |
| `generated_at` | TEXT | Generation timestamp |
| `created_at` | TEXT | Creation timestamp |

Stores generated tailored resumes.

### Accessor Methods

All database accessors follow a consistent pattern: wrap operations in try/except, return
empty/falsy values on failure.

**CRUD operations:**

| Method | Returns | Description |
|---|---|---|
| `save_job(job)` | None | Upsert a job |
| `get_job(job_id)` | Job | Get a single job by ID |
| `get_jobs(limit=100, offset=0)` | list[Job] | List jobs with pagination |
| `save_application(application)` | None | Save/update application |
| `get_application(job_id)` | Application | Get application for a job |
| `save_profile(profile)` | None | Save user profile |
| `get_profile()` | Profile | Get user profile |
| `save_resume(resume)` | None | Save generated resume |
| `get_resume()` | Resume | Get the latest generated resume |

**Embedding operations:**

| Method | Returns | Description |
|---|---|---|
| `save_embedding(kind, entity_id, vector)` | None | Store or replace embedding |
| `get_embedding(kind, entity_id)` | ndarray | Get cached embedding |
| `get_profile_embedding()` | ndarray | Get profile embedding |
| `get_job_embeddings()` | dict | All job embeddings keyed by ID |
| `cosine_similarity(vec_a, vec_b)` | float | Compute cosine similarity (numpy) |

**Counters:**

| Method | Returns | Description |
|---|---|---|
| `count_jobs()` | int | Total number of jobs |
| `count_applications()` | int | Total number of applications |

## Configuration System

JobHunt has two configuration layers: oMLX server settings and user preferences.

### oMLX Settings (`src/jobhunt/config/__init__.py`)

`load_omlx_settings()` reads oMLX connection details:

**Sources (in order of precedence):**
1. `~/.omlx/settings.json`: looks for `auth.api_key` or top-level `api_key`
2. `OMLX_API_KEY` environment variable
3. `OMLX_BASE_URL` environment variable

**Defaults (if not found in settings file):**
- `base_url`: `http://127.0.0.1:8000/v1`
- `api_key`: resolved from settings or env

**Build logic:**
- `base_url` is constructed from `server.host:server.port` in settings.json, or defaults
- `api_key` comes from `auth.api_key` or top-level `api_key`

**Caching:** `get_omlx_settings()` uses `@lru_cache(maxsize=1)` for lazy, cached loading.
The import of `jobhunt.agent` no longer requires an oMLX key at import time.

**Error:** raises `ValueError` if no API key is found anywhere.

### User Config (`src/jobhunt/config/user_config.py`)

TOML user config at `~/.config/jobhunt/config.toml`, overridable via `JOBHUNT_CONFIG` env var.

#### UserConfig Model

| Field | Default | Description |
|---|---|---|
| `sources.enabled` | `["greenhouse", "lever", "ashby"]` | Enabled source names |
| `sources.companies` | `{}` | Dict: source -> list of company slugs |
| `prompts.system` | `"You are a helpful job-hunting assistant."` | Agent system prompt |
| `prompts.score` | *(JSON prompt template)* | Fit scoring prompt template |
| `model.chat` | `gemma-4-e4b-bf16` | Chat model name |
| `model.embedding` | `bge-m3-mlx-fp16` | Embedding model name |
| `model.confirm` | *(same as chat)* | LLM confirm pass model |
| `scoring.mode` | `"hybrid"` | Scoring mode |

#### Validation

`_validate()` sanitizes the config:
- Removes unknown sources from `sources.enabled` (must be in `ALLOWED_SOURCES`)
- Removes unknown sources from `sources.companies`
- Validates `scoring.mode` against `ALLOWED_SCORING_MODES`

```python
ALLOWED_SOURCES = ("greenhouse", "lever", "ashby", "linkedin", "indeed")
ALLOWED_SCORING_MODES = ("hybrid", "embedding", "llm")
```

#### Save

`save_user_config(config)` serializes the config to TOML and clears the `lru_cache` so
subsequent reads pick up the new values.

### Environment Overrides

| Variable | Applies to |
|---|---|
| `OMLX_API_KEY` | API key (oMLX settings) |
| `OMLX_BASE_URL` | oMLX base URL |
| `JOBHUNT_CONFIG` | User config file path |
| `JOBHUNT_SCORING_MODE` | Scoring mode (overrides TOML) |
| `JOBHUNT_CHAT_MODEL` | Chat model (overrides TOML) |
| `JOBHUNT_EMBEDDING_MODEL` | Embedding model (overrides TOML) |
| `JOBHUNT_LOG_LEVEL` | Logging level |

### Logging Configuration

Logging is initialized by the app on startup:

- **stderr:** immediate visibility of logs
- **File:** `~/.config/jobhunt/logs/jobhunt.log`
- **Level:** controlled by `JOBHUNT_LOG_LEVEL` (default: `INFO`)

Module-level loggers use `logging.getLogger(__name__)`. No `print()` statements in library
or app code.
