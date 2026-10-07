# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Codex rollout conversion, including functions.exec wrapper unwrapping."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "retro" / "scripts" / "codex-transcript.py"
spec = importlib.util.spec_from_file_location("codex_transcript", SCRIPT)
adapter = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(adapter)


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


class CodexTranscriptTest(unittest.TestCase):
    def test_human_messages_survive_and_synthetic_skill_text_does_not_count(
        self,
    ) -> None:
        rows = [
            message("user", "# AGENTS.md instructions for /repo"),
            message("user", "请检查进度条"),
            message("assistant", "已检查。"),
            message("user", "<skill>expanded slash command</skill>"),
        ]
        lines = [json.loads(line) for line in adapter.render(rows, "请检查进度条")]
        self.assertEqual(
            [line["type"] for line in lines], ["user", "user", "assistant", "user"]
        )
        self.assertTrue(lines[0]["isMeta"])
        self.assertFalse(lines[1]["isMeta"])
        self.assertTrue(lines[3]["isMeta"])
        with self.assertRaisesRegex(ValueError, "no user message"):
            adapter.render(rows, "a missing phrase")

    def test_nested_commands_replace_the_exec_wrapper(self) -> None:
        rows = [
            message("user", "Check the repository"),
            tool(
                'const ignored = "tools.exec_command({cmd:\\"not a call\\"})"; '
                '// tools.exec_command({cmd:"also not a call"})\n'
                "const r=await Promise.allSettled(["
                'tools.exec_command({note:"cmd: fake",cmd:"git status --short",workdir:"/repo"}),'
                'tools.exec_command({"cmd":"npm test",workdir:"/repo"})]); text(r);'
            ),
        ]
        events = [json.loads(line) for line in adapter.render(rows)]
        uses = [
            block
            for event in events
            for block in event["message"]["content"]
            if block["type"] == "tool_use"
        ]
        self.assertEqual([item["name"] for item in uses], ["Bash", "Bash"])
        self.assertEqual(
            [item["input"]["command"] for item in uses],
            ["git status --short", "npm test"],
        )
        self.assertNotIn("exec", [item["name"] for item in uses])
        self.assertEqual(events[1]["message"]["id"], events[2]["message"]["id"])

    def test_patch_paths_are_extracted_when_the_argument_is_literal(self) -> None:
        rows = [
            tool(
                'text(await tools.apply_patch("*** Begin Patch\\n'
                "*** Update File: src/app.py\\n*** Add File: tests/test_app.py\\n"
                '*** End Patch"));'
            )
        ]
        use = json.loads(adapter.render(rows)[0])["message"]["content"][0]
        self.assertEqual(use["name"], "Patch")
        self.assertEqual(
            use["input"]["file_paths"], ["src/app.py", "tests/test_app.py"]
        )

    def test_dynamic_commands_are_omitted_instead_of_inventing_exec_calls(self) -> None:
        rows = [
            message("user", "Review"),
            tool("await tools.exec_command({cmd: buildCommand()});"),
        ]
        events = [json.loads(line) for line in adapter.render(rows)]
        self.assertEqual([event["type"] for event in events], ["user"])

    def test_cli_output_can_be_read_by_the_detector(self) -> None:
        rows = [
            message("user", "Check the repository"),
            tool('await tools.exec_command({cmd:"git status --short"});'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            rollout = Path(directory) / "rollout.jsonl"
            normalized = Path(directory) / "session.jsonl"
            rollout.write_text(
                "\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--transcript-file",
                    str(rollout),
                    "--match",
                    "Check the repository",
                ],
                capture_output=True,
                check=True,
            )
            normalized.write_bytes(result.stdout)
            detect = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "skills" / "retro" / "scripts" / "detect-mechanical.py"),
                    "--transcript-file",
                    str(normalized),
                    "--output-format",
                    "json",
                ],
                capture_output=True,
                check=True,
            )
            report = json.loads(detect.stdout)
            self.assertEqual(report["tool_uses"], 1)
            self.assertNotIn("exec", json.dumps(report["findings"]))


if __name__ == "__main__":
    unittest.main()
