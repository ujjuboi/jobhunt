# Resume System

JobHunt's resume system parses a base DOCX resume, tailors it to specific job descriptions
via LLM or heuristic methods, and generates ATS-friendly outputs including tailored resumes
and cover letters.

## Profile Parsing (`src/jobhunt/resume/profile_parser.py`)

The `DocxParser` class parses `.docx` files into a structured `Profile` object.

### Extraction Logic

| Field | Method |
|---|---|
| `name` | First heading element, or the first short paragraph |
| `email` | Regex pattern match |
| `phone` | Regex pattern match |
| `summary` | Text from the Summary section |
| `skills` | Split on commas, deduplicated, order preserved |
| `experience`, `education`, `projects` | Parsed as `ResumeSection` objects |
| `certifications` | Text from the Certifications section |

### Section Detection

Headers are recognized by their content (case-insensitive match against known headers):
Summary, Experience/Work Experience, Education, Skills, Certifications, Projects.

### Bullet Detection

Bullet points are detected by:
- Paragraph style name: matches `List*` pattern
- Bullet characters: `['•', '·', '◦', '▪', '▸', '►', '➢', '➣']`

### Section Model

`ResumeSection(title, content, bullets)` — Experience, Education, and Projects are
represented as sections with optional title, body content, and a list of bullet-point strings.

### Caching

Parsed profiles are JSON-cached at `cache/resume/{filename}.json`:
- `load_profile_from_cache()` returns the cached version first (fast path)
- `save_profile_to_cache()` writes after a fresh parse
- `load_profile_from_docx()` is the main entry point — checks cache, falls back to fresh parse

## Profile-to-DB Conversion (`src/jobhunt/resume/__init__.py`)

`ResumeManager.to_db_profile(resume_profile)` converts a `resume.Profile` (which contains
`ResumeSection` objects) into `models.Profile` (which uses `Dict[str, Any]` for structured
sections).

The conversion maps:
- Direct fields: `name`, `email`, `phone`, `location`, `summary`, `skills`, `linkedin_url`
- Structured fields: `experience`, `education`, `projects` via `[{"title", "content", "bullets"}]`

This method is called by the ResumeScreen when a user selects a DOCX, triggering auto-sync
of the profile to the database for fit scoring.

## Tailored Resumes (`src/jobhunt/resume/tailor.py`)

The `ResumeTailor` class provides two paths for tailoring a resume to a job description.

### LLM Path (`_llm_tailor`)

Sends the candidate profile and job description to the model via a structured JSON prompt.
The system prompt instructs the model for ATS optimization with strict rules:
- No fabrication of skills or experience
- Emphasize relevant keywords
- Quantify achievements where applicable

Returns a `TailoredResume` with:
- `summary` — tailored professional summary
- `updated_skills` — skill list augmented with JD-relevant terms
- `tailored_sections` — updated experience and education sections

### Heuristic Fallback (`_heuristic_tailor`)

Used when the LLM path is unavailable. Performs keyword matching:
- Keeps existing skills
- Adds keywords from the job description (length > 3, alphabetic, not in stop words)
- Experience bullets remain unchanged (no fabrication)

### DOCX Rebuild

`create_tailored_docx(profile, tailored)` rebuilds a DOCX file from the template:
- Name: centered, bold, 14pt
- Contact line: email, phone, location, LinkedIn URL
- Sections: SUMMARY, SKILLS, EXPERIENCE, EDUCATION headers
- Experience bullets: list items

## Cover Letters (`src/jobhunt/resume/cover_letter.py`)

The `CoverLetterGenerator` class provides two paths for generating cover letters.

### LLM Path (`_llm_generate`)

Sends profile, job description, and generation instructions to the model. Returns JSON with
a `content` key containing the letter text. Uses `temperature=0.3` for consistency.

### Template Fallback (`_template_generate`)

Builds a standard 3-4 paragraph letter when the LLM is unavailable:
- Extracts up to 5 keywords from the job description
- Standard salutation, body paragraphs, and closing

## PDF Conversion (`src/jobhunt/resume/pdf_converter.py`)

### Convert Function

`convert_docx_to_pdf(docx_path, pdf_path)` invokes LibreOffice headless:
```
libreoffice --headless --convert-to pdf --outdir <outdir> <docx>
```

### Availability Check

`is_libreoffice_available()` checks for `libreoffice` on the PATH via `shutil.which()`.
Returns `True` if available, `False` otherwise.

LibreOffice is required only for PDF generation. The resume system works without it,
producing DOCX output only. Install via `brew install libreoffice` on macOS.

## Output Layout

Artifacts are written to `outputs/{company_slug}/{job_slug}/` directories:

| File | Description |
|---|---|
| `resume.docx` | Always created from template |
| `resume.pdf` | Created if LibreOffice is available (may be `None`) |
| `cover_letter.txt` | Plain text cover letter |

The company slug and job slug are derived from the job's company name and job ID for
filesystem-safe paths.

## Resume Screen (`app/screens/resume.py`)

The ResumeScreen orchestrates the full workflow:

1. **DOCX selection** — dropdown picks a `.docx` from `../Resumes/` (sibling to project root)
2. **Profile loading** — parses DOCX, caches JSON, displays preview in `#resume_preview`
3. **Auto-sync** — saves profile to DB for fit scoring
4. **Job selection** — uses `app.selected_job_id` set by the Jobs screen
5. **Generation** — tailored resume, cover letter (LLM or heuristic)
6. **Save to Outputs** — writes artifacts to `outputs/{company}/{job}/`
