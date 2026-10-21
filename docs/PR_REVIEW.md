# Pull Request Review

JobHunt reviews its own pull requests. A GitHub Actions workflow runs OpenCode
against an open pull request and posts the result as **inline review comments**
on the changed lines.

The review is free: it runs on OpenCode's free model tier, so it needs no API
key and no Copilot subscription.

## How It Works

```
.github/workflows/pr-review.yml   the workflow
.opencode/commands/review-pr.md   the review command the model runs
scripts/pr_review.py              the driver: session, parsing, posting
```

1. The workflow checks out the pull request head and installs OpenCode v2.
2. `scripts/pr_review.py` reads the pull request metadata and patch with the
   GitHub CLI, then works out which lines of each file the patch touches.
3. It starts a private OpenCode server, opens a session on the checkout, and
   runs the `review-pr` command with the pull request, its commits, and the
   citable lines as the command's arguments.
4. The model answers with findings in a fixed format and a summary.
5. The driver checks every cited line against the patch and posts one pull
   request review holding the inline comments and the summary.

## The Review Command

`.opencode/commands/review-pr.md` is an OpenCode slash command. Its body is
the reviewer rubric; `$ARGUMENTS` is replaced with the pull request number,
the base and head commits, and the lines that may be cited.

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

```text
Pull request: #28
Base commit: 0043fd5...
Head commit: b5eefd5...

Citable lines (new-file line numbers, cite these and no others):
- src/jobhunt/app/components.py: 42-48, 120
```

The model sees this list and may only cite lines from it, which keeps the
review grounded in the change rather than in the whole repository.

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
