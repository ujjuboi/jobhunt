# Pull Request Review

JobHunt reviews its own pull requests with a **two-tier pipeline**:

1. **Conventions + tests (required).** A deterministic, model-free checker
   (`scripts/pr_check.py`) encodes `AGENTS.md` and `docs/` as rules. It has no
   model, no network, no secrets, and finishes in seconds, so it never dies on
   a provider's free-tier quota. The `tests` job runs the test suite next to
   it, without secrets.
2. **OpenCode review (best effort).** The model review is a separate,
   non-blocking job. It uses OpenCode's free tier when available, or
   OpenAI-compatible free providers (Gemini, OpenRouter) via an API key, or a
   local oMLX server when run locally.

The review is [inline review comments](#placing-the-comments) on the changed
lines; the deterministic job degrades to the `$GITHUB_STEP_SUMMARY` when a
read-only token cannot post reviews.

## How It Works

```
.github/workflows/pr-review.yml   the workflow: conventions + tests + llm-review
scripts/pr_check.py               the deterministic rule checker
.opencode/commands/review-pr.md   the review command the model runs
.opencode/agents/pr-reviewer.md   the read-only reviewer agent
scripts/pr_review.py              the LLM driver: session, parsing, posting
```

1. The `conventions` job checks out the pull request head, resolves the base
   and head commits, and runs `pr_check.py` against the two trees.
2. The checker runs each rule against the head tree and the base tree and
   reports only *new* debt: a violation whose key `(rule, path, symbol)`
   already exists in the base tree is assumed to be accepted and not reported.
3. Findings are posted as inline PR review comments through the same payload
   builder as `pr_review.py`; on a read-only token the report is written to
   the step summary instead and the job keeps its verdict.
4. The optional `llm-review` job starts a private OpenCode server (or calls a
   free provider directly), sends the rubric and the patch, parses the findings
   the same way, and posts one review with the inline comments and summary.

## The Rule Catalogue

| ID | Severity | Rule |
|---|---|---|
| JH001 | blocking | print or pprint in library code (`src/**`, outside `cli.py`) |
| JH002 | blocking | swallowed errors: pass-only, empty-return, silent broad except |
| JH003 | blocking | unguarded `self.agent` access in `app/**` |
| JH004 | blocking | `compose()` defined on a BaseScreen subclass |
| JH005 | blocking | raw error strings appended to `self.messages` |
| JH006 | blocking | blocking I/O inside `async def` |
| JH013 | blocking | documented widget IDs missing from `app/**` |
| JH014 | blocking | `CREATE TABLE` columns not matching `DATABASE_AND_CONFIG.md` |
| JH015 | blocking | documented `JobHuntDB` methods missing from the class |
| JH018 | blocking | `pr-reviewer` agent missing read-only denies |
| JH019 | blocking | workflow safety: `pull_request_target`, unpinned actions, secrets in `run:`, broad permissions |
| JH007 | advisory | module logger not using `__name__` |
| JH008 | advisory | abbreviated names on new parameters or targets |
| JH009 | blocking | `JobHuntDB(...)` / `get_db(...)` called with `db_path=` |
| JH010 | advisory | screens built with `db=` instead of `database=` |
| JH011 | advisory | `time.sleep` in a test function body |
| JH012 | blocking | tests hitting the network without `@pytest.mark.integration` |
| JH016 | advisory | documented source adapters missing from `sources/**` |
| JH017 | advisory | documented scoring constants missing from `scoring/**` |
| JH020 | advisory | `[project.scripts]` targets missing from source |
| JH021 | advisory | new public module/class/function without a docstring |

What the checker **will not** catch: logic bugs. A semantic review still needs
a model, which is why the LLM job exists as an optional layer.

## Suppression

Findings can be silenced two ways:

- Inline, on the offending line or the one above it, with a **mandatory**
  reason: `# prcheck: ignore JH003 reason-why-this-is-ok`. A bare
  `ignore JH003` without a reason does not suppress anything.
- By configuration in `.prcheck.toml`: `check.disable` turns rules off
  entirely, and `check.allow` lists glob patterns matched against
  `rule:path` (for example `JH002:src/jobhunt/sources/linkedin.py`) for
  *existing, accepted debt*.

Every suppression is echoed into the report so nothing is silenced silently.

## Running The Checker

```bash
uv run python scripts/pr_check.py --all            # full repository scan
uv run python scripts/pr_check.py --base 3efb2b6   # new debt against a commit
uv run python scripts/pr_review.py --provider local --pr-number 30   # local oMLX LLM review
```

The checker exits `1` when a blocking finding remains, `0` otherwise, and
`2` on an internal error. `--json` prints machine-readable findings,
`--dry-run --post` prints the review payload instead of posting it.

## Provider Fallback

`scripts/pr_review.py` accepts `--provider {opencode|gemini|openrouter|local}`:

| Provider | Cost | Notes |
|---|---|---|
| `opencode` | free tier | the default driver; fragile on shared CI egress IPs |
| `gemini` | free tier per project | OpenAI-compatible endpoint; `GEMINI_API_KEY` secret |
| `openrouter` | ~50 req/day free | `OPENROUTER_API_KEY` secret; model via `OPENROUTER_MODEL` |
| `local` | free | local oMLX server; resolve base URL via `OMLX_BASE_URL` or `jobhunt.config` |

`--preflight` exits `0` when the provider is ready and `78` (neutral/skip)
when it is not, letting a job gate itself without failing. `--api-key-env`
names the environment variable that holds the API key.

## The Review Command

`.opencode/commands/review-pr.md` is an OpenCode slash command. Its body is
the reviewer rubric; `$ARGUMENTS` is replaced with the pull request number,
the base and head commits, the lines that may be cited, and the patch.

It asks the model for findings in a format the driver can parse without
guessing:

```
### src/jobhunt/app/components.py:42
The comment body, one paragraph.

## Summary
Two or three sentences about the change.
```

The rubric asks for real defects only — logic errors, unhandled edge cases,
swallowed errors, security problems, behaviour that contradicts the intent of
the change — and explicitly rules out style opinions and praise. Findings are
capped at five, most severe first.

The command runs under `.opencode/agents/pr-reviewer.md`, a read-only primary
agent with a 24-step budget. It cannot edit files, run tests, start the app,
write probe scripts, or use the web tools, and reads under `.venv` are denied.
Shell access is limited to the read-only fallbacks `gh pr diff`, `git diff`,
and `git show`. The patch is normally passed in the prompt, so the agent does
not need to fetch it at all. Bounding the agent keeps a large pull request from
spending the whole job timeout exploring the repository.

## Placing The Comments

GitHub rejects a review comment whose line is not part of the diff, so every
cited line is checked before posting:

| Situation | Result |
|---|---|
| The line is added or modified by the patch | Posted on that line |
| The line is context inside a hunk | Posted on that line |
| The line is within 3 lines of a changed line | Moved to the nearest changed line |
| The file is not in the patch | Not posted inline |
| The line is far from any change | Not posted inline |

A finding that cannot be placed is not dropped. It is written into the review
body under **Not placed inline**, with its path, line and comment, so nothing
the model found disappears without a trace.

## Running It

The workflow triggers on `opened`, `synchronize`, `reopened` and
`ready_for_review`, and can be started by hand from the Actions tab.

The `PR Review` required check now means "**conventions + tests passed**";
the model review is allowed to fail or be skipped without blocking a merge.

````text
Pull request: #28
Base commit: 0043fd5...
Head commit: b5eefd5...

Citable lines (new-file line numbers, cite these and no others):
- src/jobhunt/app/components.py: 42-48, 120

Patch (unified diff; this is the change under review):
```diff
diff --git a/src/jobhunt/app/components.py b/src/jobhunt/app/components.py
...
```
````

The model sees this list and the patch, and may only cite lines from the list,
which keeps the review grounded in the change rather than in the whole
repository. The patch is truncated after 120,000 characters; the model is told
to read the remaining files directly when that happens.

## Diagnostics

The driver logs each tool call and every model retry while the review runs, so
a slow review is visible in the Actions log. A review that goes idle without an
answer, fails, is interrupted, or makes no progress for five minutes stops
immediately with a descriptive error instead of waiting for the full timeout.
Every HTTP request is capped at two minutes, so a stalled server cannot hold the
wait loop past its deadline, and the loop itself runs behind a watchdog that
reports the session state if a request still hangs. On a timeout the error
includes the session outcome, pending permission requests, the most recent tool
calls, and the tail of the OpenCode server output. The failure reason is also
written to `--output` so the workflow summary shows it.

## Models

The workflow reviews with `opencode/big-pickle`, a free model that needs no
credentials. Override it per run with the **model** input of a manual run, or
by changing the `REVIEW_MODEL` environment variable in the workflow.

The driver passes the model to OpenCode when it opens the session. OpenCode
also accepts a model in its configuration file, but the session level model
wins and is the only one the driver relies on.

The free tier is available only to requests made from inside OpenCode, which
is why the workflow drives OpenCode rather than calling a model API directly.

## Requirements

- `contents: read` and `pull-requests: write` on the workflow token.
- The GitHub CLI, which is present on the hosted runners.
- OpenCode v2, installed by the workflow with
  `curl -fsSL https://opencode.ai/v2/install | bash`.

## Running The Script Locally

The script talks to GitHub through the `gh` CLI, so it needs an authenticated
`gh` and a pull request it can read.

```bash
uv run python scripts/pr_review.py --pr-number 28 --dry-run
```

`--dry-run` prints the review payload instead of posting it. `--output` writes
the model's raw answer to a file, which is the first place to look when a
review looks wrong.
