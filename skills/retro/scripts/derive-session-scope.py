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
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote as unquote_url

# `git -C <path>`, `cd <path>`, `-R owner/repo`, `--repo owner/repo`.
GIT_C_RE = re.compile(r"git\s+-C\s+(?P<path>(?:\"[^\"]+\"|'[^']+'|[^\s;|&]+))")
CD_RE = re.compile(
    r"(?:^|[;&|]\s*|\&\&\s*)cd\s+(?P<path>(?:\"[^\"]+\"|'[^']+'|[^\s;|&]+))"
)
FORGE_RE = re.compile(
    r"(?:-R|--repo)[\s=]['\"]?(?P<slug>[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)['\"]?"
)
# Artefacts worth naming in the scope line.
ARTEFACT_RE = re.compile(
    r"\b(?:gh|glab)\s+(?:pr|mr|release|issue)\s+(?:create|merge|edit)\b"
    r"|\bgit\s+(?:tag|push)\s+(?:-s\s+)?(?:origin\s+)?(?P<tag>v?\d+\.\d+\.\d+)\b"
)

GITHUB_HOST = "github.com"

# Pull requests, merge requests and issues, by URL. A GitLab project path may
# be nested (`group/sub/project`), and the `/-/` separator is what marks it.
# GitLab prints a new issue as a work item (`/-/work_items/N`); its issue API
# answers for the same number.
GITHUB_URL_RE = re.compile(
    r"https://github\.com/(?P<project>[\w.-]+/[\w.-]+)/(?P<kind>pull|issues)/(?P<number>\d+)"
)
GITLAB_URL_RE = re.compile(
    r"https://(?P<host>(?!github\.com)[\w.-]+\.[a-z]{2,})/"
    r"(?P<project>[\w.-]+(?:/[\w.-]+)+)/-/(?P<kind>merge_requests|issues|work_items)/"
    r"(?P<number>\d+)"
)
# A command that may write to a PR/MR/issue: a gh/glab subcommand, or a REST
# call through `gh api` / `glab api` with a write method or body fields. The
# command only says a write may have happened; what it wrote to is read from
# its output (see `_forge_write_artefacts`).
FORGE_WRITE_RE = re.compile(
    r"\b(?P<cli>gh|glab)\s+(?P<noun>pr|mr|issue)\s+"
    r"(?P<verb>create|edit|update|comment|note|merge|ready|review|close|reopen|approve)\b"
)
API_WRITE_RE = re.compile(
    r"\b(?P<cli>gh|glab)\s+api\b[^\n;|&]*?"
    r"(?:(?:-X|--method)[\s=]*(?:POST|PATCH|PUT)\b|\s(?:-f|-F|--field|--raw-field|--input)[\s=])"
)
# How a CLI names its target when it prints no URL: `owner/repo#12` (gh),
# `group/project!12` (a glab MR), or a bare `#12` / `!12`.
SLUG_REF_RE = re.compile(
    r"(?<![\w/.-])(?P<project>[\w.-]+(?:/[\w.-]+)+)(?P<sep>[#!])(?P<number>\d+)\b"
)
# gh and glab send a request with fields as POST unless told otherwise; an
# explicit GET, and a GraphQL call that is not a mutation, only read.
EXPLICIT_GET_RE = re.compile(r"(?:-X|--method)[\s=]*GET\b")
# The endpoint of a REST write names its target on its own: repository and
# number are in the path, not in any text the call carries.
GH_API_PATH_RE = re.compile(
    r"\brepos/(?P<project>[\w.-]+/[\w.-]+)/(?P<kind>pulls|issues)/(?P<number>\d+)\b"
)
GLAB_API_PATH_RE = re.compile(
    r"\bprojects/(?P<project>[\w.-]*%2F[\w.%-]+)/(?P<kind>merge_requests|issues)/"
    r"(?P<number>\d+)\b",
    re.IGNORECASE,
)
HOSTNAME_RE = re.compile(r"--hostname[\s=](?P<host>[\w.-]+)")
# A call the harness refused never ran: its result is the refusal.
DENIED_PREFIX = "PreToolUse:"
BARE_REF_RE = re.compile(r"(?<![\w/&])(?P<sep>[#!])(?P<number>\d+)\b")
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
JIRA_COMMAND_RE = re.compile(r"\bjira-[a-z-]+\.py\b(?P<rest>[^;&|\n]*)")
QUOTED_RE = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")


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
    kind = {
        "pull": "pull",
        "issues": "issue",
        "work_items": "issue",
        "merge_requests": "merge_request",
    }.get(kind, kind)
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


def _tokens(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:  # an unbalanced quote: fall back to plain words
        return text.split()


def _kind(cli: str, noun: str, sep: str) -> str:
    if cli == "glab":
        return "merge_request" if sep == "!" or noun == "mr" else "issue"
    # gh says `owner/repo#12` for both; the subcommand tells them apart. A REST
    # call on `issues/N` may address a PR — the collector reads it as one then.
    return "pull" if noun == "pr" else "issue"


def refs_in_result(
    result: str, write: re.Match, command: str, gitlab_host: str
) -> list[dict[str, Any]]:
    """The PRs/MRs/issues a write's output names.

    A URL first; then `owner/repo#N`; then a bare `#N`, whose repository comes
    from the command's `-R`/`--repo` — only when there is exactly one."""
    found = artefacts_in_text(result)
    if found:
        return found
    cli, noun = write["cli"], write.groupdict().get("noun") or "api"
    host = GITHUB_HOST if cli == "gh" else gitlab_host
    found = [
        artefact(host, m["project"], _kind(cli, noun, m["sep"]), int(m["number"]))
        for m in SLUG_REF_RE.finditer(result)
    ]
    if found:
        return found
    slugs = {m["slug"] for m in FORGE_RE.finditer(command)}
    if len(slugs) != 1:
        return []
    (slug,) = slugs
    return [
        artefact(host, slug, _kind(cli, noun, m["sep"]), int(m["number"]))
        for m in BARE_REF_RE.finditer(result)
    ]


def _quoted_spans(command: str) -> list[tuple[int, int]]:
    """Quoted strings with a space in them: text, not a path or a slug. A
    command substitution in double quotes (`URL="$(gh pr create …)"`) runs."""
    return [
        (m.start(), m.end())
        for m in QUOTED_RE.finditer(command)
        if " " in m.group(0) and not m.group(0).startswith('"$(')
    ]


def _inside(spans: list[tuple[int, int]], index: int) -> bool:
    return any(start < index < end for start, end in spans)


def _writes(command: str) -> list[re.Match]:
    spans = _quoted_spans(command)
    found = [
        m for m in FORGE_WRITE_RE.finditer(command) if not _inside(spans, m.start())
    ]
    for m in API_WRITE_RE.finditer(command):
        call = m.group(0)
        if _inside(spans, m.start()) or EXPLICIT_GET_RE.search(call):
            continue
        if "graphql" in call and "mutation" not in command:
            continue  # a GraphQL query
        found.append(m)
    return found


def _api_path_targets(
    command: str, writes: list[re.Match], gitlab_host: str
) -> list[dict[str, Any]]:
    """PRs/MRs/issues named by the endpoint of a REST write (`repos/o/r/pulls/41`).

    A numeric GitLab project id (`projects/3424/…`) names no path to build a
    URL from, so it stays unresolved."""
    found = []
    for write in writes:
        if write.groupdict().get("verb"):
            continue
        segment = re.match(r"[^\n;|&]*", command[write.start() :]).group(0)
        if write["cli"] == "gh":
            for m in GH_API_PATH_RE.finditer(segment):
                kind = "pull" if m["kind"] == "pulls" else "issue"
                found.append(
                    artefact(GITHUB_HOST, m["project"], kind, int(m["number"]))
                )
        else:
            named = HOSTNAME_RE.search(segment)
            host = named["host"] if named else gitlab_host
            for m in GLAB_API_PATH_RE.finditer(segment):
                project = unquote_url(m["project"])
                found.append(artefact(host, project, m["kind"], int(m["number"])))
    return found


def _silent_target(
    command: str, writes: list[re.Match], gitlab_host: str
) -> list[dict[str, Any]]:
    """What a successful write names when it prints nothing.

    Two narrow shapes count, and only in a call with no heredoc: a REST
    endpoint that carries repository and number, and one subcommand write with
    its number right after the verb and one `-R` (`gh pr merge 53 -R o/r`)."""
    if "<<" in command:
        return []
    found = _api_path_targets(command, writes, gitlab_host)
    subcommands = [w for w in writes if w.groupdict().get("verb")]
    slugs = {m["slug"] for m in FORGE_RE.finditer(command)}
    if len(subcommands) == 1 and len(slugs) == 1:
        write = subcommands[0]
        number = re.match(r"\s+(\d+)\b", command[write.end() :])
        if number:
            (slug,) = slugs
            host = GITHUB_HOST if write["cli"] == "gh" else gitlab_host
            kind = _kind(write["cli"], write["noun"], "")
            found.append(artefact(host, slug, kind, int(number[1])))
    return _with_origin(found, "acted")


def _forge_write_artefacts(
    command: str, result: str, gitlab_host: str, failed: bool = False
) -> tuple[list[dict[str, Any]], bool]:
    """What a command's forge writes wrote to, as its output names it.

    The output decides, not the command text: a `gh pr merge 3` inside a
    heredoc or a quoted body prints no target, and a refused call ran nothing.
    A successful write that prints nothing counts only in the narrow shape of
    `_silent_target`. Anything else is reported as unresolved."""
    if result.startswith(DENIED_PREFIX):
        return [], False
    writes = _writes(command)
    if not writes:
        return [], False
    refs = refs_in_result(result, writes[0], command, gitlab_host)
    if not refs:
        silent = [] if failed else _silent_target(command, writes, gitlab_host)
        return silent, not silent
    if not any(w.groupdict().get("verb") == "create" for w in writes):
        return _with_origin(refs, "acted"), False
    # A create names what it made; with `-R` on the create itself, that is a
    # URL in that repository. Any other URL the call printed was written to
    # when the call holds another write, and only mentioned when it does not.
    other = (
        "acted"
        if any(w.groupdict().get("verb") != "create" for w in writes)
        else "mentioned"
    )
    slugs = {
        m["slug"].lower()
        for w in writes
        if w.groupdict().get("verb") == "create"
        for m in FORGE_RE.finditer(
            re.match(r"[^\n;|&]*", command[w.start() :]).group(0)
        )
    }
    return [
        dict(
            r,
            origin="created" if not slugs or r["project"].lower() in slugs else other,
        )
        for r in refs
    ], False


def jira_command_tickets(command: str, result: str) -> set[str]:
    """The ticket a jira script was run against, when its output names it.

    The key is the script's first positional argument. A script name inside a
    quoted text (`git commit -m "… jira-issue.py get NRS-9 …"`) is not a call;
    a quoted path without spaces (`"$HOME/…/jira-issue.py"`) is."""
    if result.startswith(DENIED_PREFIX):
        return set()
    quoted = _quoted_spans(command)
    found = set()
    for m in JIRA_COMMAND_RE.finditer(command):
        if _inside(quoted, m.start()):
            continue
        key = next((t for t in _tokens(m["rest"]) if TICKET_RE.fullmatch(t)), None)
        if key and key.split("-", 1)[0] not in NOT_A_TICKET_PREFIX and key in result:
            found.add(key)
    return found


def _mcp_write_artefacts(payload: dict[str, Any], result: str) -> list[dict[str, Any]]:
    """The PR/issue an MCP GitHub write addressed.

    The input's owner/repo/number is the identity when present; a create names
    its result by the `html_url` field. A URL echoed from a body is neither."""
    owner, repo = payload.get("owner"), payload.get("repo")
    number = payload.get("pullNumber") or payload.get("issue_number")
    if isinstance(owner, str) and isinstance(repo, str) and str(number or "").isdigit():
        is_issue = (
            "issue" in str(payload.get("method", "")) or "issue_number" in payload
        )
        kind = "issue" if is_issue else "pull"
        return [
            dict(
                artefact(GITHUB_HOST, f"{owner}/{repo}", kind, int(number)),
                origin="acted",
            )
        ]
    try:
        data = json.loads(result)
    except ValueError:
        data = None
    link = data.get("html_url") or data.get("url") if isinstance(data, dict) else None
    named = (
        artefacts_in_text(link) if isinstance(link, str) else artefacts_in_text(result)
    )
    return _with_origin(named[:1], "created")


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
            found, lost = _forge_write_artefacts(
                command, result, self.gitlab_host, bool(block.get("is_error"))
            )
            self.keep(found)
            if lost:
                self.unresolved.append(command[:200])
            self.tickets |= jira_command_tickets(command, result)
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
