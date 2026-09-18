#!/usr/bin/env python3
"""
derive-session-scope.py — the repositories, days and artefacts a session touched.

Front-end for gate 4 of `/retro done`. That gate is only as wide as the set it
sweeps: `git worktree list` in the wrong repository returns clean, and a ✅ that
measured nothing is worse than a ❌. Until now `references/done-mode.md` said
the repository list was "an input, not an output" because no command produced
it, so it came from what the agent remembered doing.

That is exactly where it fails. In the session that prompted this script the
agent named three repositories and reported the sweep clean; asked again it
found eight, two of them holding leftovers. This script, on the same
transcript, returned fifteen — and two of the seven nobody had looked at held
an orphaned branch and a dirty working tree. Every round was an honest
recollection and every round was short, because remembering is the wrong
instrument for a list that is written down, verbatim, in the transcript.

So this reads the transcript and emits the scope line. Every path a `git -C`,
a `cd`, a file write or a `--repo`/`-R` argument named, resolved to its
repository root, plus the days the session spans and the artefacts it created.

Usage:
    derive-session-scope.py --transcript-file <session.jsonl> [--output-format text|json]

The output is a starting point that is complete where the transcript is: a
repository the session only ever reached through a tool with no path in its
input cannot appear here. Read the list, add what you know is missing, and
sweep that — the point is that nothing the transcript recorded is silently
dropped.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# `git -C <path>`, `cd <path>`, `-R owner/repo`, `--repo owner/repo`.
GIT_C_RE = re.compile(r"git\s+-C\s+(?P<path>(?:\"[^\"]+\"|'[^']+'|[^\s;|&]+))")
CD_RE = re.compile(
    r"(?:^|[;&|]\s*|\&\&\s*)cd\s+(?P<path>(?:\"[^\"]+\"|'[^']+'|[^\s;|&]+))"
)
FORGE_RE = re.compile(r"(?:-R|--repo)[\s=](?P<slug>[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)")
# Artefacts worth naming in the scope line.
ARTEFACT_RE = re.compile(
    r"\b(?:gh|glab)\s+(?:pr|mr|release|issue)\s+(?:create|merge|edit)\b"
    r"|\bgit\s+(?:tag|push)\s+(?:-s\s+)?(?:origin\s+)?(?P<tag>v?\d+\.\d+\.\d+)\b"
)


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def repo_root(path: Path) -> Path | None:
    """The repository a path belongs to, or None.

    Resolved with git rather than by looking for a `.git` entry: `~/p` uses
    bare repositories with worktrees, where a worktree holds a `.git` FILE
    pointing elsewhere and the naive check misses every one of them.
    """
    probe = path if path.is_dir() else path.parent
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # a non-repository path is an ordinary answer here
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (
        Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    )


def iter_events(path: Path):
    # `.resolve()` before opening: the path arrives as a CLI argument an agent
    # composed, and canonicalising it collapses any `..` segment rather than
    # following it. The file itself is deliberately unbounded - the opencode
    # adapter writes its transcript to stdout, so a legitimate one lives
    # wherever the operator redirected it.
    with path.resolve().open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _tool_inputs(event: dict[str, Any]):
    """Every tool_use input in one transcript event."""
    message = event.get("message") or {}
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            payload = block.get("input") or {}
            if isinstance(payload, dict):
                yield payload


def _absolute_paths(payload: dict[str, Any]) -> set[str]:
    """The absolute paths a tool input names under its path-ish keys."""
    found = set()
    for key in ("file_path", "notebook_path", "path"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("/"):
            found.add(value)
    return found


def _day_of(event: dict[str, Any]) -> str | None:
    stamp = event.get("timestamp")
    return stamp[:10] if isinstance(stamp, str) and len(stamp) >= 10 else None


def _read_transcript(transcript: Path) -> tuple[list[str], set[str], set[str]]:
    """The Bash commands, the absolute file paths, and the days."""
    commands: list[str] = []
    file_paths: set[str] = set()
    days: set[str] = set()
    for event in iter_events(transcript):
        day = _day_of(event)
        if day:
            days.add(day)
        for payload in _tool_inputs(event):
            command = payload.get("command")
            if isinstance(command, str):
                commands.append(command)
            file_paths |= _absolute_paths(payload)
    return commands, file_paths, days


def _scan_commands(commands: list[str]) -> tuple[set[str], set[str], set[str]]:
    """Candidate paths, forge slugs and release tags named on command lines."""
    candidates: set[str] = set()
    forges: set[str] = set()
    tags: set[str] = set()
    for command in commands:
        for pattern in (GIT_C_RE, CD_RE):
            for match in pattern.finditer(command):
                candidates.add(unquote(match.group("path")))
        for match in FORGE_RE.finditer(command):
            forges.add(match.group("slug"))
        for match in ARTEFACT_RE.finditer(command):
            if match.group("tag"):
                tags.add(match.group("tag"))
    return candidates, forges, tags


def _resolve_roots(candidates: set[str]) -> tuple[set[str], set[str]]:
    """Split candidate paths into repository roots and what stayed unresolved."""
    roots: set[str] = set()
    unresolved: set[str] = set()
    for raw in candidates:
        # A path built from a shell variable cannot be resolved without running
        # the shell, and guessing at it would put a wrong repository in the
        # scope line, which is worse than a short one.
        if "$" in raw or "`" in raw:
            unresolved.add(raw)
            continue
        root = repo_root(Path(raw))
        if root is not None:
            roots.add(str(root))
        elif raw.startswith("/"):
            unresolved.add(raw)
    return roots, unresolved


def collect(transcript: Path) -> dict[str, Any]:
    commands, file_paths, days = _read_transcript(transcript)
    candidates, forges, tags = _scan_commands(commands)
    roots, unresolved = _resolve_roots(candidates | file_paths)

    return {
        "transcript": str(transcript),
        "repositories": sorted(roots),
        "days": sorted(days),
        "forge_slugs": sorted(forges),
        "tags": sorted(tags),
        # Not truncated. This is the list whose whole purpose is "read these,
        # a missing repository hides here", and a silent [:20] would drop the
        # entries a long session most needs to see.
        "unresolved_paths": sorted(unresolved),
        "commands_scanned": len(commands),
    }


# How many unresolved paths the text rendering shows before pointing at the
# JSON. The JSON is never truncated.
TEXT_UNRESOLVED_LIMIT = 20


def render_text(scope: dict[str, Any]) -> str:
    repos = scope["repositories"]
    lines = [
        f"Scope: {len(repos)} repositories · {', '.join(scope['days']) or 'no timestamps'}"
        + (f" · tags {', '.join(scope['tags'])}" if scope["tags"] else ""),
        "",
    ]
    lines += [f"  {r}" for r in repos] or ["  (none found — check the transcript path)"]
    if scope["forge_slugs"]:
        lines += ["", "Forge repositories addressed by slug (may have no local clone):"]
        lines += [f"  {s}" for s in scope["forge_slugs"]]
    unresolved = scope["unresolved_paths"]
    if unresolved:
        shown = unresolved[:TEXT_UNRESOLVED_LIMIT]
        lines += [
            "",
            f"{len(unresolved)} paths could not be resolved to a repository — read these,",
            "they are where a missing entry hides (a shell variable, or a directory",
            "since removed):",
        ]
        lines += [f"  {p}" for p in shown]
        if len(unresolved) > len(shown):
            # Named, not silent. The JSON carries all of them; a text list that
            # quietly stopped at twenty would hide exactly what this section is
            # for on the long sessions that need it most.
            lines.append(
                f"  … showing {len(shown)} of {len(unresolved)};"
                " --output-format json has the rest"
            )
    lines += [
        "",
        f"({scope['commands_scanned']} Bash commands scanned. Complete where the transcript is:",
        "a repository reached only through a tool that took no path cannot appear here.)",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript-file", required=True, type=Path)
    parser.add_argument("--output-format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv[1:])

    if not args.transcript_file.is_file():
        print(f"no such transcript: {args.transcript_file}", file=sys.stderr)
        return 2

    scope = collect(args.transcript_file)
    if args.output_format == "json":
        print(json.dumps(scope, indent=2))
    else:
        print(render_text(scope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
