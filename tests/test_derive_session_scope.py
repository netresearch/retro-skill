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
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def _clean_env() -> dict[str, str]:
    """The environment without the variables that override `git -C`."""
    return {k: v for k, v in os.environ.items() if k not in dss.GIT_LOCATION_VARS}


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, env=_clean_env())


class LoneSurrogateTest(unittest.TestCase):
    # json.loads turns an unpaired "\ud800" escape in a transcript into a lone
    # surrogate, which str.encode() refuses; one such command must not end
    # the whole scan.
    COMMAND = "echo \ud800 && gh pr comment 7 --body x"

    def test_shell_reads_a_command_with_a_lone_surrogate(self):
        shell = dss._Shell(self.COMMAND)
        self.assertFalse(shell.misparsed)
        self.assertEqual(len(shell.source), len(self.COMMAND))

    def test_scan_survives_a_transcript_line_with_a_lone_surrogate(self):
        events = [
            {
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": self.COMMAND},
                        }
                    ]
                }
            },
            {
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
                    ]
                }
            },
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.jsonl"
            # json.dumps escapes the surrogate, as the harness writes it.
            path.write_text("\n".join(json.dumps(e) for e in events))
            data = dss.collect_artefacts(path, "gitlab.com")
        self.assertIn("artefacts", data)


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

    def test_a_plain_directory_named_bare_is_no_repository(self) -> None:
        (self.outside / ".bare").mkdir()
        self.assertIsNone(dss.repo_root(self.outside / "gone" / "a.md"))

    def test_the_bare_repository_wins_over_an_enclosing_work_tree(self) -> None:
        _git("init", "-q", str(self.project.parent))
        self.assertEqual(
            dss.repo_root(self.removed / "docs" / "a.md"), self.bare.resolve()
        )
        self.assertEqual(dss.repo_root(self.live / "a.md"), self.live.resolve())

    def test_git_dir_in_the_environment_does_not_redirect_the_probe(self) -> None:
        other = self.outside / "other"
        _git("init", "-q", str(other))
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            self.assertEqual(
                dss.repo_root(self.removed / "docs" / "a.md"), self.bare.resolve()
            )

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


def _bash_events(commands: list[str], cwd: str | None = None) -> list[dict]:
    """One Bash call per command with its result, as Claude Code writes them;
    `cwd` on every event when given."""
    events = []
    for n, command in enumerate(commands):
        use = {"type": "tool_use", "id": f"c{n}", "name": "Bash"}
        use["input"] = {"command": command}
        result = {"type": "tool_result", "tool_use_id": f"c{n}", "content": ""}
        for event in (
            {"type": "assistant", "message": {"content": [use]}},
            {"type": "user", "message": {"content": [result]}},
        ):
            event["timestamp"] = "2026-09-25T10:00:00Z"
            if cwd is not None:
                event["cwd"] = cwd
            events.append(event)
    return events


def _write(path: Path, events: list) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


class RelativePathTest(unittest.TestCase):
    """A-F1: a relative `git -C` or `cd` path was resolved against the
    directory the script ran in, so the same transcript named different
    repositories from different places, and nothing from elsewhere."""

    # The reviewer's reproducer (ra_gen3.py), verbatim.
    COMMANDS = ("git -C .bare fetch origin", "cd ../fix-x && git status")

    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        self.project = root / "proj"
        self.bare = self.project / ".bare"
        _git("init", "--bare", "-q", str(self.bare))
        (self.project / "main").mkdir()
        self.elsewhere = root / "elsewhere"
        self.elsewhere.mkdir()
        self.addCleanup(os.chdir, os.getcwd())

    def test_without_a_cwd_nothing_is_resolved_against_the_scripts_directory(
        self,
    ) -> None:
        # Run from inside the project, where `.bare` would resolve.
        os.chdir(self.project)
        path = _write(self.elsewhere / "s.jsonl", _bash_events(list(self.COMMANDS)))
        scope = dss.collect(path)
        self.assertEqual(scope["repositories"], [])
        self.assertEqual(scope["unresolved_paths"], ["../fix-x", ".bare"])

    def test_the_events_cwd_is_the_base(self) -> None:
        os.chdir(self.elsewhere)
        events = _bash_events(list(self.COMMANDS), cwd=str(self.project / "main"))
        events[0]["cwd"] = events[1]["cwd"] = str(self.project)
        scope = dss.collect(_write(self.elsewhere / "s.jsonl", events))
        # `.bare` from the project; `../fix-x` from main: a removed worktree.
        self.assertEqual(scope["repositories"], [str(self.bare.resolve())])
        self.assertEqual(scope["unresolved_paths"], [])

    def test_a_relative_path_after_a_cd_is_relative_to_the_cd(self) -> None:
        other = self.elsewhere / "repoB"
        _git("init", "-q", str(other))
        os.chdir(self.project)
        events = _bash_events([f"cd {self.elsewhere} && git -C repoB status"])
        scope = dss.collect(_write(self.elsewhere / "s.jsonl", events))
        self.assertEqual(scope["repositories"], [str(other.resolve())])
        self.assertEqual(scope["unresolved_paths"], [str(self.elsewhere)])


class CommandShapeTest(unittest.TestCase):
    """A-F4 and A-F10: shell syntax the regexes did not read."""

    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        self.root = root
        self.repo = root / "repoA"
        _git("init", "-q", str(self.repo))

    def _scope(self, commands: list[str]) -> dict:
        return dss.collect(_write(self.root / "s.jsonl", _bash_events(commands)))

    def test_a_cd_on_the_second_line_is_read(self) -> None:
        # scope1.jsonl, first call, with the reviewer's repoA replaced.
        scope = self._scope([f"set -o pipefail\ncd {self.repo} && make test | tail -3"])
        self.assertEqual(scope["repositories"], [str(self.repo.resolve())])

    def test_a_cd_after_a_line_the_grammar_glues_on_is_read(self) -> None:
        # tree-sitter-bash reads the lines after `a | b || c` as arguments of
        # one command; a newline between two words starts the next command.
        scope = self._scope(
            [f"ps -eo cmd | grep x | head -5 || echo none\ncd {self.repo} && make"]
        )
        self.assertEqual(scope["repositories"], [str(self.repo.resolve())])

    def test_release_tags_with_git_c_and_options_before_the_name(self) -> None:
        # scope1.jsonl, second and third call, verbatim.
        scope = self._scope(
            [
                "git -C /nonexistent/x tag -s v1.2.3 -m 'v1.2.3'",
                "git -C /nonexistent/x push origin v1.2.3",
            ]
        )
        self.assertEqual(scope["tags"], ["v1.2.3"])

    def test_tag_forms_that_name_no_release(self) -> None:
        scope = self._scope(
            [
                'git tag -a v2.0.0 -m "1.9.9"',  # the message is not a tag
                "git tag -d v9.9.9",  # deleting one
                "git push --delete origin v8.8.8",
                "git commit -m 'git tag v7.7.7'",  # text
            ]
        )
        self.assertEqual(scope["tags"], ["v2.0.0"])

    def test_a_shell_given_its_program_as_a_string_is_read(self) -> None:
        scope = self._scope([f"bash -lc 'cd {self.repo} && git status'"])
        self.assertEqual(scope["repositories"], [str(self.repo.resolve())])


class MalformedTranscriptTest(unittest.TestCase):
    """A-F12: a line that is JSON but not an event must not end the scan."""

    def test_lines_that_are_not_events_are_skipped(self) -> None:
        good = {"type": "user", "timestamp": "2026-09-25T10:00:00Z"}
        good["message"] = {"role": "user", "content": "hi"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            # bad_nondict.jsonl from the review, then a message that is text.
            path.write_text(
                json.dumps(good) + "\n[1,2]\n"
                '{"type": "user", "message": "not an object"}\n',
                encoding="utf-8",
            )
            out = subprocess.run(
                [sys.executable, str(SCRIPT), "--transcript-file", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("2026-09-25", out.stdout)


class SlashBranchWorktreeTest(unittest.TestCase):
    """A-F8 (repo_root half): the worktree of a branch `fix/x` lives in
    `<project>/fix/x`; removing it leaves the empty `fix/` behind, and the
    nearest existing directory has no `.bare` beside it."""

    def test_a_removed_worktree_of_a_branch_with_a_slash(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        project = root / "proj"
        bare = project / ".bare"
        worktree = project / "fix" / "x"
        _git("init", "--bare", "-q", str(bare))
        _git(
            "-C",
            str(bare),
            "worktree",
            "add",
            "-q",
            "--orphan",
            "-b",
            "fix/x",
            str(worktree),
        )
        _git("-C", str(bare), "worktree", "remove", str(worktree))
        self.assertTrue((project / "fix").is_dir())
        self.assertEqual(dss.repo_root(worktree / "a.md"), bare.resolve())


if __name__ == "__main__":
    unittest.main()
