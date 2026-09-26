#!/usr/bin/env python3
"""Unit tests for skills/retro/scripts/scan-cross-session.py (Schicht C)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "retro" / "scripts" / "scan-cross-session.py"


def _load():
    spec = importlib.util.spec_from_file_location("scan_cross_session", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scs = _load()


class Transcript:
    """Builds a session JSONL the way Claude Code writes it."""

    def __init__(self, day: int = 1) -> None:
        self.day = day
        self.events: list[dict] = []
        self.n = 0

    def _ts(self) -> str:
        self.n += 1
        return f"2026-09-{self.day:02d}T10:{self.n // 60:02d}:{self.n % 60:02d}Z"

    def user(self, text: str) -> Transcript:
        self.events.append(
            {"type": "user", "timestamp": self._ts(), "message": {"content": text}}
        )
        return self

    def call(self, name: str, inp: dict, result: str, is_error: bool = False):
        use_id = f"toolu_{len(self.events)}"
        self.events.append(
            {
                "type": "assistant",
                "timestamp": self._ts(),
                "message": {
                    "content": [
                        {"type": "tool_use", "id": use_id, "name": name, "input": inp}
                    ]
                },
            }
        )
        self.events.append(
            {
                "type": "user",
                "timestamp": self._ts(),
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": use_id,
                            "content": result,
                            "is_error": is_error,
                        }
                    ]
                },
            }
        )
        return self

    def write(self, root: Path, project: str, session: str) -> Path:
        path = root / project / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(e) for e in self.events) + "\n", encoding="utf-8"
        )
        return path


def _sessions(root: Path) -> list[dict]:
    sessions, _skipped = scs.read_sessions(scs.session_files(root, None, 3650))
    return sessions


def _run(root: Path, *args: str) -> dict:
    out = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--projects-dir",
            str(root),
            "--days",
            "3650",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)


class LoadEventsTest(TempDirCase):
    def test_skips_lines_that_are_not_objects(self) -> None:
        path = self.root / "s.jsonl"
        path.write_text(
            '[1, 2]\n"text"\nnot json\n{"type": "user"}\n', encoding="utf-8"
        )
        self.assertEqual(scs.load_events(path), [{"type": "user"}])

    def test_a_vanished_transcript_is_skipped_not_counted(self) -> None:
        Transcript().user("hello").write(self.root, "-p", "present")
        files = scs.session_files(self.root, None, 3650)
        files.append((self.root / "-p" / "gone.jsonl", "-p"))
        sessions, skipped = scs.read_sessions(files)
        self.assertEqual([s["id"] for s in sessions], ["present"])
        self.assertEqual(skipped, [str(self.root / "-p" / "gone.jsonl")])

    def test_user_texts_survive_a_non_object_line(self) -> None:
        path = self.root / "s.jsonl"
        path.write_text(
            '[1]\n{"type": "user", "message": {"content": "no, not that"}}\n',
            encoding="utf-8",
        )
        self.assertEqual(scs.extract_user_texts(path), ["no, not that"])


class CorrectionSummaryTest(TempDirCase):
    def test_counts_sessions_within_one_project(self) -> None:
        for session in ("a", "b"):
            Transcript().user("No, use the Read tool").write(self.root, "-p", session)
        out = _run(self.root, "--user-correction-summary")
        self.assertEqual(out["sessions_scanned"], 2)
        self.assertEqual(out["projects_scanned"], 1)
        [hit] = out["cross_session_corrections"]
        self.assertEqual(hit["sessions_count"], 2)
        self.assertEqual(hit["projects_count"], 1)
        self.assertEqual(hit["sessions"], ["a", "b"])
        self.assertEqual(out["cross_project_corrections"], [])

    def test_caps_the_cross_session_list(self) -> None:
        for session in ("a", "b"):
            Transcript().user("No, use the Read tool").user("Stop polling").write(
                self.root, "-p", session
            )
        out = _run(self.root, "--user-correction-summary", "--limit", "1")
        self.assertEqual(len(out["cross_session_corrections"]), 1)
        self.assertTrue(out["cross_session_truncated"])

    def test_a_single_session_is_not_recurring(self) -> None:
        Transcript().user("No, use the Read tool").user("no, use the read tool").write(
            self.root, "-p", "a"
        )
        out = _run(self.root, "--user-correction-summary")
        self.assertEqual(out["cross_session_corrections"], [])

    def _synthetic(self, transcript: Transcript, content, **flags) -> None:
        event = {"type": "user", "timestamp": transcript._ts()}
        event["message"] = {"role": "user", "content": content}
        transcript.events.append({**event, **flags})

    def test_harness_text_is_not_a_correction(self) -> None:
        # A-F3: every cross-session correction the review measured was
        # harness text stamped isMeta — `Stop hook feedback: …` matches
        # `^stop\b`. A human's correction in the same sessions still counts.
        for session in ("a", "b"):
            t = Transcript()
            self._synthetic(
                t, "Stop hook feedback:\nname the waiter before ending", isMeta=True
            )
            self._synthetic(t, "No, that is the summary", isCompactSummary=True)
            self._synthetic(
                t,
                [
                    {
                        "type": "text",
                        "text": "<command-message>pr-finish</command-message>",
                    },
                    {"type": "text", "text": "# /pr-finish\nno merge without green"},
                ],
            )
            t.user("No, use the Read tool").write(self.root, "-p", session)
        out = _run(self.root, "--user-correction-summary")
        self.assertEqual(
            [hit["snippet"] for hit in out["cross_session_corrections"]],
            ["no, use the read tool"],
        )

    def test_the_markers_match_detect_mechanicals(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "detect_mechanical", SCRIPT.parent / "detect-mechanical.py"
        )
        detector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(detector)
        self.assertEqual(scs.SYNTHETIC_USER_MARKERS, detector._SYNTHETIC_USER_MARKERS)


class FailureLineTest(unittest.TestCase):
    def test_takes_the_marked_line_of_a_bash_failure(self) -> None:
        result = "Exit code 1\nrunning checks\nfatal: not a git repository\ndone"
        self.assertEqual(
            scs.failure_line("Bash", result), "fatal: not a git repository"
        )

    def test_takes_the_last_line_of_a_traceback(self) -> None:
        result = (
            "Exit code 1\nTraceback (most recent call last):\n"
            "  File \"x.py\", line 3, in <module>\nKeyError: 'turn'"
        )
        self.assertEqual(scs.failure_line("Bash", result), "KeyError: 'turn'")

    def test_a_bare_exit_code_has_no_message(self) -> None:
        self.assertEqual(scs.failure_line("Bash", "Exit code 2"), "")

    def test_normalise_drops_values(self) -> None:
        self.assertEqual(
            scs.normalise(
                "ls: cannot access '/tmp/a/b': No such file (42) at 1a2b3c4d"
            ),
            "ls: cannot access '<path>': No such file (<n>) at <hex>",
        )
        # A slash inside a word is prose, not a path.
        self.assertEqual(scs.normalise("piped into tail/head"), "piped into tail/head")


class RecurringFailuresTest(TempDirCase):
    DENIAL = "`cat` to read a file. Use the Read tool."

    def _two_sessions(self) -> None:
        for session, path in (("a", "/x/one"), ("b", "/y/two")):
            (
                Transcript()
                .call(
                    "Bash",
                    {"command": "ls"},
                    f"Exit code 2\nls: cannot access '{path}': No such file or directory",
                    True,
                )
                .call("Bash", {"command": "cat f"}, self.DENIAL, True)
                .call(
                    "Bash",
                    {"command": "cat g"},
                    f"PreToolUse:Bash hook error: {self.DENIAL}",
                    True,
                )
                .call("Bash", {"command": "false"}, "Exit code 1", True)
                .write(self.root, "-p", session)
            )
        Transcript().call(
            "Bash", {"command": "x"}, "Exit code 1\nerror: only once here", True
        ).write(self.root, "-p", "c")

    def test_the_same_failure_in_two_sessions_is_one_finding(self) -> None:
        self._two_sessions()
        found = scs.recurring_failures(_sessions(self.root))
        [hit] = found["recurring"]
        self.assertEqual(hit["kind"], "failure")
        self.assertEqual(
            hit["error"], "ls: cannot access '<path>': No such file or directory"
        )
        self.assertEqual(hit["sessions"], ["a", "b"])

    def test_refusals_are_excluded_and_counted(self) -> None:
        self._two_sessions()
        found = scs.recurring_failures(_sessions(self.root))
        self.assertEqual(found["excluded"], {"refusals": 4, "without_message": 2})

    def test_refusals_with_and_without_prefix_share_a_key(self) -> None:
        self._two_sessions()
        found = scs.recurring_failures(_sessions(self.root), include_refusals=True)
        refusals = [r for r in found["recurring"] if r["kind"] == "refusal"]
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["sessions_count"], 2)

    def test_a_tool_use_error_is_a_failure_not_a_refusal(self) -> None:
        for session in ("a", "b"):
            Transcript().call(
                "Bash",
                {"command": "x"},
                "<tool_use_error>InputValidationError: command contains control characters</tool_use_error>",
                True,
            ).write(self.root, "-p", session)
        [hit] = scs.recurring_failures(_sessions(self.root))["recurring"]
        self.assertEqual(hit["kind"], "failure")

    def test_cli_caps_the_list(self) -> None:
        for session in ("a", "b"):
            t = Transcript()
            for word in ("alpha", "beta", "gamma"):
                t.call(
                    "Bash", {"command": "x"}, f"Exit code 1\nerror: {word} broke", True
                )
            t.write(self.root, "-p", session)
        out = _run(self.root, "--recurring-failures", "--limit", "2")
        self.assertEqual(len(out["recurring"]), 2)
        self.assertTrue(out["truncated"])
        self.assertEqual(out["sessions_read"], 2)


def _git(*args: str) -> None:
    env = {k: v for k, v in os.environ.items() if k not in scs.GIT_LOCATION_VARS}
    subprocess.run(["git", *args], check=True, capture_output=True, env=env)


class FileKeyTest(TempDirCase):
    def test_worktrees_of_one_bare_repository_share_a_key(self) -> None:
        project = self.root / "proj"
        _git("init", "--bare", "-q", str(project / ".bare"))
        _git(
            "-C",
            str(project / ".bare"),
            "worktree",
            "add",
            "-q",
            "--orphan",
            "-b",
            "one",
            str(project / "one"),
        )
        live = scs.file_key(str(project / "one" / "docs" / "a.md"))
        # A removed worktree is recognised from the project directory that remains.
        removed = scs.file_key(str(project / "gone-branch" / "docs" / "a.md"))
        self.assertEqual(live, (str((project / ".bare").resolve()), "docs/a.md"))
        self.assertEqual(removed, live)

    def test_a_file_outside_any_repository_keeps_its_path(self) -> None:
        path = str(self.root / "loose" / "notes.md")
        self.assertEqual(scs.file_key(path), (None, path))

    def _bare_project(self) -> Path:
        project = self.root / "proj"
        _git("init", "--bare", "-q", str(project / ".bare"))
        return project

    def test_a_plain_directory_named_bare_is_no_repository(self) -> None:
        (self.root / "plain" / ".bare").mkdir(parents=True)
        path = str(self.root / "plain" / "gone" / "a.md")
        self.assertEqual(scs.file_key(path), (None, path))

    def test_the_bare_repository_wins_over_an_enclosing_work_tree(self) -> None:
        project = self._bare_project()
        _git("init", "-q", str(self.root))
        self.assertEqual(
            scs.file_key(str(project / "gone" / "docs" / "a.md")),
            (str((project / ".bare").resolve()), "docs/a.md"),
        )

    def test_git_dir_in_the_environment_does_not_redirect_the_probe(self) -> None:
        project = self._bare_project()
        other = self.root / "other"
        _git("init", "-q", str(other))
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            key = scs.file_key(str(project / "gone" / "docs" / "a.md"))
        self.assertEqual(key, (str((project / ".bare").resolve()), "docs/a.md"))

    # A-F8: the worktree of a branch with a slash (`fix/x`) sits in
    # `<project>/fix/x`. After `git worktree remove` its files must key like
    # every other worktree's: the bare repository and the path inside it.
    def _removed_slash_worktree(self) -> tuple[Path, Path]:
        project = self._bare_project()
        bare = project / ".bare"
        worktree = project / "fix" / "x"
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
        _git(
            "-C",
            str(worktree),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.org",
            "commit",
            "-q",
            "--allow-empty",
            "--no-gpg-sign",
            "-m",
            "x",
        )
        _git("-C", str(bare), "worktree", "remove", str(worktree))
        return bare.resolve(), worktree

    def test_a_removed_slash_worktree_whose_parent_directory_remains(self) -> None:
        bare, worktree = self._removed_slash_worktree()
        self.assertTrue(worktree.parent.is_dir())  # the empty `fix/`
        self.assertEqual(scs.file_key(str(worktree / "a.txt")), (str(bare), "a.txt"))

    def test_a_removed_slash_worktree_is_found_by_its_branch(self) -> None:
        bare, worktree = self._removed_slash_worktree()
        worktree.parent.rmdir()
        self.assertEqual(
            scs.file_key(str(worktree / "docs" / "a.txt")), (str(bare), "docs/a.txt")
        )

    def test_a_remote_tracking_branch_outlives_the_local_one(self) -> None:
        bare, worktree = self._removed_slash_worktree()
        worktree.parent.rmdir()
        _git("-C", str(bare), "update-ref", "refs/remotes/origin/fix/x", "fix/x")
        _git("-C", str(bare), "branch", "-D", "fix/x")
        self.assertEqual(scs.file_key(str(worktree / "a.txt")), (str(bare), "a.txt"))

    def test_without_a_trace_the_first_directory_is_the_worktree(self) -> None:
        # The documented limit: branch deleted everywhere, `fix/` removed as
        # well — nothing says the worktree was two levels deep.
        bare, worktree = self._removed_slash_worktree()
        worktree.parent.rmdir()
        _git("-C", str(bare), "branch", "-D", "fix/x")
        self.assertEqual(scs.file_key(str(worktree / "a.txt")), (str(bare), "x/a.txt"))


class FollowUpSessionsTest(TempDirCase):
    WROTE = "the earlier session wrote this sentence"

    def _edit(self, day: int, session: str, old: str, new: str, path: str) -> None:
        Transcript(day).call(
            "Edit", {"file_path": path, "old_string": old, "new_string": new}, "ok"
        ).write(self.root, "-p", session)

    def _found(self, window_days: int = 7) -> dict:
        return scs.follow_up_sessions(_sessions(self.root), timedelta(days=window_days))

    def test_a_later_session_rewriting_earlier_text_is_found(self) -> None:
        path = str(self.root / "loose" / "a.md")
        self._edit(1, "a", "old text", self.WROTE, path)
        self._edit(3, "b", self.WROTE, "something else entirely", path)
        [hit] = self._found()["rewritten_edits"]
        self.assertEqual((hit["earlier_session"], hit["later_session"]), ("a", "b"))
        self.assertFalse(hit["exact_revert"])

    def test_an_exact_revert_is_marked_and_ranked_first(self) -> None:
        path = str(self.root / "loose" / "a.md")
        other = str(self.root / "loose" / "b.md")
        self._edit(1, "a", "old text", self.WROTE, path)
        Transcript(2).call(
            "MultiEdit",
            {
                "file_path": path,
                "edits": [{"old_string": self.WROTE, "new_string": "old text"}],
            },
            "ok",
        ).call(
            "Edit",
            {"file_path": other, "old_string": "x", "new_string": self.WROTE},
            "ok",
        ).write(self.root, "-p", "b")
        self._edit(3, "c", self.WROTE, "changed", other)
        hits = self._found()["rewritten_edits"]
        self.assertTrue(hits[0]["exact_revert"])
        self.assertEqual(hits[0]["file"], path)
        self.assertFalse(hits[1]["exact_revert"])

    def test_outside_the_window_nothing_is_found(self) -> None:
        path = str(self.root / "loose" / "a.md")
        self._edit(1, "a", "old text", self.WROTE, path)
        self._edit(20, "b", self.WROTE, "changed", path)
        self.assertEqual(self._found()["rewritten_edits"], [])
        self.assertEqual(len(self._found(window_days=30)["rewritten_edits"]), 1)

    def test_short_text_does_not_count(self) -> None:
        path = str(self.root / "loose" / "a.md")
        self._edit(1, "a", "old", "True", path)
        self._edit(2, "b", "return True", "return False", path)
        self.assertEqual(self._found()["rewritten_edits"], [])

    def test_a_failed_edit_does_not_count(self) -> None:
        path = str(self.root / "loose" / "a.md")
        self._edit(1, "a", "old text", self.WROTE, path)
        Transcript(2).call(
            "Edit",
            {"file_path": path, "old_string": self.WROTE, "new_string": "changed"},
            "String to replace not found in file.",
            is_error=True,
        ).write(self.root, "-p", "b")
        self.assertEqual(self._found()["rewritten_edits"], [])

    def test_a_revert_of_an_earlier_sessions_commit_is_found(self) -> None:
        Transcript(1).call(
            "Bash",
            {"command": "git commit -S -m 'feat: x'"},
            "[feat/x 1a2b3c4d] feat: x\n 1 file changed",
        ).write(self.root, "-p", "a")
        Transcript(2).call(
            "Bash",
            {"command": "git -C /r revert --no-edit 1a2b3c4"},
            "[main 9f8e7d6] Revert",
        ).write(self.root, "-p", "b")
        Transcript(2).call(
            "Bash", {"command": "git revert deadbee"}, "[main 1111111] Revert"
        ).write(self.root, "-p", "c")
        [hit] = self._found()["reverted_commits"]
        self.assertEqual(
            hit, {"commit": "1a2b3c4d", "earlier_session": "a", "later_session": "b"}
        )


if __name__ == "__main__":
    unittest.main()
