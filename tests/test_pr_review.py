"""
Tests for the pull request review script.
"""
import logging
import sys
import threading
from pathlib import Path

import pytest

# Add src to the path to import jobhunt modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
# Add scripts to the path to import the review script
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pr_review  # noqa: E402
from pr_review import (  # noqa: E402
    Finding,
    ReviewError,
    build_command_arguments,
    build_review_payload,
    format_ranges,
    normalise_path,
    parse_findings,
    parse_unified_diff,
    resolve_finding,
    wait_for_review,
)

SAMPLE_PATCH = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,4 +10,6 @@ def handler():
     context one
     context two
-    removed
+    added one
+    added two
     context three
diff --git a/src/new.py b/src/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,3 @@
+line one
+line two
+line three
diff --git a/src/gone.py b/src/gone.py
deleted file mode 100644
index 4444444..0000000
--- a/src/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-was here
-also here
"""

SAMPLE_REVIEW = """### src/app.py:12
The guard returns `None` instead of raising, so callers silently divide by
`None` later on.

### src/new.py:2
The helper ignores the default when the variable is set but empty.

## Summary
The commit adds a guard and a new helper.
"""


def test_parse_unified_diff_tracks_changed_lines():
    """Modified files expose only their added lines as changed."""
    files = parse_unified_diff(SAMPLE_PATCH)

    assert "src/app.py" in files
    assert files["src/app.py"].changed_lines == {12, 13}


def test_parse_unified_diff_tracks_context_lines():
    """Lines inside a hunk are tracked separately from changed lines."""
    files = parse_unified_diff(SAMPLE_PATCH)

    assert files["src/app.py"].hunk_lines == {10, 11, 12, 13, 14}


def test_parse_unified_diff_handles_new_files():
    """Every line of a new file counts as changed."""
    files = parse_unified_diff(SAMPLE_PATCH)

    assert files["src/new.py"].changed_lines == {1, 2, 3}


def test_parse_unified_diff_skips_deleted_files():
    """A deleted file has no new side and is left out."""
    files = parse_unified_diff(SAMPLE_PATCH)

    assert "src/gone.py" not in files


def test_parse_findings_extracts_blocks_and_summary():
    """Findings and the trailing summary are separated."""
    findings, summary = parse_findings(SAMPLE_REVIEW)

    assert len(findings) == 2
    assert findings[0].path == "src/app.py"
    assert findings[0].line == 12
    assert findings[1].path == "src/new.py"
    assert findings[1].line == 2
    assert summary == "The commit adds a guard and a new helper."


def test_parse_findings_keeps_the_comment_body():
    """The text under a heading becomes the comment body."""
    findings, _ = parse_findings(SAMPLE_REVIEW)

    assert "silently divide by" in findings[0].body
    assert "## Summary" not in findings[0].body


def test_parse_findings_without_any_findings():
    """A review with no findings yields an empty list."""
    findings, summary = parse_findings("## Summary\nNothing looked wrong.\n")

    assert findings == []
    assert summary == "Nothing looked wrong."


def test_parse_findings_ignores_non_finding_headings():
    """Headings without a path and line are not findings."""
    findings, _ = parse_findings("### Notes\nThis is prose, not a finding.\n")

    assert findings == []


def test_parse_findings_ignores_deeper_headings():
    """A fourth level heading is not a finding heading."""
    findings, _ = parse_findings("#### src/app.py:12\nNot a finding.\n")

    assert findings == []


def test_parse_findings_keeps_a_trailing_heading_title():
    """Text the model adds after the line number stays with the comment."""
    findings, _ = parse_findings("### src/app.py:12 [Medium]\nThe problem.\n")

    assert len(findings) == 1
    assert findings[0].body.startswith("[Medium]")
    assert "The problem." in findings[0].body


def test_normalise_path_strips_diff_decorations():
    """The decorations a model adds are removed."""
    assert normalise_path("`./src/app.py`") == "src/app.py"
    assert normalise_path("b/src/app.py") == "src/app.py"
    assert normalise_path("src/app.py") == "src/app.py"


def test_format_ranges_compresses_line_numbers():
    """Consecutive line numbers collapse into a range."""
    assert format_ranges({1, 2, 3, 7}) == "1-3, 7"
    assert format_ranges({5}) == "5"
    assert format_ranges(set()) == ""


def test_resolve_finding_accepts_a_changed_line():
    """A line the diff adds is used as written."""
    diff_files = parse_unified_diff(SAMPLE_PATCH)

    placed = resolve_finding(parse_findings(SAMPLE_REVIEW)[0][0], diff_files)

    assert placed.status == "changed"
    assert placed.path == "src/app.py"
    assert placed.line == 12


def test_resolve_finding_accepts_a_context_line():
    """A context line inside a hunk can still be commented on."""
    diff_files = parse_unified_diff(SAMPLE_PATCH)
    placed = resolve_finding(Finding(path="src/app.py", line=11, body="x"), diff_files)

    assert placed.status == "context"
    assert placed.line == 11


def test_resolve_finding_snaps_a_nearby_line():
    """A line just outside the diff moves to the closest changed line."""
    diff_files = parse_unified_diff(SAMPLE_PATCH)
    placed = resolve_finding(Finding(path="src/app.py", line=15, body="x"), diff_files)

    assert placed.status == "snapped"
    assert placed.line == 13


def test_resolve_finding_rejects_a_distant_line():
    """A line far from the diff cannot be placed."""
    diff_files = parse_unified_diff(SAMPLE_PATCH)
    placed = resolve_finding(Finding(path="src/app.py", line=900, body="x"), diff_files)

    assert placed.status == "unresolved-line"
    assert placed.line is None


def test_resolve_finding_rejects_an_unknown_path():
    """A path that is not in the diff cannot be placed."""
    diff_files = parse_unified_diff(SAMPLE_PATCH)
    placed = resolve_finding(Finding(path="src/other.py", line=1, body="x"), diff_files)

    assert placed.status == "unknown-path"
    assert placed.line is None


def test_resolve_finding_matches_a_bare_file_name():
    """A model that cites only the file name is still matched."""
    diff_files = parse_unified_diff(SAMPLE_PATCH)
    placed = resolve_finding(Finding(path="app.py", line=12, body="x"), diff_files)

    assert placed.path == "src/app.py"
    assert placed.status == "changed"


def test_build_review_payload_creates_inline_comments():
    """Placed findings become right sided inline comments."""
    diff_files = parse_unified_diff(SAMPLE_PATCH)
    findings, summary = parse_findings(SAMPLE_REVIEW)
    placed = [resolve_finding(finding, diff_files) for finding in findings]

    payload = build_review_payload(placed, [], summary, "opencode/big-pickle", "abc123")

    assert payload["commit_id"] == "abc123"
    assert payload["event"] == "COMMENT"
    assert len(payload["comments"]) == 2
    assert payload["comments"][0] == {
        "path": "src/app.py",
        "line": 12,
        "side": "RIGHT",
        "body": payload["comments"][0]["body"],
    }


def test_build_review_payload_keeps_unplaced_findings_in_the_body():
    """A finding without a line is reported in the review body instead."""
    diff_files = parse_unified_diff(SAMPLE_PATCH)
    findings, summary = parse_findings(SAMPLE_REVIEW)
    resolved = [resolve_finding(finding, diff_files) for finding in findings]
    stray = resolve_finding(Finding(path="src/app.py", line=900, body="A stray finding."), diff_files)
    placed = [item for item in resolved if item.line is not None]
    unplaced = [item for item in resolved if item.line is None] + [stray]

    payload = build_review_payload(placed, unplaced, summary, "opencode/big-pickle", "abc123")

    assert len(payload["comments"]) == len(placed)
    assert "Not placed inline" in payload["body"]
    assert "src/app.py:900" in payload["body"]
    assert "A stray finding." in payload["body"]


PULL_REQUEST = {
    "number": 30,
    "title": "Add a context menu to job row clicks",
    "baseRefOid": "base123",
    "headRefOid": "head456",
}


def test_build_command_arguments_includes_the_patch():
    """The model receives the diff instead of fetching it with a tool."""
    arguments = build_command_arguments(
        PULL_REQUEST,
        parse_unified_diff(SAMPLE_PATCH),
        40,
        SAMPLE_PATCH,
    )

    assert "Pull request: #30" in arguments
    assert "- src/app.py: 12-13" in arguments
    assert "```diff" in arguments
    assert "+    added one" in arguments


def test_build_command_arguments_truncates_an_oversized_patch(monkeypatch):
    """A very large diff is cut short and the model is told to read files."""
    monkeypatch.setattr(pr_review, "DEFAULT_MAX_DIFF_CHARS", 40)

    arguments = build_command_arguments(
        PULL_REQUEST,
        parse_unified_diff(SAMPLE_PATCH),
        40,
        SAMPLE_PATCH,
    )

    assert "patch truncated" in arguments
    assert "+    added two" not in arguments


def test_build_command_arguments_fences_a_patch_with_backticks():
    """A patch containing a code fence cannot close the surround fence."""
    patch = "diff --git a/a.md b/a.md\n@@ -0,0 +1 @@\n+```python\n"

    arguments = build_command_arguments(PULL_REQUEST, parse_unified_diff(patch), 40, patch)

    assert "````diff" in arguments


def _fake_api(messages, session=None):
    """Build an ``api_request`` stand-in for the wait loop."""

    def fake(url, method="GET", body=None, password=None, timeout=None):
        assert timeout is None or timeout > 0
        if "/message" in url:
            return {"data": messages}
        if url.endswith("/permission"):
            return {"data": []}
        return {"data": session or {"outcome": "succeeded"}}

    return fake


def _answer_message():
    return {
        "id": "msg_answer",
        "type": "assistant",
        "time": {"created": 2},
        "finish": "stop",
        "content": [{"type": "text", "text": SAMPLE_REVIEW}],
    }


def test_wait_for_review_returns_the_model_answer(monkeypatch):
    """A finished assistant message is returned as the review."""
    monkeypatch.setattr(pr_review, "api_request", _fake_api([_answer_message()]))

    answer = wait_for_review("http://test", "pw", "ses_test", 1)

    assert answer == SAMPLE_REVIEW


def test_wait_for_review_surfaces_a_failed_idle(monkeypatch):
    """A failed session reports the provider error instead of waiting."""
    messages = [
        {"id": "msg_tool", "type": "assistant", "time": {"created": 1}, "finish": "tool-calls", "content": []},
        {
            "id": "msg_idle",
            "type": "idle",
            "time": {"created": 2},
            "outcome": "failed",
            "error": {"message": "provider exploded"},
        },
    ]
    monkeypatch.setattr(pr_review, "api_request", _fake_api(messages, {"outcome": "failed"}))

    with pytest.raises(ReviewError, match="provider exploded"):
        wait_for_review("http://test", "pw", "ses_test", 1)


def test_wait_for_review_rejects_an_idle_without_an_answer(monkeypatch):
    """An idle session without a parsable answer fails immediately."""
    messages = [{"id": "msg_idle", "type": "idle", "time": {"created": 1}, "outcome": "succeeded"}]
    monkeypatch.setattr(
        pr_review,
        "api_request",
        _fake_api(messages, {"outcome": "succeeded", "time": {"updated": 1}}),
    )

    with pytest.raises(ReviewError, match="without a final answer"):
        wait_for_review("http://test", "pw", "ses_test", 1)


def test_wait_for_review_surfaces_an_interrupted_session(monkeypatch):
    """An interrupted session is terminal, not a reason to keep polling."""
    monkeypatch.setattr(pr_review, "api_request", _fake_api([], {"outcome": "interrupted"}))

    with pytest.raises(ReviewError, match="interrupted"):
        wait_for_review("http://test", "pw", "ses_test", 1)


def test_wait_for_review_reports_diagnostics_on_timeout(monkeypatch):
    """A timeout includes the session outcome and recent activity."""
    monkeypatch.setattr(
        pr_review,
        "api_request",
        _fake_api([], {"outcome": "running", "time": {"updated": 1}}),
    )

    with pytest.raises(ReviewError, match="did not finish within 0 seconds; outcome=running"):
        wait_for_review("http://test", "pw", "ses_test", 0)


def test_wait_for_review_caps_a_request_at_the_remaining_budget(monkeypatch):
    """When less time is left than the request cap, the poll uses what is left."""
    request_timeouts: list[float] = []

    def fake_api(url, method="GET", body=None, password=None, timeout=None):
        if "/message" in url:
            request_timeouts.append(timeout)
            return {"data": [_answer_message()]}
        return {"data": {"outcome": "running"}}

    monkeypatch.setattr(pr_review, "api_request", fake_api)

    assert wait_for_review("http://test", "pw", "ses_test", 1) == SAMPLE_REVIEW
    assert request_timeouts == [pytest.approx(1.0)]


def test_wait_for_review_caps_a_request_at_the_request_timeout(monkeypatch):
    """A generous deadline does not let one request outlive the request cap."""
    request_timeouts: list[float] = []

    def fake_api(url, method="GET", body=None, password=None, timeout=None):
        if "/message" in url:
            request_timeouts.append(timeout)
            return {"data": [_answer_message()]}
        return {"data": {"outcome": "running"}}

    monkeypatch.setattr(pr_review, "api_request", fake_api)
    monkeypatch.setattr(pr_review, "REQUEST_TIMEOUT_SECONDS", 30)

    assert wait_for_review("http://test", "pw", "ses_test", 600) == SAMPLE_REVIEW
    assert request_timeouts == [pytest.approx(30)]


def test_wait_for_review_reports_diagnostics_when_the_session_stalls(monkeypatch):
    """A session that stops changing fails with its recent activity."""
    messages = [
        {
            "id": "msg_retry",
            "type": "assistant",
            "time": {"created": 1},
            "finish": None,
            "retry": {
                "attempt": 2,
                "at": 2,
                "error": {"message": "Timed out waiting for response headers"},
            },
            "content": [
                {
                    "type": "tool",
                    "id": "tool_bash",
                    "name": "bash",
                    "state": {"status": "completed", "input": {"command": "uv run pytest -q"}},
                }
            ],
        }
    ]

    def fake_api(url, method="GET", body=None, password=None, timeout=None):
        if "/message" in url:
            return {"data": messages}
        if url.endswith("/permission"):
            return {"data": [{"action": "read", "resources": ["src/app.py"]}]}
        return {"data": {"outcome": "running", "time": {"updated": 7}}}

    monkeypatch.setattr(pr_review, "api_request", fake_api)
    monkeypatch.setattr(pr_review, "STALL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(pr_review.time, "sleep", lambda seconds: None)

    with pytest.raises(ReviewError) as error:
        wait_for_review("http://test", "pw", "ses_test", 5)

    message = str(error.value)
    assert "made no progress for 0.05 seconds" in message
    assert "outcome=running" in message
    assert "pending permissions: read(src/app.py)" in message
    assert "retry 2: Timed out waiting for response headers" in message
    assert "recent tools: bash: uv run pytest -q" in message


def test_wait_for_review_surfaces_a_terminal_step_error(monkeypatch):
    """A step that failed without an idle message does not wait for the timeout."""
    messages = [
        {
            "id": "msg_error",
            "type": "assistant",
            "time": {"created": 1},
            "finish": "error",
            "error": {"type": "provider", "message": "stream dropped"},
            "content": [],
        }
    ]
    monkeypatch.setattr(
        pr_review,
        "api_request",
        _fake_api(messages, {"outcome": "running", "time": {"updated": 1}}),
    )

    with pytest.raises(ReviewError, match="stream dropped"):
        wait_for_review("http://test", "pw", "ses_test", 1)


def test_wait_for_review_ignores_a_step_error_that_is_retried(monkeypatch):
    """An error with a pending retry keeps the wait alive."""
    messages = [
        {
            "id": "msg_error",
            "type": "assistant",
            "time": {"created": 1},
            "finish": "error",
            "retry": {"attempt": 1, "at": 2, "error": {"type": "provider", "message": "again"}},
            "error": {"type": "provider", "message": "again"},
            "content": [],
        },
        {
            "id": "msg_answer",
            "type": "assistant",
            "time": {"created": 3},
            "finish": "stop",
            "content": [{"type": "text", "text": SAMPLE_REVIEW}],
        },
    ]
    monkeypatch.setattr(pr_review, "api_request", _fake_api(messages))

    assert wait_for_review("http://test", "pw", "ses_test", 1) == SAMPLE_REVIEW


def test_log_new_messages_logs_a_tool_part_that_arrives_later(caplog):
    """A tool call streamed after its message is still logged."""
    message = {
        "id": "msg_tool",
        "type": "assistant",
        "time": {"created": 1},
        "finish": None,
        "content": [],
    }
    seen: set[str] = set()
    pr_review._log_new_messages([message], seen)
    message["content"].append(
        {
            "type": "tool",
            "id": "tool_read",
            "name": "read",
            "state": {"status": "completed", "input": {"filePath": "src/app.py"}},
        }
    )

    with caplog.at_level(logging.INFO, logger="pr_review"):
        pr_review._log_new_messages([message], seen)
        pr_review._log_new_messages([message], seen)

    assert caplog.text.count("tool read: src/app.py") == 1


def test_run_with_deadline_returns_the_call_result():
    """A call that finishes in time returns its value."""
    assert pr_review.run_with_deadline(lambda: "the review", 5) == "the review"


def test_run_with_deadline_gives_up_on_a_hanging_call():
    """A call that ignores its deadline does not hang the driver."""
    release = threading.Event()
    try:
        with pytest.raises(pr_review.DriverTimeoutError, match="stopped responding"):
            pr_review.run_with_deadline(lambda: release.wait(30) and "late", 0.05)
    finally:
        release.set()


def test_run_with_deadline_reraises_a_review_error():
    """A failure inside the wait loop reaches the caller unchanged."""

    def fail():
        raise ReviewError("the review session ended with outcome 'failed'")

    with pytest.raises(ReviewError, match="outcome 'failed'"):
        pr_review.run_with_deadline(fail, 5)


def test_api_request_reports_a_timeout(monkeypatch):
    """A request that times out is reported with its URL."""

    def timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(pr_review.urllib.request, "urlopen", timeout)

    with pytest.raises(ReviewError, match="timed out after 5 seconds"):
        pr_review.api_request("http://test/api/session", timeout=5)
