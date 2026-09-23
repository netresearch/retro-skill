#!/usr/bin/env python3
"""Unit tests for collect-review-findings.py and the artefact detection in
derive-session-scope.py it builds on.

The GitHub fixture is a recorded GraphQL answer for netresearch/retro-skill#122
(bodies cut to 240 characters). The GitLab and Jira fixtures keep the recorded
shape of `glab api` and `jira-issue.py --json … --raw` with names and text
replaced, because the originals are internal.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

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
        # threads; 3 bot reviews carry a body. Self: the one own PR comment.
        self.assertEqual(len(reviews), 3)
        self.assertEqual(self.parsed["self_comments"], 1)
        self.assertTrue(all(f["report"] for f in reviews))

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
        self.assertEqual(
            self.parsed["self_comments"], 1
        )  # the system note is not counted

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
            if endpoint.endswith("closes_issues"):
                return raw["closes"]
            return raw["item"]

        item = dss.artefact("git.example.org", "group/app", "merge_requests", 88) | {
            "origin": "created"
        }
        result = crf.collect([item], None, run=runner, jira_cli=None)
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
