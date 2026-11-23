# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Unit tests for skills/retro/scripts/steering-size.py."""

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = REPO_ROOT / "skills" / "retro" / "scripts" / "steering-size.py"
    spec = importlib.util.spec_from_file_location("steering_size", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ss = _load()


class SteeringSizeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.repo = base / "repo"
        self.home = base / "home"
        self.repo.mkdir()
        self.home.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def run_main(self, *argv: str) -> dict:
        out = io.StringIO()
        with redirect_stdout(out):
            code = ss.main([*argv, "--home", str(self.home)])
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def entry(self, report: dict, path: Path) -> dict:
        return next(f for f in report["files"] if f["path"] == str(path))

    def test_sizes_of_every_always_loaded_file(self):
        self.write(self.repo / "AGENTS.md", "# P\n\nline\n")
        self.write(self.home / ".claude" / "CLAUDE.md", "a" * 400 + "\n")
        self.write(self.home / ".codex" / "AGENTS.md", "x\ny\n")
        r = self.run_main("--repo", str(self.repo))
        self.assertEqual(
            [Path(f["path"]).name for f in r["files"]],
            ["AGENTS.md", "CLAUDE.md", "CLAUDE.md", "AGENTS.md"],
        )
        agents = self.entry(r, self.repo / "AGENTS.md")
        self.assertEqual((agents["lines"], agents["bytes"]), (3, 10))
        self.assertFalse(agents["imported_by_claude_md"])
        self.assertFalse(self.entry(r, self.repo / "CLAUDE.md")["exists"])
        glob = self.entry(r, self.home / ".claude" / "CLAUDE.md")
        self.assertEqual(
            (glob["lines"], glob["bytes"], glob["approx_tokens"]), (1, 401, 100)
        )
        self.assertEqual(self.entry(r, self.home / ".codex" / "AGENTS.md")["lines"], 2)

    def test_without_repo_only_global_files(self):
        r = self.run_main()
        self.assertEqual(len(r["files"]), 2)
        self.assertTrue(all(not f["exists"] for f in r["files"]))

    def test_claude_md_that_imports_agents_md(self):
        self.write(self.repo / "AGENTS.md", "rules\n")
        self.write(self.repo / "CLAUDE.md", "# Claude\n\n@AGENTS.md\n")
        r = self.run_main("--repo", str(self.repo))
        self.assertTrue(self.entry(r, self.repo / "AGENTS.md")["imported_by_claude_md"])

    def test_import_inside_a_sentence(self):
        self.write(self.repo / "AGENTS.md", "rules\n")
        self.write(self.repo / "CLAUDE.md", "See @AGENTS.md for rules\n")
        r = self.run_main("--repo", str(self.repo))
        self.assertTrue(self.entry(r, self.repo / "AGENTS.md")["imported_by_claude_md"])

    def test_code_span_or_fence_is_no_import(self):
        self.write(self.repo / "AGENTS.md", "rules\n")
        for text in (
            "Write `x @AGENTS.md y` to import.\n",
            "~~~text\n@AGENTS.md\n~~~\n",
            "````md\n```\n@AGENTS.md\n```\n````\n",
        ):
            self.write(self.repo / "CLAUDE.md", text)
            r = self.run_main("--repo", str(self.repo))
            entry = self.entry(r, self.repo / "AGENTS.md")
            self.assertFalse(entry["imported_by_claude_md"], text)

    def test_import_after_a_closed_fence_counts(self):
        self.write(self.repo / "AGENTS.md", "rules\n")
        self.write(self.repo / "CLAUDE.md", "```\ncode\n```\n@AGENTS.md\n")
        r = self.run_main("--repo", str(self.repo))
        self.assertTrue(self.entry(r, self.repo / "AGENTS.md")["imported_by_claude_md"])

    def test_other_import_is_not_agents_md(self):
        self.write(self.repo / "AGENTS.md", "rules\n")
        self.write(self.repo / "CLAUDE.md", "@AGENTS.md.bak and @docs/AGENTS.md\n")
        r = self.run_main("--repo", str(self.repo))
        self.assertFalse(
            self.entry(r, self.repo / "AGENTS.md")["imported_by_claude_md"]
        )

    def test_proposed_delta_is_signed(self):
        target = self.write(self.repo / "AGENTS.md", "one\ntwo\nthree\n")
        grown = self.write(
            self.repo.parent / "grown.md", "one\ntwo\nthree\nfour\nfive\n"
        )
        shrunk = self.write(self.repo.parent / "shrunk.md", "one\n")
        r = self.run_main("--repo", str(self.repo), "--proposed", f"{target}={grown}")
        self.assertEqual(
            self.entry(r, target)["proposed_delta"], {"lines": 2, "bytes": 10}
        )
        r = self.run_main("--repo", str(self.repo), "--proposed", f"{target}={shrunk}")
        self.assertEqual(
            self.entry(r, target)["proposed_delta"], {"lines": -2, "bytes": -10}
        )

    def test_symlinked_claude_md_gets_the_agents_md_delta(self):
        agents = self.write(self.repo / "AGENTS.md", "a\nb\n")
        (self.repo / "CLAUDE.md").symlink_to("AGENTS.md")
        grown = self.write(self.repo.parent / "grown.md", "a\nb\nc\n")
        r = self.run_main("--repo", str(self.repo), "--proposed", f"{agents}={grown}")
        delta = {"lines": 1, "bytes": 2}
        self.assertEqual(self.entry(r, agents)["proposed_delta"], delta)
        claude = self.entry(r, self.repo / "CLAUDE.md")
        self.assertEqual(claude["proposed_delta"], delta)
        self.assertEqual(claude["same_file_as"], str(agents))

    def test_proposed_delta_for_a_new_file(self):
        new = self.write(self.repo.parent / "new.md", "a\nb\n")
        target = self.home / ".codex" / "AGENTS.md"
        r = self.run_main("--proposed", f"{target}={new}")
        self.assertEqual(
            self.entry(r, target)["proposed_delta"], {"lines": 2, "bytes": 4}
        )

    def test_proposed_target_that_is_not_always_loaded_is_refused(self):
        new = self.write(self.repo.parent / "new.md", "a\n")
        with self.assertRaises(SystemExit):
            ss.main(
                ["--home", str(self.home), "--proposed", f"{self.repo}/docs/x.md={new}"]
            )


if __name__ == "__main__":
    unittest.main()
