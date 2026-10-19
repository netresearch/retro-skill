#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.10"
# dependencies = ["tree-sitter==0.26.0", "tree-sitter-bash==0.25.1"]
# ///
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

A subagent keeps its own transcript, `<session id>/subagents/agent-*.jsonl`
beside `<session id>.jsonl` (a Workflow's agents in `subagents/workflows/wf_*/`).
When `--transcript-file` is named by its session UUID, every one below that
directory is read with it; `transcripts` in the output lists the files read,
the main transcript first. collect-review-findings.py reads the same set.

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
import functools
import importlib.util
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote as unquote_url


def _load_masking():
    """mask-secrets.py, loaded by path: its name is hyphenated like ours."""
    path = Path(__file__).resolve().parent / "mask-secrets.py"
    spec = importlib.util.spec_from_file_location("mask_secrets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_masking = _load_masking()
mask, squeeze = _masking.mask, _masking.squeeze

try:
    import tree_sitter_bash
    from tree_sitter import Language, Parser
except ImportError:  # pragma: no cover - depends on how the script is started
    sys.exit(
        "derive-session-scope.py reads shell commands with tree-sitter-bash, which "
        "is not installed here. Run it with `uv run <path>/derive-session-scope.py` "
        "(the dependencies are declared in the script header)."
    )

BASH = Parser(Language(tree_sitter_bash.language()))

# `-R owner/repo`, `--repo owner/repo`. The directories a command works in
# (`git -C <path>`, `cd <path>`) and the release tags it names are read from
# the parse tree, in `_command_scope`.
FORGE_RE = re.compile(
    r"(?:-R|--repo)[\s=]['\"]?(?P<scheme>https?://)?"
    r"(?P<slug>[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)['\"]?"
)
# A release tag, as a whole argument of `git tag` or `git push`.
RELEASE_TAG_RE = re.compile(r"v?\d+\.\d+\.\d+")
# Commands that run the command after their own options: `sudo git -C …`.
COMMAND_WRAPPERS = frozenset(
    {"sudo", "env", "command", "exec", "nice", "nohup", "timeout", "time"}
)
# Options of git itself that take the next word as their value.
GIT_VALUE_OPTIONS = frozenset({"-c", "--git-dir", "--work-tree", "--namespace"})
# Options of `git tag` / `git push` that take the next word as their value:
# `-m 1.2.3` is a message, not a tag.
TAG_VALUE_OPTIONS = frozenset(
    {"-m", "-F", "-u", "--message", "--file", "--local-user", "--cleanup"}
)
PUSH_VALUE_OPTIONS = frozenset(
    {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
)
# A `git tag` or `git push` with one of these deletes, lists or checks a tag.
NOT_A_RELEASE = frozenset({"-d", "--delete", "-l", "--list", "-v", "--verify"})
# A shell given its program as a string: `bash -lc 'cd /r && git status'`.
SHELLS = frozenset({"bash", "sh", "zsh"})

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
# gh writes whose own report is a status line (`✓ Pull request o/r#5 is
# marked as "ready for review"`, `✓ Merged pull request #5 (…)`), never a URL
# alone on a line, which is what `gh pr create` prints. Measured over the 130
# successful single-write calls of these verbs in session e72080f1
# (2026-10-18): none printed a URL alone on a line. `review` is left out:
# `--comment` and `--request-changes` report with `-`/`+`, not a status line.
STATUS_REPORT_VERBS = frozenset({"ready", "merge"})
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
# `-f query='query{…}'`: the GraphQL document itself, not a variable holding it.
LITERAL_QUERY_RE = re.compile(r"\bquery=(?:'|\"(?!\$))")
# A GraphQL document from a file or a command: it may be a mutation.
QUERY_ELSEWHERE_RE = re.compile(r"query=(?:@|\"?\$\(|\"?`)|(?:^|\s)--input[\s=]")
# `query="$Q"`: a document in a variable, read where the call assigns it.
QUERY_VARIABLE_RE = re.compile(
    r"(?:(?<![\w-])|(?<=-[fF]))query=\"?\$\{?(?P<name>[A-Za-z_]\w*|[0-9]+|[@*])"
)
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
# `… && echo ok || echo failed`: the call names its own failure message.
# Read from the write onward: quoted arguments (whole, so a `;` in a body
# does not end the write) and redirections (`>/dev/null 2>&1`) may stand
# between the write and its `&&`, another command may not.
ECHO_BRANCHES_RE = re.compile(
    r"(?:\"[^\"\n]*\"|'[^'\n]*'|[^\n;|&\"']|&(?!&))*&&\s*echo(?:\s+-[neE]+)*\s+"
    r"(?P<ok>\"[^\"\n]*\"|'[^'\n]*'|(?:>&|[^;|&\n])+?)"
    r"\s*\|\|\s*\{?\s*echo(?:\s+-[neE]+)*\s+"
    r"(?P<fail>\"[^\"\n]*\"|'[^'\n]*'|(?:>&|[^;|&\n}])+)"
)
# A message's own redirection (`echo failed >&2`) is not part of its text.
ECHO_REDIRECT_RE = re.compile(r"\s*\d*>&?\s*\S+$")
REPORTED_FAILURE_RE = re.compile(
    r"HTTP [45]\d\d|: [45]\d\d \{message|\"status\":\"[45]\d\d\"|\}gh: "
    r"|(?:^|: )GraphQL: "
    r"|^\s*(?:[xX✗]\s|gh: |failed to |Cannot perform)",
    re.MULTILINE,
)
BACKGROUND_RE = re.compile(
    r"Command running in background|moved to the background|^Monitor started \(",
    re.MULTILINE,
)
FAILED_OUTPUT_RE = re.compile(
    f"{REPORTED_FAILURE_RE.pattern}|{BACKGROUND_RE.pattern}", re.MULTILINE
)


# An MCP tool that fails often returns its error as ordinary text with
# is_error unset: "Error: 404 not found", "Issue does not exist".
TOOL_ERROR_TEXT_RE = re.compile(
    r"^\s*(?:error|failed|failure|denied|forbidden|unauthori[sz]ed)\b"
    r"|\b(?:not found|does not exist|permission denied)\b",
    re.IGNORECASE | re.MULTILINE,
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
# The wrapper's own report that it wrote nothing to one PR.
PR_MERGE_SHUT_RE = re.compile(
    r"^pr-merge: (?:not merging (?P<target>[\w.-]+/[\w.-]+#\d+)\b"
    r"|(?P<failed>[\w.-]+/[\w.-]+#\d+) failed)",
    re.MULTILINE,
)
PR_MERGE_NO_WRITE_RE = re.compile(
    r"^pr-merge: (?:not merging|dry-run|.*#\d+ failed)", re.MULTILINE
)
# Programs that read a file they are given and never run it: `grep … pr-merge.sh`
# names the wrapper without running it. Any other mention may be a run.
FILE_READERS = frozenset(
    [
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "ugrep",
        "ag",
        "head",
        "tail",
        "cat",
        "bat",
        "less",
        "more",
        "sed",
        "awk",
        "gawk",
        "wc",
        "ls",
        "stat",
        "file",
        "diff",
        "cmp",
        "sha256sum",
        "sha1sum",
        "md5sum",
        "shellcheck",
        "git",
    ]
)
# `pr-merge.sh` flags with which it writes nothing.
NO_WRITE_FLAGS = frozenset({"--dry-run", "--help", "-h", "--version"})
# The duration `timeout` takes before the command it runs: `timeout 600 x`.
DURATION_RE = re.compile(r"\d+(?:\.\d+)?[smhd]?")
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
# A GraphQL write on a review thread names the thread by its node id only
# (`resolveReviewThread(input:{threadId:"PRRT_…"})`); the pull request it
# belongs to is in no text the call carries. The ids are kept so the collector
# can ask the forge — never matched to a PR by what else the session touched.
# A review comment edited by its node id (`PRRC_…`) is the same
# case: the forge names its pull request.
REVIEW_THREAD_MUTATION_RE = re.compile(
    r"\b(?:resolveReviewThread|unresolveReviewThread|addPullRequestReviewThreadReply"
    r"|updatePullRequestReviewComment)\b"
)
REVIEW_THREAD_ID_RE = re.compile(r"(?<![\w-])PRR[TC]_[A-Za-z0-9_-]+")
# A thread id where a thread mutation takes it, given literally.
THREAD_ID_LITERAL_RE = re.compile(
    r"\b(?:pullRequestReviewThreadId|threadId)\s*:\s*\\?\"(PRRT_[A-Za-z0-9_-]+)"
)
# `-f id=PRRT_…`: a GraphQL variable given a literal id.
GQL_FIELD_ID_RE = re.compile(
    r"(?:^|\s)(?:-f|-F|--field|--raw-field)[\s=]['\"]?(\w+)=['\"]?(PRR[TC]_[A-Za-z0-9_-]+)"
)
# The id an `updatePullRequestReviewComment` edits, given literally.
COMMENT_ID_ARGUMENT_RE = re.compile(
    r"\bpullRequestReviewCommentId\s*:\s*\\?\"(PRRC_[A-Za-z0-9_-]+)"
)
# A REST edit of one comment names the comment, not the PR or issue it is
# on (`repos/o/r/issues/comments/5917853122`); GitHub names that PR or issue
# when the collector asks it for the comment. A deleted one it cannot name.
COMMENT_ENDPOINT_RE = re.compile(
    r"\brepos/[\w.-]+/[\w.-]+/(?:issues|pulls)/comments/\d+(?![\w/])"
)
# `for t in PRRT_a PRRT_b; do gh api graphql … $t …`: the list a loop variable
# takes its values from.
FOR_LIST_RE = re.compile(r"\bfor\s+(?P<var>\w+)\s+in\s+(?P<list>[^;\n]*)")
# A call in list form, as a script spells it: `subprocess.run(["gh", "pr", …])`.
LIST_CALL_RE = re.compile(r"""\[\s*["'](?:gh|glab)["'][^\]]*\]""")
# MCP tools that write to a PR or issue; their input names owner/repo/number.
MCP_WRITE_RE = re.compile(
    r"github__(?:create_pull_request|update_pull_request|merge_pull_request|"
    r"pull_request_review_write|add_reply_to_pull_request_comment|"
    r"add_comment_to_pending_review|issue_write|add_issue_comment|request_copilot_review"
    r"|sub_issue_write|assign_copilot_to_issue)"
)
# Key-shaped arguments are only reference candidates, never tracker identities.
# Exclude common standards to reduce noise, not to infer a provider by exclusion.
# The set includes jira-integration's NON_JIRA_KEY_PREFIXES (3.34.0): SPDX
# licence ids with a version (`GPL-3` from `GPL-3.0-or-later`), MD5 and the
# documentation placeholders PROJ-/EXAMPLE-. BSD stays: it is a real project key.
TICKET_RE = re.compile(r"\b(?P<key>[A-Z][A-Z0-9]{1,9}-\d+)\b")
NOT_A_TICKET_PREFIX = frozenset(
    {
        "MD5",
        "PROJ",
        "EXAMPLE",
        "GPL",
        "AGPL",
        "LGPL",
        "MPL",
        "EPL",
        "EUPL",
        "CDDL",
        "BSL",
        "BUSL",
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

    A path with no work tree still names a repository in that layout: the
    bare repository itself (`<project>/.bare`), the project directory beside
    it, and a worktree removed after its branch merged — whose files the
    transcript still names while the directory is gone. Each resolves to the
    bare repository, where `git worktree list` answers for all of them;
    otherwise a session that ends with a clean merge sweeps nothing. The
    `.bare` is looked for in every directory above the path, not only the
    nearest one that still exists: a worktree of a branch with a slash
    (`fix/x`) lives in `<project>/fix/x`, and removing it leaves the empty
    `fix/` behind. The `.bare` is asked first: a project directory that sits
    inside another work tree would otherwise answer with that outer one; only
    a work tree below the project directory — a live worktree — answers.
    """
    probe = path if path.is_dir() else path.parent
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir():
        return None
    top = _git_path(probe, "--show-toplevel")
    project = _bare_project(probe)
    if project is not None:
        if top is not None and project.resolve() in top.resolve().parents:
            return top
        return (project / ".bare").resolve()
    if top is not None:
        return top
    if _git_path(probe, "--is-bare-repository") == Path("true"):
        return _git_path(probe, "--path-format=absolute", "--git-dir")
    return None


def _bare_project(directory: Path) -> Path | None:
    """The nearest directory at or above `directory` that holds a bare
    repository named `.bare`, or None."""
    for candidate in (directory, *directory.parents):
        bare = candidate / ".bare"
        if bare.is_dir() and _git_path(bare, "--is-bare-repository") == Path("true"):
            return candidate
    return None


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


def _git_path(directory: Path, *query: str) -> Path | None:
    """One `git rev-parse` answer for a directory, or None."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARS}
    try:
        out = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", *query],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # a non-repository path is an ordinary answer here
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    answer = out.stdout.strip()
    return Path(answer) if out.returncode == 0 and answer else None


def iter_events(path: Path):
    # `.resolve()` before opening: the path arrives as a CLI argument an agent
    # composed, and canonicalising it collapses any `..` segment rather than
    # following it. The file itself is deliberately unbounded - the opencode
    # adapter writes its transcript to stdout, so a legitimate one lives
    # wherever the operator redirected it.
    with path.resolve().open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # A line that is valid JSON but not an object (`[1, 2]`, `null`)
            # is no event; every reader below calls `.get` on one.
            if isinstance(event, dict):
                yield event


def _message(event: dict[str, Any]) -> dict[str, Any]:
    """The event's message, or {} when it is missing, null or not an object."""
    message = event.get("message")
    return message if isinstance(message, dict) else {}


def _tool_inputs(event: dict[str, Any]):
    """Every tool_use input in one transcript event."""
    content = _message(event).get("content")
    for block in content if isinstance(content, list) else []:
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


def _read_transcript(
    transcript: Path,
) -> tuple[list[tuple[str, str | None]], set[str], set[str]]:
    """The Bash commands with the directory each ran in, the absolute file
    paths, and the days.

    Claude Code stamps every event with the session's working directory at
    that moment (`cwd`), and it follows the `cd`s of earlier calls. A command
    from a transcript without it — an opencode rendering, an old or hand-made
    one — has no directory, and its relative paths stay unresolved."""
    commands: list[tuple[str, str | None]] = []
    file_paths: set[str] = set()
    days: set[str] = set()
    for event in iter_events(transcript):
        day = _day_of(event)
        if day:
            days.add(day)
        cwd = event.get("cwd")
        cwd = cwd if isinstance(cwd, str) and cwd.startswith("/") else None
        for payload in _tool_inputs(event):
            command = payload.get("command")
            if isinstance(command, str):
                commands.append((command, cwd))
            file_paths |= _absolute_paths(payload)
    return commands, file_paths, days


def _word(shell: _Shell, node) -> str:
    """A command word as written, without its surrounding quotes."""
    return unquote(
        shell.source[shell._char[node.start_byte] : shell._char[node.end_byte]]
    )


def _within(base: str | None, raw: str) -> str:
    """`raw` as an absolute path when it can be one without guessing: as
    written when absolute, joined to `base` when relative and `base` is known.
    Otherwise `raw` itself, which `_resolve_roots` lists as unresolved."""
    if "$" in raw or "`" in raw or raw.startswith("~"):
        return raw
    if raw.startswith("/"):
        return os.path.normpath(raw)
    return os.path.normpath(os.path.join(base, raw)) if base else raw


def _release_tags(args: list[str], value_options: frozenset[str]) -> set[str]:
    """The release tags among a `git tag` / `git push` command's arguments."""
    if NOT_A_RELEASE.intersection(args):
        return set()
    tags, skip = set(), False
    for arg in args:
        if skip:
            skip = False
        elif arg in value_options:
            skip = True
        elif RELEASE_TAG_RE.fullmatch(arg):
            tags.add(arg)
    return tags


def _git_scope(words: list[str], base: str | None) -> tuple[list[str], set[str]]:
    """The `-C` directories and release tags of one git command's words
    (`words[0]` is git). Each `-C` is relative to the one before it."""
    paths: list[str] = []
    index = 1
    while index < len(words) and words[index].startswith("-"):
        option = words[index]
        if option == "-C" and index + 1 < len(words):
            target = _within(base, words[index + 1])
            paths.append(target)
            base = target if target.startswith("/") else None
            index += 2
        elif option in GIT_VALUE_OPTIONS:
            index += 2
        else:
            index += 1
    if index >= len(words):
        return paths, set()
    subcommand, args = words[index], words[index + 1 :]
    if subcommand == "tag":
        return paths, _release_tags(args, TAG_VALUE_OPTIONS)
    if subcommand == "push":
        return paths, _release_tags(args, PUSH_VALUE_OPTIONS)
    return paths, set()


def _command_scope(command: str, cwd: str | None) -> tuple[list[str], set[str]]:
    """The directories one Bash command worked in and the release tags it named.

    Read from the parse tree, so a `cd` on the second line counts as much as
    one after `&&`, and a quoted message is not a command. A relative path is
    joined to the directory the command started in (`cwd`) or, after a `cd`
    earlier in the same command, to that `cd`'s target; with neither known it
    is returned as written and stays unresolved — never joined to the
    directory this script runs in. The commands are followed in the order
    they are written; a `cd` inside `( … )` or `$( … )` is taken as if it
    changed the directory for the rest, since which of them ran is not in the
    transcript. A shell given its program as a string (`bash -c '…'`) is
    read the same way.

    Any other text — a quoted string, a heredoc body — may still be a
    command that runs: `G="git -C /p/.bare"; $G fetch`, a script written by
    `cat > x.sh <<EOF` and run after, `tmux-run.py "cd /p && make"`. Its
    absolute paths are candidates too; its relative paths and tags are not,
    since neither its directory nor whether it ran is known. That recall
    costs some noise from quoted examples and remote `ssh host 'cd /srv/x'`
    paths, which land in `unresolved_paths` when nothing local is there."""
    return _shell_scope(_shell(command), cwd, 0)


def _simple_commands(shell: _Shell, node) -> list[list[Any]]:
    """The word nodes of one `command` node, a list per simple command. The
    grammar glues the lines after `a | b || c` into one command node (see
    `_Shell.misparsed`); a newline between two words starts the next one."""
    nodes = [node.child_by_field_name("name")]
    nodes += node.children_by_field_name("argument")
    groups: list[list[Any]] = []
    for word in (n for n in nodes if n is not None):
        gap = shell._data[groups[-1][-1].end_byte : word.start_byte] if groups else b""
        if not groups or (b"\n" in gap and b"\\\n" not in gap):
            groups.append([word])
        else:
            groups[-1].append(word)
    return groups


# How deep text inside text is read again as a command.
MAX_TEXT_DEPTH = 3
TEXT_SCOPE_NODES = frozenset(["string", "raw_string", "heredoc_body"])
MAY_NAME_A_DIRECTORY_RE = re.compile(r"\b(?:git|cd|pushd)\b")


def _text_scope(shell: _Shell, node, depth: int) -> list[str]:
    """The absolute paths of a text node read again as a command, when it is
    not too deep and may name a directory."""
    text = _word(shell, node)
    if depth >= MAX_TEXT_DEPTH or not MAY_NAME_A_DIRECTORY_RE.search(text):
        return []
    found, _tags = _shell_scope(_Shell(text), None, depth + 1)
    return [p for p in found if p.startswith("/")]


def _unwrapped(
    group: list[Any], words: list[str]
) -> tuple[list[Any], list[str], str] | None:
    """(word nodes, words, head) of one simple command with a leading wrapper
    peeled off: `sudo -u me git …` starts at git or cd. None when a wrapper
    wraps neither."""
    head = os.path.basename(words[0])
    if head not in COMMAND_WRAPPERS:
        return group, words, head
    starts = [i for i, w in enumerate(words) if w in ("git", "cd")]
    if not starts:
        return None
    return group[starts[0] :], words[starts[0] :], words[starts[0]]


def _cd_step(words: list[str], base: str | None) -> tuple[list[str], str | None]:
    """(paths named, base after it) of one `cd` / `pushd`."""
    targets = [w for w in words[1:] if not w.startswith("-")]
    if not targets:
        return [], None  # `cd` (home) or `cd -` (the previous directory)
    target = _within(base, targets[0])
    return [target], target if target.startswith("/") else None


def _shell_program(shell: _Shell, group: list[Any]):
    """The program string node of a shell given one with `-c`, or None."""
    for flag, program in itertools.pairwise(group[1:]):
        text = _word(shell, flag)
        if (
            text.startswith("-")
            and not text.startswith("--")
            and "c" in text
            and program.type in ("raw_string", "string")
        ):
            return program
    return None


# `$W`, `${W}` and the `$W` of `$W/sub`: the variable forms a path word takes.
# re.ASCII keeps `\w` to the ASCII letters, digits and `_` a bash name allows.
VARIABLE_RE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))", re.ASCII)


def _expanded(word: str, variables: dict[str, str | None]) -> str:
    """`word` with every variable this command assigned a known path replaced
    by that path; anything else keeps its `$` and stays unresolved."""

    def value(match: re.Match[str]) -> str:
        known = variables.get(match.group(1) or match.group(2))
        return known if known is not None else match.group(0)

    return VARIABLE_RE.sub(value, word)


def _word_value(shell: _Shell, node, variables: dict[str, str | None]) -> str:
    """A word as bash reads it: known variables expanded, except inside
    single quotes, where `$W` is the literal text `$W`."""
    if node.type == "raw_string":
        return _word(shell, node)
    if node.type == "concatenation":
        return "".join(_word_value(shell, part, variables) for part in node.children)
    return _expanded(_word(shell, node), variables)


def _assignment(shell: _Shell, node, variables: dict[str, str | None]) -> None:
    """Record `W=/path` (or `export W=/path`) for the words that follow it.

    The value is kept as written: a relative one is joined to the directory
    current where `$W` is used, as bash does. A prefix assignment
    (`W=/x git …`) applies to its own command only and is skipped. A value
    still holding a variable or a command makes the name unknown, so an older
    value is not reused."""
    name, value = node.child_by_field_name("name"), node.child_by_field_name("value")
    if name is None or (node.parent is not None and node.parent.type == "command"):
        return
    raw = _word_value(shell, value, variables) if value is not None else ""
    known = raw and "$" not in raw and "`" not in raw
    variables[_word(shell, name)] = raw if known else None


def _track_variable(shell: _Shell, node, variables: dict[str, str | None]) -> None:
    """Apply one assignment or `unset` to the variables in force. tree-sitter-bash
    gives `unset` a node of its own (`unset_command`), not a `command`."""
    if node.type == "variable_assignment":
        _assignment(shell, node, variables)
        return
    for name in node.children:
        if name.type == "variable_name":
            variables[_word(shell, name)] = None


def _group_scope(
    shell: _Shell,
    group: list[Any],
    base: str | None,
    depth: int,
    programs: set[tuple[int, int]],
    variables: dict[str, str | None],
) -> tuple[list[str], set[str], str | None]:
    """(paths, tags, base after it) of one simple command. A `bash -c`
    program read here is recorded in `programs`, so the text walk skips it."""
    words = [_word_value(shell, w, variables) for w in group]
    unwrapped = _unwrapped(group, words)
    if unwrapped is None:
        return [], set(), base
    group, words, head = unwrapped
    if head in ("cd", "pushd"):
        found, base = _cd_step(words, base)
        return found, set(), base
    if head == "git":
        found, named = _git_scope(words, base)
        return found, named, base
    if head in SHELLS:
        program = _shell_program(shell, group)
        if program is not None:
            programs.add((program.start_byte, program.end_byte))
            found, named = _shell_scope(_Shell(_word(shell, program)), base, depth)
            return found, named, base
    return [], set(), base


SUBSHELL_NODES = frozenset(["subshell", "command_substitution", "process_substitution"])


def _leave_scopes(
    node,
    scopes: list[tuple[int, dict[str, str | None]]],
    variables: dict[str, str | None],
) -> dict[str, str | None]:
    """The variables in force at `node`: each subshell the walk has left since
    the last node gives back the map from before it."""
    while scopes and node.start_byte >= scopes[-1][0]:
        variables = scopes.pop()[1]
    return variables


def _shell_scope(
    shell: _Shell, cwd: str | None, depth: int
) -> tuple[list[str], set[str]]:
    base = cwd
    paths: list[str] = []
    tags: set[str] = set()
    programs: set[tuple[int, int]] = set()  # `bash -c` strings, read as programs
    variables: dict[str, str | None] = {}  # `W=/path` assigned earlier in the command
    # Variables set inside `( … )` or `$( … )` are gone when it ends.
    scopes: list[tuple[int, dict[str, str | None]]] = []
    for node in shell._walk():
        variables = _leave_scopes(node, scopes, variables)
        if node.type in SUBSHELL_NODES:
            scopes.append((node.end_byte, dict(variables)))
        if node.type in TEXT_SCOPE_NODES:
            if (node.start_byte, node.end_byte) not in programs:
                paths += _text_scope(shell, node, depth)
        elif node.type in ("variable_assignment", "unset_command"):
            _track_variable(shell, node, variables)
        elif node.type == "command":
            for group in _simple_commands(shell, node):
                found, named, base = _group_scope(
                    shell, group, base, depth, programs, variables
                )
                paths += found
                tags |= named
    return paths, tags


def _scan_commands(
    commands: list[tuple[str, str | None]],
) -> tuple[set[str], set[str], set[str]]:
    """Candidate paths, forge slugs and release tags named on command lines."""
    candidates: set[str] = set()
    forges: set[str] = set()
    tags: set[str] = set()
    for command, cwd in commands:
        paths, named = _command_scope(command, cwd)
        candidates.update(paths)
        tags |= named
        for match in FORGE_RE.finditer(command):
            forges.add(match.group("slug"))
    return candidates, forges, tags


def _resolve_roots(candidates: set[str]) -> tuple[set[str], set[str]]:
    """Split candidate paths into repository roots and what stayed unresolved."""
    roots: set[str] = set()
    unresolved: set[str] = set()
    for raw in candidates:
        # A path built from a shell variable, or a relative path whose base
        # the transcript does not name, cannot be resolved without running the
        # shell, and guessing at it would put a wrong repository in the scope
        # line, which is worse than a short one. It is listed, not dropped.
        if "$" in raw or "`" in raw or not raw.startswith("/"):
            unresolved.add(raw)
            continue
        root = repo_root(Path(raw))
        if root is not None:
            roots.add(str(root))
        else:
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


def _write_number(command: str, write: re.Match) -> re.Match | None:
    """The number a `gh|glab pr|mr|issue <verb> N` names right after its verb.

    The number must be the whole argument: `123-fix` is a branch, not PR 123."""
    return re.match(r"\s+(\d+)(?=$|[\s;&|)])", command[write.end() :])


def _reports_on_status_line(command: str, write: re.Match) -> bool:
    """A gh `ready`/`merge` that names no number (`gh pr ready <branch>`):
    it reports on a status line, never a URL alone on a line, so it takes
    only status lines (every one of its repository: with two such writes
    and two creates on one repository, the second create stays unresolved)."""
    return (
        write.groupdict().get("cli") == "gh"
        and write.groupdict().get("verb") in STATUS_REPORT_VERBS
        and not _write_number(command, write)
    )


def _write_order(command: str, write: re.Match) -> int:
    """Every write before the creates, so a create never takes the URL of a
    PR an edit, a comment or a merge in the same call reported. The one
    exception is a write that `_reports_on_status_line`: it cannot take a
    URL line, so it follows the creates in command order and a create in
    `gh pr create … && gh pr ready <branch>` keeps the URL it printed."""
    verb = write.groupdict().get("verb")
    if verb == "create" or _reports_on_status_line(command, write):
        return 1
    return 0


def _segment(command: str, write: re.Match) -> str:
    """The write's own simple command: up to the next newline, `;`, `|` or `&`
    outside quoted text and outside a later `$(…)`, as the parser reads it."""
    return command[write.start() : _shell(command).segment_end(write.start())]


def _named_lines(
    result: str, cli: str, host: str, noun: str = "", form: str = ""
) -> list[tuple[dict[str, Any] | None, str, int]]:
    """What the output's report lines name, in order.

    Each entry is (artefact, "", 0) for a URL, `owner/repo#N` or a JSON
    `html_url`, or (None, sep, N) for a bare `#N` / `!N` on a status line.
    `form` narrows them to what one kind of write prints: "url" keeps URLs
    (alone on a line, a JSON `html_url`, or on a status line such as glab's
    `- Creating issue in g/p https://…`) and drops `o/r#N` / `#N`; "status"
    keeps status lines only; "" keeps everything."""
    found: list[tuple[dict[str, Any] | None, str, int]] = []
    previous = ""
    for line in result.splitlines():
        # `gh pr create` that failed: `a pull request for branch "x" into
        # branch "main" already exists:` and the existing PR's URL below it.
        existing = previous.rstrip().endswith("already exists:")
        previous = line
        text = line.strip().strip("`'\"").rstrip(".,")
        html = HTML_URL_LINE_RE.match(line) or _json_url(line)
        if html:
            text = html["url"]
        if text.startswith("https://") and " " not in text:
            if form != "status" and not (form == "url" and existing):
                found += [(a, "", 0) for a in artefacts_in_text(text)]
            continue
        if not STATUS_LINE_RE.match(line):
            continue
        if line.lstrip().startswith("!") and "already" in line:
            continue  # `! Pull request o/r#5 is already queued`: nothing written
        urls = artefacts_in_text(line)
        found += [(a, "", 0) for a in urls]
        if urls or form == "url":
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


# Node types whose text is data, not commands, and those that make it code again.
TEXT_NODES = frozenset(
    [
        "string",
        "raw_string",
        "ansi_c_string",
        "translated_string",
        "comment",
        "heredoc_body",
    ]
)
CODE_NODES = frozenset(["command_substitution", "process_substitution"])
LOOP_NODES = frozenset(["for_statement", "c_style_for_statement", "while_statement"])


class _Shell:
    """One command as tree-sitter-bash reads it, with positions in characters.

    The regexes elsewhere find candidate writes in the raw command; this class
    answers the questions a regex cannot: whether a position is text or code,
    where the simple command around it ends, and whether it runs in a loop."""

    def __init__(self, source: str):
        self.source = source
        # A transcript's JSON can hold an unpaired surrogate escape, which a
        # plain encode() refuses; surrogatepass keeps one code unit per char.
        data = self._data = source.encode("utf-8", "surrogatepass")
        self.root = BASH.parse(data).root_node
        # Tree offsets are bytes; every caller works in characters.
        self._byte = [0]
        for ch in source:
            self._byte.append(self._byte[-1] + len(ch.encode("utf-8", "surrogatepass")))
        self._char = [0] * (len(data) + 1)
        for index, offset in enumerate(self._byte):
            self._char[offset] = index
        self.blanked = self._blank()
        self.substitutions = [
            (self._char[n.start_byte], self._char[n.end_byte])
            for n in self._walk()
            if n.type == "command_substitution"
        ]

    def _walk(self):
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def _node_at(self, index: int):
        offset = self._byte[min(index, len(self.source))]
        return self.root.descendant_for_byte_range(offset, offset + 1)

    def _blank(self) -> str:
        """The command with its texts blanked, same length: heredoc bodies and
        comments whole, quoted strings with a space in them between their
        quotes (a quoted path or slug stays). A `$(…)` inside a text is code
        and stays."""
        mask = [False] * len(self.source)

        def paint(node, value: bool) -> None:
            start, end = self._char[node.start_byte], self._char[node.end_byte]
            if value and node.type in (
                "string",
                "raw_string",
                "ansi_c_string",
                "translated_string",
            ):
                if " " not in self.source[start:end]:
                    return
                # `$'…'` opens with two characters; keep both quotes whole.
                opening = 2 if self.source[start] == "$" else 1
                start, end = start + opening, end - 1
            for i in range(start, end):
                mask[i] = value

        stack = [(self.root, False)]
        while stack:
            node, in_text = stack.pop()
            if node.type in CODE_NODES:
                paint(node, False)
                in_text = False
            elif node.type in TEXT_NODES:
                paint(node, True)
                in_text = True
            stack.extend((child, in_text) for child in reversed(node.children))
        return "".join(
            " " if hidden and ch != "\n" else ch
            for ch, hidden in zip(self.source, mask)
        )

    def is_text(self, index: int) -> bool:
        """Whether the character at `index` is data: the nearest enclosing text
        or substitution node decides."""
        node = self._node_at(index)
        while node is not None:
            if node.type in CODE_NODES:
                return False
            if node.type in TEXT_NODES:
                # A quoted word without a space is a path or a slug
                # (`"$HOME/…/tracker.py"`), not a text.
                return (
                    node.type in ("comment", "heredoc_body")
                    or " "
                    in (
                        self.source[
                            self._char[node.start_byte] : self._char[node.end_byte]
                        ]
                    )
                )
            node = node.parent
        return False

    def in_loop_body(self, index: int) -> bool:
        node = self._node_at(index)
        while node is not None:
            if (
                node.type == "do_group"
                and node.parent is not None
                and (node.parent.type in LOOP_NODES)
            ):
                return True
            node = node.parent
        return False

    def own_text(self, index: int) -> str:
        """The blanked command, same length, with every `$(…)` that starts
        after `index` blanked too: another command's words, not this one's. A
        `$(` around `index` starts before it and stays."""
        text = list(self.blanked)
        for start, end in self.substitutions:
            if start > index:
                for i in range(start + 2, end - 1):
                    if text[i] != "\n":
                        text[i] = " "
        return "".join(text)

    def segment_end(self, index: int) -> int:
        """End of the simple command starting at `index`: the next newline,
        `;`, `|` or `&` outside a text and outside a later `$(…)`."""
        own = self.own_text(index)[index:]
        return index + len(re.match(r"[^\n;|&]*", own).group(0))

    def without_substitutions(self) -> str:
        """The blanked command with every `$(…)` body blanked too, same length."""
        return self.own_text(-1)

    @functools.cached_property
    def misparsed(self) -> bool:
        """An ERROR or MISSING node, or two lines glued into one command: the
        grammar joins `a | b` and a following `c | d` line without flagging it."""
        if self.root.has_error:
            return True
        data = self._data
        for node in self._walk():
            if node.type != "command":
                continue
            for a, b in zip(node.children, node.children[1:]):
                gap = data[a.end_byte : b.start_byte]
                if b"\n" in gap and b"\\\n" not in gap:
                    return True
        return False


@functools.lru_cache(maxsize=256)
def _shell(command: str) -> _Shell:
    return _Shell(command)


def _writes(command: str) -> list[re.Match]:
    found = list(FORGE_WRITE_RE.finditer(command))
    shell = _shell(command)
    for m in API_WRITE_RE.finditer(command):
        call = _segment(command, m)
        # A `-X GET` inside a quoted body or a `$(…)` is not this write's method.
        # From the write onward, so a `$(` around the write is not included; a
        # `$(…)` further along is another command and is blanked before the
        # segment is cut, so a `|` or `;` inside it does not end the segment.
        own = shell.own_text(m.start())[m.start() : shell.segment_end(m.start())]
        if EXPLICIT_GET_RE.search(own):
            continue
        # A query written into the call is read where it stands; one held in a
        # variable (`-f query="$Q"`) may be a mutation anywhere in the command.
        query = call if LITERAL_QUERY_RE.search(call) else command
        if (
            "graphql" in call
            and "mutation" not in query
            and not QUERY_ELSEWHERE_RE.search(call)
            and not _query_from_run_time(command, call)
        ):
            continue  # a GraphQL query (a query read from a file may be a mutation)
        found.append(m)
    return found


def _query_from_run_time(command: str, call: str) -> bool:
    """Whether a GraphQL document held in a variable (`query="$Q"`) may be
    something the call's text does not show: unless every value the call
    gives that variable is plain text (`Q='mutation{…}'`), it comes from a
    command, a file, another variable or an earlier call, and may be a
    mutation."""
    return any(
        _held_elsewhere(command, held["name"])
        for held in QUERY_VARIABLE_RE.finditer(call)
    )


def _held_elsewhere(command: str, name: str) -> bool:
    """Whether the call gives the variable `name` anything but plain text.
    A positional parameter (`$1`, `"$@"`) is never a variable assignment
    the call shows, so it always counts as given elsewhere."""
    shell = _shell(command)
    assigned = False
    for node in shell._walk():
        if node.type == "variable_assignment":
            named = node.child_by_field_name("name")
            if named is None or _word(shell, named) != name:
                continue
            text = _word(shell, node)
            value = node.child_by_field_name("value")
            given = _word(shell, value) if value is not None else ""
            appended = "+=" in text[: len(text) - len(given)]
            if appended or "$" in given or "`" in given:
                return True
            assigned = True
        elif node.type == "for_statement":
            variable = node.child_by_field_name("variable")
            if variable is not None and _word(shell, variable) == name:
                return True
        elif _sets_variable(shell, node, name):
            return True
    return not assigned


def _sets_variable(shell: _Shell, node, name: str) -> bool:
    """Whether a command may give the variable `name` a value at run time.
    Any command that names it as a bare word (not `$name`) counts, whatever
    runs it: `read t`, `printf -v t`, `declare t=…`, `IFS= builtin read t`,
    `eval 't=…'`, `\\read t`. Only gh and glab, `echo`, and a `printf`
    without `-v` are known to set nothing."""
    if node.type not in ("command", "declaration_command"):
        return False
    text = shell.source[shell._char[node.start_byte] : shell._char[node.end_byte]]
    if not re.search(rf"(?<![\w$])(?<!\$\{{){re.escape(name)}(?!\w)", text):
        return False
    head = node.child_by_field_name("name")
    command = os.path.basename(_word(shell, head)) if head is not None else ""
    if node.type == "declaration_command" or command.startswith("\\"):
        return True
    if command in ("gh", "glab", "echo"):
        return False
    words = [_word(shell, c) for c in node.children_by_field_name("argument")]
    return command != "printf" or any(w.startswith("-v") for w in words)


def _blank_texts(command: str) -> str:
    """The command with heredoc bodies and quoted texts blanked, same length."""
    return _shell(command).blanked


def _in_loop(command: str, index: int) -> bool:
    return _shell(command).in_loop_body(index)


def _is_text(command: str, write: re.Match) -> bool:
    """A write that is part of a text: inside a heredoc body, a quoted string
    or a comment, and not inside a `$(…)` within it."""
    return _shell(command).is_text(write.start())


class _Call:
    """One tool call: its command, its output, and whether it failed."""

    def __init__(self, command: str, result: str, gitlab_host: str, failed: bool):
        self.command = command
        self.result = result
        self.gitlab_host = gitlab_host
        # The output says a write failed.
        self.reported_failure = (
            failed
            or bool(REPORTED_FAILURE_RE.search(result))
            or _took_the_failure_branch(command, result)
        )
        # Or it is not in the result at all: the call ran in the background.
        self.failed = self.reported_failure or bool(BACKGROUND_RE.search(result))
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
        """What `gh|glab pr|mr|issue <verb>` wrote to; None when unknown.

        A create takes only a URL line, the form it prints. A gh write that
        reports on a status line (`STATUS_REPORT_VERBS`) and names no number
        takes only status lines, so a create in the same call keeps its URL."""
        cli, noun, verb = write["cli"], write["noun"], write["verb"]
        segment = _segment(self.command, write)
        slug = FORGE_RE.search(segment)
        number = _write_number(self.command, write)
        form = ""
        if verb == "create":
            form = "url"
        elif _reports_on_status_line(self.command, write):
            form = "status"
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
        for ref, sep, bare in _named_lines(self.result, cli, host, noun, form):
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
        # a call the parser reads whole (an unclosed heredoc, which hides its
        # extent, is an ERROR node). A run in the background names its target
        # the same way; only its output is elsewhere.
        # Never when the output names this number under another repository:
        # then the `-R` was not understood, and a guess would name a wrong one.
        if (
            number
            and slug
            and not same_number
            and not self.reported_failure
            and not _shell(self.command).misparsed
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


def _echo_text(argument: str) -> str:
    """What an echo argument prints: a quoted one exactly its quoted text (a
    `>` inside `"merge -> failed"` is text), an unquoted one without its own
    redirection (`echo failed >&2`)."""
    argument = argument.strip()
    quoted = QUOTED_RE.match(argument)
    if quoted:
        return quoted.group(0)[1:-1].strip()
    return ECHO_REDIRECT_RE.sub("", argument).strip()


def _took_the_failure_branch(command: str, result: str) -> bool:
    """Whether a write's own `&& echo A || echo B` printed B and not A: the
    write exited non-zero. Only the pair right behind a write counts, so a
    `test -f … && echo … || echo …` elsewhere in the call says nothing."""
    lines = {line.strip() for line in result.splitlines()}
    # A `|` inside a `$(…)` argument is another command's; blanked, same length.
    plain = _shell(command).without_substitutions()
    for write in _writes(command):
        m = ECHO_BRANCHES_RE.match(plain, write.start())
        if not m:
            continue
        ok, fail = (_echo_text(command[m.start(g) : m.end(g)]) for g in ("ok", "fail"))
        if fail and "$" not in fail and fail in lines and ok not in lines:
            return True
    return False


def _joined(command: str) -> str:
    """Backslash-newline continuations joined, same length."""
    return command.replace("\\\n", "  ")


def _run_words(words: list[str]) -> list[str]:
    """A simple command's words from the program it runs: `timeout 600`,
    `env A=1`, `bash -x` and the other wrappers peeled off."""
    index = 0
    while index < len(words):
        head = os.path.basename(words[index])
        if head not in COMMAND_WRAPPERS and head not in SHELLS:
            return words[index:]
        index += 1
        while index < len(words) and (
            words[index].startswith("-")
            or (head == "timeout" and DURATION_RE.fullmatch(words[index]))
            or (head == "env" and "=" in words[index])
        ):
            index += 1
    return []


def _wrapper_mentions(command: str) -> list[tuple[list[str] | None, bool]]:
    """Each `pr-merge.sh` outside a text that may run, with whether its
    output goes to a file: the words of the simple command it runs
    (`pr-merge.sh -R o/r 5 …`), or None when the words around it do not say
    (a `for` list, `xargs`). A mention a file reader is given (`grep -n x
    pr-merge.sh`, `head pr-merge.sh`) is no run, unless the reader's output
    may reach a program (`_read_output_may_run`)."""
    shell = _shell(command)
    mentions: list[tuple[list[str] | None, bool]] = []
    for m in PR_MERGE_WRAPPER_RE.finditer(shell.blanked):
        node = _enclosing(shell._node_at(m.start()), "command")
        group = None
        if node is not None:
            offset = shell._byte[m.start()]
            group = next(
                (
                    g
                    for g in _simple_commands(shell, node)
                    if g[0].start_byte <= offset < g[-1].end_byte
                ),
                None,
            )
        if group is None:
            mentions.append((None, False))
            continue
        words = _run_words([_word(shell, w) for w in group])
        head = os.path.basename(words[0]) if words else ""
        if head == "pr-merge.sh":
            mentions.append((words, _to_a_file(shell, node)))
        elif head not in FILE_READERS or _read_output_may_run(shell, node):
            mentions.append((None, False))
    return mentions


# Where a reader's output only reaches the terminal (or more readers).
READER_CONTEXT = frozenset(
    {
        "program",
        "list",
        "do_group",
        "for_statement",
        "while_statement",
        "if_statement",
        "elif_clause",
        "else_clause",
        "negated_command",
    }
)


def _to_a_file(shell: _Shell, node, stdout_only: bool = False) -> bool:
    """Whether a command prints nothing the transcript shows: its standard
    output and its standard error both end in a file (`> m.txt 2>&1`,
    `&> m.txt`; not `2>&1 > m.txt`, applied left to right). `pr-merge.sh`
    reports a refusal on standard error. With `stdout_only`, whether its
    standard output alone ends in a file."""
    parent = node.parent
    if parent is None or parent.type != "redirected_statement":
        return False
    out = err = "terminal"
    for r in parent.children_by_field_name("redirect"):
        if r.type != "file_redirect":
            continue
        text = _word(shell, r).replace(" ", "")
        if text.startswith("&>"):
            out = err = "file"
        elif text == "2>&1":
            err = out
        elif re.match(r"1?>&2", text):
            out = err
        elif text.startswith("2>"):
            err = "file"
        elif re.match(r"1?>", text):
            out = "file"
    return out == "file" and (err == "file" or stdout_only)


def _read_output_may_run(shell: _Shell, node) -> bool:
    """Whether what a reader prints may reach a program: a pipeline into a
    command that is not a reader (`cat pr-merge.sh | bash -s`), a file
    (`cat pr-merge.sh > m.sh`), or a substitution, group or subshell whose
    output goes on (`bash <(cat pr-merge.sh)`, `eval "$(cat …)"`,
    `{ cat pr-merge.sh; } | bash`). `grep … | head` reaches none."""
    child, parent = node, node.parent
    while parent is not None and parent.type != "program":
        if parent.type == "pipeline":
            for part in parent.children:
                if part.start_byte <= child.start_byte or part.type in ("|", "|&"):
                    continue
                name = (
                    part.child_by_field_name("name") if part.type == "command" else None
                )
                if (
                    name is None
                    or os.path.basename(_word(shell, name)) not in FILE_READERS
                ):
                    return True
        elif parent.type == "redirected_statement":
            if _to_a_file(shell, child, stdout_only=True):
                return True
        elif parent.type not in READER_CONTEXT:
            return True
        child, parent = parent, parent.parent
    return False


def _wrapper_target(words: list[str]) -> tuple[str, int] | None:
    """(repository, number) a `pr-merge.sh` run names in literal words."""
    repo = last = None
    rest = iter(words[1:])
    for word in rest:
        if word in ("-R", "--repo"):
            repo = next(rest, None)
        elif word.startswith("--repo="):
            repo = word.split("=", 1)[1]
        elif not word.startswith("-"):
            last = word  # the script keeps its last positional argument
    if repo and last and last.isdigit() and re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return repo, int(last)
    return None


def _wrapper_targets(command: str, result: str) -> list[dict[str, Any]] | None:
    """What `pr-merge.sh` merged or commented on, from its own report lines;
    [] when it says it wrote nothing or never runs, None when it says
    neither. Its report can be in a file the transcript does not show
    (`pr-merge.sh -R o/r 5 > merge.txt`); then its literal `-R` and number
    name the target, since every write it makes (the merge, the queue
    entry, the self-review attestation) goes to that PR."""
    mentions = [
        (w, to_file)
        for w, to_file in _wrapper_mentions(command)
        if w is None or not NO_WRITE_FLAGS & set(w)
    ]
    if not mentions:
        return []
    targets = [_wrapper_target(w) if w else None for w, _ in mentions]
    if all(targets):
        return _literal_wrapper_targets(
            [(t, to_file) for t, (_, to_file) in zip(targets, mentions)], result
        )
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


def _literal_wrapper_targets(
    runs: list[tuple[tuple[str, int], bool]], result: str
) -> list[dict[str, Any]]:
    """The PRs runs with literal targets wrote to: each target, unless every
    run on it shows its output and a report at a line start says it wrote
    nothing there (`pr-merge: not merging o/r#5 …`, `pr-merge: o/r#5
    failed …`), once per run, and none says it wrote (the attestation it
    posts before it declines to merge). Any other report line is somebody
    else's text."""
    wrote = {
        (m["project"].lower(), int(m["number"]))
        for m in PR_MERGE_REPORT_RE.finditer(result)
    }
    shut: dict[tuple[str, int], int] = {}
    for m in PR_MERGE_SHUT_RE.finditer(result):
        project, _, number = (m["target"] or m["failed"]).rpartition("#")
        key = (project.lower(), int(number))
        shut[key] = shut.get(key, 0) + 1
    counts: dict[tuple[str, int], list[bool]] = {}
    for (repo, number), to_file in runs:
        counts.setdefault((repo, number), []).append(to_file)
    return [
        dict(artefact(GITHUB_HOST, repo, "pull", number), origin="acted")
        for (repo, number), files in counts.items()
        if any(files)
        or (repo.lower(), number) in wrote
        or shut.get((repo.lower(), number), 0) < len(files)
    ]


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


def _comment_endpoint(command: str, write: re.Match, call: _Call) -> str | None:
    """The REST path of the one GitHub comment a successful API write edits,
    when that path is all it names. A deletion leaves nothing to ask for."""
    segment = _segment(command, write)
    if call.failed or write.groupdict().get("cli") != "gh":
        return None
    if re.search(r"(?:-X|--method)[\s=]*DELETE\b", segment):
        return None
    found = COMMENT_ENDPOINT_RE.search(segment)
    return found.group(0) if found else None


def _review_thread_ids(
    command: str, write: re.Match, call: _Call
) -> tuple[list[str], bool]:
    """The review-thread and review-comment node ids a successful GraphQL
    mutation names, literally or through a variable (`_traced_thread_ids`),
    and whether those are all it names: False when a variable id does not
    trace to literal ones. ([], True) for any other write and for a call
    that failed."""
    segment = _segment(command, write)
    if call.failed or "graphql" not in segment:
        return [], True
    if not REVIEW_THREAD_MUTATION_RE.search(segment):
        return [], True
    # An id counts only where a mutation takes it, never in a body or note.
    found = THREAD_ID_LITERAL_RE.findall(segment) + COMMENT_ID_ARGUMENT_RE.findall(
        segment
    )
    found += [
        v
        for k, v in GQL_FIELD_ID_RE.findall(segment)
        if re.search(
            rf"(?:pullRequestReviewThreadId|threadId|pullRequestReviewCommentId)"
            rf"\s*:\s*\${k}\b",
            segment,
        )
    ]
    for loop in FOR_LIST_RE.finditer(command[: write.start()]):
        if re.search(rf"\$\{{?{loop['var']}\b", segment):
            found += REVIEW_THREAD_ID_RE.findall(loop["list"])
    # Every argument must be a literal id or a variable that traces to
    # literal ids; any other form (`threadId:"'"$T"'"`) leaves it unknown.
    literal = len(THREAD_ID_LITERAL_RE.findall(segment)) + len(
        COMMENT_ID_ARGUMENT_RE.findall(segment)
    )
    by_variable = len(THREAD_ID_ARGUMENT_RE.findall(segment))
    known = literal + by_variable >= len(ID_ARGUMENT_RE.findall(segment))
    # A document from a file or a command may name other threads.
    known = (
        known
        and not QUERY_ELSEWHERE_RE.search(segment)
        and not _query_from_run_time(command, segment)
    )
    if by_variable:
        # A thread named by a variable, beside literal ones or not: every
        # such variable must trace to literal ids, or the write is unknown.
        traced = _traced_thread_ids(command, write)
        if traced is None:
            return list(dict.fromkeys(found)), False
        found += traced
    return list(dict.fromkeys(found)), known


# The GraphQL argument a thread mutation names its thread by:
# `pullRequestReviewThreadId:$id` (a GraphQL variable, given with `-f id=…`;
# `\$id` inside a double-quoted query) or `threadId:\"$t\"` (a shell
# variable inside a double-quoted query).
THREAD_ID_ARGUMENT_RE = re.compile(
    r"\b(?:pullRequestReviewThreadId|threadId|pullRequestReviewCommentId)\s*:\s*(?:\\?\")?"
    r"\\?(?P<ref>\$(?:\{[^}\"]*\}|\w+))"
)
# Every place a mutation takes a thread or comment id, whatever follows.
ID_ARGUMENT_RE = re.compile(
    r"(?<!\$)\b(?:pullRequestReviewThreadId|threadId|pullRequestReviewCommentId)\s*:"
)
# `$id`, `${id}`, `$1`, `${pair%%|*}`: a variable and the operator applied to it.
SHELL_REF_RE = re.compile(
    r"\$(?:\{(?P<braced>[A-Za-z_]\w*|\d)(?P<op>[^}]*)\}|(?P<name>[A-Za-z_]\w*|\d))"
)
FIELD_FLAGS = frozenset({"-f", "-F", "--field", "--raw-field"})
# Builtins and wrappers that run a command they are given as data.
DISPATCHERS = frozenset(
    {".", "source", "eval", "trap", "xargs", "command", "builtin", "exec", "compgen"}
    | {"declare", "typeset", "alias", "time", "nohup", "timeout", "env", "sudo"}
)
# What changes which value a positional parameter holds inside a function.
POSITIONAL_SHIFT_RE = re.compile(r"\b(?:shift|getopts)\b|\bset\s+\S|\$#|\$@|\$\*")


def _enclosing(node, kind: str):
    while node is not None and node.type != kind:
        node = node.parent
    return node


def _write_words(shell: _Shell, index: int) -> tuple[Any, list[str]] | None:
    """The `command` node around `index` and the words, as written, of the
    simple command in it that holds `index`."""
    node = _enclosing(shell._node_at(index), "command")
    if node is None:
        return None
    offset = shell._byte[index]
    for group in _simple_commands(shell, node):
        if group[0].start_byte <= offset < group[-1].end_byte:
            return node, [
                shell.source[shell._char[w.start_byte] : shell._char[w.end_byte]]
                for w in group
            ]
    return None


def _in_shell_expansion(shell: _Shell, index: int) -> bool:
    """Whether the `$` at `index` is expanded by the shell, not text for gh."""
    node = shell._node_at(index)
    while node is not None and node.type not in ("string", "raw_string", "program"):
        if node.type in ("simple_expansion", "expansion"):
            return True
        node = node.parent
    return False


def _bindings(shell: _Shell, write_node, name: str) -> list[str] | None:
    """Every value the variable `name` takes in this call, as written, or
    None when one of them is not in the call's text: a positional parameter
    of the function the write is in (`reply(){ … "$1" …; }; reply PRRT_x …`),
    an assignment (`t=PRRT_x`) or a `for` list (`for t in PRRT_x …`)."""
    values: list[str] = []
    if name.isdigit():
        function = _enclosing(write_node, "function_definition")
        called = function.child_by_field_name("name") if function else None
        if called is None:
            return None
        body = function.child_by_field_name("body")
        if body is not None and POSITIONAL_SHIFT_RE.search(_word(shell, body)):
            return None  # `shift`, `set -- …`, `getopts`: `$1` moves
        if _called_indirectly(shell, _word(shell, called)):
            return None  # `f=r; $f PRRT_b`: a call the names do not show
        for node in shell._walk():
            head = node.child_by_field_name("name") if node.type == "command" else None
            if head is None or _word(shell, head) != _word(shell, called):
                continue
            arguments = node.children_by_field_name("argument")
            if int(name) > len(arguments):
                return None
            values.append(_word(shell, arguments[int(name) - 1]))
        return values or None
    for node in shell._walk():
        if node.type == "variable_assignment" and (
            node.parent is None or node.parent.type != "command"
        ):
            named, value = (
                node.child_by_field_name("name"),
                node.child_by_field_name("value"),
            )
            if named is not None and _word(shell, named) == name:
                values.append(_word(shell, value) if value is not None else "")
        elif node.type == "for_statement":
            variable = node.child_by_field_name("variable")
            if variable is not None and _word(shell, variable) == name:
                values += [
                    _word(shell, v) for v in node.children_by_field_name("value")
                ]
        elif _sets_variable(shell, node, name):
            return None  # a value set at run time
    return values or None


def _called_indirectly(shell: _Shell, function: str) -> bool:
    """Whether the call may run `function` other than by its plain name:
    an occurrence of the name, outside its definition, that is not the name
    of a command (`\\r …`, `retry r …`, `f=${F:-r}; $f …`, `trap 'r …' EXIT`,
    a body that mentions it), a command named by an expansion (`$f`,
    `$(printf …)`, `"${FUNCNAME[0]}"`) or a builtin that runs what it is
    given (`.`, `eval`, `xargs`, …) leaves its calls unknown."""
    calls = sum(
        1
        for n in shell._walk()
        if n.type == "command"
        and n.child_by_field_name("name") is not None
        and shell.source[
            shell._char[n.child_by_field_name("name").start_byte] : shell._char[
                n.child_by_field_name("name").end_byte
            ]
        ]
        == function
    )
    named = re.findall(rf"(?<!\w){re.escape(function)}(?!\w)", shell.source)
    if len(named) > calls + 1:  # one is the definition
        return True
    # A command whose name is not a plain word, or a builtin that runs code
    # it is given, may call the function without spelling its name.
    for n in shell._walk():
        name = n.child_by_field_name("name") if n.type == "command" else None
        if name is None:
            continue
        word = _word(shell, name)
        if not re.fullmatch(r"[\w./-]+", word) or word in DISPATCHERS:
            return True
    return False


def _bound_ids(
    shell: _Shell, write_node, value: str, depth: int = 0
) -> list[str] | None:
    """The thread ids `value` stands for: itself when it is one, or the
    values of the variable it expands. `${pair%%|*}` keeps the front of each
    value, so `for pair in "PRRT_x|reply text"` gives PRRT_x."""
    if REVIEW_THREAD_ID_RE.fullmatch(value):
        return [value]
    ref = SHELL_REF_RE.fullmatch(value)
    if ref is None or depth > 2:
        return None
    name, op = ref["braced"] or ref["name"], ref["op"] or ""
    if op and not op.startswith("%"):
        return None
    values = _bindings(shell, write_node, name)
    if values is None:
        return None
    ids: list[str] = []
    for bound in values:
        front = (REVIEW_THREAD_ID_RE.match if op else REVIEW_THREAD_ID_RE.fullmatch)(
            bound
        )
        nested = (
            None if front or op else _bound_ids(shell, write_node, bound, depth + 1)
        )
        if front:
            ids.append(front.group(0))
        elif nested:
            ids += nested
        else:
            return None
    return ids


def _traced_thread_ids(command: str, write: re.Match) -> list[str] | None:
    """The ids of a thread mutation that names its thread by a variable,
    when every value that variable takes is a literal id in this call; None
    otherwise (an id read from a query, a file or the network)."""
    shell = _shell(command)
    located = _write_words(shell, write.start())
    if located is None:
        return None
    node, words = located
    fields = {}
    for flag, value in itertools.pairwise(words):
        if flag in FIELD_FLAGS and "=" in value:
            key, _, given = value.partition("=")
            fields[key] = unquote(given)
    segment = _segment(command, write)
    ids: list[str] = []
    refs = list(THREAD_ID_ARGUMENT_RE.finditer(segment))
    for m in refs:
        ref = m["ref"]
        if _in_shell_expansion(shell, write.start() + m.start("ref")):
            value = ref
        else:
            parsed = SHELL_REF_RE.fullmatch(ref)
            value = fields.get(parsed["braced"] or parsed["name"]) if parsed else None
        found = _bound_ids(shell, node, value) if value else None
        if not found:
            return None
        ids += found
    return ids or None


def _forge_write_artefacts(
    command: str, result: str, gitlab_host: str, failed: bool = False
) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """What a command's forge writes wrote to, as their output names it.

    Each write is matched with the report lines its output carries: its own
    number and `-R`, a URL alone on a line or a CLI status line — never a
    link standing in running text. A refused call ran nothing. A write whose
    target stays unknown is reported as unresolved, not guessed.

    The third value lists what the forge has to be asked for the writes
    whose target is otherwise unknown: the node ids of GraphQL review-thread
    and review-comment mutations, and the REST path of a comment edited
    by id. Such a write does not make the call unresolved by itself;
    it is pending until the forge has named each one's PR or issue."""
    if refused(result, failed):
        return [], False, []
    command = _joined(command)
    call = _Call(command, result, gitlab_host, failed)
    writes = sorted(_writes(command), key=lambda w: _write_order(command, w))
    wrapper = _wrapper_targets(command, result)
    found: list[dict[str, Any]] = list(wrapper or [])
    threads: list[str] = []
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
        ids, known = (
            _review_thread_ids(command, write, call) if targets is None else ([], True)
        )
        if ids:
            # A variable id that does not trace leaves the write unknown;
            # the literal ids beside it are still asked for (their PRs read).
            threads += ids
            unresolved = unresolved or not known
        elif targets is None and (path := _comment_endpoint(command, write, call)):
            threads.append(path)
        elif targets is None:
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
    # A command the parser could not read whole (truncated, not shell, or two
    # lines the grammar glues together) may hide a write it reports as text.
    if (writes or text_writes or wrapper) and _shell(command).misparsed:
        unresolved = True
    if about_prs and not unresolved:
        unresolved = _unclaimed(result, found, text_writes)
    return found, unresolved, list(dict.fromkeys(threads))


def command_reference_candidates(
    command: str, result: str, is_error: bool = False
) -> set[str]:
    """Find literal key arguments corroborated by a successful tool result.

    The shell parser, not executable names, separates arguments from quoted
    prose and heredocs. These remain hints: a successful command may merely
    print a key; it proves neither an issue's existence nor its provider.
    """
    if is_error or refused(result, is_error) or FAILED_OUTPUT_RE.search(result):
        return set()
    shell = _shell(_joined(command))
    if shell.misparsed:
        return set()
    result_keys = tickets_in(result)
    found = set()
    for node in shell._walk():
        if node.type != "command":
            continue
        for arg in node.children_by_field_name("argument"):
            # Do not interpret substitutions, expansions or concatenations as
            # literal IDs. Commands inside substitutions are visited separately.
            if arg.type not in {"word", "string", "raw_string"}:
                continue
            text = shell.source[shell._char[arg.start_byte] : shell._char[arg.end_byte]]
            key = unquote(text)
            if TICKET_RE.fullmatch(key) and key in result_keys:
                found.add(key)
    return found


def payload_reference_candidates(payload: dict[str, Any]) -> set[str]:
    """Hints from explicit reference fields; no MCP tool-name assumptions."""
    found = set()
    for field in ("ticket", "issue_key", "work_item", "reference"):
        value = payload.get(field)
        if isinstance(value, str) and TICKET_RE.fullmatch(value):
            found |= tickets_in(value)
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

    def __init__(self, gitlab_host: str, context: str) -> None:
        self.gitlab_host = gitlab_host
        self.context = context
        self.reference_candidates: list[dict[str, str]] = []
        self.pending: dict[str, tuple[str, dict[str, Any]]] = {}
        self.by_url: dict[str, dict[str, Any]] = {}
        self.tickets: set[str] = set()
        self.unresolved: list[str] = []
        self.review_thread_writes: list[dict[str, Any]] = []

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

    def tool_result(self, block: dict[str, Any]) -> None:
        name, payload = self.pending.pop(block.get("tool_use_id", ""), ("", {}))
        result = _result_text(block)
        command = payload.get("command")
        if isinstance(command, str):
            found, lost, threads = _forge_write_artefacts(
                command, result, self.gitlab_host, bool(block.get("is_error"))
            )
            self.keep(found)
            if lost:
                self.unresolved.append(squeeze(command, 200))
            if threads:
                # A thread write is pending, not unresolved: the forge names
                # each thread's PR (collect-review-findings.py asks it). The
                # ids come from the full command; the squeezed one may end
                # before they do.
                self.review_thread_writes.append(
                    {
                        "command": squeeze(command, 200),
                        "thread_ids": [
                            t for t in threads if not t.startswith("repos/")
                        ],
                        "comment_endpoints": [
                            t for t in threads if t.startswith("repos/")
                        ],
                        "only_review_threads": not lost,
                    }
                )
        elif MCP_WRITE_RE.search(name):
            self.keep(
                _mcp_write_artefacts(payload, result, bool(block.get("is_error")))
            )
        if not block.get("is_error") and not refused(result, False):
            if isinstance(command, str):
                refs = command_reference_candidates(command, result)
            elif FAILED_OUTPUT_RE.search(result) or TOOL_ERROR_TEXT_RE.search(result):
                # A tool that reports an error in its text proves no reference,
                # even when the harness did not flag the result as an error.
                refs = set()
            else:
                refs = payload_reference_candidates(payload)
            context = f"{self.context}#tool={block.get('tool_use_id', '')}"
            self.tickets |= refs
            self.reference_candidates += [
                {"ref": ref, "context": context, "source": "tool-result", "tool": name}
                for ref in sorted(refs)
            ]
        self.mention(result)

    def event(self, event: dict[str, Any]) -> None:
        content = _message(event).get("content")
        if isinstance(content, str):
            self.mention(content)
            return
        if not isinstance(content, list):
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
    """Native artifacts plus unassigned, context-preserving reference hints.

    `origin` says how much the transcript supports the link: `created` (the
    command's own output printed the URL), `acted` (a write command named it),
    `mentioned` (a URL appeared somewhere, which includes documentation
    placeholders such as `OWNER/REPO` — a reader weighs those, a fetch skips them).
    """
    scan = _ArtefactScan(gitlab_host, transcript.resolve().as_uri())
    for event in iter_events(transcript):
        scan.event(event)
    items = sorted(
        scan.by_url.values(), key=lambda a: (-ORIGIN_RANK[a["origin"]], a["url"])
    )
    return {
        "artefacts": items,
        # Compatibility projection only; never sufficient to select a tracker.
        "tickets": sorted(scan.tickets),
        "reference_candidates": scan.reference_candidates,
        # Writes whose target neither the transcript nor a forge lookup
        # can name: a call that also holds a pending thread write is listed
        # here when something else in it stays unknown.
        "unresolved_forge_commands": scan.unresolved,
        # Calls that wrote to a review thread named by node id: pending, not
        # unresolved. `thread_ids`, and whether those threads are all the call
        # left unknown (`only_review_threads`). collect-review-findings.py
        # asks the forge which pull request each thread belongs to, and lists
        # a call whose lookup fails as unresolved.
        "review_thread_writes": scan.review_thread_writes,
    }


SESSION_ID_RE = re.compile(
    r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE
)


def subagent_transcripts(transcript: Path) -> list[Path]:
    """The session's subagent transcripts: Claude Code keeps each at
    `<session id>/subagents/agent-<agent id>.jsonl` beside `<session id>.jsonl`
    (agents an agent started included, in the same directory), and a Workflow's
    agents one level deeper, at `subagents/workflows/wf_*/agent-*.jsonl`. The
    `.meta.json` files and a workflow's `journal.jsonl` are no transcripts.
    Resolved first: a symlink to the session file names the real directory.

    Only a session file named by its UUID has subagents: a converted transcript
    at a fixed path (`/tmp/retro-codex-session.jsonl`) must not pick up a
    `subagents/` directory somebody else created beside it."""
    session = transcript.resolve()
    if not SESSION_ID_RE.fullmatch(session.stem):
        return []
    directory = session.with_suffix("") / "subagents"
    if not directory.is_dir():
        return []
    # A symlink out of the directory (another session's transcript) is not
    # this session's; it would file that session's writes under this one.
    return sorted(
        p
        for p in directory.rglob("agent-*.jsonl")
        if p.is_file() and p.resolve().is_relative_to(directory)
    )


def session_transcripts(transcript: Path) -> list[Path]:
    """The transcript and its subagents', the main one first."""
    return [transcript, *subagent_transcripts(transcript)]


def scan_transcripts(paths: list[Path], gitlab_host: str) -> dict[str, Any]:
    """`collect_artefacts` over several transcripts of one session.

    An artefact named in more than one keeps its strongest origin, so a PR a
    subagent created and the main loop only mentioned counts as created."""
    by_url: dict[str, dict[str, Any]] = {}
    merged: dict[str, Any] = {
        "tickets": set(),
        "reference_candidates": [],
        "unresolved_forge_commands": [],
        "review_thread_writes": [],
    }
    for path in paths:
        data = collect_artefacts(path, gitlab_host)
        for item in data["artefacts"]:
            have = by_url.get(item["url"])
            if not have or ORIGIN_RANK[item["origin"]] > ORIGIN_RANK[have["origin"]]:
                by_url[item["url"]] = item
        merged["tickets"] |= set(data["tickets"])
        merged["reference_candidates"] += data["reference_candidates"]
        merged["unresolved_forge_commands"] += data["unresolved_forge_commands"]
        merged["review_thread_writes"] += data["review_thread_writes"]
    merged["tickets"] = sorted(merged["tickets"])
    merged["artefacts"] = sorted(
        by_url.values(), key=lambda a: (-ORIGIN_RANK[a["origin"]], a["url"])
    )
    return merged


def collect(transcript: Path, gitlab_host: str = "") -> dict[str, Any]:
    """The scope of the session `transcript` belongs to: its own events and
    every subagent's (`session_transcripts`)."""
    transcripts = session_transcripts(transcript)
    commands: list[tuple[str, str | None]] = []
    file_paths: set[str] = set()
    days: set[str] = set()
    for path in transcripts:
        more, paths, dates = _read_transcript(path)
        commands += more
        file_paths |= paths
        days |= dates
    candidates, forges, tags = _scan_commands(commands)
    roots, unresolved = _resolve_roots(candidates | file_paths)
    forge_artefacts = scan_transcripts(transcripts, gitlab_host)

    return {
        "transcript": str(transcript),
        # The population the lists below were derived from, the main
        # transcript first, so "no repository" and "the transcript that named
        # it was not read" stay apart. Masked like the collector's.
        "transcripts": [mask(str(p)) for p in transcripts],
        "repositories": sorted(roots),
        "days": sorted(days),
        "forge_slugs": sorted(forges),
        "tags": sorted(tags),
        # Not truncated. This is the list whose whole purpose is "read these,
        # a missing repository hides here", and a silent [:20] would drop the
        # entries a long session most needs to see.
        # Raw transcript text, so masked like every other snippet.
        "unresolved_paths": sorted(mask(p) for p in unresolved),
        "commands_scanned": len(commands),
        # Native artifacts, opaque references and unresolved writes stay distinct.
        **forge_artefacts,
    }


# How many unresolved paths the text rendering shows before pointing at the
# JSON. The JSON is never truncated.
TEXT_UNRESOLVED_LIMIT = 20


def _written_lines(scope: dict[str, Any], owned: list[dict[str, Any]]) -> list[str]:
    if not owned and not scope["tickets"]:
        return []
    lines = ["", "PRs, MRs and issues this session created or wrote to:"]
    lines += [f"  {a['origin']:<8} {a['url']}" for a in owned]
    if scope["tickets"]:
        lines.append("  Unresolved reference candidates (not tracker identities):")
        lines += [
            f"    {ref['ref']} (context: {ref['context']})"
            for ref in scope.get("reference_candidates", [])
        ]
    return lines


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
    lines += _written_lines(scope, owned)
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
    pending = [w for w in scope["review_thread_writes"] if w["only_review_threads"]]
    if pending:
        lines.append(
            f"  {len(pending)} review-thread writes name their PR only on the"
            " forge — collect-review-findings.py looks them up"
        )
    unresolved = scope["unresolved_paths"]
    if unresolved:
        shown = unresolved[:TEXT_UNRESOLVED_LIMIT]
        lines += [
            "",
            f"{len(unresolved)} paths could not be resolved to a repository — read these,",
            "they are where a missing entry hides (a shell variable, a relative path",
            "whose directory the transcript does not record, or a directory since",
            "removed):",
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
    transcripts = scope["transcripts"]
    line = f"transcripts read: 1 main + {len(transcripts) - 1} subagent"
    if len(transcripts) > 1:
        line += " (--output-format json lists them)"
    lines += [
        "",
        line,
        f"({scope['commands_scanned']} Bash commands scanned. Complete where the transcripts are:",
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
