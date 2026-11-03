# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""The adapter freezes raw inputs and keeps the oracle out of target context."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills/retro/scripts/prepare-behavior-evals.py"
)
spec = importlib.util.spec_from_file_location("prepare_behavior_evals", SCRIPT)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

CASE = """---
id: example
trigger: "A raw observed event"
expected:
  - PRIVATE_SUCCESS_ORACLE
negative_expected:
  - PRIVATE_FAILURE_ORACLE
fixture: fixtures/example
---
PRIVATE_EXPLANATION
"""


class PrepareBehaviorEvalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.skill = self.root / "skill"
        (self.skill / "evals/fixtures/example").mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("Candidate instructions", encoding="utf-8")
        (self.skill / "evals/example.md").write_text(CASE, encoding="utf-8")
        (self.skill / "evals/fixtures/example/source.txt").write_text(
            "Raw input", encoding="utf-8"
        )
        self.args = argparse.Namespace(
            skill_dir=self.skill,
            baseline_dir=None,
            reference=[],
            candidate_reference=[],
            case=["example"],
            all=False,
            output_dir=self.root / "run",
            target_label="actual-primary",
            model="unresolved-alias",
            model_version=None,
            review_model=None,
            judge_model=None,
            runtime="native-test",
            reasoning_budget=None,
            tool_environment=None,
            samples=3,
        )

    def test_private_oracle_never_enters_execution_inputs(self):
        result = adapter.prepare(self.args)
        output = self.args.output_dir
        for path in (output / "execution").rglob("*"):
            if path.is_file():
                self.assertNotIn("PRIVATE_", path.read_text(encoding="utf-8"))
        shared = json.loads((output / "shared/evals.json").read_text(encoding="utf-8"))[
            "evals"
        ][0]
        self.assertNotIn("PRIVATE_", shared["prompt"])
        self.assertIn("PRIVATE_SUCCESS_ORACLE", shared["expectations"])
        self.assertEqual(result["status"], "prepared_not_executed")
        self.assertIsNone(result["target"]["resolved_model_version"])
        self.assertEqual(result["target"]["execution_model"], "unresolved-alias")

    def test_frozen_fixture_is_independent_of_later_source_edits(self):
        result = adapter.prepare(self.args)
        (self.skill / "evals/fixtures/example/source.txt").write_text(
            "Changed", encoding="utf-8"
        )
        frozen = self.args.output_dir / "execution/example/inputs/source.txt"
        self.assertEqual(frozen.read_text(encoding="utf-8"), "Raw input")
        record = next(
            x for x in result["cases"][0]["inputs"] if x["path"].endswith("source.txt")
        )
        self.assertEqual(record["sha256"], adapter.digest(frozen))

    def test_baseline_and_candidate_share_cases_but_have_distinct_contexts(self):
        self.args.baseline_dir = self.root / "baseline"
        self.args.baseline_dir.mkdir()
        (self.args.baseline_dir / "SKILL.md").write_text(
            "Old instructions", encoding="utf-8"
        )
        result = adapter.prepare(self.args)
        self.assertNotEqual(
            result["contexts"]["baseline"]["sha256"],
            result["contexts"]["candidate"]["sha256"],
        )
        self.assertEqual(len(result["cases"]), 1)
        candidate_input = self.args.output_dir / "execution/example/inputs/source.txt"
        candidate_input.write_text("Candidate edit", encoding="utf-8")
        baseline_input = (
            self.args.output_dir / "execution/baseline-cases/example/inputs/source.txt"
        )
        self.assertEqual(baseline_input.read_text(encoding="utf-8"), "Raw input")

    def test_context_requires_same_explicit_references_in_both_arms(self):
        self.args.reference = ["missing.md"]
        with self.assertRaisesRegex(ValueError, "Missing"):
            adapter.prepare(self.args)
        self.assertFalse(self.args.output_dir.exists())

    def test_new_candidate_reference_is_explicit_and_does_not_rewrite_baseline(self):
        self.args.baseline_dir = self.root / "baseline"
        self.args.baseline_dir.mkdir()
        (self.args.baseline_dir / "SKILL.md").write_text("Old", encoding="utf-8")
        (self.skill / "new-reference.md").write_text("New capability", encoding="utf-8")
        self.args.candidate_reference = ["new-reference.md"]
        result = adapter.prepare(self.args)
        self.assertEqual(len(result["contexts"]["baseline"]["sources"]), 1)
        self.assertEqual(len(result["contexts"]["candidate"]["sources"]), 2)
        self.assertNotIn(
            "New capability",
            (self.args.output_dir / "execution/baseline-context.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_eval_content_cannot_be_selected_as_context(self):
        self.args.reference = ["evals/example.md"]
        with self.assertRaisesRegex(ValueError, "answers"):
            adapter.prepare(self.args)

    def test_reuse_and_unknown_cases_are_rejected(self):
        self.args.case = ["absent"]
        with self.assertRaisesRegex(ValueError, "Unknown cases"):
            adapter.prepare(self.args)
        self.args.case = ["example"]
        adapter.prepare(self.args)
        with self.assertRaisesRegex(ValueError, "already exists"):
            adapter.prepare(self.args)

    def test_fixture_cannot_escape_eval_directory(self):
        (self.skill / "evals/example.md").write_text(
            CASE.replace("fixtures/example", "../.."), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "Invalid fixture"):
            adapter.prepare(self.args)

    def test_environment_fixture_exposes_a_real_missing_prerequisite(self):
        source = SCRIPT.parents[1] / "evals/fixtures/environment"
        copied = self.root / "environment"
        shutil.copytree(source, copied)
        baseline = subprocess.run(
            ["sh", str(copied / "run-tests.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(baseline.returncode, 0)
        prepared = subprocess.run(
            [sys.executable, str(copied / "bootstrap.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        for _ in range(2):
            checked = subprocess.run(
                ["sh", str(copied / "run-tests.sh")],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn("Local database check passed", checked.stdout)


if __name__ == "__main__":
    unittest.main()
