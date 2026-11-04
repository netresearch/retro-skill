# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""`--since-command`: the pre-pass over one slash-command run only.

Phase 11 (self-check) asks what went wrong in the retro run itself. The rest of
the session is the work the retro just analysed; its findings must not come
back as findings about retro. `--since-command retro` blanks every event before
the last `/retro` invocation and keeps the indices, so a finding still points
at its real turn.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "retro"
    / "scripts"
    / "detect-mechanical.py"
)


def _command(name: str) -> dict:
    """A slash-command expansion as Claude Code records it."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": f"<command-message>{name}</command-message>\n"
            f"<command-name>/{name}</command-name>",
        },
    }


def _user(text: str) -> dict:
    """A message the human typed, as a text block."""
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _call(tool_id: str, command: str, result: str, is_error: bool) -> list[dict]:
    return [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "Bash",
                        "input": {"command": command},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result,
                        "is_error": is_error,
                    }
                ],
            },
        },
    ]


def _run(events: list[dict], *extra: str) -> subprocess.CompletedProcess:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)  # noqa: SIM115 -- path returned; unlinked below
    tmp.write("\n".join(json.dumps(e) for e in events) + "\n")
    tmp.close()
    try:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--transcript-file",
                tmp.name,
                "--signals",
                "A1",
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        Path(tmp.name).unlink(missing_ok=True)


# Work before the retro fails once, the first retro run fails once, and the
# second, last retro run fails once (a jq call guessing a field name).
EVENTS = (
    _call("w1", "make build", "Error: build failed", True)
    + [_command("retro:retro")]
    + _call("r1", "uv run detect-mechanical.py", "Error: first run", True)
    + [_command("retro:retro")]
    + _call(
        "r2",
        "jq -r '.findings[].summary' mech.json",
        "jq: error: Cannot index string",
        True,
    )
)


class SinceCommand(unittest.TestCase):
    def test_without_the_flag_every_failure_is_reported(self):
        out = _run(EVENTS)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["findings_total"], 3)

    def test_only_the_last_run_of_the_command_is_analysed(self):
        out = _run(EVENTS, "--since-command", "retro")
        self.assertEqual(out.returncode, 0, out.stderr)
        report = json.loads(out.stdout)
        self.assertEqual(report["findings_total"], 1)
        self.assertIn("Cannot index string", report["findings"][0]["snippet"])

    def test_turn_numbers_stay_those_of_the_whole_transcript(self):
        report = json.loads(_run(EVENTS, "--since-command", "retro").stdout)
        # 2 events per call, 1 per command: w1(0,1) cmd(2) r1(3,4) cmd(5) r2(6,7)
        self.assertEqual(report["since_event"], 5)
        self.assertGreaterEqual(report["findings"][0]["turn"], 5)

    def test_a_command_that_never_ran_is_an_error_not_an_empty_result(self):
        out = _run(_call("w1", "make", "ok", False), "--since-command", "retro")
        self.assertEqual(out.returncode, 2)
        self.assertIn("/retro", out.stderr)
        self.assertEqual(out.stdout, "")

    def test_a_message_quoting_the_tag_is_not_an_invocation(self):
        # A later message that quotes the tag must not move the start past the
        # run's own errors and turn them into "nothing found".
        quoted = _user("as you can see, <command-name>/retro</command-name> ran twice")
        report = json.loads(_run(EVENTS + [quoted], "--since-command", "retro").stdout)
        self.assertEqual(report["since_event"], 5)
        self.assertEqual(report["findings_total"], 1)

    def test_a_typed_invocation_counts_as_in_a_codex_transcript(self):
        # codex-transcript.py copies the typed text verbatim: no command tags.
        events = (
            _call("w1", "make build", "Error: build failed", True)
            + [_user("/retro zur retro?")]
            + _call("r1", "jq .x out.json", "jq: error: Cannot index", True)
        )
        report = json.loads(_run(events, "--since-command", "retro").stdout)
        self.assertEqual(report["since_event"], 2)
        self.assertEqual(report["findings_total"], 1)

    def test_a_typed_mention_or_a_longer_command_is_not_an_invocation(self):
        for text in ("please run /retro later", "/retrospective now", "/retro-x"):
            with self.subTest(text=text):
                events = [_user(text)] + _call("w1", "make", "ok", False)
                self.assertEqual(_run(events, "--since-command", "retro").returncode, 2)

    def test_a_null_text_block_is_skipped_not_a_crash(self):
        odd = {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": None}]},
        }
        out = _run([odd] + EVENTS, "--since-command", "retro")
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_a_name_that_is_not_a_command_name_is_refused(self):
        out = _run(EVENTS, "--since-command", "re(t|r)o")
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stdout, "")


if __name__ == "__main__":
    unittest.main()
