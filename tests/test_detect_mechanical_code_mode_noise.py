# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""A1, A9 and A19 on Code Mode sessions: what the script wrapper adds is noise."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "retro"
    / "scripts"
    / "detect-mechanical.py"
)
_spec = importlib.util.spec_from_file_location("detect_code_mode_noise", SCRIPT)
detect = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = detect
_spec.loader.exec_module(detect)

# As recorded by Claude Code 2.1.330 on 2026-11-25.
DENIED = (
    "Permission denied for Write: PreToolUse:Write hook error: "
    "[/usr/bin/python3 -I -S $HOME/.claude/hooks/security_reminder_hook.py]: "
    "Security Warning"
)


def pair(tool_id, name, inp, result, is_error=False, virtual=False):
    use = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}]
        },
    }
    res = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result,
                    "is_error": is_error,
                }
            ]
        },
    }
    if virtual:
        use["isVirtual"] = res["isVirtual"] = True
    return [use, res]


def script_error(tool_id, text, virtual=True):
    """A dispatched script's error: `isVirtual`, after its inner calls."""
    return pair(tool_id, "REPL", {}, text, True, virtual=virtual)


def errors(*events):
    uses = detect.extract_tool_uses([e for group in events for e in group])
    return [f["tool"] for f in detect.signal_tool_errors(uses)]


class RepeatedInnerErrorTest(unittest.TestCase):
    def test_a_quoted_inner_error_counts_once(self):
        self.assertEqual(
            errors(
                pair("w", "Write", {}, DENIED, True, virtual=True),
                pair("ok", "Write", {}, "", virtual=True),
                script_error("r", f"Error: write /x/y.sh: {DENIED}"),
            ),
            ["Write"],
        )

    def test_a_shell_error_counts_once(self):
        self.assertEqual(
            errors(
                pair("b", "Bash", {"command": "x"}, "boom", True, virtual=True),
                script_error("r", "ShellError: Command failed with exit code 1:"),
            ),
            ["Bash"],
        )

    def test_an_error_of_the_script_itself_is_reported(self):
        self.assertEqual(
            errors(
                pair("w", "Write", {}, DENIED, True, virtual=True),
                script_error("r", "Error: edit 1 must be [old, new]"),
            ),
            ["Write", "REPL"],
        )

    def test_a_handled_call_error_does_not_hide_an_unrelated_one(self):
        own = "ReferenceError: X is not defined"
        shell = "ShellError: Command failed with exit code 1:"
        for name, text in (("Bash", own), ("Write", shell)):
            with self.subTest(name=name):
                self.assertEqual(
                    errors(
                        pair("c", name, {}, "boom", True, virtual=True),
                        script_error("r", text),
                    ),
                    [name, "REPL"],
                )

    def test_a_shell_error_without_an_inner_error_is_reported(self):
        text = "ShellError: Command failed with exit code 1:"
        self.assertEqual(
            errors(
                pair("b", "Bash", {"command": "x"}, "fine", virtual=True),
                script_error("r", text),
            ),
            ["REPL"],
        )

    def test_an_earlier_scripts_error_does_not_hide_a_later_one(self):
        self.assertEqual(
            errors(
                pair("w", "Write", {}, DENIED, True, virtual=True),
                pair("p", "Poll", {}, "settled"),
                script_error("r", f"Error: {DENIED}"),
            ),
            ["Write", "REPL"],
        )

    def test_a_call_outside_a_script_hides_nothing(self):
        self.assertEqual(
            errors(
                pair("w", "Write", {}, DENIED, True),
                script_error("r", f"Error: {DENIED}"),
            ),
            ["Write", "REPL"],
        )

    def test_an_empty_inner_error_hides_nothing(self):
        self.assertEqual(
            errors(
                pair("w", "Write", {}, "", True, virtual=True),
                script_error("r", "Error: anything"),
            ),
            ["Write", "REPL"],
        )

    def test_another_tool_quoting_the_error_is_reported(self):
        self.assertEqual(
            errors(
                pair("w", "Write", {}, DENIED, True, virtual=True),
                pair("e", "Edit", {}, DENIED, True, virtual=True),
            ),
            ["Write", "Edit"],
        )


class DirectScriptTest(unittest.TestCase):
    def test_two_failed_scripts_in_a_row_are_both_reported(self):
        text = "Error: ReferenceError: X is not defined"
        self.assertEqual(
            errors(script_error("r1", text), script_error("r2", text)),
            ["REPL", "REPL"],
        )

    def test_the_earlier_scripts_call_does_not_hide_the_second_error(self):
        text = "ShellError: Command failed with exit code 9:"
        self.assertEqual(
            errors(
                pair("b", "Bash", {"command": "x"}, "boom", True, virtual=True),
                script_error("r1", "ShellError: Command failed with exit code 1:"),
                script_error("r2", text),
            ),
            ["Bash", "REPL"],
        )

    def test_a_directly_returned_error_is_not_matched_backwards(self):
        # Its own calls follow it; the ones before belong to another script.
        self.assertEqual(
            errors(
                pair("w", "Write", {}, DENIED, True, virtual=True),
                script_error("r", f"<repl-output>{DENIED}", virtual=False),
            ),
            ["Write", "REPL"],
        )

    def direct(self, text):
        wrapped = f"<repl-output>\n<error>{text}</error>\n</repl-output>"
        return script_error("r", wrapped, virtual=False)

    def test_a_directly_returned_error_counts_once(self):
        # Its calls follow it, and its text is escaped.
        inner = "Exit code 1\nboom <a> & <b>"
        for name, text, error in (
            ("Write", f"Error: write /x/y.sh: {DENIED}", DENIED),
            ("Read", "Error: 1 &lt; 2 &amp; more", "1 < 2 & more"),
            ("Bash", "ShellError: Command failed with exit code 1:\nboom", inner),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    errors(
                        self.direct(text),
                        pair("ok", "Read", {}, "", virtual=True),
                        pair("c", name, {}, error, True, virtual=True),
                    ),
                    [name],
                )

    def test_the_next_scripts_call_does_not_hide_a_direct_error(self):
        for between in (
            pair("p", "Poll", {}, "settled"),
            pair("n", "REPL", {}, "<repl-output>fine</repl-output>"),
        ):
            self.assertEqual(
                errors(
                    self.direct(DENIED),
                    between,
                    pair("w", "Write", {}, DENIED, True, virtual=True),
                ),
                ["REPL", "Write"],
            )

    def test_output_printed_before_a_direct_error_is_not_the_error(self):
        text = f"<repl-output><log>{DENIED}</log><error>TypeError: x</error>"
        self.assertEqual(
            errors(
                script_error("r", text, virtual=False),
                pair("w", "Write", {}, DENIED, True, virtual=True),
            ),
            ["REPL", "Write"],
        )


class GenericSequenceTest(unittest.TestCase):
    def ngrams(self, names):
        uses = detect.extract_tool_uses(
            [e for k, name in enumerate(names) for e in pair(f"u{k}", name, {}, "")]
        )
        return [f["ngram"] for f in detect.signal_tool_sequence_repetition(uses)]

    def test_generic_tools_only_is_not_reported(self):
        self.assertEqual(self.ngrams(["REPL", "Poll", "Bash", "Write"] * 4), [])

    def test_a_sequence_that_names_the_work_is_reported(self):
        self.assertIn(
            ["Read", "mcp__tt__get_day", "Bash"],
            self.ngrams(["Read", "mcp__tt__get_day", "Bash"] * 3),
        )


class RepeatedShapeTest(unittest.TestCase):
    def shapes(self, name, inp):
        events = []
        for k in range(9):
            events += pair(f"u{k}", name, inp, "")
        uses = detect.extract_tool_uses(events)
        return [f["shape"] for f in detect.signal_repeated_probe(uses)]

    def test_a_tool_name_is_no_command_shape(self):
        for name in ("Write", "Poll", "mcp__tt__get_day"):
            self.assertEqual(self.shapes(name, {}), [])

    def test_a_shell_command_still_is(self):
        self.assertEqual(
            self.shapes("Bash", {"command": "gh pr view 1"}), ["gh pr view"]
        )


if __name__ == "__main__":
    unittest.main()
