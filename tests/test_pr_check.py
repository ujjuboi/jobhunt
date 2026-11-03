"""Tests for the deterministic pull request checker."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pr_check  # noqa: E402
import pr_review  # noqa: E402
from pr_check import (  # noqa: E402
    ADVISORY,
    BLOCKING,
    CheckConfig,
    CheckFinding,
    RuleContext,
    changed_paths,
    format_report,
    load_config,
    run_checks,
    self_suppressed,
)

PHASE_A_FIXTURES = {
    "JH001": ('print("hi")\n', "src/jobhunt/lib.py", 'logger.info("hi")\n', "src/jobhunt/lib.py"),
    "JH002": (
        "try:\n    x = 1\nexcept Exception:\n    pass\n",
        "src/jobhunt/lib.py",
        "try:\n    x = 1\nexcept Exception as error:\n    logger.warning(f'dropped: {error}')\n",
        "src/jobhunt/lib.py",
    ),
    "JH003": (
        "class Screen:\n    def go(self) -> None:\n        self.agent.chat('hi')\n",
        "src/jobhunt/app/screens/fit.py",
        "class Screen:\n    def go(self) -> None:\n        agent = self._require_agent()\n        agent.chat('hi')\n",
        "src/jobhunt/app/screens/fit.py",
    ),
    "JH004": (
        "class DashboardScreen(BaseScreen):\n    def compose(self):\n        yield Title()\n",
        "src/jobhunt/app/screens/db.py",
        "class DashboardScreen(BaseScreen):\n    def _get_content(self):\n        yield Title()\n",
        "src/jobhunt/app/screens/db.py",
    ),
    "JH005": (
        "def go(self) -> None:\n    try:\n        pass\n    except Exception as error:\n        self.messages.append(f'bad: {error}')\n",
        "src/jobhunt/app/screens/chat.py",
        "def go(self) -> None:\n    try:\n        pass\n    except Exception:\n        self.messages.append('[error: see logs]')\n",
        "src/jobhunt/app/screens/chat.py",
    ),
    "JH006": (
        "async def poll(self) -> None:\n    time.sleep(5)\n",
        "src/jobhunt/app/screens/fit.py",
        "async def poll(self) -> None:\n    self._run_worker(asyncio.to_thread(time.sleep, 5))\n",
        "src/jobhunt/app/screens/fit.py",
    ),
    "JH007": (
        "logger = logging.getLogger('jobhunt.special')\n",
        "src/jobhunt/lib.py",
        "logger = logging.getLogger(__name__)\n",
        "src/jobhunt/lib.py",
    ),
    "JH008": (
        "def special(db=None):\n    pass\n",
        "src/jobhunt/lib.py",
        "def special(database=None):\n    pass\n",
        "src/jobhunt/lib.py",
    ),
    "JH009": (
        "JobHuntDB(db_path='x.db')\n",
        "src/jobhunt/lib.py",
        "JobHuntDB(database_path='x.db')\n",
        "src/jobhunt/lib.py",
    ),
    "JH010": (
        "screen = ScreenName(db=self.database)\n",
        "tests/test_settings.py",
        "screen = ScreenName(database=self.database)\n",
        "tests/test_settings.py",
    ),
    "JH011": (
        "def test_poll():\n    time.sleep(3)\n",
        "tests/test_poll.py",
        "def test_poll():\n    poll_for(lambda: state.ready)\n",
        "tests/test_poll.py",
    ),
    "JH012": (
        "def test_real_greenhouse_board_returns_jobs():\n    requests.get('x')\n",
        "tests/test_integration_greenhouse.py",
        "@pytest.mark.integration\ndef test_real_greenhouse_board_returns_jobs():\n    requests.get('x')\n",
        "tests/test_integration_greenhouse.py",
    ),
}


PHASE_B_FIXTURES = {
    "JH013": (
        {
            "docs/SCREENS.md": "the `#refresh_button` reloads the table",
        },
        ["JH013"],
    ),
    "JH014": (
        {
            "docs/DATABASE_AND_CONFIG.md": "### Tables\n\n#### jobs\n| `ghost_column` | TEXT | note |\n",
            "src/jobhunt/db/__init__.py": (
                "sql = '''\n    CREATE TABLE IF NOT EXISTS jobs (\n"
                "        id TEXT PRIMARY KEY,\n        title TEXT\n    )\n'''\n"
            ),
        },
        ["JH014"],
    ),
    "JH015": (
        {
            "docs/DATABASE_AND_CONFIG.md": "### Accessor Methods\n| `fetch_missing_jobs()` | list | ... |\n",
            "src/jobhunt/db/__init__.py": "class JobHuntDB:\n    def get_jobs(self):\n        pass\n",
        },
        ["JH015"],
    ),
    "JH017": (
        {
            "docs/SCORING.md": "### Constants\n| `MY_PENALTY` | 0.5 | note |\n",
            "src/jobhunt/scoring/__init__.py": "DEDUPE_THRESHOLD = 0.95\n",
        },
        ["JH017"],
    ),
    "JH018": (
        {
            ".opencode/agents/pr-reviewer.md": "---\npermissions:\n  - action: edit\n    resource: '*'\n    effect: deny\n---\ntext\n",
        },
        ["JH018"],
    ),
    "JH020": (
        {
            "pyproject.toml": "[project.scripts]\nghost = 'jobhunt.cli:missing'\n",
            "src/jobhunt/cli.py": "def smoke() -> None:\n    pass\n",
        },
        ["JH020"],
    ),
    "JH021": (
        {"src/jobhunt/lib.py": "def public_thing():\n    pass\n"},
        ["JH021"],
    ),
}


def make_context(root: Path, files: dict[str, str]) -> RuleContext:
    """Build a rule context from a mapping of path to source.

    Args:
        root: The tree root.
        files: Repository-relative path to file content.

    Returns:
        A context over the given tree.
    """
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return RuleContext(tree=root, python_paths=sorted(files))


def run_rule(rule_id: str, context: RuleContext) -> list[CheckFinding]:
    """Run one registered rule.

    Args:
        rule_id: The rule identifier.
        context: The context to pass.

    Returns:
        The rule's findings.
    """
    return pr_check.RULES[rule_id](context)


@pytest.mark.parametrize("rule_id", sorted(PHASE_A_FIXTURES))
def test_phase_a_rule_flags_violation_and_clean_tree(rule_id, tmp_path):
    """Each Phase A rule flags its violation and leaves its clean tree alone."""
    negative_body, negative_path, positive_body, positive_path = PHASE_A_FIXTURES[rule_id]
    flagged = {negative_path: negative_body}
    clean = {positive_path: positive_body}

    flagged_findings = run_rule(rule_id, make_context(tmp_path, flagged))
    assert flagged_findings, f"positive fixture for {rule_id} was not flagged"

    clean_findings = run_rule(rule_id, make_context(tmp_path / "one", clean))
    assert not clean_findings, f"negative fixture for {rule_id} produced findings"


@pytest.mark.parametrize("rule_id", sorted(PHASE_B_FIXTURES))
def test_phase_b_rule_flags_documentation_drift(rule_id, tmp_path):
    """Each Phase B rule flags its documentation drift fixture."""
    files, _ = PHASE_B_FIXTURES[rule_id]

    findings = run_rule(rule_id, make_context(tmp_path, files))

    assert findings
    assert {finding.rule for finding in findings} == {rule_id}


def test_jh019_flags_unsafe_workflow_patterns(tmp_path):
    """The workflow rule flags the four unsafe patterns."""
    files = {
        ".github/workflows/pr-review.yml": (
            "on:\n  pull_request_target:\njobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout\n"
            "      - run: echo ${{ secrets.GITHUB_TOKEN }}\n"
            "    permissions:\n      administration: write\n"
        )
    }
    findings = run_rule("JH019", make_context(tmp_path, files))

    assert findings
    assert all(finding.rule == "JH019" for finding in findings)


def test_jh013_flags_tests_referencing_missing_widget(tmp_path):
    """A test-referenced id that no widget defines is flagged with the test path."""
    files = {
        "docs/SCREENS.md": "the `#ghost_widget_id` reloads the table",
        "tests/test_dash.py": "screen.query_one('#ghost_widget_id', Button)\n",
    }
    findings = run_rule("JH013", make_context(tmp_path, files))

    assert findings
    assert findings[0].path == "tests/test_dash.py"
    assert findings[0].symbol.endswith("test_dash.py")


def test_jh014_flags_undocumented_column(tmp_path):
    """A code column missing from the docs is flagged against the db module."""
    files = {
        "docs/DATABASE_AND_CONFIG.md": "### Tables\n\n#### jobs\n| `id` | TEXT (PK) | note |\n",
        "src/jobhunt/db/__init__.py": (
            "sql = '''\n    CREATE TABLE IF NOT EXISTS jobs (\n"
            "        id TEXT PRIMARY KEY,\n        phantom TEXT\n    )\n'''\n"
        ),
    }
    findings = run_rule("JH014", make_context(tmp_path, files))

    assert any("phantom" in finding.message and finding.path == "src/jobhunt/db/__init__.py" for finding in findings)


def test_existing_debt_is_filtered(tmp_path):
    """run_checks drops findings that already exist in the base tree."""
    path = "src/jobhunt/app/screens/dash.py"
    violation = "class Dash(BaseScreen):\n    def compose(self):\n        yield None\n"
    head = make_context(tmp_path, {path: violation})
    base = make_context(tmp_path / "base", {path: violation})

    findings, suppressions = run_checks(head.tree, base.tree, [path], CheckConfig())

    assert not findings
    assert not suppressions


def test_new_debt_is_reported(tmp_path):
    """A violation that only exists in the head tree is reported."""
    path = "src/jobhunt/app/screens/dash.py"
    head = make_context(tmp_path, {path: "class Dash(BaseScreen):\n    def compose(self):\n        yield None\n"})
    base = make_context(tmp_path / "base", {path: "def fine() -> None:\n    pass\n"})

    findings, _ = run_checks(head.tree, base.tree, [path], CheckConfig())

    assert "JH004" in [finding.rule for finding in findings]
    blocking = [finding for finding in findings if finding.severity == BLOCKING]
    assert [finding.rule for finding in blocking] == ["JH004"]


def test_inline_suppression_silences_finding(tmp_path):
    """An inline prcheck: ignore marker silences the finding on that line."""
    source = "def go(self) -> None:\n    self.agent.chat('hi')  # prcheck: ignore JH003 mock-agent\n"
    path = "src/jobhunt/app/screens/dash.py"
    head = make_context(tmp_path, {path: source})

    findings, suppressions = run_checks(head.tree, None, [path], CheckConfig())

    assert suppressions == [
        pr_check.Suppression("JH003", path, 2, "mock-agent", "inline")
    ]
    assert all(finding.rule != "JH003" for finding in findings)


def test_inline_suppression_requires_reason(tmp_path):
    """A suppression without a reason string stays visible in the report."""
    source = "def go(self) -> None:\n    self.agent.chat('hi')  # prcheck: ignore JH003\n"
    path = "src/jobhunt/app/screens/dash.py"
    head = make_context(tmp_path, {path: source})

    findings, _ = run_checks(head.tree, None, [path], CheckConfig())

    assert any(finding.rule == "JH003" for finding in findings)


def test_config_allow_suppresses_finding():
    """An allow pattern suppresses a finding with a config-allow source."""
    finding = CheckFinding("JH002", "src/jobhunt/legacy.py", 10, BLOCKING, "m", "sym")
    config = CheckConfig(allow=["JH002:src/jobhunt/legacy.py"])

    reason = self_suppressed(finding, {}, config)

    assert reason is not None
    assert reason[0] == "config-allow"


def test_config_disable_removes_rule(tmp_path):
    """A disabled rule contributes no findings."""
    files = {"src/jobhunt/lib.py": 'print("hi")\n'}
    head = make_context(tmp_path, files)

    findings, _ = run_checks(head.tree, None, list(files), CheckConfig(disable={"JH001"}))

    assert all(finding.rule != "JH001" for finding in findings)


def test_format_report_is_deterministic():
    """Report lines sort by (path, line, rule) with fixed wording."""
    findings = [
        CheckFinding("JH003", "b.py", 12, BLOCKING, "b message", "b-sym"),
        CheckFinding("JH001", "a.py", 2, BLOCKING, "a message", "a-sym"),
        CheckFinding("JH007", "a.py", 1, ADVISORY, "c message", "c-sym"),
    ]
    report = format_report(findings, [], exit_code=1)

    lines = [line for line in report.splitlines() if line.startswith("- ")]
    assert lines[0].startswith("- **JH007** (advisory) `a.py:1`")
    assert lines[1].startswith("- **JH001** (blocking) `a.py:2`")
    assert lines[2].startswith("- **JH003** (blocking) `b.py:12`")
    assert report.endswith("blocking: 2, advisory: 1, suppressions: 0 -> FAIL")


def test_load_config_defaults_to_empty(tmp_path):
    """A missing config yields defaults."""
    config = load_config(tmp_path / "does-not-exist.toml")

    assert config.disable == set()
    assert config.allow == []


# ---------------------------------------------------------------------------
# pr_review parser extensions: added text, removed lines, LEFT side
# ---------------------------------------------------------------------------

SAMPLE_PATCH_WITH_TEXT = """diff --git a/app.py b/app.py
index 000..111 100644
--- a/app.py
+++ b/app.py
@@ -5,7 +5,7 @@ import os
 keep_one = 1
-removed_line = go()
+added_line = come()
"""

SAMPLE_DELETION_PATCH = """diff --git a/gone.py b/gone.py
deleted file mode 100644
index 000..111 100644
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-first()
-second()
"""


def test_parse_unified_diff_records_added_line_text():
    """Added lines keep their source text for rules to inspect."""
    files = pr_review.parse_unified_diff(SAMPLE_PATCH_WITH_TEXT)

    assert files["app.py"].added_lines == {6: "added_line = come()"}


def test_parse_unified_diff_records_removed_lines():
    """Removed lines are tracked under their old side line numbers."""
    files = pr_review.parse_unified_diff(SAMPLE_PATCH_WITH_TEXT)

    assert files["app.py"].removed_lines == {6: "removed_line = go()"}


def test_parse_unified_diff_skips_deletions_by_default():
    """Deleted files are not in the mapping unless include_deletions is set."""
    assert "gone.py" not in pr_review.parse_unified_diff(SAMPLE_DELETION_PATCH)
    assert "gone.py" in pr_review.parse_unified_diff(SAMPLE_DELETION_PATCH, include_deletions=True)


def test_resolve_finding_places_deleted_line_on_left():
    """A finding on a removed line resolves to the LEFT side."""
    files = pr_review.parse_unified_diff(SAMPLE_DELETION_PATCH, include_deletions=True)

    finding = pr_review.Finding("gone.py", 2, "redesigned, see #1")
    resolution = pr_review.resolve_finding(finding, diff_files=files, allow_left=True)

    assert resolution.side == "LEFT"
    assert resolution.path == "gone.py"
    assert resolution.line == 2


def test_resolve_finding_default_keeps_right_behaviour():
    """Without allow_left, a deleted-line finding is not placed."""
    files = pr_review.parse_unified_diff(SAMPLE_DELETION_PATCH, include_deletions=True)

    finding = pr_review.Finding("gone.py", 2, "redesigned, see #1")
    resolution = pr_review.resolve_finding(finding, diff_files=files)

    assert resolution.line is None
    assert resolution.side == "RIGHT"


def test_build_review_payload_carries_side():
    """The payload builder forwards the resolved side to GitHub."""
    finding = pr_review.Finding("gone.py", 2, "redesigned, see #1")
    placed = pr_review.PlacedFinding(finding=finding, path="gone.py", line=2, status="deleted", side="LEFT")
    payload = pr_review.build_review_payload([placed], [], "summary", "pr_check", "abc123")

    assert payload["comments"] == [{"path": "gone.py", "line": 2, "side": "LEFT", "body": "redesigned, see #1"}]


def test_changed_paths_returns_repository_files(tmp_path):
    """changed_paths with no base lists tracked files of the repository."""
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    (repository / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repository, check=True)

    paths = changed_paths(repository, None, None)

    assert paths == ["file.txt"]


# ---------------------------------------------------------------------------
# Provider fallback (Phase C)
# ---------------------------------------------------------------------------


def test_provider_preflight_missing_openrouter_key(monkeypatch):
    """An unset key makes the provider not ready."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    reason = pr_review.provider_preflight("openrouter")

    assert reason is not None
    assert "OPENROUTER_API_KEY" in reason


def test_provider_preflight_ready_openrouter(monkeypatch):
    """A set key makes the provider ready."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    assert pr_review.provider_preflight("openrouter") is None


def test_resolve_provider_connection_rejects_unknown_provider():
    """Direct calls are limited to the three OpenAI-compatible providers."""
    with pytest.raises(pr_review.ReviewError):
        pr_review.resolve_provider_connection("opencode", "m")


def test_main_preflight_exits_neutral_without_key(monkeypatch, capsys):
    """--preflight exits 78 when no key is configured."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    exit_code = pr_review.main(["--provider", "gemini", "--preflight"])

    assert exit_code == pr_review.PREVIEW_EXIT_NEUTRAL


def test_openai_chat_completion_empty_answer_raises(monkeypatch):
    """An empty choices list produces a ReviewError."""
    def fake_urlopen(request, timeout):  # noqa: ANN001
        class Response:
            def read(self):
                return b'{"choices": []}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Response()

    monkeypatch.setattr(pr_review.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(pr_review.ReviewError):
        pr_review.openai_chat_completion("https://x/v1", "key", "test-model", [])
