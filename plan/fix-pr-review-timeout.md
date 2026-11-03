# Plan: Bound the PR review and fail fast when it stalls

**Status:** IMPLEMENTED (CI reliability fix)
**Trigger:** PR #30 — the `PR Review` check failed after 20m14s (run
39654709944) instead of posting a review.
**Branch:** `feat/jobs-row-context-menu`

## Problem

The `PR Review` workflow runs `scripts/pr_review.py`, which opens an OpenCode
session, runs the `review-pr` command, and waits for the model's answer. On PR
#30 the job hit the workflow's 35-minute job timeout with only the
`Review the pull request` step failing:

```
ERROR the review did not finish within 1200 seconds
```

No review was posted, and the log gave no clue about what the model was doing.

## Root cause

Three separate problems compounded:

1. **No step budget.** The session ran the default `build` agent, so the model
   could read forever. In the failing run it made 37+ model steps: it ran
   `uv run pytest`, wrote probe scripts, and read Textual internals — none of
   which is needed to review a diff. The driver only stopped it at 1,200
   seconds.
2. **The model had to fetch the diff itself.** `gh pr diff` cost a shell step
   and a round trip before any review work began, and encouraged further shell
   exploration.
3. **The wait loop could outlive its own deadline.** `api_request` used a fixed
   120-second socket timeout with no relationship to the loop's deadline, and a
   stalled HTTP read could keep the driver blocked well past `--timeout`. A
   local run (`run4`) was still alive 56 minutes into a 900-second budget, with
   the session stuck in provider retries (`Timed out waiting for response
   headers`, `Timed out waiting for response data`, `ECONNRESET`).

## Changes

### 1. `.opencode/agents/pr-reviewer.md` — a dedicated reviewer agent

- `mode: primary`, `steps: 24`, so the review has a hard step budget.
- Denies `edit`, `execute`, `subagent`, `webfetch`, `websearch`, `question`, and
  reads under `.venv` / `**/.venv/**`.
- Denies shell except the read-only fallbacks `gh pr diff *`, `git diff *`, and
  `git show *`.
- The system prompt states the review is read-only, forbids tests, probe
  scripts, lockfiles, dependency manifests, and unrelated files, and tells the
  model to report the defects it has confirmed when the budget runs out.

### 2. `.opencode/commands/review-pr.md` — smaller, self-contained review

- Frontmatter selects the agent with `agent: pr-reviewer`.
- Method step 1 uses the patch from the target and only falls back to `gh pr
  diff` / `git diff -U0` when the patch is missing.
- Step 2 reads only the changed files and the functions the hunks touch, and
  explicitly skips tests unless the patch changes them.

### 3. `scripts/pr_review.py` — inline patch, bounded requests, diagnostics

- `build_command_arguments` receives the patch and embeds it in the target
  with `diff_fence`, which picks a backtick fence longer than any run of
  backticks in the patch. The patch is capped at `DEFAULT_MAX_DIFF_CHARS =
  120_000`; when truncated the model is told to read the remaining files.
- `api_request` takes a `timeout` (default `REQUEST_TIMEOUT_SECONDS = 120`) and
  converts `TimeoutError` and other `OSError`s into `ReviewError`, so a socket
  timeout no longer escapes as a traceback.
- `wait_for_review` derives each request's timeout from the remaining budget
  (`min(REQUEST_TIMEOUT_SECONDS, remaining)`), so requests cannot push the loop
  past its deadline.
- `run_with_deadline` runs the wait loop on a daemon thread and raises
  `DriverTimeoutError` if it overruns `timeout + DRIVER_GRACE_SECONDS`; the
  driver then reports the session state instead of hanging until CI kills the
  job.
- `_log_new_messages` tracks parts individually, so tool calls that stream in
  after their assistant message are logged as they land, and retries/errors are
  logged once each.
- New terminal handling in `wait_for_review`: a latest assistant step with
  `finish: "error"` and no pending `retry` fails immediately with the provider
  error; idle with `succeeded` but no answer, failed/interrupted outcomes, and
  a 300-second stall all fail with `_session_diagnostics` (outcome, agent,
  pending permissions, recent tool calls).
- `review_pull_request` logs the selected agent right after starting the
  command, dumps the tail of the OpenCode server output on failure, and writes
  the failure reason to `--output`.

### 4. Tests — `tests/test_pr_review.py`

- Patch inclusion, fence selection, and truncation.
- Request timeout reporting and bounded wait-loop requests.
- `run_with_deadline` returning, re-raising `ReviewError`, and giving up on a
  hanging call.
- Idle/failed/interrupted/step-error handling, retry tolerance, stall
  diagnostics, and incremental tool logging.

### 5. Docs — `docs/PR_REVIEW.md`

- Documents the reviewer agent, the inline patch, the 24-step budget, the
  per-request timeout, the watchdog, and the diagnostics written on failure.

## Verification

- `uv run python -m compileall scripts/pr_review.py`
- `uv run pytest tests/test_pr_review.py -q` — 35 passed.
- `uv run pytest -q` — 200 passed, 1 skipped.
- Agent discovery on OpenCode v2.1.4: `/api/agent` lists `pr-reviewer` with
  `mode: primary`, `steps: 24`, and the expected permission rules once the
  location is loaded (the driver loads it by creating a session with
  `location`).
- Command selection: a probe command with `agent: pr-reviewer` switched the
  session agent, and the driver now logs `Review session agent pr-reviewer`.
- End-to-end dry run (`--pr-number 30 --dry-run`): the reviewer reads only the
  changed app files instead of tests and lockfiles.

## Out of scope

- No change to the review rubric's finding format or to how comments are
  posted.
- The workflow keeps its 35-minute job timeout and 1,200-second driver
  timeout; the changes make the driver finish well inside them or fail with a
  real reason.
