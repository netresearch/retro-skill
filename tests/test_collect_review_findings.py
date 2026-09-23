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
        error = payload.pop("__error", False)
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
                            "is_error": error,
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
                        "✓ Comment added to NRS-4763",
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
        # Copilot saying it could not review (quota) is one.
        self.assertEqual(
            [f["author"] for f in reviews if f["report"]],
            ["copilot-pull-request-reviewer"],
        )

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

    def test_a_silent_write_with_the_number_after_a_flag_is_unresolved(self):
        # Only `<verb> <number>` is read without output; anything else is not guessed.
        urls, data = self.urls([({"command": "gh pr merge --merge 12 -R o/r"}, "")])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 1))

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
            dss.jira_command_tickets(
                'uv run jira-comment.py add NRS-1 "see ABC-2"',
                "added to NRS-1, see ABC-2",
            ),
            {"NRS-1"},
        )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


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
                # What gh prints, with exit 1, for a PR number asked as an issue.
                raise RuntimeError(
                    "gh: Could not resolve to an Issue with the number of 1."
                )
            return _pr()

        item = dss.artefact("github.com", "o/r", "issues", 1) | {"origin": "acted"}
        result = crf.collect([item], None, run=runner)
        self.assertTrue(result["artefacts"][0]["fetched"])


class SecondRoundTest(unittest.TestCase):
    """Inputs from the second review round (4243db7)."""

    def urls(self, pairs):
        data = dss.collect_artefacts(_transcript(pairs))
        return {a["url"]: a["origin"] for a in data["artefacts"]}, data

    def repo(self, origin: str) -> Path:
        path = Path(TMP.name) / f"r2repo{next(_COUNTER)}"
        path.mkdir()
        _git("init", "-q", cwd=path)
        _git("remote", "add", "origin", origin, cwd=path)
        return path

    def test_a_quoted_repo_flag_wins_over_the_cd(self):
        wrong = self.repo("git@github.com:wrong/repo.git")
        urls, _ = self.urls(
            [({"command": f'cd {wrong} && gh pr merge 5 -R "o/r" --merge'}, "")]
        )
        self.assertEqual(urls, {"https://github.com/o/r/pull/5": "acted"})

    def test_a_cd_inside_a_quoted_string_is_text(self):
        wrong = self.repo("git@github.com:wrong/repo.git")
        cmd = f'git commit -m "note; cd {wrong} " && gh pr merge 5 --merge'
        urls, data = self.urls([({"command": cmd}, "")])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 1))

    def test_an_explicit_get_with_fields_is_a_read(self):
        urls, _ = self.urls(
            [
                (
                    {
                        "command": "gh api -X GET repos/o/r/issues/9/comments -f per_page=100"
                    },
                    "",
                ),
                # CodeRabbit on cbccd69: the GET after the fields.
                (
                    {
                        "command": "gh api repos/o/r/issues/8/comments -f per_page=100 -X GET"
                    },
                    "",
                ),
                (
                    {"command": "gh api repos/o/r/issues/7 -F per_page=1 --method GET"},
                    "",
                ),
            ]
        )
        self.assertEqual(urls, {})

    def test_a_value_flag_before_the_number_is_not_guessed(self):
        cmd = 'gh pr close -c "5" 10 -R o/r'
        urls, data = self.urls([({"command": cmd}, "")])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 1))
        urls, _ = self.urls([({"command": cmd}, "✓ Closed pull request o/r#10")])
        self.assertEqual(urls, {"https://github.com/o/r/pull/10": "acted"})

    def test_more_heredoc_forms_are_text(self):
        body = "Run gh pr merge 3 -R x/y"
        pairs = [
            ({"command": f"cat > a.md <<'PR-BODY'\n{body}\nPR-BODY"}, ""),
            ({"command": f"cat > b.md <<\\EOF\n{body}\nEOF"}, ""),
            ({"command": f"cat > c.md <<EOF\n{body}\n"}, ""),  # never closed
        ]
        urls, _ = self.urls(pairs)
        self.assertEqual(urls, {})

    def test_create_inside_a_command_substitution_counts(self):
        cmd = 'PR_URL="$(gh pr create --repo o/r --fill)"; echo "$PR_URL"'
        urls, _ = self.urls([({"command": cmd}, "https://github.com/o/r/pull/3")])
        self.assertEqual(urls, {"https://github.com/o/r/pull/3": "created"})

    def test_a_quoted_jira_script_path_is_found(self):
        self.assertEqual(
            dss.jira_command_tickets(
                'uv run "$HOME/x/jira-issue.py" get NRS-5', "NRS-5: x"
            ),
            {"NRS-5"},
        )

    def test_owner_and_name_are_passed_as_strings(self):
        seen = []
        crf.fetch_github(
            {"project": "gabrielecirulli/2048", "kind": "pull", "number": 1},
            seen.append,
        )
        command = seen[0]
        self.assertEqual(command[command.index("name=2048") - 1], "-f")

    def test_a_dismissed_bot_approval_is_dropped(self):
        pr = _pr(
            reviews=[
                {"state": "DISMISSED", "body": "Automated approval for maintainer PR", "url": "rv1",
                 "submittedAt": "2026-09-20T10:00:00Z", "author": {"login": "github-actions", "__typename": "Bot"}},
            ]
        )  # fmt: skip
        node = pr["data"]["repository"]["pullRequest"]
        node["timelineItems"] = {
            "nodes": [{"previousReviewState": "APPROVED", "review": {"url": "rv1"}}]
        }
        self.assertEqual(crf.parse_github_pr(pr, set())["findings"], [])

    def test_the_opening_bots_follow_up_is_not_feedback(self):
        thread = {
            "comments": {
                "totalCount": 3,
                "nodes": [
                    _comment("coderabbitai", "Bot", "2026-09-20T10:00:00Z", "fix this"),
                    _comment("me", "User", "2026-09-20T10:05:00Z", "fixed in abc"),
                    _comment(
                        "coderabbitai", "Bot", "2026-09-20T10:06:00Z", "confirmed"
                    ),
                ],
            }
        }
        found = crf.parse_github_pr(_pr(threads=[thread]), set())["findings"]
        self.assertEqual([f["source"] for f in found], ["review-thread"])

    def test_a_refusal_is_a_report_a_long_review_is_not(self):
        refusal = crf.finding(
            "u",
            "review",
            "copilot",
            "bot",
            None,
            "Copilot was unable to review this pull request because the user reached their quota limit.",
        )
        long_one = crf.finding(
            "u",
            "review",
            "coderabbitai",
            "bot",
            None,
            "Actionable comments posted: 2. " + "x" * 700 + " rate limit",
        )
        self.assertEqual((refusal["report"], long_one["report"]), (True, False))  # fmt: skip

    def test_a_ticket_jira_does_not_know_is_absent_not_unread(self):
        def runner(command):
            raise RuntimeError("✗ Failed to get issue TYPO3-14: Issue Does Not Exist")

        item = crf.ticket_item("TYPO3-14", "linked")
        result = crf.collect([item], None, run=runner, jira_cli=Path(__file__))
        self.assertTrue(result["artefacts"][0]["absent"])
        text = crf.render_text(result)
        self.assertIn("NO SUCH   TYPO3-14", text)
        self.assertNotIn("NOT READ", text)

    def test_truncated_changelog_and_thread_comments_are_named(self):
        raw = _fixture("jira-ticket.json")
        raw["issue"]["changelog"]["total"] = 99
        self.assertIn("changelog", crf.parse_jira(raw, set(), "")["truncated"])
        thread = {
            "comments": {
                "totalCount": 150,
                "nodes": [_comment("x", "User", "2026-09-20T10:00:00Z", "a")],
            }
        }
        self.assertIn("reviewThreads.comments", crf.parse_github_pr(_pr(threads=[thread]), set())["truncated"])  # fmt: skip

    def test_the_installed_jira_plugin_is_found(self):
        home = Path(TMP.name) / f"home{next(_COUNTER)}"
        cli = (
            home
            / "cache/jira/3.32.0/skills/jira-communication/scripts/core/jira-issue.py"
        )
        cli.parent.mkdir(parents=True)
        cli.write_text("")
        index = home / ".claude/plugins/installed_plugins.json"
        index.parent.mkdir(parents=True)
        index.write_text(
            json.dumps(
                {
                    "plugins": {
                        "jira": [{"installPath": str(home / "cache/jira/3.32.0")}]
                    }
                }
            )
        )
        with (
            mock.patch.object(crf.Path, "home", return_value=home),
            mock.patch.object(crf, "JIRA_CLI_CANDIDATES", ()),
        ):
            self.assertEqual(crf.find_jira_cli(None), cli)  # fmt: skip

    def test_gitlab_host_with_a_scheme_is_compared_bare(self):
        self.assertEqual(
            crf.gitlab_hosts_from([], "https://git.example.org/"), ("git.example.org",)
        )


class CorroborationTest(unittest.TestCase):
    """A forge write counts when its output names the target (review round 3)."""

    def urls(self, pairs):
        data = dss.collect_artefacts(_transcript(pairs))
        return {a["url"]: a["origin"] for a in data["artefacts"]}, data

    def test_a_refused_call_ran_nothing(self):
        refused = "PreToolUse:Bash hook error: This body runs past five lines"
        urls, data = self.urls([({"command": "gh pr merge 3 -R o/r --merge"}, refused)])
        self.assertEqual((urls, data["unresolved_forge_commands"]), ({}, []))

    def test_a_failed_silent_call_is_not_guessed(self):
        failed = {"command": "gh pr merge 3 -R o/r --merge", "__error": True}
        urls, data = self.urls([(failed, "Exit code 1")])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 1))

    def test_a_graphql_query_is_a_read_a_mutation_a_write(self):
        query = "gh api graphql -F owner=o -F repo=r -f query='query{repository{id}}'"
        mutation = "gh api graphql -f query='mutation{addPullRequestReviewThreadReply(input:{}){comment{url}}}'"
        printed = "https://github.com/o/r/pull/7#discussion_r1"
        q_urls, _ = self.urls([({"command": query}, printed)])
        m_urls, _ = self.urls([({"command": mutation}, printed)])
        self.assertEqual(q_urls, {"https://github.com/o/r/pull/7": "mentioned"})
        self.assertEqual(m_urls, {"https://github.com/o/r/pull/7": "acted"})

    def test_a_gitlab_work_item_is_an_issue(self):
        printed = "- Creating issue in g/p https://git.example.org/g/p/-/work_items/4"
        urls, _ = self.urls([({"command": "glab issue create -R g/p -t x"}, printed)])
        self.assertEqual(urls, {"https://git.example.org/g/p/-/issues/4": "created"})

    def test_owner_repo_hash_number_in_the_output(self):
        printed = 'Pull request o/r#124 is marked as "ready for review"'
        urls, _ = self.urls([({"command": "gh pr ready 124 --repo o/r"}, printed)])
        self.assertEqual(urls, {"https://github.com/o/r/pull/124": "acted"})

    def test_a_bare_number_needs_the_writes_own_repo(self):
        merged = "✓ Merged pull request #9 (title)"
        own, _ = self.urls([({"command": "gh pr merge 9 -R o/r --merge"}, merged)])
        # The `-R` belongs to another command in the call, not to the merge.
        other = "gh pr merge 9 --merge; gh pr view 1 -R x/y"
        foreign, data = self.urls([({"command": other}, merged)])
        self.assertEqual(own, {"https://github.com/o/r/pull/9": "acted"})
        self.assertEqual((foreign, len(data["unresolved_forge_commands"])), ({}, 1))

    def test_links_in_running_text_are_not_what_a_write_did(self):
        # Round 4: a PR body read after the write, a JSON answer, an error line.
        cmd = "gh pr ready 113 --repo o/r && gh pr view 107 --repo o/r --json body"
        printed = (
            '✓ Pull request o/r#113 is marked as "ready for review"\n'
            '{"body":"Fixes https://github.com/o/r/issues/104"}'
        )
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls["https://github.com/o/r/pull/113"], "acted")
        self.assertEqual(urls["https://github.com/o/r/issues/104"], "mentioned")
        scanning = (
            "gh api -X PATCH repos/o/r/code-scanning/alerts/119 -f state=dismissed"
        )
        alert = '{"html_url": "https://github.com/ossf/scorecard/issues/1773"}'
        urls, data = self.urls([({"command": scanning}, alert)])
        self.assertEqual(
            urls, {"https://github.com/ossf/scorecard/issues/1773": "mentioned"}
        )
        self.assertEqual(data["unresolved_forge_commands"], [])

    def test_the_endpoint_beats_a_listing_printed_after_it(self):
        cmd = "gh api -X PUT repos/o/r/pulls/37/merge -f merge_method=merge; gh issue list -R o/r"
        urls, _ = self.urls([({"command": cmd}, "#33 open thing\n#28 other")])
        self.assertEqual(urls, {"https://github.com/o/r/pull/37": "acted"})

    def test_an_error_line_number_is_not_a_target(self):
        cmd = "glab mr merge 258 -R g/main --yes"
        out = "Exit code 1\nx #1: PUT https://git.example.org/api/v4/... 405"
        urls, _ = self.urls([({"command": cmd, "__error": True}, out)])
        self.assertEqual(urls, {})

    def test_a_silent_rest_write_is_named_by_its_endpoint(self):
        rest = "gh api -X PUT repos/o/r/pulls/5/merge -f merge_method=merge --silent"
        numeric = 'glab api "projects/3424/merge_requests/10/merge" --method PUT -f squash=false'
        urls, data = self.urls(
            [({"command": rest}, ""), ({"command": numeric}, "merged")]
        )
        self.assertEqual(urls, {"https://github.com/o/r/pull/5": "acted"})
        self.assertEqual(len(data["unresolved_forge_commands"]), 1)

    def test_a_jira_script_named_inside_a_commit_message_is_not_a_call(self):
        cmd = 'git commit -m "docs: jira-issue.py get NRS-9 example"'
        result = "[b 1a2b] docs: jira-issue.py get NRS-9"
        self.assertEqual(dss.jira_command_tickets(cmd, result), set())

    def test_a_create_beside_another_write(self):
        cmd = "gh pr create -R o/r --fill && gh pr comment 3 -R x/y --body hi"
        printed = "https://github.com/o/r/pull/2\nhttps://github.com/x/y/pull/3#issuecomment-1"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(
            urls,
            {
                "https://github.com/o/r/pull/2": "created",
                "https://github.com/x/y/pull/3": "acted",
            },
        )

    def test_a_refused_jira_call_quoting_its_key_names_no_ticket(self):
        cmd = "uv run jira-comment.py add NRS-9 -"
        refused = "PreToolUse:Bash hook error: [uv run jira-comment.py add NRS-9 -] lint failed"
        self.assertEqual(dss.jira_command_tickets(cmd, refused), set())

    def test_a_jira_call_that_failed_names_no_ticket(self):
        cmd = "uv run jira-comment.py add NRS-9 -"
        result = "Usage: jira-comment.py add [OPTIONS] ISSUE_KEY"
        self.assertEqual(dss.jira_command_tickets(cmd, result), set())


class ThirdRoundCollectorTest(unittest.TestCase):
    """Collector inputs from the third review round (dcf6bcf)."""

    def test_a_finding_about_limits_is_not_a_refusal(self):
        bodies = [
            "Consider adding a rate limit to this endpoint; it is unauthenticated.",
            "The quota limit check in line 42 is off by one.",
        ]
        reports = [
            crf.finding("u", "review", "b", "bot", None, b)["report"] for b in bodies
        ]
        self.assertEqual(reports, [False, False])
        copilot = (
            "Copilot was unable to review this pull request because the user who"
            " requested the review has reached their quota limit."
        )
        self.assertTrue(
            crf.finding("u", "review", "copilot", "bot", None, copilot)["report"]
        )

    def test_no_permission_is_a_read_failure_not_absent(self):
        def runner(command):
            raise RuntimeError(
                "Issue does not exist or you do not have permission to see it."
            )

        result = crf.collect(
            [crf.ticket_item("OPS-1", "linked")],
            None,
            run=runner,
            jira_cli=Path(__file__),
        )
        self.assertFalse(result["artefacts"][0]["absent"])

    def test_an_issue_read_as_the_pr_already_read_is_not_read_twice(self):
        def runner(command):
            if any("issue(number" in part for part in command):
                raise RuntimeError(
                    "gh: Could not resolve to an Issue with the number of 1."
                )
            return _pr()

        items = [
            dss.artefact("github.com", "o/r", "pull", 1) | {"origin": "created"},
            dss.artefact("github.com", "o/r", "issues", 1) | {"origin": "acted"},
        ]
        result = crf.collect(items, None, run=runner)
        self.assertEqual(
            [a["url"] for a in result["artefacts"]], ["https://github.com/o/r/pull/1"]
        )

    def test_a_malformed_plugin_index_does_not_end_the_run(self):
        home = Path(TMP.name) / f"home{next(_COUNTER)}"
        index = home / ".claude/plugins/installed_plugins.json"
        index.parent.mkdir(parents=True)
        index.write_text(json.dumps({"plugins": {"x": ["not-a-dict", None]}}))
        with mock.patch.object(crf.Path, "home", return_value=home):
            self.assertEqual(crf._installed_jira_clis(), [])

    def test_more_dismissals_than_read_is_named(self):
        pr = _pr()
        pr["data"]["repository"]["pullRequest"]["timelineItems"] = {
            "totalCount": 150,
            "pageInfo": {"hasNextPage": True},
            "nodes": [],
        }
        self.assertIn("timelineItems", crf.parse_github_pr(pr, set())["truncated"])


class FourthRoundTest(unittest.TestCase):
    """Inputs from the fourth review round (cbccd69)."""

    def urls(self, pairs):
        data = dss.collect_artefacts(_transcript(pairs))
        return {a["url"]: a["origin"] for a in data["artefacts"]}, data

    def test_a_refusal_without_the_prefix_ran_nothing(self):
        # The bare-reference gate echoes `#721`; `is_error` without `Exit code`.
        gate = "Bare references in a message you are about to send to people: #721."
        cmd = {
            "command": "gh issue comment 721 -R o/r --body-file c.md",
            "__error": True,
        }
        urls, data = self.urls([(cmd, gate)])
        self.assertEqual((urls, data["unresolved_forge_commands"]), ({}, []))
        jira = "uv run jira-comment.py add NRS-9999 -"
        self.assertEqual(dss.jira_command_tickets(jira, "lint: NRS-9999", True), set())

    def test_a_failed_run_is_still_a_run(self):
        cmd = {"command": "gh pr merge 3 -R o/r --merge", "__error": True}
        _, data = self.urls([(cmd, "Exit code 1\nx Cannot perform merge action")])
        self.assertEqual(len(data["unresolved_forge_commands"]), 1)

    def test_an_apostrophe_in_a_heredoc_does_not_hide_the_next_command(self):
        cmd = (
            "cat > b.md <<'MD'\nthe runner's own check\nMD\n"
            "gh pr create -R o/r --body-file b.md"
        )
        urls, _ = self.urls([({"command": cmd}, "https://github.com/o/r/pull/194")])
        self.assertEqual(urls, {"https://github.com/o/r/pull/194": "created"})

    def test_error_output_behind_a_pipe_is_not_a_silent_success(self):
        cmds = [
            (
                "gh pr merge 202 -R o/r --merge 2>&1 | tail -2",
                "gh: Pull Request is still a draft (HTTP 405)",
            ),
            (
                "gh pr review 684 -R o/r --approve 2>&1 | tail -1",
                "GraphQL: Can not approve your own pull request",
            ),
            (
                "gh pr merge 5 -R o/r --merge",
                "Command running in background with ID: b1.",
            ),
        ]
        urls, data = self.urls([({"command": c}, r) for c, r in cmds])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 3))

    def test_a_create_counts_only_its_own_kind(self):
        cmd = "gh pr create -R o/r --fill"
        printed = "https://github.com/o/r/issues/169#issuecomment-1\nhttps://github.com/o/r/pull/170"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls["https://github.com/o/r/pull/170"], "created")
        self.assertEqual(urls["https://github.com/o/r/issues/169"], "mentioned")

    def test_rate_limited_in_a_finding_is_not_a_refusal(self):
        body = "The new /login handler is not rate-limited, so a client can brute-force it."
        self.assertFalse(crf.finding("u", "review", "b", "bot", None, body)["report"])

    def test_no_dismissals_on_a_long_timeline_is_not_truncated(self):
        pr = _pr()
        pr["data"]["repository"]["pullRequest"]["timelineItems"] = {
            # totalCount counts the whole timeline, not the dismissals.
            "totalCount": 13,
            "filteredCount": 0,
            "pageInfo": {"hasNextPage": False},
            "nodes": [],
        }
        self.assertNotIn("timelineItems", crf.parse_github_pr(pr, set())["truncated"])

    def test_a_write_without_a_number_takes_only_report_lines(self):
        cmd = "gh pr edit --add-label x; gh pr view --json body"
        printed = (
            "https://github.com/o/r/pull/7\n"
            '{"body":"see https://github.com/o/r/issues/104"}'
        )
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls["https://github.com/o/r/pull/7"], "acted")
        self.assertEqual(urls["https://github.com/o/r/issues/104"], "mentioned")

    def test_a_write_takes_only_its_own_number(self):
        cmd = "gh pr ready 113 --repo o/r && gh pr view 107 --repo o/r --json url --jq .url"
        printed = (
            "✓ Pull request o/r#113 is marked as ready\nhttps://github.com/o/r/pull/107"
        )
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls["https://github.com/o/r/pull/113"], "acted")
        self.assertEqual(urls["https://github.com/o/r/pull/107"], "mentioned")

    def test_a_write_takes_only_its_own_repository(self):
        cmd = "gh pr merge 5 -R o/r --merge && gh pr view 5 -R x/y --json url --jq .url"
        printed = "✓ Merged pull request o/r#5\nhttps://github.com/x/y/pull/5"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls["https://github.com/o/r/pull/5"], "acted")
        self.assertEqual(urls["https://github.com/x/y/pull/5"], "mentioned")

    def test_a_jira_call_after_a_heredoc_with_an_apostrophe(self):
        # Unmasked, the apostrophe in the heredoc and the quote in `echo 'done'`
        # would form one quoted span over the jira call.
        cmd = (
            "cat > c.txt <<'EOF'\nthe runner's note\nEOF\n"
            "uv run jira-comment.py add NRS-5 - < c.txt; echo 'all done'"
        )
        self.assertEqual(
            dss.jira_command_tickets(cmd, "Comment added to NRS-5"), {"NRS-5"}
        )

    def test_a_plugin_index_whose_plugins_is_a_list(self):
        home = Path(TMP.name) / f"home{next(_COUNTER)}"
        index = home / ".claude/plugins/installed_plugins.json"
        index.parent.mkdir(parents=True)
        index.write_text(json.dumps({"plugins": ["x"]}))
        with mock.patch.object(crf.Path, "home", return_value=home):
            self.assertEqual(crf._installed_jira_clis(), [])


class FifthRoundTest(unittest.TestCase):
    """Inputs from the fifth review round (f2a4784)."""

    def urls(self, pairs):
        data = dss.collect_artefacts(
            _transcript(
                pairs,
            ),
            gitlab_host="git.example.org",
        )
        return {a["url"]: a["origin"] for a in data["artefacts"]}, data

    def test_a_variable_in_the_path_is_unresolved_not_dropped(self):
        cmd = 'gh api -X PUT "repos/$R/pulls/29/merge" -f merge_method=merge'
        urls, data = self.urls([({"command": cmd}, "")])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 1))
        printed = '{"sha":"1","merged":true}\nhttps://github.com/o/r/pull/29'
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {"https://github.com/o/r/pull/29": "acted"})

    def test_a_glab_create_by_path(self):
        cmd = "glab api projects/g%2Fp/merge_requests -X POST -f title=x -f source_branch=b"
        printed = "https://git.example.org/g/p/-/merge_requests/21"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {printed: "created"})

    def test_a_numeric_project_create_is_unresolved(self):
        cmd = 'glab api "projects/907/issues" --method POST -f title=x'
        urls, data = self.urls([({"command": cmd}, '{"iid": 4}')])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 1))

    def test_a_numeric_project_create_names_its_url(self):
        cmd = 'glab api "projects/907/issues" --method POST -f title=x'
        printed = (
            '{\n  "iid": 4,\n  "web_url": "https://git.example.org/g/p/-/issues/4"\n}'
        )
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {"https://git.example.org/g/p/-/issues/4": "created"})

    def test_editing_a_comment_by_id(self):
        cmd = "gh api -X PATCH repos/o/r/issues/comments/99 -f body=x"
        printed = '{"id":99,"html_url":"https://github.com/o/r/pull/5#issuecomment-99","body":"x"}'
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {"https://github.com/o/r/pull/5": "acted"})

    def test_several_creates_in_one_call(self):
        cmd = "gh issue create -R o/r -t a -b a; gh issue create -R o/r -t b -b b"
        printed = "https://github.com/o/r/issues/1\nhttps://github.com/o/r/issues/2"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(
            urls,
            {
                "https://github.com/o/r/issues/1": "created",
                "https://github.com/o/r/issues/2": "created",
            },
        )

    def test_a_refused_mcp_write_wrote_nothing(self):
        payload = {
            "__name": "mcp__github__merge_pull_request",
            "__error": True,
            "owner": "o",
            "repo": "r",
            "pullNumber": 117,
        }
        refusal = "Permission for this action was denied by the Claude Code auto mode classifier."
        urls, _ = self.urls([(payload, refusal)])
        self.assertEqual(urls, {})

    def test_a_gitlab_json_answer_names_its_web_url(self):
        cmd = "glab api projects/g%2Fp/issues -X POST -f title=x"
        printed = '{"iid":7,"web_url":"https://git.example.org/g/p/-/issues/7"}'
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {"https://git.example.org/g/p/-/issues/7": "created"})

    def test_a_continued_line_is_one_command(self):
        cmd = 'glab api "projects/g%2Fp/merge_requests/434" --hostname git.example.org \\\n  --method PUT -f title=x'
        urls, _ = self.urls([({"command": cmd}, "")])
        self.assertEqual(
            urls, {"https://git.example.org/g/p/-/merge_requests/434": "acted"}
        )

    def test_cannot_in_a_body_is_not_a_failure(self):
        cmd = "gh api -X POST repos/o/r/pulls/5/requested_reviewers -f 'reviewers[]=x'"
        printed = '{"body":"This cannot happen twice"}'
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {"https://github.com/o/r/pull/5": "acted"})

    def test_a_rest_write_in_quoted_text_is_not_a_call(self):
        cmd = 'echo "run gh api -X PUT repos/o/r/pulls/5/merge -f merge_method=merge"'
        urls, data = self.urls([({"command": cmd}, "")])
        self.assertEqual((urls, data["unresolved_forge_commands"]), ({}, []))


class SixthRoundTest(unittest.TestCase):
    """Inputs from the sixth review round (1e2b0cb)."""

    def urls(self, pairs):
        data = dss.collect_artefacts(_transcript(pairs), gitlab_host="git.example.org")
        return {a["url"]: a["origin"] for a in data["artefacts"]}, data

    def test_a_create_in_a_loop_takes_every_url(self):
        cmd = "for r in a b c; do gh pr create --repo netresearch/$r --fill; done"
        printed = (
            "https://github.com/netresearch/a/pull/1\n"
            "https://github.com/netresearch/b/pull/2\n"
            "https://github.com/netresearch/c/pull/3"
        )
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(set(urls.values()), {"created"})
        self.assertEqual(len(urls), 3)

    def test_a_loop_word_in_quoted_text_is_not_a_loop(self):
        cmd = 'echo "for a in b do"; gh pr create -R o/r --fill; echo "done"'
        printed = "https://github.com/o/r/pull/2\nhttps://github.com/o/r/pull/9"
        urls, data = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls["https://github.com/o/r/pull/2"], "created")
        self.assertEqual(urls["https://github.com/o/r/pull/9"], "mentioned")
        # pull/9 is a report line no write claimed: the call is not complete.
        self.assertEqual(len(data["unresolved_forge_commands"]), 1)

    def test_an_unclaimed_report_line_makes_any_call_unresolved(self):
        cmd = "gh pr create -R o/r --fill && gh pr view 1 -R o/r --json url --jq .url"
        printed = "https://github.com/o/r/pull/2\nhttps://github.com/o/r/pull/1"
        urls, data = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls["https://github.com/o/r/pull/2"], "created")
        self.assertEqual(urls["https://github.com/o/r/pull/1"], "mentioned")
        self.assertEqual(len(data["unresolved_forge_commands"]), 1)

    def test_a_heredoc_script_the_call_runs_is_unresolved_not_dropped(self):
        cmd = "cat > x.sh <<'EOF'\nfor n in 3 4; do gh issue edit \"$n\" -R o/r --add-label x; done\nEOF\nbash x.sh"
        printed = "https://github.com/o/r/issues/3\nhttps://github.com/o/r/issues/4"
        urls, data = self.urls([({"command": cmd}, printed)])
        self.assertEqual(set(urls.values()), {"mentioned"})
        self.assertEqual(len(data["unresolved_forge_commands"]), 1)

    def test_graphql_after_a_colon_is_a_failure(self):
        cmd = 'gh pr review 684 -R o/r --approve; echo "exit=$?"'
        # The recorded line starts with "failed to"; this one only has the
        # mid-line "GraphQL:".
        printed = "review not created: GraphQL: Review Can not approve your own pull request\nexit=1"
        urls, data = self.urls([({"command": cmd}, printed)])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 1))

    def test_an_x_line_is_a_failure(self):
        cmd = "gh pr merge 5 -R o/r --merge; echo done"
        urls, _ = self.urls(
            [({"command": cmd}, "X Pull request o/r#5 is not mergeable\ndone")]
        )
        self.assertEqual(urls, {})

    def test_several_rest_creates_in_one_call(self):
        cmd = "gh api repos/o/r/issues -X POST -f title=a; gh api repos/o/r/issues -X POST -f title=b"
        printed = "https://github.com/o/r/issues/1\nhttps://github.com/o/r/issues/2"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(
            urls,
            {
                "https://github.com/o/r/issues/1": "created",
                "https://github.com/o/r/issues/2": "created",
            },
        )

    def test_an_endpoint_in_a_variable_reads_the_report_line(self):
        cmd = 'gh api -X POST "$R/4061866425/replies" -f body=x --jq .html_url'
        printed = "https://github.com/o/r/pull/133#discussion_r9"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {"https://github.com/o/r/pull/133": "acted"})

    def test_the_rest_fallback_keeps_its_own_number(self):
        cmd = (
            'gh api -X POST "repos/$R/pulls/29/requested_reviewers" -f "reviewers[]=x"'
        )
        printed = "https://github.com/o/r/pull/29\nhttps://github.com/o/r/pull/30"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls["https://github.com/o/r/pull/29"], "acted")
        self.assertEqual(urls["https://github.com/o/r/pull/30"], "mentioned")

    def test_the_rest_fallback_keeps_its_own_kind_and_number(self):
        cmd = (
            "gh pr ready 87 -R o/r; "
            'gh api "repos/$1/pulls/$2/requested_reviewers" -X POST -f "reviewers[]=x"'
        )
        printed = '✓ Pull request o/r#87 is marked as "ready for review"'
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {"https://github.com/o/r/pull/87": "acted"})

    def test_more_verbs_and_tools_write(self):
        pairs = [
            ({"command": "glab mr rebase 12 -R g/p"}, "✓ Rebase successful"),
            ({"command": "gh issue delete 9 -R o/r --yes"}, "✓ Deleted issue o/r#9"),
            (
                {
                    "__name": "mcp__github__request_copilot_review",
                    "owner": "o",
                    "repo": "r",
                    "pullNumber": 5,
                },
                "ok",
            ),
        ]
        urls, _ = self.urls(pairs)
        self.assertEqual(
            urls,
            {
                "https://git.example.org/g/p/-/merge_requests/12": "acted",
                "https://github.com/o/r/issues/9": "acted",
                "https://github.com/o/r/pull/5": "acted",
            },
        )

    def test_a_create_in_a_variable_project_is_a_create(self):
        cmd = 'for p in 1 2; do glab api "projects/$p/merge_requests" --method POST -f title=x; done'
        printed = "https://git.example.org/g/a/-/merge_requests/7\nhttps://git.example.org/g/b/-/merge_requests/8"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(set(urls.values()), {"created"})
        self.assertEqual(len(urls), 2)


class SeventhRoundTest(unittest.TestCase):
    """Inputs from the seventh review round (fc610d5)."""

    def urls(self, pairs):
        data = dss.collect_artefacts(_transcript(pairs), gitlab_host="git.example.org")
        return {a["url"]: a["origin"] for a in data["artefacts"]}, data

    def test_the_merge_wrapper_reports_its_writes(self):
        cmd = "pr-merge.sh -R o/r 150 --self-reviewed"
        printed = (
            "pr-merge: posted Self-review attestation for 1a2b3c4d5e6f on o/r#150\n"
            "pr-merge: o/r#150 merged (--merge)"
        )
        urls, data = self.urls([({"command": cmd}, printed)])
        self.assertEqual(urls, {"https://github.com/o/r/pull/150": "acted"})
        self.assertEqual(data["unresolved_forge_commands"], [])

    def test_the_merge_wrapper_that_wrote_nothing(self):
        shut = "pr-merge: not merging o/r#150 — request-review: no review on the current head"
        urls, data = self.urls([({"command": "pr-merge.sh -R o/r 150"}, shut)])
        self.assertEqual((urls, data["unresolved_forge_commands"]), ({}, []))
        urls, data = self.urls([({"command": "pr-merge.sh -R o/r 150"}, "")])
        self.assertEqual((urls, len(data["unresolved_forge_commands"])), ({}, 1))

    def test_a_status_line_of_the_same_pr_is_not_unclaimed(self):
        ready = '✓ Pull request o/r#682 is marked as "ready for review"'
        urls, data = self.urls([({"command": "gh pr ready 682 -R o/r"}, ready)])
        self.assertEqual(urls, {"https://github.com/o/r/pull/682": "acted"})
        self.assertEqual(data["unresolved_forge_commands"], [])
        urls, data = self.urls(
            [({"command": "glab mr rebase 12 -R g/p"}, "✓ Rebased g/p!12")]
        )
        self.assertEqual(
            urls, {"https://git.example.org/g/p/-/merge_requests/12": "acted"}
        )
        self.assertEqual(data["unresolved_forge_commands"], [])

    def test_an_edit_and_a_create_in_one_call(self):
        cmd = "gh pr edit 92 -R o/r --add-label x; gh pr create -R o/r --fill"
        printed = "https://github.com/o/r/pull/92\nhttps://github.com/o/r/pull/97"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(
            urls,
            {
                "https://github.com/o/r/pull/92": "acted",
                "https://github.com/o/r/pull/97": "created",
            },
        )

    def test_a_create_before_an_edit_in_one_call(self):
        cmd = "gh pr create -R o/r --fill; gh pr edit 92 -R o/r --add-label x"
        printed = "https://github.com/o/r/pull/92\nhttps://github.com/o/r/pull/97"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(
            urls,
            {
                "https://github.com/o/r/pull/92": "acted",
                "https://github.com/o/r/pull/97": "created",
            },
        )

    def test_a_script_printing_urls_in_running_text_is_unresolved(self):
        cmd = "cat > s.sh <<'EOF'\ngh pr merge 5 -R o/r --merge\nEOF\nbash s.sh"
        urls, data = self.urls(
            [({"command": cmd}, "o/r: https://github.com/o/r/pull/5 done")]
        )
        self.assertEqual(set(urls.values()), {"mentioned"})
        self.assertEqual(len(data["unresolved_forge_commands"]), 1)

    def test_a_loop_with_do_on_the_next_line(self):
        cmd = "for r in a b\ndo\n  gh pr create --repo netresearch/$r --fill\ndone"
        printed = "https://github.com/netresearch/a/pull/1\nhttps://github.com/netresearch/b/pull/2"
        urls, _ = self.urls([({"command": cmd}, printed)])
        self.assertEqual(set(urls.values()), {"created"})
        self.assertEqual(len(urls), 2)


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
