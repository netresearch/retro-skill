# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Tests for skills/retro/scripts/transcript-results.py and its three readers."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "retro" / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(
        "tr_" + name.replace("-", "_"), SCRIPTS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


results = load("transcript-results")

PR = "https://github.com/o/r/pull/283"


def shell(stdout="", stderr="", **more):
    """`toolUseResult` of a shell command, as Claude Code 2.1.330 stores it."""
    return {
        "stdout": stdout,
        "stderr": stderr,
        "interrupted": False,
        "isImage": False,
        "noOutputExpected": False,
        **more,
    }


def answer(stored, content="", is_error=False, virtual=True, use_id="repl_1"):
    """The user event of a nested call; keys as in a real transcript."""
    event = {
        "type": "user",
        "timestamp": "2026-11-25T11:43:30.000Z",
        "isVirtual": virtual,
        "turnCompanion": True,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": use_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
        "toolUseResult": stored,
    }
    if not virtual:
        del event["isVirtual"]
    return event


def call(command, use_id="repl_1"):
    return {
        "type": "assistant",
        "timestamp": "2026-11-25T11:43:29.000Z",
        "isVirtual": True,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": use_id,
                    "name": "Bash",
                    "input": {"command": command},
                }
            ],
        },
    }


def block(event):
    return event["message"]["content"][0]


class FillTest(unittest.TestCase):
    def test_a_shell_commands_output_is_filled_in(self):
        for stored, expected in (
            (shell("out"), "out"),
            (shell("out", "err"), "out\nerr"),
            (shell("", "err"), "err"),
            ("an MCP tool's text", "an MCP tool's text"),
        ):
            with self.subTest(expected=expected):
                filled = block(results.fill_nested_result(answer(stored)))
                self.assertEqual(filled["content"], expected)
                self.assertIs(filled["nested"], True)

    def test_a_command_that_runs_on_says_so(self):
        stored = shell("first line", backgroundTaskId="b1", timedOutAfterMs=3000)
        filled = block(results.fill_nested_result(answer(stored)))
        self.assertEqual(filled["content"], "first line\nCommand running in background")

    def test_anything_else_is_left_alone(self):
        for event in (
            answer(shell("x"), virtual=False),
            answer(shell("x"), content="Exit code 1", is_error=True),
            answer(shell("x"), content=[{"type": "text", "text": "y"}]),
            answer(shell("x", isImage=True)),
            answer(shell()),
            answer({"type": "text", "file": {"content": "x"}}),
            answer(None),
            answer([1]),
            {"isVirtual": True, "message": "text", "toolUseResult": shell("x")},
            {"isVirtual": True, "message": {"content": "text"}},
            {},
        ):
            before = json.dumps(event)
            with self.subTest(event=before):
                self.assertEqual(json.dumps(results.fill_nested_result(event)), before)

    def test_two_results_in_one_event_are_left_alone(self):
        event = answer(shell("x"))
        event["message"]["content"].append(dict(block(event), tool_use_id="repl_2"))
        before = json.dumps(event)
        self.assertEqual(json.dumps(results.fill_nested_result(event)), before)


class ReadersTest(unittest.TestCase):
    def transcript(self, *events):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "s.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in events), "utf-8")
        return path

    def test_a_created_pr_is_read_from_the_output(self):
        scope = load("derive-session-scope")
        path = self.transcript(
            call("gh pr create --draft --title x --body-file y"),
            answer(shell(PR)),
        )
        data = scope.collect_artefacts(path)
        self.assertEqual(
            {a["url"]: a["origin"] for a in data["artefacts"]}, {PR: "created"}
        )
        self.assertEqual(data["unresolved_forge_commands"], [])

    def test_a_create_in_the_background_stays_unresolved(self):
        scope = load("derive-session-scope")
        path = self.transcript(
            call("gh pr create --draft --title x --body-file y"),
            answer(shell("", backgroundTaskId="b1")),
        )
        self.assertEqual(
            len(scope.collect_artefacts(path)["unresolved_forge_commands"]), 1
        )

    def test_the_detector_reads_an_error_text_and_no_verbose_output(self):
        detect = load("detect-mechanical")
        path = self.transcript(
            call("git status; true"),
            answer(shell("fatal: not a git repository")),
            call("seq 99999", "repl_2"),
            answer(shell("x" * 200_000), use_id="repl_2"),
        )
        uses = detect.extract_tool_uses(detect.load_jsonl(path))
        self.assertEqual([u[3][:6] for u in uses], ["fatal:", "xxxxxx"])
        self.assertEqual(len(detect.signal_tool_errors(uses)), 1)
        self.assertEqual(detect.signal_verbose_results(uses), [])

    def test_a_direct_calls_verbose_output_is_still_found(self):
        detect = load("detect-mechanical")
        path = self.transcript(
            call("seq 99999"), answer(None, content="x" * 200_000, virtual=False)
        )
        uses = detect.extract_tool_uses(detect.load_jsonl(path))
        self.assertEqual(len(detect.signal_verbose_results(uses)), 1)

    def test_the_cross_session_scan_reads_the_output(self):
        scan = load("scan-cross-session")
        path = self.transcript(call("ls"), answer(shell("listing")))
        [found] = scan.tool_calls(scan.load_events(path))
        self.assertEqual(found["result"], "listing")


if __name__ == "__main__":
    unittest.main()
