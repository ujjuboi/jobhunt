---
description: Review a pull request and emit inline findings as `path:line` blocks that the CI job converts to GitHub inline review comments. Usage: /review-pr <pull request #N>.
agent: pr-reviewer
---

# Pull Request Review

Review the pull request described below and report genuine defects as inline
findings. The target below is authoritative: it names the pull request, the
commits, the exact line numbers that may be cited, and the patch.

## Target

$ARGUMENTS

## Method

1. Use the patch in the target as the source of the change. If the target has no
   patch, fetch it with `gh pr diff <number>` using the pull request number. If
   that fails, fall back to `git diff -U0 <base>...<head>` with the commits
   from the target.
2. Read only the changed files and the functions or classes the hunks touch.
   Open a file when a hunk is ambiguous; do not read installed dependencies,
   lockfiles, dependency manifests, unrelated modules, or whole files "for
   context". Skip tests unless the patch changes them.
3. Look only for real defects:
   - logic errors and inverted or short-circuit conditions
   - unhandled edge cases (empty input, zero, `None`, missing keys, off-by-one)
   - swallowed errors and silent fallbacks that hide a failure
   - resource leaks and missing cleanup on error paths
   - security problems (injection, path traversal, secrets in logs)
   - behaviour that contradicts the stated intent of the change
   - async mistakes (blocking the event loop, cancelled work leaving state
     inconsistent, races between workers)
4. Do not report style, naming, formatting, missing type hints, or speculative
   refactors. Do not praise the change. Do not report a problem you are not
   certain about.
5. Verify a candidate defect by re-reading the surrounding code. Do not run the
   test suite, start the application, or write probe scripts; the review is
   read-only and has a small step budget.

## Output

Emit **only** the blocks described below. No preamble, no closing remarks, no
restatement of the method.

Each finding is one block:

### <path>:<line>
<one paragraph explaining what is wrong, under which conditions it breaks, and
how to fix it>

- `<path>` is a repository-relative path, exactly as it appears in the diff.
- `<line>` is a new-file line number and **must** be one of the citable lines
  listed in the target above. Never cite a line that is not on that list.
- No severity labels, no numbering, no bold text in the heading.
- The comment is a single paragraph of at most four sentences.
- Report at most five findings, most severe first. If the change has no
  defects, emit no blocks at all.

After the last block, emit exactly this section:

## Summary

Two or three sentences describing what the change does and your overall
assessment of it.
