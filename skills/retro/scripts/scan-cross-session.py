#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "markdown-it-py==4.3.0",
# ]
# ///

"""
scan-cross-session.py — Schicht-C cross-session data source.

Scans Claude Code session JSONL files across projects to find similar friction
patterns. Used to detect "same friction again" (C1), "cross-project pattern"
(C2), "follow-up-fix session" (C5) and "rule never applicable" (C7) signals.

Usage:
    uv run scan-cross-session.py --pattern="<keyword or phrase>" [--days 30] [--project=<slug>]
    uv run scan-cross-session.py --user-correction-summary [--days 7]
    uv run scan-cross-session.py --recurring-failures [--days 30] [--limit 20] [--include-refusals]
    uv run scan-cross-session.py --follow-up-sessions [--days 30] [--window-days 7] [--limit 20]
    uv run scan-cross-session.py --rule-tally CLAUDE.md [--days 90] [--min-sessions 30]
    uv run scan-cross-session.py --learning-observations observations.json

The C1, C5 and C7 modes read every tool call of every transcript in the window, so
they run on demand (an audit), not per event. The C1 and C5 modes report only
what recurs in at least two sessions. Each names the sessions it was computed
from and caps its session lists at --limit; --rule-tally lists every rule, so
write its output to a file and query it. Their output is a candidate list for
the model to read, not a verdict: a hit says where to look.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt


def _load_masking():
    """mask-secrets.py, loaded by path: its name is hyphenated like ours."""
    path = Path(__file__).resolve().parent / "mask-secrets.py"
    spec = importlib.util.spec_from_file_location("mask_secrets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_masking = _load_masking()
mask, squeeze = _masking.mask, _masking.squeeze

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CORRECTION_PATTERNS = re.compile(
    r"^\s*(no\b|nein\b|stop\b|don't\b|wrong\b|NEIN\b|nicht so\b)",
    re.IGNORECASE | re.MULTILINE,
)
DEFAULT_LIMIT = 20

# --- tool results ------------------------------------------------------------
# Bash reports a command that ran and failed as `Exit code N` followed by its
# output. A call the harness refused never ran: its result is the refusal text
# alone, with or without a `PreToolUse:Bash hook error:` prefix. A refusal is a
# deployed gate doing its job, which C6 already reads (`gate_observed`), so the
# failure count keeps it apart.
EXIT_CODE_RE = re.compile(r"\AExit code \d+\s*")
PRETOOL_PREFIX_RE = re.compile(
    r"\A\s*PreToolUse:?\w*\s+hook(?:\s+error)?:\s*", re.IGNORECASE
)
TOOL_USE_ERROR_RE = re.compile(r"</?tool_use_error>")
# The line of a command's output that carries the failure. A traceback's
# header names none; its last line does.
ERROR_LINE_RE = re.compile(
    r"error|fatal|denied|not found|failed|no such|cannot|can't|invalid|refused"
    r"|exception|unknown|missing|forbidden|unauthori[sz]ed|timed? ?out",
    re.IGNORECASE,
)
TRACEBACK_RE = re.compile(r"^\s*Traceback \(most recent call last\)")
# A path is a value, not part of the message: `/a/b/c`, `~/x`, `./y`. `tail/head`
# in prose is not a path, so a slash only starts one after a boundary.
PATH_RE = re.compile(r"(?<![\w>])(?:~|\.\.?)?/[^\s'\"`:,;()\]]+")
HEX_RE = re.compile(r"\b[0-9a-f]{7,64}\b")
NUMBER_RE = re.compile(r"\d+")
MAX_KEY_CHARS = 160
# A key needs two words besides its placeholders: `<path>`, `exit=<n>`, `---`
# and a bare `ERROR` recur everywhere and say nothing about what failed.
PLACEHOLDER_RE = re.compile(r"<(?:path|hex|n)>")
WORD_RE = re.compile(r"[^\W\d_]{2,}")
MIN_KEY_WORDS = 2

# --- follow-up sessions ------------------------------------------------------
# An edit counts as rewriting earlier work only when the earlier text is long
# enough to be specific; a one-word `new_string` recurs by chance.
MIN_REWRITE_CHARS = 20
# `git commit` prints `[branch 1a2b3c4] subject`, `[main (root-commit) 1a2b3c4] …`.
COMMIT_LINE_RE = re.compile(r"^\[[^\]\n]*?\b([0-9a-f]{7,40})\] ", re.MULTILINE)
GIT_REVERT_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?revert\b(?P<args>[^;&|\n]*)")


# --- reading -------------------------------------------------------------------


def _project_sessions(
    project: Path, cutoff: datetime, gaps: Counter[str]
) -> Iterator[tuple[Path, str]]:
    # Path.glob suppresses directory read errors on some supported versions.
    with os.scandir(project) as entries:
        for entry in entries:
            if not entry.name.endswith(".jsonl"):
                continue
            try:
                mtime = datetime.fromtimestamp(entry.stat().st_mtime, UTC)
            except OSError:
                gaps["unstatable_entries"] += 1
                continue
            if mtime >= cutoff:
                yield Path(entry.path), project.name


def session_files(
    projects_dir: Path,
    project_slug: str | None,
    days: int,
    gaps: Counter[str] | None = None,
) -> list[tuple[Path, str]]:
    """Return list of (jsonl_path, project_slug) within the last N days."""
    # Use elapsed days so local clock changes cannot shift the cutoff.
    cutoff = datetime.now(UTC) - timedelta(days=days)
    out = []
    if gaps is None:
        gaps = Counter()
    if project_slug is None:
        candidates = [p for p in projects_dir.iterdir() if p.is_dir()]
    else:
        candidates = [projects_dir / project_slug]
    for proj_dir in candidates:
        try:
            out.extend(_project_sessions(proj_dir, cutoff, gaps))
        except OSError:
            if project_slug is not None:
                raise
            gaps["unreadable_projects"] += 1
    return out


def load_events(
    path: Path, gaps: Counter[str] | None = None
) -> list[dict[str, Any]] | None:
    """The transcript's event objects, or None when it cannot be read.

    A transcript can vanish between listing and reading while another session
    runs, and a line can hold JSON that is not an object; neither may abort the
    scan or be counted as a session.
    """
    events = []
    if gaps is None:
        gaps = Counter()
    try:
        with path.open("rb") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    gaps["invalid_rows"] += 1
                    continue
                if not isinstance(ev, dict):
                    gaps["invalid_rows"] += 1
                    continue
                # Claude Code's API request logs replay earlier messages, tool
                # calls included; read as conversation they repeat every call.
                # Blanked, not dropped, so event positions stay those of the file.
                if _is_request_log(ev):
                    ev = {}
                events.append(ev)
    except OSError:
        gaps["unreadable_sessions"] += 1
        return None
    return events


#: Event types that log what the harness sent to the API, not the conversation.
REQUEST_LOG_TYPES = frozenset({"api-request", "api-request-blob"})


def _is_request_log(ev: dict) -> bool:
    # `type` can be any JSON value; an unhashable one is simply not a log type.
    kind = ev.get("type")
    return isinstance(kind, str) and kind in REQUEST_LOG_TYPES


# Turns that carry the "user" role but were not typed by a human. A copy of
# `_SYNTHETIC_USER_MARKERS` in detect-mechanical.py, which explains each one;
# tests/test_scan_cross_session.py fails when the two drift apart.
SYNTHETIC_USER_MARKERS = (
    "<task-notification>",
    "[SYSTEM NOTIFICATION",
    "<system-reminder>",
    "<command-message>",
    "<teammate-message",
    "<agent-message",
    "This session is being continued from a previous conversation",
)


def _is_synthetic_user_text(text: str) -> bool:
    head = text.lstrip()[:400]
    return any(marker in head for marker in SYNTHETIC_USER_MARKERS)


def _user_text_blocks(message: Any, gaps: Counter[str]) -> list[str]:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        gaps["invalid_user_turns"] += 1
        return []
    texts = []
    malformed = False
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str):
            malformed = True
        elif block["type"] == "text":
            if isinstance(block.get("text"), str):
                texts.append(block["text"])
            else:
                malformed = True
    if malformed:
        gaps["invalid_user_turns"] += 1
    return texts


def extract_user_texts(path: Path, gaps: Counter[str] | None = None) -> list[str]:
    """What a human typed: the text of every user turn the harness did not
    write itself.

    The harness stamps its own user turns — hook feedback (`Stop hook
    feedback: …`), slash-command expansions, notifications — with `isMeta`,
    and a compaction recap with `isCompactSummary`; the markers are the
    fallback for transcripts older than those flags, as in
    detect-mechanical.py. Without this, `--user-correction-summary` counted a
    hook's `Stop …` feedback, repeated in every session, as a correction."""
    if gaps is None:
        gaps = Counter()
    return user_texts_of(load_events(path, gaps) or [], gaps)


def user_texts_of(events: list[dict[str, Any]], gaps: Counter[str]) -> list[str]:
    """extract_user_texts for events already read."""
    texts = []
    for ev in events:
        if ev.get("type") in (
            "response_item",
            "event_msg",
            "turn_context",
            "session_meta",
        ) and isinstance(ev.get("payload"), dict):
            # Raw Codex records require the adapter even in a mixed export.
            gaps["native_codex_rows"] += 1
            continue
        if ev.get("type") != "user":
            continue
        if ev.get("isMeta") or ev.get("isCompactSummary"):
            continue
        found = _user_text_blocks(ev.get("message"), gaps)
        # A slash-command expansion delivers its template as a sibling text
        # block of the <command-message> marker: one synthetic block makes the
        # whole message synthetic.
        if any(_is_synthetic_user_text(t) for t in found):
            continue
        texts.extend(found)
    return texts


def _content_blocks(ev: dict[str, Any]) -> list[dict[str, Any]]:
    msg = ev.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict)]


def _result_text(block: dict[str, Any]) -> str:
    content = block.get("content", "")
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content)


def tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every tool call with its result: name, input, result, is_error, timestamp."""
    pending: dict[str, dict[str, Any]] = {}
    calls = []
    for ev in events:
        for block in _content_blocks(ev):
            if block.get("type") == "tool_use":
                inp = block.get("input")
                call = {
                    "name": block.get("name", "?"),
                    "input": inp if isinstance(inp, dict) else {},
                    "result": "",
                    "is_error": False,
                    "timestamp": ev.get("timestamp"),
                }
                calls.append(call)
                pending[block.get("id")] = call
            elif block.get("type") == "tool_result":
                call = pending.pop(block.get("tool_use_id"), None)
                if call is not None:
                    call["result"] = _result_text(block)
                    call["is_error"] = bool(block.get("is_error"))
    return calls


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def read_sessions(
    files: list[tuple[Path, str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Sessions with their tool calls and time span, plus the unreadable ones."""
    sessions, skipped = [], []
    for path, project in files:
        events = load_events(path)
        if not events:
            skipped.append(str(path))
            continue
        stamps = [t for t in (_timestamp(ev.get("timestamp")) for ev in events) if t]
        sessions.append(
            {
                "id": path.stem,
                "project": project,
                "start": min(stamps) if stamps else None,
                "end": max(stamps) if stamps else None,
                "calls": tool_calls(events),
            }
        )
    return sessions, skipped


# --- C1: corrections across sessions ------------------------------------------


def _correction_key(text: str) -> str:
    """Normalize the first 80 chars as a fingerprint, credentials masked
    before lowercasing (AKIA…, eyJ… only match in their own case)."""
    return squeeze(text, 80).lower()


def user_turn_coverage(args, files, gaps):
    """Coverage of the requested Claude user-turn search in the selected time window."""
    return {
        "status": "partial" if gaps else "scanned",
        "corpus": "claude_user_turns",
        "project": args.project,
        "sessions_read": len(files) - gaps["unreadable_sessions"],
        "gaps": dict(gaps),
    }


def cmd_pattern(args, files, gaps) -> int:
    pattern = re.compile(re.escape(args.pattern), re.IGNORECASE)
    hits = defaultdict(list)
    for path, proj in files:
        for txt in extract_user_texts(path, gaps):
            if pattern.search(txt):
                hits[proj].append(
                    {
                        "session": path.name,
                        "snippet": squeeze(txt, 300),
                    }
                )
                break  # one hit per session is enough for cross-session signal
    print(
        json.dumps(
            {
                "coverage": user_turn_coverage(args, files, gaps),
                "pattern": mask(args.pattern),
                "days": args.days,
                "projects_with_matches": len(hits),
                "matches": dict(hits),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_correction_summary(args, files, gaps) -> int:
    corrections_by_project: dict[str, Counter] = defaultdict(Counter)
    # C1 is "the same correction in several sessions"; C2 is the same across
    # projects. Counting only projects hid C1 inside a single project.
    sessions_by_key: dict[str, set[str]] = defaultdict(set)
    projects_by_key: dict[str, set[str]] = defaultdict(set)
    for path, proj in files:
        for txt in extract_user_texts(path, gaps):
            if not CORRECTION_PATTERNS.search(txt):
                continue
            key = _correction_key(txt)
            corrections_by_project[proj][key] += 1
            sessions_by_key[key].add(path.stem)
            projects_by_key[key].add(proj)

    cross_project = Counter()
    for counter in corrections_by_project.values():
        for key in counter:
            cross_project[key] += 1

    cross_session = sorted(
        (k for k, s in sessions_by_key.items() if len(s) >= 2),
        key=lambda k: (-len(sessions_by_key[k]), k),
    )
    output = {
        "days": args.days,
        "coverage": user_turn_coverage(args, files, gaps),
        "sessions_scanned": len(files) - gaps["unreadable_sessions"],
        "projects_scanned": len({proj for _path, proj in files}),
        "cross_session_corrections": [
            {
                "snippet": k,
                "sessions_count": len(sessions_by_key[k]),
                "projects_count": len(projects_by_key[k]),
                "sessions": sorted(sessions_by_key[k]),
            }
            for k in cross_session[: args.limit]
        ],
        "cross_session_truncated": len(cross_session) > args.limit,
        "cross_project_corrections": [
            {"snippet": k, "projects_count": v}
            for k, v in cross_project.most_common(20)
            if v >= 2
        ],
        "by_project_top5": {
            proj: [{"snippet": k, "count": cnt} for k, cnt in c.most_common(5)]
            for proj, c in corrections_by_project.items()
            if c
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


# --- C1: recurring failures ----------------------------------------------------


def is_refusal(name: str, result: str) -> bool:
    """A call the harness or a hook refused: it never ran."""
    if PRETOOL_PREFIX_RE.match(result):
        return True
    return (
        name == "Bash"
        and not EXIT_CODE_RE.match(result)
        and not TOOL_USE_ERROR_RE.search(result)
    )


def failure_line(name: str, result: str) -> str:
    """The line of a failed call's result that says what went wrong."""
    text = PRETOOL_PREFIX_RE.sub("", result, count=1)
    text = TOOL_USE_ERROR_RE.sub("", text)
    if name == "Bash":
        text = EXIT_CODE_RE.sub("", text, count=1)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not TRACEBACK_RE.match(ln)]
    if not lines:
        return ""
    if name != "Bash":
        return lines[0]
    marked = [ln for ln in lines if ERROR_LINE_RE.search(ln)]
    return marked[0] if marked else lines[-1]


def normalise(line: str) -> str:
    """Drop the values from a message so the same failure shares one key."""
    line = re.sub(r"^Error:\s*", "", line)
    line = PATH_RE.sub("<path>", line)
    line = HEX_RE.sub("<hex>", line)
    line = NUMBER_RE.sub("<n>", line)
    return re.sub(r"\s+", " ", line).strip()[:MAX_KEY_CHARS]


def _failure_key(
    call: dict[str, Any], include_refusals: bool
) -> tuple[str | None, tuple[str, str, str], str]:
    """(reason it is excluded or None, grouping key, the line it came from)."""
    refusal = is_refusal(call["name"], call["result"])
    if refusal and not include_refusals:
        return "refusals", ("", "", ""), ""
    # Masked before normalise(), which would otherwise leave a token's
    # letters in the key with only its digits replaced.
    line = mask(failure_line(call["name"], call["result"]))
    key_text = normalise(line)
    if len(WORD_RE.findall(PLACEHOLDER_RE.sub(" ", key_text))) < MIN_KEY_WORDS:
        return "without_message", ("", "", ""), ""
    kind = "refusal" if refusal else "failure"
    return None, (kind, call["name"], key_text), line


def recurring_failures(
    sessions: list[dict[str, Any]], include_refusals: bool = False
) -> dict[str, Any]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    excluded = Counter()
    failed = (
        (session, call)
        for session in sessions
        for call in session["calls"]
        if call["is_error"]
    )
    for session, call in failed:
        reason, key, line = _failure_key(call, include_refusals)
        if reason:
            excluded[reason] += 1
            continue
        entry = by_key.setdefault(
            key, {"example": line[:200], "sessions": set(), "projects": set()}
        )
        entry["sessions"].add(session["id"])
        entry["projects"].add(session["project"])
    recurring = sorted(
        (
            {
                "kind": kind,
                "tool": tool,
                "error": key_text,
                "example": e["example"],
                "sessions_count": len(e["sessions"]),
                "projects_count": len(e["projects"]),
                "sessions": sorted(e["sessions"]),
            }
            for (kind, tool, key_text), e in by_key.items()
            if len(e["sessions"]) >= 2
        ),
        key=lambda r: (-r["sessions_count"], r["tool"], r["error"]),
    )
    return {"recurring": recurring, "excluded": dict(excluded)}


def cmd_recurring_failures(args, files) -> int:
    sessions, skipped = read_sessions(files)
    found = recurring_failures(sessions, args.include_refusals)
    output = {
        "mode": "recurring-failures",
        "days": args.days,
        "sessions_read": len(sessions),
        "sessions_skipped": skipped,
        "excluded": found["excluded"],
        "recurring": found["recurring"][: args.limit],
        "truncated": len(found["recurring"]) > args.limit,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


# --- C5: follow-up sessions ------------------------------------------------------


# Variables that choose the repository ahead of `-C`: set by a git hook or by
# the caller's shell, they would make every probe answer for that repository.
GIT_LOCATION_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
    }
)


def _git_lines(directory: str, *args: str) -> list[str] | None:
    """The output lines of one git command in a directory, or None."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARS}
    try:
        out = subprocess.run(
            ["git", "-C", directory, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # a directory outside any repository is an ordinary answer
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.split("\n") if out.returncode == 0 else None


@functools.cache
def _rev_parse(directory: str, *query: str) -> list[str] | None:
    """The answer lines of `git rev-parse` in a directory, or None."""
    return _git_lines(directory, "rev-parse", *query)


@functools.cache
def _branch_names(bare: str) -> frozenset[str]:
    """The branch names a bare repository knows: its own, and those of its
    remote-tracking branches without the remote's name (`origin/fix/x` is
    `fix/x`)."""
    lines = _git_lines(
        bare, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"
    )
    names = set()
    for ref in lines or []:
        if ref.startswith("refs/heads/"):
            names.add(ref[len("refs/heads/") :])
        elif ref.startswith("refs/remotes/"):
            _remote, _, name = ref[len("refs/remotes/") :].partition("/")
            if name and name != "HEAD":
                names.add(name)
    return frozenset(names)


# The directory name of the bare repository in a bare-repository layout.
BARE_DIR = ".bare"


def _bare_project(directory: Path) -> Path | None:
    """The nearest directory at or above `directory` that holds a bare
    repository named `.bare`, or None."""
    for candidate in (directory, *directory.parents):
        bare = candidate / BARE_DIR
        if bare.is_dir() and _rev_parse(str(bare), "--is-bare-repository") == [
            "true",
            "",
        ]:
            return candidate
    return None


def _worktree_depth(project: Path, probe: Path, parts: tuple[str, ...]) -> int:
    """How many leading components of `parts` (a path below `project`) named
    the directory of a worktree that no longer exists.

    `git worktree remove` deletes the worktree's own directory and nothing
    above it, so when a branch with a slash (`fix/x`) had its worktree in
    `<project>/fix/x`, the empty `fix/` that remains says the worktree sat one
    level below it. When that is gone too, a branch of the same name says how
    deep it went — `worktree remove` keeps the branch, and a remote-tracking
    copy outlives a local `branch -d` until the next `fetch --prune`. With
    neither, the worktree is taken to be the first directory below the
    deepest one that still exists: a `fix/x` whose branch is deleted
    everywhere and whose `fix/` was removed as well keys as `x/…`."""
    existing = len(probe.relative_to(project).parts)
    names = _branch_names(str(project / BARE_DIR))
    for depth in range(len(parts) - 1, existing, -1):
        if "/".join(parts[:depth]) in names:
            return depth
    return existing + 1


def _repository_of_dir(directory: str) -> tuple[str, str] | None:
    """(git common dir, top level) for a directory inside a work tree."""
    lines = _rev_parse(
        directory, "--path-format=absolute", "--git-common-dir", "--show-toplevel"
    )
    if not lines or len(lines) < 2 or not lines[1]:
        return None
    return lines[0], lines[1]


def file_key(path: str) -> tuple[str | None, str]:
    """(repository, path inside it) for an edited file.

    The same file carries a different absolute path in every worktree, and a
    worktree is usually removed after its branch merged — so the key is the
    repository's common git directory plus the path inside the work tree, and a
    removed worktree of a bare-repository layout (`<project>/.bare` beside
    `<project>/<worktree>/`) is recognised from the project directory that
    remains. The `.bare` is looked for in every directory above the file, since
    a worktree of a branch with a slash (`fix/x`) leaves an empty `fix/`
    behind, and the worktree's own part of the path (`fix/x/`) is dropped —
    see `_worktree_depth`. That `.bare` is asked first: a project directory
    inside another work tree would otherwise answer with the outer one; only a
    work tree below the project directory — a live worktree — answers. A file
    outside any repository keeps its absolute path.
    """
    target = Path(path)
    probe = target.parent
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    found = _repository_of_dir(str(probe))
    project = _bare_project(probe)
    live = (
        found is not None
        and project is not None
        and project.resolve() in Path(found[1]).resolve().parents
    )
    if project is not None and not live:
        parts = target.relative_to(project).parts
        # At least one directory of the worktree that is gone, then the file.
        if len(parts) >= len(probe.relative_to(project).parts) + 2:
            depth = _worktree_depth(project, probe, parts)
            return str((project / BARE_DIR).resolve()), "/".join(parts[depth:])
    if found:
        common, top = found
        try:
            return str(Path(common).resolve()), target.relative_to(top).as_posix()
        except ValueError:
            return None, path
    return None, path


def _edit_pairs(call: dict[str, Any]) -> list[tuple[str, str]]:
    """(old_string, new_string) of an Edit or a MultiEdit call."""
    inp = call["input"]
    if call["name"] == "Edit":
        return [(str(inp.get("old_string", "")), str(inp.get("new_string", "")))]
    if call["name"] == "MultiEdit":
        return [
            (str(e.get("old_string", "")), str(e.get("new_string", "")))
            for e in inp.get("edits") or []
            if isinstance(e, dict)
        ]
    return []


def _revert_targets(command: str) -> list[str]:
    targets = []
    for match in GIT_REVERT_RE.finditer(command):
        try:
            tokens = shlex.split(match.group("args"))
        except ValueError:
            tokens = match.group("args").split()
        targets.extend(t for t in tokens if HEX_RE.fullmatch(t))
    return targets


def _same_commit(a: str, b: str) -> bool:
    return a.startswith(b) or b.startswith(a)


Edits = dict[tuple[str | None, str], dict[str, list[tuple[str, str]]]]


def _collect_work(
    sessions: list[dict[str, Any]],
) -> tuple[Edits, dict[str, list[str]], dict[str, list[str]]]:
    """Per session: the edits by file, the commits written, the commits reverted."""
    edits: Edits = defaultdict(lambda: defaultdict(list))
    commits: dict[str, list[str]] = defaultdict(list)
    reverts: dict[str, list[str]] = defaultdict(list)
    for session in sessions:
        for call in (c for c in session["calls"] if not c["is_error"]):
            pairs = _edit_pairs(call)
            path = call["input"].get("file_path")
            if pairs and isinstance(path, str) and path:
                edits[file_key(path)][session["id"]].extend(pairs)
            if call["name"] == "Bash":
                command = str(call["input"].get("command", ""))
                commits[session["id"]].extend(COMMIT_LINE_RE.findall(call["result"]))
                reverts[session["id"]].extend(_revert_targets(command))
    return edits, commits, reverts


def _pairs_in_window(
    sessions: list[dict[str, Any]], window: timedelta
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(earlier, later) sessions whose gap is at most `window`."""
    ordered = sorted(
        (s for s in sessions if s["start"] and s["end"]), key=lambda s: s["start"]
    )
    return [
        (a, b)
        for i, a in enumerate(ordered)
        for b in ordered[i + 1 :]
        if b["start"] > a["start"] and b["start"] - a["end"] <= window
    ]


def _rewrites(earlier: list[tuple[str, str]], later: list[tuple[str, str]]) -> bool:
    """The later edits replace text the earlier edits wrote."""
    written = [n for _o, n in earlier if len(n.strip()) >= MIN_REWRITE_CHARS]
    return any(n in old for n in written for old, _n in later)


def _rewritten_edits(edits: Edits, pairs: list) -> list[dict[str, Any]]:
    rewritten = []
    for (repository, rel), by_session in edits.items():
        for a, b in pairs:
            earlier, later = by_session.get(a["id"]), by_session.get(b["id"])
            if not earlier or not later or not _rewrites(earlier, later):
                continue
            rewritten.append(
                {
                    "repository": repository,
                    "file": rel,
                    "earlier_session": a["id"],
                    "later_session": b["id"],
                    # The later session put back exactly what the earlier replaced.
                    "exact_revert": any(
                        o_a == n_b and n_a == o_b
                        for o_a, n_a in earlier
                        for o_b, n_b in later
                    ),
                    "hours_apart": round(
                        (b["start"] - a["end"]).total_seconds() / 3600, 1
                    ),
                }
            )
    rewritten.sort(key=lambda r: (not r["exact_revert"], r["hours_apart"]))
    return rewritten


def _reverted_commits(
    commits: dict[str, list[str]], reverts: dict[str, list[str]], pairs: list
) -> list[dict[str, Any]]:
    return [
        {"commit": sha, "earlier_session": a["id"], "later_session": b["id"]}
        for a, b in pairs
        for target in reverts.get(b["id"], [])
        for sha in commits.get(a["id"], [])
        if _same_commit(sha, target)
    ]


def follow_up_sessions(
    sessions: list[dict[str, Any]], window: timedelta
) -> dict[str, list[dict[str, Any]]]:
    """Session pairs where the later one undid or rewrote the earlier one's work."""
    edits, commits, reverts = _collect_work(sessions)
    pairs = _pairs_in_window(sessions, window)
    return {
        "rewritten_edits": _rewritten_edits(edits, pairs),
        "reverted_commits": _reverted_commits(commits, reverts, pairs),
    }


def cmd_follow_up_sessions(args, files) -> int:
    sessions, skipped = read_sessions(files)
    found = follow_up_sessions(sessions, timedelta(days=args.window_days))
    output = {
        "mode": "follow-up-sessions",
        "days": args.days,
        "window_days": args.window_days,
        "sessions_read": len(sessions),
        "sessions_skipped": skipped,
        "reverted_commits": found["reverted_commits"][: args.limit],
        "rewritten_edits": found["rewritten_edits"][: args.limit],
        "truncated": any(len(v) > args.limit for v in found.values()),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


# --- C7: per-rule tally ---------------------------------------------------------

# A rule's identity: its [→A123] anchors where the file has them, else a hash of
# its text, which changes when the rule's wording does.
ANCHOR_RE = re.compile(r"\[→\s*(A\d+(?:\s*,\s*A\d+)*)")
LIST_MARKER_RE = re.compile(r"\A\s*(?:[-*+]|\d+[.)])\s+")
# A placeholder or an ellipsis never appears in a real command; only the literal
# text before it can.
KEYWORD_GAP_RE = re.compile(r"<[^<>]*>|\{[^{}]*\}|…|\.\.\.|\*")
BARE_WORD_RE = re.compile(r"[\w-]{1,5}")
MIN_KEYWORD_CHARS = 3
# A chunk that quotes the rule's opening is the rule being read, not its topic.
QUOTE_CHARS = 40
# Chosen, not measured: below this many scanned sessions a zero says little.
DEFAULT_MIN_SESSIONS = 30
# Tally output read back, indented or compact (jq -c), is not a use.
TALLY_OUTPUT_RE = re.compile(r'"mode":\s*"rule-tally"|"violation_candidate_sessions"')
_MD = MarkdownIt("commonmark")


def _flat(text: str) -> str:
    return " ".join(text.split()).lower()


def _keyword(span: str) -> str | None:
    parts = KEYWORD_GAP_RE.split(span, maxsplit=1)
    literal = parts[0].strip()
    if len(parts) > 1 and BARE_WORD_RE.fullmatch(literal):
        # A short word left before a cut (`try {...}`, `OPS{X}`) is too
        # common to stand for the rule: it would hit in most sessions.
        return None
    return literal if len(literal) >= MIN_KEYWORD_CHARS else None


def _list_items(text: str) -> tuple[list[dict[str, Any]], int]:
    """Top-level list items with their source and code spans, and prose lines."""
    lines = text.splitlines()
    tokens = _MD.parse(text)
    items, heading, depth, outside = [], "", 0, 0
    for index, tok in enumerate(tokens):
        if tok.type in ("bullet_list_open", "ordered_list_open"):
            depth += 1
        elif tok.type in ("bullet_list_close", "ordered_list_close"):
            depth -= 1
        elif tok.type == "heading_open":
            heading = tokens[index + 1].content
        elif tok.type == "list_item_open" and depth == 1:
            start, end = tok.map
            source = LIST_MARKER_RE.sub("", "\n".join(lines[start:end]), count=1)
            items.append(
                {"line": start + 1, "heading": heading, "source": source, "spans": []}
            )
        elif tok.type == "inline" and depth and items:
            items[-1]["spans"] += _code_spans(tok)
        elif tok.type == "paragraph_open" and not depth:
            outside += tok.map[1] - tok.map[0]
    return items, outside


def _code_spans(tok: Any) -> list[str]:
    return [c.content for c in tok.children or () if c.type == "code_inline"]


def _rule_id(source: str, flat: str, seen: Counter[str]) -> str:
    """The anchors, else a text hash; a repeated id gets a #N suffix."""
    anchor = ANCHOR_RE.search(source)
    if anchor:
        rule_id = re.sub(r"\s", "", anchor[1])
    else:
        rule_id = "h:" + hashlib.sha256(flat.encode()).hexdigest()[:10]
    seen[rule_id] += 1
    return f"{rule_id}#{seen[rule_id]}" if seen[rule_id] > 1 else rule_id


def _blank_frontmatter(text: str) -> str:
    """Blank a leading YAML frontmatter block, keeping line numbers."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    for end in range(1, len(lines)):
        if lines[end].strip() in ("---", "..."):
            return "\n" * (end + 1) + "\n".join(lines[end + 1 :])
    return text


def parse_rules(text: str) -> dict[str, Any]:
    """Top-level list items of a Markdown file, each with an id, line and keywords."""
    items, outside = _list_items(_blank_frontmatter(text))
    rules, seen = [], Counter()
    for item in items:
        flat = _flat(item["source"])
        keywords = {k for k in map(_keyword, item["spans"]) if k}
        rules.append(
            {
                "id": _rule_id(item["source"], flat, seen),
                "line": item["line"],
                "heading": item["heading"],
                "keywords": sorted(keywords),
                "quote": flat[:QUOTE_CHARS],
            }
        )
    return {"rules": rules, "lines_outside_rules": outside}


def _strings(value: Any) -> Iterator[str]:
    """The string values of a tool input, unescaped, at any depth."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _chunks(session: dict[str, Any]) -> Iterator[tuple[str, bool]]:
    """Each text a session saw, flattened, and whether it reads as a failure.

    A refused call is a gate doing its job, not a violation (see C6)."""
    for call in session["calls"]:
        failed = call["is_error"] and not is_refusal(call["name"], call["result"])
        yield _flat(" ".join(_strings(call["input"]))), failed
        yield _flat(call["result"]), failed
    for text in session["user_texts"]:
        yield _flat(text), bool(CORRECTION_PATTERNS.search(text))


def ran_tally(calls: list[dict[str, Any]]) -> bool:
    return any("--rule-tally" in " ".join(_strings(c["input"])) for c in calls)


class _KeywordMatcher:
    """Each distinct keyword tested once per chunk, for every rule that has it.

    A substring test per keyword measured about five times faster than one
    alternation regex over all of them, and it finds overlapping keywords."""

    def __init__(self, rules: list[dict[str, Any]]) -> None:
        self.rules_of: dict[str, list[int]] = defaultdict(list)
        for index, rule in enumerate(rules):
            for keyword in rule["keywords"]:
                self.rules_of[_flat(keyword).lower()].append(index)

    def rules_in(self, chunk: str) -> set[int]:
        return {i for k, rules in self.rules_of.items() if k in chunk for i in rules}


def _scan_session(
    session: dict[str, Any],
    rules: list[dict[str, Any]],
    matcher: _KeywordMatcher,
    hits: list[set[str]],
    flagged: list[set[str]],
) -> None:
    for chunk, failed in _chunks(session):
        if TALLY_OUTPUT_RE.search(chunk):
            continue
        for index in matcher.rules_in(chunk):
            if rules[index]["quote"] in chunk:
                continue
            hits[index].add(session["id"])
            if failed:
                flagged[index].add(session["id"])


def _session_kind(session: dict[str, Any]) -> str:
    # A session that ran a tally reads its candidates back; they are not uses.
    if session["ran_tally"]:
        return "ran_a_tally"
    if not session["calls"] and not session["user_texts"]:
        return "empty"
    return "scanned"


def _tally_row(
    rule: dict[str, Any], hit: set[str], flag: set[str], limit: int
) -> dict[str, Any]:
    return {
        "id": rule["id"],
        "line": rule["line"],
        "heading": mask(rule["heading"]),
        "keywords": [mask(k) for k in rule["keywords"]],
        "state": "measured" if rule["keywords"] else "not_measurable",
        "applicable_sessions": len(hit),
        "violation_candidate_sessions": len(flag),
        "sessions": sorted(hit)[:limit],
        "violation_candidates": sorted(flag)[:limit],
    }


def rule_tally(
    rules: list[dict[str, Any]], sessions: Iterable[dict[str, Any]], limit: int
) -> dict[str, Any]:
    """Per rule: sessions whose text names a keyword, and those where it failed."""
    matcher = _KeywordMatcher(rules)
    hits = [set() for _ in rules]
    flagged = [set() for _ in rules]
    counts = Counter()
    for session in sessions:
        kind = _session_kind(session)
        counts[kind] += 1
        if kind == "scanned":
            _scan_session(session, rules, matcher, hits, flagged)
    tally = [
        _tally_row(rule, hit, flag, limit)
        for rule, hit, flag in zip(rules, hits, flagged, strict=True)
    ]
    return {
        "rules": tally,
        "sessions_scanned": counts["scanned"],
        "sessions_that_ran_a_tally": counts["ran_a_tally"],
        "sessions_empty": counts["empty"],
        "truncated": any(len(h) > limit for h in hits),
    }


def _tally_sessions(
    files: list[tuple[Path, str]], gaps: Counter[str], skipped: list[str]
) -> Iterator[dict[str, Any]]:
    """Each transcript read once and released after its turn in the tally."""
    for path, _project in files:
        events = load_events(path, gaps)
        if not events:
            skipped.append(str(path))
            continue
        calls = tool_calls(events)
        yield {
            "id": path.stem,
            "calls": calls,
            "user_texts": user_texts_of(events, gaps),
            "ran_tally": ran_tally(calls),
        }


def cmd_rule_tally(args, files, text: str, gaps: Counter[str]) -> int:
    parsed = parse_rules(text)
    skipped: list[str] = []
    found = rule_tally(
        parsed["rules"], _tally_sessions(files, gaps, skipped), args.limit
    )
    tally = found.pop("rules")
    enough = found["sessions_scanned"] >= args.min_sessions
    print(
        json.dumps(
            {
                "mode": "rule-tally",
                "signal": "C7",
                "rules_file": str(args.rule_tally),
                "days": args.days,
                **found,
                "sessions_skipped": skipped,
                "gaps": dict(gaps),
                "min_sessions": args.min_sessions,
                "window_sufficient": enough,
                "rules_total": len(tally),
                "rules_not_measurable": sum(
                    r["state"] == "not_measurable" for r in tally
                ),
                "lines_outside_rules": parsed["lines_outside_rules"],
                "never_applicable": [
                    r["id"]
                    for r in tally
                    if r["state"] == "measured" and not r["applicable_sessions"]
                ]
                if enough
                else None,
                "rules": tally,
                "interpretation": "Keyword hits are candidates; followed or violated "
                "is judged by reading the sessions. Zero hits can mean the rule "
                "prevents its mistake silently.",
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def learning_effectiveness(observations: Any) -> dict[str, Any]:
    """C4: summarize explicit later opportunities, not inferred non-use.

    The caller supplies evidence-backed states; this script validates and
    counts them. It cannot infer causation, complete coverage, or loaded skill
    versions from an absent citation or a recurring error string.
    """
    states = ("adopted", "available", "loaded", "applicable", "applied", "success")
    if not isinstance(observations, list):
        raise TypeError("learning observations must be a JSON array")
    distinct, duplicates = {}, 0
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            raise TypeError(f"observation {index}: expected object")
        for field in ("learning_id", "opportunity_id", "evidence"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"observation {index}: nonempty {field} required")
        if any(
            item.get(field) is not None and type(item[field]) is not bool
            for field in states
        ):
            raise ValueError(f"observation {index}: states must be boolean or null")
        item = {
            field: item.get(field)
            for field in ("learning_id", "opportunity_id", "evidence", *states)
        }
        item["evidence"] = mask(item["evidence"])
        key = (item["learning_id"], item["opportunity_id"])
        if key in distinct:
            # More copies are not independent evidence. Contradictory copies
            # require reconciliation rather than keeping a convenient result.
            if distinct[key] != item:
                raise ValueError(f"conflicting observations at index {index}")
            duplicates += 1
        else:
            distinct[key] = item
    grouped = defaultdict(list)
    for item in distinct.values():
        grouped[item["learning_id"]].append(item)
    learnings = []
    for identity, items in sorted(grouped.items()):
        tested = [
            item
            for item in items
            if all(item.get(field) is True for field in states[:-1])
            and type(item.get("success")) is bool
        ]
        successful = sum(item["success"] for item in tested)
        learnings.append(
            {
                "learning_id": identity,
                "observed_opportunities": len(items),
                "applicable_opportunities": sum(
                    item.get("applicable") is True for item in items
                ),
                "tested_applications": len(tested),
                "successful_applications": successful,
                "failed_applications": len(tested) - successful,
                "unassessed": len(items) - len(tested),
                "unknown_states": {
                    field: sum(item.get(field) is None for item in items)
                    for field in states
                },
                "success_rate": successful / len(tested) if tested else None,
                "observations": items,
            }
        )
    return {
        "mode": "learning-effectiveness",
        "signal": "C4",
        "coverage": "supplied_observations_only",
        "duplicates_ignored": duplicates,
        "learnings": learnings,
        "interpretation": "Observed application outcomes; no causal or comparative effectiveness claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-dir", type=Path, default=DEFAULT_PROJECTS_DIR)
    parser.add_argument("--project", help="Specific project slug (e.g. -home-sme-p)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--pattern",
        help="Search for keyword/phrase in user turns (mostly typed text; not tool results or assistant replies)",
    )
    parser.add_argument(
        "--user-correction-summary",
        action="store_true",
        help="Summarize correction patterns across sessions and projects (C1, C2)",
    )
    parser.add_argument(
        "--recurring-failures",
        action="store_true",
        help="The same failing tool call in two or more sessions (C1)",
    )
    parser.add_argument(
        "--include-refusals",
        action="store_true",
        help="With --recurring-failures: also list calls a hook or the harness refused",
    )
    parser.add_argument(
        "--follow-up-sessions",
        action="store_true",
        help="Later sessions that reverted or rewrote an earlier session's work (C5)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="With --follow-up-sessions: the most days between the two sessions",
    )
    parser.add_argument(
        "--rule-tally",
        type=Path,
        help="C7: per rule of this instruction file, the sessions its keywords appear in",
    )
    parser.add_argument(
        "--min-sessions",
        type=int,
        default=DEFAULT_MIN_SESSIONS,
        help="With --rule-tally: fewer sessions read withholds never_applicable",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--learning-observations",
        type=Path,
        help="C4: explicit evidence-backed adoption/application/outcome states",
    )
    args = parser.parse_args()

    if args.learning_observations is not None:
        try:
            # S8707: explicit caller-selected local evidence, not a path from
            # untrusted session content. No privilege boundary is crossed;
            # restricted wrappers must enforce their own authorized roots.
            observations = json.loads(
                args.learning_observations.read_text(encoding="utf-8")  # NOSONAR
            )
            print(
                json.dumps(
                    learning_effectiveness(observations), indent=2, ensure_ascii=False
                )
            )
        except (OSError, ValueError, TypeError) as error:
            parser.exit(2, f"scan-cross-session: {error}\n")
        return 0

    rules_text = None
    if args.rule_tally is not None:
        try:
            # S8707: explicit caller-selected local instruction file, not a path
            # from untrusted session content. No privilege boundary is crossed.
            rules_text = args.rule_tally.read_text(encoding="utf-8")  # NOSONAR
        except (OSError, UnicodeDecodeError) as error:
            parser.exit(2, f"scan-cross-session: {error}\n")

    if args.project is not None and (
        args.project in ("", ".", "..") or Path(args.project).name != args.project
    ):
        parser.error("--project expects one nonempty project slug")

    gaps: Counter[str] = Counter()
    try:
        files = session_files(args.projects_dir, args.project, args.days, gaps)
    except OSError as error:
        print(
            json.dumps(
                {
                    "available": False,
                    "reason": str(error),
                    "coverage": {"status": "unavailable", "project": args.project},
                }
            )
        )
        return 0

    if args.pattern:
        return cmd_pattern(args, files, gaps)
    if args.user_correction_summary:
        return cmd_correction_summary(args, files, gaps)
    if args.recurring_failures:
        return cmd_recurring_failures(args, files)
    if args.follow_up_sessions:
        return cmd_follow_up_sessions(args, files)
    if rules_text is not None:
        return cmd_rule_tally(args, files, rules_text, gaps)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
