"""Regression tests for the review findings on detect-mechanical.py.

Each class pins one finding; the first case in each is the reviewer's
reproducer, copied event for event.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "retro"
    / "scripts"
    / "detect-mechanical.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("detect_mechanical_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect = _load()


def _write(lines: list[str]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)  # noqa: SIM115 -- path returned; caller unlinks
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    return Path(tmp.name)


def _run_cli(lines: list[str], signals: str | None = None):
    path = _write(lines)
    try:
        cmd = [sys.executable, str(SCRIPT), "--transcript-file", str(path)]
        if signals:
            cmd += ["--signals", signals]
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False
        )
    finally:
        path.unlink(missing_ok=True)


def _uses(events: list[dict]):
    path = _write([json.dumps(e) for e in events])
    try:
        return detect.extract_tool_uses(detect.load_jsonl(path))
    finally:
        path.unlink(missing_ok=True)


def call(msg_id, tool_id, name, input_, result="ok"):
    """One tool call as Claude Code writes it: its own assistant event, carrying
    the message id, followed by its own tool_result event."""
    assistant = {"type": "assistant", "message": {"role": "assistant", "content": []}}
    if msg_id is not None:
        assistant["message"]["id"] = msg_id
    assistant["message"]["content"].append(
        {"type": "tool_use", "id": tool_id, "name": name, "input": input_}
    )
    return [
        assistant,
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result,
                        "is_error": False,
                    }
                ],
            },
        },
    ]


def bash(msg_id, tool_id, command, result="ok"):
    return call(msg_id, tool_id, "Bash", {"command": command}, result)


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


# --- A-F2: parallel calls are one message, not a sequence ------------------------


class TestParallelCallsAreOneMessage(unittest.TestCase):
    # a5.jsonl: three Reads sharing message.id msg_1, each in its own event,
    # interleaved with their results.
    A5_REPRODUCER: ClassVar[list[dict]] = [
        user("look at the three files"),
        *call("msg_1", "t0", "Read", {"file_path": "/r/a.py"}, "x"),
        *call("msg_1", "t1", "Read", {"file_path": "/r/b.py"}, "x"),
        *call("msg_1", "t2", "Read", {"file_path": "/r/c.py"}, "x"),
    ]

    # The layout the pre-existing test uses: every call in ONE assistant event.
    SINGLE_EVENT: ClassVar[list[dict]] = [
        {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"p{n}",
                        "name": "Read",
                        "input": {"file_path": f"/{n}.py"},
                    }
                    for n in range(3)
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": f"p{n}", "content": "ok"}
                    for n in range(3)
                ]
            },
        },
    ]

    def test_A5_interleaved_parallel_batch_does_not_fire(self):
        uses = _uses(self.A5_REPRODUCER)
        self.assertEqual(detect.signal_sequential_parallelizable(uses), [])

    def test_A2_interleaved_parallel_batch_does_not_fire(self):
        uses = _uses(self.A5_REPRODUCER)
        self.assertEqual(detect.signal_retry_clusters(uses), [])

    def test_A2_single_event_parallel_batch_does_not_fire(self):
        uses = _uses(self.SINGLE_EVENT)
        self.assertEqual(detect.signal_retry_clusters(uses), [])

    def test_cli_interleaved_parallel_batch_reports_neither(self):
        lines = [json.dumps(e) for e in self.A5_REPRODUCER]
        proc = _run_cli(lines, "A2,A5")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["findings"], [])

    def test_A5_sequential_calls_with_distinct_message_ids_still_fire(self):
        # The control: the same three Reads, each its own message.
        evs = [user("look")]
        for n in range(3):
            evs += call(f"msg_{n}", f"t{n}", "Read", {"file_path": f"/r/{n}.py"})
        findings = detect.signal_sequential_parallelizable(_uses(evs))
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["assistant_messages"], [1, 3, 5])

    def test_A2_sequential_retries_with_distinct_message_ids_still_fire(self):
        evs = []
        for n in range(3):
            evs += bash(f"msg_{n}", f"t{n}", f"gh pr view {n} --json state", "{}")
        findings = detect.signal_retry_clusters(_uses(evs))
        self.assertEqual([f["signal"] for f in findings], ["A2"])

    def test_A5_run_mixing_one_batch_and_two_singles_counts_messages(self):
        # Two parallel Reads (one message) then two single-call messages:
        # three messages, four calls -> still a sequential run of three.
        evs = [
            *call("m_a", "t0", "Read", {"file_path": "/0"}),
            *call("m_a", "t1", "Read", {"file_path": "/1"}),
            *call("m_b", "t2", "Read", {"file_path": "/2"}),
            *call("m_c", "t3", "Read", {"file_path": "/3"}),
        ]
        findings = detect.signal_sequential_parallelizable(_uses(evs))
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["assistant_messages"], [0, 4, 6])

    def test_extract_tool_uses_carries_the_message_id(self):
        uses = _uses(self.A5_REPRODUCER)
        self.assertEqual([len(u) for u in uses], [5, 5, 5])
        self.assertEqual([u.message_id for u in uses], ["msg_1"] * 3)


# --- A-F5: `git -C <dir>` / `git -c k=v` before the subcommand -------------------


def a14(evs):
    return detect.signal_main_branch_work(_uses(evs))


class TestGitGlobalOptions(unittest.TestCase):
    # a14c.jsonl
    A14C_REPRODUCER: ClassVar[list[dict]] = [
        user("commit it"),
        *bash(
            "m1",
            "g1",
            "git -C /p/proj/main status",
            "On branch main\nnothing to commit",
        ),
        *bash(
            "m2",
            "g2",
            "git -C /p/proj/main commit -m x",
            "[main 1a2b3c4] x\n 1 file changed",
        ),
        *bash(
            "m3",
            "g3",
            "git -C /p/proj/main push origin main",
            "To github.com:o/r.git\n   0000000..1a2b3c4  main -> main",
        ),
        *bash("m4", "g4", "git push origin main", "ok"),
    ]

    def test_A14_dash_C_commit_and_push_on_main_are_reported(self):
        commands = [f["command"] for f in a14(self.A14C_REPRODUCER)]
        self.assertEqual(
            commands,
            [
                "git -C /p/proj/main commit -m x",
                "git -C /p/proj/main push origin main",
                "git push origin main",
            ],
        )

    def test_command_shape_skips_git_global_options(self):
        """A2/A19 group by shape; `git -C <dir> push` is `git push`, not `git`."""
        self.assertEqual(
            detect.command_shapes("git -C /p/proj/main push origin main"), ["git push"]
        )
        self.assertEqual(
            detect.command_shapes("git -c core.pager=cat -C /p log -1"), ["git log"]
        )

    def test_A15_dash_C_commit_with_bot_attribution_fires(self):
        cmd = 'git -C /p/proj commit -m "fix: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"'
        findings = detect.signal_bot_attribution(
            [(0, "Bash", {"command": cmd}, "", False)]
        )
        self.assertEqual([f["signal"] for f in findings], ["A15"])

    def test_A17_failed_dash_C_push_fires(self):
        use = (
            0,
            "Bash",
            {"command": "git -C /p/proj push origin feat"},
            "rejected",
            True,
        )
        findings = detect.signal_upstream_failure([use])
        self.assertEqual([f["signal"] for f in findings], ["A17"])

    def test_A14_dash_c_config_before_commit_on_main_fires(self):
        evs = bash("m1", "g1", "git status", "On branch main")
        evs += bash(
            "m2",
            "g2",
            "git -c user.name=x -c user.email=y commit -m x",
            "1 file changed",
        )
        self.assertEqual(len(a14(evs)), 1)

    def test_A14_dash_C_push_of_a_feature_branch_does_not_fire(self):
        # "main" sits in the -C path, before the subcommand.
        evs = bash("m1", "g1", "git -C /p/proj/main push origin feat", "ok")
        self.assertEqual(a14(evs), [])

    def test_A14_dash_C_checkout_main_then_commit_fires(self):
        evs = bash(
            "m1", "g1", "git -C /p/proj checkout main", "Your branch is up to date."
        )
        evs += bash("m2", "g2", "git -C /p/proj commit -m x", "1 file changed")
        self.assertEqual(len(a14(evs)), 1)

    def test_A14_dash_C_worktree_add_feature_branch_does_not_fire(self):
        # The repository's own convention: add a feature worktree from .bare.
        evs = bash("m1", "g1", "git status", "On branch main")
        evs += bash(
            "m2",
            "g2",
            "git -C .bare worktree add ../feat -b feat origin/main",
            "Preparing worktree (new branch 'feat')",
        )
        evs += bash("m3", "g3", "git commit -m x", "1 file changed")
        self.assertEqual(a14(evs), [])

    def test_A14_worktree_add_with_dash_b_after_the_path_does_not_fire(self):
        evs = bash("m1", "g1", "git status", "On branch main")
        evs += bash(
            "m2",
            "g2",
            "git worktree add ../feat -b feat origin/main",
            "Preparing worktree (new branch 'feat')",
        )
        evs += bash("m3", "g3", "git commit -m x", "1 file changed")
        self.assertEqual(a14(evs), [])

    def test_A14_dash_C_worktree_add_existing_branch_does_not_fire(self):
        evs = bash("m1", "g1", "git status", "On branch main")
        evs += bash(
            "m2", "g2", "git -C .bare worktree add ../feat feat", "Preparing worktree"
        )
        evs += bash("m3", "g3", "git commit -m x", "1 file changed")
        self.assertEqual(a14(evs), [])


# --- A-F6: `git checkout <ref> -- <path>` restores a file, it does not switch ----


class TestCheckoutPathIsNotASwitch(unittest.TestCase):
    # a14b.jsonl
    A14B_REPRODUCER: ClassVar[list[dict]] = [
        user("commit the fix"),
        *bash("m0", "h0", "git checkout -b feat", "Switched to a new branch 'feat'"),
        *bash(
            "m1", "h1", "git checkout main -- src/app.py", "Updated 1 path from 1a2b3c4"
        ),
        *bash(
            "m2",
            "h2",
            "git commit -m 'fix: restore app.py'",
            "[feat 5d6e7f8] fix: restore app.py",
        ),
    ]

    def test_A14_path_restore_from_main_then_commit_does_not_fire(self):
        self.assertEqual(a14(self.A14B_REPRODUCER), [])

    def test_A14_path_restore_without_branch_in_commit_output_does_not_fire(self):
        # Same as the reproducer, but the commit output names no branch, so only
        # the `--` rule can keep the tracked branch on feat.
        evs = bash(
            "m0", "h0", "git checkout -b feat", "Switched to a new branch 'feat'"
        )
        evs += bash("m1", "h1", "git checkout main -- src/app.py", "Updated 1 path")
        evs += bash("m2", "h2", "git commit -m x", "1 file changed")
        self.assertEqual(a14(evs), [])

    def test_A14_path_restore_on_main_keeps_main(self):
        # The mirror: `git checkout -- f` while on main must not read as a
        # switch to a branch called `f`, which silenced the later commit.
        evs = bash("m0", "h0", "git status", "On branch main")
        evs += bash("m1", "h1", "git checkout -- src/app.py", "Updated 1 path")
        evs += bash("m2", "h2", "git commit -m x", "1 file changed")
        self.assertEqual(len(a14(evs)), 1)

    def test_A14_restore_then_real_switch_in_one_command(self):
        evs = bash(
            "m0", "h0", "git checkout -b feat", "Switched to a new branch 'feat'"
        )
        evs += bash("m1", "h1", "git checkout main -- a.py && git checkout main", "")
        evs += bash("m2", "h2", "git commit -m x", "1 file changed")
        self.assertEqual(len(a14(evs)), 1)

    def test_A14_commit_output_naming_main_fires_without_prior_tracking(self):
        evs = bash("m0", "h0", "git commit -m x", "[main 1a2b3c4] x\n 1 file changed")
        self.assertEqual(len(a14(evs)), 1)

    def test_A14_root_commit_output_naming_main_fires(self):
        evs = bash("m0", "h0", "git commit -m x", "[main (root-commit) 1a2b3c4] x")
        self.assertEqual(len(a14(evs)), 1)

    def test_A14_detached_head_commit_does_not_fire(self):
        evs = bash("m0", "h0", "git status", "On branch main")
        evs += bash("m1", "h1", "git commit -m x", "[detached HEAD 1a2b3c4] x")
        self.assertEqual(a14(evs), [])


# --- A-F11: paging through a file is not re-reading it ----------------------------


def read(msg_id, tool_id, path, **rng):
    return call(msg_id, tool_id, "Read", {"file_path": path, **rng}, "...")


def a12(evs):
    return detect.signal_reread_same_file(_uses(evs))


class TestPagedReads(unittest.TestCase):
    # a12.jsonl
    A12_REPRODUCER: ClassVar[list[dict]] = [
        user("review big.py"),
        *read("m0", "r0", "/r/big.py", offset=1, limit=700),
        *read("m1", "r1", "/r/big.py", offset=700, limit=750),
        *read("m2", "r2", "/r/big.py", offset=1450, limit=740),
    ]

    def test_A12_consecutive_ranges_are_not_a_reread(self):
        self.assertEqual(a12(self.A12_REPRODUCER), [])

    def test_A12_default_read_then_next_page_is_not_a_reread(self):
        # Read defaults to 2000 lines; the next page starts at the boundary.
        evs = read("m0", "r0", "/f") + read("m1", "r1", "/f", offset=2000)
        self.assertEqual(a12(evs), [])

    def test_A12_overlapping_ranges_fire(self):
        evs = read("m0", "r0", "/f", offset=1, limit=700)
        evs += read("m1", "r1", "/f", offset=600, limit=200)
        self.assertEqual([f["turns"] for f in a12(evs)], [[0, 2]])

    def test_A12_whole_file_after_a_range_fires(self):
        evs = read("m0", "r0", "/f", offset=1, limit=700) + read("m1", "r1", "/f")
        self.assertEqual(len(a12(evs)), 1)

    def test_A12_same_whole_file_twice_fires(self):
        evs = read("m0", "r0", "/f") + read("m1", "r1", "/f")
        self.assertEqual(len(a12(evs)), 1)

    def test_A12_overlap_with_an_earlier_non_adjacent_read_fires(self):
        evs = read("m0", "r0", "/f", offset=1, limit=100)
        evs += read("m1", "r1", "/f", offset=500, limit=100)
        evs += read("m2", "r2", "/f", offset=50, limit=10)
        self.assertEqual(len(a12(evs)), 1)

    def test_A12_edit_between_overlapping_reads_does_not_fire(self):
        evs = read("m0", "r0", "/f", offset=1, limit=700)
        evs += call("m1", "e1", "Edit", {"file_path": "/f"})
        evs += read("m2", "r2", "/f", offset=600, limit=200)
        self.assertEqual(a12(evs), [])


# --- A-F12: malformed lines must not crash the run ---------------------------------


class TestMalformedTranscriptLines(unittest.TestCase):
    HI = '{"type": "user", "message": {"role": "user", "content": "hi"}}'
    CASES: ClassVar[dict[str, list[str]]] = {
        "bad_null_msg": [HI, '{"type":"user","message":null}'],
        "bad_nondict": [HI, "[1,2]"],
        "bad_toolu_noid": [
            HI,
            '{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}',
        ],
        "bad_input_null": [
            HI,
            '{"type": "assistant", "message": {"id": "m", "role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "Bash", "input": null}]}}',
            '{"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok", "is_error": false}]}}',
        ],
    }

    def test_each_malformed_shape_exits_cleanly(self):
        for name, lines in self.CASES.items():
            with self.subTest(name):
                proc = _run_cli(lines)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)
                json.loads(proc.stdout)

    def test_load_jsonl_keeps_only_objects(self):
        path = _write(self.CASES["bad_nondict"] + ['"a string"', "3"])
        try:
            events = detect.load_jsonl(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(events), 1)
        self.assertTrue(all(isinstance(e, dict) for e in events))


# --- A-F13: --help names every signal the default run executes --------------------


class TestDocstringNamesEverySignal(unittest.TestCase):
    def test_every_signal_func_is_listed_in_the_module_docstring(self):
        doc = detect.__doc__ or ""
        missing = [
            sid
            for sid in detect.SIGNAL_FUNCS
            if not re.search(rf"^\s+{sid}\s", doc, re.MULTILINE)
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
