# JobHunt User Guide

JobHunt is a local, terminal-based (TUI) app that helps you prepare job
applications: it pulls job postings from your chosen job boards, scores how well
each fits your resume, tailors your resume and writes cover letters for the jobs
you care about — all against your local oMLX server, with no data leaving your
machine.

**Workflow philosophy: prep only, you submit.** JobHunt prepares the materials
(tailored resumes, cover letters, fit notes). You review them and apply on the
company's site yourself.

---

## 1. Prerequisites

- macOS with Apple Silicon
- Homebrew installed
- oMLX server running on `127.0.0.1:8000` (API key read automatically from
  `~/.omlx/settings.json`)
- The following models installed on oMLX:
  - `Qwen3-30B-A3B-6bit` — primary agent/chat model
  - `Qwen3-Coder-30B-A3B-Instruct-MLX-8bit` — fallback
  - `Qwen2.5-Coder-7B-Instruct-MLX` — backup
  - `bge-m3-mlx-fp16` — embeddings (fit scoring)
- A base resume as a `.docx` file (see [Resume setup](#4-resume-setup))

## 2. Installation

```bash
# 1. Install system dependencies
brew install uv libreoffice

# 2. Install the project (Python 3.12)
uv sync

# 3. Optional — Playwright browser for the LinkedIn / Indeed web sources
uv run playwright install chromium

# 4. Verify the oMLX connection (round-trip, structured JSON, embeddings)
uv run jobhunt-smoke

# 5. Launch the app
uv run jobhunt
```

## 3. Configuration

The app reads a user config from `~/.config/jobhunt/config.toml`. If the file
doesn't exist, sensible defaults are used; a file is created the first time you
press **Save Config** on the Settings screen.

The Settings screen edits the active sources, target company slugs, chat model,
scoring mode, and system prompt. You can also edit the TOML by hand:

```toml
[sources]
enabled = ["greenhouse", "lever", "ashby"]

[sources.companies]
greenhouse = ["stripe"]

[prompts]
system = "You are a helpful job-hunting assistant."
score = 'Score how well this candidate profile fits this job posting. Respond with JSON only, using keys: "score" (0.0 to 1.0), "explanation" (short reason), "matched_skills" (list), "missing_skills" (list), "suggested_bullets" (list).'

[model]
chat = "Qwen3-30B-A3B-6bit"
embedding = "bge-m3-mlx-fp16"
confirm = "Qwen3-30B-A3B-6bit"

[scoring]
mode = "hybrid"
```

Environment variables take precedence over the config file:

| Variable | Purpose |
| --- | --- |
| `OMLX_API_KEY`, `OMLX_BASE_URL` | oMLX credentials / endpoint override |
| `JOBHUNT_CHAT_MODEL` | Override the chat model |
| `JOBHUNT_EMBEDDING_MODEL` | Override the embedding model |
| `JOBHUNT_CONFIRM_MODEL` | Override the fit-scoring LLM model |
| `JOBHUNT_SCORING_MODE` | `hybrid` (default) \| `embedding` \| `llm` |
| `JOBHUNT_LOG_LEVEL` | Logging verbosity (e.g. `DEBUG`, `INFO`, `WARNING`) |
| `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD` | Credentials for the LinkedIn source |

Logs are written to stderr and to `~/.config/jobhunt/logs/jobhunt.log`.

### Scoring modes

- `hybrid` (default) — embedding similarity over all saved jobs, then an LLM
  confirm pass over the top candidates.
- `embedding` — pure semantic similarity; fastest, no LLM scoring.
- `llm` — LLM scoring over all jobs; slowest, most detail.

## 4. Resume setup

Your base resume `.docx` files live in `../Resumes/`, a sibling directory next to
the project folder:

```
Documents/Study/projects/python/
├── jobhunt/        # this project
└── Resumes/
    └── my-resume.docx
```

Place one or more `.docx` resumes there. When you select a resume in the app, it
is parsed into a structured profile (name, contact, summary, experience,
education, skills, certifications, projects), cached under `cache/resume/`, and
synced so the Fit screen can score against it.

The parser recognizes section headings like **Summary**, **Experience / Work
Experience**, **Education**, **Skills**, **Certifications**, and **Projects**. Use
bullet points in the experience section so bullets are captured cleanly.

## 5. Using the TUI

Seven screens are available from the navigation bar at the top of every screen:
**Dashboard · Search · Jobs · Fit · Resume · Chat · Settings**. Use the Tab/arrow
keys and Enter to move around.

### Dashboard

An overview of your search pipeline: total saved jobs, tracked applications, and
recent activity. Quick-action buttons jump straight to Search, Jobs, or Resume.

### Search

1. Type a query (job title, keywords) and press **Search**.
2. JobHunt searches **every enabled source** from your config, merges the
   results, removes duplicates, and tags each result with its source.
3. Results are saved to your local database automatically.

Notes:
- Per-source failures (for example, a source that needs credentials you haven't
  set) are reported inline rather than aborting the whole search.
- Enable only the sources you actually use in Settings to keep searches fast.

### Jobs

Lists the jobs saved locally from Search. **Refresh** reloads the list.

**Select a job row** to target it — this is what the Fit and Resume screens use
as the current job.

### Fit

Ranks saved jobs against your resume and shows an explainable score for each:

1. Select your resume once on the **Resume** screen first (this syncs your profile
   for scoring).
2. Press **Analyze**. JobHunt scores the saved jobs using your configured scoring
   mode.
3. Select a row to see the breakdown: overall score, explanation, matched skills,
   missing skills, and suggested resume bullets.

Scores are cached per job, so re-analyzing is fast.

### Resume

1. Select a base resume from the dropdown — the structured profile preview loads
   and your profile is synced for Fit scoring.
2. **Select a job** on the Jobs screen (you'll be prompted if none is selected).
3. Choose an action:
   - **Generate Tailored Resume** — the LLM rewrites the resume for the job's
     posting (ATS-friendly, keyword-focused).
   - **Generate Cover Letter** — drafts a cover letter addressed to the job's
     company.
   - **Save to Outputs** — writes the generated documents to the outputs folder
     (see [Outputs](#7-outputs--data)).

### Chat

A streaming chat with the JobHunt agent. The agent can answer questions about
your job hunt and, like the screens, can **search jobs**, **score fit**,
**generate a tailored resume**, and **write a cover letter**. Replies stream in;
transient oMLX hiccups are retried automatically.

### Settings

- Read-only **oMLX connection** details (base URL; the API key is masked).
- Editable **application settings**: enabled sources, company slugs, chat model,
  and scoring mode.
- Editable **system prompt** used by the Chat screen.
- **Save Config** writes everything to `~/.config/jobhunt/config.toml`.

## 6. Job board sources

Managed on the Settings screen under "Enabled sources".

| Source | Type | Notes |
| --- | --- | --- |
| **Greenhouse** | API | Open job board API; optional API key |
| **Lever** | API | Open job board API; optional API key |
| **Ashby** | API | Open job board API; optional API key |
| **Indeed** | Web scrape | No key; requires Playwright chromium |
| **LinkedIn** | Web scrape | Requires `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` |

For the web-scraping sources:

- Run `uv run playwright install chromium` once before first use.
- **LinkedIn** logs in once in a visible browser on first run and persists the
  session afterwards (headless), so you generally only sign in once. If the
  session expires, remove `cache/linkedin_session.json` and try again.
- These scrapers parse live site markup and can break if a site redesigns its
  pages; they also depend on the sites' robots/structure. Treat them as
  convenience helpers and prefer official APIs where available.

## 7. Outputs & data

Generated material is written to `outputs/{company}/{job}/`:

- `resume.docx` — tailored resume
- `resume.pdf` — PDF version (requires LibreOffice)
- `cover_letter.txt` — cover letter

Other data locations:

- `cache/resume/` — parsed resume profiles (JSON)
- `cache/linkedin_session.json` — LinkedIn session cookie jar

## 8. Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `jobhunt-smoke` fails | oMLX not running, or wrong key/base URL. Check `~/.omlx/settings.json` or `OMLX_API_KEY` / `OMLX_BASE_URL`, and that the models are installed. |
| Chat shows a connection error | oMLX briefly unavailable — retries handle short outages; otherwise start oMLX and retry. |
| Fit says "no profile found" | Select your resume on the Resume screen to sync your profile. |
| Fit/Resume prompt to select a job | Choose a job row on the Jobs screen first. |
| "Base resume directory not found" | Create the `../Resumes/` sibling folder and put your `.docx` resume(s) there. |
| No `.pdf` in outputs | LibreOffice isn't installed; the `.docx` is still saved. Run `brew install libreoffice`. |
| LinkedIn source errors | Set `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD`; install the Playwright browser; delete `cache/linkedin_session.json` if the session is stale. |
| Playwright/Chromium errors | Run `uv run playwright install chromium`. |
| Scored jobs look wrong | Check the scoring mode in Settings; `hybrid` is a good default. |

## 9. Development & maintenance

```bash
# Run the full test suite
uv run jobhunt-test

# Smoke-test oMLX, then run the suite
uv run jobhunt-check
```

## 10. Known limitations

- Web-scraping sources (LinkedIn, Indeed) depend on live site markup and can
  change or break; they are opt-in.
- PDF conversion requires LibreOffice being installed.
- Job fit and resume tailoring quality depends on your local models and how your
  resume is structured.