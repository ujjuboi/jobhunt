"""
Tests for the pull request review script.
"""
import sys
from pathlib import Path

# Add src to the path to import jobhunt modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
# Add scripts to the path to import the review script
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from pr_review import (  # noqa: E402
    Finding,
    build_review_payload,
    format_ranges,
    normalise_path,
    parse_findings,
    parse_unified_diff,
    resolve_finding,
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
