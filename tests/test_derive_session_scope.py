"""Tests for how skills/retro/scripts/derive-session-scope.py finds repositories.

The shape that prompted them: a session in a bare-repository layout
(`<project>/.bare` beside one worktree per branch) that ends with a clean merge
and removes its worktree. Every path the transcript names is then gone or has
no work tree, and the scope line reported 0 repositories — the cleanup gate
swept nothing.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "retro"
    / "scripts"
    / "derive-session-scope.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("derive_session_scope", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dss = _load()


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


class BareLayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        self.project = root / "proj"
        self.bare = self.project / ".bare"
        _git("init", "--bare", "-q", str(self.bare))
        self.live = self.project / "main"
        _git(
            "-C",
            str(self.bare),
            "worktree",
            "add",
            "-q",
            "--orphan",
            "-b",
            "main",
            str(self.live),
        )
        removed = self.project / "feat-x"
        _git(
            "-C",
            str(self.bare),
            "worktree",
            "add",
            "-q",
            "--orphan",
            "-b",
            "feat-x",
            str(removed),
        )
        _git("-C", str(self.bare), "worktree", "remove", str(removed))
        self.removed = removed
        self.outside = root / "elsewhere"
        self.outside.mkdir()

    def test_a_live_worktree_is_its_own_root(self) -> None:
        self.assertEqual(dss.repo_root(self.live / "a.md"), self.live.resolve())

    def test_a_removed_worktree_resolves_to_the_bare_repository(self) -> None:
        self.assertEqual(
            dss.repo_root(self.removed / "docs" / "a.md"), self.bare.resolve()
        )

    def test_the_bare_repository_and_the_project_directory_resolve_to_it(self) -> None:
        self.assertEqual(dss.repo_root(self.bare), self.bare.resolve())
        self.assertEqual(dss.repo_root(self.project), self.bare.resolve())

    def test_a_directory_outside_any_repository_has_none(self) -> None:
        self.assertIsNone(dss.repo_root(self.outside / "x.md"))

    def test_scope_of_a_session_whose_worktree_was_removed(self) -> None:
        transcript = self.outside / "session.jsonl"
        events = [
            {
                "timestamp": "2026-09-25T10:00:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t0",
                            "name": "Edit",
                            "input": {"file_path": str(self.removed / "README.md")},
                        },
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": f"git -C {self.bare} fetch origin"},
                        },
                    ]
                },
            }
        ]
        transcript.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
        )
        scope = dss.collect(transcript)
        self.assertEqual(scope["repositories"], [str(self.bare.resolve())])
        self.assertEqual(scope["unresolved_paths"], [])


if __name__ == "__main__":
    unittest.main()
