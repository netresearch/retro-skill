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
        # opencode's `bash` under the name the detector's shell signals match.
        self.assertEqual(uses[0]["name"], "Bash")
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

    def test_a_synthetic_text_part_is_not_rendered_as_the_users_words(self) -> None:
        """opencode injects `synthetic` parts; the detector would read them as corrections."""
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?)",
            (
                "p6",
                "m1",
                "s1",
                0,
                json.dumps(
                    {"type": "text", "text": "[SYSTEM DIRECTIVE]", "synthetic": True}
                ),
            ),
        )
        conn.commit()
        conn.close()

        lines = adapter.render(adapter._connect(self.db), "s1")
        texts = [
            b["text"]
            for line in lines
            for b in json.loads(line)["message"]["content"]
            if b["type"] == "text"
        ]
        self.assertEqual(texts, ["please fix the CLI", "looking"])

    def test_a_relative_file_path_resolves_against_the_session_directory(self) -> None:
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE session (id TEXT, directory TEXT)")
        conn.execute("INSERT INTO session VALUES ('s1', '/repo')")
        state = {
            "status": "completed",
            "input": {"filePath": "src/app.py"},
            "output": "x",
        }
        conn.execute(
            "INSERT INTO part VALUES (?,?,?,?,?)",
            (
                "p7",
                "m2",
                "s1",
                8,
                json.dumps(
                    {"type": "tool", "tool": "read", "id": "c7", "state": state}
                ),
            ),
        )
        conn.commit()
        conn.close()

        lines = adapter.render(adapter._connect(self.db), "s1")
        read = next(
            b
            for line in lines
            for b in json.loads(line)["message"]["content"]
            if b.get("id") == "c7"
        )
        self.assertEqual(
            (read["name"], read["input"]), ("Read", {"file_path": "/repo/src/app.py"})
        )

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


def _v2_tool(call_id: str, state: dict, name: str = "shell") -> dict:
    """A tool block; `shell` is what opencode 2.x names its shell tool."""
    return {
        "type": "tool",
        "id": call_id,
        "name": name,
        "state": state,
        "time": {"created": 1},
    }


def _v2_assistant(*content: dict) -> dict:
    return {"agent": "build", "time": {"created": 4}, "content": list(content)}


#: One V2 session in the shape of opencode v2.0.15's
#: `packages/schema/src/session-message.ts`: `data` carries neither `id` nor
#: `type` (both are columns), and tool output is `state.content[]`. The row ids
#: sort AGAINST `seq`, so a render ordered by id shows it.
V2_ROWS = [
    ("msg_z", "user", 1, {"text": "please fix the parser", "time": {"created": 1}}),
    ("msg_y", "agent-switched", 2, {"agent": "build", "time": {"created": 2}}),
    ("msg_x", "synthetic", 3, {"text": "[injected]", "time": {"created": 3}}),
    (
        "msg_w",
        "assistant",
        4,
        _v2_assistant(
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
                    "content": [{"type": "text", "text": "2 findings"}],
                },
            ),
            _v2_tool(
                "call-run",
                {"status": "running", "input": {"command": "sleep"}, "metadata": {}},
            ),
            _v2_tool("call-live", {"status": "streaming", "input": '{"comm'}),
        ),
    ),
]


def _v2_database(
    path: str,
    rows: list = V2_ROWS,
    session_id: str = "ses_v2",
    directory: str = "/repo",
    parent: str | None = None,
    copied: int = 0,
) -> None:
    """The V2 tables, only as wide as the adapter reads.

    A fork (`parent`) carries its parent's rows up to `seq` `copied` under the
    ids opencode gives them, `<event id>_<seq>`.
    """
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_v2"
        " (id TEXT PRIMARY KEY, directory TEXT, fork_session_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_message (id TEXT PRIMARY KEY, session_id TEXT,"
        " type TEXT, seq INTEGER, time_created INTEGER, time_updated INTEGER, data TEXT)"
    )
    conn.execute(
        "INSERT INTO session_v2 VALUES (?, ?, ?)", (session_id, directory, parent)
    )
    # Inserted out of `seq` order, with `time_created` inverted, so a render
    # that sorts by anything but `seq` shows it.
    for message_id, kind, seq, data in reversed(rows):
        conn.execute(
            "INSERT INTO session_message VALUES (?,?,?,?,?,?,?)",
            (
                f"msg_fork{session_id}_{seq}"
                if seq <= copied
                else f"{message_id}_{session_id}",
                session_id,
                kind,
                seq,
                100 - seq,
                100 - seq,
                json.dumps(data),
            ),
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

    def _render(self, session_id: str = "ses_v2") -> list[str]:
        return adapter.render(adapter._connect(self.db), session_id)

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
        texts = [b["text"] for b in _blocks(self._render()) if b["type"] == "text"]
        # `reasoning`, `synthetic` and `agent-switched` are not rendered.
        self.assertEqual(texts, ["please fix the parser", "running the tests"])

    def test_v2_tool_blocks_become_paired_uses_and_results(self) -> None:
        blocks = _blocks(self._render())
        uses = {b["id"]: b for b in blocks if b["type"] == "tool_use"}
        results = {b["tool_use_id"]: b for b in blocks if b["type"] == "tool_result"}

        self.assertEqual(sorted(uses), ["call-bad", "call-live", "call-ok", "call-run"])
        self.assertEqual(uses["call-ok"]["name"], "Bash")
        self.assertEqual(uses["call-ok"]["input"], {"command": "make test"})
        # Output is `state.content[]`; an error is `state.error.message`, first.
        self.assertEqual(results["call-ok"]["content"], "3 passed\n[file log]")
        self.assertFalse(results["call-ok"]["is_error"])
        self.assertEqual(results["call-bad"]["content"], "lint failed\n2 findings")
        self.assertTrue(results["call-bad"]["is_error"])
        # `running` and `streaming` calls are unfinished: no result. A result
        # would file them as successful commands.
        self.assertEqual(sorted(results), ["call-bad", "call-ok"])
        # A `streaming` call's string input is not passed on, because the
        # detector reads `input` as a dict.
        self.assertEqual(uses["call-live"]["input"], {})

    def test_a_database_with_both_schemas_resolves_a_session_of_either(self) -> None:
        """A 1.x session that was never copied into V2 still renders from legacy."""
        _database(self.db)
        conn = adapter._connect(self.db)
        self.assertEqual(adapter.schema_of(conn, "ses_v2"), "v2")
        self.assertEqual(adapter.schema_of(conn, "s1"), "legacy")
        self.assertEqual(adapter.find_session(conn, "fix the CLI"), "s1")
        self.assertIn("tool_use", [b["type"] for b in _blocks(self._render("s1"))])
        self.assertEqual(len(self._main("--session", "ses_v2")), 3)

    def test_a_session_in_both_schemas_renders_from_v2(self) -> None:
        """opencode 2.x copies a 1.x session into V2 under the same id.

        The V2 copy is the one 2.x goes on writing to. The call that was still
        running at the upgrade is copied as a `tool.interrupted` error; like
        the legacy `running` call, it gets no result.
        """
        _database(self.db)
        _v2_database(
            self.db,
            [
                (
                    "m1",
                    "user",
                    1,
                    {"text": "please fix the CLI", "time": {"created": 1}},
                ),
                (
                    "m2",
                    "assistant",
                    2,
                    _v2_assistant(
                        {"type": "text", "text": "continued after the upgrade"},
                        _v2_tool(
                            "call-cut",
                            {
                                "status": "error",
                                "input": {"command": "sleep"},
                                "error": {
                                    "type": "tool.interrupted",
                                    "message": "Tool execution was interrupted before V2 migration",
                                },
                            },
                        ),
                    ),
                ),
            ],
            session_id="s1",
        )
        conn = adapter._connect(self.db)
        self.assertEqual(adapter.schema_of(conn, "s1"), "v2")

        blocks = _blocks(self._render("s1"))
        self.assertIn("continued after the upgrade", [b.get("text") for b in blocks])
        self.assertEqual([b for b in blocks if b["type"] == "tool_result"], [])

    def test_a_database_with_neither_schema_is_refused_by_name(self) -> None:
        empty = str(self.dir / "empty.db")
        sqlite3.connect(empty).execute("CREATE TABLE unrelated (x)").connection.commit()
        for argv in (["--session", "ses_v2"], ["--match", "anything"]):
            with self.assertRaises(SystemExit) as raised:
                adapter.main([*argv, "--db", empty])
            self.assertIn("no supported schema", str(raised.exception))

    def _tool_uses(self, *calls: tuple[str, dict]) -> list:
        """The detector's tool uses for completed `(name, input)` calls, one turn each."""
        self._sessions = getattr(self, "_sessions", 0) + 1
        session_id = f"ses_sig{self._sessions}"
        rows = [
            (
                f"m{n}",
                "assistant",
                n,
                _v2_assistant(
                    _v2_tool(
                        f"call-{n}",
                        {
                            "status": "completed",
                            "input": inputs,
                            "content": [{"type": "text", "text": "ok"}],
                        },
                        name=name,
                    )
                ),
            )
            for n, (name, inputs) in enumerate(calls, start=1)
        ]
        _v2_database(self.db, rows, session_id)
        out = self.dir / f"{session_id}.jsonl"
        out.write_text("\n".join(self._render(session_id)) + "\n", encoding="utf-8")
        return detector.extract_tool_uses(detector.load_jsonl(out))

    def test_opencode_2x_tools_reach_the_detectors_shell_and_file_signals(self) -> None:
        """2.x names its shell tool `shell` and its file key `path`.

        The detector's signals match Claude's `Bash` and `file_path`. Under
        opencode's names A14 stays silent on a push to main, and A12 files
        every read under an empty path, so two different files look re-read.
        """
        uses = self._tool_uses(
            ("read", {"path": "app.py"}),
            ("read", {"path": "lib.py"}),
            ("read", {"path": "/repo/app.py"}),
            ("shell", {"command": "git push origin main"}),
            ("grep", {"pattern": "x", "path": "src"}),
            ("glob", {"pattern": "*.py"}),
            ("skill", {"name": "retro"}),
        )
        # A5 reads `Grep`/`Glob`, A10 reads `Skill`.
        self.assertEqual([u[1] for u in uses[-3:]], ["Grep", "Glob", "Skill"])
        # On `grep` the `path` is a directory, not a file: it keeps its key.
        self.assertEqual(uses[-3][2], {"pattern": "x", "path": "src"})
        # `app.py` resolves against the session directory `/repo`.
        reread = detector.signal_reread_same_file(uses)
        self.assertEqual([f["path"] for f in reread], ["/repo/app.py"])
        pushes = detector.signal_main_branch_work(uses)
        self.assertEqual([f["signal"] for f in pushes], ["A14"])

    def test_migrated_1x_tools_reach_the_same_signals(self) -> None:
        """A migrated session keeps the 1.x names: `bash` and `filePath`."""
        uses = self._tool_uses(
            ("read", {"filePath": "/repo/app.py"}),
            ("read", {"filePath": "/repo/app.py"}),
            ("bash", {"command": "git push origin main"}),
        )
        reread = detector.signal_reread_same_file(uses)
        self.assertEqual([f["path"] for f in reread], ["/repo/app.py"])
        pushes = detector.signal_main_branch_work(uses)
        self.assertEqual([f["signal"] for f in pushes], ["A14"])

    def test_a_patch_between_two_reads_is_an_edit_of_every_file_it_names(self) -> None:
        """Without it, read → patch → read looks like a re-read without an edit."""
        # The example from opencode's `packages/core/src/tool/patch.txt`, shortened.
        patch = (
            "*** Begin Patch\n"
            "*** Add File: new.py\n"
            "+x = 1\n"
            "*** Update File: app.py\n"
            "*** Move to: main.py\n"
            "@@\n"
            "-a\n"
            "+b\n"
            "*** Delete File: old.py\n"
            "*** End Patch"
        )
        read = ("read", {"path": "/repo/app.py"})
        for name in ("patch", "apply_patch"):
            uses = self._tool_uses(read, (name, {"patchText": patch}), read)
            self.assertEqual(
                uses[1][2]["file_paths"],
                ["/repo/new.py", "/repo/app.py", "/repo/main.py", "/repo/old.py"],
            )
            self.assertEqual(detector.signal_reread_same_file(uses), [], name)
        # The control: the same two reads with no patch between them.
        self.assertNotEqual(
            detector.signal_reread_same_file(self._tool_uses(read, read)), []
        )

    def test_a_1x_patch_header_without_a_space_still_names_its_file(self) -> None:
        """1.x's parser matches `*** Update File:` and trims; the space is optional."""
        # A header with no name at all names no file.
        patch = "*** Begin Patch\n*** Update File:app.py\n*** Move to:main.py\n*** Add File:\n*** End Patch"
        uses = self._tool_uses(("apply_patch", {"patchText": patch}))
        self.assertEqual(uses[0][2]["file_paths"], ["/repo/app.py", "/repo/main.py"])

    def test_a_home_relative_path_is_not_joined_onto_the_session_directory(
        self,
    ) -> None:
        """opencode expands `~` to a home directory the database does not record."""
        uses = self._tool_uses(("read", {"path": "~/.bashrc"}))
        self.assertEqual(uses[0][2]["file_path"], "~/.bashrc")

    def _moved_session(self, switch: dict) -> list:
        """read, patch, read in `/old`; then the move; then one more patch."""
        patch = {"patchText": "*** Begin Patch\n*** Update File: app.py\n*** End Patch"}
        read = {"path": "/old/app.py"}
        done = {"status": "completed", "content": [{"type": "text", "text": "ok"}]}
        calls = [
            ("read", read),
            ("patch", patch),
            ("read", read),
            None,
            ("patch", patch),
        ]
        rows = [
            ("m4", "location-switched", 4, {**switch, "time": {"created": 4}})
            if call is None
            else (
                f"m{n}",
                "assistant",
                n,
                _v2_assistant(
                    _v2_tool(f"c{n}", {**done, "input": call[1]}, name=call[0])
                ),
            )
            for n, call in enumerate(calls, start=1)
        ]
        # The move has already rewritten the session's own directory.
        _v2_database(self.db, rows, "ses_moved")
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE session_v2 SET directory='/new' WHERE id='ses_moved'")
        conn.commit()
        conn.close()
        out = self.dir / "moved.jsonl"
        out.write_text("\n".join(self._render("ses_moved")) + "\n", encoding="utf-8")
        return detector.extract_tool_uses(detector.load_jsonl(out))

    def test_a_moved_session_resolves_each_path_against_the_directory_it_had(
        self,
    ) -> None:
        uses = self._moved_session(
            {
                "location": {"directory": "/new"},
                "previous": {"location": {"directory": "/old"}},
            }
        )
        patched = [u[2]["file_paths"] for u in uses if u[1] == "Patch"]
        self.assertEqual(patched, [["/old/app.py"], ["/new/app.py"]])
        self.assertEqual(detector.signal_reread_same_file(uses), [])

    def test_a_move_without_a_previous_location_leaves_earlier_paths_relative(
        self,
    ) -> None:
        """The start directory is then unknown; the current one would be wrong.

        opencode v2.0.15 always writes `previous` on a move; this guards a
        database written by another version.
        """
        uses = self._moved_session({"location": {"directory": "/new"}})
        patched = [u[2]["file_paths"] for u in uses if u[1] == "Patch"]
        self.assertEqual(patched, [["app.py"], ["/new/app.py"]])

    def _session(self, session_id: str, steps: list, **fixture) -> None:
        """A V2 session of `("patch", file)` calls and `("move", old, new)` rows."""
        rows = []
        for seq, step in enumerate(steps, start=1):
            if step[0] == "move":
                switch = {
                    "location": {"directory": step[2]},
                    "previous": {"location": {"directory": step[1]}},
                    "time": {"created": seq},
                }
                rows.append((f"m{seq}", "location-switched", seq, switch))
                continue
            patch = f"*** Begin Patch\n*** Update File: {step[1]}\n*** End Patch"
            state = {
                "status": "completed",
                "input": {"patchText": patch},
                "content": [{"type": "text", "text": "ok"}],
            }
            tool = _v2_tool(f"c{seq}", state, name="patch")
            rows.append((f"m{seq}", "assistant", seq, _v2_assistant(tool)))
        _v2_database(self.db, rows, session_id, **fixture)

    def _patched(self, session_id: str) -> list[str]:
        return [
            path
            for block in _blocks(self._render(session_id))
            if block.get("name") == "Patch"
            for path in block["input"]["file_paths"]
        ]

    def test_each_row_resolves_against_the_directory_before_the_next_move(
        self,
    ) -> None:
        """With two moves, the first row ran where the FIRST move started."""
        steps = [
            ("patch", "a.py"),
            ("move", "/A", "/B"),
            ("patch", "b.py"),
            ("move", "/B", "/C"),
            ("patch", "c.py"),
        ]
        self._session("ses_two", steps, directory="/C")
        self.assertEqual(self._patched("ses_two"), ["/A/a.py", "/B/b.py", "/C/c.py"])

    def test_a_forks_copied_rows_resolve_where_the_parent_ran_them(self) -> None:
        """A fork starts in its parent's CURRENT directory and copies older rows.

        The parent moved `/A` → `/B` → `/C`; the fork copied the rows up to
        `seq` 3 and was created in `/C`, where its own row then ran.
        """
        parent = [
            ("patch", "a.py"),
            ("move", "/A", "/B"),
            ("patch", "b.py"),
            ("move", "/B", "/C"),
        ]
        self._session("ses_par", parent, directory="/C")
        self._session(
            "ses_frk",
            [*parent[:3], ("patch", "own.py")],
            directory="/C",
            parent="ses_par",
            copied=3,
        )
        self.assertEqual(self._patched("ses_frk"), ["/A/a.py", "/B/b.py", "/C/own.py"])

    def test_a_fork_before_the_parents_move_keeps_read_patch_read_apart(
        self,
    ) -> None:
        """The false re-read the fork rule removes: the copied patch ran in `/A`."""
        read = ("read", {"path": "/A/app.py"})
        patch = ("patch", {"patchText": "*** Update File: app.py"})
        done = {"status": "completed", "content": [{"type": "text", "text": "ok"}]}
        rows = [
            (
                f"m{seq}",
                "assistant",
                seq,
                _v2_assistant(_v2_tool(f"c{seq}", {**done, "input": call[1]}, call[0])),
            )
            for seq, call in enumerate([read, patch, read], start=1)
        ]
        switch = {
            "location": {"directory": "/B"},
            "previous": {"location": {"directory": "/A"}},
            "time": {"created": 4},
        }
        _v2_database(
            self.db, [*rows, ("m4", "location-switched", 4, switch)], "ses_p", "/B"
        )
        _v2_database(self.db, rows, "ses_f", "/B", parent="ses_p", copied=3)

        out = self.dir / "fork.jsonl"
        out.write_text("\n".join(self._render("ses_f")) + "\n", encoding="utf-8")
        uses = detector.extract_tool_uses(detector.load_jsonl(out))
        self.assertEqual(uses[1][2]["file_paths"], ["/A/app.py"])
        self.assertEqual(detector.signal_reread_same_file(uses), [])

    def test_a_home_path_is_joined_in_1x_and_left_alone_in_2x(self) -> None:
        """2.x expands `~` and `~/…`; 1.x resolves them like any relative path."""
        for path, v2 in (("~", "~"), ("~/.bashrc", "~/.bashrc"), ("~x", "/repo/~x")):
            self.assertEqual(
                adapter._tool_use("c", "read", {"path": path}, "/repo", True)["input"],
                {"file_path": v2},
            )
        legacy = adapter._tool_use("c", "read", {"filePath": "~/.bashrc"}, "/repo")
        self.assertEqual(legacy["input"], {"file_path": "/repo/~/.bashrc"})

    def test_the_detector_accepts_the_rendered_v2_transcript(self) -> None:
        """The consumer contract, run end to end through the detector's own CLI."""
        out = self.dir / "session.jsonl"
        out.write_text("\n".join(self._render()) + "\n", encoding="utf-8")
        # The detector pairs a use with its result; unfinished calls have none.
        paired = detector.extract_tool_uses(detector.load_jsonl(out))
        self.assertEqual(
            [(name, err) for _, name, _, _, err in paired],
            [("Bash", False), ("Bash", True)],
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
