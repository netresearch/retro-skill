#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Unit tests for skills/retro/scripts/scan-cross-session.py (Schicht C)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "retro" / "scripts" / "scan-cross-session.py"


def _load():
    spec = importlib.util.spec_from_file_location("scan_cross_session", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scs = _load()


class Transcript:
    """Builds a session JSONL the way Claude Code writes it."""

    def __init__(self, day: int = 1) -> None:
        self.day = day
        self.events: list[dict] = []
        self.n = 0

    def _ts(self) -> str:
        self.n += 1
        return f"2026-09-{self.day:02d}T10:{self.n // 60:02d}:{self.n % 60:02d}Z"

    def user(self, text: str) -> Transcript:
        self.events.append(
            {"type": "user", "timestamp": self._ts(), "message": {"content": text}}
        )
        return self

    def call(self, name: str, inp: dict, result: str, is_error: bool = False):
        use_id = f"toolu_{len(self.events)}"
        self.events.append(
            {
                "type": "assistant",
                "timestamp": self._ts(),
                "message": {
                    "content": [
                        {"type": "tool_use", "id": use_id, "name": name, "input": inp}
                    ]
                },
            }
        )
        self.events.append(
            {
                "type": "user",
                "timestamp": self._ts(),
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": use_id,
                            "content": result,
                            "is_error": is_error,
                        }
                    ]
                },
            }
        )
        return self

    def write(self, root: Path, project: str, session: str) -> Path:
        path = root / project / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(e) for e in self.events) + "\n", encoding="utf-8"
        )
        return path


def _sessions(root: Path) -> list[dict]:
    sessions, _skipped = scs.read_sessions(scs.session_files(root, None, 3650))
    return sessions


def _run(root: Path, *args: str) -> dict:
    out = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--projects-dir",
            str(root),
            "--days",
            "3650",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)


class SessionFilesTest(TempDirCase):
    @unittest.skipUnless(hasattr(time, "tzset"), "requires POSIX timezone selection")
    def test_elapsed_day_cutoff_is_inclusive_across_local_clock_changes(self) -> None:
        paths = {
            name: Transcript().write(self.root, "-p", name)
            for name in ("before", "at", "after")
        }
        for month, day in ((3, 29), (10, 25)):
            instant = datetime(2026, month, day, 12, tzinfo=UTC)
            cutoff = instant - timedelta(days=1)
            for name, seconds in (("before", -1), ("at", 0), ("after", 1)):
                stamp = cutoff.timestamp() + seconds
                os.utime(paths[name], (stamp, stamp))
            for zone in ("UTC0", "CET-1CEST,M3.5.0/2,M10.5.0/3"):
                with self.subTest(month=month, zone=zone):
                    try:
                        with mock.patch.dict(os.environ, {"TZ": zone}):
                            time.tzset()
                            with mock.patch.object(
                                scs, "datetime", wraps=datetime
                            ) as clock:
                                clock.now.side_effect = lambda tz=None, now=instant: (
                                    now.astimezone(tz)
                                    if tz is not None
                                    else now.astimezone().replace(tzinfo=None)
                                )
                                found = scs.session_files(self.root, None, 1)
                            self.assertEqual(
                                set(found),
                                {(paths["at"], "-p"), (paths["after"], "-p")},
                            )
                    finally:
                        time.tzset()


class UserTurnCoverageTest(TempDirCase):
    def test_empty_project_and_missing_source_are_distinct(self):
        (self.root / "-empty").mkdir()
        for mode in (["--pattern=relay"], ["--user-correction-summary"]):
            with self.subTest(mode=mode):
                empty = _run(self.root, "--project=-empty", *mode)["coverage"]
                self.assertEqual(
                    (empty["status"], empty["sessions_read"]), ("scanned", 0)
                )
                for root, slug in (
                    (self.root, "-gone"),
                    (self.root / "absent", "-empty"),
                ):
                    missing = _run(root, "--project=" + slug, *mode)
                    self.assertFalse(missing["available"])
                    self.assertEqual(
                        missing["coverage"], {"status": "unavailable", "project": slug}
                    )

    def test_valid_hits_survive_partial_reads_and_stay_in_scope(self):
        path = (
            Transcript().user("no, first attempt").write(self.root, "-project", "seen")
        )
        Transcript().user("no, relay").write(self.root, "-other", "unrelated")
        with path.open("ab") as raw:
            raw.write(b'{"type":\n[]\n\xff\n{"type":"user","message":null}\n')
            raw.write(b'{"type":"response_item","payload":{}}\n')
            raw.write(
                b'{"type":"user","message":{"content":[{"type":"text","text":null},'
                b'{"type":"text","text":"no, relay again"}]}}\n'
            )
        # An unreadable input without relying on Unix permissions or process uid.
        (path.parent / "broken.jsonl").mkdir()
        for mode in (["--pattern=relay"], ["--user-correction-summary"]):
            with self.subTest(mode=mode):
                result = _run(self.root, "--project=-project", *mode)
                self.assertEqual(
                    result["coverage"],
                    {
                        "status": "partial",
                        "corpus": "claude_user_turns",
                        "project": "-project",
                        "sessions_read": 1,
                        "gaps": {
                            "invalid_rows": 3,
                            "invalid_user_turns": 2,
                            "unreadable_sessions": 1,
                            "native_codex_rows": 1,
                        },
                    },
                )
                if "matches" in result:
                    self.assertEqual(list(result["matches"]), ["-project"])
                    self.assertEqual(
                        result["matches"]["-project"],
                        [{"session": "seen.jsonl", "snippet": "no, relay again"}],
                    )
                else:
                    self.assertEqual(result["sessions_scanned"], 1)
                    self.assertEqual(list(result["by_project_top5"]), ["-project"])

    def test_codex_user_event_alone_is_not_a_complete_claude_search(self):
        fixture = REPO_ROOT / "tests/fixtures/codex/rollout-0.101.0.jsonl"
        rows = (json.loads(line) for line in fixture.read_text().splitlines())
        event = next(
            row
            for row in rows
            if row.get("type") == "event_msg"
            and row["payload"].get("type") == "user_message"
        )
        project = self.root / "-project"
        project.mkdir()
        (project / "one-turn.jsonl").write_text(json.dumps(event) + "\n")
        result = _run(self.root, "--project=-project", "--pattern=Run the test suite")
        self.assertEqual(result["matches"], {})
        self.assertEqual(result["coverage"]["status"], "partial")
        self.assertEqual(result["coverage"]["gaps"], {"native_codex_rows": 1})

    def test_explicit_empty_scope_does_not_search_every_project(self):
        Transcript().user("no, relay").write(self.root, "-other", "unrelated")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--projects-dir",
                str(self.root),
                "--project=",
                "--pattern=relay",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_query_and_matching_excerpt_use_the_same_mask(self):
        query = "Authorization: Bearer " + "example" * 5
        Transcript().user(query).write(self.root, "-project", "seen")
        result = _run(self.root, "--pattern=" + query)
        self.assertEqual(result["projects_with_matches"], 1)
        self.assertNotIn("example" * 5, json.dumps(result))
        self.assertIn("[REDACTED]", result["pattern"])


RULES = """# Rules

- **Never merge.** No `gh pr merge` without a per-PR instruction. [→A12]
- Prefer `uv run` over a bare
  `pip install` for Python.
- Be kind.

~~~
- `not a rule` inside a fence
~~~
"""


def _tally(root: Path, rules_text: str = RULES, limit: int = 20) -> dict:
    parsed = scs.parse_rules(rules_text)
    sessions = []
    for s in _sessions(root):
        events = scs.load_events(root / s["project"] / f"{s['id']}.jsonl")
        s["user_texts"] = scs.user_texts_of(events, Counter())
        s["ran_tally"] = scs.ran_tally(s["calls"])
        sessions.append(s)
    return scs.rule_tally(parsed["rules"], sessions, limit)


def _by_id(found: dict) -> dict:
    return {r["id"]: r for r in found["rules"]}


class ParseRulesTest(unittest.TestCase):
    def test_rules_take_the_anchor_or_a_text_hash(self) -> None:
        rules = scs.parse_rules(RULES)["rules"]
        self.assertEqual(len(rules), 3)
        self.assertEqual((rules[0]["id"], rules[0]["line"]), ("A12", 3))
        self.assertEqual(rules[0]["keywords"], ["gh pr merge"])
        self.assertTrue(rules[1]["id"].startswith("h:"))
        self.assertEqual(rules[1]["keywords"], ["pip install", "uv run"])
        self.assertEqual(rules[2]["keywords"], [])

    def test_markdown_structure_is_read_by_a_parser(self) -> None:
        text = (
            "- a rule with `one` and\n#123 `kept after hash`\n\n"
            "  a second paragraph with `later span`\n\n"
            "* * *\n\n"
            "~~~\n- `tilde`\n~~~\n\n"
            "````\n```\n- `fenced`\n```\n````\n\n"
            "- double ``two ` ticks``\n"
        )
        rules = scs.parse_rules(text)["rules"]
        self.assertEqual(
            [r["keywords"] for r in rules],
            [["kept after hash", "later span", "one"], ["two ` ticks"]],
        )

    def test_placeholders_leave_only_their_literal_prefix(self) -> None:
        text = "- `gh issue delete <n>` and `<sha>` and `cmd ...`\n- only `<sha>`\n"
        rules = scs.parse_rules(text)["rules"]
        # `cmd ...` leaves only a short bare word, too common to count.
        self.assertEqual(rules[0]["keywords"], ["gh issue delete"])
        self.assertEqual(rules[1]["keywords"], [])

    def test_frontmatter_is_not_read_as_rules(self) -> None:
        text = "---\nname: x\nallowed-tools:\n  - Read\n---\n\n- `uv run` only\n"
        rules = scs.parse_rules(text)["rules"]
        self.assertEqual([r["keywords"] for r in rules], [["uv run"]])
        self.assertEqual(rules[0]["line"], 7)

    def test_glob_and_brace_placeholders_are_cut(self) -> None:
        text = "- `mcp__package-version__*` and `OPS{CUSTOMER}-board`\n"
        rules = scs.parse_rules(text)["rules"]
        self.assertEqual(rules[0]["keywords"], ["mcp__package-version__"])

    def test_a_short_word_before_a_cut_is_dropped(self) -> None:
        text = "- `try { work; commit } catch { rollBack }` and `array{key: int}`\n"
        self.assertEqual(scs.parse_rules(text)["rules"][0]["keywords"], [])

    def test_a_placeholder_with_spaces_is_cut_too(self) -> None:
        rules = scs.parse_rules("- `git add <only its files>` [→A146]\n")["rules"]
        self.assertEqual(rules[0]["keywords"], ["git add"])

    def test_duplicate_ids_are_suffixed_and_every_anchor_kept(self) -> None:
        text = "- x [→A16,A373]\n- y [→A1]\n- z [→A1]\n"
        ids = [r["id"] for r in scs.parse_rules(text)["rules"]]
        self.assertEqual(ids, ["A16,A373", "A1", "A1#2"])


class RuleTallyTest(TempDirCase):
    def test_hits_failures_and_corrections_are_counted_per_session(self) -> None:
        Transcript().call("Bash", {"command": "uv run x.py"}, "ok").write(
            self.root, "-p", "a"
        )
        Transcript().call(
            "Bash", {"command": "pip install x"}, "Exit code 1\nerror", True
        ).write(self.root, "-p", "b")
        Transcript().user("no, use gh pr merge only when told").write(
            self.root, "-p", "c"
        )
        tally = _by_id(_tally(self.root))
        self.assertEqual(tally["A12"]["sessions"], ["c"])
        self.assertEqual(tally["A12"]["violation_candidates"], ["c"])
        uv = next(r for k, r in tally.items() if k.startswith("h:") and r["keywords"])
        self.assertEqual(uv["sessions"], ["a", "b"])
        self.assertEqual(uv["violation_candidates"], ["b"])
        self.assertEqual(uv["state"], "measured")
        kind = next(r for r in tally.values() if not r["keywords"])
        self.assertEqual(kind["state"], "not_measurable")

    def test_a_refusal_is_not_a_violation_candidate(self) -> None:
        Transcript().call(
            "Bash", {"command": "pip install x"}, "Use uv, not pip.", True
        ).write(self.root, "-p", "a")
        uv = next(r for r in _tally(self.root)["rules"] if "uv run" in r["keywords"])
        self.assertEqual((uv["sessions"], uv["violation_candidates"]), (["a"], []))

    def test_interior_spaces_of_a_keyword_still_match(self) -> None:
        rules = "- run `git  status` first\n"
        Transcript().call("Bash", {"command": "git  status"}, "ok").write(
            self.root, "-p", "a"
        )
        found = _tally(self.root, rules)
        self.assertEqual([r["sessions"] for r in found["rules"]], [["a"]])

    def test_a_shorter_keyword_inside_a_longer_one_still_hits(self) -> None:
        rules = "- `git add -A` never\n- `git` always\n"
        Transcript().call("Bash", {"command": "git add -A"}, "ok").write(
            self.root, "-p", "a"
        )
        found = _tally(self.root, rules)
        self.assertEqual([r["sessions"] for r in found["rules"]], [["a"], ["a"]])

    def _applicable(self, rules: str, name: str, inp: dict, result: str) -> list[int]:
        """Per rule, the sessions that count for one call."""
        path = Transcript().call(name, inp, result).write(self.root, "-p", "a")
        self.addCleanup(path.unlink, missing_ok=True)
        return [r["applicable_sessions"] for r in _tally(self.root, rules)["rules"]]

    def test_a_keyword_inside_another_word_does_not_hit(self) -> None:
        rules = (
            "- Never use bare `pip`.\n- Avoid `sed` for JSON.\n- Keep `.env` intact\n"
        )
        for command, expected in (
            ("glab pipeline list; echo used x.environ", [0, 0, 0]),
            ("mcp__pip__sed_x", [1, 1, 0]),
            ("pipeline; pip; cat prod.env", [1, 0, 1]),
            ("pip install x; sed -n 1p .env", [1, 1, 1]),
        ):
            with self.subTest(command=command):
                hit = self._applicable(rules, "Bash", {"command": command}, "ok")
                self.assertEqual(hit, expected)

    def test_a_keyword_ending_in_a_separator_hits_what_follows_it(self) -> None:
        rules = "- read `docs/` first\n"
        hit = self._applicable(rules, "Bash", {"command": "cat docs/x.md"}, "ok")
        self.assertEqual(hit, [1])

    def test_a_short_option_hits_the_bundle_it_opens(self) -> None:
        rules = "- `set -e` first\n- never `tool --e`\n"
        for command, expected in (
            ("set -euo pipefail", [1, 0]),
            ("tool --exit", [0, 0]),
        ):
            with self.subTest(command=command):
                hit = self._applicable(rules, "Bash", {"command": command}, "ok")
                self.assertEqual(hit, expected)

    def test_an_escaped_line_break_before_a_keyword_still_hits(self) -> None:
        result = '{"log": "one\\nmake unit"}'
        rules = "- run `make unit`\n"
        self.assertEqual(self._applicable(rules, "Bash", {"command": "x"}, result), [1])

    def test_a_keyword_cut_inside_a_word_hits_what_continues_it(self) -> None:
        rules = "- board `OPSCUST-board{X}`\n- run `make unit <n>`\n"
        for command, expected in (
            ("show OPSCUST-board7", [1, 0]),
            ("make unit 3", [0, 1]),
            ("make units", [0, 0]),
        ):
            with self.subTest(command=command):
                hit = self._applicable(rules, "Bash", {"command": command}, "ok")
                self.assertEqual(hit, expected)

    def test_reading_a_numbered_or_diffed_rule_is_not_an_occurrence(self) -> None:
        rules = "- Test:\n  - `make unit`\n  - `make lint`\n"
        lines = rules.splitlines()
        for prefix in ("{n}\t", "    {n}→", "{n}:", "+", "-", " "):
            shown = "\n".join(
                prefix.format(n=n) + line for n, line in enumerate(lines, 1)
            )
            with self.subTest(prefix=prefix):
                hit = self._applicable(rules, "Read", {"file_path": "x"}, shown)
                self.assertEqual(hit, [0])
        use = self._applicable(rules, "Bash", {"command": "make unit"}, "1\tok")
        self.assertEqual(use, [1])

    def test_a_cut_does_not_hide_a_credential_from_the_mask(self) -> None:
        rules = "- DB: `postgres://app:S3cr*tPw99@db/x`\n"
        out = json.dumps(_tally(self.root, rules))
        self.assertNotIn("S3cr", out)
        self.assertIn("[REDACTED]", out)

    def test_quotes_in_a_command_match_unescaped(self) -> None:
        rules = '- count with `grep -c "foo"` before you claim one\n'
        Transcript().call("Bash", {"command": 'grep -c "foo" f'}, "3").write(
            self.root, "-p", "a"
        )
        Transcript().call(
            "Write",
            {"file_path": "CLAUDE.md", "content": rules},
            "File written",
        ).write(self.root, "-p", "b")
        [rule] = _tally(self.root, rules)["rules"]
        self.assertEqual(rule["sessions"], ["a"])

    def test_reading_the_rules_file_is_not_an_occurrence(self) -> None:
        Transcript().call("Read", {"file_path": "/x/CLAUDE.md"}, RULES).write(
            self.root, "-p", "a"
        )
        Transcript().call(
            "Bash", {"command": "x"}, '{"mode":"rule-tally","keywords":["uv run"]}'
        ).write(self.root, "-p", "b")
        Transcript().call(
            "Bash",
            {"command": "cat out.json"},
            '{"violation_candidate_sessions": 0, "k": "uv run"}',
        ).write(self.root, "-p", "d")
        Transcript().call(
            "Bash",
            {"command": "jq .never_applicable out.json  # --rule-tally"},
            "uv run",
        ).write(self.root, "-p", "c")
        found = _tally(self.root)
        self.assertEqual([r["applicable_sessions"] for r in found["rules"]], [0, 0, 0])
        self.assertEqual(found["sessions_that_ran_a_tally"], 1)

    def _rules_file(self) -> Path:
        rules = self.root / "CLAUDE.md"
        rules.write_text(RULES, encoding="utf-8")
        return rules

    def test_never_applicable_is_withheld_below_the_window(self) -> None:
        Transcript().call("Bash", {"command": "uv run x"}, "ok").write(
            self.root, "-p", "a"
        )
        rules = self._rules_file()
        out = _run(self.root, "--rule-tally", str(rules), "--min-sessions", "2")
        self.assertIsNone(out["never_applicable"])
        self.assertFalse(out["window_sufficient"])
        out = _run(self.root, "--rule-tally", str(rules), "--min-sessions", "1")
        self.assertEqual(out["never_applicable"], ["A12"])
        self.assertEqual(out["rules_not_measurable"], 1)
        self.assertIn("gaps", out)

    def test_the_window_counts_only_scanned_sessions(self) -> None:
        Transcript().call("Bash", {"command": "uv run x"}, "ok").write(
            self.root, "-p", "a"
        )
        Transcript().call(
            "Bash", {"command": "scan-cross-session.py --rule-tally CLAUDE.md"}, "{}"
        ).write(self.root, "-p", "b")
        out = _run(
            self.root, "--rule-tally", str(self._rules_file()), "--min-sessions", "2"
        )
        self.assertEqual(out["sessions_scanned"], 1)
        self.assertFalse(out["window_sufficient"])

    def test_an_unreadable_rules_file_exits_2_without_a_traceback(self) -> None:
        for path in (self.root / "missing.md", self.root):
            run = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--projects-dir",
                    str(self.root),
                    "--rule-tally",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2)
            self.assertNotIn("Traceback", run.stderr)


class LoadEventsTest(TempDirCase):
    def test_skips_lines_that_are_not_objects(self) -> None:
        path = self.root / "s.jsonl"
        path.write_text(
            '[1, 2]\n"text"\nnot json\n{"type": "user"}\n', encoding="utf-8"
        )
        self.assertEqual(scs.load_events(path), [{"type": "user"}])

    def test_request_logs_are_blanked(self) -> None:
        # Claude Code's api-request-blob replays the conversation; its tool
        # calls must not be counted a second time.
        call = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}
                ]
            },
        }
        rows = [call, {"type": "api-request-blob", "message": call["message"]}]
        path = self.root / "s.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        events = scs.load_events(path)
        self.assertEqual(events, [call, {}])
        self.assertEqual(len(scs.tool_calls(events)), 1)

    def test_a_vanished_transcript_is_skipped_not_counted(self) -> None:
        Transcript().user("hello").write(self.root, "-p", "present")
        files = scs.session_files(self.root, None, 3650)
        files.append((self.root / "-p" / "gone.jsonl", "-p"))
        sessions, skipped = scs.read_sessions(files)
        self.assertEqual([s["id"] for s in sessions], ["present"])
        self.assertEqual(skipped, [str(self.root / "-p" / "gone.jsonl")])

    def test_user_texts_survive_a_non_object_line(self) -> None:
        path = self.root / "s.jsonl"
        path.write_text(
            '[1]\n{"type": "user", "message": {"content": "no, not that"}}\n',
            encoding="utf-8",
        )
        self.assertEqual(scs.extract_user_texts(path), ["no, not that"])


class LearningEffectivenessTest(TempDirCase):
    def observation(self, opportunity="one", **states):
        return {
            "learning_id": "RT-test",
            "opportunity_id": opportunity,
            "evidence": "session:task:outcome",
            "adopted": True,
            "available": True,
            "loaded": True,
            "applicable": True,
            "applied": True,
            "success": True,
            **states,
        }

    def test_unloaded_and_unused_changes_are_not_failed_interventions(self):
        report = scs.learning_effectiveness(
            [
                self.observation(
                    "old-copy", loaded=False, applied=False, success=False
                ),
                self.observation(
                    "unused", applicable=False, applied=False, success=None
                ),
                self.observation("worked"),
                self.observation("did-not-help", success=False),
            ]
        )
        [learning] = report["learnings"]
        self.assertEqual(learning["tested_applications"], 2)
        self.assertEqual(learning["successful_applications"], 1)
        self.assertEqual(learning["failed_applications"], 1)
        self.assertEqual(learning["applicable_opportunities"], 3)
        self.assertEqual(learning["unassessed"], 2)

    def test_copied_observations_do_not_inflate_the_denominator(self):
        first = self.observation()
        report = scs.learning_effectiveness([first, dict(first)])
        self.assertEqual(report["duplicates_ignored"], 1)
        self.assertEqual(report["learnings"][0]["tested_applications"], 1)
        with self.assertRaises(ValueError):
            scs.learning_effectiveness([first, self.observation(success=False)])

    def test_no_matching_opportunity_keeps_effect_unassessed(self):
        report = scs.learning_effectiveness([self.observation(applicable=None)])
        [learning] = report["learnings"]
        self.assertEqual(learning["tested_applications"], 0)
        self.assertIsNone(learning["success_rate"])
        self.assertEqual(report["coverage"], "supplied_observations_only")

    def test_observations_need_evidence_and_boolean_states(self):
        for fields in ({"evidence": ""}, {"loaded": "yes"}, {"success": 1}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                scs.learning_effectiveness([self.observation(**fields)])

    def test_observations_cli_needs_no_host_project_directory(self):
        path = self.root / "observations.json"
        path.write_text(json.dumps([self.observation()]), encoding="utf-8")
        report = _run(self.root / "missing", "--learning-observations", str(path))
        self.assertEqual(report["mode"], "learning-effectiveness")
        self.assertEqual(report["learnings"][0]["tested_applications"], 1)


class CorrectionSummaryTest(TempDirCase):
    def test_counts_sessions_within_one_project(self) -> None:
        for session in ("a", "b"):
            Transcript().user("No, use the Read tool").write(self.root, "-p", session)
        out = _run(self.root, "--user-correction-summary")
        self.assertEqual(out["sessions_scanned"], 2)
        self.assertEqual(out["projects_scanned"], 1)
        [hit] = out["cross_session_corrections"]
        self.assertEqual(hit["sessions_count"], 2)
        self.assertEqual(hit["projects_count"], 1)
        self.assertEqual(hit["sessions"], ["a", "b"])
        self.assertEqual(out["cross_project_corrections"], [])

    def test_caps_the_cross_session_list(self) -> None:
        for session in ("a", "b"):
            Transcript().user("No, use the Read tool").user("Stop polling").write(
                self.root, "-p", session
            )
        out = _run(self.root, "--user-correction-summary", "--limit", "1")
        self.assertEqual(len(out["cross_session_corrections"]), 1)
        self.assertTrue(out["cross_session_truncated"])

    def test_a_single_session_is_not_recurring(self) -> None:
        Transcript().user("No, use the Read tool").user("no, use the read tool").write(
            self.root, "-p", "a"
        )
        out = _run(self.root, "--user-correction-summary")
        self.assertEqual(out["cross_session_corrections"], [])

    def _synthetic(self, transcript: Transcript, content, **flags) -> None:
        event = {"type": "user", "timestamp": transcript._ts()}
        event["message"] = {"role": "user", "content": content}
        transcript.events.append({**event, **flags})

    def test_harness_text_is_not_a_correction(self) -> None:
        # A-F3: every cross-session correction the review measured was
        # harness text stamped isMeta — `Stop hook feedback: …` matches
        # `^stop\b`. A human's correction in the same sessions still counts.
        for session in ("a", "b"):
            t = Transcript()
            self._synthetic(
                t, "Stop hook feedback:\nname the waiter before ending", isMeta=True
            )
            self._synthetic(t, "No, that is the summary", isCompactSummary=True)
            self._synthetic(
                t,
                [
                    {
                        "type": "text",
                        "text": "<command-message>pr-finish</command-message>",
                    },
                    {"type": "text", "text": "# /pr-finish\nno merge without green"},
                ],
            )
            t.user("No, use the Read tool").write(self.root, "-p", session)
        out = _run(self.root, "--user-correction-summary")
        self.assertEqual(
            [hit["snippet"] for hit in out["cross_session_corrections"]],
            ["no, use the read tool"],
        )

    def test_the_markers_match_detect_mechanicals(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "detect_mechanical", SCRIPT.parent / "detect-mechanical.py"
        )
        detector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(detector)
        self.assertEqual(scs.SYNTHETIC_USER_MARKERS, detector._SYNTHETIC_USER_MARKERS)


class FailureLineTest(unittest.TestCase):
    def test_takes_the_marked_line_of_a_bash_failure(self) -> None:
        result = "Exit code 1\nrunning checks\nfatal: not a git repository\ndone"
        self.assertEqual(
            scs.failure_line("Bash", result), "fatal: not a git repository"
        )

    def test_takes_the_last_line_of_a_traceback(self) -> None:
        result = (
            "Exit code 1\nTraceback (most recent call last):\n"
            "  File \"x.py\", line 3, in <module>\nKeyError: 'turn'"
        )
        self.assertEqual(scs.failure_line("Bash", result), "KeyError: 'turn'")

    def test_a_bare_exit_code_has_no_message(self) -> None:
        self.assertEqual(scs.failure_line("Bash", "Exit code 2"), "")

    def test_normalise_drops_values(self) -> None:
        self.assertEqual(
            scs.normalise(
                "ls: cannot access '/tmp/a/b': No such file (42) at 1a2b3c4d"
            ),
            "ls: cannot access '<path>': No such file (<n>) at <hex>",
        )
        # A slash inside a word is prose, not a path.
        self.assertEqual(scs.normalise("piped into tail/head"), "piped into tail/head")


class RecurringFailuresTest(TempDirCase):
    DENIAL = "`cat` to read a file. Use the Read tool."

    def _two_sessions(self) -> None:
        for session, path in (("a", "/x/one"), ("b", "/y/two")):
            (
                Transcript()
                .call(
                    "Bash",
                    {"command": "ls"},
                    f"Exit code 2\nls: cannot access '{path}': No such file or directory",
                    True,
                )
                .call("Bash", {"command": "cat f"}, self.DENIAL, True)
                .call(
                    "Bash",
                    {"command": "cat g"},
                    f"PreToolUse:Bash hook error: {self.DENIAL}",
                    True,
                )
                .call("Bash", {"command": "false"}, "Exit code 1", True)
                .write(self.root, "-p", session)
            )
        Transcript().call(
            "Bash", {"command": "x"}, "Exit code 1\nerror: only once here", True
        ).write(self.root, "-p", "c")

    def test_the_same_failure_in_two_sessions_is_one_finding(self) -> None:
        self._two_sessions()
        found = scs.recurring_failures(_sessions(self.root))
        [hit] = found["recurring"]
        self.assertEqual(hit["kind"], "failure")
        self.assertEqual(
            hit["error"], "ls: cannot access '<path>': No such file or directory"
        )
        self.assertEqual(hit["sessions"], ["a", "b"])

    def test_refusals_are_excluded_and_counted(self) -> None:
        self._two_sessions()
        found = scs.recurring_failures(_sessions(self.root))
        self.assertEqual(found["excluded"], {"refusals": 4, "without_message": 2})

    def test_refusals_with_and_without_prefix_share_a_key(self) -> None:
        self._two_sessions()
        found = scs.recurring_failures(_sessions(self.root), include_refusals=True)
        refusals = [r for r in found["recurring"] if r["kind"] == "refusal"]
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["sessions_count"], 2)

    def test_a_tool_use_error_is_a_failure_not_a_refusal(self) -> None:
        for session in ("a", "b"):
            Transcript().call(
                "Bash",
                {"command": "x"},
                "<tool_use_error>InputValidationError: command contains control characters</tool_use_error>",
                True,
            ).write(self.root, "-p", session)
        [hit] = scs.recurring_failures(_sessions(self.root))["recurring"]
        self.assertEqual(hit["kind"], "failure")

    def test_cli_caps_the_list(self) -> None:
        for session in ("a", "b"):
            t = Transcript()
            for word in ("alpha", "beta", "gamma"):
                t.call(
                    "Bash", {"command": "x"}, f"Exit code 1\nerror: {word} broke", True
                )
            t.write(self.root, "-p", session)
        out = _run(self.root, "--recurring-failures", "--limit", "2")
        self.assertEqual(len(out["recurring"]), 2)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["sessions_read"], 2)


def _git(*args: str) -> None:
    env = {k: v for k, v in os.environ.items() if k not in scs.GIT_LOCATION_VARS}
    subprocess.run(["git", *args], check=True, capture_output=True, env=env)


class FileKeyTest(TempDirCase):
    def test_worktrees_of_one_bare_repository_share_a_key(self) -> None:
        project = self.root / "proj"
        _git("init", "--bare", "-q", str(project / ".bare"))
        _git(
            "-C",
            str(project / ".bare"),
            "worktree",
            "add",
            "-q",
            "--orphan",
            "-b",
            "one",
            str(project / "one"),
        )
        live = scs.file_key(str(project / "one" / "docs" / "a.md"))
        # A removed worktree is recognised from the project directory that remains.
        removed = scs.file_key(str(project / "gone-branch" / "docs" / "a.md"))
        self.assertEqual(live, (str((project / ".bare").resolve()), "docs/a.md"))
        self.assertEqual(removed, live)

    def test_a_file_outside_any_repository_keeps_its_path(self) -> None:
        path = str(self.root / "loose" / "notes.md")
        self.assertEqual(scs.file_key(path), (None, path))

    def _bare_project(self) -> Path:
        project = self.root / "proj"
        _git("init", "--bare", "-q", str(project / ".bare"))
        return project

    def test_a_plain_directory_named_bare_is_no_repository(self) -> None:
        (self.root / "plain" / ".bare").mkdir(parents=True)
        path = str(self.root / "plain" / "gone" / "a.md")
        self.assertEqual(scs.file_key(path), (None, path))

    def test_the_bare_repository_wins_over_an_enclosing_work_tree(self) -> None:
        project = self._bare_project()
        _git("init", "-q", str(self.root))
        self.assertEqual(
            scs.file_key(str(project / "gone" / "docs" / "a.md")),
            (str((project / ".bare").resolve()), "docs/a.md"),
        )

    def test_git_dir_in_the_environment_does_not_redirect_the_probe(self) -> None:
        project = self._bare_project()
        other = self.root / "other"
        _git("init", "-q", str(other))
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            key = scs.file_key(str(project / "gone" / "docs" / "a.md"))
        self.assertEqual(key, (str((project / ".bare").resolve()), "docs/a.md"))

    # A-F8: the worktree of a branch with a slash (`fix/x`) sits in
    # `<project>/fix/x`. After `git worktree remove` its files must key like
    # every other worktree's: the bare repository and the path inside it.
    def _removed_slash_worktree(self) -> tuple[Path, Path]:
        project = self._bare_project()
        bare = project / ".bare"
        worktree = project / "fix" / "x"
        _git(
            "-C",
            str(bare),
            "worktree",
            "add",
            "-q",
            "--orphan",
            "-b",
            "fix/x",
            str(worktree),
        )
        _git(
            "-C",
            str(worktree),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.org",
            "commit",
            "-q",
            "--allow-empty",
            "--no-gpg-sign",
            "-m",
            "x",
        )
        _git("-C", str(bare), "worktree", "remove", str(worktree))
        return bare.resolve(), worktree

    def test_a_removed_slash_worktree_whose_parent_directory_remains(self) -> None:
        bare, worktree = self._removed_slash_worktree()
        self.assertTrue(worktree.parent.is_dir())  # the empty `fix/`
        self.assertEqual(scs.file_key(str(worktree / "a.txt")), (str(bare), "a.txt"))

    def test_a_removed_slash_worktree_is_found_by_its_branch(self) -> None:
        bare, worktree = self._removed_slash_worktree()
        worktree.parent.rmdir()
        self.assertEqual(
            scs.file_key(str(worktree / "docs" / "a.txt")), (str(bare), "docs/a.txt")
        )

    def test_a_remote_tracking_branch_outlives_the_local_one(self) -> None:
        bare, worktree = self._removed_slash_worktree()
        worktree.parent.rmdir()
        _git("-C", str(bare), "update-ref", "refs/remotes/origin/fix/x", "fix/x")
        _git("-C", str(bare), "branch", "-D", "fix/x")
        self.assertEqual(scs.file_key(str(worktree / "a.txt")), (str(bare), "a.txt"))

    def test_without_a_trace_the_first_directory_is_the_worktree(self) -> None:
        # The documented limit: branch deleted everywhere, `fix/` removed as
        # well — nothing says the worktree was two levels deep.
        bare, worktree = self._removed_slash_worktree()
        worktree.parent.rmdir()
        _git("-C", str(bare), "branch", "-D", "fix/x")
        self.assertEqual(scs.file_key(str(worktree / "a.txt")), (str(bare), "x/a.txt"))


class FollowUpSessionsTest(TempDirCase):
    WROTE = "the earlier session wrote this sentence"

    def _edit(self, day: int, session: str, old: str, new: str, path: str) -> None:
        Transcript(day).call(
            "Edit", {"file_path": path, "old_string": old, "new_string": new}, "ok"
        ).write(self.root, "-p", session)

    def _found(self, window_days: int = 7) -> dict:
        return scs.follow_up_sessions(_sessions(self.root), timedelta(days=window_days))

    def test_a_later_session_rewriting_earlier_text_is_found(self) -> None:
        path = str(self.root / "loose" / "a.md")
        self._edit(1, "a", "old text", self.WROTE, path)
        self._edit(3, "b", self.WROTE, "something else entirely", path)
        [hit] = self._found()["rewritten_edits"]
        self.assertEqual((hit["earlier_session"], hit["later_session"]), ("a", "b"))
        self.assertFalse(hit["exact_revert"])

    def test_an_exact_revert_is_marked_and_ranked_first(self) -> None:
        path = str(self.root / "loose" / "a.md")
        other = str(self.root / "loose" / "b.md")
        self._edit(1, "a", "old text", self.WROTE, path)
        Transcript(2).call(
            "MultiEdit",
            {
                "file_path": path,
                "edits": [{"old_string": self.WROTE, "new_string": "old text"}],
            },
            "ok",
        ).call(
            "Edit",
            {"file_path": other, "old_string": "x", "new_string": self.WROTE},
            "ok",
        ).write(self.root, "-p", "b")
        self._edit(3, "c", self.WROTE, "changed", other)
        hits = self._found()["rewritten_edits"]
        self.assertTrue(hits[0]["exact_revert"])
        self.assertEqual(hits[0]["file"], path)
        self.assertFalse(hits[1]["exact_revert"])

    def test_outside_the_window_nothing_is_found(self) -> None:
        path = str(self.root / "loose" / "a.md")
        self._edit(1, "a", "old text", self.WROTE, path)
        self._edit(20, "b", self.WROTE, "changed", path)
        self.assertEqual(self._found()["rewritten_edits"], [])
        self.assertEqual(len(self._found(window_days=30)["rewritten_edits"]), 1)

    def test_short_text_does_not_count(self) -> None:
        path = str(self.root / "loose" / "a.md")
        self._edit(1, "a", "old", "True", path)
        self._edit(2, "b", "return True", "return False", path)
        self.assertEqual(self._found()["rewritten_edits"], [])

    def test_a_failed_edit_does_not_count(self) -> None:
        path = str(self.root / "loose" / "a.md")
        self._edit(1, "a", "old text", self.WROTE, path)
        Transcript(2).call(
            "Edit",
            {"file_path": path, "old_string": self.WROTE, "new_string": "changed"},
            "String to replace not found in file.",
            is_error=True,
        ).write(self.root, "-p", "b")
        self.assertEqual(self._found()["rewritten_edits"], [])

    def test_a_revert_of_an_earlier_sessions_commit_is_found(self) -> None:
        Transcript(1).call(
            "Bash",
            {"command": "git commit -S -m 'feat: x'"},
            "[feat/x 1a2b3c4d] feat: x\n 1 file changed",
        ).write(self.root, "-p", "a")
        Transcript(2).call(
            "Bash",
            {"command": "git -C /r revert --no-edit 1a2b3c4"},
            "[main 9f8e7d6] Revert",
        ).write(self.root, "-p", "b")
        Transcript(2).call(
            "Bash", {"command": "git revert deadbee"}, "[main 1111111] Revert"
        ).write(self.root, "-p", "c")
        [hit] = self._found()["reverted_commits"]
        self.assertEqual(
            hit, {"commit": "1a2b3c4d", "earlier_session": "a", "later_session": "b"}
        )


if __name__ == "__main__":
    unittest.main()
