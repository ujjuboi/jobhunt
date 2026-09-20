# Sources

JobHunt supports five job-board sources through a unified `SourceAdapter` interface.
Sources are classified as **API-based** (Greenhouse, Lever, Ashby) or **web scraping**
(Indeed, LinkedIn via Playwright).

## SourceAdapter Interface (`src/jobhunt/sources/__init__.py`)

All sources implement this abstract base class:

| Method | Signature | Description |
|---|---|---|
| `get_jobs` | `(company_slug, limit, raise_errors)` | Fetch jobs for a company |
| `get_job_detail` | `(job_id)` | Fetch a single job by ID |
| `search_jobs` | `(query, limit, raise_errors)` | Search jobs by keyword |

The factory function `get_source_adapter(source_type, api_key)` returns the appropriate
subclass. All sources normalize responses to the shared `Job` model.

## API-Based Sources

### Greenhouse (`src/jobhunt/sources/greenhouse.py`)

**Base URL:** `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
**Auth:** API token passed as `auth_token` query parameter
**Features:**
- Full REST API, no anti-bot measures
- Normalizes `content` as description, `absolute_url`, `updated_at` as date
- `departments` are mapped to tags

**Search:** board-only APIs don't support free-text search. Falls back to `get_jobs(query, ...)`
where the query is used as the company slug.

### Lever (`src/jobhunt/sources/lever.py`)

**Base URL:** `https://api.lever.co/v0/postings/{slug}?mode=json`
**Auth:** No API key required (but may be needed for some accounts)
**Features:**
- Simple REST API
- Normalizes `createdAt` to timestamp
- `categories.team` is mapped to tags
- `applyUrl` is preserved

### Ashby (`src/jobhunt/sources/ashby.py`)

**Base URL:** `https://api.ashbyhq.com/posting-api/job-board/{slug}`
**Auth:** API key required
**Features:**
- POST request to job-board endpoint
- Supports both `descriptionPlain` and `descriptionHtml`
- Normalizes `publishedAt` as date
- `department` is mapped to tags

## Web Scraping Sources (Playwright)

### LinkedIn (`src/jobhunt/sources/linkedin.py`)

**Auth:** Browser login (no stored credentials or API keys)
**Features:**
- Headful first login for interactive authentication
- Session cookies persisted at `cache/linkedin_session.json`
- Subsequent runs use headless mode with the saved session
- Scrapes `div.job-card-container` elements from job search results
- Navigates `/jobs/search/?keywords={query}` for keyword search
- Navigates `/company/{slug}/jobs/` for company-specific jobs
- Playwright browser context is reused across requests

**Caveats:**
- ToS disclaimer: opt-in, feature-flagged, can break on site redesign
- Requires `playwright` installation (`playwright install chromium`)

### Indeed (`src/jobhunt/sources/indeed.py`)

**Auth:** None (free to use)
**Features:**
- Always headless (no login required)
- Scrapes `td.jobsearch-jobList-result` elements
- Uses `jk` query parameter as the job identifier
- Navigates `/company/{slug}/jobs` for company-specific jobs
- Navigates `/jobs?q={query}` for keyword search
- Polite 3-second delays between page loads

**Caveats:**
- ToS disclaimer: opt-in, can break on site redesign
- Requires `playwright` installation

## Per-Source Company Configuration

Configured in `config.toml` under `sources.companies`:

```toml
[sources.companies]
greenhouse = ["company-a", "company-b"]
lever = ["company-c"]
ashby = ["company-d"]
linkedin = ["linkedin-company-slug"]
indeed = ["indeed-company-slug"]
```

Each source maintains its own list of company slugs. The Search screen iterates the enabled
sources and, for board sources, fetches jobs from each configured company.

## Keyword Sources vs Board Sources

`KEYWORD_SOURCES = ("indeed", "linkedin")` — sources that support free-text keyword search.

`keyword_search_available()` checks if any keyword-search source is enabled. The Search
screen uses this to determine which sources to query with the user's search query.

Board sources (Greenhouse, Lever, Ashby) only support company-specific job fetching — their
`search_jobs` method falls back to `get_jobs(query, ...)` treating the query as a company
slug.

## Multi-Source Search (`app/screens/search.py`)

The Search screen (Phase 7) iterates all enabled sources from `user_config.sources.enabled`:

1. For each keyword-search source, calls `agent.run_tool("search_jobs", query=query, source=source)`
2. For each board source, calls with each configured company slug
3. Each source's results are collected individually with per-source try/except
4. Results are merged and deduplicated by `(title, company)`
5. Each result line is tagged with its `[source]` for identification

**Error handling:** if a source fails (e.g., LinkedIn without browser login), the failure
is noted in the status output but other sources continue.
