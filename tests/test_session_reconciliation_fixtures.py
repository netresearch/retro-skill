# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Check the raw scenarios' ground truth; this does not run a retro agent."""

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "skills/retro/evals/fixtures/session-reconciliation"
)


def load_module(case, name):
    path = FIXTURES / case / "after" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{case}_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SessionReconciliationFixturesTest(unittest.TestCase):
    def test_recorded_checks_pass_and_command_outputs_are_reproducible(self):
        for case in ("case-a", "case-b", "case-d"):
            root = FIXTURES / case
            records = json.loads((root / "checks.json").read_text(encoding="utf-8"))
            for record in records:
                with self.subTest(case=case, command=record["argv"]):
                    result = subprocess.run(
                        [sys.executable, "-B", *record["argv"][1:]],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.returncode, record["exit_code"])
                    if record["stdout"].strip():
                        self.assertEqual(
                            json.loads(result.stdout), json.loads(record["stdout"])
                        )

    def test_inventory_a_leaves_an_enabled_job_out_despite_passing_checks(self):
        module = load_module("case-a", "inventory")
        responses = json.loads(
            (FIXTURES / "case-a/api.json").read_text(encoding="utf-8")
        )
        client = module.Client(responses)
        result = module.collect(client)
        self.assertEqual(result, ["build"])
        self.assertNotEqual(result, ["build", "deploy"])
        self.assertEqual(client.calls, ["/jobs?limit=2"])

    def test_inventory_b_satisfies_the_same_contract_with_bounded_change(self):
        module = load_module("case-b", "inventory")
        responses = json.loads(
            (FIXTURES / "case-b/api.json").read_text(encoding="utf-8")
        )
        self.assertEqual(module.collect(module.Client(responses)), ["build", "deploy"])

    def test_inventory_c_does_not_supply_the_delegated_implementation(self):
        root = FIXTURES / "case-c"
        self.assertTrue((root / "before/inventory.py").is_file())
        self.assertTrue((root / "api.json").is_file())
        self.assertFalse((root / "after").exists())
        self.assertFalse((root / "checks.json").exists())

    def test_rendering_preserves_page_isolation_but_not_language_isolation(self):
        module = load_module("case-d", "rendering")
        content = json.loads(
            (FIXTURES / "case-d/content.json").read_text(encoding="utf-8")
        )
        cache = {}
        self.assertEqual(module.render(cache, "home", "en", content), "Welcome")
        self.assertEqual(module.render(cache, "about", "en", content), "About us")
        result = module.render(cache, "home", "de", content)
        self.assertEqual(result, "Welcome")
        self.assertNotEqual(result, content["home"]["de"])


if __name__ == "__main__":
    unittest.main()
