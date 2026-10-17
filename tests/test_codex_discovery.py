# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
"""Native Codex inventory: active versions, standalone skills and coverage."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "codex_discovery", ROOT / "skills/retro/scripts/find-org-skills.py"
)
discovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discovery)


class CodexDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / ".codex"

    def skill(self, path, name, description):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n", encoding="utf-8"
        )

    def test_standalone_skills_include_both_roots(self):
        self.skill(self.home / "skills/local/SKILL.md", "local", "Local workflow")
        self.skill(
            self.home.parent / ".agents/skills/global/SKILL.md",
            "global",
            "Shared workflow",
        )
        rows = discovery.collect_codex(self.home, {})
        self.assertEqual({r["name"] for r in rows}, {"local", "global"})
        self.assertTrue(all(r["installed"] and r["path"] for r in rows))

    def test_recorded_version_wins_over_newer_cached_copy(self):
        for version in ("1.0.0", "2.0.0"):
            self.skill(
                self.home
                / f"plugins/cache/catalog/example/{version}/skills/check/SKILL.md",
                "check",
                f"Version {version}",
            )
        plugin = {
            "name": "example",
            "marketplaceName": "catalog",
            "version": "1.0.0",
            "enabled": True,
            "source": {"source": "remote"},
        }
        rows = discovery.collect_codex(self.home, {"installed": [plugin]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Version 1.0.0")
        self.assertIn("/1.0.0/", rows[0]["path"])

    def test_local_source_available_and_disabled_plugins(self):
        base = self.home.parent / "source"
        self.skill(base / "skills/check/SKILL.md", "check", "Active source")
        rows = discovery.collect_codex(
            self.home,
            {
                "installed": [
                    {
                        "name": "disabled",
                        "enabled": False,
                        "source": {"source": "local", "path": str(base)},
                    }
                ],
                "available": [
                    {
                        "name": "optional",
                        "description": "Not installed",
                        "source": {"repo": "org/optional"},
                    }
                ],
            },
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["installed"])
        self.assertEqual(rows[0]["description_source"], "catalogue")
        self.assertEqual(rows[0]["repo_url"], "https://github.com/org/optional")
        rows = discovery.collect_codex(
            self.home,
            {
                "installed": [
                    {
                        "name": "local-plugin",
                        "source": {"source": "local", "path": str(base)},
                    }
                ]
            },
        )
        self.assertEqual(rows[0]["description"], "Active source")

    def test_cache_path_escape_is_not_read(self):
        self.skill(
            self.home / "outside/skills/check/SKILL.md", "outside", "Must not be read"
        )
        rows = discovery.collect_codex(
            self.home,
            {
                "installed": [
                    {
                        "name": "bad",
                        "marketplaceName": "..",
                        "version": "../outside",
                        "source": {"source": "remote"},
                    }
                ]
            },
        )
        self.assertFalse(any(r.get("path") for r in rows))

    def test_non_object_source_remains_catalogue_only(self):
        rows = discovery.collect_codex(
            self.home,
            {"available": [{"name": "optional", "source": "remote"}]},
        )
        self.assertEqual(rows[0]["description_source"], "catalogue")
        self.assertFalse(rows[0]["installed"])

    def test_cli_failure_is_explicit_reduced_coverage(self):
        self.skill(self.home / "skills/local/SKILL.md", "local", "Local")
        with (
            patch.object(discovery.subprocess, "run", side_effect=FileNotFoundError),
            patch("sys.stderr") as stderr,
        ):
            rows = discovery.codex_catalogue(self.home)
        self.assertEqual(rows[0]["coverage"], "standalone-only")
        self.assertTrue(stderr.write.called)

    def test_cli_uses_native_read_only_inventory(self):
        result = subprocess.CompletedProcess(
            [], 0, json.dumps({"installed": [], "available": []})
        )
        with patch.object(discovery.subprocess, "run", return_value=result) as run:
            discovery.codex_catalogue(self.home)
        self.assertEqual(run.call_args.args[0], ["codex", "plugin", "list", "--json"])
        self.assertEqual(run.call_args.kwargs["env"]["CODEX_HOME"], str(self.home))

    def test_malformed_cli_payload_falls_back_without_claiming_full_coverage(self):
        self.skill(self.home / "skills/local/SKILL.md", "local", "Local")
        for data in ([], {"installed": None}):
            with self.subTest(data=data):
                result = subprocess.CompletedProcess([], 0, json.dumps(data))
                with (
                    patch.object(discovery.subprocess, "run", return_value=result),
                    patch("sys.stderr"),
                ):
                    rows = discovery.codex_catalogue(self.home)
                self.assertEqual(rows[0]["coverage"], "standalone-only")


if __name__ == "__main__":
    unittest.main()
