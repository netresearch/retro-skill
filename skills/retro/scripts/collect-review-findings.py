#!/usr/bin/env python3
"""
collect-review-findings.py — what reviewers, maintainers and tickets said about
a session's PRs, MRs and issues.

A review finding is a defect that passed every check the agent ran. That makes
it the most precise input a retro gets — and until now the retro saw one only
when the agent happened to read it inside the session. Findings that arrived
later, bot reviews nobody opened, and the feedback a team writes into the
ticket instead of the PR never reached it.

This script reads them from the forge and the tracker:

- per PR (GitHub): review threads, review bodies, PR comments, commits
- per MR (GitLab): discussions (threads and plain notes), commits
- linked issues: GitHub `closingIssuesReferences`, GitLab `closes_issues`, and
  issue URLs in the PR/MR description — their comments
- Jira tickets: keys in the PR/MR title and branch, plus the tickets the session
  named on a jira script — their comments and status changes, read through the
  `jira-communication` skill's `jira-issue.py`

Every finding carries `source`, `author_class` (`self` · `bot` · `human`),
`resolved` where the forge says so, and `commit_after`: the first commit on
the PR/MR dated after the finding. That is a necessary sign that the finding
changed the code, not proof — any later commit qualifies, and a rebase re-dates
them all. Read it together with `resolved` and `last_self_reply`.

`self` is the account running this script (GitHub `viewer`, GitLab `user`, Jira
`me`) plus every `--self-login`. When the session ran under another account —
Outcome mode run by somebody else — pass that account, or its comments are
listed as `human`.

Usage:
    collect-review-findings.py --transcript-file <session.jsonl> [--since ISO]
        [--include-mentioned] [--output-format text|json]
    collect-review-findings.py --ref <PR/MR/issue URL or Jira key> [--ref …]

Failure stays distinguishable from silence: an artefact that could not be read
is listed with `fetched: false` and the error, never as an artefact with no
findings. Comments from before `--since` (default: the transcript's first
timestamp) are counted, not listed — on a linked issue they are the request,
not feedback on the work.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

HERE = Path(__file__).resolve().parent


def _load_scope():
    spec = importlib.util.spec_from_file_location(
        "derive_session_scope", HERE / "derive-session-scope.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scope = _load_scope()

# Logins that are bots although GraphQL reports them as users, and GitLab
# service accounts, which carry no bot flag at all: group/project access tokens
# are `group_<id>_bot_<hash>` / `project_<id>_bot_<hash>`.
KNOWN_BOTS = frozenset(
    {
        "coderabbitai",
        "copilot-pull-request-reviewer",
        "copilot",
        "github-advanced-security",
        "github-actions",
        "renovate",
        "dependabot",
        "sonarqubecloud",
        "sonarcloud",
        "codecov",
        "gemini-code-assist",
    }
)
GITLAB_BOT_RE = re.compile(r"(?:^(?:group|project)_\d+_bot(?:_|$))|(?:(?:^|[-_.])bot$)")
ISSUE_KEYWORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.IGNORECASE
)

Runner = Callable[[list[str]], Any]
REPORT_SOURCES = frozenset({"review", "pr-comment", "mr-comment"})
# A bot verdict without content: an auto-approval, or one dismissed by a push.
BOT_EMPTY_VERDICTS = frozenset({"APPROVED", "DISMISSED"})


# --------------------------------------------------------------------------
# time


def parse_time(value: str | None) -> datetime | None:
    """ISO 8601 from GitHub, GitLab or Jira (`+0000` without a colon)."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def transcript_start(transcript: Path) -> datetime | None:
    for event in scope.iter_events(transcript):
        stamp = parse_time(event.get("timestamp"))
        if stamp:
            return stamp
    return None


# --------------------------------------------------------------------------
# classification (pure)


def author_class(login: str | None, typename: str | None, self_logins: set[str]) -> str:
    if not login:
        return "human"  # a deleted account ("ghost") is somebody, not a bot
    bare = login.removesuffix("[bot]")
    if login in self_logins or bare in self_logins:
        return "self"
    if typename == "Bot" or login.endswith("[bot]") or bare.lower() in KNOWN_BOTS:
        return "bot"
    if GITLAB_BOT_RE.search(login):
        return "bot"
    return "human"


def first_commit_after(
    commits: list[dict[str, Any]], moment: datetime | None
) -> str | None:
    """SHA of the earliest commit made after `moment`, or None."""
    if moment is None:
        return None
    later = [c for c in commits if c["date"] and c["date"] > moment]
    return min(later, key=lambda c: c["date"])["sha"] if later else None


def finding(
    artefact_url: str,
    source: str,
    login: str | None,
    klass: str,
    created: str | None,
    body: str,
    url: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "artefact": artefact_url,
        "source": source,
        # A bot's summary, status or verdict on the whole PR — a quality gate,
        # a coverage delta, a review envelope — as opposed to a finding
        # anchored in the code. Kept, because a failed gate is feedback, but
        # rendered apart so the threads are read first.
        "report": klass == "bot" and source in REPORT_SOURCES,
        "author": login or "ghost",
        "author_class": klass,
        "created_at": created,
        "url": url,
        "body": body or "",
        **extra,
    }


def _split_by_since(items: list[dict[str, Any]], since: datetime | None):
    if since is None:
        return items, 0
    kept = [i for i in items if (parse_time(i["created_at"]) or since) >= since]
    return kept, len(items) - len(kept)


# --------------------------------------------------------------------------
# GitHub


GH_PR_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  viewer { login }
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      url title body headRefName state createdAt
      author { login __typename }
      closingIssuesReferences(first: 50) { nodes { url } }
      reviewThreads(first: 100) {
        totalCount pageInfo { hasNextPage }
        nodes {
          isResolved isOutdated path line
          comments(first: 100) {
            totalCount
            nodes { author { login __typename } body createdAt url }
          }
        }
      }
      reviews(first: 100) {
        totalCount pageInfo { hasNextPage }
        nodes { state body submittedAt url author { login __typename } }
      }
      comments(first: 100) {
        totalCount pageInfo { hasNextPage }
        nodes { author { login __typename } body createdAt url }
      }
      commits(last: 100) {
        totalCount
        nodes { commit { oid committedDate messageHeadline } }
      }
    }
  }
}
"""

GH_ISSUE_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  viewer { login }
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      url title state createdAt
      author { login __typename }
      comments(first: 100) {
        totalCount pageInfo { hasNextPage }
        nodes { author { login __typename } body createdAt url }
      }
    }
  }
}
"""


def fetch_github(item: dict[str, Any], run: Runner) -> dict[str, Any]:
    owner, name = item["project"].split("/", 1)
    query = GH_PR_QUERY if item["kind"] == "pull" else GH_ISSUE_QUERY
    return run(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={item['number']}",
        ]
    )


def _gh_truncated(node: dict[str, Any], *connections: str) -> list[str]:
    """Connections that held more than one page — named, never silently cut."""
    cut = []
    for conn in connections:
        data = node.get(conn) or {}
        if (data.get("pageInfo") or {}).get("hasNextPage") or (
            data.get("totalCount", 0) > len(data.get("nodes") or [])
        ):
            cut.append(conn)
    return cut


def _nodes(node: dict[str, Any], connection: str) -> list[dict[str, Any]]:
    return (node.get(connection) or {}).get("nodes") or []


def _gh_class(node: dict[str, Any], self_logins: set[str]) -> tuple[str | None, str]:
    """(login, author class) of a GraphQL comment, review or thread entry."""
    author = node.get("author") or {}
    login = author.get("login")
    return login, author_class(login, author.get("__typename"), self_logins)


class _Collected:
    """Findings of one artefact, plus the count of the agent's own entries."""

    def __init__(self) -> None:
        self.findings: list[dict[str, Any]] = []
        self.self_count = 0


def _gh_threads(pr, url, commits, self_logins, out: _Collected) -> None:
    for thread in _nodes(pr, "reviewThreads"):
        comments = _nodes(thread, "comments")
        if not comments:
            continue
        head, replies = comments[0], comments[1:]
        login, klass = _gh_class(head, self_logins)
        # An own thread nobody answered is the agent talking to itself; one
        # that somebody answered carries feedback in the answers.
        if klass == "self" and not replies:
            out.self_count += 1
            continue
        own = [r for r in replies if _gh_class(r, self_logins)[1] == "self"]
        out.findings.append(
            finding(
                url,
                "review-thread",
                login,
                klass,
                head.get("createdAt"),
                head.get("body", ""),
                head.get("url"),
                path=thread.get("path"),
                line=thread.get("line"),
                resolved=thread.get("isResolved"),
                outdated=thread.get("isOutdated"),
                replies=len(replies),
                last_self_reply=own[-1]["body"] if own else None,
                commit_after=first_commit_after(
                    commits, parse_time(head.get("createdAt"))
                ),
            )
        )


def _gh_reviews(pr, url, commits, self_logins, out: _Collected) -> None:
    for review in _nodes(pr, "reviews"):
        login, klass = _gh_class(review, self_logins)
        state = review.get("state")
        # An empty COMMENTED review is the envelope of inline threads, which
        # are listed on their own. A verdict without text still counts.
        if state == "COMMENTED" and not (review.get("body") or "").strip():
            continue
        if klass == "self":
            out.self_count += 1
            continue
        if klass == "bot" and state in BOT_EMPTY_VERDICTS:
            continue
        stamp = review.get("submittedAt")
        out.findings.append(
            finding(
                url,
                "review",
                login,
                klass,
                stamp,
                review.get("body", ""),
                review.get("url"),
                state=state,
                commit_after=first_commit_after(commits, parse_time(stamp)),
            )
        )


def _gh_comments(node, url, source, commits, self_logins, out: _Collected) -> None:
    for comment in _nodes(node, "comments"):
        login, klass = _gh_class(comment, self_logins)
        if klass == "self":
            out.self_count += 1
            continue
        stamp = comment.get("createdAt")
        extra = (
            {"commit_after": first_commit_after(commits, parse_time(stamp))}
            if commits is not None
            else {}
        )
        out.findings.append(
            finding(
                url,
                source,
                login,
                klass,
                stamp,
                comment.get("body", ""),
                comment.get("url"),
                **extra,
            )
        )


def _gh_node(raw: dict[str, Any], kind: str, self_logins: set[str]):
    """The PR or issue node and the self set including the GraphQL viewer."""
    data = raw.get("data") or {}
    node = (data.get("repository") or {}).get(kind)
    if not node:
        raise LookupError(_graphql_error(raw) or f"{kind} not found")
    return node, self_logins | {(data.get("viewer") or {}).get("login", "")}


def parse_github_pr(raw: dict[str, Any], self_logins: set[str]) -> dict[str, Any]:
    pr, self_logins = _gh_node(raw, "pullRequest", self_logins)
    url = pr["url"]
    commits = [
        {
            "sha": n["commit"]["oid"],
            "date": parse_time(n["commit"]["committedDate"]),
            "subject": n["commit"]["messageHeadline"],
        }
        for n in _nodes(pr, "commits")
    ]
    out = _Collected()
    _gh_threads(pr, url, commits, self_logins, out)
    _gh_reviews(pr, url, commits, self_logins, out)
    _gh_comments(pr, url, "pr-comment", commits, self_logins, out)
    linked = [n["url"] for n in _nodes(pr, "closingIssuesReferences")]
    linked += _issue_urls_in(pr.get("body") or "", url)
    return {
        "url": url,
        "title": pr.get("title"),
        "branch": pr.get("headRefName"),
        "state": pr.get("state"),
        "commits": len(commits),
        "findings": out.findings,
        "self_comments": out.self_count,
        "linked": sorted(set(linked)),
        "tickets": sorted(
            scope.tickets_in(f"{pr.get('title', '')} {pr.get('headRefName', '')}")
        ),
        "truncated": _gh_truncated(pr, "reviewThreads", "reviews", "comments"),
    }


def parse_github_issue(raw: dict[str, Any], self_logins: set[str]) -> dict[str, Any]:
    issue, self_logins = _gh_node(raw, "issue", self_logins)
    out = _Collected()
    _gh_comments(issue, issue["url"], "issue-comment", None, self_logins, out)
    return {
        "url": issue["url"],
        "title": issue.get("title"),
        "state": issue.get("state"),
        "findings": out.findings,
        "self_comments": out.self_count,
        "linked": [],
        "tickets": sorted(scope.tickets_in(issue.get("title", ""))),
        "truncated": _gh_truncated(issue, "comments"),
    }


def _graphql_error(raw: dict[str, Any]) -> str:
    errors = raw.get("errors") or []
    return "; ".join(e.get("message", "") for e in errors if isinstance(e, dict))


def _issue_urls_in(text: str, own_url: str) -> list[str]:
    """Issue URLs in a PR/MR description, plus `Closes #N` in the same project."""
    urls = [a["url"] for a in scope.artefacts_in_text(text) if a["kind"] == "issue"]
    # Compared by host, never by substring: `github.com` can stand anywhere in
    # a URL that points somewhere else.
    if urlparse(own_url).hostname == scope.GITHUB_HOST:
        base = own_url.rsplit("/", 2)[0]
        urls += [f"{base}/issues/{n}" for n in ISSUE_KEYWORD_RE.findall(text)]
    return [u for u in urls if u != own_url]


# --------------------------------------------------------------------------
# GitLab


def fetch_gitlab(item: dict[str, Any], run: Runner) -> dict[str, Any]:
    enc = quote(item["project"], safe="")
    kind = "merge_requests" if item["kind"] == "merge_request" else "issues"
    base = f"projects/{enc}/{kind}/{item['number']}"
    host = ["--hostname", item["host"]]
    raw: dict[str, Any] = {
        "self": run(["glab", "api", "user", *host]),
        "item": run(["glab", "api", base, *host]),
        "notes": run(
            ["glab", "api", "--paginate", f"{base}/discussions?per_page=100", *host]
        ),
    }
    if kind == "merge_requests":
        raw["commits"] = run(
            ["glab", "api", "--paginate", f"{base}/commits?per_page=100", *host]
        )
        raw["closes"] = run(["glab", "api", f"{base}/closes_issues", *host])
    return raw


def _gitlab_source(is_mr: bool, threaded: bool) -> str:
    if not is_mr:
        return "issue-comment"
    return "review-thread" if threaded else "mr-comment"


def _gitlab_discussion(discussion, url, is_mr, commits, self_logins, out: _Collected):
    notes = [n for n in discussion.get("notes") or [] if not n.get("system")]
    if not notes:
        return
    head, replies = notes[0], notes[1:]
    login = (head.get("author") or {}).get("username")
    klass = author_class(login, None, self_logins)
    if klass == "self" and not replies:
        out.self_count += 1
        return
    own = [
        r
        for r in replies
        if author_class((r.get("author") or {}).get("username"), None, self_logins)
        == "self"
    ]
    threaded = bool(head.get("resolvable"))
    position = head.get("position") or {}
    stamp = head.get("created_at")
    out.findings.append(
        finding(
            url,
            _gitlab_source(is_mr, threaded),
            login,
            klass,
            stamp,
            head.get("body", ""),
            f"{url}#note_{head['id']}" if head.get("id") else None,
            path=position.get("new_path"),
            line=position.get("new_line"),
            resolved=head.get("resolved") if threaded else None,
            replies=len(replies),
            last_self_reply=own[-1]["body"] if own else None,
            commit_after=first_commit_after(commits, parse_time(stamp)),
        )
    )


def parse_gitlab(raw: dict[str, Any], self_logins: set[str]) -> dict[str, Any]:
    item = raw["item"]
    self_logins = self_logins | {(raw.get("self") or {}).get("username", "")}
    url = item["web_url"]
    is_mr = "/-/merge_requests/" in url
    commits = [
        {
            "sha": c["id"],
            "date": parse_time(c.get("committed_date") or c.get("created_at")),
            "subject": c.get("title"),
        }
        for c in _flatten(raw.get("commits") or [])
    ]
    out = _Collected()
    for discussion in _flatten(raw.get("notes") or []):
        _gitlab_discussion(discussion, url, is_mr, commits, self_logins, out)
    linked = [
        i["web_url"] for i in _flatten(raw.get("closes") or []) if i.get("web_url")
    ]
    linked += _issue_urls_in(item.get("description") or "", url)
    branch = item.get("source_branch") or ""
    return {
        "url": url,
        "title": item.get("title"),
        "branch": branch or None,
        "state": item.get("state"),
        "commits": len(commits) if is_mr else None,
        "findings": out.findings,
        "self_comments": out.self_count,
        "linked": sorted(set(linked)),
        "tickets": sorted(scope.tickets_in(f"{item.get('title', '')} {branch}")),
        "truncated": [],  # --paginate reads every page
    }


def _flatten(value: Any) -> list[dict[str, Any]]:
    """`glab api --paginate` concatenates one JSON array per page."""
    if isinstance(value, list) and value and isinstance(value[0], list):
        return [x for page in value for x in page]
    return value if isinstance(value, list) else []


# --------------------------------------------------------------------------
# Jira


JIRA_CLI_CANDIDATES = (
    Path.home() / ".agents/skills/jira-communication/scripts/core/jira-issue.py",
    Path.home() / ".claude/skills/jira-communication/scripts/core/jira-issue.py",
)
JIRA_USER_NAME = "jira-user.py"


def find_jira_cli(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    return next((p for p in JIRA_CLI_CANDIDATES if p.is_file()), None)


def fetch_jira(key: str, cli: Path, run: Runner) -> dict[str, Any]:
    me = cli.parent.parent / "utility" / JIRA_USER_NAME
    return {
        "self": run(["python3", str(me), "--json", "me"]) if me.is_file() else {},
        "issue": run(
            [
                "python3",
                str(cli),
                "--json",
                "get",
                key,
                "--fields",
                "summary,status,comment",
                "--expand",
                "changelog",
                "--raw",
            ]
        ),
    }


def _jira_comments(comments, url, self_logins, out: _Collected) -> None:
    for comment in comments:
        login = (comment.get("author") or {}).get("name")
        klass = author_class(login, None, self_logins)
        if klass == "self":
            out.self_count += 1
            continue
        out.findings.append(
            finding(
                url,
                "ticket-comment",
                login,
                klass,
                comment.get("created"),
                comment.get("body", ""),
            )
        )


def _jira_transitions(histories, url, self_logins, out: _Collected) -> None:
    """A status change by somebody else — a ticket sent back from QA — is
    feedback even without a word of comment."""
    for history in histories:
        login = (history.get("author") or {}).get("name")
        klass = author_class(login, None, self_logins)
        if klass == "self":
            continue
        out.findings += [
            finding(
                url,
                "ticket-transition",
                login,
                klass,
                history.get("created"),
                f"{change.get('fromString')} → {change.get('toString')}",
            )
            for change in history.get("items") or []
            if change.get("field") == "status"
        ]


def parse_jira(
    raw: dict[str, Any], self_logins: set[str], browse: str
) -> dict[str, Any]:
    issue = raw["issue"]
    me = raw.get("self") or {}
    self_logins = self_logins | {me.get("name", ""), me.get("key", "")}
    key = issue["key"]
    browse = browse or (issue.get("self") or "").split("/rest/", 1)[0]
    url = f"{browse.rstrip('/')}/browse/{key}" if browse else key
    fields = issue.get("fields") or {}
    comments = (fields.get("comment") or {}).get("comments") or []
    out = _Collected()
    _jira_comments(comments, url, self_logins, out)
    _jira_transitions(
        (issue.get("changelog") or {}).get("histories") or [], url, self_logins, out
    )
    total = (fields.get("comment") or {}).get("total", len(comments))
    return {
        "url": url,
        "title": fields.get("summary"),
        "state": (fields.get("status") or {}).get("name"),
        "findings": out.findings,
        "self_comments": out.self_count,
        "linked": [],
        "tickets": [],
        "truncated": ["comments"] if total > len(comments) else [],
    }


# --------------------------------------------------------------------------
# orchestration


def default_runner(command: list[str]) -> Any:
    """Run a CLI that prints JSON. Raises on a non-zero exit or unparsable output."""
    out = subprocess.run(
        command, capture_output=True, text=True, timeout=120, check=False
    )
    if out.returncode != 0:
        message = (out.stderr or out.stdout).strip().splitlines()
        raise RuntimeError(message[-1] if message else f"exit {out.returncode}")
    return _decode_stream(out.stdout)


def _decode_stream(text: str) -> Any:
    """One JSON value, or several back to back (`--paginate`) as a list of pages."""
    decoder = json.JSONDecoder()
    values, index = [], 0
    text = text.strip()
    while index < len(text):
        value, end = decoder.raw_decode(text, index)
        values.append(value)
        index = end
        while index < len(text) and text[index].isspace():
            index += 1
    return values[0] if len(values) == 1 else values


def ticket_item(key: str, origin: str) -> dict[str, Any]:
    return {"forge": "jira", "kind": "ticket", "key": key, "url": key, "origin": origin}


def parse_ref(ref: str) -> dict[str, Any] | None:
    found = scope.artefacts_in_text(ref)
    if found:
        return dict(found[0], origin="named")
    return ticket_item(ref, "named") if scope.TICKET_RE.fullmatch(ref) else None


def read_one(item, run, self_logins, jira_cli, jira_browse) -> dict[str, Any]:
    """Fetch and parse one artefact. Raises when it cannot be read."""
    if item["forge"] == "github":
        raw = fetch_github(item, run)
        if item["kind"] == "pull":
            return parse_github_pr(raw, self_logins)
        return parse_github_issue(raw, self_logins)
    if item["forge"] == "gitlab":
        return parse_gitlab(fetch_gitlab(item, run), self_logins)
    if jira_cli is None:
        raise RuntimeError(
            "no jira-issue.py found — install the jira-communication skill"
            " or pass --jira-cli"
        )
    return parse_jira(fetch_jira(item["key"], jira_cli, run), self_logins, jira_browse)


def links_of(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """The issues and tickets one artefact links to, as queue items."""
    found = [
        dict(linked, origin="linked")
        for url in parsed["linked"]
        for linked in scope.artefacts_in_text(url)
    ]
    return found + [ticket_item(key, "linked") for key in parsed["tickets"]]


def collect(
    items: list[dict[str, Any]],
    since: datetime | None,
    run: Runner = default_runner,
    self_logins: set[str] | None = None,
    jira_cli: Path | None = None,
    jira_browse: str = "",
) -> dict[str, Any]:
    """Read every artefact, follow its links once, and gather the findings."""
    self_logins = set(self_logins or ())
    queue = list(items)
    seen: set[str] = set()
    artefacts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    earlier = 0

    while queue:
        item = queue.pop(0)
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        record = {k: item.get(k) for k in ("url", "forge", "kind", "origin")}
        try:
            parsed = read_one(item, run, self_logins, jira_cli, jira_browse)
        except (RuntimeError, LookupError, ValueError, OSError) as exc:
            artefacts.append({**record, "fetched": False, "error": str(exc)})
            continue
        kept, skipped = _split_by_since(parsed.pop("findings"), since)
        earlier += skipped
        findings += kept
        artefacts.append(
            {
                **record,
                **parsed,
                "fetched": True,
                "findings": len(kept),
                "before_since": skipped,
            }
        )
        # Follow links one level: the issue a PR closes, the ticket its branch
        # names. What those link to in turn is not this session's work.
        if item.get("origin") != "linked":
            queue += links_of(parsed)

    return {
        "since": since.isoformat() if since else None,
        "artefacts": artefacts,
        "findings": findings,
        "findings_before_since": earlier,
    }


def items_from_scope(
    data: dict[str, Any], include_mentioned: bool
) -> list[dict[str, Any]]:
    items = [
        a for a in data["artefacts"] if include_mentioned or a["origin"] != "mentioned"
    ]
    items += [ticket_item(k, "acted") for k in data["tickets"]]
    return items


# --------------------------------------------------------------------------
# rendering


TEXT_BODY_LIMIT = 400
TEXT_REPORT_LIMIT = 160


def plain(body: str) -> str:
    """Body text without HTML comments, tags, images and link targets."""
    text = re.sub(r"<!--.*?-->", " ", body, flags=re.DOTALL)
    text = re.sub(r"<details>.*?</details>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return " ".join(text.split())


def _tally(result: dict[str, Any], mentioned_skipped: int) -> list[str]:
    arts = result["artefacts"]
    read = [a for a in arts if a["fetched"]]
    silent = sum(1 for a in read if a["findings"] == 0)
    by_class: dict[str, int] = {}
    for f in result["findings"]:
        by_class[f["author_class"]] = by_class.get(f["author_class"], 0) + 1
    classes = ", ".join(f"{v} {k}" for k, v in sorted(by_class.items()))
    line = (
        f"{len(arts)} artefacts: {len(read)} read ({silent} with no finding),"
        f" {len(arts) - len(read)} could not be read · {len(result['findings'])} findings"
    )
    if classes:
        line += f" ({classes})"
    if result["since"]:
        line += f" · since {result['since']}"
    lines = [line]
    if result["findings_before_since"]:
        lines.append(
            f"{result['findings_before_since']} comments predate --since and are not listed."
        )
    if mentioned_skipped:
        lines.append(
            f"{mentioned_skipped} artefacts only mentioned in the transcript were not read"
            " (--include-mentioned reads them)."
        )
    lines += [f"NOT READ  {a['url']}: {a['error']}" for a in arts if not a["fetched"]]
    lines += [
        f"TRUNCATED {a['url']}: {', '.join(a['truncated'])} held more than one page"
        for a in read
        if a.get("truncated")
    ]
    return lines


def _where(f: dict[str, Any]) -> str:
    if not f.get("path"):
        return ""
    return f" {f['path']}" + (f":{f['line']}" if f.get("line") else "")


def _flags(f: dict[str, Any]) -> str:
    flags = []
    if f.get("resolved") is not None:
        flags.append("resolved" if f["resolved"] else "open")
    if f.get("commit_after"):
        flags.append(f"commit after: {f['commit_after'][:8]}")
    if f.get("last_self_reply"):
        flags.append("answered")
    return f" ({', '.join(flags)})" if flags else ""


def _clip(text: str, limit: int, marker: str) -> str:
    return text[:limit] + (marker if len(text) > limit else "")


def _render_artefact(a: dict[str, Any], own: list[dict[str, Any]]) -> list[str]:
    lines = [
        "",
        f"== {a['url']} ({a['origin']}, {a.get('state')}) — {a.get('title') or ''}",
    ]
    for f in (f for f in own if not f["report"]):
        lines.append(
            f"- [{f['source']} · {f['author_class']} {f['author']}{_where(f)}]{_flags(f)}"
        )
        lines.append(
            "  " + _clip(plain(f["body"]), TEXT_BODY_LIMIT, " …[trimmed; json has all]")
        )
    lines += [
        f"  report · {f['author']}: " + _clip(plain(f["body"]), TEXT_REPORT_LIMIT, " …")
        for f in own
        if f["report"]
    ]
    return lines


def render_text(result: dict[str, Any], mentioned_skipped: int = 0) -> str:
    lines = _tally(result, mentioned_skipped)
    for a in result["artefacts"]:
        own = [f for f in result["findings"] if f["artefact"] == a["url"]]
        if a["fetched"] and own:
            lines += _render_artefact(a, own)
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--transcript-file", type=Path)
    parser.add_argument(
        "--ref", action="append", default=[], help="PR/MR/issue URL or Jira key"
    )
    parser.add_argument(
        "--since", help="ISO time; default: the transcript's first timestamp"
    )
    parser.add_argument("--include-mentioned", action="store_true")
    parser.add_argument("--self-login", action="append", default=[])
    parser.add_argument("--jira-cli", help="path to jira-communication's jira-issue.py")
    parser.add_argument(
        "--jira-browse",
        default=os.environ.get("JIRA_URL", ""),
        help="Jira base URL for ticket links (default: $JIRA_URL)",
    )
    parser.add_argument(
        "--gitlab-host", default=os.environ.get("GITLAB_HOST", "gitlab.com")
    )
    parser.add_argument("--output-format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv[1:])

    if not args.transcript_file and not args.ref:
        parser.error("give --transcript-file or at least one --ref")
    items: list[dict[str, Any]] = []
    mentioned_skipped = 0
    since = parse_time(args.since) if args.since else None
    if args.transcript_file:
        if not args.transcript_file.is_file():
            print(f"no such transcript: {args.transcript_file}", file=sys.stderr)
            return 2
        data = scope.collect_artefacts(args.transcript_file, args.gitlab_host)
        items = items_from_scope(data, args.include_mentioned)
        mentioned_skipped = (
            0
            if args.include_mentioned
            else sum(1 for a in data["artefacts"] if a["origin"] == "mentioned")
        )
        since = since or transcript_start(args.transcript_file)
    for ref in args.ref:
        item = parse_ref(ref)
        if item is None:
            print(f"not a PR/MR/issue URL or Jira key: {ref}", file=sys.stderr)
            return 2
        items.append(item)

    result = collect(
        items,
        since,
        self_logins=set(args.self_login),
        jira_cli=find_jira_cli(args.jira_cli),
        jira_browse=args.jira_browse,
    )
    if args.output_format == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render_text(result, mentioned_skipped))
    return 1 if any(not a["fetched"] for a in result["artefacts"]) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
