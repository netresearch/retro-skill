# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Codex rollout conversion: real record shapes, human turns, wrapper unwrapping."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "retro" / "scripts" / "codex-transcript.py"
DETECTOR = ROOT / "skills" / "retro" / "scripts" / "detect-mechanical.py"
#: Redacted excerpts of real rollouts: structure, ids, timestamps and output
#: headers as Codex wrote them; commands, paths and prose replaced.
FIXTURES = ROOT / "tests" / "fixtures" / "codex"
spec = importlib.util.spec_from_file_location("codex_transcript", SCRIPT)
adapter = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(adapter)


def fixture(name: str) -> list[dict]:
    path = FIXTURES / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def row(payload: dict, *, kind: str = "response_item") -> dict:
    return {"type": kind, "payload": payload}


def message(role: str, text: str) -> dict:
    return row(
        {
            "type": "message",
            "role": role,
            "id": f"message-{role}-{len(text)}",
            "content": [
                {
                    "type": "input_text" if role == "user" else "output_text",
                    "text": text,
                }
            ],
        }
    )


def tool(source: str) -> dict:
    return row(
        {"type": "custom_tool_call", "name": "exec", "id": "wrapper-1", "input": source}
    )


def blocks(lines: list[str], kind: str) -> list[dict]:
    return [
        block
        for line in lines
        for block in json.loads(line)["message"]["content"]
        if block["type"] == kind
    ]


def detect(lines: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        session = Path(directory) / "session.jsonl"
        session.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(DETECTOR),
                "--transcript-file",
                str(session),
                "--output-format",
                "json",
            ],
            capture_output=True,
            check=True,
        )
    return json.loads(result.stdout)


class RealRolloutTest(unittest.TestCase):
    def test_exec_command_calls_pair_with_their_exit_codes(self) -> None:
        lines = adapter.render(fixture("rollout-0.101.0.jsonl"), "Run the test suite")
        uses = blocks(lines, "tool_use")
        results = {r["tool_use_id"]: r for r in blocks(lines, "tool_result")}
        self.assertEqual(
            [u["input"]["command"] for u in uses],
            ["ls missing-file", "git status --short"],
        )
        self.assertEqual({u["name"] for u in uses}, {"Bash"})
        self.assertEqual([results[u["id"]]["is_error"] for u in uses], [True, False])
        self.assertEqual(
            results[uses[0]["id"]]["content"],
            "ls: cannot access 'missing-file': No such file or directory\n",
        )
        report = detect(lines)
        self.assertEqual(report["tool_uses"], 2)
        self.assertIn("A1", [f["signal"] for f in report["findings"]])

    def test_shell_call_takes_the_script_and_the_json_exit_code(self) -> None:
        rows = fixture("rollout-0.39.0-shell.jsonl")
        lines = adapter.render(rows)
        (use,) = blocks(lines, "tool_use")
        (result,) = blocks(lines, "tool_result")
        self.assertEqual(use["input"], {"command": "ls"})
        self.assertFalse(result["is_error"])
        self.assertEqual(result["content"], "README.md\n")
        output = rows[6]["payload"]
        failed = json.loads(output["output"])
        failed["metadata"]["exit_code"] = 2
        rows[6] = {**rows[6], "payload": {**output, "output": json.dumps(failed)}}
        (result,) = blocks(adapter.render(rows), "tool_result")
        self.assertTrue(result["is_error"])

    def test_a_running_call_gets_no_result(self) -> None:
        lines = adapter.render(fixture("rollout-0.101.0-running.jsonl"))
        self.assertEqual(len(blocks(lines, "tool_use")), 1)
        self.assertEqual(blocks(lines, "tool_result"), [])

    def test_injected_user_text_is_meta_by_the_human_record(self) -> None:
        events = [
            json.loads(line)
            for line in adapter.render(fixture("rollout-0.101.0.jsonl"))
            if json.loads(line)["type"] == "user" and blocks([line], "text")
        ]
        self.assertEqual(
            [(e["isMeta"], e["message"]["content"][0]["text"][:14]) for e in events],
            [
                (True, "# AGENTS.md in"),
                (True, "<environment_c"),
                (False, "Run the test s"),
            ],
        )

    def test_every_event_keeps_the_row_timestamp(self) -> None:
        lines = adapter.render(fixture("rollout-0.101.0.jsonl"))
        self.assertTrue(all(json.loads(line)["timestamp"] for line in lines))


class HumanTurnTest(unittest.TestCase):
    def test_content_item_kinds_decide_on_0_163(self) -> None:
        def kinds_message(text: str, kinds: list[str]) -> dict:
            item = message("user", text)
            item["payload"]["internal_chat_message_metadata_passthrough"] = {
                "content_item_kinds": kinds
            }
            return item

        rows = [
            kinds_message(
                "<environment_context>", ["environments.environment_context"]
            ),
            kinds_message("Fix the build", ["user.text"]),
            kinds_message("Plain words injected", ["environments.other"]),
        ]
        events = [json.loads(line) for line in adapter.render(rows, "Fix the build")]
        self.assertEqual([e["isMeta"] for e in events], [True, False, True])

    def test_item_completed_user_message_is_the_human_record(self) -> None:
        rows = [
            message("user", "Injected without a known prefix"),
            message("user", "Fix the build"),
            row(
                {
                    "type": "item_completed",
                    "item": {
                        "type": "UserMessage",
                        "content": [{"type": "text", "text": "Fix the build"}],
                    },
                },
                kind="event_msg",
            ),
        ]
        events = [json.loads(line) for line in adapter.render(rows)]
        self.assertEqual([e["isMeta"] for e in events], [True, False])

    def test_prefixes_decide_without_a_human_record(self) -> None:
        rows = [
            message("user", "# AGENTS.md instructions for /repo"),
            message("user", "<user_instructions>be brief</user_instructions>"),
            message("user", "请检查进度条"),
            message("assistant", "已检查。"),
            message("user", "<skill>expanded slash command</skill>"),
        ]
        events = [json.loads(line) for line in adapter.render(rows, "请检查进度条")]
        self.assertEqual(
            [e["isMeta"] for e in events if e["type"] == "user"],
            [True, True, False, True],
        )

    def test_match_ignores_injected_text(self) -> None:
        rows = fixture("rollout-0.101.0.jsonl")
        with self.assertRaisesRegex(ValueError, "no human user message"):
            adapter.render(rows, "environment_context")

    def test_subagent_rollout_is_refused(self) -> None:
        rows = fixture("rollout-0.101.0.jsonl")
        meta = rows[0]["payload"]
        rows[0] = {
            **rows[0],
            "payload": {**meta, "source": {"subagent": {"other": "guardian"}}},
        }
        with self.assertRaisesRegex(ValueError, "subagent rollout"):
            adapter.render(rows, "Run the test suite")


class ToolCallTest(unittest.TestCase):
    def test_direct_apply_patch_resolves_against_the_turn_directory(self) -> None:
        rows = [
            row({"type": "turn_context", "cwd": "/repo"}, kind="turn_context"),
            row(
                {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "call-1",
                    "input": "*** Begin Patch\n*** Update File: src/app.py\n"
                    "*** Move to: src/main.py\n@@\n-a\n+b\n"
                    "*** Add File: /abs/new.py\n+x\n*** End Patch",
                }
            ),
            row(
                {
                    "type": "custom_tool_call_output",
                    "call_id": "call-1",
                    "output": "Success. Updated the following files:\nM src/main.py",
                }
            ),
        ]
        lines = adapter.render(rows)
        (use,) = blocks(lines, "tool_use")
        self.assertEqual(use["name"], "Patch")
        self.assertEqual(
            use["input"]["file_paths"],
            ["/repo/src/app.py", "/repo/src/main.py", "/abs/new.py"],
        )
        (result,) = blocks(lines, "tool_result")
        self.assertEqual(result["tool_use_id"], "call-1")
        self.assertFalse(result["is_error"])

    def test_other_function_calls_pass_through(self) -> None:
        rows = [
            row(
                {
                    "type": "function_call",
                    "name": "update_plan",
                    "arguments": json.dumps({"plan": []}),
                    "call_id": "call-2",
                }
            ),
            row(
                {
                    "type": "function_call_output",
                    "call_id": "call-2",
                    "output": "Plan updated",
                }
            ),
        ]
        lines = adapter.render(rows)
        (use,) = blocks(lines, "tool_use")
        self.assertEqual((use["name"], use["id"]), ("update_plan", "call-2"))
        self.assertFalse(blocks(lines, "tool_result")[0]["is_error"])

    def test_calls_that_render_to_nothing_are_refused(self) -> None:
        rows = [
            message("user", "Review"),
            tool("await tools.exec_command({cmd: buildCommand()});"),
        ]
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(ValueError, r"1 tool calls \(exec\), none rendered"),
        ):
            adapter.render(rows)


class ExecWrapperTest(unittest.TestCase):
    def test_nested_commands_replace_the_exec_wrapper(self) -> None:
        rows = [
            message("user", "Check the repository"),
            tool(
                'const ignored = "tools.exec_command({cmd:\\"not a call\\"})"; '
                '// tools.exec_command({cmd:"also not a call"})\n'
                "const r=await Promise.allSettled(["
                'tools.exec_command({note:"cmd: fake",cmd:"git status --short",workdir:"/repo"}),'
                "tools.exec_command({'cmd':'npm test',workdir:\"/repo\"})]); text(r);"
            ),
        ]
        lines = adapter.render(rows)
        uses = blocks(lines, "tool_use")
        self.assertEqual([item["name"] for item in uses], ["Bash", "Bash"])
        self.assertEqual(
            [item["input"]["command"] for item in uses],
            ["git status --short", "npm test"],
        )
        self.assertTrue(all("id" not in item for item in uses))
        events = [json.loads(line) for line in lines]
        self.assertEqual(events[1]["message"]["id"], events[2]["message"]["id"])

    def test_patch_paths_are_extracted_when_the_argument_is_literal(self) -> None:
        rows = [
            tool(
                'text(await tools.apply_patch("*** Begin Patch\\n'
                "*** Update File: src/app.py\\n*** Add File: tests/test_app.py\\n"
                '*** End Patch"));'
            )
        ]
        (use,) = blocks(adapter.render(rows), "tool_use")
        self.assertEqual(use["name"], "Patch")
        self.assertEqual(
            use["input"]["file_paths"], ["src/app.py", "tests/test_app.py"]
        )

    def test_computed_arguments_are_omitted_and_counted(self) -> None:
        rows = [
            message("user", "Review"),
            tool(
                'await tools.exec_command({cmd: "git " + "status"});'
                "await tools.exec_command({cmd: `git ${sub}`});"
                'await tools.apply_patch(header + "*** End Patch");'
                'await tools.exec_command({cmd: "ls", workdir: "/repo"});'
            ),
        ]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            lines = adapter.render(rows)
        self.assertEqual(
            [u["input"]["command"] for u in blocks(lines, "tool_use")], ["ls"]
        )
        self.assertIn("3 tool call(s)", stderr.getvalue())


class RealWrapperTest(unittest.TestCase):
    """`codex exec` 0.163.0: every tool runs inside a `functions.exec` wrapper."""

    def test_single_call_wrappers_pair_with_their_output(self) -> None:
        lines = adapter.render(fixture("rollout-0.163.0-exec.jsonl"), "probe-r168")
        uses = blocks(lines, "tool_use")
        results = {r["tool_use_id"]: r for r in blocks(lines, "tool_result")}
        self.assertEqual(
            [(u["name"], u.get("input")) for u in uses],
            [
                ("Bash", {"command": "echo probe-r168"}),
                ("Bash", {"command": "ls /nonexistent-r168"}),
                ("Patch", {"file_paths": ["/repo/hello.txt"]}),
            ],
        )
        self.assertEqual(set(results), {u["id"] for u in uses})
        self.assertEqual(results[uses[0]["id"]]["content"], "probe-r168\n")
        self.assertEqual(
            [results[u["id"]]["is_error"] for u in uses], [False, False, False]
        )
        report = detect(lines)
        self.assertEqual(report["tool_uses"], 3)

    def test_a_failed_script_is_an_error(self) -> None:
        lines = adapter.render(fixture("rollout-0.163.0-script-error.jsonl"))
        (use,) = blocks(lines, "tool_use")
        (result,) = blocks(lines, "tool_result")
        self.assertEqual(result["tool_use_id"], use["id"])
        self.assertTrue(result["is_error"])
        self.assertTrue(result["content"].startswith("before\nScript error:\n"))
        self.assertIn("A1", [f["signal"] for f in detect(lines)["findings"]])

    def test_a_wrapper_with_several_calls_renders_no_result(self) -> None:
        rows = fixture("rollout-0.163.0-script-error.jsonl")
        call = rows[5]["payload"]
        rows[5] = {
            **rows[5],
            "payload": {
                **call,
                "input": 'await tools.exec_command({cmd:"a"});'
                'await tools.exec_command({cmd:"b"});',
            },
        }
        lines = adapter.render(rows)
        self.assertEqual(len(blocks(lines, "tool_use")), 2)
        self.assertTrue(all("id" not in u for u in blocks(lines, "tool_use")))
        self.assertEqual(blocks(lines, "tool_result"), [])


def executed_rows(rows: list[dict]) -> list[dict]:
    """The `item_completed` rows of commands and patches, in order."""
    return [
        r
        for r in rows
        if r["payload"].get("type") == "item_completed"
        and r["payload"]["item"]["type"] in ("CommandExecution", "FileChange")
    ]


class ExecutionItemTest(unittest.TestCase):
    """0.163.0 records every nested command and patch as an executed item."""

    def test_a_failing_command_in_a_completed_script_is_an_error(self) -> None:
        lines = adapter.render(fixture("rollout-0.163.0-command-exit.jsonl"))
        uses = blocks(lines, "tool_use")
        results = {r["tool_use_id"]: r for r in blocks(lines, "tool_result")}
        self.assertEqual(
            [u["input"]["command"] for u in uses],
            ["ls /nonexistent-r184", "echo ok-r184"],
        )
        self.assertEqual([results[u["id"]]["is_error"] for u in uses], [True, False])
        self.assertTrue(results[uses[0]["id"]]["content"].startswith("ls: cannot"))
        self.assertIn("A1", [f["signal"] for f in detect(lines)["findings"]])

    def test_each_call_of_a_script_gets_its_own_result(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            lines = adapter.render(fixture("rollout-0.163.0-multi-call.jsonl"))
        uses = blocks(lines, "tool_use")
        results = {r["tool_use_id"]: r for r in blocks(lines, "tool_result")}
        self.assertEqual(
            [(u["name"], u["input"]) for u in uses],
            [
                ("Bash", {"command": "ls /nonexistent-r184b"}),
                ("Bash", {"command": "echo two-r184"}),
                ("Patch", {"file_paths": ["/repo/p184.txt"]}),
            ],
        )
        self.assertEqual(
            [results[u["id"]]["is_error"] for u in uses], [True, False, False]
        )
        # The computed `'ls /' + d` is no longer left out.
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(detect(lines)["tool_uses"], 3)

    def test_other_tools_of_the_script_are_kept(self) -> None:
        rows = fixture("rollout-0.163.0-multi-call.jsonl")
        call = rows[6]["payload"]
        rows[6] = {
            **rows[6],
            "payload": {**call, "input": call["input"] + "await tools.view_image({});"},
        }
        names = [u["name"] for u in blocks(adapter.render(rows), "tool_use")]
        self.assertEqual(names, ["view_image", "Bash", "Bash", "Patch"])

    def test_items_outside_a_wrapper_are_not_counted_twice(self) -> None:
        rows = fixture("rollout-0.101.0.jsonl")
        rows.insert(9, executed_rows(fixture("rollout-0.163.0-command-exit.jsonl"))[0])
        self.assertEqual(len(blocks(adapter.render(rows), "tool_use")), 2)

    def test_an_item_that_has_not_ended_stays_id_less(self) -> None:
        rows = fixture("rollout-0.163.0-command-exit.jsonl")
        executed = executed_rows(rows)[0]["payload"]["item"]
        for key in ("exit_code", "status"):
            executed.pop(key)
        lines = adapter.render(rows)
        self.assertNotIn("id", blocks(lines, "tool_use")[0])
        self.assertEqual(detect(lines)["tool_uses"], 2)

    def test_a_script_that_throws_after_its_command_stays_an_error(self) -> None:
        lines = adapter.render(fixture("rollout-0.163.0-script-error-items.jsonl"))
        uses = blocks(lines, "tool_use")
        results = {r["tool_use_id"]: r for r in blocks(lines, "tool_result")}
        self.assertEqual([u["name"] for u in uses], ["Bash", "exec"])
        self.assertEqual([results[u["id"]]["is_error"] for u in uses], [False, True])
        self.assertIn("probe-throw2-r184", results[uses[1]["id"]]["content"])
        self.assertIn("A1", [f["signal"] for f in detect(lines)["findings"]])

    def test_a_failed_status_without_exit_code_is_an_error(self) -> None:
        rows = fixture("rollout-0.163.0-multi-call.jsonl")
        command, _, patch = (r["payload"]["item"] for r in executed_rows(rows))
        command.pop("exit_code")
        patch["status"] = "failed"
        lines = adapter.render(rows)
        errors = [r["is_error"] for r in blocks(lines, "tool_result")]
        self.assertEqual(errors, [True, False, True])

    def test_equal_wrappers_close_independently(self) -> None:
        def wrapper(call_id: str) -> dict:
            return row(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": call_id,
                    "input": 'await tools.exec_command({cmd:"ls"});',
                }
            )

        def done(call_id: str) -> dict:
            return row(
                {
                    "type": "custom_tool_call_output",
                    "call_id": call_id,
                    "output": "Script completed\nOutput:\n",
                }
            )

        # Equal content, closed in reverse order: removal must be by identity.
        rows = [wrapper("a"), wrapper("b"), done("b"), done("a")]
        lines = adapter.render(rows)
        self.assertEqual(detect(lines)["tool_uses"], 2)

    def test_an_item_goes_to_the_wrapper_that_names_its_command(self) -> None:
        rows = fixture("rollout-0.163.0-command-exit.jsonl")
        first, second = (
            i for i, r in enumerate(rows) if r["payload"].get("name") == "exec"
        )
        item = rows.pop(first + 1)
        later = rows.pop(first + 1)  # the first wrapper's output row
        # Both wrappers are open when the first one's item arrives.
        rows.insert(second - 1, item)
        rows.insert(second, later)
        lines = adapter.render(rows)
        commands = [u["input"]["command"] for u in blocks(lines, "tool_use")]
        self.assertEqual(sorted(commands), ["echo ok-r184", "ls /nonexistent-r184"])

    def test_an_item_after_an_unclosable_wrapper_is_ignored(self) -> None:
        rows = fixture("rollout-0.163.0-command-exit.jsonl")
        exec_rows = [r for r in rows if r["payload"].get("name") == "exec"]
        exec_rows[0]["payload"].pop("call_id")
        stray = json.loads(json.dumps(executed_rows(rows)[0]))
        stray["payload"]["item"]["id"] = "exec-stray"
        rows.append(stray)
        commands = [
            u["input"]["command"] for u in blocks(adapter.render(rows), "tool_use")
        ]
        self.assertEqual(commands, ["ls /nonexistent-r184", "echo ok-r184"])

    def test_a_command_still_running_at_the_end_is_kept(self) -> None:
        rows = fixture("rollout-0.163.0-multi-call.jsonl")
        wrapper = next(r for r in rows if r["payload"].get("name") == "exec")
        wrapper["payload"]["input"] += 'await tools.exec_command({cmd: "sleep 600"});'
        rows = [
            r for r in rows if r["payload"].get("type") != "custom_tool_call_output"
        ]
        uses = blocks(adapter.render(rows), "tool_use")
        self.assertEqual(
            [u["input"].get("command") for u in uses if u["name"] == "Bash"],
            ["ls /nonexistent-r184b", "echo two-r184", "sleep 600"],
        )
        self.assertNotIn("id", uses[-1])

    def test_a_command_the_script_never_reached_is_left_out(self) -> None:
        rows = fixture("rollout-0.163.0-script-error-items.jsonl")
        wrapper = next(r for r in rows if r["payload"].get("name") == "exec")
        wrapper["payload"]["input"] += 'await tools.exec_command({cmd: "never"});'
        commands = [
            u["input"].get("command")
            for u in blocks(adapter.render(rows), "tool_use")
            if u["name"] == "Bash"
        ]
        self.assertEqual(commands, ["echo before-r184"])

    def wrapper_rows(self, source: str, items: list[dict], header: str | None) -> list:
        rows = [
            row({"type": "turn_context", "cwd": "/repo"}, kind="turn_context"),
            row(
                {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "w",
                    "input": source,
                }
            ),
        ]
        rows += [
            row({"type": "item_completed", "item": item}, kind="event_msg")
            for item in items
        ]
        if header is not None:
            rows.append(
                row(
                    {
                        "type": "custom_tool_call_output",
                        "call_id": "w",
                        "output": f"{header}\nOutput:\n",
                    }
                )
            )
        return rows

    @staticmethod
    def ran(item_id: str, command: str, code: int = 0) -> dict:
        return {
            "type": "CommandExecution",
            "id": item_id,
            "command": ["/bin/bash", "-lc", command],
            "status": "failed" if code else "completed",
            "exit_code": code,
            "aggregated_output": "",
        }

    def test_a_command_left_running_past_a_completed_script_is_kept(self) -> None:
        rows = self.wrapper_rows(
            'await tools.exec_command({cmd:"ls"});'
            'await tools.exec_command({cmd:"npm run dev", yield_time_ms:1000});',
            [self.ran("i1", "ls")],
            "Script completed",
        )
        commands = [
            u["input"]["command"] for u in blocks(adapter.render(rows), "tool_use")
        ]
        self.assertEqual(commands, ["ls", "npm run dev"])

    def test_each_item_accounts_for_one_call(self) -> None:
        rows = self.wrapper_rows(
            'await tools.exec_command({cmd:"echo a"});'
            'await tools.exec_command({cmd:"echo a"});',
            [self.ran("i1", "echo a")],
            None,
        )
        self.assertEqual(len(blocks(adapter.render(rows), "tool_use")), 2)

    def test_a_computed_patch_does_not_take_a_literal_ones_place(self) -> None:
        patch = "*** Begin Patch\\n*** Add File: {}\\n+x\\n*** End Patch"
        rows = self.wrapper_rows(
            f"await tools.apply_patch(`{patch.format('a.txt')}`);"
            f'await tools.apply_patch("{patch.format("b.txt")}");',
            [
                {
                    "type": "FileChange",
                    "id": "p1",
                    "changes": {"/repo/a.txt": {"type": "add"}},
                    "status": "completed",
                    "stdout": "",
                    "stderr": "",
                }
            ],
            None,
        )
        paths = [
            u["input"]["file_paths"] for u in blocks(adapter.render(rows), "tool_use")
        ]
        self.assertEqual(paths, [["/repo/a.txt"], ["/repo/b.txt"]])

    def test_another_shell_still_matches_its_literal(self) -> None:
        for argv in (
            ["/usr/bin/fish", "-c", "ls -la"],
            ["pwsh.exe", "-Command", "ls -la"],
        ):
            with self.subTest(argv=argv):
                item = {**self.ran("i1", "ls -la"), "command": argv}
                rows = self.wrapper_rows(
                    'await tools.exec_command({cmd:"ls -la"});',
                    [item],
                    "Script completed",
                )
                uses = blocks(adapter.render(rows), "tool_use")
                self.assertEqual(
                    [(u["input"]["command"], "id" in u) for u in uses],
                    [("ls -la", True)],
                )

    def test_a_relative_patch_path_matches_its_absolute_item(self) -> None:
        rows = self.wrapper_rows(
            'await tools.apply_patch("*** Begin Patch\\n*** Add File: .github/x.yml'
            '\\n+x\\n*** End Patch");',
            [
                {
                    "type": "FileChange",
                    "id": "p1",
                    "changes": {"/repo/.github/x.yml": {"type": "add"}},
                    "status": "completed",
                    "stdout": "",
                    "stderr": "",
                }
            ],
            "Script completed",
        )
        del rows[0]  # no turn directory: the source path stays relative
        self.assertEqual(len(blocks(adapter.render(rows), "tool_use")), 1)

    def test_routing_compares_commands_not_source_text(self) -> None:
        # "ls" occurs in every source ("tools."), but only the first
        # wrapper runs it.
        rows = self.wrapper_rows('await tools.exec_command({cmd:"ls"});', [], None)
        second = self.wrapper_rows(
            'await tools.exec_command({cmd:"echo b"});', [], None
        )
        second[1]["payload"]["call_id"] = "w2"
        rows += second[1:]
        rows.append(
            row(
                {"type": "item_completed", "item": self.ran("i1", "ls")},
                kind="event_msg",
            )
        )
        rows.append(
            row(
                {
                    "type": "custom_tool_call_output",
                    "call_id": "w",
                    "output": "Script completed\nOutput:\n",
                }
            )
        )
        rows.append(
            row(
                {"type": "item_completed", "item": self.ran("i2", "echo b")},
                kind="event_msg",
            )
        )
        rows.append(
            row(
                {
                    "type": "custom_tool_call_output",
                    "call_id": "w2",
                    "output": "Script completed\nOutput:\n",
                }
            )
        )
        commands = sorted(
            u["input"]["command"] for u in blocks(adapter.render(rows), "tool_use")
        )
        self.assertEqual(commands, ["echo b", "ls"])

    def test_an_interrupted_wrapper_keeps_its_executed_calls(self) -> None:
        rows = [
            r
            for r in fixture("rollout-0.163.0-multi-call.jsonl")
            if r["payload"].get("type") != "custom_tool_call_output"
        ]
        lines = adapter.render(rows)
        self.assertEqual(len(blocks(lines, "tool_result")), 3)
        self.assertEqual(detect(lines)["tool_uses"], 3)


class WrapperEdgeTest(unittest.TestCase):
    """Wrapper rows a real rollout can carry in other combinations."""

    def wrapper(self, source: str, call_id: str | None = "call-w") -> dict:
        payload = {"type": "custom_tool_call", "name": "exec", "input": source}
        if call_id is not None:
            payload["call_id"] = call_id
        return row(payload)

    def output(self, header: str, body: str, call_id: str | None = "call-w") -> dict:
        payload = {
            "type": "custom_tool_call_output",
            "output": [
                {
                    "type": "input_text",
                    "text": f"{header}\nWall time 0.1 seconds\nOutput:\n",
                },
                {"type": "input_text", "text": body},
            ],
        }
        if call_id is not None:
            payload["call_id"] = call_id
        return row(payload)

    def test_a_call_whose_output_is_missing_is_still_counted(self) -> None:
        rows = fixture("rollout-0.163.0-exec.jsonl")
        del rows[11]
        lines = adapter.render(rows)
        uses = blocks(lines, "tool_use")
        self.assertNotIn("id", uses[2])
        self.assertEqual(detect(lines)["tool_uses"], 3)

    def test_rows_without_call_id_do_not_crash(self) -> None:
        rows = [
            self.wrapper('await tools.exec_command({cmd:"ls"});', call_id=None),
            self.output("Script completed", "x\n", call_id=None),
        ]
        (use,) = blocks(adapter.render(rows), "tool_use")
        self.assertNotIn("id", use)

    def test_an_unhashable_call_id_does_not_crash(self) -> None:
        for bad in ({"k": 1}, ["x"]):
            with self.subTest(call_id=bad):
                rows = [
                    self.wrapper('await tools.exec_command({cmd:"ls"});'),
                    self.output("Script completed", "x\n", call_id=None),
                ]
                rows[1]["payload"]["call_id"] = bad
                (use,) = blocks(adapter.render(rows), "tool_use")
                self.assertNotIn("id", use)

    def test_an_unhashable_wrapper_call_id_does_not_crash(self) -> None:
        rows = [
            self.wrapper('await tools.exec_command({cmd:"ls"});'),
            self.output("Script completed", "x\n"),
        ]
        rows[0]["payload"]["call_id"] = {"k": 1}
        (use,) = blocks(adapter.render(rows), "tool_use")
        self.assertNotIn("id", use)

    def test_another_nested_tool_is_counted_and_takes_no_output(self) -> None:
        rows = [
            self.wrapper(
                'await tools.exec_command({cmd:"ls"});'
                'await tools.view_image({path:"x.png"});'
            ),
            self.output("Script failed", "view_image: not found"),
        ]
        lines = adapter.render(rows)
        uses = blocks(lines, "tool_use")
        self.assertEqual([u["name"] for u in uses], ["Bash", "view_image"])
        self.assertTrue(all("id" not in u for u in uses))
        self.assertEqual(blocks(lines, "tool_result"), [])

    def test_a_direct_call_keeps_its_call_id_from_a_wrapper(self) -> None:
        rows = [
            self.wrapper('await tools.exec_command({cmd:"ls"});', call_id="c1"),
            row(
                {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "c1",
                    "input": "*** Begin Patch\n*** Add File: a.py\n+x\n*** End Patch",
                }
            ),
            self.output("Script completed", "", call_id="c1"),
        ]
        lines = adapter.render(rows)
        self.assertEqual(detect(lines)["tool_uses"], 2)

    def test_malformed_rows_and_items_are_skipped(self) -> None:
        rows = [
            [1],
            "text",
            row({"type": "message", "role": "user", "content": 5}),
            message("user", "Fix it"),
            row(
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "ls"}),
                    "call_id": "call-f",
                }
            ),
            row({"type": "function_call_output", "call_id": "call-f", "output": [1]}),
            row({"type": "function_call_output", "call_id": ["x"], "output": "y"}),
        ]
        lines = adapter.render(rows, "Fix it")
        (result,) = blocks(lines, "tool_result")
        self.assertEqual((result["tool_use_id"], result["content"]), ("call-f", "[1]"))
        self.assertEqual(detect(lines)["tool_uses"], 1)

    def test_a_non_string_call_id_leaves_the_call_counted(self) -> None:
        for bad in (5, [1], {"a": 1}):
            with self.subTest(call_id=bad):
                rows = [
                    row(
                        {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": bad,
                            "arguments": json.dumps({"cmd": "ls"}),
                        }
                    ),
                    row(
                        {
                            "type": "function_call_output",
                            "call_id": bad,
                            "output": "Process exited with code 0\nOutput:\nx",
                        }
                    ),
                ]
                lines = adapter.render(rows)
                (use,) = blocks(lines, "tool_use")
                self.assertNotIn("id", use)
                self.assertEqual(detect(lines)["tool_uses"], 1)

    def test_only_the_runtime_tools_object_is_read(self) -> None:
        rows = [
            self.wrapper(
                "mytools.foo(1); $tools.bar(2); ctx.tools.write_stdin({});"
                'await tools.exec_command({cmd:"ls"});'
            ),
            self.output("Script completed", "x\n"),
        ]
        lines = adapter.render(rows)
        (use,) = blocks(lines, "tool_use")
        self.assertEqual((use["name"], use["id"]), ("Bash", "call-w"))

    def test_a_wrapper_does_not_take_a_direct_calls_id(self) -> None:
        rows = [
            row(
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "w1",
                    "arguments": json.dumps({"cmd": "pwd"}),
                }
            ),
            self.wrapper('await tools.exec_command({cmd:"ls"});', call_id="w1"),
            self.output("Script failed", "", call_id="w1"),
        ]
        lines = adapter.render(rows)
        self.assertEqual(detect(lines)["tool_uses"], 2)

    def test_item_completed_content_that_is_no_list_is_skipped(self) -> None:
        rows = [
            message("user", "Fix it"),
            row(
                {
                    "type": "item_completed",
                    "item": {"type": "UserMessage", "content": 5},
                },
                kind="event_msg",
            ),
        ]
        (event,) = [json.loads(line) for line in adapter.render(rows)]
        self.assertTrue(event["isMeta"])

    def test_a_computed_call_keeps_the_output_from_the_literal_one(self) -> None:
        rows = [
            self.wrapper(
                'await tools.exec_command({cmd:"ls"});'
                "await tools.exec_command({cmd: built});"
            ),
            self.output("Script completed", "both outputs\n"),
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            lines = adapter.render(rows)
        (use,) = blocks(lines, "tool_use")
        self.assertNotIn("id", use)
        self.assertEqual(blocks(lines, "tool_result"), [])

    def test_a_terminated_script_is_an_error(self) -> None:
        rows = [
            self.wrapper('await tools.exec_command({cmd:"sleep 999"});'),
            self.output("Script terminated", ""),
        ]
        (result,) = blocks(adapter.render(rows), "tool_result")
        self.assertEqual(result["tool_use_id"], "call-w")
        self.assertTrue(result["is_error"])

    def test_a_list_output_of_a_function_call_is_read_as_text(self) -> None:
        rows = [
            row(
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "false"}),
                    "call_id": "call-f",
                }
            ),
            row(
                {
                    "type": "function_call_output",
                    "call_id": "call-f",
                    "output": [
                        {
                            "type": "input_text",
                            "text": "Process exited with code 1\nOutput:\nboom",
                        }
                    ],
                }
            ),
        ]
        (result,) = blocks(adapter.render(rows), "tool_result")
        self.assertEqual((result["content"], result["is_error"]), ("boom", True))


class CommandLineTest(unittest.TestCase):
    def test_cli_output_can_be_read_by_the_detector(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--transcript-file",
                str(FIXTURES / "rollout-0.101.0.jsonl"),
                "--match",
                "Run the test suite",
            ],
            capture_output=True,
            check=True,
        )
        report = detect(result.stdout.decode("utf-8").splitlines())
        self.assertEqual(report["tool_uses"], 2)
        self.assertNotIn("exec", json.dumps(report["findings"]))

    def test_cli_refusal_exits_2_with_the_reason(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--transcript-file",
                str(FIXTURES / "rollout-0.101.0.jsonl"),
                "--match",
                "a phrase nobody typed",
            ],
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"no human user message", result.stderr)

    def run_cli(self, text: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            rollout.write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--transcript-file", str(rollout)],
                capture_output=True,
                check=False,
            )

    def test_a_lone_surrogate_is_written_escaped(self) -> None:
        line = json.dumps(
            row(
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "c",
                    "arguments": '{"cmd": "echo \\ud800"}',
                }
            )
        )
        result = self.run_cli(line + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"\\ud800", result.stdout)

    def test_the_detector_reports_a_lone_surrogate_it_quotes(self) -> None:
        rows = [
            row(
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "c",
                    "arguments": json.dumps({"cmd": "cat x"}),
                }
            ),
            row(
                {
                    "type": "function_call_output",
                    "call_id": "c",
                    "output": "Process exited with code 1\nOutput:\nerror: \ud800 bad",
                }
            ),
        ]
        result = self.run_cli("\n".join(json.dumps(r) for r in rows) + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = detect(result.stdout.decode("utf-8").splitlines())
        self.assertIn("A1", [f["signal"] for f in report["findings"]])
        # Any stdout encoding: the surrogate's escape is ASCII. Text the
        # encoding cannot hold still fails visibly; it is never turned into
        # an escape JSON does not have, with exit 0.
        cases = (
            ("ascii", "\ud800", True),
            ("latin-1", "Größe \ud800", True),
            ("ascii", "Größe 😀", False),
        )
        for encoding, text, writable in cases:
            with self.subTest(encoding=encoding, text=text):
                rows[1]["payload"]["output"] = (
                    f"Process exited with code 1\nOutput:\nerror: {text} bad"
                )
                converted = self.run_cli(
                    "\n".join(json.dumps(r) for r in rows) + "\n"
                ).stdout.decode("utf-8")
                with tempfile.TemporaryDirectory() as directory:
                    session = Path(directory) / "session.jsonl"
                    session.write_text(converted, encoding="utf-8")
                    out = subprocess.run(
                        [
                            sys.executable,
                            str(DETECTOR),
                            "--transcript-file",
                            str(session),
                            "--output-format",
                            "json",
                        ],
                        capture_output=True,
                        check=False,
                        env={**os.environ, "PYTHONIOENCODING": encoding},
                    )
                if not writable:
                    self.assertNotEqual(out.returncode, 0)
                    continue
                self.assertEqual(out.returncode, 0, out.stderr)
                snippets = json.dumps(json.loads(out.stdout.decode(encoding)))
                self.assertIn(json.dumps(text)[1:-1], snippets)

    def test_too_deep_nesting_is_refused(self) -> None:
        result = self.run_cli("[" * 200000 + "\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"nested too deeply", result.stderr)


if __name__ == "__main__":
    unittest.main()
