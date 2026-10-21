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
from dataclasses import dataclass, field
from pathlib import Path

LOGGER = logging.getLogger("pr_review")

DEFAULT_MODEL = "opencode/big-pickle"
DEFAULT_COMMAND = "review-pr"
DEFAULT_PORT = 4097
DEFAULT_TIMEOUT_SECONDS = 1200
DEFAULT_MAX_FILES = 40
SNAP_DISTANCE = 3

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
FINDING_HEADING = re.compile(r"^###\s+(?P<path>[^\s:]+):(?P<line>\d+)(?P<rest>.*)$")
SUMMARY_HEADING = re.compile(r"^##\s+Summary\s*$", re.IGNORECASE)
SERVER_URL = re.compile(r"server listening on (?P<url>\S+)")
SERVER_PASSWORD = re.compile(r"server password (?P<password>\S+)")


class ReviewError(RuntimeError):
    """Raised when the review cannot be produced or posted."""


@dataclass
class DiffFile:
    """The lines a single file contributes to a pull request diff.

    Attributes:
        path: Repository-relative path of the file.
        changed_lines: New-side line numbers the diff adds or modifies.
        hunk_lines: New-side line numbers inside a hunk, context lines included.
    """

    path: str
    changed_lines: set[int] = field(default_factory=set)
    hunk_lines: set[int] = field(default_factory=set)


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
    """

    finding: Finding
    path: str | None
    line: int | None
    status: str


def parse_unified_diff(patch: str) -> dict[str, DiffFile]:
    """Map every file in a unified diff to the lines it adds or modifies.

    Args:
        patch: The unified diff text.

    Returns:
        A mapping of repository-relative path to its diff lines.
    """
    files: dict[str, DiffFile] = {}
    current: DiffFile | None = None
    new_line = 0
    in_hunk = False

    for raw in patch.splitlines():
        if raw.startswith("diff --git "):
            current = None
            in_hunk = False
            continue
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                current = None
                in_hunk = False
                continue
            path = target[2:] if target.startswith("b/") else target
            current = files.setdefault(path, DiffFile(path=path))
            in_hunk = False
            continue
        if raw.startswith("--- "):
            continue
        hunk = HUNK_HEADER.match(raw)
        if hunk is not None:
            new_line = int(hunk.group(3))
            in_hunk = current is not None
            continue
        if current is None or not in_hunk:
            continue
        if raw.startswith("+"):
            current.changed_lines.add(new_line)
            current.hunk_lines.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue
        elif raw.startswith(" ") or raw == "":
            current.hunk_lines.add(new_line)
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


def resolve_finding(finding: Finding, diff_files: dict[str, DiffFile]) -> PlacedFinding:
    """Decide where a finding can be posted, if anywhere.

    Args:
        finding: The finding as the model wrote it.
        diff_files: The lines each changed file contributes.

    Returns:
        The finding together with its resolved position and the reason for it.
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


def build_command_arguments(pull_request: dict, diff_files: dict[str, DiffFile], max_files: int) -> str:
    """Build the target description handed to the review command.

    Args:
        pull_request: The pull request metadata.
        diff_files: The lines each changed file contributes.
        max_files: The largest number of files to list.

    Returns:
        The text substituted for ``$ARGUMENTS`` in the review command.
    """
    return (
        f"Pull request: #{pull_request['number']}\n"
        f"Title: {pull_request['title']}\n"
        f"Base commit: {pull_request['baseRefOid']}\n"
        f"Head commit: {pull_request['headRefOid']}\n"
        "\n"
        "Citable lines (new-file line numbers, cite these and no others):\n"
        f"{render_citable_lines(diff_files, max_files)}"
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


def api_request(url: str, method: str = "GET", body: dict | None = None, password: str | None = None) -> dict:
    """Call the OpenCode HTTP API.

    Args:
        url: The absolute URL to call.
        method: The HTTP method to use.
        body: The JSON body to send.
        password: The server password to authenticate with.

    Returns:
        The decoded response body, or an empty mapping for an empty response.

    Raises:
        ReviewError: If the request fails.
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
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise ReviewError(f"{method} {url} returned {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise ReviewError(f"{method} {url} failed: {error.reason}") from error
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


def wait_for_review(base_url: str, password: str, session_id: str, timeout: float) -> str:
    """Wait for the review to finish and return the model's answer.

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
    while time.monotonic() < deadline:
        response = api_request(f"{base_url}/api/session/{session_id}/message", password=password)
        messages = response.get("data") or []
        messages.sort(key=lambda message: (message.get("time") or {}).get("created") or 0)
        answer = _final_answer(messages)
        if answer is not None:
            return answer
        outcome = _session_outcome(base_url, password, session_id)
        if outcome in {"failed", "error", "aborted"}:
            raise ReviewError(f"the review session ended with outcome {outcome!r}")
        time.sleep(5)
    raise ReviewError(f"the review did not finish within {timeout:.0f} seconds")


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


def _session_outcome(base_url: str, password: str, session_id: str) -> str | None:
    """Read the outcome of a session.

    Args:
        base_url: The base URL of the OpenCode server.
        password: The server password.
        session_id: The session to inspect.

    Returns:
        The outcome, or None when the session is still running.
    """
    try:
        response = api_request(f"{base_url}/api/session/{session_id}", password=password)
    except ReviewError:
        return None
    session = response.get("data") or response
    return session.get("outcome")


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
            "side": "RIGHT",
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

    arguments = build_command_arguments(pull_request, diff_files, max_files)
    fetch_base_commit(pull_request["baseRefOid"])
    LOGGER.info("Reviewing PR #%s with %s", number, model)
    LOGGER.info("Diff covers %d changed files", len(diff_files))

    server = OpenCodeServer()
    try:
        session_id = create_session(server.base_url, server.password, model, directory)
        LOGGER.info("Created session %s", session_id)
        run_review_command(server.base_url, server.password, session_id, command, arguments)
        answer = wait_for_review(server.base_url, server.password, session_id, timeout)
    finally:
        server.close()

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


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface.

    Args:
        argv: The command line arguments, defaulting to the process arguments.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-number", required=True, type=int, help="The pull request number to review.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="The model to review with, as provider/model-id.")
    parser.add_argument("--command", default=DEFAULT_COMMAND, help="The OpenCode command to run.")
    parser.add_argument("--directory", default=".", help="The directory the review runs in.")
    parser.add_argument("--timeout", default=DEFAULT_TIMEOUT_SECONDS, type=float, help="Seconds to allow the review to take.")
    parser.add_argument("--max-files", default=DEFAULT_MAX_FILES, type=int, help="Most files to list for the model.")
    parser.add_argument("--output", type=Path, default=None, help="Where to write the raw model output.")
    parser.add_argument("--dry-run", action="store_true", help="Print the review instead of posting it.")
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        review_pull_request(
            number=arguments.pr_number,
            model=arguments.model,
            command=arguments.command,
            directory=Path(arguments.directory).resolve(),
            timeout=arguments.timeout,
            max_files=arguments.max_files,
            dry_run=arguments.dry_run,
            output_path=arguments.output,
        )
    except ReviewError as error:
        LOGGER.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
