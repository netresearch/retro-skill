#!/usr/bin/env python3
"""Unit tests for collect-review-findings.py and the artefact detection in
derive-session-scope.py it builds on.

The GitHub fixture is a recorded GraphQL answer for netresearch/retro-skill#122
(bodies cut to 240 characters). The GitLab and Jira fixtures keep the recorded
shape of `glab api` and `jira-issue.py --json … --raw` with names and text
replaced, because the originals are internal.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import itertools
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "retro" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review-findings"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crf = _load("collect_review_findings", "collect-review-findings.py")
dss = _load("derive_session_scope", "derive-session-scope.py")


# Removed when the interpreter exits.
TMP = tempfile.TemporaryDirectory()
_COUNTER = itertools.count()


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _transcript(pairs: list[tuple[dict, str]], texts: list[str] = ()) -> Path:
    """A JSONL transcript: one tool_use + tool_result per (input, result) pair."""
    lines = [{"timestamp": "2026-09-20T09:36:50.553Z", "message": {"content": "start"}}]
    for i, (payload, result) in enumerate(pairs):
        name = payload.pop("__name", "Bash")
        lines.append(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"t{i}",
                            "name": name,
                            "input": payload,
                        }
                    ]
                },
            }
        )
        lines.append(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"t{i}",
                            "content": result,
                        }
                    ]
                },
            }
        )
    for text in texts:
        lines.append({"message": {"content": [{"type": "text", "text": text}]}})
    path = Path(TMP.name) / f"t{next(_COUNTER)}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


class SessionArtefactsTest(unittest.TestCase):
    def test_the_recorded_create_and_comment_pair_is_found(self):
        # Copied from the session that prompted #123 (t3x-nr-passkeys-be#152).
        create = (
            {
                "command": 'cd /home/cybot/projects/t3x-nr-passkeys-be/ci-e2e && gh pr create --repo netresearch/t3x-nr-passkeys-be --base main --head ci/e2e-workflow --title "ci: run the end-to-end suite in CI" --body-file /tmp/pr-e2e.md; echo "EXIT: $?"'
            },
            "https://github.com/netresearch/t3x-nr-passkeys-be/pull/152\nEXIT: 0",
        )
        comment = (
            {
                "command": 'gh pr comment 152 --repo netresearch/t3x-nr-passkeys-be --body-file /tmp/comment-152b.md; echo "EXIT: $?"'
            },
            "https://github.com/netresearch/t3x-nr-passkeys-be/pull/152#issuecomment-5749411350\nEXIT: 0",
        )
        data = dss.collect_artefacts(_transcript([create, comment]))
        self.assertEqual(
            [(a["url"], a["origin"]) for a in data["artefacts"]],
            [("https://github.com/netresearch/t3x-nr-passkeys-be/pull/152", "created")],
        )

    def test_create_takes_the_printed_url_not_one_from_its_body(self):
        cmd = 'gh pr create -R o/r --title t --body "follows https://github.com/o/r/pull/1"'
        data = dss.collect_artefacts(
            _transcript([({"command": cmd}, "https://github.com/o/r/pull/2")])
        )
        created = [a["url"] for a in data["artefacts"] if a["origin"] == "created"]
        self.assertEqual(created, ["https://github.com/o/r/pull/2"])

    def test_number_and_repo_flag_without_url(self):
        data = dss.collect_artefacts(
            _transcript([({"command": "gh pr edit 151 --repo o/r --add-label x"}, "")])
        )
        self.assertEqual(data["artefacts"][0]["url"], "https://github.com/o/r/pull/151")
        self.assertEqual(data["artefacts"][0]["origin"], "acted")

    def test_a_url_inside_the_body_is_not_the_target(self):
        cmd = (
            'gh pr comment 7 -R o/r --body "same as https://github.com/o/other/pull/9"'
        )
        data = dss.collect_artefacts(_transcript([({"command": cmd}, "")]))
        urls = {a["url"]: a["origin"] for a in data["artefacts"]}
        self.assertEqual(urls, {"https://github.com/o/r/pull/7": "acted"})

    def test_flag_value_is_not_the_number(self):
        self.assertIsNone(dss.positional_number("--limit 5 --json url"))
        self.assertEqual(dss.positional_number("--repo o/r 12"), 12)

    def test_read_only_and_placeholder_urls_are_only_mentioned(self):
        data = dss.collect_artefacts(
            _transcript(
                [({"command": "gh pr view 3 -R o/r"}, "https://github.com/o/r/pull/3")],
                texts=["see https://github.com/OWNER/REPO/pull/431"],
            )
        )
        self.assertEqual({a["origin"] for a in data["artefacts"]}, {"mentioned"})

    def test_gitlab_mr_nested_group(self):
        result = "https://git.example.org/group/sub/app/-/merge_requests/88\n"
        data = dss.collect_artefacts(
            _transcript([({"command": "glab mr create --fill --yes"}, result)])
        )
        item = data["artefacts"][0]
        self.assertEqual(
            (item["project"], item["kind"], item["origin"]),
            ("group/sub/app", "merge_request", "created"),
        )

    def test_edit_without_target_is_reported_unresolved(self):
        data = dss.collect_artefacts(
            _transcript([({"command": "gh pr edit --add-label x"}, "")])
        )
        self.assertEqual(data["artefacts"], [])
        self.assertEqual(len(data["unresolved_forge_commands"]), 1)

    def test_tickets_from_jira_scripts_and_bookings_not_standards(self):
        data = dss.collect_artefacts(
            _transcript(
                [
                    (
                        {
                            "command": 'python3 jira-comment.py add NRS-4763 "UTF-8, SHA-256"'
                        },
                        "",
                    ),
                    ({"__name": "mcp__tt__log_time", "ticket": "OPS-12"}, ""),
                    ({"command": "echo UTF-8 SHA-256 NRS-1 | wc"}, ""),
                ]
            )
        )
        self.assertEqual(data["tickets"], ["NRS-4763", "OPS-12"])


class AuthorClassTest(unittest.TestCase):
    def test_classes(self):
        me = {"CybotTM"}
        self.assertEqual(crf.author_class("CybotTM", "User", me), "self")
        self.assertEqual(crf.author_class("coderabbitai", "Bot", me), "bot")
        self.assertEqual(crf.author_class("renovate[bot]", None, me), "bot")
        self.assertEqual(crf.author_class("project_42_bot_3f9a1c", None, me), "bot")
        self.assertEqual(crf.author_class("team.lead", None, me), "human")
        self.assertEqual(crf.author_class("abbot", None, me), "human")
        self.assertEqual(crf.author_class(None, None, me), "human")


class GitHubParseTest(unittest.TestCase):
    def setUp(self):
        self.parsed = crf.parse_github_pr(
            _fixture("github-pr-retro-skill-122.json"), set()
        )

    def test_threads_carry_resolution_reply_and_fix_commit(self):
        threads = [f for f in self.parsed["findings"] if f["source"] == "review-thread"]
        self.assertEqual(len(threads), 3)
        self.assertTrue(
            all(t["resolved"] and t["author_class"] == "bot" for t in threads)
        )
        self.assertTrue(all(t["last_self_reply"] for t in threads))
        self.assertEqual(
            [t["commit_after"][:8] for t in threads],
            ["d4fc3406", "d4fc3406", "82e54205"],
        )

    def test_empty_envelopes_and_own_comments_are_not_findings(self):
        reviews = [f for f in self.parsed["findings"] if f["source"] == "review"]
        # 9 reviews: 3 own and 3 bot ones are empty envelopes of inline
        # threads; 3 bot reviews carry a body. Self: the own reply in each of
        # the 3 threads, and the one own PR comment.
        self.assertEqual(len(reviews), 3)
        self.assertEqual(self.parsed["self_comments"], 4)
        # A bot review body can carry findings outside the diff: not a report.
        self.assertFalse(any(f["report"] for f in reviews))

    def test_viewer_login_counts_as_self_without_a_flag(self):
        self.assertNotIn("CybotTM", {f["author"] for f in self.parsed["findings"]})

    def test_bot_auto_approval_is_dropped(self):
        raw = _fixture("github-pr-retro-skill-122.json")
        reviews = raw["data"]["repository"]["pullRequest"]["reviews"]["nodes"]
        reviews.append(
            {"state": "APPROVED", "body": "Auto-approved", "submittedAt": "2026-09-22T06:00:00Z",
             "url": None, "author": {"login": "github-actions", "__typename": "Bot"}}
        )  # fmt: skip
        reviews.append(
            {"state": "APPROVED", "body": "", "submittedAt": "2026-09-22T06:00:00Z",
             "url": None, "author": {"login": "team.lead", "__typename": "User"}}
        )  # fmt: skip
        parsed = crf.parse_github_pr(raw, set())
        verdicts = [f for f in parsed["findings"] if f.get("state") == "APPROVED"]
        self.assertEqual([f["author"] for f in verdicts], ["team.lead"])
        self.assertFalse(verdicts[0]["report"])

    def test_missing_pr_is_an_error_not_an_empty_list(self):
        with self.assertRaises(LookupError):
            crf.parse_github_pr(
                {"errors": [{"message": "Could not resolve"}], "data": None}, set()
            )


class IssueKeywordTest(unittest.TestCase):
    def test_closes_keyword_resolves_on_github(self):
        self.assertEqual(
            crf._issue_urls_in("Closes #5", "https://github.com/o/r/pull/7"),
            ["https://github.com/o/r/issues/5"],
        )

    def test_github_in_a_foreign_path_is_not_github(self):
        own = "https://git.example.org/github.com/r/-/merge_requests/7"
        self.assertEqual(crf._issue_urls_in("Closes #5", own), [])


class GitLabParseTest(unittest.TestCase):
    def setUp(self):
        self.parsed = crf.parse_gitlab(_fixture("gitlab-mr.json"), set())
        self.by_body = {f["body"][:20]: f for f in self.parsed["findings"]}

    def test_sources_and_classes(self):
        self.assertEqual(
            sorted((f["source"], f["author_class"]) for f in self.parsed["findings"]),
            [
                ("mr-comment", "bot"),
                ("mr-comment", "human"),
                ("review-thread", "human"),
            ],
        )
        # The own note and the own reply in the thread; the system note is not counted.
        self.assertEqual(self.parsed["self_comments"], 2)

    def test_thread_resolution_position_and_fix_commit(self):
        thread = self.by_body["The variable check r"]
        self.assertEqual(
            (thread["path"], thread["line"], thread["resolved"]),
            ("ci/deploy.yml", 41, True),
        )
        # Opened 14:02; 5b1e2c0 was committed at 14:25, a1b2c3d at 12:30.
        self.assertEqual(
            thread["commit_after"], "5b1e2c0d9f8e7a6b5c4d3e2f1a0b9c8d7e6f5a4b"
        )

    def test_links_and_tickets(self):
        self.assertEqual(
            self.parsed["linked"],
            [
                "https://git.example.org/group/app/-/issues/12",
                "https://git.example.org/group/app/-/issues/13",
            ],
        )
        self.assertEqual(self.parsed["tickets"], ["OPS-901"])


class JiraParseTest(unittest.TestCase):
    def setUp(self):
        self.parsed = crf.parse_jira(_fixture("jira-ticket.json"), set(), "")

    def test_foreign_comments_and_status_changes(self):
        self.assertEqual(
            [(f["source"], f["author"]) for f in self.parsed["findings"]],
            [
                ("ticket-comment", "team.lead"),
                ("ticket-comment", "colleague"),
                ("ticket-transition", "team.lead"),
            ],
        )
        self.assertEqual(self.parsed["findings"][-1]["body"], "QA → In Progress")
        self.assertEqual(self.parsed["self_comments"], 1)

    def test_link_from_the_api_self_url(self):
        self.assertEqual(self.parsed["url"], "https://jira.example.org/browse/OPS-901")

    def test_more_comments_than_returned_is_named(self):
        raw = _fixture("jira-ticket.json")
        raw["issue"]["fields"]["comment"]["total"] = 50
        self.assertEqual(crf.parse_jira(raw, set(), "")["truncated"], ["comments"])


class CollectTest(unittest.TestCase):
    """The orchestration with a recorded runner: no network."""

    def runner(self, command):
        if command[:3] == ["gh", "api", "graphql"]:
            if "number=122" in command:
                return _fixture("github-pr-retro-skill-122.json")
            raise RuntimeError("HTTP 404: Could not resolve to a Repository")
        raise AssertionError(f"unexpected command {command}")

    def test_failure_is_listed_apart_from_silence(self):
        items = [
            dss.artefact("github.com", "netresearch/retro-skill", "pull", 122)
            | {"origin": "created"},
            dss.artefact("github.com", "OWNER/REPO", "pull", 431)
            | {"origin": "mentioned"},
        ]
        result = crf.collect(items, None, run=self.runner)
        state = {a["url"]: a["fetched"] for a in result["artefacts"]}
        self.assertEqual(
            state,
            {
                "https://github.com/netresearch/retro-skill/pull/122": True,
                "https://github.com/OWNER/REPO/pull/431": False,
            },
        )
        failed = next(a for a in result["artefacts"] if not a["fetched"])
        self.assertIn("404", failed["error"])

    def test_since_counts_what_it_hides(self):
        items = [
            dss.artefact("github.com", "netresearch/retro-skill", "pull", 122)
            | {"origin": "created"}
        ]
        late = datetime(2026, 9, 22, 5, 0, tzinfo=timezone.utc)
        result = crf.collect(items, late, run=self.runner)
        everything = crf.collect(items, None, run=self.runner)
        self.assertGreater(result["findings_before_since"], 0)
        self.assertEqual(
            len(result["findings"]) + result["findings_before_since"],
            len(everything["findings"]),
        )

    def test_links_are_followed_one_level(self):
        raw = _fixture("gitlab-mr.json")

        def runner(command):
            endpoint = command[3] if command[2] == "--paginate" else command[2]
            if endpoint == "user":
                return raw["self"]
            if "/issues/" in endpoint:
                if endpoint.endswith("discussions?per_page=100"):
                    return []
                # The linked issue links back to an MR: followed no further.
                return {
                    **raw["item"],
                    "web_url": "https://git.example.org/group/app/-/issues/"
                    + endpoint.rsplit("/", 1)[1],
                    "description": "https://git.example.org/group/app/-/merge_requests/99",
                    "title": "NRS-1 unrelated",
                }
            if endpoint.endswith("discussions?per_page=100"):
                return raw["notes"]
            if endpoint.endswith("commits?per_page=100"):
                return raw["commits"]
            if "/closes_issues" in endpoint:
                return raw["closes"]
            return raw["item"]

        item = dss.artefact("git.example.org", "group/app", "merge_requests", 88) | {
            "origin": "created"
        }
        result = crf.collect(
            [item], None, run=runner, jira_cli=None, gitlab_hosts=("git.example.org",)
        )
        origins = sorted((a["origin"], a["url"]) for a in result["artefacts"])
        self.assertEqual(
            origins,
            [
                ("created", "https://git.example.org/group/app/-/merge_requests/88"),
                ("linked", "OPS-901"),
                ("linked", "https://git.example.org/group/app/-/issues/12"),
                ("linked", "https://git.example.org/group/app/-/issues/13"),
            ],
        )
        jira = next(a for a in result["artefacts"] if a["url"] == "OPS-901")
        self.assertFalse(jira["fetched"])
        self.assertIn("jira-issue.py", jira["error"])


class ReviewFixesArtefactTest(unittest.TestCase):
    """Inputs from the independent review of eb232d8 that produced a wrong target."""

    def urls(self, pairs, **kw):
        data = dss.collect_artefacts(_transcript(pairs), **kw)
        return {a["url"]: a["origin"] for a in data["artefacts"]}, data

    def test_a_number_inside_the_body_is_not_the_pr(self):
        urls, data = self.urls(
            [({"command": 'gh pr comment -R o/r --body "fixed 12 nits"'}, "")]
        )
        self.assertEqual(urls, {})
        self.assertEqual(len(data["unresolved_forge_commands"]), 1)

    def test_a_boolean_flag_does_not_hide_the_number(self):
        urls, _ = self.urls([({"command": "gh pr merge --merge 12 -R o/r"}, "")])
        self.assertEqual(urls, {"https://github.com/o/r/pull/12": "acted"})

    def test_create_keeps_only_its_own_url(self):
        cmd = "gh pr create -R o/r --fill && gh pr view 1 -R x/y --comments"
        result = "https://github.com/o/r/pull/2\nsee https://github.com/x/y/issues/4"
        urls, _ = self.urls([({"command": cmd}, result)])
        self.assertEqual(urls["https://github.com/o/r/pull/2"], "created")
        self.assertEqual(urls["https://github.com/x/y/issues/4"], "mentioned")

    def test_mcp_write_takes_its_input_not_an_echoed_link(self):
        payload = {
            "__name": "mcp__github__add_issue_comment",
            "owner": "o",
            "repo": "r",
            "issue_number": 5,
        }
        urls, _ = self.urls(
            [(payload, '{"body": "see https://github.com/z/z/issues/77"}')]
        )
        self.assertEqual(urls["https://github.com/o/r/issues/5"], "acted")
        self.assertEqual(urls["https://github.com/z/z/issues/77"], "mentioned")

    def test_commands_in_heredocs_and_quotes_are_text(self):
        doc = "cat > /tmp/doc.md <<'EOF'\nRun gh pr merge 3 -R someone/else\nEOF"
        echo = 'echo "gh pr merge 4 -R someone/else"'
        urls, _ = self.urls([({"command": doc}, ""), ({"command": echo}, "")])
        self.assertEqual(urls, {})

    def test_rest_writes_through_gh_api_and_glab_api(self):
        pairs = [
            ({"command": "gh api -X POST repos/o/r/issues/9/comments -f body=x"}, ""),
            ({"command": "gh api repos/o/r/pulls/8"}, ""),  # a read
            (
                {
                    "command": 'glab api --method POST "projects/group%2Fapp/merge_requests/4/notes"'
                    " --hostname git.example.org -f body=x"
                },
                "",
            ),
        ]
        urls, _ = self.urls(pairs)
        self.assertEqual(
            urls,
            {
                "https://github.com/o/r/issues/9": "acted",
                "https://git.example.org/group/app/-/merge_requests/4": "acted",
            },
        )

    def test_jira_key_inside_the_comment_text_is_not_the_ticket(self):
        self.assertEqual(
            dss.jira_command_tickets('uv run jira-comment.py add NRS-1 "see ABC-2"'),
            {"NRS-1"},
        )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class RemoteResolutionTest(unittest.TestCase):
    def repo(self, remotes: dict[str, str]) -> Path:
        path = Path(TMP.name) / f"repo{next(_COUNTER)}"
        path.mkdir()
        _git("init", "-q", cwd=path)
        for name, url in remotes.items():
            _git("remote", "add", name, url, cwd=path)
        return path

    def test_credentials_are_dropped_from_the_remote(self):
        path = self.repo(
            {
                "origin": "https://gitlab-ci-token:glpat-SECRET@git.example.org/group/app.git"
            }
        )
        self.assertEqual(
            dss.remote_project(str(path), "glab"), ("git.example.org", "group/app")
        )

    def test_gh_prefers_upstream_in_a_fork(self):
        path = self.repo(
            {
                "origin": "git@github.com:me/fork.git",
                "upstream": "https://github.com/org/proj.git",
            }
        )
        self.assertEqual(
            dss.remote_project(str(path), "gh"), ("github.com", "org/proj")
        )
        self.assertEqual(
            dss.remote_project(str(path), "glab"), ("github.com", "me/fork")
        )

    def test_gh_set_default_wins(self):
        path = self.repo(
            {
                "origin": "git@github.com:me/fork.git",
                "upstream": "https://github.com/org/proj.git",
            }
        )
        _git("config", "remote.origin.gh-resolved", "base", cwd=path)
        self.assertEqual(dss.remote_project(str(path), "gh"), ("github.com", "me/fork"))

    def test_the_last_cd_decides(self):
        first = self.repo({"origin": "git@github.com:a/first.git"})
        second = self.repo({"origin": "git@github.com:b/second.git"})
        cmd = f"cd {first} && git fetch && cd {second} && gh pr edit 5 --add-label x"
        data = dss.collect_artefacts(_transcript([({"command": cmd}, "")]))
        self.assertEqual(
            [a["url"] for a in data["artefacts"]],
            ["https://github.com/b/second/pull/5"],
        )

    def test_a_relative_cd_is_unresolved(self):
        # A real repository, named relative to this process's cwd: the session's
        # cwd is unknown, so resolving it here would name a different checkout.
        path = self.repo({"origin": "git@github.com:a/here.git"})
        with contextlib.chdir(path.parent):
            self.assertIsNone(dss.remote_project(path.name))


def _pr(threads=(), reviews=(), commits_total=None):
    commits = [
        {
            "commit": {
                "oid": "c1",
                "committedDate": "2026-09-21T12:00:00Z",
                "messageHeadline": "x",
            }
        }
    ]
    return {
        "data": {
            "viewer": {"login": "me"},
            "repository": {
                "pullRequest": {
                    "url": "https://github.com/o/r/pull/1",
                    "title": "t",
                    "headRefName": "b",
                    "reviewThreads": {
                        "totalCount": len(threads),
                        "nodes": list(threads),
                    },
                    "reviews": {"totalCount": len(reviews), "nodes": list(reviews)},
                    "comments": {"totalCount": 0, "nodes": []},
                    "commits": {"totalCount": commits_total or 1, "nodes": commits},
                    "closingIssuesReferences": {"totalCount": 0, "nodes": []},
                }
            },
        }
    }


def _comment(login, typename, when, body):
    return {
        "author": {"login": login, "__typename": typename},
        "createdAt": when,
        "body": body,
        "url": f"u-{when}",
    }


class ReviewFixesParseTest(unittest.TestCase):
    def test_a_human_reply_in_a_bot_thread_is_its_own_finding(self):
        thread = {
            "path": "a.py",
            "line": 3,
            "isResolved": True,
            "comments": {
                "totalCount": 3,
                "nodes": [
                    _comment("coderabbitai", "Bot", "2026-09-20T10:00:00Z", "fix this"),
                    _comment("me", "User", "2026-09-20T10:05:00Z", "won't fix"),
                    _comment(
                        "team.lead", "User", "2026-09-21T11:00:00Z", "please do fix it"
                    ),
                ],
            },
        }
        found = crf.parse_github_pr(_pr(threads=[thread]), set())["findings"]
        reply = next(f for f in found if f["source"] == "review-reply")
        self.assertEqual(
            (reply["author"], reply["author_class"], reply["path"]),
            ("team.lead", "human", "a.py"),
        )

    def test_since_keeps_a_thread_answered_later(self):
        thread = {
            "comments": {
                "totalCount": 2,
                "nodes": [
                    _comment("coderabbitai", "Bot", "2026-09-20T10:00:00Z", "fix this"),
                    _comment("team.lead", "User", "2026-09-21T11:00:00Z", "agreed"),
                ],
            }
        }
        found = crf.parse_github_pr(_pr(threads=[thread]), set())["findings"]
        kept, hidden = crf._split_by_since(
            found, datetime(2026, 9, 21, tzinfo=timezone.utc)
        )
        self.assertEqual(
            ({f["source"] for f in kept}, hidden),
            ({"review-thread", "review-reply"}, 0),
        )

    def test_an_own_thread_with_only_own_replies_is_not_listed(self):
        thread = {
            "comments": {
                "totalCount": 2,
                "nodes": [
                    _comment("me", "User", "2026-09-20T10:00:00Z", "note"),
                    _comment("Me", "User", "2026-09-20T10:01:00Z", "note 2"),
                ],
            }
        }
        parsed = crf.parse_github_pr(_pr(threads=[thread]), set())
        self.assertEqual((parsed["findings"], parsed["self_comments"]), ([], 2))

    def test_dismissed_bot_review_with_a_body_is_kept_approval_is_not(self):
        reviews = [
            {"state": "DISMISSED", "body": "SQL injection in x.php", "submittedAt": "2026-09-20T10:00:00Z", "author": {"login": "sonarqubecloud", "__typename": "Bot"}},
            {"state": "DISMISSED", "body": "", "submittedAt": "2026-09-20T10:00:00Z", "author": {"login": "sonarqubecloud", "__typename": "Bot"}},
            {"state": "APPROVED", "body": "Auto-approved", "submittedAt": "2026-09-20T10:00:00Z", "author": {"login": "github-actions", "__typename": "Bot"}},
        ]  # fmt: skip
        found = crf.parse_github_pr(_pr(reviews=reviews), set())["findings"]
        self.assertEqual([f["body"] for f in found], ["SQL injection in x.php"])

    def test_more_commits_than_read_is_named(self):
        self.assertIn(
            "commits", crf.parse_github_pr(_pr(commits_total=150), set())["truncated"]
        )

    def test_details_text_survives_plain(self):
        body = "<details><summary>Outside diff (1)</summary>Qualify the grep -r rule</details>"
        self.assertIn("Qualify the grep -r rule", crf.plain(body))

    def test_tickets_only_from_title_prefix_and_branch_segment(self):
        self.assertEqual(
            crf.tickets_named("ci: test PHP-8.4 and TYPO3-14", "ci/matrix"), []
        )
        self.assertEqual(
            crf.tickets_named("[NRS-12] x", "feature/OPS-3-y"), ["NRS-12", "OPS-3"]
        )
        # The recorded MR whose feedback sat only in the ticket.
        title = (
            "Draft: OPS-901: ci: resolve every pipeline variable before set-pipeline"
        )
        self.assertEqual(
            crf.tickets_named(title, "ops-901-pipeline-var-check"), ["OPS-901"]
        )

    def test_jira_cloud_accounts_and_error_bodies(self):
        raw = {
            "self": {"accountId": "acc-me"},
            "issue": {
                "key": "OPS-1",
                "self": "https://x.atlassian.net/rest/api/2/issue/1",
                "fields": {
                    "comment": {
                        "total": 2,
                        "comments": [
                            {"author": {"accountId": "acc-me"}, "created": "2026-09-20T10:00:00.000+0000", "body": "mine"},
                            {"author": {"accountId": "acc-lead"}, "created": "2026-09-20T11:00:00.000+0000", "body": "theirs"},
                        ],
                    }
                },
            },
        }  # fmt: skip
        parsed = crf.parse_jira(raw, set(), "")
        self.assertEqual(
            ([f["body"] for f in parsed["findings"]], parsed["self_comments"]),
            (["theirs"], 1),
        )
        with self.assertRaisesRegex(LookupError, "Issue does not exist"):
            crf.parse_jira(
                {"issue": {"errorMessages": ["Issue does not exist"]}}, set(), ""
            )


class ReviewFixesCollectTest(unittest.TestCase):
    item = dss.artefact("github.com", "o/r", "pull", 1) | {"origin": "created"}

    def test_a_timeout_is_one_unread_artefact_not_a_crash(self):
        def runner(command):
            raise subprocess.TimeoutExpired(command, 120)

        result = crf.collect([self.item], None, run=runner)
        self.assertEqual([a["fetched"] for a in result["artefacts"]], [False])
        self.assertIn("TimeoutExpired", result["artefacts"][0]["error"])

    def test_a_list_where_an_object_belongs_is_unread(self):
        result = crf.collect([self.item], None, run=lambda command: [])
        self.assertFalse(result["artefacts"][0]["fetched"])
        self.assertIn("expected a JSON object", result["artefacts"][0]["error"])

    def test_empty_output_is_an_error(self):
        with self.assertRaises(RuntimeError):
            crf._decode_stream("  \n")

    def test_default_runner_turns_a_timeout_into_an_error(self):
        timeout = subprocess.TimeoutExpired(["gh"], 120)
        with (
            mock.patch.object(crf.subprocess, "run", side_effect=timeout),
            self.assertRaisesRegex(RuntimeError, "timed out"),
        ):
            crf.default_runner(["gh", "api"])

    def test_a_foreign_gitlab_host_is_not_contacted(self):
        calls = []
        item = dss.artefact("evil.example", "g/p", "issues", 1) | {"origin": "linked"}
        result = crf.collect(
            [item], None, run=calls.append, gitlab_hosts=("git.example.org",)
        )
        self.assertEqual(calls, [])
        self.assertIn("not allowed", result["artefacts"][0]["error"])

    def test_an_issue_number_that_is_a_pr_is_read_as_one(self):
        def runner(command):
            if any("issue(number" in part for part in command):
                return {
                    "data": {"viewer": {"login": "me"}, "repository": {"issue": None}}
                }
            return _pr()

        item = dss.artefact("github.com", "o/r", "issues", 1) | {"origin": "acted"}
        result = crf.collect([item], None, run=runner)
        self.assertTrue(result["artefacts"][0]["fetched"])


class MainTest(unittest.TestCase):
    def test_an_unparsable_since_is_an_error(self):
        with (
            self.assertRaises(SystemExit) as caught,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            crf.main(["x", "--ref", "NRS-1", "--since", "21.09.2026"])
        self.assertEqual(caught.exception.code, 2)


class DecodeTest(unittest.TestCase):
    def test_paginated_arrays(self):
        self.assertEqual(crf._decode_stream("[1,2]\n[3]"), [[1, 2], [3]])
        self.assertEqual(crf._flatten([[1, 2], [3]]), [1, 2, 3])
        self.assertEqual(crf._decode_stream('{"a": 1}'), {"a": 1})

    def test_jira_offset_without_colon(self):
        self.assertEqual(
            crf.parse_time("2026-09-17T09:15:11.286+0000"),
            datetime(2026, 9, 17, 9, 15, 11, 286000, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
