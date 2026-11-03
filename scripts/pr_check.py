#!/usr/bin/env python3
"""Deterministic pull request convention checker.

The checker encodes ``AGENTS.md`` and ``docs/`` as rules that need no model,
no network, and no secrets. It reports only *new* debt: every rule runs
against the base and the head tree, and a violation whose key ``(rule, path,
symbol)`` already exists in the base tree is treated as existing debt and not
reported. Findings are sorted by ``(path, line, rule)`` with fixed message
strings and no timestamps, so the output is snapshot-testable.

Rules:

| ID | Severity | Rule |
|---|---|---|
| JH001 | blocking | print or pprint in library code (src/**, outside cli.py) |
| JH002 | blocking | swallowed errors: pass-only, empty-return, or silent except |
| JH003 | blocking | unguarded ``self.agent`` access in app/** |
| JH004 | blocking | ``compose()`` defined on a BaseScreen subclass |
| JH005 | blocking | raw error strings appended to ``self.messages`` |
| JH006 | blocking | blocking I/O inside ``async def`` |
| JH013 | blocking | documented widget IDs missing from app/** (docs/SCREENS.md) |
| JH014 | blocking | CREATE TABLE columns not matching docs/DATABASE_AND_CONFIG.md |
| JH015 | blocking | documented JobHuntDB methods missing from the class |
| JH018 | blocking | pr-reviewer agent missing read-only denies |
| JH019 | blocking | workflow safety: pull_request_target, unpinned actions, secrets in run |
| JH007 | advisory | module logger not using ``__name__`` |
| JH008 | advisory | abbreviated names (db, e, exc, ...) on new parameters/targets |
| JH009 | blocking | JobHuntDB/get_db called with ``db_path=`` |
| JH010 | advisory | screens built with ``db=`` instead of ``database=`` |
| JH011 | advisory | time.sleep in a test function body |
| JH012 | blocking | network/adapter tests without @pytest.mark.integration |
| JH016 | advisory | documented source adapters missing from sources/** |
| JH017 | advisory | documented scoring constants missing from scoring/** |
| JH020 | advisory | [project.scripts] targets missing from source |
| JH021 | advisory | new public module/class/function without a docstring |

Exit codes: 0 when no blocking finding remains, 1 when one does, 2 on an
internal error. The ``--post`` mode inlines findings as PR review comments
through the same payload builder as ``scripts/pr_review.py`` and degrades to
``$GITHUB_STEP_SUMMARY`` when the token cannot write reviews.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import json
import logging
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("pr_check")

CONFIG_FILE = ".prcheck.toml"
IGNORE_PATTERN = re.compile(r"#\s*prcheck:\s*ignore\s+(?P<rule>JH\d{3})(?:\s+(?P<reason>\S.*))?")

BLOCKING = "blocking"
ADVISORY = "advisory"

SEVERITY = {
    "JH001": BLOCKING,
    "JH002": BLOCKING,
    "JH003": BLOCKING,
    "JH004": BLOCKING,
    "JH005": BLOCKING,
    "JH006": BLOCKING,
    "JH007": ADVISORY,
    "JH008": ADVISORY,
    "JH009": BLOCKING,
    "JH010": ADVISORY,
    "JH011": ADVISORY,
    "JH012": BLOCKING,
    "JH013": BLOCKING,
    "JH014": BLOCKING,
    "JH015": BLOCKING,
    "JH016": ADVISORY,
    "JH017": ADVISORY,
    "JH018": BLOCKING,
    "JH019": BLOCKING,
    "JH020": ADVISORY,
    "JH021": ADVISORY,
}

ABBREVIATED_NAMES = {"db", "e", "exc", "err", "cfg", "msg", "req", "res", "tmp", "tbl"}
INTEGRATION_MARKER_PATTERN = re.compile(r"pytest\.mark\.integration")
DOCS_DB_FILE = "docs/DATABASE_AND_CONFIG.md"
DOCS_SCREENS_FILE = "docs/SCREENS.md"
DOCS_SOURCES_FILE = "docs/SOURCES.md"
DOCS_SCORING_FILE = "docs/SCORING.md"
AGENT_FILE = ".opencode/agents/pr-reviewer.md"
ENTRY_POINTS = "pyproject.toml"


class CheckError(RuntimeError):
    """Raised when the checker cannot run its own pipeline."""


@dataclass
class CheckFinding:
    """A single rule violation.

    Attributes:
        rule: The rule identifier, such as ``JH002``.
        path: Repository-relative path the finding belongs to.
        line: Line number in the tree the rule ran on.
        severity: ``blocking`` or ``advisory``.
        message: Deterministic, human-readable description of the violation.
        symbol: Stable identity of the violation used for debt filtering.
    """

    rule: str
    path: str
    line: int
    severity: str
    message: str
    symbol: str

    def key(self) -> tuple[str, str, str]:
        """Return the identity used to tell new debt from existing debt.

        Returns:
            The ``(rule, path, symbol)`` triple.
        """
        return (self.rule, self.path, self.symbol)

    def slug(self) -> str:
        """Return the one-line description used in reports and comments.

        Returns:
            ``rule severity path:line message``.
        """
        return f"**{self.rule}** ({self.severity}) `{self.path}:{self.line}` - {self.message}"


@dataclass
class Suppression:
    """A finding that was deliberately silenced.

    Attributes:
        rule: The suppressed rule identifier.
        path: Path the finding belongs to.
        line: Line the finding belongs to.
        reason: The mandatory reason string.
        source: Where the suppression came from.
    """

    rule: str
    path: str
    line: int
    reason: str
    source: str


@dataclass
class CheckConfig:
    """Suppression configuration loaded from ``.prcheck.toml``.

    Attributes:
        disable: Rule identifiers turned off entirely.
        allow: Path patterns whose findings are advisory-only.
        config_path: File the configuration came from, for reporting.
    """

    disable: set[str] = field(default_factory=set)
    allow: list[str] = field(default_factory=list)
    config_path: str | None = None


@dataclass
class RuleContext:
    """The tree a rule runs against.

    Attributes:
        tree: Root directory the rule reads files from.
        python_paths: ``.py`` paths (repository-relative) present in the tree
            and relevant to the run.
    """

    tree: Path
    python_paths: list[str]

    def read_text(self, path: str) -> str | None:
        """Read a file from the tree.

        Args:
            path: Repository-relative path.

        Returns:
            The text, or None when the tree does not contain the file.
        """
        try:
            return (self.tree / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def exists(self, path: str) -> bool:
        """Test whether the tree contains a file.

        Args:
            path: Repository-relative path.

        Returns:
            True when the file exists in the tree.
        """
        return (self.tree / path).is_file()

    def python_files(self) -> list[tuple[str, str]]:
        """Return the relevant python files of the tree with their text.

        Returns:
            A list of ``(path, source)`` pairs that parse cleanly; files with
            syntax errors are skipped with a warning.
        """
        pairs: list[tuple[str, str]] = []
        for path in self.python_paths:
            source = self.read_text(path)
            if source is None:
                continue
            pairs.append((path, source))
        return pairs


RuleFunction = Callable[[RuleContext], list[CheckFinding]]
RULES: dict[str, RuleFunction] = {}


def rule(rule_id: str) -> Callable[[RuleFunction], RuleFunction]:
    """Register a rule function.

    Args:
        rule_id: The JH identifier of the rule.

    Returns:
        A decorator adding the function to the rule registry.
    """

    def decorator(function: RuleFunction) -> RuleFunction:
        RULES[rule_id] = function
        return function

    return decorator


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def parent_map(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    """Build a child-to-parent mapping for a module.

    Args:
        tree: The module AST.

    Returns:
        A mapping of every visited node to its parent.
    """
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def enclosing_qualname(tree: ast.Module, node: ast.AST) -> str:
    """Return the dotted name of the function or class enclosing a node.

    Args:
        tree: The module AST the node belongs to.
        node: The node to name.

    Returns:
        A dotted name such as ``JobHuntDB.get_job`` or ``""``.
    """
    parents = parent_map(tree)
    chain: list[str] = []
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            chain.append(current.name)
        current = parents.get(current)
    return ".".join(reversed(chain))


def _is_log_or_raise(body: list[ast.stmt]) -> bool:
    """Test whether a handler body surfaces an error or re-raises.

    Logging to any logger, updating a status widget, notifying the user, and
    re-raising all count as surfacing.

    Args:
        body: The handler statement body.

    Returns:
        True when the body contains a raise or a call that surfaces the error.
    """
    surfacing_attributes = {
        "log",
        "info",
        "warning",
        "error",
        "debug",
        "critical",
        "exception",
        "notify",
        "set_message",
    }
    for node in body:
        if isinstance(node, ast.Raise):
            return True
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                function = child.func
                name = ""
                if isinstance(function, ast.Attribute):
                    name = function.attr
                    name = (
                        getattr(function.value, "id", "") + "." + name
                        if isinstance(function.value, ast.Name)
                        else name
                    )
                elif isinstance(function, ast.Name):
                    name = function.id
                parts = name.split(".")
                if any(part.startswith("log") or part in surfacing_attributes for part in parts):
                    return True
    return False


def _handler_name(node: ast.ExceptHandler) -> str:
    """Return a readable label for an except clause.

    Args:
        node: The handler node.

    Returns:
        ``bare`` or the exception type expression such as ``OSError``.
    """
    if node.type is None:
        return "bare"
    name = ast.unparse(node.type)
    return name.split(".")[-1]


# ---------------------------------------------------------------------------
# Phase A: convention rules
# ---------------------------------------------------------------------------


@rule("JH001")
def check_print_in_library(context: RuleContext) -> list[CheckFinding]:
    """Flag print and pprint calls in library code.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every print call outside ``cli.py``.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith("src/jobhunt/") or Path(path).name == "cli.py":
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = ""
            if isinstance(function, ast.Name):
                name = function.id
            elif isinstance(function, ast.Attribute):
                name = function.attr
            if name not in {"print", "pprint", "pformat"}:
                continue
            findings.append(
                CheckFinding(
                    rule="JH001",
                    path=path,
                    line=node.lineno,
                    severity=SEVERITY["JH001"],
                    message=f"print in library code; use logging.getLogger(__name__) ({name} call)",
                    symbol=f"print:{enclosing_qualname(tree, node)}",
                )
            )
    return findings


@rule("JH002")
def check_swallowed_error(context: RuleContext) -> list[CheckFinding]:
    """Flag except handlers that hide a failure.

    A handler is flagged when its body is only ``pass``, returns an empty
    falsy value without logging, or catches broadly with no log and no raise.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every swallowed error.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith(("src/jobhunt/", "scripts/")):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            qualname = enclosing_qualname(tree, node)
            if _is_log_or_raise(node.body):
                continue
            label = _handler_name(node)
            symbol = f"except:{label}:{path}:{qualname}"
            broad = label in {"bare", "Exception", "BaseException"}
            if len(node.body) == 1:
                statement = node.body[0]
                if isinstance(statement, ast.Pass):
                    if label == "ImportError":
                        # An optional dependency guard is the idiomatic reason
                        # for `pass`; hiding a real ImportError is rare enough
                        # here that the noise outweighs the protection.
                        continue
                    findings.append(
                        CheckFinding(
                            rule="JH002",
                            path=path,
                            line=node.lineno,
                            severity=SEVERITY["JH002"],
                            message=f"swallowed error: `except {label}: pass` without logging or re-raising",
                            symbol=symbol,
                        )
                    )
                    continue
                if isinstance(statement, ast.Return) and statement.value is not None:
                    value = ast.unparse(statement.value)
                    if value in {"None", "False", "[]", "{}", "()", '""', "''"} and broad:
                        findings.append(
                            CheckFinding(
                                rule="JH002",
                                path=path,
                                line=node.lineno,
                                severity=SEVERITY["JH002"],
                                message=f"swallowed error: `except {label}:` returns {value} without logging or raising",
                                symbol=symbol,
                            )
                        )
                        continue
                continue
            if broad:
                findings.append(
                    CheckFinding(
                        rule="JH002",
                        path=path,
                        line=node.lineno,
                        severity=SEVERITY["JH002"],
                        message=f"swallowed error: broad `except {label}` with no logging or re-raising",
                        symbol=symbol,
                    )
                )
    return findings


@rule("JH003")
def check_unguarded_agent(context: RuleContext) -> list[CheckFinding]:
    """Flag direct attribute chains on ``self.agent`` in the TUI app.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every call on ``self.agent.<attr>(...)``.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith("src/jobhunt/app/"):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            value = node.func.value
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "agent"
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
            ):
                findings.append(
                    CheckFinding(
                        rule="JH003",
                        path=path,
                        line=node.lineno,
                        severity=SEVERITY["JH003"],
                        message=(
                            f"unguarded agent access: self.agent.{node.func.attr}(...); agent may be None. "
                            "Call self._require_agent() first"
                        ),
                        symbol=f"self.agent.{node.func.attr}:{enclosing_qualname(tree, node)}",
                    )
                )
    return findings


@rule("JH004")
def check_compose_in_screen(context: RuleContext) -> list[CheckFinding]:
    """Flag compose() defined on a screen subclass.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every BaseScreen subclass defining compose().
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith("src/jobhunt/app/"):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [ast.unparse(base).split(".")[-1].split("[")[0] for base in node.bases]
            if not any(name.endswith("Screen") for name in bases):
                continue
            if node.name == "BaseScreen":
                continue
            for statement in node.body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == "compose":
                    findings.append(
                        CheckFinding(
                            rule="JH004",
                            path=path,
                            line=statement.lineno,
                            severity=SEVERITY["JH004"],
                            message=(
                                f"{node.name} defines compose(); screen bodies belong in _get_content() "
                                "(AGENTS.md TUI screens)"
                            ),
                            symbol=f"compose:{node.name}",
                        )
                    )
    return findings


@rule("JH005")
def check_chat_raw_error(context: RuleContext) -> list[CheckFinding]:
    """Flag raw exception text appended to the chat transcript.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every self.messages.append that interpolates a bound
        exception variable.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith("src/jobhunt/app/"):
            continue
        try:
            parsed_tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(parsed_tree):
            if not isinstance(node, ast.ExceptHandler) or node.name is None:
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                function = child.func
                if not (
                    isinstance(function, ast.Attribute)
                    and function.attr == "append"
                    and isinstance(function.value, ast.Attribute)
                    and function.value.attr == "messages"
                    and isinstance(function.value.value, ast.Name)
                    and function.value.value.id == "self"
                ):
                    continue
                if not child.args:
                    continue
                bound = node.name
                interpolated = any(
                    isinstance(part, ast.Name) and part.id == bound for part in ast.walk(child.args[0])
                )
                if not interpolated:
                    continue
                entry = ast.unparse(child.args[0])
                if len(entry) > 60:
                    entry = entry[:60] + ""
                findings.append(
                    CheckFinding(
                        rule="JH005",
                        path=path,
                        line=child.lineno,
                        severity=SEVERITY["JH005"],
                        message=(
                            f"chat transcript receives raw error text ({entry}); store a neutral "
                            "marker such as '[error: see logs]' instead (AGENTS.md Chat)"
                        ),
                        symbol=f"raw-error:{enclosing_qualname(parsed_tree, node)}",
                    )
                )
    return findings


@rule("JH006")
def check_blocking_io_in_async(context: RuleContext) -> list[CheckFinding]:
    """Flag blocking I/O calls inside async functions.

    Args:
        context: The tree being checked.

    Returns:
        Findings for time.sleep, requests, subprocess and direct
        self.database calls made on the event loop.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith("src/jobhunt/app/"):
            continue
        try:
            module_tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(module_tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            parents = parent_map(module_tree)
            for child in ast.walk(node):
                if child is node:
                    continue
                if not isinstance(child, ast.Call):
                    continue
                if _inside_dispatch(child, parents):
                    continue
                kind = _blocking_call_kind(child)
                if kind:
                    findings.append(
                        CheckFinding(
                            rule="JH006",
                            path=path,
                            line=child.lineno,
                            severity=SEVERITY["JH006"],
                            message=(
                                f"blocking {kind} inside async function {node.name}; "
                                "dispatch with self._run_worker(asyncio.to_thread(...))"
                            ),
                            symbol=f"blocking:{kind}:{path}:{node.name}",
                        )
                    )
    return findings


def _blocking_call_kind(node: ast.Call) -> str | None:
    """Classify a call as blocking I/O.

    Args:
        node: The call node.

    Returns:
        A short kind label, or None for non-blocking calls.
    """
    function = node.func
    if isinstance(function, ast.Attribute):
        base = function.value
        if isinstance(base, ast.Name):
            if base.id == "time" and function.attr == "sleep":
                return "time.sleep"
            if base.id == "requests":
                return f"requests.{function.attr}"
            if base.id == "subprocess" and function.attr in {
                "run",
                "call",
                "check_call",
                "check_output",
                "getoutput",
            }:
                return f"subprocess.{function.attr}"
            if base.id == "self" and function.attr.startswith(("save", "delete_")):
                return f"database.{function.attr}"
        if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id == "self":
            if base.attr == "database" and not function.attr.startswith("path"):
                return f"self.database.{function.attr}"
    if isinstance(function, ast.Name) and function.id in {"input", "open"}:
        return None
    return None


def _inside_dispatch(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Test whether a call is wrapped in the async dispatch helpers.

    Args:
        node: The call to test.
        parents: The child-to-parent mapping of the enclosing tree.

    Returns:
        True when the ancestor chain contains asyncio.to_thread or
        ``self._run_worker``.
    """
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.Call):
            function = current.func
            name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
            if name in {"to_thread", "_run_worker", "run_in_executor"}:
                return True
        current = parents.get(current)
    return False


@rule("JH007")
def check_module_logger(context: RuleContext) -> list[CheckFinding]:
    """Flag logging.getLogger(<literal>) not using __name__.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every hardcoded module logger name.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith("src/jobhunt/"):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "getLogger" or not isinstance(node.func.value, ast.Name):
                continue
            if node.func.value.id != "logging":
                continue
            if node.args and isinstance(node.args[0], ast.Constant):
                name = node.args[0].value
                if name == "__name__":
                    continue
                findings.append(
                    CheckFinding(
                        rule="JH007",
                        path=path,
                        line=node.lineno,
                        severity=SEVERITY["JH007"],
                        message=f"module logger should use logging.getLogger(__name__) (found {name!r})",
                        symbol=f"logger:{name}:{enclosing_qualname(tree, node)}",
                    )
                )
    return findings


@rule("JH008")
def check_abbreviated_names(context: RuleContext) -> list[CheckFinding]:
    """Flag abbreviated parameter and target names.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every banned short name.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith(("src/jobhunt/", "tests/")):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args
                names = [arg.arg for arg in arguments.posonlyargs + arguments.args + arguments.kwonlyargs]
                names += [arg.arg for arg in (arguments.vararg, arguments.kwarg) if arg]
                for name in names:
                    if name in ABBREVIATED_NAMES:
                        findings.append(
                            CheckFinding(
                                rule="JH008",
                                path=path,
                                line=node.lineno,
                                severity=SEVERITY["JH008"],
                                message=(
                                    f"abbreviated name {name!r} on parameter of {node.name}; "
                                    "use a descriptive name (AGENTS.md Naming)"
                                ),
                                symbol=f"name:{node.name}:{name}",
                            )
                        )
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ABBREVIATED_NAMES:
                        findings.append(
                            CheckFinding(
                                rule="JH008",
                                path=path,
                                line=node.lineno,
                                severity=SEVERITY["JH008"],
                                message=(
                                    f"abbreviated name {target.id!r} on target; use a descriptive "
                                    "name (AGENTS.md Naming)"
                                ),
                                symbol=f"target:{target.id}:{enclosing_qualname(tree, node)}",
                            )
                        )
    return findings


@rule("JH009")
def check_db_path_kwarg(context: RuleContext) -> list[CheckFinding]:
    """Flag JobHuntDB(...) and get_db(db_path=...) calls.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every db_path keyword argument.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith(("src/jobhunt/", "tests/", "scripts/")):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, (ast.Name, ast.Attribute)):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if name not in {"JobHuntDB", "get_db"}:
                continue
            for keyword in node.keywords:
                if keyword.arg == "db_path":
                    findings.append(
                        CheckFinding(
                            rule="JH009",
                            path=path,
                            line=node.lineno,
                            severity=SEVERITY["JH009"],
                            message=(
                                f"{name}() takes database_path=, not db_path= "
                                "(AGENTS.md Naming: JobHuntDB constructor parameter)"
                            ),
                            symbol=f"db_path:{enclosing_qualname(tree, node)}",
                        )
                    )
    return findings


@rule("JH010")
def check_screen_db_kwarg(context: RuleContext) -> list[CheckFinding]:
    """Flag screens constructed with db= instead of database=.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every Screen* call with a db keyword.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith(("src/jobhunt/", "tests/")):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, (ast.Name, ast.Attribute)):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if "Screen" not in name:
                continue
            for keyword in node.keywords:
                if keyword.arg == "db":
                    findings.append(
                        CheckFinding(
                            rule="JH010",
                            path=path,
                            line=node.lineno,
                            severity=SEVERITY["JH010"],
                            message=f"{name} takes database=, not db= (AGENTS.md Tests)",
                            symbol=f"db-kwarg:{name}:{enclosing_qualname(tree, node)}",
                        )
                    )
    return findings


@rule("JH011")
def check_fixed_sleep_tests(context: RuleContext) -> list[CheckFinding]:
    """Flag time.sleep inside test bodies.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every fixed sleep in a test function.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith("tests/"):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test") and not _inside_test_class(tree, node):
                continue
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    if child.func.attr == "sleep" and isinstance(child.func.value, ast.Name):
                        if child.func.value.id == "time":
                            findings.append(
                                CheckFinding(
                                    rule="JH011",
                                    path=path,
                                    line=child.lineno,
                                    severity=SEVERITY["JH011"],
                                    message=(
                                        f"fixed time.sleep in test {node.name}; poll for the target "
                                        "state and wait for workers to settle instead (AGENTS.md Tests)"
                                    ),
                                    symbol=f"sleep:{node.name}:{path}",
                                )
                            )
    return findings


def _inside_test_class(tree: ast.Module, node: ast.AST) -> bool:
    """Test whether a function is defined inside a pytest class.

    Args:
        tree: The module AST.
        node: The function node.

    Returns:
        True when the enclosing class name starts with ``Test``.
    """
    parents = parent_map(tree)
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.ClassDef):
            return current.name.startswith("Test")
        current = parents.get(current)
    return False


@rule("JH012")
def check_integration_marker(context: RuleContext) -> list[CheckFinding]:
    """Flag tests exercising network I/O without the integration marker.

    A test function is flagged when it calls HTTP clients or ``urlopen``
    directly, or when it lives in an ``integration`` test file that never
    sets ``pytest.mark.integration``. Unit tests that only fake adapter
    payloads are not network-touching and are not flagged.

    Args:
        context: The tree being checked.

    Returns:
        Findings for network-touching test functions that lack
        ``@pytest.mark.integration``.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if not path.startswith("tests/") or not path.endswith(".py"):
            continue
        try:
            module_tree = ast.parse(source)
        except SyntaxError:
            continue
        module_marked = _module_marked_integration(source)
        for node in ast.walk(module_tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test"):
                continue
            marked = any(
                INTEGRATION_MARKER_PATTERN.search(ast.unparse(decorator)) for decorator in node.decorator_list
            )
            if marked or module_marked:
                continue
            if not _calls_network(node) and not Path(path).stem.startswith("integration"):
                continue
            findings.append(
                CheckFinding(
                    rule="JH012",
                    path=path,
                    line=node.lineno,
                    severity=SEVERITY["JH012"],
                    message=(
                        f"test {node.name} would hit the network directly but lacks "
                        "@pytest.mark.integration; fake the payloads or mark the test "
                        "(AGENTS.md Commands)"
                    ),
                    symbol=f"integration:{node.name}:{path}",
                )
            )
    return findings


def _module_marked_integration(source: str) -> bool:
    """Test whether a test module sets the integration marker globally.

    Args:
        source: The module source text.

    Returns:
        True when ``pytestmark = pytest.mark.integration`` is present.
    """
    return bool(re.search(r"pytestmark\s*=\s*pytest\.mark\.integration", source))


def _calls_network(function_node: ast.AST) -> bool:
    """Test whether a function body calls network primitives directly.

    Args:
        function_node: The function AST node.

    Returns:
        True when the body invokes ``urlopen``, a httpx or requests module
        call, or a Playwright browser launcher.
    """
    for child in ast.walk(function_node):
        if not isinstance(child, ast.Call):
            continue
        function = child.func
        if isinstance(function, ast.Name):
            label = function.id
        elif isinstance(function, ast.Attribute):
            label = getattr(function.value, "id", "") + "." + function.attr
        else:
            continue
        if label == "urlopen":
            return True
        if label.startswith(("httpx.", "requests.")):
            return True
        if label in {"sync_playwright", "async_playwright", "chromium.launch", "firefox.launch", "webkit.launch"}:
            return True
    return False


# ---------------------------------------------------------------------------
# Phase B: docs-in-sync rules
# ---------------------------------------------------------------------------


@rule("JH013")
def check_doc_widget_ids(context: RuleContext) -> list[CheckFinding]:
    """Flag documented widget IDs missing from the app source.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every ``#id`` documented in docs/SCREENS.md that the
        application source and the tests do not reference.
    """
    findings: list[CheckFinding] = []
    documented = context.read_text(DOCS_SCREENS_FILE)
    if documented is None:
        return findings
    app_text = _collect_source_text(context, ("src/jobhunt/app/",))
    test_text = _collect_source_text(context, ("tests/",))
    id_pattern = re.compile(r"`#([a-z0-9_]+)`")
    for match in id_pattern.finditer(documented):
        widget_id = match.group(1)
        line = documented.count("\n", 0, match.start()) + 1
        in_app = any(f'"{widget_id}"' in text or f"'{widget_id}'" in text for _, text in app_text)
        if in_app:
            continue
        test_files = [relative for relative, text in test_text if f"#{widget_id}" in text]
        if test_files:
            findings.append(
                CheckFinding(
                    rule="JH013",
                    path=test_files[0],
                    line=1,
                    severity=SEVERITY["JH013"],
                    message=(
                        f"tests reference widget id `#{widget_id}` that no widget in src/jobhunt/app/** "
                        "defines; SCREENS.md documents a stale id"
                    ),
                    symbol=f"widget-id-test:{widget_id}:{test_files[0]}",
                )
            )
            continue
        findings.append(
            CheckFinding(
                rule="JH013",
                path=DOCS_SCREENS_FILE,
                line=line,
                severity=SEVERITY["JH013"],
                message=f"widget id `#{widget_id}` documented in SCREENS.md is absent from src/jobhunt/app/**",
                symbol=f"widget-id:{widget_id}",
            )
        )
    return findings


def _collect_source_text(context: RuleContext, prefixes: tuple[str, ...]) -> list[tuple[str, str]]:
    """Collect text of python files under prefixes from the tree.

    Args:
        context: The tree being checked.
        prefixes: Path prefixes to include.

    Returns:
        A list of ``(path, text)`` pairs.
    """
    collected: list[tuple[str, str]] = []
    for prefix in prefixes:
        directory = context.tree / prefix.rstrip("/")
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            relative = path.relative_to(context.tree).as_posix()
            collected.append((relative, text))
    return collected


@rule("JH014")
def check_doc_db_schema(context: RuleContext) -> list[CheckFinding]:
    """Flag CREATE TABLE columns that drift from the documentation.

    Args:
        context: The tree being checked.

    Returns:
        Findings for each column documented but unused, and each column
        present in code but absent from the docs.
    """
    findings: list[CheckFinding] = []
    documented = context.read_text(DOCS_DB_FILE)
    schema = context.read_text("src/jobhunt/db/__init__.py")
    if documented is None or schema is None:
        return findings
    code_tables = _code_tables(schema)
    doc_tables = _doc_tables(documented)
    for table, columns in doc_tables.items():
        code_columns = code_tables.get(table)
        if code_columns is None:
            findings.append(
                CheckFinding(
                    rule="JH014",
                    path=DOCS_DB_FILE,
                    line=1,
                    severity=SEVERITY["JH014"],
                    message=f"table `{table}` documented in DATABASE_AND_CONFIG.md has no CREATE TABLE in db/__init__.py",
                    symbol=f"table:{table}",
                )
            )
            continue
        for column in sorted(set(columns) - set(code_columns)):
            line = _line_of(documented, column)
            findings.append(
                CheckFinding(
                    rule="JH014",
                    path=DOCS_DB_FILE,
                    line=line,
                    severity=SEVERITY["JH014"],
                    message=f"column `{column}` of `{table}` is documented but absent from CREATE TABLE",
                    symbol=f"column:{table}:{column}",
                )
            )
        for column in sorted(set(code_columns) - set(columns)):
            line = _line_of(schema, column)
            findings.append(
                CheckFinding(
                    rule="JH014",
                    path="src/jobhunt/db/__init__.py",
                    line=line,
                    severity=SEVERITY["JH014"],
                    message=f"column `{column}` of `{table}` exists in CREATE TABLE but is not in DATABASE_AND_CONFIG.md",
                    symbol=f"column-undocumented:{table}:{column}",
                )
            )
    return findings


def _code_tables(schema: str) -> dict[str, set[str]]:
    """Extract CREATE TABLE columns from db/__init__.py.

    Args:
        schema: The db source text.

    Returns:
        A mapping of table name to the set of column names.
    """
    tables: dict[str, set[str]] = {}
    for match in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\s{4,}\)\s*.{0,20}'''", schema, re.DOTALL):
        name, columns = match.group(1), match.group(2)
        column_names: set[str] = set()
        for raw in columns.splitlines():
            stripped = raw.strip()
            if stripped.startswith("--"):
                continue
            if " -- " in stripped:
                stripped = stripped.split(" -- ", 1)[0].strip()
            parts = stripped.strip(",").split()
            if not parts:
                continue
            first = parts[0].strip()
            if first.isidentifier() and first.upper() not in {
                "PRIMARY",
                "UNIQUE",
                "FOREIGN",
                "CHECK",
                "CONSTRAINT",
            }:
                column_names.add(first)
        tables[name] = column_names
    return tables


def _doc_tables(documented: str) -> dict[str, set[str]]:
    """Extract the documented table columns from DATABASE_AND_CONFIG.md.

    Args:
        documented: The markdown text.

    Returns:
        A mapping of table name to the set of documented column names.
        Only the ``### Tables`` section is considered.
    """
    tables: dict[str, set[str]] = {}
    section = documented.split("### Tables", 1)
    body = section[1].split("\n### ", 1)[0] if len(section) > 1 else ""
    current_table: str | None = None
    for line in body.splitlines():
        heading = re.match(r"####\s+(\w+)", line)
        if heading:
            current_table = heading.group(1)
            tables.setdefault(current_table, set())
            continue
        if current_table is None:
            continue
        cell = re.match(r"\|\s*`(\w+)`\s*\|", line)
        if cell:
            tables[current_table].add(cell.group(1))
    return tables


def _line_of(text: str, needle: str) -> int:
    """Return the first line containing a needle.

    Args:
        text: The text to search.
        needle: The string to find.

    Returns:
        The 1-based line number, or 1 when the needle is absent.
    """
    position = text.find(needle)
    if position < 0:
        return 1
    return text.count("\n", 0, position) + 1


@rule("JH015")
def check_doc_db_methods(context: RuleContext) -> list[CheckFinding]:
    """Flag documented JobHuntDB methods missing from the class.

    Args:
        context: The tree being checked.

    Returns:
        Findings for every accessor method documented in
        docs/DATABASE_AND_CONFIG.md but absent from JobHuntDB.
    """
    findings: list[CheckFinding] = []
    documented = context.read_text(DOCS_DB_FILE)
    schema = context.read_text("src/jobhunt/db/__init__.py")
    if documented is None or schema is None:
        return findings
    section = documented.split("### Accessor Methods", 1)
    body = section[1].split("## ", 1)[0] if len(section) > 1 else ""
    documented_methods = set(re.findall(r"^\|\s*`?(\w+)\(", body, re.MULTILINE))
    class_methods = _pyclass_methods(schema, "JobHuntDB")
    module_methods = _module_functions(schema)
    for method in sorted(documented_methods):
        if method in class_methods or method in module_methods:
            continue
        findings.append(
            CheckFinding(
                rule="JH015",
                path=DOCS_DB_FILE,
                line=_line_of(documented, method),
                severity=SEVERITY["JH015"],
                message=f"method `{method}` documented for JobHuntDB is absent from the class",
                symbol=f"db-method:{method}",
            )
        )
    return findings


def _pyclass_methods(source: str, class_name: str) -> set[str]:
    """Return the methods defined by a class.

    Args:
        source: The python source text.
        class_name: The class to inspect.

    Returns:
        The set of method names.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                statement.name
                for statement in node.body
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return set()


def _module_functions(source: str) -> set[str]:
    """Return the module-level function names in a source text.

    Args:
        source: The python source text.

    Returns:
        The set of function names.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


@rule("JH016")
def check_doc_source_adapters(context: RuleContext) -> list[CheckFinding]:
    """Flag documented source adapters missing from sources/**.

    Args:
        context: The tree being checked.

    Returns:
        Findings for每一个 documented adapter module or factory key missing
        from the sources package.
    """
    return _check_doc_source_adapters(context)


def _check_doc_source_adapters(context: RuleContext) -> list[CheckFinding]:
    """Shared implementation of the source adapter documentation rule.

    Args:
        context: The tree being checked.

    Returns:
        Findings for missing adapter modules and missing factory keys.
    """
    findings: list[CheckFinding] = []
    documented = context.read_text(DOCS_SOURCES_FILE)
    if documented is None:
        return findings
    factory = context.read_text("src/jobhunt/sources/__init__.py")
    modules = set(re.findall(r"`src/jobhunt/sources/(\w+)\.py`", documented))
    for module in sorted(modules):
        if not context.exists(f"src/jobhunt/sources/{module}.py"):
            findings.append(
                CheckFinding(
                    rule="JH016",
                    path=DOCS_SOURCES_FILE,
                    line=_line_of(documented, module),
                    severity=SEVERITY["JH016"],
                    message=f"adapter source `{module}.py` documented in SOURCES.md is missing from sources/",
                    symbol=f"adapter:{module}",
                )
            )
    if factory is not None and "def get_source_adapter(" not in factory:
        findings.append(
            CheckFinding(
                rule="JH016",
                path="src/jobhunt/sources/__init__.py",
                line=_line_of(factory, "get_source_adapter"),
                severity=SEVERITY["JH016"],
                message="factory `get_source_adapter` documented in SOURCES.md is absent from sources/__init__.py",
                symbol="adapter-factory",
            )
        )
    return findings


@rule("JH017")
def check_doc_scoring_weights(context: RuleContext) -> list[CheckFinding]:
    """Flag documented scoring constants missing from scoring/**.

    Args:
        context: The tree being checked.

    Returns:
        Findings for each constant in docs/SCORING.md absent from the scoring
        package.
    """
    findings: list[CheckFinding] = []
    documented = context.read_text(DOCS_SCORING_FILE)
    if documented is None:
        return findings
    break_at = documented.split("### Constants", 1)
    body = break_at[1].split("\n## ", 1)[0] if len(break_at) > 1 else ""
    constants = set(re.findall(r"^\|\s*`([A-Z_][A-Z0-9_]*)`\s*\|", body, re.MULTILINE))
    source = _collect_source_text(context, ("src/jobhunt/scoring/",))
    combined = "\n".join(text for _, text in source)
    for constant in sorted(constants):
        if constant in combined:
            continue
        findings.append(
            CheckFinding(
                rule="JH017",
                path=DOCS_SCORING_FILE,
                line=_line_of(documented, constant),
                severity=SEVERITY["JH017"],
                message=f"scoring constant `{constant}` documented in SCORING.md is absent from src/jobhunt/scoring/**",
                symbol=f"scoring:{constant}",
            )
        )
    return findings


@rule("JH018")
def check_agent_read_only(context: RuleContext) -> list[CheckFinding]:
    """Flag a pr-reviewer agent missing read-only denies.

    Args:
        context: The tree being checked.

    Returns:
        Findings when an edit, shell, or webfetch deny disappears from the
        agent front-matter permissions, or when such a deny is turned into an
        unrestricted allow.
    """
    findings: list[CheckFinding] = []
    text = context.read_text(AGENT_FILE)
    if text is None:
        return findings
    entries = _parse_permissions(text)
    for entry in ("edit", "shell", "webfetch", "execute"):
        denied = any(action == entry and effect == "deny" for action, effect in entries)
        if denied:
            continue
        findings.append(
            CheckFinding(
                rule="JH018",
                path=AGENT_FILE,
                line=_line_of(text, "permissions"),
                severity=SEVERITY["JH018"],
                message=f"pr-reviewer agent is missing a deny for `{entry}`; the reviewer must stay read-only",
                symbol=f"agent-deny:{entry}",
            )
        )
    return findings


def _parse_permissions(text: str) -> list[tuple[str, str]]:
    """Extract ``(action, effect)`` pairs from an agent front-matter block.

    Args:
        text: The agent markdown file text.

    Returns:
        Pairs in the order they appear before the closing ``---``.
    """
    entries: list[tuple[str, str]] = []
    pending_action: str | None = None
    lines = text.splitlines()
    iterable = lines[1:] if text.startswith("---") else lines
    for line in iterable:
        if line.strip() == "---":
            break
        match = re.match(r"\s*-\s*action:\s*(\w+)", line)
        if match:
            pending_action = match.group(1)
            continue
        effect = re.match(r"\s*effect:\s*(\w+)", line)
        if effect:
            if pending_action is not None:
                entries.append((pending_action, effect.group(1)))
            pending_action = None
    return entries


@rule("JH019")
def check_workflow_safety(context: RuleContext) -> list[CheckFinding]:
    """Flag unsafe patterns in GitHub Actions workflows.

    Args:
        context: The tree being checked.

    Returns:
        Findings for pull_request_target triggers, unpinned actions, secrets
        interpolated into ``run:`` steps, and overly broad permissions.
    """
    findings: list[CheckFinding] = []
    workflow_files = sorted(
        path
        for path in context.python_paths + _tree_paths(context)
        if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
    )
    for path in workflow_files:
        text = context.read_text(path)
        if text is None:
            continue
        lines = text.splitlines()
        for number, line in enumerate(lines, start=1):
            if "pull_request_target" in line and "on:" in text:
                findings.append(
                    CheckFinding(
                        rule="JH019",
                        path=path,
                        line=number,
                        severity=SEVERITY["JH019"],
                        message="workflow triggers on pull_request_target; fork pull requests get write access",
                        symbol="pull_request_target",
                    )
                )
            if re.search(r"^\s*(?:-\s*)?uses:\s*\S+$", line) and "@" not in line:
                findings.append(
                    CheckFinding(
                        rule="JH019",
                        path=path,
                        line=number,
                        severity=SEVERITY["JH019"],
                        message=f"action used without a version pin: {line.strip()}",
                        symbol=f"unpinned:{number}",
                    )
                )
            if "${{ secrets." in line and re.search(r"run:|echo|sh |curl", line):
                findings.append(
                    CheckFinding(
                        rule="JH019",
                        path=path,
                        line=number,
                        severity=SEVERITY["JH019"],
                        message="secret interpolated into a run: step; risk of leaking through the command line",
                        symbol=f"secret:{number}",
                    )
                )
        _check_permissions(path, text, findings)
    return findings


def _tree_paths(context: RuleContext) -> list[str]:
    """List the workflow files present in the tree.

    Args:
        context: The tree being checked.

    Returns:
        Repository-relative file paths for .github/workflows.
    """
    directory = context.tree / ".github" / "workflows"
    if not directory.is_dir():
        return []
    return sorted(
        (path.relative_to(context.tree)).as_posix()
        for path in directory.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    )


def _check_permissions(path: str, text: str, findings: list[CheckFinding]) -> None:
    """Flag permissions broader than needed.

    Args:
        path: The workflow path.
        text: The workflow text.
        findings: The list to append to.
    """
    broad = {"administration: write", "packages: write", "security-events: write", "statuses: write"}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if any(entry in stripped for entry in broad) and ":" in stripped:
            findings.append(
                CheckFinding(
                    rule="JH019",
                    path=path,
                    line=number,
                    severity=SEVERITY["JH019"],
                    message=f"workflow permission is broader than needed: {stripped}",
                    symbol=f"permissions:{number}",
                )
            )


@rule("JH020")
def check_script_entrypoints(context: RuleContext) -> list[CheckFinding]:
    """Flag [project.scripts] targets missing from source.

    Args:
        context: The tree being checked.

    Returns:
        Findings for each entry point whose ``module:attr`` cannot be resolved.
    """
    findings: list[CheckFinding] = []
    pyproject = context.read_text(ENTRY_POINTS)
    if pyproject is None:
        return findings
    try:
        parsed = tomllib.loads(pyproject)
    except tomllib.TOMLDecodeError as error:
        LOGGER.warning("could not parse %s: %s", ENTRY_POINTS, error)
        return findings
    scripts = ((parsed.get("project") or {}).get("scripts")) or {}
    for name, reference in sorted(scripts.items()):
        entry = str(reference)
        entry_target = entry.split(":", 1)
        if len(entry_target) != 2:
            findings.append(
                CheckFinding(
                    rule="JH020",
                    path=ENTRY_POINTS,
                    line=_line_of(pyproject, name),
                    severity=SEVERITY["JH020"],
                    message=f"entry point {name!r} references {entry!r}; module-attr syntax is required",
                    symbol=f"entrypoint:{entry}",
                )
            )
            continue
        module_name, attribute = entry_target
        module_path = Path(*(module_name.split(".")))
        for candidate in (module_path.with_suffix(".py"), module_path / "__init__.py"):
            if context.exists("src/" + candidate.as_posix()):
                source = context.read_text("src/" + candidate.as_posix()) or ""
                if re.search(rf"^def {attribute}\b|^class {attribute}\b", source, re.MULTILINE):
                    attribute_defined = True
                else:
                    attribute_defined = False
                if attribute_defined:
                    break
        else:
            findings.append(
                CheckFinding(
                    rule="JH020",
                    path=ENTRY_POINTS,
                    line=_line_of(pyproject, name),
                    severity=SEVERITY["JH020"],
                    message=f"entry point {name!r} references {entry!r}, which is missing from src/**",
                    symbol=f"entrypoint:{entry}",
                )
            )
    return findings


@rule("JH021")
def check_docstrings(context: RuleContext) -> list[CheckFinding]:
    """Flag new public module/class/function definitions without docstrings.

    Args:
        context: The tree being checked.

    Returns:
        Findings for public top-level definitions missing a docstring.
    """
    findings: list[CheckFinding] = []
    for path, source in context.python_files():
        if path.endswith(("/conftest.py", "/__init__.py")) or not path.startswith(("src/jobhunt/", "scripts/")):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        if not _module_doc(source) and not path.startswith("tests/"):
            findings.append(
                CheckFinding(
                    rule="JH021",
                    path=path,
                    line=1,
                    severity=SEVERITY["JH021"],
                    message="public module is missing a docstring (AGENTS.md Docstrings)",
                    symbol=f"module-doc:{path}",
                )
            )
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name.startswith("_"):
                continue
            if ast.get_docstring(node):
                continue
            kind = type(node).__name__.removesuffix("Def").replace("Async", "")
            findings.append(
                CheckFinding(
                    rule="JH021",
                    path=path,
                    line=node.lineno,
                    severity=SEVERITY["JH021"],
                    message=f"public {kind.lower()} {node.name} is missing a docstring (AGENTS.md Docstrings)",
                    symbol=f"docstring:{node.name}:{path}",
                )
            )
    return findings


def _module_doc(source: str) -> bool:
    """Test whether a module has a docstring.

    Args:
        source: The python source text.

    Returns:
        True when the module starts with a docstring.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    return ast.get_docstring(tree) is not None


# ---------------------------------------------------------------------------
# Engine: run rules, filter debt, apply suppression
# ---------------------------------------------------------------------------


def load_config(path: Path | None) -> CheckConfig:
    """Load suppression configuration.

    Args:
        path: The config file, defaulting to ``.prcheck.toml``.

    Returns:
        The parsed configuration, or defaults when the file is absent.
    """
    target = path or Path(CONFIG_FILE)
    if not target.is_file():
        return CheckConfig()
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        LOGGER.warning("could not read %s: %s", target, error)
        return CheckConfig()
    return CheckConfig(
        disable=set(raw.get("check", {}).get("disable", []) or []),
        allow=list(raw.get("check", {}).get("allow", []) or []),
        config_path=str(target),
    )


def materialize_tree(repository_root: Path, ref: str, destination: Path) -> Path | None:
    """Extract a git ref into a directory.

    Args:
        repository_root: The git repository to read from.
        ref: The commit to archive.
        destination: The directory to extract into.

    Returns:
        The extraction root, or None when the extraction fails.
    """
    result = subprocess.run(
        ["git", "archive", ref],
        cwd=repository_root,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        LOGGER.warning("git archive %s failed: %s", ref, result.stderr.decode(errors="replace").strip())
        return None
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        try:
            archive.extractall(destination, filter="data")  # noqa: S202 - archive is trusted, git tree
        except TypeError:
            archive.extractall(destination)
    return destination


def changed_paths(repository_root: Path, base_ref: str | None, head_ref: str | None) -> list[str]:
    """List the paths a check should cover.

    Args:
        repository_root: The git repository to read from.
        base_ref: The base commit (already the merge base when applicable), or
            None for a whole-repository run.
        head_ref: The head commit, or None to compare against the working
            tree.

    Returns:
        A sorted list of repository paths.
    """
    if base_ref is None:
        result = subprocess.run(["git", "ls-files"], cwd=repository_root, capture_output=True, timeout=60)
        if result.returncode != 0:
            raise CheckError(f"git ls-files failed: {result.stderr.decode(errors='replace').strip()}")
        return sorted(line for line in result.stdout.decode().splitlines() if line)
    command = ["git", "diff", "--name-only", base_ref, "--diff-filter=d"]
    if head_ref:
        command.insert(3, head_ref)
    result = subprocess.run(command, cwd=repository_root, capture_output=True, timeout=60)
    if result.returncode != 0:
        raise CheckError(f"git diff failed: {result.stderr.decode(errors='replace').strip()}")
    return sorted(line for line in result.stdout.decode().splitlines() if line)


def pull_request_refs(number: int) -> tuple[str, str, list[str]]:
    """Resolve a pull request number into base and head refs.

    Args:
        number: The pull request number.

    Returns:
        The base and head commit ids and the changed paths.

    Raises:
        CheckError: When the GitHub CLI cannot read the pull request.
    """
    view = subprocess.run(
        ["gh", "pr", "view", str(number), "--json", "baseRefOid,headRefOid"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if view.returncode != 0:
        raise CheckError(f"gh pr view failed: {view.stderr.strip()}")
    refs = json.loads(view.stdout)
    diff = subprocess.run(
        ["gh", "pr", "diff", str(number), "--name-only"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if diff.returncode != 0:
        raise CheckError(f"gh pr diff failed: {diff.stderr.strip()}")
    return refs["baseRefOid"], refs["headRefOid"], sorted(line for line in diff.stdout.splitlines() if line)


def run_checks(
    head_tree: Path,
    base_tree: Path | None,
    paths: list[str],
    config: CheckConfig,
) -> tuple[list[CheckFinding], list[Suppression]]:
    """Run the rules against head and base and report new debt.

    Args:
        head_tree: The head tree (the working tree).
        base_tree: The base tree, or None to treat everything as new.
        paths: The repository-relative paths relevant to the run.
        config: Suppression configuration.

    Returns:
        The reported findings and the applied suppressions.
    """
    python_paths = [path for path in paths if path.endswith(".py")]
    head_context = RuleContext(tree=head_tree, python_paths=python_paths)
    base_context = (
        RuleContext(tree=base_tree, python_paths=python_paths) if base_tree is not None else None
    )
    all_findings: dict[tuple[str, str, str], CheckFinding] = {}
    for rule_id in sorted(RULES):
        if rule_id in config.disable:
            continue
        function = RULES[rule_id]
        head_findings = _safe_run(rule_id, function, head_context)
        key_map = {finding.key(): finding for finding in head_findings}
        if base_context is not None:
            base_findings = _safe_run(rule_id, function, base_context)
            for base_key in {finding.key() for finding in base_findings}:
                key_map.pop(base_key, None)
        all_findings.update(key_map)
    findings = sorted(all_findings.values(), key=lambda finding: (finding.path, finding.line, finding.rule))
    suppressed, remaining = _apply_suppressions(findings, config, head_context)
    return remaining, suppressed


def _safe_run(rule_id: str, function: RuleFunction, context: RuleContext) -> list[CheckFinding]:
    """Run one rule without letting failures corrupt the report.

    Args:
        rule_id: The rule identifier, used only for logging.
        function: The rule implementation.
        context: The tree to check.

    Returns:
        The findings, or an empty list when the rule failed.
    """
    try:
        return function(context)
    except (OSError, SyntaxError, ValueError, RuntimeError, TypeError, AttributeError) as error:
        LOGGER.warning("rule %s failed: %s", rule_id, error)
        return []


def _apply_suppressions(
    findings: list[CheckFinding],
    config: CheckConfig,
    context: RuleContext,
) -> tuple[list[Suppression], list[CheckFinding]]:
    """Split findings into suppressed and reported.

    Args:
        findings: The candidate findings, already sorted.
        config: Suppression configuration.
        context: The head tree, for inline ``prcheck: ignore`` markers.

    Returns:
        The suppressions and the remaining findings.
    """
    inline = _collect_inline_suppressions(context)
    suppressed: list[Suppression] = []
    remaining: list[CheckFinding] = []
    for finding in findings:
        reason = self_suppressed(finding, inline, config)
        if reason is not None:
            source, text = reason
            suppressed.append(
                Suppression(
                    rule=finding.rule,
                    path=finding.path,
                    line=finding.line,
                    reason=text,
                    source=source,
                )
            )
            continue
        remaining.append(finding)
    return suppressed, remaining


def self_suppressed(
    finding: CheckFinding,
    inline: dict[tuple[str, str], list[tuple[str, str]]],
    config: CheckConfig,
) -> tuple[str, str] | None:
    """Decide whether a finding is suppressed, and by what.

    Args:
        finding: The finding to test.
        inline: Inline markers keyed by ``(rule, path)``.
        config: Suppression configuration.

    Returns:
        A ``(source, reason)`` pair, or None when the finding is reported.
    """
    for rule_id, path in inline:
        if rule_id != finding.rule or path != finding.path:
            continue
        for line, reason in inline[(rule_id, path)]:
            if line in {finding.line, finding.line - 1}:
                return ("inline", reason)
    for pattern in config.allow:
        if fnmatch.fnmatch(f"{finding.rule}:{finding.path}", pattern):
            return ("config-allow", f"allowed by {pattern} in {CONFIG_FILE}")
    return None


def _collect_inline_suppressions(context: RuleContext) -> dict[tuple[str, str], list[tuple[int, str]]]:
    """Collect ``# prcheck: ignore`` markers from the head tree files.

    A suppression reason is mandatory: a bare ``ignore JH00X`` marker is not
    registered and its finding is reported instead.

    Args:
        context: The head tree.

    Returns:
        Markers keyed by ``(rule, path)`` mapping to ``(line, reason)`` pairs.
    """
    markers: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for path, source in context.python_files():
        for number, line in enumerate(source.splitlines(), start=1):
            match = IGNORE_PATTERN.search(line)
            if match is None:
                continue
            reason = (match.group("reason") or "").strip()
            if not reason:
                continue
            markers.setdefault((match.group("rule"), path), []).append((number, reason))
    return markers


# ---------------------------------------------------------------------------
# Reporting and posting
# ---------------------------------------------------------------------------


def format_report(
    findings: list[CheckFinding],
    suppressions: list[Suppression],
    exit_code: int,
) -> str:
    """Render the deterministic markdown report.

    Args:
        findings: The reported findings.
        suppressions: The applied suppressions.
        exit_code: The exit code the run will produce.

    Returns:
        The markdown report text.
    """
    lines: list[str] = []
    for finding in sorted(findings, key=lambda finding: (finding.path, finding.line, finding.rule)):
        lines.append(f"- {finding.slug()}")
    if suppressions:
        for entry in suppressions:
            lines.append(f"- ~~{entry.rule} {entry.path}:{entry.line}~~ suppressed ({entry.source}: {entry.reason})")
    lines.append("")
    blocking = sum(1 for finding in findings if finding.severity == BLOCKING)
    advisory = len(findings) - blocking
    outcome = "FAIL" if exit_code == 1 else "PASS"
    lines.append(
        f"blocking: {blocking}, advisory: {advisory}, suppressions: {len(suppressions)} -> {outcome}"
    )
    return "\n".join(lines)


def load_pr_review_module() -> Any:
    """Import scripts/pr_review.py as a module.

    Returns:
        The imported module.

    Raises:
        CheckError: When the module cannot load.
    """
    import importlib.util

    path = Path(__file__).with_name("pr_review.py")
    spec = importlib.util.spec_from_file_location("pr_review", path)
    if spec is None or spec.loader is None:
        raise CheckError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_inline_payload(
    findings: list[CheckFinding],
    repository_root: Path,
    number: int,
) -> dict | None:
    """Build a pull request review payload from the checker's findings.

    Only findings that resolve to a diff line become inline comments; the
    rest are listed in the review body.

    Args:
        findings: The reported findings.
        repository_root: The checked-out repository.
        number: The pull request number.

    Returns:
        The review payload, or None when no pull request is reachable.
    """
    module = load_pr_review_module()
    diff = subprocess.run(
        ["gh", "pr", "diff", str(number)], capture_output=True, text=True, timeout=120, cwd=repository_root
    )
    if diff.returncode != 0:
        LOGGER.warning("could not read the pull request diff: %s", diff.stderr.strip())
        return None
    diff_files = module.parse_unified_diff(diff.stdout)
    view = subprocess.run(
        ["gh", "pr", "view", str(number), "--json", "headRefOid"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=repository_root,
    )
    if view.returncode != 0:
        LOGGER.warning("could not read the pull request metadata: %s", view.stderr.strip())
        return None
    head_commit = json.loads(view.stdout)["headRefOid"]
    placed = []
    unplaced = []
    for finding in findings:
        body = "\n".join(
            [
                f"**{finding.rule}** ({finding.severity}) - {finding.message}",
                "",
                "<sub>pr_check · suppress with `# prcheck: ignore "
                f"{finding.rule} <reason>`.</sub>",
            ]
        )
        model_finding = module.Finding(path=finding.path, line=finding.line, body=body)
        resolution = module.resolve_finding(model_finding, diff_files)
        if resolution.line is None:
            unplaced.append(resolution)
        else:
            resolution.finding.body = body
            placed.append(resolution)
    summary = build_summary(findings)
    payload = module.build_review_payload(placed, unplaced, summary, "pr_check", head_commit)
    if findings:
        payload["event"] = "REQUEST_CHANGES" if any(f.severity == BLOCKING for f in findings) else "COMMENT"
    return payload


def build_summary(findings: list[CheckFinding]) -> str:
    """Write the review body summary the checker posts.

    Args:
        findings: The findings that could not be placed inline.

    Returns:
        The markdown summary text.
    """
    if not findings:
        return "pr_check: no findings to report."
    bullets = "\n".join(f"- {finding.slug()}" for finding in findings)
    return f"## pr_check\n\n{bullets}\n\n<sub>Deterministic convention checker; no model involved.</sub>"


def write_step_summary(text: str) -> None:
    """Append a report to the GitHub step summary.

    Args:
        text: The markdown to append.
    """
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    header = "## pr_check report\n\nBlocked from posting inline comments; degrading to the step summary.\n\n"
    with open(target, "a", encoding="utf-8") as stream:
        stream.write(header)
        stream.write(text)
        stream.write("\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: The arguments, defaulting to the process arguments.

    Returns:
        The parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="The base commit to compare against.")
    parser.add_argument("--head", default=None, help="The head commit; defaults to the working tree.")
    parser.add_argument("--pr-number", type=int, default=None, help="The pull request number to fetch diffs for.")
    parser.add_argument("--all", action="store_true", help="Scan the entire repository instead of the diff.")
    parser.add_argument("--repository-root", default=".", help="The repository to check.")
    parser.add_argument("--config", type=Path, default=None, help="Suppression configuration file.")
    parser.add_argument("--output", type=Path, default=None, help="Where to write the markdown report.")
    parser.add_argument("--json", action="store_true", help="Print findings as JSON instead of markdown.")
    parser.add_argument("--post", action="store_true", help="Post findings as inline PR review comments.")
    parser.add_argument("--dry-run", action="store_true", help="Print the payload instead of posting it.")
    arguments = parser.parse_args(argv)
    if arguments.all and arguments.base:
        parser.error("--all cannot be combined with --base")
    if arguments.pr_number is None and not arguments.all and not arguments.base:
        parser.error("one of --pr-number, --base or --all is required")
    if arguments.post and arguments.pr_number is None:
        number = re.search(r"refs/pull/(\d+)/", os.environ.get("GITHUB_REF", ""))
        if number is None:
            parser.error("--post needs --pr-number or a pull request ref in GITHUB_REF")
        arguments.pr_number = int(number.group(1))
    return arguments


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface.

    Args:
        argv: The command line arguments, defaulting to the process arguments.

    Returns:
        0 when no blocking finding remains, 1 otherwise, or 2 on error.
    """
    arguments = parse_arguments(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    repository_root = Path(arguments.repository_root).resolve()
    config = load_config(arguments.config)
    try:
        base_ref = None
        head_ref = arguments.head or "HEAD"
        paths = []

        if arguments.all:
            paths = changed_paths(repository_root, None, None)
        elif arguments.base is not None:
            base_ref = arguments.base
            paths = changed_paths(repository_root, base_ref, arguments.head)
        elif arguments.pr_number is not None:
            base_ref, head_ref, paths = pull_request_refs(arguments.pr_number)
        else:
            parser.error("one of --pr-number, --base or --all is required")
    except (CheckError, OSError) as error:
        LOGGER.error("%s", error)
        return 2

    head_tree = repository_root
    if arguments.pr_number is None and base_ref and not arguments.all:
        merge_result = subprocess.run(
            ["git", "merge-base", base_ref, head_ref],
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if merge_result.returncode == 0:
            base_ref = merge_result.stdout.strip()
        paths = changed_paths(repository_root, base_ref, arguments.head)

    base_tree_path: Path | None = None
    base_tree: Path | None = None
    if base_ref:
        base_tree_path = Path(tempfile.mkdtemp(prefix="prcheck-base-"))
        base_tree = materialize_tree(repository_root, base_ref, base_tree_path)
        if base_tree is None:
            LOGGER.warning("no base tree; treating every violation as new debt")

    try:
        findings, suppressions = run_checks(head_tree=repository_root, base_tree=base_tree, paths=paths, config=config)
    except CheckError as error:
        LOGGER.error("%s", error)
        if base_tree_path:
            import shutil

            shutil.rmtree(base_tree_path, ignore_errors=True)
        return 2

    blocking = sum(1 for finding in findings if finding.severity == BLOCKING)
    exit_code = 1 if blocking else 0
    report = format_report(findings, suppressions, exit_code)

    if arguments.json:
        print(json.dumps({"findings": [asdict(f) for f in findings], "suppressions": [asdict(s) for s in suppressions]}, indent=2))
    else:
        print(report)
    if arguments.output is not None:
        arguments.output.write_text(report + "\n", encoding="utf-8")

    if arguments.post and arguments.pr_number is not None:
        if arguments.dry_run or not findings:
            payload = build_inline_payload(findings, repository_root, arguments.pr_number) if findings else None
            if payload is not None:
                print(json.dumps(payload, indent=2))
        else:
            payload = build_inline_payload(findings, repository_root, arguments.pr_number)
            if payload is None:
                write_step_summary(report)
                print("could not fetch the pull request; wrote the report to the step summary.")
            else:
                module = load_pr_review_module()
                try:
                    repository = module.fetch_repository_name()
                    module.post_review(repository, arguments.pr_number, payload)
                    print(f"posted the pr_check review on PR #{arguments.pr_number}.")
                except Exception as error:  # noqa: BLE001 - degrade gracefully on read-only tokens
                    LOGGER.warning("posting failed, degrading to the step summary: %s", error)
                    write_step_summary(report)

    if base_tree_path:
        import shutil

        shutil.rmtree(base_tree_path, ignore_errors=True)
    if blocking:
        LOGGER.error("%d blocking finding(s)", blocking)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
