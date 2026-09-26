"""Tests for skills/retro/scripts/find-installed-skills.sh.

The script runs for real against a temporary CLAUDE_HOME. Descriptions come
from find-org-skills.py's frontmatter parser, so the shapes below are the
ones the old awk extraction returned wrongly: a block scalar came back as
`>-`, single quotes and `\\"` escapes stayed in the text.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "retro" / "scripts" / "find-installed-skills.sh"

SKILLS = {
    "folded": "description: >-\n  Use when folded\n  across lines",
    "single": "description: 'Use when ''quoted'' twice'",
    "escaped": 'description: "Use when \\"escaped\\" quotes"',
    "plain": "description: Use when plain",
}


class FindInstalledSkillsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        for name, line in SKILLS.items():
            skill = self.home / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\n{line}\nmetadata:\n  author: a\n---\n# {name}\n",
                encoding="utf-8",
            )

    def _run(self, path: str | None = None):
        env = {**os.environ, "CLAUDE_HOME": str(self.home)}
        if path is not None:
            env["PATH"] = path
        return subprocess.run(
            ["bash", str(SCRIPT)], capture_output=True, text=True, check=False, env=env
        )

    def test_descriptions_are_parsed_as_yaml_scalars(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        skills = {s["name"]: s for s in json.loads(result.stdout)}
        self.assertEqual(
            {name: s["description"] for name, s in skills.items()},
            {
                "folded": "Use when folded across lines",
                "single": "Use when 'quoted' twice",
                "escaped": 'Use when "escaped" quotes',
                "plain": "Use when plain",
            },
        )
        self.assertEqual(
            sorted(skills["plain"]), ["description", "name", "path", "repo_url"]
        )

    def test_missing_jq_is_an_error_not_an_empty_list(self):
        """`[]` with exit 0 would read as "no skills installed"."""
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        for tool in ("bash", "dirname", "basename", "readlink", "python3", "git"):
            found = shutil.which(tool)
            self.assertIsNotNone(found, tool)
            (bin_dir / tool).symlink_to(found)
        result = self._run(path=str(bin_dir))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("jq is required", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
