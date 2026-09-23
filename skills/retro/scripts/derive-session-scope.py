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
    r"(?:-R|--repo)[\s=]['\"]?(?P<scheme>https?://)?"
    r"(?P<slug>[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)['\"]?"
)
# Artefacts worth naming in the scope line.
ARTEFACT_RE = re.compile(
    r"\b(?:gh|glab)\s+(?:pr|mr|release|issue)\s+(?:create|merge|edit)\b"
    r"|\bgit\s+(?:tag|push)\s+(?:-s\s+)?(?:origin\s+)?(?P<tag>v?\d+\.\d+\.\d+)\b"
)

GITHUB_HOST = "github.com"
# Public forges a `-R` value can name without a scheme; any other dotted
# first segment is a GitLab group (`some.group/sub/proj`).
PUBLIC_FORGE_HOSTS = frozenset(["gitlab.com", "bitbucket.org", "codeberg.org"])

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
    r"(?P<verb>create|edit|update|comment|note|merge|ready|review|close|reopen|approve"
    r"|rebase|delete)\b"
)
API_WRITE_RE = re.compile(
    r"\b(?P<cli>gh|glab)\s+api\b[^\n;|&]*?"
    r"(?:(?:-X|--method)[\s=]*(?:POST|PATCH|PUT|DELETE)\b"
    r"|\s(?:-f|-F|--field|--raw-field|--input)[\s=])"
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
# A REST path about a PR, MR or issue that the literal patterns cannot read —
# a variable (`repos/$R/pulls/29`), a placeholder, a comment id, a create.
PR_ENDPOINT_RE = re.compile(r"/(?:pulls|issues|merge_requests)\b")
HOSTNAME_RE = re.compile(r"--hostname[\s=](?P<host>[\w.-]+)")
# A call the harness refused never ran: its result is the refusal. Bash marks
# it `is_error` without the `Exit code N` a command that ran and failed gets.
DENIED_PREFIX = "PreToolUse:"
EXIT_CODE_RE = re.compile(r"Exit code \d+")
# Output that says a write did not happen, although the exit code (behind a
# pipe or `; echo`) says nothing: an HTTP error (glab: `422 {message: …}`),
# a GraphQL error, a refusal, or a background run whose output is not in the
# result at all (a Bash call sent or moved to the background, a Monitor).
FAILED_OUTPUT_RE = re.compile(
    r"HTTP [45]\d\d|: [45]\d\d \{message|\"status\":\"[45]\d\d\"|\}gh: "
    r"|(?:^|: )GraphQL: "
    r"|^\s*(?:[xX✗]\s|gh: |failed to |Cannot perform)"
    r"|Command running in background|moved to the background|^Monitor started \(",
    re.MULTILINE,
)
# A shell loop runs its body once per item: `for r in a b c; do gh pr create …; done`.
# Matched on the command with heredoc bodies and quoted texts blanked, so a
# `for` or a `done` inside a text neither opens nor closes one. The head's
# alternatives are disjoint (a `$` or `(` is read by exactly one of them), so
# a head full of `$()` cannot backtrack exponentially.
LOOP_RE = re.compile(
    r"\b(?:for|while|until)\b"
    r"(?:\(\([^)]*\)\)|\$\([^)]*\)|\$(?!\()|\((?!\()|[^;\n$(])*(?:;|\n)\s*do\b"
    r"(?P<body>.*?)\bdone\b",
    re.DOTALL,
)
# A REST endpoint held in a variable: `gh api -X POST "$R/123/replies"`.
VARIABLE_ENDPOINT_RE = re.compile(r"\bapi\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+[\"']?\$")
REST_KIND_RE = re.compile(
    r"/(?P<kind>pulls|issues|merge_requests)(?:/(?P<number>\d+))?\b"
)
# A line that reports what a write did: a CLI status line (`✓ …`, `! …`,
# `- Creating issue in …`). A URL alone on its line counts too. A link inside
# a PR body, a JSON answer or an error message stands in running text.
STATUS_LINE_RE = re.compile(r"\s*(?:[✓✔!]\s|-\s+(?:Creating|Updating)\b)")
HTML_URL_LINE_RE = re.compile(r'\s*"(?:html_url|web_url)"\s*:\s*"(?P<url>[^"]+)"')
CLOSED_HEREDOC_RE = re.compile(
    r"<<-?\s*\\?(['\"]?)(?P<tag>[\w-]+)\1[^\n]*\n(?P<body>.*?)\n[ \t]*(?P=tag)[ \t]*(?=\n|$)",
    re.DOTALL,
)
GH_API_CREATE_RE = re.compile(
    r"\brepos/(?P<project>[\w.-]+/[\w.-]+)/(?P<kind>pulls|issues)(?![\w/])"
)
GLAB_API_CREATE_RE = re.compile(
    r"\bprojects/(?P<project>[\w.-]*%2F[\w.%-]+|\d+|\$\{?\w+\}?)/"
    r"(?P<kind>merge_requests|issues)(?![\w/])",
    re.IGNORECASE,
)
BARE_REF_RE = re.compile(r"(?<![\w/&])(?P<sep>[#!])(?P<number>\d+)\b")
# git-workflow's merge wrapper: `pr-merge.sh -R owner/repo N`. It reports every
# write on a line of its own — `pr-merge: o/r#N merged (…)`, `… queued (…)`,
# `pr-merge: posted Self-review attestation for <sha> on o/r#N`; `not merging`,
# `failed` and `dry-run` mean nothing was written.
PR_MERGE_WRAPPER_RE = re.compile(r"\bpr-merge\.sh\b")
PR_MERGE_REPORT_RE = re.compile(
    r"^pr-merge: (?:posted Self-review attestation for \S+ on )?"
    r"(?P<project>[\w.-]+/[\w.-]+)#(?P<number>\d+)(?: merged| queued|$)",
    re.MULTILINE,
)
PR_MERGE_NO_WRITE_RE = re.compile(
    r"^pr-merge: (?:not merging|dry-run|.*#\d+ failed)", re.MULTILINE
)
# A heredoc the same call runs: fed to an interpreter (`python3 - <<'PY'`), or
# written to a file (`cat > x.sh <<'EOF'`) that the call then executes.
# A shell runs every line; another interpreter runs a command only through a
# process call. `bump.sh <<` is a file name, not the interpreter `sh`.
INTERPRETER_HEREDOC_RE = re.compile(
    r"(?<![\w.-])(?:(?P<shell>bash|sh|zsh)|python3?|node|ruby|perl)(?![\w.-])"
    r"[^\n|;&]*(?=<<)"
)
SPAWN_RE = re.compile(
    r"\b(?:subprocess|os\.(?:system|popen|exec\w*)|child_process|execSync"
    r"|spawnSync|Open3|system\s*\(|exec\s*\()"
)
# `! Pull request o/r#5 is already queued`: the write found nothing to do.
ALREADY_RE = re.compile(r"^\s*!\s.*?[#!](?P<number>\d+)\b.*\balready\b", re.MULTILINE)
HEREDOC_FILE_RE = re.compile(
    r"\bcat\s*>>?\s*(?P<file>[^\s>]\S*)[^\n]*<<"
    r"|\bcat\s*<<-?\s*\S+\s*>>?\s*(?P<after>\S+)"
    r"|\btee\s+(?:-a\s+)?(?P<tee>[^\s-]\S*)[^\n]*<<"
    r"|<<[^\n]*\|\s*tee\s+(?:-a\s+)?(?P<pipe>[^\s-]\S*)"
)
# A file that is a program: a script suffix, no suffix, or a `#!` line.
SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".rb", ".pl")
# A shell or an interpreter given its program inline: `bash -lc '…'`,
# `python3 -c '…'`, `node -e '…'`.
INLINE_PROGRAM_RE = re.compile(
    r"(?<![\w.-])(?:(?P<shell>bash|sh|zsh)\s+(?:-\w+\s+)*-[a-z]*c[a-z]*"
    r"|python3?\s+(?:-\w+\s+)*-c"
    r"|(?:node|ruby|perl)\s+(?:-\w+\s+)*-[a-z]*e[a-z]*)\s"
)
# A call in list form, as a script spells it: `subprocess.run(["gh", "pr", …])`.
LIST_CALL_RE = re.compile(r"""\[\s*["'](?:gh|glab)["'][^\]]*\]""")
# MCP tools that write to a PR or issue; their input names owner/repo/number.
MCP_WRITE_RE = re.compile(
    r"github__(?:create_pull_request|update_pull_request|merge_pull_request|"
    r"pull_request_review_write|add_reply_to_pull_request_comment|"
    r"add_comment_to_pending_review|issue_write|add_issue_comment|request_copilot_review"
    r"|sub_issue_write|assign_copilot_to_issue)"
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


def refused(result: str, is_error: bool) -> bool:
    """A call the harness refused, so nothing in it ran."""
    return result.startswith(DENIED_PREFIX) or (
        is_error and not EXIT_CODE_RE.match(result)
    )


def _segment(command: str, write: re.Match) -> str:
    """The write's own simple command: up to the next newline, `;`, `|` or `&`."""
    return re.match(r"[^\n;|&]*", command[write.start() :]).group(0)


def _named_lines(
    result: str, cli: str, host: str, noun: str = ""
) -> list[tuple[dict[str, Any] | None, str, int]]:
    """What the output's report lines name, in order.

    Each entry is (artefact, "", 0) for a URL, `owner/repo#N` or a JSON
    `html_url`, or (None, sep, N) for a bare `#N` / `!N` on a status line."""
    found: list[tuple[dict[str, Any] | None, str, int]] = []
    for line in result.splitlines():
        text = line.strip().strip("`'\"").rstrip(".,")
        html = HTML_URL_LINE_RE.match(line) or _json_url(line)
        if html:
            text = html["url"]
        if text.startswith("https://") and " " not in text:
            found += [(a, "", 0) for a in artefacts_in_text(text)]
            continue
        if not STATUS_LINE_RE.match(line):
            continue
        if line.lstrip().startswith("!") and "already" in line:
            continue  # `! Pull request o/r#5 is already queued`: nothing written
        urls = artefacts_in_text(line)
        found += [(a, "", 0) for a in urls]
        if urls:
            continue
        slugs = list(SLUG_REF_RE.finditer(line))
        found += [
            (
                artefact(
                    host, m["project"], _kind(cli, noun, m["sep"]), int(m["number"])
                ),
                "",
                0,
            )
            for m in slugs
        ]
        if not slugs:
            found += [
                (None, m["sep"], int(m["number"])) for m in BARE_REF_RE.finditer(line)
            ]
    return found


def _repo(slug: str, host: str, scheme: bool = False) -> tuple[str, str] | None:
    """(host, project) of a `-R` value: `o/r`, `group/sub/app`, `github.com/o/r`;
    None for a host this run does not know (`https://x.org/g/p`, `gitlab.com/g/p`)."""
    first, _, rest = slug.partition("/")
    if first in (GITHUB_HOST, host) and "/" in rest:
        return first, rest
    if "/" in rest and (scheme or first in PUBLIC_FORGE_HOSTS):
        return None
    return host, slug


def _json_url(line: str) -> dict[str, str] | None:
    """The `html_url` / `web_url` of a one-line JSON object, as a match-like dict."""
    if not line.lstrip().startswith("{"):
        return None
    try:
        data = json.loads(line)
    except ValueError:
        return None
    url = (
        data.get("html_url") or data.get("web_url") if isinstance(data, dict) else None
    )
    return {"url": url} if isinstance(url, str) else None


def _masked(command: str) -> str:
    """The command with closed heredoc bodies blanked, same length, so a
    quote inside a heredoc text does not open a span over the next command."""
    return CLOSED_HEREDOC_RE.sub(
        lambda m: (
            m.group(0)[: m.start("body") - m.start()]
            + re.sub(r"[^\n]", " ", m["body"])
            + m.group(0)[m.end("body") - m.start() :]
        ),
        command,
    )


def _substitutions(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """The `$(…)` command substitutions in `text[start:end]`, nesting counted."""
    found = []
    i = text.find("$(", start, end)
    while i != -1:
        if (i - len(text[start:i].rstrip("\\")) - start) % 2:
            i = text.find("$(", i + 2, end)
            continue  # `\$(` inside double quotes is literal
        depth, j = 0, i + 1
        while j < end:
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            if depth == 0:
                break
            j += 1
        found.append((i, j + 1))
        i = text.find("$(", j + 1, end)
    return found


def _without_substitutions(text: str) -> str:
    """The text with every `$(…)` body blanked, same length."""
    for sub_start, sub_end in _substitutions(text, 0, len(text)):
        text = (
            text[: sub_start + 2]
            + re.sub(r"[^\n]", " ", text[sub_start + 2 : sub_end - 1])
            + text[sub_end - 1 :]
        )
    return text


def _quoted_spans(command: str) -> list[tuple[int, int]]:
    """Quoted strings with a space in them: text, not a path or a slug. A
    command substitution in double quotes (`"#5: $(gh pr merge …)"`) runs, so
    only the text around it is a span."""
    masked = _masked(command)
    spans = []
    for m in QUOTED_RE.finditer(masked):
        if " " not in m.group(0):
            continue
        start = m.start()
        if m.group(0).startswith('"'):
            for sub_start, sub_end in _substitutions(masked, m.start(), m.end()):
                spans.append((start, sub_start))
                spans += [
                    (q.start(), q.end())
                    for q in QUOTED_RE.finditer(masked, sub_start + 2, sub_end - 1)
                    if " " in q.group(0)
                ]
                start = sub_end - 1
        spans.append((start, m.end()))
    return spans


def _inside(spans: list[tuple[int, int]], index: int) -> bool:
    return any(start < index < end for start, end in spans)


def _in_heredoc(command: str, index: int) -> bool:
    return any(
        m.start("body") <= index < m.end("body")
        for m in CLOSED_HEREDOC_RE.finditer(command)
    )


def _writes(command: str) -> list[re.Match]:
    found = list(FORGE_WRITE_RE.finditer(command))
    blank = _blank_texts(command)
    for m in API_WRITE_RE.finditer(command):
        call = _segment(command, m)
        # A `-X GET` inside a quoted body or a `$(…)` is not this write's method.
        # The segment starts at the write, so a `$(` around the write is not in
        # it; a `$(…)` further along is another command and is blanked.
        if EXPLICIT_GET_RE.search(_without_substitutions(_segment(blank, m))):
            continue
        if "graphql" in call and "mutation" not in command and "query=@" not in call:
            continue  # a GraphQL query (a query read from a file may be a mutation)
        found.append(m)
    return found


def _blank_texts(command: str) -> str:
    """The command with heredoc bodies and quoted texts blanked, same length."""
    masked = _masked(command)
    for start, end in _quoted_spans(command):
        masked = (
            masked[: start + 1]
            + re.sub(r"[^\n]", " ", masked[start + 1 : end - 1])
            + masked[end - 1 :]
        )
    return masked


def _in_loop(command: str, index: int) -> bool:
    return any(
        m.start("body") <= index < m.end("body")
        for m in LOOP_RE.finditer(_blank_texts(command))
    )


def _is_text(command: str, write: re.Match) -> bool:
    """A write that is part of a text: inside a heredoc body or a quoted string."""
    return _in_heredoc(command, write.start()) or _inside(
        _quoted_spans(command), write.start()
    )


class _Call:
    """One tool call: its command, its output, and whether it failed."""

    def __init__(self, command: str, result: str, gitlab_host: str, failed: bool):
        self.command = command
        self.result = result
        self.gitlab_host = gitlab_host
        self.failed = failed or bool(FAILED_OUTPUT_RE.search(result))
        # URLs a create in this call already took: each create takes the next.
        self.claimed: set[str] = set()

    def host(self, cli: str) -> str:
        return GITHUB_HOST if cli == "gh" else self.gitlab_host

    def _claim(self, refs: list[dict[str, Any]], loop: bool) -> list[dict[str, Any]]:
        """The next unclaimed URL for one create; every unclaimed URL of its
        kind for a create that a loop runs once per item."""
        free = [r for r in refs if r["url"] not in self.claimed]
        taken = free if loop else free[:1]
        self.claimed.update(r["url"] for r in taken)
        return taken

    def subcommand_targets(self, write: re.Match) -> list[dict[str, Any]] | None:
        """What `gh|glab pr|mr|issue <verb>` wrote to; None when unknown."""
        cli, noun, verb = write["cli"], write["noun"], write["verb"]
        segment = _segment(self.command, write)
        slug = FORGE_RE.search(segment)
        number = re.match(r"\s+(\d+)\b", self.command[write.end() :])
        repo = (
            _repo(slug["slug"], self.host(cli), bool(slug["scheme"]))
            if slug
            else (self.host(cli), "")
        )
        if repo is None:
            return None
        host, project = repo
        wanted = _kind(cli, noun, "")
        found = []
        same_number = False  # the output names this write's number at all
        for ref, sep, bare in _named_lines(self.result, cli, host, noun):
            if ref is None:
                if not slug:
                    continue  # `#N` needs the repository from this write's `-R`
                ref = artefact(host, project, _kind(cli, noun, sep), bare)
            if number and ref["number"] != int(number[1]):
                continue
            same_number = True
            if slug and ref["project"].lower() != project.lower():
                continue
            if verb == "create" and ref["kind"] != wanted:
                continue
            found.append(ref)
        if verb == "create":
            found = self._claim(found, _in_loop(self.command, write.start()))
        else:
            self.claimed.update(r["url"] for r in found)
        if found:
            return _with_origin(found, "created" if verb == "create" else "acted")
        if number and any(
            m["number"] == number[1] for m in ALREADY_RE.finditer(self.result)
        ):
            return []
        # Silent success in the one unambiguous shape: `<verb> N -R repo`, in
        # a call without any heredoc (an unclosed one hides its extent).
        # Never when the output names this number under another repository:
        # then the `-R` was not understood, and a guess would name a wrong one.
        if (
            number
            and slug
            and not same_number
            and not self.failed
            and "<<" not in self.command
            and not _is_text(self.command, write)
        ):
            return [
                dict(artefact(host, project, wanted, int(number[1])), origin="acted")
            ]
        return None

    def _endpoint_target(self, cli: str, segment: str) -> list[dict[str, Any]] | None:
        path = (GH_API_PATH_RE if cli == "gh" else GLAB_API_PATH_RE).search(segment)
        if not path:
            return None
        project = path["project"] if cli == "gh" else unquote_url(path["project"])
        kind = {"pulls": "pull", "issues": "issue"}.get(path["kind"], path["kind"])
        named = HOSTNAME_RE.search(segment)
        host = named["host"] if named and cli == "glab" else self.host(cli)
        return [
            dict(artefact(host, project, kind, int(path["number"])), origin="acted")
        ]

    def _created_by_path(
        self, cli: str, segment: str, loop: bool = False
    ) -> list[dict[str, Any]] | None:
        create = (GH_API_CREATE_RE if cli == "gh" else GLAB_API_CREATE_RE).search(
            segment
        )
        if not create:
            return None
        project = create["project"] if cli == "gh" else unquote_url(create["project"])
        kind = {"pulls": "pull", "issues": "issue", "merge_requests": "merge_request"}[
            create["kind"].lower()
        ]
        # A numeric GitLab project id or a variable names no path; the created
        # URL does.
        any_project = project.isdigit() or project.startswith("$")
        refs = [
            r
            for r, _, _ in _named_lines(self.result, cli, self.host(cli))
            if r
            and r["kind"] == kind
            and (any_project or r["project"].lower() == project.lower())
        ]
        return _with_origin(self._claim(refs, loop), "created")

    def _rest_fallback(self, cli: str, segment: str) -> list[dict[str, Any]] | None:
        """A REST write on a PR/MR/issue path the literal patterns cannot read:
        the output's report lines, of the path's kind and number when it has them."""
        path = REST_KIND_RE.search(segment)
        noun = (
            {"pulls": "pr", "merge_requests": "mr"}.get(path["kind"], "issue")
            if path
            else ""
        )
        refs = [
            r for r, _, _ in _named_lines(self.result, cli, self.host(cli), noun) if r
        ]
        if path and path["number"]:
            refs = [r for r in refs if r["number"] == int(path["number"])]
        return _with_origin(refs, "acted") if refs else None

    def api_targets(self, write: re.Match) -> list[dict[str, Any]] | None:
        """What a REST or GraphQL write wrote to; [] for an endpoint that is
        not a PR, MR or issue; None when unknown."""
        cli, segment = write["cli"], _segment(self.command, write)
        endpoint = self._endpoint_target(cli, segment)
        if endpoint is not None:
            # The endpoint names the target; the output of a merge or a label
            # change is JSON about something else, or nothing.
            if self.failed:
                return None
            # It claims the URL only in its own report form, a JSON line; a
            # URL alone on a line is what a create in the same call prints.
            # With `--jq .html_url` the call prints that URL alone on a line.
            prints_url = bool(
                re.search(r"--jq[\s=]['\"]?\.(?:html_|web_)?url\b", segment)
            )
            reported = [
                a
                for line in self.result.splitlines()
                if (html := HTML_URL_LINE_RE.match(line) or _json_url(line))
                for a in artefacts_in_text(html["url"])
            ] + (artefacts_in_text(self.result) if prints_url else [])
            keys = {_key(r) for r in endpoint}
            self.claimed.update(a["url"] for a in reported if _key(a) in keys)
            return endpoint
        created = self._created_by_path(
            cli, segment, _in_loop(self.command, write.start())
        )
        if created:
            return created
        about_a_pr = PR_ENDPOINT_RE.search(segment) or VARIABLE_ENDPOINT_RE.search(
            segment
        )
        if not about_a_pr and "graphql" not in segment:
            return []  # an endpoint that is not about a PR, MR or issue
        return self._rest_fallback(cli, segment)


def _joined(command: str) -> str:
    """Backslash-newline continuations joined, same length."""
    return command.replace("\\\n", "  ")


def _wrapper_targets(command: str, result: str) -> list[dict[str, Any]] | None:
    """What `pr-merge.sh` merged or commented on, from its own report lines;
    [] when it says it wrote nothing, None when it says neither."""
    blank = _blank_texts(command)
    runs = [
        m
        for m in PR_MERGE_WRAPPER_RE.finditer(blank)
        if "--dry-run" not in _segment(blank, m)
    ]
    if not runs:
        return []
    found = [
        dict(
            artefact(GITHUB_HOST, m["project"], "pull", int(m["number"])),
            origin="acted",
        )
        for m in PR_MERGE_REPORT_RE.finditer(result)
    ]
    if found or PR_MERGE_NO_WRITE_RE.search(result):
        return found
    return None


def _runs_a_program(command: str) -> bool:
    """Whether the call runs a program it carries: a shell given its program
    (a heredoc, `bash -lc '…'`), another interpreter's heredoc or inline
    program with a process call, or a script file the call writes and names
    again later (`bash x.sh`, `./x.sh`, `timeout 60 x.sh`). Such a program can
    write anywhere; the call is unresolved rather than taken as read-only."""
    # A word in a quoted title (`--title "fix: bash completion"`) is text.
    blank = _blank_texts(command)
    for m in INLINE_PROGRAM_RE.finditer(blank):
        arg = QUOTED_RE.match(command, m.end())
        program = arg.group(0) if arg else _segment(command, m)
        if m["shell"] or SPAWN_RE.search(program):
            return True
    for m in INTERPRETER_HEREDOC_RE.finditer(blank):
        body = CLOSED_HEREDOC_RE.match(command, m.end())
        program = body["body"] if body else command[m.end() :]
        if m["shell"] or SPAWN_RE.search(program):
            return True
    for m in HEREDOC_FILE_RE.finditer(command):
        path = (m["file"] or m["after"] or m["tee"] or m["pipe"]).strip("\"'")
        name = path.rsplit("/", 1)[-1]
        body = CLOSED_HEREDOC_RE.search(command, m.start())
        shebang = body is not None and body["body"].lstrip().startswith("#!")
        if not (shebang or "." not in name or name.endswith(SCRIPT_SUFFIXES)):
            continue  # a body or a note (`cat > pr.md`), not a program
        later = command[body.end() :] if body else command[m.end() :]
        if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", later):
            return True
    return False


def _key(ref: dict[str, Any]) -> tuple[str, int]:
    """Repository and number: `o/r#5`, `…/pull/5` and `…/issues/5` are one PR."""
    return ref["project"].lower(), ref["number"]


def _unclaimed(result: str, found: list[dict[str, Any]], text_writes: bool) -> bool:
    """Whether the output names a target no write claimed. With a write inside
    a heredoc or quoted text (a script the call may run), any URL counts, since
    such a script prints what it likes; otherwise only report lines do."""
    claimed = {_key(a) for a in found}
    named = [r for r, _, _ in _named_lines(result, "gh", GITHUB_HOST) if r]
    if text_writes:
        named += artefacts_in_text(result)
    return any(_key(r) not in claimed for r in named)


def _forge_write_artefacts(
    command: str, result: str, gitlab_host: str, failed: bool = False
) -> tuple[list[dict[str, Any]], bool]:
    """What a command's forge writes wrote to, as their output names it.

    Each write is matched with the report lines its output carries: its own
    number and `-R`, a URL alone on a line or a CLI status line — never a
    link standing in running text. A refused call ran nothing. A write whose
    target stays unknown is reported as unresolved, not guessed."""
    if refused(result, failed):
        return [], False
    command = _joined(command)
    call = _Call(command, result, gitlab_host, failed)
    # Numbered writes first, so a create never takes the URL of a PR an edit
    # or a merge in the same call reported.
    writes = sorted(
        _writes(command), key=lambda w: w.groupdict().get("verb") == "create"
    )
    wrapper = _wrapper_targets(command, result)
    found: list[dict[str, Any]] = list(wrapper or [])
    unresolved = wrapper is None
    about_prs = bool(wrapper) or wrapper is None  # a write concerning a PR, MR or issue
    # A call in list form (`["gh", "pr", …]`) only occurs inside a script.
    text_writes = bool(LIST_CALL_RE.search(command))
    about_prs = about_prs or text_writes
    # `pr-merge.sh` written into a heredoc or a quoted text is a write in text.
    if any(_is_text(command, m) for m in PR_MERGE_WRAPPER_RE.finditer(command)):
        about_prs = text_writes = True
    for write in writes:
        if _is_text(command, write):
            # Written into a heredoc or a quoted text: a heredoc may be a
            # script the same call runs, so it is never attributed.
            about_prs = text_writes = True
            continue
        if write.groupdict().get("verb"):
            targets = call.subcommand_targets(write)
        else:
            targets = call.api_targets(write)
        about_prs = about_prs or targets != []
        if targets is None:
            unresolved = True
        else:
            found += targets
    # Every gh/glab/api/MCP/pr-merge.sh write lands in one of three places —
    # attributed, unresolved, or refused. A target the output names that no
    # write claimed means some write was not understood: the call is unresolved.
    # A script the call runs can write anywhere and print nothing about it;
    # its writes are never attributed, so the call is unresolved.
    if text_writes and _runs_a_program(command):
        unresolved = True
    if about_prs and not unresolved:
        unresolved = _unclaimed(result, found, text_writes)
    return found, unresolved


def jira_command_tickets(command: str, result: str, is_error: bool = False) -> set[str]:
    """The ticket a jira script was run against, when its output names it.

    The key is the script's first positional argument. A script name inside a
    quoted text (`git commit -m "… jira-issue.py get NRS-9 …"`) or a heredoc
    is not a call; a quoted path without spaces (`"$HOME/…/jira-issue.py"`) is."""
    if refused(result, is_error):
        return set()
    command = _joined(command)
    found = set()
    for m in JIRA_COMMAND_RE.finditer(command):
        if _is_text(command, m):
            continue
        key = next((t for t in _tokens(m["rest"]) if TICKET_RE.fullmatch(t)), None)
        if key and key.split("-", 1)[0] not in NOT_A_TICKET_PREFIX and key in result:
            found.add(key)
    return found


def _mcp_write_artefacts(
    payload: dict[str, Any], result: str, is_error: bool = False
) -> list[dict[str, Any]]:
    """The PR/issue an MCP GitHub write addressed.

    The input's owner/repo/number is the identity when present; a create names
    its result by the `html_url` field. A URL echoed from a body is neither.
    A call the harness refused, or one that failed, wrote nothing."""
    if is_error:
        return []
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
            self.tickets |= jira_command_tickets(
                command, result, bool(block.get("is_error"))
            )
        elif MCP_WRITE_RE.search(name):
            self.keep(
                _mcp_write_artefacts(payload, result, bool(block.get("is_error")))
            )
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
        # not be identified. collect-review-findings.py reads the artefacts and
        # tickets, and lists the unresolved writes as UNRESOLVED.
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
