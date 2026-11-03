#!/usr/bin/env python3
"""Run the OpenCode pull request review command and post inline review comments.

The script drives one OpenCode session against a pull request, reads the
findings the model produced, checks every cited line against the pull request
diff, and posts the result as a GitHub pull request review. Findings whose
line cannot be placed in the diff are reported in the review body instead of
being dropped.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

LOGGER = logging.getLogger("pr_review")

DEFAULT_MODEL = "opencode/big-pickle"
DEFAULT_COMMAND = "review-pr"
DEFAULT_PORT = 4097
DEFAULT_TIMEOUT_SECONDS = 1200
DEFAULT_MAX_FILES = 40
DEFAULT_MAX_DIFF_CHARS = 120_000
MESSAGE_PAGE_SIZE = 100
STALL_TIMEOUT_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 120
DRIVER_GRACE_SECONDS = 120
SNAP_DISTANCE = 3

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
FINDING_HEADING = re.compile(r"^###\s+(?P<path>[^\s:]+):(?P<line>\d+)(?P<rest>.*)$")
SUMMARY_HEADING = re.compile(r"^##\s+Summary\s*$", re.IGNORECASE)
SERVER_URL = re.compile(r"server listening on (?P<url>\S+)")
SERVER_PASSWORD = re.compile(r"server password (?P<password>\S+)")


class ReviewError(RuntimeError):
    """Raised when the review cannot be produced or posted."""


class DriverTimeoutError(ReviewError):
    """Raised when a blocking review call ignores its own deadline."""


@dataclass
class DiffFile:
    """The lines a single file contributes to a pull request diff.

    Attributes:
        path: Repository-relative path of the file (new side for modifications).
        changed_lines: New-side line numbers the diff adds or modifies.
        hunk_lines: New-side line numbers inside a hunk, context lines included.
        added_lines: Text of added lines keyed by their new-side line number.
        removed_lines: Text of removed lines keyed by their old-side line number.
        old_path: Left-side path for renames and deletions.
        deleted: True when the file no longer exists in the head tree.
    """

    path: str
    changed_lines: set[int] = field(default_factory=set)
    hunk_lines: set[int] = field(default_factory=set)
    added_lines: dict[int, str] = field(default_factory=dict)
    removed_lines: dict[int, str] = field(default_factory=dict)
    old_path: str | None = None
    deleted: bool = False


@dataclass
class Finding:
    """A single issue the model reported.

    Attributes:
        path: Path the model cited.
        line: New-file line number the model cited.
        body: Comment text the model wrote.
    """

    path: str
    line: int
    body: str


@dataclass
class PlacedFinding:
    """A finding together with the position it will be posted at.

    Attributes:
        finding: The finding as the model wrote it.
        path: Path the comment will be attached to, or None when unplaceable.
        line: Line the comment will be attached to, or None when unplaceable.
        status: Why the finding was placed the way it was.
        side: ``RIGHT`` for new-file lines, ``LEFT`` for deleted ones.
    """

    finding: Finding
    path: str | None
    line: int | None
    status: str
    side: str = "RIGHT"


def parse_unified_diff(patch: str, include_deletions: bool = False) -> dict[str, DiffFile]:
    """Map every file in a unified diff to the lines it adds or modifies.

    Args:
        patch: The unified diff text.
        include_deletions: When True, files deleted by the patch are keyed under
            their old path with ``deleted`` set to True; by default they are
            skipped, matching the original behaviour.

    Returns:
        A mapping of repository-relative path to its diff lines.
    """
    files: dict[str, DiffFile] = {}
    current: DiffFile | None = None
    old_path: str | None = None
    new_line = 0
    old_line = 0
    in_hunk = False

    for raw in patch.splitlines():
        if raw.startswith("diff --git "):
            current = None
            in_hunk = False
            continue
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                # Pure deletion: the file only exists on the left side.
                if include_deletions and old_path is not None:
                    current = files.setdefault(old_path, DiffFile(path=old_path, old_path=old_path, deleted=True))
                else:
                    current = None
                in_hunk = False
                continue
            path = target[2:] if target.startswith("b/") else target
            current = files.setdefault(path, DiffFile(path=path))
            in_hunk = False
            continue
        if raw.startswith("--- "):
            source = raw[4:].strip()
            if source != "/dev/null":
                old_path = source[2:] if source.startswith("a/") else source
            continue
        hunk = HUNK_HEADER.match(raw)
        if hunk is not None:
            old_line = int(hunk.group(1))
            new_line = int(hunk.group(3))
            in_hunk = current is not None
            continue
        if current is None or not in_hunk:
            continue
        if raw.startswith("+"):
            current.changed_lines.add(new_line)
            current.hunk_lines.add(new_line)
            current.added_lines[new_line] = raw[1:]
            new_line += 1
        elif raw.startswith("-"):
            current.removed_lines[old_line] = raw[1:]
            old_line += 1
        elif raw.startswith(" ") or raw == "":
            current.hunk_lines.add(new_line)
            old_line += 1
            new_line += 1

    return files


def parse_findings(text: str) -> tuple[list[Finding], str]:
    """Split a model answer into findings and the trailing summary.

    Args:
        text: The final assistant message.

    Returns:
        A tuple of the findings and the summary text.
    """
    findings: list[Finding] = []
    summary_parts: list[str] = []
    current: Finding | None = None
    body_lines: list[str] = []
    in_summary = False

    def close() -> None:
        if current is not None:
            current.body = "\n".join(body_lines).strip()

    for raw in text.splitlines():
        if SUMMARY_HEADING.match(raw):
            close()
            current = None
            in_summary = True
            continue
        if in_summary:
            summary_parts.append(raw)
            continue
        heading = FINDING_HEADING.match(raw)
        if heading is not None:
            close()
            trailing = heading.group("rest").strip()
            current = Finding(
                path=heading.group("path"),
                line=int(heading.group("line")),
                body="",
            )
            findings.append(current)
            body_lines = [trailing] if trailing else []
            continue
        if current is not None:
            body_lines.append(raw)

    close()
    return findings, "\n".join(summary_parts).strip()


def normalise_path(path: str) -> str:
    """Strip the decorations a model may add around a repository path.

    Args:
        path: The path as the model wrote it.

    Returns:
        The path in the form used by the diff.
    """
    cleaned = path.strip().strip("`").strip()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned.startswith("b/"):
        cleaned = cleaned[2:]
    return cleaned


def resolve_finding(finding: Finding, diff_files: dict[str, DiffFile], allow_left: bool = False) -> PlacedFinding:
    """Decide where a finding can be posted, if anywhere.

    Args:
        finding: The finding as the model wrote it.
        diff_files: The lines each changed file contributes.
        allow_left: Whether a deleted line may resolve to the LEFT side.

    Returns:
        The finding together with its resolved position and the reason for
        it. A finding that cites a line the patch removed and ``allow_left``
        is True resolves to the ``LEFT`` side.
    """
    path = normalise_path(finding.path)
    diff_file = diff_files.get(path)
    if diff_file is None:
        matches = [candidate for candidate in diff_files.values() if Path(candidate.path).name == Path(path).name]
        if len(matches) == 1:
            diff_file = matches[0]
            path = diff_file.path
    if diff_file is None:
        return PlacedFinding(finding=finding, path=None, line=None, status="unknown-path")

    if diff_file.deleted and finding.line in diff_file.removed_lines:
        if allow_left:
            return PlacedFinding(
                finding=finding, path=diff_file.path, line=finding.line, status="deleted", side="LEFT"
            )
        return PlacedFinding(finding=finding, path=path, line=None, status="unresolved-line")

    if finding.line in diff_file.changed_lines:
        return PlacedFinding(finding=finding, path=path, line=finding.line, status="changed")
    if finding.line in diff_file.hunk_lines:
        return PlacedFinding(finding=finding, path=path, line=finding.line, status="context")

    nearby = [candidate for candidate in diff_file.changed_lines if abs(candidate - finding.line) <= SNAP_DISTANCE]
    if nearby:
        snapped = min(nearby, key=lambda candidate: abs(candidate - finding.line))
        return PlacedFinding(finding=finding, path=path, line=snapped, status="snapped")
    return PlacedFinding(finding=finding, path=path, line=None, status="unresolved-line")


def format_ranges(lines: set[int]) -> str:
    """Render a set of line numbers as compact ranges.

    Args:
        lines: The line numbers to render.

    Returns:
        A comma separated list such as ``3-5, 12``.
    """
    if not lines:
        return ""
    ordered = sorted(lines)
    ranges: list[str] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(f"{start}-{previous}" if start != previous else f"{start}")
        start = previous = value
    ranges.append(f"{start}-{previous}" if start != previous else f"{start}")
    return ", ".join(ranges)


def render_citable_lines(diff_files: dict[str, DiffFile], max_files: int) -> str:
    """Describe the lines the model is allowed to cite.

    Args:
        diff_files: The lines each changed file contributes.
        max_files: The largest number of files to list.

    Returns:
        A markdown list of paths and their citable lines.
    """
    entries: list[str] = []
    for path in sorted(diff_files):
        diff_file = diff_files[path]
        if not diff_file.changed_lines:
            continue
        entries.append(f"- {path}: {format_ranges(diff_file.changed_lines)}")
    listed = entries[:max_files]
    if len(entries) > max_files:
        listed.append(f"- ... and {len(entries) - max_files} further files (omitted for brevity)")
    return "\n".join(listed)


def diff_fence(patch: str) -> str:
    """Choose a code fence that cannot be closed by the patch itself.

    Args:
        patch: The unified diff text.

    Returns:
        A backtick fence longer than any run of backticks in the patch.
    """
    longest = max((len(match) for match in re.findall(r"`+", patch)), default=0)
    return "`" * max(3, longest + 1)


def build_command_arguments(
    pull_request: dict,
    diff_files: dict[str, DiffFile],
    max_files: int,
    patch: str,
) -> str:
    """Build the target description handed to the review command.

    Args:
        pull_request: The pull request metadata.
        diff_files: The lines each changed file contributes.
        max_files: The largest number of files to list.
        patch: The unified diff of the pull request.

    Returns:
        The text substituted for ``$ARGUMENTS`` in the review command.
    """
    if len(patch) > DEFAULT_MAX_DIFF_CHARS:
        included = patch[:DEFAULT_MAX_DIFF_CHARS].rstrip()
        included += "\n... patch truncated; read the remaining changed files directly."
    else:
        included = patch
    fence = diff_fence(included)
    return (
        f"Pull request: #{pull_request['number']}\n"
        f"Title: {pull_request['title']}\n"
        f"Base commit: {pull_request['baseRefOid']}\n"
        f"Head commit: {pull_request['headRefOid']}\n"
        "\n"
        "Citable lines (new-file line numbers, cite these and no others):\n"
        f"{render_citable_lines(diff_files, max_files)}\n"
        "\n"
        "Patch (unified diff; this is the change under review):\n"
        f"{fence}diff\n{included}\n{fence}\n"
    )


def run_gh(arguments: list[str], stdin: str | None = None) -> str:
    """Run a GitHub CLI command and return its output.

    Args:
        arguments: Arguments to pass to ``gh``.
        stdin: Text to feed to the command on standard input.

    Returns:
        The command's standard output.

    Raises:
        ReviewError: If the command fails.
    """
    result = subprocess.run(["gh", *arguments], input=stdin, text=True, capture_output=True)
    if result.returncode != 0:
        raise ReviewError(f"gh {' '.join(arguments)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def fetch_pull_request(number: int) -> dict:
    """Read a pull request's metadata.

    Args:
        number: The pull request number.

    Returns:
        The pull request metadata.

    Raises:
        ReviewError: If the pull request cannot be read.
    """
    fields = "number,title,url,state,isDraft,baseRefOid,headRefOid,headRefName,baseRefName"
    raw = run_gh(["pr", "view", str(number), "--json", fields])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ReviewError(f"could not parse pull request metadata: {error}") from error


def fetch_pull_request_diff(number: int) -> str:
    """Read the patch of a pull request.

    Args:
        number: The pull request number.

    Returns:
        The unified diff text.
    """
    return run_gh(["pr", "diff", str(number)])


def fetch_repository_name() -> str:
    """Read the ``owner/name`` of the repository the CLI is pointed at.

    Returns:
        The repository name in ``owner/name`` form.
    """
    return run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()


def post_review(repository: str, number: int, payload: dict) -> None:
    """Post a pull request review.

    Args:
        repository: The repository in ``owner/name`` form.
        number: The pull request number.
        payload: The review payload.

    Raises:
        ReviewError: If the review cannot be posted.
    """
    endpoint = f"/repos/{repository}/pulls/{number}/reviews"
    run_gh(["api", "--method", "POST", endpoint, "--input", "-"], stdin=json.dumps(payload))


def post_comments_individually(repository: str, number: int, payload: dict) -> None:
    """Post the review one comment at a time.

    This is the fallback for a review request the API rejects as a whole, for
    instance when two findings resolve to the same line.

    Args:
        repository: The repository in ``owner/name`` form.
        number: The pull request number.
        payload: The review payload.

    Raises:
        ReviewError: If a comment cannot be posted.
    """
    for comment in payload.get("comments") or []:
        body = dict(comment)
        body["commit_id"] = payload["commit_id"]
        endpoint = f"/repos/{repository}/pulls/{number}/comments"
        run_gh(["api", "--method", "POST", endpoint, "--input", "-"], stdin=json.dumps(body))
    summary = (payload.get("body") or "").strip()
    if summary:
        endpoint = f"/repos/{repository}/issues/{number}/comments"
        run_gh(["api", "--method", "POST", endpoint, "--input", "-"], stdin=json.dumps({"body": summary}))


def api_request(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    password: str | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> dict:
    """Call the OpenCode HTTP API.

    Args:
        url: The absolute URL to call.
        method: The HTTP method to use.
        body: The JSON body to send.
        password: The server password to authenticate with.
        timeout: How long a single request may take.

    Returns:
        The decoded response body, or an empty mapping for an empty response.

    Raises:
        ReviewError: If the request fails or exceeds its timeout.
    """
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if password:
        token = base64.b64encode(f"opencode:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise ReviewError(f"{method} {url} returned {error.code}: {detail}") from error
    except TimeoutError as error:
        raise ReviewError(f"{method} {url} timed out after {timeout:.0f} seconds") from error
    except urllib.error.URLError as error:
        raise ReviewError(f"{method} {url} failed: {error.reason}") from error
    except OSError as error:
        raise ReviewError(f"{method} {url} failed: {error}") from error
    return json.loads(raw) if raw else {}


class OpenCodeServer:
    """A running OpenCode server that the review runs against.

    The server is started in a private process rather than the shared
    background service, so the review uses only the configuration the workflow
    provides.
    """

    def __init__(self, binary: str = "opencode", port: int = DEFAULT_PORT, startup_timeout: float = 120.0) -> None:
        """Start the server and wait until it accepts requests.

        Args:
            binary: The OpenCode executable to run.
            port: The port to serve on.
            startup_timeout: How long to wait for the server to come up.

        Raises:
            ReviewError: If the server does not start in time.
        """
        self.password = os.environ.get("OPENCODE_PASSWORD") or secrets.token_urlsafe(32)
        environment = dict(os.environ)
        environment["OPENCODE_PASSWORD"] = self.password
        self._lines: list[str] = []
        self._process = subprocess.Popen(
            [binary, "serve", "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
        )
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        self.base_url = self._await_url(startup_timeout)

    def _drain(self) -> None:
        """Copy the server output into a buffer the caller can inspect."""
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._lines.append(line.rstrip("\n"))

    def _await_url(self, startup_timeout: float) -> str:
        """Wait for the server to report the URL it serves on.

        Args:
            startup_timeout: How long to wait for the server to come up.

        Returns:
            The base URL of the server.

        Raises:
            ReviewError: If the server does not start in time.
        """
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            for line in self._lines:
                match = SERVER_URL.search(line)
                if match is not None:
                    password = SERVER_PASSWORD.search(line)
                    if password is not None:
                        self.password = password.group("password")
                    return match.group("url")
            if self._process.poll() is not None:
                raise ReviewError(f"opencode serve exited early: {' '.join(self._lines[-10:])}")
            time.sleep(0.5)
        raise ReviewError("opencode serve did not report a listening URL in time")

    def recent_output(self, limit: int = 20) -> list[str]:
        """Return the most recent lines the server printed.

        Args:
            limit: The largest number of lines to return.

        Returns:
            The tail of the server output.
        """
        return self._lines[-limit:]

    def close(self) -> None:
        """Stop the server."""
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._process.kill()


def fetch_base_commit(base_commit: str) -> None:
    """Make the base commit available locally so the git fallback works.

    Args:
        base_commit: The base commit of the pull request.
    """
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "fetch", "--no-tags", "origin", base_commit],
            text=True,
            capture_output=True,
            timeout=120,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        LOGGER.warning("timed out fetching the base commit %s", base_commit)
        return
    if result.returncode != 0:
        LOGGER.warning("could not fetch the base commit %s: %s", base_commit, result.stderr.strip())


def create_session(base_url: str, password: str, model: str, directory: Path) -> str:
    """Create an OpenCode session for the review.

    Args:
        base_url: The base URL of the OpenCode server.
        password: The server password.
        model: The model to review with, in ``provider/model-id`` form.
        directory: The directory the session should work in.

    Returns:
        The session identifier.

    Raises:
        ReviewError: If the session cannot be created.
    """
    provider, _, model_id = model.partition("/")
    if not provider or not model_id:
        raise ReviewError(f"model must look like 'provider/model-id', got {model!r}")
    payload = {
        "model": {"providerID": provider, "id": model_id},
        "location": {"directory": str(directory)},
        "title": f"pr-review-{directory.name}",
    }
    response = api_request(f"{base_url}/api/session", method="POST", body=payload, password=password)
    session = response.get("data") or response
    session_id = session.get("id")
    if not session_id:
        raise ReviewError("opencode did not return a session id")
    return session_id


def run_review_command(base_url: str, password: str, session_id: str, command: str, arguments: str) -> None:
    """Ask the server to run a slash command in a session.

    Args:
        base_url: The base URL of the OpenCode server.
        password: The server password.
        session_id: The session to run the command in.
        command: The name of the command to run.
        arguments: The text substituted for ``$ARGUMENTS``.

    Raises:
        ReviewError: If the command cannot be started.
    """
    payload = {"name": command, "text": arguments}
    api_request(f"{base_url}/api/session/{session_id}/command", method="POST", body=payload, password=password)


def fetch_session_messages(
    base_url: str,
    password: str,
    session_id: str,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> list[dict]:
    """Read the most recent messages of a session.

    The API returns its newest page in reverse order. The messages are sorted
    oldest first so callers can scan them in the order they were produced.

    Args:
        base_url: The base URL of the OpenCode server.
        password: The server password.
        session_id: The session to inspect.
        timeout: How long the request may take.

    Returns:
        The session messages, oldest first.

    Raises:
        ReviewError: If the messages cannot be read.
    """
    url = f"{base_url}/api/session/{session_id}/message?order=desc&limit={MESSAGE_PAGE_SIZE}"
    response = api_request(url, password=password, timeout=timeout)
    messages = response.get("data") or []
    messages.sort(key=lambda message: (message.get("time") or {}).get("created") or 0)
    return messages


def _tool_detail(part: dict) -> str:
    """Describe a tool call compactly enough for a log line.

    Args:
        part: A tool content part of an assistant message.

    Returns:
        The tool name with its command, path, or query.
    """
    state = part.get("state") or {}
    arguments = state.get("input") or {}
    detail = (
        arguments.get("command")
        or arguments.get("filePath")
        or arguments.get("path")
        or arguments.get("pattern")
        or arguments.get("query")
        or arguments.get("code")
        or ""
    )
    detail = " ".join(str(detail).split())
    if len(detail) > 160:
        detail = detail[:160].rstrip() + "..."
    name = part.get("name") or "tool"
    return f"{name}: {detail}" if detail else str(name)


def _log_new_messages(messages: list[dict], seen: set[str]) -> None:
    """Log the parts that appeared since the previous poll.

    An assistant message is streamed, so its tool calls arrive after the
    message itself. Parts are tracked individually to log them as they land.

    Args:
        messages: The session messages, oldest first.
        seen: Identifiers of the parts already logged. Updated in place.
    """
    for message in messages:
        message_id = message.get("id")
        if not message_id:
            continue
        if message.get("type") == "idle":
            key = f"{message_id}:idle"
            if key not in seen:
                seen.add(key)
                LOGGER.info("session idle with outcome %s", message.get("outcome"))
            continue
        if message.get("type") != "assistant":
            continue

        retry = message.get("retry")
        if retry:
            key = f"{message_id}:retry:{retry.get('attempt')}"
            if key not in seen:
                seen.add(key)
                detail = (retry.get("error") or {}).get("message") or "no detail"
                LOGGER.warning("model retry %s: %s", retry.get("attempt"), detail)

        error = message.get("error")
        if error:
            key = f"{message_id}:error"
            if key not in seen:
                seen.add(key)
                LOGGER.warning("model error: %s", error.get("message") or error)

        for index, part in enumerate(message.get("content") or []):
            if part.get("type") != "tool":
                continue
            key = f"{message_id}:tool:{part.get('id') or index}"
            if key in seen:
                continue
            seen.add(key)
            LOGGER.info("tool %s", _tool_detail(part))


def _step_error(messages: list[dict]) -> str | None:
    """Describe a terminal error on the latest assistant step.

    Args:
        messages: The session messages, oldest first.

    Returns:
        The error type and message, or None when the latest step did not fail.
    """
    last_assistant = next(
        (message for message in reversed(messages) if message.get("type") == "assistant"),
        None,
    )
    if not last_assistant or last_assistant.get("finish") != "error":
        return None
    if last_assistant.get("retry"):
        return None
    error = last_assistant.get("error") or {}
    return f"{error.get('type') or 'error'}: {error.get('message') or 'no detail'}"


def _idle_result(messages: list[dict]) -> tuple[str, str] | None:
    """Find the terminal idle message of a session.

    Args:
        messages: The session messages, oldest first.

    Returns:
        The idle outcome and its error detail, or None while the session runs.
    """
    for message in reversed(messages):
        if message.get("type") == "idle":
            error = message.get("error") or {}
            return (message.get("outcome") or "unknown", error.get("message") or "")
    return None


def run_with_deadline(call: Callable[[], str], seconds: float) -> str:
    """Run a blocking call and give up when it overruns its deadline.

    A socket timeout bounds each request, but a request can still stall past
    the wait loop's own deadline. The loop therefore runs on a worker thread so
    the driver always exits and reports the session state instead of sitting
    until the CI job is killed.

    Args:
        call: The zero-argument callable to run.
        seconds: How long to allow the call to take.

    Returns:
        Whatever the call returns.

    Raises:
        DriverTimeoutError: If the call does not return within the deadline.
        ReviewError: If the call raises one.
    """
    outcome: dict[str, str | Exception] = {}

    def run() -> None:
        try:
            outcome["value"] = call()
        except Exception as error:
            outcome["error"] = error

    worker = threading.Thread(target=run, name="pr-review-wait", daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise DriverTimeoutError(
            f"the review did not finish within {seconds:.0f} seconds and the driver stopped responding"
        )
    error = outcome.get("error")
    if isinstance(error, ReviewError):
        raise error
    if isinstance(error, Exception):
        raise ReviewError(f"the review failed: {error}") from error
    return str(outcome.get("value") or "")


def wait_for_review(base_url: str, password: str, session_id: str, timeout: float) -> str:
    """Wait for the review to finish and return the model's answer.

    Progress is logged as messages arrive. A session that goes idle without an
    answer, fails, is interrupted, or stops making progress ends the wait with
    a descriptive error instead of running until the full timeout.

    Args:
        base_url: The base URL of the OpenCode server.
        password: The server password.
        session_id: The session running the review.
        timeout: How long to wait for the review.

    Returns:
        The final assistant message.

    Raises:
        ReviewError: If the review fails or does not finish in time.
    """
    deadline = time.monotonic() + timeout
    seen: set[str] = set()
    last_updated: float | None = None
    last_change = time.monotonic()

    while time.monotonic() < deadline:
        remaining = max(1.0, deadline - time.monotonic())
        request_timeout = min(REQUEST_TIMEOUT_SECONDS, remaining)
        try:
            messages = fetch_session_messages(
                base_url,
                password,
                session_id,
                timeout=request_timeout,
            )
        except ReviewError as error:
            LOGGER.warning("could not read the review messages: %s", error)
            time.sleep(5)
            continue

        _log_new_messages(messages, seen)

        step_error = _step_error(messages)
        if step_error is not None:
            raise ReviewError(
                f"the review step failed ({step_error}); "
                + _session_diagnostics(base_url, password, session_id)
            )

        answer = _final_answer(messages)
        if answer is not None:
            return answer

        idle = _idle_result(messages)
        if idle is not None:
            outcome, detail = idle
            if outcome == "succeeded":
                raise ReviewError(
                    "the review session finished without a final answer; "
                    + _session_diagnostics(base_url, password, session_id)
                )
            raise ReviewError(
                f"the review session ended with outcome {outcome!r}: {detail or 'no error reported'}"
            )

        session = _session_info(base_url, password, session_id, timeout=request_timeout)
        outcome = session.get("outcome")
        if outcome in {"failed", "interrupted"}:
            raise ReviewError(
                f"the review session ended with outcome {outcome!r}; "
                + _session_diagnostics(base_url, password, session_id)
            )

        updated = (session.get("time") or {}).get("updated")
        if updated != last_updated:
            last_updated = updated
            last_change = time.monotonic()
        elif time.monotonic() - last_change > STALL_TIMEOUT_SECONDS:
            raise ReviewError(
                f"the review made no progress for {STALL_TIMEOUT_SECONDS} seconds; "
                + _session_diagnostics(base_url, password, session_id)
            )

        time.sleep(5)

    raise ReviewError(
        f"the review did not finish within {timeout:.0f} seconds; "
        + _session_diagnostics(base_url, password, session_id)
    )


def _final_answer(messages: list[dict]) -> str | None:
    """Extract the model's final answer from a list of session messages.

    Args:
        messages: The session messages, in any order.

    Returns:
        The concatenated text of the last assistant message, or None while the
        assistant is still calling tools.
    """
    for message in reversed(messages):
        if message.get("type") != "assistant":
            continue
        finish = message.get("finish")
        if finish is None or finish == "tool-calls":
            continue
        parts = message.get("content") or []
        text = "".join(part.get("text") or "" for part in parts if part.get("type") == "text")
        if text.strip():
            return text
    return None


def _session_info(
    base_url: str,
    password: str,
    session_id: str,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> dict:
    """Read the state of a session.

    Args:
        base_url: The base URL of the OpenCode server.
        password: The server password.
        session_id: The session to inspect.
        timeout: How long the request may take.

    Returns:
        The session state, or an empty mapping when it cannot be read.
    """
    try:
        response = api_request(
            f"{base_url}/api/session/{session_id}",
            password=password,
            timeout=timeout,
        )
    except ReviewError as error:
        LOGGER.debug("could not read the session state: %s", error)
        return {}
    return response.get("data") or response


def _session_diagnostics(base_url: str, password: str, session_id: str) -> str:
    """Collect the session state a failed review should report.

    Args:
        base_url: The base URL of the OpenCode server.
        password: The server password.
        session_id: The session that failed.

    Returns:
        A one-line summary of the outcome, pending permissions, and recent tools.
    """
    details: list[str] = []
    session = _session_info(base_url, password, session_id)
    if session:
        details.append(f"outcome={session.get('outcome') or 'running'}")
        if session.get("agent"):
            details.append(f"agent={session['agent']}")

    try:
        response = api_request(f"{base_url}/api/session/{session_id}/permission", password=password)
        pending = response.get("data") or []
    except ReviewError:
        pending = []
    if pending:
        summaries = [
            f"{item.get('action')}({', '.join(item.get('resources') or [])})" for item in pending[:3]
        ]
        details.append(f"pending permissions: {'; '.join(summaries)}")

    try:
        messages = fetch_session_messages(base_url, password, session_id)
    except ReviewError:
        messages = []
    if messages:
        details.append(f"last message={messages[-1].get('type')}")
        last_assistant = next(
            (message for message in reversed(messages) if message.get("type") == "assistant"),
            None,
        )
        retry = (last_assistant or {}).get("retry") or {}
        if retry:
            retry_error = (retry.get("error") or {}).get("message") or "no detail"
            details.append(f"retry {retry.get('attempt')}: {retry_error}")
        recent_tools = [
            _tool_detail(part)
            for message in messages[-5:]
            for part in (message.get("content") or [])
            if part.get("type") == "tool"
        ]
        if recent_tools:
            details.append(f"recent tools: {' | '.join(recent_tools[-3:])}")

    return "; ".join(details) if details else "no session diagnostics"


def build_review_body(summary: str, unplaced: list[PlacedFinding], model: str) -> str:
    """Build the body of the pull request review.

    Args:
        summary: The summary the model wrote.
        unplaced: Findings that could not be attached to a diff line.
        model: The model that produced the review.

    Returns:
        The review body in markdown.
    """
    sections: list[str] = []
    if summary:
        sections.append(summary)
    if unplaced:
        bullets = []
        for placed in unplaced:
            detail = placed.finding.body.replace("\n", " ").strip()
            if len(detail) > 300:
                detail = detail[:300].rstrip() + "..."
            bullets.append(f"- `{placed.finding.path}:{placed.finding.line}` — {detail}")
        sections.append("### Not placed inline\n\n" + "\n".join(bullets))
    footer = f"Reviewed by [OpenCode](https://opencode.ai) using `{model}`."
    run_url = _workflow_run_url()
    if run_url:
        footer += f" [Workflow run]({run_url})."
    sections.append(footer)
    return "\n\n".join(sections).strip()


def _workflow_run_url() -> str | None:
    """Build the URL of the workflow run that is executing.

    Returns:
        The run URL, or None when the script does not run in GitHub Actions.
    """
    server = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not (server and repository and run_id):
        return None
    return f"{server}/{repository}/actions/runs/{run_id}"


def build_review_payload(
    placed_findings: list[PlacedFinding],
    unplaced: list[PlacedFinding],
    summary: str,
    model: str,
    head_commit: str,
) -> dict:
    """Build the payload for the pull request review endpoint.

    Args:
        placed_findings: Findings that will be posted inline.
        unplaced: Findings that could not be attached to a diff line.
        summary: The summary the model wrote.
        model: The model that produced the review.
        head_commit: The head commit of the pull request.

    Returns:
        The review payload.
    """
    comments = [
        {
            "path": placed.path,
            "line": placed.line,
            "side": placed.side,
            "body": placed.finding.body,
        }
        for placed in placed_findings
    ]
    return {
        "commit_id": head_commit,
        "body": build_review_body(summary, unplaced, model),
        "event": "COMMENT",
        "comments": comments,
    }


PROVIDER_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "local": os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8000/v1"),
}
PROVIDER_KEY_ENVIRONMENTS = {
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
PROVIDER_MODELS = {
    "opencode": DEFAULT_MODEL,
    "gemini": "gemini-2.0-flash",
    "openrouter": os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free"),
    "local": os.environ.get("OMLX_MODEL", "default"),
}
PREVIEW_EXIT_NEUTRAL = 78


def load_review_rubric(directory: Path) -> str:
    """Read the review command body used as the reviewer prompt.

    Args:
        directory: The repository the review runs in.

    Returns:
        The command body, or a minimal fallback rubric when the file is absent.
    """
    command_path = Path(directory) / ".opencode" / "commands" / "review-pr.md"
    try:
        raw = command_path.read_text(encoding="utf-8")
    except OSError:
        LOGGER.warning("no review command at %s; using a minimal rubric", command_path)
        return (
            "# Pull Request Review\n\n"
            "Review the pull request below and report genuine defects only, in the"
            " `### <path>:<line>` block format, followed by a `## Summary` section.\n\n"
            "## Target\n\n$ARGUMENTS\n"
        )
    if raw.startswith("---"):
        end = raw.find("~~~", 3)
        closing = raw.find("\n---", 3)
        end = closing + 4 if closing != -1 else 0
        raw = raw[end:]
    return raw


def provider_preflight(provider: str) -> str | None:
    """Check whether a provider is ready to review.

    Args:
        provider: One of ``opencode``, ``gemini``, ``openrouter`` or ``local``.

    Returns:
        None when the provider is ready, otherwise the failure reason.
    """
    if provider == "opencode":
        from shutil import which

        if which("opencode") is None:
            return "the opencode binary is not on PATH"
        return None
    key_environment = PROVIDER_KEY_ENVIRONMENTS.get(provider)
    if key_environment is not None:
        if not os.environ.get(key_environment):
            return f"the {key_environment} environment variable is not set"
        return None
    if provider == "local":
        try:
            settings = _local_provider_settings()
        except Exception as error:  # noqa: BLE001 - preflight must not raise
            return f"could not read oMLX settings: {error}"
        url = settings["base_url"].rstrip("/") + "/models"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - fixed scheme
                response.read()
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            return f"the oMLX server at {settings['base_url']} is not reachable: {error}"
        return None
    return f"unknown provider {provider!r}"


def _local_provider_settings() -> dict[str, str]:
    """Resolve the oMLX OpenAI-compatible settings.

    Returns:
        A mapping with ``base_url`` and ``api_key``.
    """
    base_url = os.environ.get("OMLX_BASE_URL")
    api_key = os.environ.get("OMLX_API_KEY")
    if base_url is None:
        try:
            from jobhunt.config import get_omlx_settings

            settings = get_omlx_settings()
            base_url = settings.base_url  # type: ignore[attr-defined]
            api_key = api_key or getattr(settings, "api_key", "")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - fall back to documented defaults
            base_url = PROVIDER_BASE_URLS["local"]
    return {"base_url": base_url.rstrip("/") + "/v1" if "://" in str(base_url) and not str(base_url).rstrip("/").endswith("v1") else str(base_url).rstrip("/"), "api_key": api_key or ""}


def openai_chat_completion(base_url: str, api_key: str, model: str, messages: list[dict]) -> str:
    """Call an OpenAI-compatible ``chat/completions`` endpoint.

    Args:
        base_url: The API root, without a trailing ``chat/completions``.
        api_key: The bearer token, or an empty string when none is needed.
        model: The model identifier to request.
        messages: The chat messages.

    Returns:
        The assistant message text.

    Raises:
        ReviewError: If the request fails or the answer is empty.
    """
    body = {"model": model, "messages": messages, "temperature": 0.0, "stream": False}
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:400]
        raise ReviewError(f"chat completion returned {error.code}: {detail}") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ReviewError(f"chat completion failed: {error}") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ReviewError(f"chat completion returned invalid JSON: {error}") from error
    answer = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not answer or not str(answer).strip():
        raise ReviewError("chat completion returned an empty answer")
    return str(answer)


def resolve_provider_connection(provider: str, model: str, key_env: str | None = None) -> tuple[str, str, str]:
    """Resolve the endpoint, key, and model for a direct provider call.

    Args:
        provider: One of ``gemini``, ``openrouter`` or ``local``.
        model: The model override, or the empty string for the provider default.
        key_env: Environment variable holding the API key; defaults to the
            provider's own variable.

    Returns:
        A tuple of base URL, API key and model identifier.

    Raises:
        ReviewError: If the provider has no usable credentials or settings.
    """
    if provider not in {"gemini", "openrouter", "local"}:
        raise ReviewError(f"provider {provider!r} cannot be called directly; use the opencode driver")
    if provider == "local":
        settings = _local_provider_settings()
        base_url, api_key = settings["base_url"], settings["api_key"]
        used_model = model or PROVIDER_MODELS["local"]
        if not base_url:
            raise ReviewError("no oMLX base URL available; set OMLX_BASE_URL")
        return base_url, api_key, used_model
    base_url = PROVIDER_BASE_URLS[provider]
    environment = key_env or PROVIDER_KEY_ENVIRONMENTS[provider]
    api_key = os.environ.get(environment, "")
    if not api_key:
        raise ReviewError(f"the {environment} environment variable is not set")
    return base_url, api_key, model or PROVIDER_MODELS.get(provider, model)


def review_pull_request_direct(
    number: int,
    provider: str,
    model: str,
    directory: Path,
    timeout: float,
    max_files: int,
    dry_run: bool,
    output_path: Path | None,
    key_env: str | None = None,
) -> int:
    """Review a pull request against an OpenAI-compatible provider.

    This is the fallback driver that bypasses OpenCode when its free tier is
    exhausted. It reuses the rubric, the finding parser and the posting logic
    of the OpenCode driver.

    Args:
        number: The pull request number.
        provider: The direct provider to call.
        model: The model override, or the empty string for the provider default.
        directory: The directory the review runs in.
        timeout: Reserved for parity with the OpenCode driver.
        max_files: The largest number of files to list.
        dry_run: When True, print the review instead of posting it.
        output_path: Where to write the raw model output, if anywhere.

    Returns:
        The number of inline comments posted.

    Raises:
        ReviewError: If the review cannot be produced or posted.
    """
    del timeout  # the HTTP request timeout bounds the single API call
    pull_request = fetch_pull_request(number)
    if pull_request.get("state") != "OPEN":
        raise ReviewError(f"pull request #{number} is {pull_request.get('state')}, not OPEN")

    patch = fetch_pull_request_diff(number)
    diff_files = parse_unified_diff(patch)
    if not diff_files:
        raise ReviewError(f"pull request #{number} has no diff to review")

    arguments = build_command_arguments(pull_request, diff_files, max_files, patch)
    rubric = load_review_rubric(directory)
    base_url, api_key, used_model = resolve_provider_connection(provider, model, key_env)

    LOGGER.info("Reviewing PR #%s with %s via %s", number, used_model, provider)
    LOGGER.info("Diff covers %d changed files", len(diff_files))

    from datetime import datetime, timezone

    prefix = (
        f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
        "You are the read-only pr-reviewer. Follow the instructions verbatim.\n"
    )
    answer = openai_chat_completion(
        base_url,
        api_key,
        used_model,
        messages=[
            {"role": "system", "content": prefix + rubric.strip()},
            {"role": "user", "content": arguments},
        ],
    )
    return publish_model_answer(answer, pull_request, diff_files, used_model, dry_run, output_path)


def publish_model_answer(
    answer: str,
    pull_request: dict,
    diff_files: dict[str, DiffFile],
    model: str,
    dry_run: bool,
    output_path: Path | None,
) -> int:
    """Parse, place and post a model's review answer.

    Args:
        answer: The raw model output with findings and a summary.
        pull_request: The pull request metadata.
        diff_files: The lines each changed file contributes.
        model: The model that produced the review.
        dry_run: When True, print the payload instead of posting it.
        output_path: Where to write the raw answer, if anywhere.

    Returns:
        The number of inline comments posted.
    """
    if output_path is not None:
        output_path.write_text(answer, encoding="utf-8")
        LOGGER.info("Wrote raw review output to %s", output_path)

    findings, summary = parse_findings(answer)
    LOGGER.info("Parsed %d findings from the review", len(findings))

    placed: list[PlacedFinding] = []
    unplaced: list[PlacedFinding] = []
    for finding in findings:
        resolved = resolve_finding(finding, diff_files)
        LOGGER.info(
            "Finding %s:%s -> %s%s",
            finding.path,
            finding.line,
            resolved.status,
            f" (line {resolved.line})" if resolved.line is not None else "",
        )
        if resolved.line is None:
            unplaced.append(resolved)
        else:
            placed.append(resolved)

    if not findings:
        LOGGER.info("The review found nothing to report")
        return 0

    payload = build_review_payload(placed, unplaced, summary, model, pull_request["headRefOid"])
    if dry_run:
        print(json.dumps(payload, indent=2))
        return len(placed)

    number = pull_request["number"]
    repository = fetch_repository_name()
    try:
        post_review(repository, number, payload)
    except ReviewError as error:
        LOGGER.warning("the review was rejected as a whole, posting comments one by one: %s", error)
        post_comments_individually(repository, number, payload)
    print(f"Posted {len(placed)} inline comment(s) on PR #{number}.")
    if unplaced:
        print(f"Added {len(unplaced)} finding(s) to the review body.")
    return len(placed)


def review_pull_request(
    number: int,
    model: str,
    command: str,
    directory: Path,
    timeout: float,
    max_files: int,
    dry_run: bool,
    output_path: Path | None,
) -> int:
    """Review a pull request and post the result.

    Args:
        number: The pull request number.
        model: The model to review with, in ``provider/model-id`` form.
        command: The OpenCode command to run.
        directory: The directory the review runs in.
        timeout: How long to allow the review to take.
        max_files: The largest number of files to list for the model.
        dry_run: When True, print the review instead of posting it.
        output_path: Where to write the raw model output, if anywhere.

    Returns:
        The number of inline comments posted.

    Raises:
        ReviewError: If the review cannot be produced or posted.
    """
    pull_request = fetch_pull_request(number)
    if pull_request.get("state") != "OPEN":
        raise ReviewError(f"pull request #{number} is {pull_request.get('state')}, not OPEN")

    patch = fetch_pull_request_diff(number)
    diff_files = parse_unified_diff(patch)
    if not diff_files:
        raise ReviewError(f"pull request #{number} has no diff to review")

    arguments = build_command_arguments(pull_request, diff_files, max_files, patch)
    fetch_base_commit(pull_request["baseRefOid"])
    LOGGER.info("Reviewing PR #%s with %s", number, model)
    LOGGER.info("Diff covers %d changed files", len(diff_files))

    server = OpenCodeServer()
    try:
        session_id = create_session(server.base_url, server.password, model, directory)
        LOGGER.info("Created session %s", session_id)
        run_review_command(server.base_url, server.password, session_id, command, arguments)
        session_agent = _session_info(server.base_url, server.password, session_id).get("agent")
        LOGGER.info("Review session agent %s", session_agent or "unset")
        try:
            answer = run_with_deadline(
                lambda: wait_for_review(server.base_url, server.password, session_id, timeout),
                timeout + DRIVER_GRACE_SECONDS,
            )
        except DriverTimeoutError as error:
            for line in server.recent_output():
                LOGGER.error("opencode: %s", line)
            raise ReviewError(
                f"{error}; " + _session_diagnostics(server.base_url, server.password, session_id)
            ) from error
        except ReviewError:
            for line in server.recent_output():
                LOGGER.error("opencode: %s", line)
            raise
    finally:
        server.close()

    if output_path is not None:
        output_path.write_text(answer, encoding="utf-8")
        LOGGER.info("Wrote raw review output to %s", output_path)
    return publish_model_answer(answer, pull_request, diff_files, model, dry_run, output_path)


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface.

    Args:
        argv: The command line arguments, defaulting to the process arguments.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-number", type=int, default=None, help="The pull request number to review.")
    parser.add_argument(
        "--provider",
        default="opencode",
        choices=sorted(set(PROVIDER_BASE_URLS) | {"opencode"}),
        help="The reviewer backend to use.",
    )
    parser.add_argument(
        "--api-key-env",
        default=None,
        help="Environment variable holding the provider API key (default: per-provider).",
    )
    parser.add_argument("--model", default=None, help="The model to review with, as provider/model-id.")
    parser.add_argument("--command", default=DEFAULT_COMMAND, help="The OpenCode command to run.")
    parser.add_argument("--directory", default=".", help="The directory the review runs in.")
    parser.add_argument("--timeout", default=DEFAULT_TIMEOUT_SECONDS, type=float, help="Seconds to allow the review to take.")
    parser.add_argument("--max-files", default=DEFAULT_MAX_FILES, type=int, help="Most files to list for the model.")
    parser.add_argument("--output", type=Path, default=None, help="Where to write the raw model output.")
    parser.add_argument("--dry-run", action="store_true", help="Print the review instead of posting it.")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Exit 0 when the provider is ready, 78 (neutral) when it is not; no review runs.",
    )
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    if arguments.api_key_env:
        if arguments.provider in PROVIDER_KEY_ENVIRONMENTS and not os.environ.get(arguments.api_key_env):
            raise SystemExit(f"{arguments.provider} needs an API key in {arguments.api_key_env}")

    if arguments.preflight:
        reason = provider_preflight(arguments.provider)
        if reason is not None:
            LOGGER.error("provider %s not ready: %s", arguments.provider, reason)
            return PREVIEW_EXIT_NEUTRAL
        print(f"provider {arguments.provider} is ready")
        return 0

    if arguments.pr_number is None:
        parser.error("--pr-number is required unless --preflight is given")

    if arguments.model is None:
        arguments.model = PROVIDER_MODELS.get(arguments.provider, DEFAULT_MODEL)
    try:
        common = dict(
            number=arguments.pr_number,
            model=arguments.model,
            directory=Path(arguments.directory).resolve(),
            timeout=arguments.timeout,
            max_files=arguments.max_files,
            dry_run=arguments.dry_run,
            output_path=arguments.output,
        )
        if arguments.provider == "opencode":
            review_pull_request(command=arguments.command, **common)
        else:
            review_pull_request_direct(provider=arguments.provider, key_env=arguments.api_key_env, **common)
    except ReviewError as error:
        LOGGER.error("%s", error)
        if arguments.output is not None:
            arguments.output.write_text(f"Review failed: {error}\n", encoding="utf-8")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
