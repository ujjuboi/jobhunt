---
description: Review a pull request and emit inline findings as `path:line` blocks that the CI job converts to GitHub inline review comments. Usage: /review-pr <pull request #N>.
---

# Pull Request Review

Review the pull request described below and report genuine defects as inline
findings. The target below is authoritative: it names the pull request, the
commits, and the exact line numbers that may be cited.

## Target

$ARGUMENTS

## Method

1. Fetch the change with `gh pr diff <number>` using the pull request number
   from the target above. If that command fails, fall back to
   `git diff -U0 <base>...<head>` with the commits from the target.
2. Read the **entire** content of every file the diff touches. A hunk in
   isolation hides bugs; the surrounding code shows whether a problem is real.
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
5. Verify a candidate defect before reporting it: re-read the surrounding code
   and, when it is cheap, run a command that demonstrates the behaviour.

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
