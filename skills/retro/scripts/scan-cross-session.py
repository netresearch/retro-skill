#!/usr/bin/env python3
"""
scan-cross-session.py — Schicht-C cross-session data source.

Scans Claude Code session JSONL files across projects to find similar friction
patterns. Used to detect "same friction again" (C1), "cross-project pattern"
(C2) and "follow-up-fix session" (C5) signals.

Usage:
    python3 scan-cross-session.py --pattern "<keyword or phrase>" [--days 30] [--project <slug>]
    python3 scan-cross-session.py --user-correction-summary [--days 7]
    python3 scan-cross-session.py --recurring-failures [--days 30] [--limit 20] [--include-refusals]
    python3 scan-cross-session.py --follow-up-sessions [--days 30] [--window-days 7] [--limit 20]

The last two modes read every tool call of every transcript in the window, so
they run on demand (an audit), not per event. Each reports only what recurs in
at least two sessions, names the sessions it was computed from, and caps its
lists at --limit. Their output is a candidate list for the model to read, not a
verdict: a hit says where to look.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


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


def session_files(
    projects_dir: Path, project_slug: str | None, days: int
) -> list[tuple[Path, str]]:
    """Return list of (jsonl_path, project_slug) within the last N days."""
    cutoff = datetime.now() - timedelta(days=days)  # noqa: DTZ005 -- naive local time, compared against naive file mtimes below
    out = []
    if project_slug:
        candidates = [projects_dir / project_slug]
    else:
        candidates = [p for p in projects_dir.iterdir() if p.is_dir()]
    for proj_dir in candidates:
        if not proj_dir.exists():
            continue
        for f in proj_dir.glob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)  # noqa: DTZ006 -- naive local time, compared against naive cutoff above
            except OSError:
                continue
            if mtime >= cutoff:
                out.append((f, proj_dir.name))
    return out


def load_events(path: Path) -> list[dict[str, Any]] | None:
    """The transcript's event objects, or None when it cannot be read.

    A transcript can vanish between listing and reading while another session
    runs, and a line can hold JSON that is not an object; neither may abort the
    scan or be counted as a session.
    """
    events = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict):
                    events.append(ev)
    except OSError:
        return None
    return events


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


def extract_user_texts(path: Path) -> list[str]:
    """What a human typed: the text of every user turn the harness did not
    write itself.

    The harness stamps its own user turns — hook feedback (`Stop hook
    feedback: …`), slash-command expansions, notifications — with `isMeta`,
    and a compaction recap with `isCompactSummary`; the markers are the
    fallback for transcripts older than those flags, as in
    detect-mechanical.py. Without this, `--user-correction-summary` counted a
    hook's `Stop …` feedback, repeated in every session, as a correction."""
    texts = []
    for ev in load_events(path) or []:
        if ev.get("type") != "user":
            continue
        if ev.get("isMeta") or ev.get("isCompactSummary"):
            continue
        msg = ev.get("message", {}) or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        found = []
        if isinstance(content, str):
            found.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    found.append(text if isinstance(text, str) else "")
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
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
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


def cmd_pattern(args, files) -> int:
    pattern = re.compile(re.escape(args.pattern), re.IGNORECASE)
    hits = defaultdict(list)
    for path, proj in files:
        for txt in extract_user_texts(path):
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
                "pattern": args.pattern,
                "days": args.days,
                "projects_with_matches": len(hits),
                "matches": dict(hits),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_correction_summary(args, files) -> int:
    corrections_by_project: dict[str, Counter] = defaultdict(Counter)
    # C1 is "the same correction in several sessions"; C2 is the same across
    # projects. Counting only projects hid C1 inside a single project.
    sessions_by_key: dict[str, set[str]] = defaultdict(set)
    projects_by_key: dict[str, set[str]] = defaultdict(set)
    for path, proj in files:
        for txt in extract_user_texts(path):
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
        "sessions_scanned": len(files),
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


def _bare_project(directory: Path) -> Path | None:
    """The nearest directory at or above `directory` that holds a bare
    repository named `.bare`, or None."""
    for candidate in (directory, *directory.parents):
        bare = candidate / ".bare"
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
    names = _branch_names(str(project / ".bare"))
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
            return str((project / ".bare").resolve()), "/".join(parts[depth:])
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-dir", type=Path, default=DEFAULT_PROJECTS_DIR)
    parser.add_argument("--project", help="Specific project slug (e.g. -home-sme-p)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--pattern", help="Search for keyword/phrase in user messages")
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
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    if not args.projects_dir.exists():
        print(
            json.dumps(
                {"available": False, "reason": f"not found: {args.projects_dir}"}
            )
        )
        return 0

    files = session_files(args.projects_dir, args.project, args.days)
    if args.pattern:
        return cmd_pattern(args, files)
    if args.user_correction_summary:
        return cmd_correction_summary(args, files)
    if args.recurring_failures:
        return cmd_recurring_failures(args, files)
    if args.follow_up_sessions:
        return cmd_follow_up_sessions(args, files)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
