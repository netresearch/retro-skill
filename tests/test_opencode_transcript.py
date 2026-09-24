"""Tests for skills/retro/scripts/opencode-transcript.py.

Builds a tiny opencode database under `tempfile` and asserts the JSONL the adapter
renders. The load-bearing case is the LAST one: the detector is run over the
rendered transcript, because a `tool_use` block without an `id` makes it raise
`KeyError: 'id'` on the first tool call — which is exactly how the mapping was
discovered, by running it rather than by reading it.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _load(name: str, filename: str):
    """Import a hyphenated script by path, the way `test_detect_mechanical.py` does."""
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "skills" / "retro" / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load("opencode_transcript", "opencode-transcript.py")
detector = _load("detect_mechanical", "detect-mechanical.py")


def _database(path: str) -> None:
    """A real opencode database, only as wide as the adapter reads."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)"
    )
    conn.execute(
        "CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT,"
        " time_created INTEGER, data TEXT)"
    )
    rows = [
        ("m1", "s1", 1, {"role": "user"}),
        ("m2", "s1", 2, {"role": "assistant"}),
    ]
    for message_id, session_id, created, data in rows:
        conn.execute(
            "INSERT INTO message VALUES (?,?,?,?)",
            (message_id, session_id, created, json.dumps(data)),
        )
    parts = [
        ("p1", "m1", "s1", {"type": "text", "text": "please fix the CLI"}),
        ("p2", "m2", "s1", {"type": "text", "text": "looking"}),
        (
            "p3",
            "m2",
            "s1",
            {
                "type": "tool",
                "tool": "bash",
                "id": "call-1",
                "state": {
                    "status": "completed",
                    "input": {"command": "ls"},
                    "output": "boom",
                },
            },
        ),
    ]
    for index, (part_id, message_id, session_id, data) in enumerate(parts, start=1):
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?)",
            (part_id, message_id, session_id, index, json.dumps(data)),
        )
    conn.commit()
    conn.close()


def _tool_part(path: str, part_id: str, call_id: str, state: dict) -> None:
    """One more tool part on the assistant message, for the cases that need a second call."""
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO part VALUES (?,?,?,?,?)",
        (
            part_id,
            "m2",
            "s1",
            9,
            json.dumps({"type": "tool", "tool": "bash", "id": call_id, "state": state}),
        ),
    )
    conn.commit()
    conn.close()


class OpencodeTranscriptTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(Path(tmp.name) / "opencode.db")
        _database(self.db)

    def test_a_tool_part_becomes_a_tool_use_and_a_matching_tool_result(self) -> None:
        conn = adapter._connect(self.db)
        lines = [json.loads(line) for line in adapter.render(conn, "s1")]

        kinds = [
            block["type"] for line in lines for block in line["message"]["content"]
        ]
        self.assertIn("tool_use", kinds)
        self.assertIn("tool_result", kinds)

        uses = [
            b
            for line in lines
            for b in line["message"]["content"]
            if b["type"] == "tool_use"
        ]
        results = [
            b
            for line in lines
            for b in line["message"]["content"]
            if b["type"] == "tool_result"
        ]
        self.assertEqual(uses[0]["name"], "bash")
        self.assertEqual(uses[0]["id"], "call-1")
        # The detector pairs them BY ID, so a missing one is the whole defect.
        self.assertEqual(results[0]["tool_use_id"], uses[0]["id"])

    def test_the_session_is_found_by_content_and_an_unknown_token_is_refused(
        self,
    ) -> None:
        conn = adapter._connect(self.db)
        self.assertEqual(adapter.find_session(conn, "fix the CLI"), "s1")
        with self.assertRaises(SystemExit):
            adapter.find_session(conn, "a token that is nowhere")

    def test_a_path_carrying_a_query_cannot_override_the_read_only_mode(self) -> None:
        """`mode=ro` is what the READ-ONLY promise rests on; an unencoded path drops it."""
        hostile = str(Path(self.db).parent / "opencode.db?mode=rwc&")
        Path(hostile).write_bytes(Path(self.db).read_bytes())

        conn = adapter._connect(hostile)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE injected (x)")

    def test_a_like_wildcard_in_the_token_matches_only_itself(self) -> None:
        """`_` is a LIKE wildcard: unescaped, `fix_the` would also find `fix the`."""
        with self.assertRaises(SystemExit):
            adapter.find_session(adapter._connect(self.db), "fix_the")

    def test_an_unfinished_tool_call_produces_no_result_block(self) -> None:
        """A `running` part has neither output nor error; a result for it reads as success."""
        _tool_part(
            self.db,
            "p4",
            "call-2",
            {"status": "running", "input": {"command": "sleep"}},
        )

        lines = [
            json.loads(line) for line in adapter.render(adapter._connect(self.db), "s1")
        ]
        results = [
            b
            for line in lines
            for b in line["message"]["content"]
            if b["type"] == "tool_result"
        ]
        self.assertEqual([r["tool_use_id"] for r in results], ["call-1"])

    def test_an_over_long_output_keeps_its_head_and_its_tail(self) -> None:
        """The comment on RESULT_CHARS promises both ends; a plain slice keeps only one."""
        _tool_part(
            self.db,
            "p5",
            "call-3",
            {
                "status": "completed",
                "input": {"command": "build"},
                "output": "E" * adapter.RESULT_CHARS + "T" * adapter.RESULT_CHARS,
            },
        )

        lines = [
            json.loads(line) for line in adapter.render(adapter._connect(self.db), "s1")
        ]
        content = next(
            b["content"]
            for line in lines
            for b in line["message"]["content"]
            if b.get("tool_use_id") == "call-3"
        )
        self.assertTrue(content.startswith("E"))
        self.assertTrue(content.endswith("T"))
        self.assertLessEqual(len(content), adapter.RESULT_CHARS + 3)

    def test_an_unknown_session_id_is_refused_rather_than_rendered_empty(self) -> None:
        with self.assertRaises(SystemExit):
            adapter.main(["--session", "no-such-session", "--db", self.db])

    def test_the_detector_accepts_the_rendered_transcript(self) -> None:
        """The shape is only right if the CONSUMER takes it: no `KeyError: 'id'`."""
        conn = adapter._connect(self.db)
        out = Path(self.db).parent / "session.jsonl"
        out.write_text("\n".join(adapter.render(conn, "s1")) + "\n", encoding="utf-8")

        events = detector.load_jsonl(out)
        self.assertTrue(events)
        self.assertEqual(len(detector.extract_tool_uses(events)), 1)


def _v2_tool(call_id: str, state: dict) -> dict:
    return {
        "type": "tool",
        "id": call_id,
        "name": "bash",
        "state": state,
        "time": {"created": 1},
    }


#: One V2 session in the shape of opencode v2.0.15's
#: `packages/schema/src/session-message.ts`: `data` carries neither `id` nor
#: `type` (both are columns), and tool output is `state.content[]`.
V2_ROWS = [
    ("msg1", "user", 1, {"text": "please fix the parser", "time": {"created": 1}}),
    ("msg2", "agent-switched", 2, {"agent": "build", "time": {"created": 2}}),
    (
        "msg3",
        "assistant",
        4,
        {
            "agent": "build",
            "time": {"created": 4},
            "content": [
                {"type": "reasoning", "text": "thinking it over"},
                {"type": "text", "text": "running the tests"},
                _v2_tool(
                    "call-ok",
                    {
                        "status": "completed",
                        "input": {"command": "make test"},
                        "content": [
                            {"type": "text", "text": "3 passed"},
                            {
                                "type": "file",
                                "uri": "file:///tmp/log",
                                "mime": "text/plain",
                                "name": "log",
                            },
                        ],
                    },
                ),
                _v2_tool(
                    "call-bad",
                    {
                        "status": "error",
                        "input": {"command": "make lint"},
                        "error": {"type": "unknown", "message": "lint failed"},
                    },
                ),
                _v2_tool("call-live", {"status": "streaming", "input": '{"comm'}),
            ],
        },
    ),
]


def _v2_database(path: str, rows: list = V2_ROWS, session_id: str = "ses_v2") -> None:
    """The V2 tables, only as wide as the adapter reads."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS session_v2 (id TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_message (id TEXT PRIMARY KEY, session_id TEXT,"
        " type TEXT, seq INTEGER, time_created INTEGER, time_updated INTEGER, data TEXT)"
    )
    conn.execute("INSERT INTO session_v2 VALUES (?)", (session_id,))
    # Inserted out of `seq` order, with `time_created` inverted, so a render
    # that sorts by anything but `seq` shows it.
    for message_id, kind, seq, data in reversed(rows):
        conn.execute(
            "INSERT INTO session_message VALUES (?,?,?,?,?,?,?)",
            (message_id, session_id, kind, seq, 100 - seq, 100 - seq, json.dumps(data)),
        )
    conn.commit()
    conn.close()


def _blocks(lines: list[str]) -> list[dict]:
    return [block for line in lines for block in json.loads(line)["message"]["content"]]


class OpencodeV2TranscriptTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = str(self.dir / "opencode.db")
        _v2_database(self.db)

    def _main(self, *argv: str) -> list[str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(adapter.main([*argv, "--db", self.db]), 0)
        return [line for line in out.getvalue().splitlines() if line]

    def test_a_v2_session_id_renders_instead_of_being_refused(self) -> None:
        """The reported failure: `no messages for session` on every V2 id.

        The reporter's database carried the legacy tables with 0 rows beside
        the V2 ones, which is what made the refusal read as a missing session.
        """
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)"
        )
        conn.execute(
            "CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT, time_created INTEGER, data TEXT)"
        )
        conn.commit()
        conn.close()

        lines = self._main("--session", "ses_v2")
        roles = [json.loads(line)["message"]["role"] for line in lines]
        self.assertEqual(roles, ["user", "assistant", "user"])

    def test_the_v2_session_is_found_by_content(self) -> None:
        self.assertEqual(
            adapter.find_session(adapter._connect(self.db), "fix the parser"), "ses_v2"
        )

    def test_v2_rows_render_in_seq_order_with_role_from_the_type_column(self) -> None:
        lines = adapter.render(adapter._connect(self.db), "ses_v2")
        texts = [b["text"] for b in _blocks(lines) if b["type"] == "text"]
        # `reasoning` and the `agent-switched` row are not rendered.
        self.assertEqual(texts, ["please fix the parser", "running the tests"])

    def test_v2_tool_blocks_become_paired_uses_and_results(self) -> None:
        blocks = _blocks(adapter.render(adapter._connect(self.db), "ses_v2"))
        uses = {b["id"]: b for b in blocks if b["type"] == "tool_use"}
        results = {b["tool_use_id"]: b for b in blocks if b["type"] == "tool_result"}

        self.assertEqual(sorted(uses), ["call-bad", "call-live", "call-ok"])
        self.assertEqual(uses["call-ok"]["name"], "bash")
        self.assertEqual(uses["call-ok"]["input"], {"command": "make test"})
        # Output is `state.content[]`; an error is `state.error.message`.
        self.assertEqual(results["call-ok"]["content"], "3 passed\n[file log]")
        self.assertFalse(results["call-ok"]["is_error"])
        self.assertEqual(results["call-bad"]["content"], "lint failed")
        self.assertTrue(results["call-bad"]["is_error"])
        # A `streaming` call is unfinished: no result, and its string input is
        # not passed on, because the detector reads `input` as a dict.
        self.assertNotIn("call-live", results)
        self.assertEqual(uses["call-live"]["input"], {})

    def test_a_database_with_both_schemas_resolves_a_session_of_either(self) -> None:
        """An upgraded database keeps `message` + `part` beside the V2 tables."""
        _database(self.db)
        conn = adapter._connect(self.db)
        self.assertEqual(adapter.schema_of(conn, "ses_v2"), "v2")
        self.assertEqual(adapter.schema_of(conn, "s1"), "legacy")
        self.assertEqual(adapter.find_session(conn, "fix the CLI"), "s1")
        self.assertIn(
            "tool_use", [b["type"] for b in _blocks(adapter.render(conn, "s1"))]
        )
        self.assertEqual(len(self._main("--session", "ses_v2")), 3)

    def test_a_database_with_neither_schema_is_refused_by_name(self) -> None:
        empty = str(self.dir / "empty.db")
        sqlite3.connect(empty).execute("CREATE TABLE unrelated (x)").connection.commit()
        for argv in (["--session", "ses_v2"], ["--match", "anything"]):
            with self.assertRaises(SystemExit) as raised:
                adapter.main([*argv, "--db", empty])
            self.assertIn("no supported schema", str(raised.exception))

    def test_the_detector_accepts_the_rendered_v2_transcript(self) -> None:
        """The consumer contract, run end to end through the detector's own CLI."""
        out = self.dir / "session.jsonl"
        out.write_text(
            "\n".join(adapter.render(adapter._connect(self.db), "ses_v2")) + "\n",
            encoding="utf-8",
        )
        # The detector pairs a use with its result; the `streaming` call has none.
        paired = detector.extract_tool_uses(detector.load_jsonl(out))
        self.assertEqual(
            [(name, err) for _, name, _, _, err in paired],
            [("bash", False), ("bash", True)],
        )

        script = Path(detector.__file__)
        run = subprocess.run(
            [sys.executable, str(script), "--transcript-file", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        json.loads(run.stdout)


if __name__ == "__main__":
    unittest.main()
