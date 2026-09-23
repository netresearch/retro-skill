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
        [--gitlab-host <host>]

The output is a starting point that is complete where the transcript is: a
repository the session only ever reached through a tool with no path in its
input cannot appear here. Read the list, add what you know is missing, and
sweep that — the point is that nothing the transcript recorded is silently
dropped.
"""

from __future__ import annotations

import argparse
import json
import os
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

GITHUB_HOST = "github.com"

# Pull requests, merge requests and issues, by URL. A GitLab project path may
# be nested (`group/sub/project`), and the `/-/` separator is what marks it.
GITHUB_URL_RE = re.compile(
    r"https://github\.com/(?P<project>[\w.-]+/[\w.-]+)/(?P<kind>pull|issues)/(?P<number>\d+)"
)
GITLAB_URL_RE = re.compile(
    r"https://(?P<host>(?!github\.com)[\w.-]+\.[a-z]{2,})/"
    r"(?P<project>[\w.-]+(?:/[\w.-]+)+)/-/(?P<kind>merge_requests|issues)/(?P<number>\d+)"
)
# A forge command that writes to a PR/MR/issue. `create` prints the URL of what
# it made; the others name a number and, usually, `-R`/`--repo`.
FORGE_WRITE_RE = re.compile(
    r"\b(?P<cli>gh|glab)\s+(?P<noun>pr|mr|issue)\s+"
    r"(?P<verb>create|edit|update|comment|note|merge|ready|review|close|reopen|approve)\b"
    r"(?P<rest>[^;&|\n]*)"
)
# MCP tools that write to a PR or issue; their input names owner/repo/number.
MCP_WRITE_RE = re.compile(
    r"github__(?:create_pull_request|update_pull_request|merge_pull_request|"
    r"pull_request_review_write|add_reply_to_pull_request_comment|"
    r"add_comment_to_pending_review|issue_write|add_issue_comment)"
)
# A Jira key a session acted on: the key on a command line that runs one of the
# jira skill's scripts, or the `ticket` a time booking named. Prefixes that are
# standards, not projects, are refused — `UTF-8`, `SHA-256`, `CVE-2025-1` would
# otherwise all read as tickets.
TICKET_RE = re.compile(r"\b(?P<key>[A-Z][A-Z0-9]{1,9}-\d+)\b")
NOT_A_TICKET_PREFIX = frozenset(
    {
        "CVE",
        "CWE",
        "GHSA",
        "UTF",
        "SHA",
        "ISO",
        "RFC",
        "TLS",
        "SSL",
        "HTTP",
        "PSR",
        "PEP",
        "ECMA",
        "WCAG",
        "OWASP",
        "ASD",
        "STE100",
        "X509",
        "AES",
    }
)
JIRA_COMMAND_RE = re.compile(r"\bjira-[a-z-]+\.py\b")


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


ORIGIN_RANK = {"mentioned": 0, "acted": 1, "created": 2}


def artefact(host: str, project: str, kind: str, number: int) -> dict[str, Any]:
    """One PR/MR/issue, keyed by its canonical URL."""
    kind = {"pull": "pull", "issues": "issue", "merge_requests": "merge_request"}.get(
        kind, kind
    )
    if host == GITHUB_HOST:
        path = "pull" if kind == "pull" else "issues"
        url = f"https://{GITHUB_HOST}/{project}/{path}/{number}"
    else:
        path = "merge_requests" if kind == "merge_request" else "issues"
        url = f"https://{host}/{project}/-/{path}/{number}"
    return {
        "forge": "github" if host == GITHUB_HOST else "gitlab",
        "host": host,
        "project": project,
        "kind": kind,
        "number": number,
        "url": url,
    }


def artefacts_in_text(text: str) -> list[dict[str, Any]]:
    found = [
        artefact(GITHUB_HOST, m["project"], m["kind"], int(m["number"]))
        for m in GITHUB_URL_RE.finditer(text)
    ]
    found += [
        artefact(m["host"], m["project"], m["kind"], int(m["number"]))
        for m in GITLAB_URL_RE.finditer(text)
    ]
    return found


def _with_origin(found: list[dict[str, Any]], origin: str) -> list[dict[str, Any]]:
    return [dict(a, origin=origin) for a in found]


def remote_project(path: str) -> tuple[str, str] | None:
    """(host, project) of the `origin` remote of the checkout at `path`."""
    if "$" in path or "`" in path or not Path(path).is_dir():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # no remote is an ordinary answer here
        )
    except (OSError, subprocess.SubprocessError):
        return None
    url = out.stdout.strip()
    m = re.match(
        r"(?:https://|ssh://git@|git@)(?P<host>[\w.-]+)(?::\d+)?[:/](?P<project>.+?)(?:\.git)?/?$",
        url,
    )
    return (m["host"], m["project"]) if out.returncode == 0 and m else None


def positional_number(rest: str) -> int | None:
    """The first bare number that is not the value of a flag (`--limit 5`)."""
    previous = ""
    for token in rest.split():
        if token.isdigit() and not (previous.startswith("-") and "=" not in previous):
            return int(token)
        previous = token
    return None


def _numbered_target(
    m: re.Match, command: str, number: int, gitlab_host: str
) -> dict[str, Any] | None:
    """The artefact a `<noun> <verb> <number>` names, via `-R` or the `cd` before it."""
    slug = FORGE_RE.search(m["rest"])
    if slug:
        host = GITHUB_HOST if m["cli"] == "gh" else gitlab_host
        project = slug["slug"]
    else:
        cd = CD_RE.search(command[: m.start()])
        where = remote_project(unquote(cd["path"])) if cd else None
        if not where:
            return None
        host, project = where
    kind = {"pr": "pull", "mr": "merge_request"}.get(m["noun"], "issue")
    return dict(artefact(host, project, kind, number), origin="acted")


def _one_write(
    m: re.Match, command: str, result: str, gitlab_host: str
) -> list[dict[str, Any]] | None:
    """What one forge write acted on; None when its target stays unknown."""
    rest = m["rest"]
    if m["verb"] == "create":
        # The URL `create` printed is the identity. A body text can name other
        # URLs, so only the result counts; no URL means nothing was made.
        return _with_origin(artefacts_in_text(result), "created")
    # The positional argument: a number, or a URL. Never a URL from inside
    # `--body`, which names other PRs as often as this one.
    words = rest.split()
    positional = artefacts_in_text(words[0]) if words else []
    if positional:
        return _with_origin(positional, "acted")
    number = positional_number(rest)
    if number is None:
        # `gh pr edit` on the current branch: the result may carry the URL.
        printed = artefacts_in_text(result)[:1]
        return _with_origin(printed, "acted") if printed else None
    target = _numbered_target(m, command, number, gitlab_host)
    return [target] if target else None


def _forge_write_artefacts(
    command: str, result: str, gitlab_host: str
) -> tuple[list[dict[str, Any]], bool]:
    """Artefacts one command's forge writes acted on, and whether any stayed unknown."""
    found: list[dict[str, Any]] = []
    unresolved = False
    for m in FORGE_WRITE_RE.finditer(command):
        items = _one_write(m, command, result, gitlab_host)
        if items is None:
            unresolved = True
        else:
            found += items
    return found, unresolved


def _mcp_write_artefacts(payload: dict[str, Any], result: str) -> list[dict[str, Any]]:
    owner, repo = payload.get("owner"), payload.get("repo")
    number = payload.get("pullNumber") or payload.get("issue_number")
    named = artefacts_in_text(result)
    if named:
        origin = "acted" if number else "created"
        return [dict(a, origin=origin) for a in named]
    if isinstance(owner, str) and isinstance(repo, str) and str(number or "").isdigit():
        kind = (
            "issue"
            if "issue" in payload.get("method", "") or "issue_number" in payload
            else "pull"
        )
        return [
            dict(
                artefact(GITHUB_HOST, f"{owner}/{repo}", kind, int(number)),
                origin="acted",
            )
        ]
    return []


def _result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return ""


def tickets_in(text: str) -> set[str]:
    return {
        m["key"]
        for m in TICKET_RE.finditer(text)
        if m["key"].split("-", 1)[0] not in NOT_A_TICKET_PREFIX
    }


class _ArtefactScan:
    """State of one pass over a transcript: pending tool calls and what they named."""

    def __init__(self, gitlab_host: str) -> None:
        self.gitlab_host = gitlab_host
        self.pending: dict[str, tuple[str, dict[str, Any]]] = {}
        self.by_url: dict[str, dict[str, Any]] = {}
        self.tickets: set[str] = set()
        self.unresolved: list[str] = []

    def keep(self, found: list[dict[str, Any]]) -> None:
        for item in found:
            have = self.by_url.get(item["url"])
            if not have or ORIGIN_RANK[item["origin"]] > ORIGIN_RANK[have["origin"]]:
                self.by_url[item["url"]] = item

    def mention(self, text: str) -> None:
        self.keep(_with_origin(artefacts_in_text(text), "mentioned"))

    def tool_use(self, block: dict[str, Any]) -> None:
        payload = block.get("input") or {}
        if not isinstance(payload, dict):
            return
        self.pending[block.get("id", "")] = (block.get("name", ""), payload)
        if block.get("name") == "mcp__tt__log_time":
            self.tickets |= tickets_in(str(payload.get("ticket", "")))

    def tool_result(self, block: dict[str, Any]) -> None:
        name, payload = self.pending.pop(block.get("tool_use_id", ""), ("", {}))
        result = _result_text(block)
        command = payload.get("command")
        if isinstance(command, str):
            found, lost = _forge_write_artefacts(command, result, self.gitlab_host)
            self.keep(found)
            if lost:
                self.unresolved.append(command[:200])
            if JIRA_COMMAND_RE.search(command):
                self.tickets |= tickets_in(command)
        elif MCP_WRITE_RE.search(name):
            self.keep(_mcp_write_artefacts(payload, result))
        self.mention(result)

    def event(self, event: dict[str, Any]) -> None:
        content = (event.get("message") or {}).get("content")
        if isinstance(content, str):
            self.mention(content)
            return
        handlers = {
            "tool_use": self.tool_use,
            "tool_result": self.tool_result,
            "text": lambda block: self.mention(block.get("text", "")),
        }
        for block in content or []:
            if isinstance(block, dict) and block.get("type") in handlers:
                handlers[block["type"]](block)


def collect_artefacts(transcript: Path, gitlab_host: str = "") -> dict[str, Any]:
    """The PRs, MRs, issues and Jira tickets a session created, acted on or mentioned.

    `origin` says how much the transcript supports the link: `created` (the
    command's own output printed the URL), `acted` (a write command named it),
    `mentioned` (a URL appeared somewhere, which includes documentation
    placeholders such as `OWNER/REPO` — a reader weighs those, a fetch skips them).
    """
    scan = _ArtefactScan(gitlab_host)
    for event in iter_events(transcript):
        scan.event(event)
    items = sorted(
        scan.by_url.values(), key=lambda a: (-ORIGIN_RANK[a["origin"]], a["url"])
    )
    return {
        "artefacts": items,
        "tickets": sorted(scan.tickets),
        "unresolved_forge_commands": scan.unresolved,
    }


def collect(transcript: Path, gitlab_host: str = "") -> dict[str, Any]:
    commands, file_paths, days = _read_transcript(transcript)
    candidates, forges, tags = _scan_commands(commands)
    roots, unresolved = _resolve_roots(candidates | file_paths)
    forge_artefacts = collect_artefacts(transcript, gitlab_host)

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
        # PRs, MRs and issues with how the transcript links them; the tickets a
        # jira script or a time booking named; forge writes whose target could
        # not be identified. collect-review-findings.py reads these.
        **forge_artefacts,
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
    owned = [a for a in scope["artefacts"] if a["origin"] != "mentioned"]
    if owned or scope["tickets"]:
        lines += ["", "PRs, MRs and issues this session created or wrote to:"]
        lines += [f"  {a['origin']:<8} {a['url']}" for a in owned]
        if scope["tickets"]:
            lines.append(f"  tickets  {', '.join(scope['tickets'])}")
    mentioned = len(scope["artefacts"]) - len(owned)
    if mentioned:
        lines.append(
            f"  (+{mentioned} only mentioned — --output-format json lists them)"
        )
    if scope["unresolved_forge_commands"]:
        lines.append(
            f"  {len(scope['unresolved_forge_commands'])} forge writes named no"
            " resolvable target — --output-format json lists them"
        )
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
    parser.add_argument(
        "--gitlab-host",
        default=os.environ.get("GITLAB_HOST", "gitlab.com"),
        help="host for a `glab ... -R group/project` that names no host (default: $GITLAB_HOST)",
    )
    args = parser.parse_args(argv[1:])

    if not args.transcript_file.is_file():
        print(f"no such transcript: {args.transcript_file}", file=sys.stderr)
        return 2

    scope = collect(args.transcript_file, args.gitlab_host)
    if args.output_format == "json":
        print(json.dumps(scope, indent=2))
    else:
        print(render_text(scope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
