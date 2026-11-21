# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Check the raw critical-question fixtures; this does not run a retro agent."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "skills/retro/evals/fixtures/critical-questions"
)
RAN = re.compile(r"^Ran \d+ tests?", re.MULTILINE)


def run(case, argv):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / case
        shutil.copytree(FIXTURES / case, root)
        return subprocess.run(
            [sys.executable, "-B", *argv[1:]],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )


class CriticalQuestionFixturesTest(unittest.TestCase):
    def test_recorded_commands_reproduce(self):
        for case in ("downstream", "downstream-noisy", "unwired", "wired"):
            records = json.loads(
                (FIXTURES / case / "checks.json").read_text(encoding="utf-8")
            )
            self.assertTrue(records)
            for record in records:
                with self.subTest(case=case, argv=record["argv"]):
                    result = run(case, record["argv"])
                    self.assertEqual(result.returncode, record["exit_code"])
                    self.assertEqual(result.stdout, record["stdout"])
                    recorded = RAN.search(record["stderr"])
                    if recorded:
                        actual = RAN.search(result.stderr)
                        self.assertIsNotNone(actual, result.stderr)
                        self.assertEqual(actual.group(), recorded.group())

    def test_downstream_output_drops_what_the_runbook_reads(self):
        runbook = (FIXTURES / "downstream/docs/runbook.md").read_text(encoding="utf-8")
        self.assertIn("read the error printed for that host", runbook)
        self.assertIn("keeps no log file", runbook)
        before = run("downstream", ["python3", "before/report.py", "results.json"])
        after = run("downstream", ["python3", "after/report.py", "results.json"])
        self.assertIn("disk full on /var", before.stdout)
        self.assertNotIn("disk full", after.stdout)
        session = (FIXTURES / "downstream/session.txt").read_text(encoding="utf-8")
        self.assertNotIn("runbook", session)

    def test_noisy_downstream_names_the_on_call_procedure_nowhere(self):
        root = FIXTURES / "downstream-noisy"
        procedure = (root / "docs/operations/on-call.md").read_text(encoding="utf-8")
        self.assertIn("read the error printed for that host", procedure)
        for name in (
            "before/report.py",
            "after/report.py",
            "results.json",
            "session.txt",
        ):
            self.assertEqual(
                (root / name).read_bytes(),
                (FIXTURES / "downstream" / name).read_bytes(),
                name,
            )
        files = [p for p in root.rglob("*") if p.is_file()]
        self.assertGreaterEqual(len(files), 30)
        for path in files:
            if path.name == "on-call.md":
                continue
            text = path.read_text(encoding="utf-8").lower()
            with self.subTest(path=str(path.relative_to(root))):
                for pointer in ("on-call", "runbook", "operations/"):
                    self.assertNotIn(pointer, text)

    def test_unwired_runs_the_checks_nowhere_and_wired_runs_them(self):
        def text(case, rel):
            path = FIXTURES / case / rel
            return path.read_text(encoding="utf-8") if path.exists() else ""

        self.assertNotIn("make test", text("unwired", ".github/workflows/build.yml"))
        self.assertNotIn("make lint", text("unwired", ".github/workflows/build.yml"))
        self.assertFalse((FIXTURES / "unwired/.pre-commit-config.yaml").exists())
        self.assertFalse((FIXTURES / "unwired/.github/workflows/ci.yml").exists())
        ci = text("wired", ".github/workflows/ci.yml")
        self.assertIn("make test", ci)
        self.assertIn("make lint", ci)
        self.assertIn("make lint", text("wired", ".pre-commit-config.yaml"))


if __name__ == "__main__":
    unittest.main()
