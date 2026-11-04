# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""A21 (a write into an auto-memory store) and the request-log events that
replay earlier messages in a Claude Code transcript."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_detect_mechanical import detect, tool_use_pair, write_jsonl

# Case 1: the Edit a real session made to a memory note on 2026-11-04,
# copied from its transcript.
REAL_EDIT = {
    "replace_all": False,
    "file_path": "/home/cybot/.claude/projects/-home-cybot-projects/memory/feedback_matrix_jira_reactions.md",
    "old_string": '- always 🤖 next to it, so humans see an agent set the reaction (user rule 2026-10-31: "only ONE of ▶️ or 🩹 or ✅")',
    "new_string": '- always 🤖 next to it: an agent works or worked on this ticket (user correction 2026-11-04: it marks the ticket as agent work, NOT "an agent set this reaction" and NOT the generic read-receipt meaning of 🤖 in matrix-communication\'s messaging-guide). User rule 2026-10-31: "only ONE of ▶️ or 🩹 or ✅"',
}


def a21(events):
    path = write_jsonl(events)
    try:
        return detect.signal_memory_store_write(
            detect.extract_tool_uses(detect.load_jsonl(path))
        )
    finally:
        path.unlink(missing_ok=True)


class MemoryStoreWriteTest(unittest.TestCase):
    def test_real_edit_of_a_memory_note_fires(self):
        out = a21(tool_use_pair("t1", "Edit", REAL_EDIT, "updated"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["signal"], "A21")
        self.assertEqual(out[0]["slug"], "-home-cybot-projects")
        self.assertFalse(out[0]["index"])

    def test_project_store_write_fires(self):
        path = "/home/u/.claude/projects/-home-u-projects-go-cron/memory/adr.md"
        out = a21(
            tool_use_pair("t1", "Write", {"file_path": path, "content": "x"}, "ok")
        )
        self.assertEqual([f["slug"] for f in out], ["-home-u-projects-go-cron"])

    def test_one_finding_per_file_with_every_turn(self):
        events = []
        for n in range(3):
            events += tool_use_pair(f"t{n}", "Edit", REAL_EDIT, "ok")
        out = a21(events)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["turns"]), 3)

    def test_index_file_is_marked(self):
        path = "/home/u/.claude/projects/-p/memory/MEMORY.md"
        out = a21(tool_use_pair("t1", "Edit", {"file_path": path}, "ok"))
        self.assertTrue(out[0]["index"])

    def test_tombstone_and_other_paths_do_not_fire(self):
        events = tool_use_pair(
            "t1",
            "Write",
            {"file_path": "/home/u/.claude/projects/-p/memory/.promoted/x.md"},
            "ok",
        )
        events += tool_use_pair(
            "t2", "Write", {"file_path": "/home/u/.claude/projects/-p/abc.jsonl"}, "ok"
        )
        events += tool_use_pair("t3", "Edit", {"file_path": "/repo/AGENTS.md"}, "ok")
        self.assertEqual(a21(events), [])

    def test_windows_paths_fire(self):
        # Paths as native Windows Claude Code wrote them (2026-07).
        note = "C:\\Users\\live\\.claude\\projects\\F--foo\\memory\\wsl-mcp-oom-2026-07-01.md"
        index = "C:\\Users\\live\\.claude\\projects\\F--foo\\memory\\MEMORY.md"
        tomb = "C:\\Users\\live\\.claude\\projects\\F--foo\\memory\\.promoted\\x.md"
        events = tool_use_pair("t1", "Write", {"file_path": note}, "ok")
        events += tool_use_pair("t2", "Edit", {"file_path": index}, "ok")
        events += tool_use_pair("t3", "Write", {"file_path": tomb}, "ok")
        out = a21(events)
        self.assertEqual(
            [(f["slug"], f["index"]) for f in out],
            [("F--foo", False), ("F--foo", True)],
        )

    def test_reading_a_note_does_not_fire(self):
        self.assertEqual(
            a21(tool_use_pair("t1", "Read", {"file_path": REAL_EDIT["file_path"]}, "")),
            [],
        )


class RequestLogEventsTest(unittest.TestCase):
    """`api-request-blob` replays messages; it must not count a call twice."""

    def test_replayed_call_is_counted_once(self):
        events = tool_use_pair("t1", "Edit", REAL_EDIT, "ok")
        # The blob carries the same message again, as Claude Code writes it.
        events += [
            {
                "type": "api-request-blob",
                "message": {
                    "role": e["message"].get("role", e["type"]),
                    "content": e["message"]["content"],
                },
            }
            for e in events
        ]
        events.append({"type": "api-request", "message": events[0]["message"]})
        path = write_jsonl(events)
        try:
            loaded = detect.load_jsonl(path)
            self.assertEqual(len(loaded), len(events))  # positions kept
            self.assertEqual(len(detect.extract_tool_uses(loaded)), 1)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(a21(events)[0]["turns"]), 1)

    def test_replayed_user_text_is_not_a_repetition(self):
        msg = {
            "type": "user",
            "message": {
                "content": [{"type": "text", "text": "please fix the reaction rule"}]
            },
        }
        events = [msg, {"type": "api-request-blob", "message": msg["message"]}]
        path = write_jsonl(events)
        try:
            texts = detect.extract_user_texts(detect.load_jsonl(path))
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(texts), 1)
        self.assertEqual(detect.signal_prompt_repetition(texts), [])


class DetectorRegistryTest(unittest.TestCase):
    def test_a21_runs_by_default(self):
        self.assertIs(detect.SIGNAL_FUNCS["A21"], detect.signal_memory_store_write)

    def test_cli_reports_a21(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(e) for e in tool_use_pair("t1", "Edit", REAL_EDIT, "ok")
                ),
                encoding="utf-8",
            )
            import contextlib
            import io
            import sys

            argv, out = sys.argv, io.StringIO()
            sys.argv = [
                "detect-mechanical.py",
                "--transcript-file",
                str(path),
                "--signals",
                "A21",
            ]
            try:
                with contextlib.redirect_stdout(out):
                    rc = detect.main()
            finally:
                sys.argv = argv
        self.assertEqual(rc, 0)
        self.assertEqual(
            [f["signal"] for f in json.loads(out.getvalue())["findings"]], ["A21"]
        )


if __name__ == "__main__":
    unittest.main()
