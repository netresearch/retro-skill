# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""`--scan-since`: the pre-pass over the window after an earlier retro."""

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


def call(tool_id: str, result: str, stamp: str | None) -> list[dict]:
    """A failed shell call; both events carry `stamp` unless it is None."""
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "Bash",
                        "input": {"command": "make"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result,
                        "is_error": True,
                    }
                ]
            },
        },
    ]
    if stamp is not None:
        for event in events:
            event["timestamp"] = stamp
    return events


OLD, NEW = "2026-11-25T13:00:00.000Z", "2026-11-25T14:00:00.000Z"
EVENTS = call("o", "old failure", OLD) + call("n", "new failure", NEW)


def run(events: list[dict], *extra: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--transcript-file",
                str(path),
                "--signals",
                "A1",
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


def snippets(events: list[dict], since: str) -> list[str]:
    out = run(events, "--scan-since", since)
    return [f["snippet"] for f in json.loads(out.stdout)["findings"]]


class ScanSinceTest(unittest.TestCase):
    def test_without_it_everything_is_read(self):
        report = json.loads(run(EVENTS).stdout)
        self.assertEqual(report["findings_total"], 2)
        self.assertNotIn("scan_since", report)

    def test_only_the_window_is_read(self):
        report = json.loads(run(EVENTS, "--scan-since", "2026-11-25T13:09:00Z").stdout)
        self.assertEqual([f["snippet"] for f in report["findings"]], ["new failure"])
        self.assertEqual(report["events_before_scan_since"], 2)

    def test_turns_stay_those_of_the_whole_transcript(self):
        report = json.loads(run(EVENTS, "--scan-since", "2026-11-25T13:09:00Z").stdout)
        self.assertEqual(report["findings"][0]["turn"], 2)

    def test_the_cutoff_itself_is_in_the_window(self):
        self.assertEqual(snippets(EVENTS, NEW), ["new failure"])

    def test_an_offset_is_read_as_the_same_moment(self):
        for since in ("2026-11-25T14:30:00+01:00", "2026-11-25T14:30:00+0100"):
            self.assertEqual(snippets(EVENTS, since), ["new failure"])

    def test_a_time_without_a_zone_is_utc(self):
        self.assertEqual(snippets(EVENTS, "2026-11-25T13:30:00"), ["new failure"])

    def test_an_event_without_a_timestamp_is_kept(self):
        events = call("u", "undated failure", None) + EVENTS
        self.assertEqual(
            snippets(events, "2026-11-25T13:09:00Z"),
            ["undated failure", "new failure"],
        )

    def test_an_unreadable_time_is_refused(self):
        for since in ("yesterday", ""):
            with self.subTest(since=since):
                out = run(EVENTS, "--scan-since", since)
                self.assertEqual(out.returncode, 2)
                self.assertIn("not an ISO 8601 time", out.stderr)

    def test_an_empty_window_is_refused(self):
        out = run(EVENTS, "--scan-since", "2026-11-26T00:00:00Z")
        self.assertEqual(out.returncode, 2)
        self.assertIn("No event at or after", out.stderr)

    def test_undated_events_alone_are_no_window(self):
        out = run(call("u", "x", None), "--scan-since", OLD)
        self.assertEqual(out.returncode, 2)

    def test_the_text_output_names_the_window(self):
        out = run(
            EVENTS, "--output-format", "text", "--scan-since", "2026-11-25T13:09:00Z"
        )
        self.assertIn("2 events before it were not read", out.stdout)


if __name__ == "__main__":
    unittest.main()
