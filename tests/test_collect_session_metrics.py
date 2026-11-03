# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Usage is evidence, with missing values and overlapping work kept explicit."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills/retro/scripts/collect-session-metrics.py"


def load():
    spec = importlib.util.spec_from_file_location("collect_session_metrics", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.metrics = load()

    def test_real_codex_snapshots_are_not_added_to_their_deltas(self):
        rows = [
            json.loads(line)
            for line in (ROOT / "tests/fixtures/codex/usage-0.166.0-alpha.5.1.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        report = self.metrics.collect(rows)
        self.assertEqual(report["usage"]["counts"]["total_tokens"], 65466)
        self.assertEqual(report["usage"]["counts"]["cached_input_tokens"], 42880)
        self.assertEqual(report["usage"]["basis"], "cumulative_snapshot")
        self.assertIsNone(report["cost"])

    def test_missing_is_not_zero_and_a_counter_reset_is_unknown(self):
        report = self.metrics.collect([{"type": "user", "message": {"content": "x"}}])
        self.assertIsNone(report["usage"]["counts"]["total_tokens"])
        self.assertIsNone(report["timing"]["observed_span_seconds"])
        rows = [
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": total}},
                },
            }
            for total in (100, 50)
        ]
        self.assertIsNone(self.metrics.collect(rows)["usage"]["counts"]["total_tokens"])

    def test_copied_transcript_cannot_be_counted_as_an_independent_child(self):
        with tempfile.TemporaryDirectory() as directory:
            parent, child = (
                Path(directory) / "parent.jsonl",
                Path(directory) / "child.jsonl",
            )
            content = (
                ROOT / "tests/fixtures/codex/usage-0.166.0-alpha.5.1.jsonl"
            ).read_bytes()
            parent.write_bytes(content)
            child.write_bytes(content)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--transcript-file",
                    str(parent),
                    "--subagent-transcript",
                    str(child),
                    "--subagent-usage",
                    "excluded",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("copied transcript supplied twice", result.stderr)

    def test_counter_reset_across_missing_component_is_unknown(self):
        rows = [
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": value},
                },
            }
            for value in ({"total_tokens": 100}, {}, {"total_tokens": 50})
        ]
        report = self.metrics.collect(rows)
        self.assertEqual(report["usage"]["status"], "unknown")
        self.assertIsNone(report["usage"]["counts"]["total_tokens"])

    def test_embedded_summary_preserves_valid_data_and_rejects_invalid_counters(self):
        report = self.metrics.collect([{"type": "user"}])
        self.assertEqual(self.metrics.collect([{"retro_metrics": report}]), report)
        report["usage"]["counts"]["total_tokens"] = -1
        with self.assertRaises(ValueError):
            self.metrics.collect([{"retro_metrics": report}])

    def test_malformed_embedded_summary_is_a_controlled_cli_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.jsonl"
            path.write_text('{"type":"user","retro_metrics":{}}\n', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--transcript-file", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid embedded metrics", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_all_unknown_claude_usage_is_not_actual(self):
        report = self.metrics.collect(
            [{"type": "assistant", "message": {"id": "message-1", "usage": {}}}]
        )
        self.assertEqual(report["usage"]["status"], "unknown")

    def test_claude_message_updates_do_not_duplicate_usage(self):
        rows = [
            {
                "type": "assistant",
                "message": {
                    "id": "message-1",
                    "model": "sonnet",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": count,
                        "cache_read_input_tokens": 2,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }
            for count in (3, 5)
        ]
        report = self.metrics.collect(rows)
        self.assertEqual(report["usage"]["counts"]["output_tokens"], 5)
        self.assertEqual(report["usage"]["counts"]["total_tokens"], 17)
        self.assertEqual(
            report["provenance"]["execution"]["reported_models"], ["sonnet"]
        )
        self.assertIsNone(report["provenance"]["execution"]["exact_model_version"])

    def test_parallel_time_uses_union_and_unknown_overlap_does_not_sum_tokens(self):
        reports = [
            self.metrics.collect(
                [
                    {"timestamp": start, "type": "user"},
                    {"timestamp": end, "type": "user"},
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {"total_token_usage": {"total_tokens": count}},
                        },
                    },
                ]
            )
            for start, end, count in [
                ("2026-11-03T08:00:00Z", "2026-11-03T08:00:10Z", 100),
                ("2026-11-03T08:00:05Z", "2026-11-03T08:00:15Z", 50),
            ]
        ]
        report = self.metrics.combine(reports, "unknown")
        self.assertEqual(report["observed_interval_union_seconds"], 15)
        self.assertIsNone(report["usage"]["counts"]["total_tokens"])
        self.assertEqual(
            self.metrics.combine(reports, "included")["usage"]["counts"][
                "total_tokens"
            ],
            100,
        )
        self.assertEqual(
            self.metrics.combine(reports, "excluded")["usage"]["counts"][
                "total_tokens"
            ],
            150,
        )


if __name__ == "__main__":
    unittest.main()
