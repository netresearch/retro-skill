"""Smoke tests for scripts/detect-mechanical.py.

Builds tiny synthetic JSONL transcripts and asserts the detector fires the
expected signal. Not exhaustive — one synthetic case per implemented signal.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def load_detect_module():
    """Import scripts/detect-mechanical.py despite its hyphenated filename."""
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "scripts" / "detect-mechanical.py"
    spec = importlib.util.spec_from_file_location("detect_mechanical", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect = load_detect_module()


def write_jsonl(events: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for ev in events:
        tmp.write(json.dumps(ev) + "\n")
    tmp.close()
    return Path(tmp.name)


def user_msg(text: str) -> dict:
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def tool_use_pair(
    tool_id: str, name: str, input_: dict, result_text: str, is_error: bool = False
) -> list[dict]:
    return [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": tool_id, "name": name, "input": input_}
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                ]
            },
        },
    ]


class TestSchichtA(unittest.TestCase):
    def assert_signal(self, events: list[dict], expected_signal: str):
        signals = self._run_all(events)
        self.assertIn(
            expected_signal, signals, f"expected {expected_signal} in {signals}"
        )

    def assert_not_signal(self, events: list[dict], unexpected_signal: str):
        signals = self._run_all(events)
        self.assertNotIn(
            unexpected_signal, signals, f"unexpected {unexpected_signal} in {signals}"
        )

    def _run_all(self, events: list[dict]) -> set:
        path = write_jsonl(events)
        try:
            events_loaded = detect.load_jsonl(path)
            user_texts = detect.extract_user_texts(events_loaded)
            assistant_texts = detect.extract_assistant_texts(events_loaded)
            tool_uses = detect.extract_tool_uses(events_loaded)
            findings = []
            for sid, func in detect.SIGNAL_FUNCS.items():
                if func in (
                    detect.signal_user_corrections,
                    detect.signal_prompt_repetition,
                    detect.signal_prompt_sequence_repetition,
                ):
                    findings.extend(func(user_texts))
                elif func is detect.signal_skill_reminder_vs_invoke:
                    findings.extend(func(events_loaded))
                elif func is detect.signal_tool_count_vs_task:
                    findings.extend(func(tool_uses, user_texts))
                elif func is detect.signal_skipped_verification:
                    findings.extend(func(assistant_texts, tool_uses))
                else:
                    findings.extend(func(tool_uses))
            return {f["signal"] for f in findings}
        finally:
            path.unlink(missing_ok=True)

    def test_A1_tool_error(self):
        evs = tool_use_pair(
            "u1", "Bash", {"command": "exit 1"}, "Exit code 1\nerror", is_error=True
        )
        self.assert_signal(evs, "A1")

    def test_A1_benign_error_word_does_not_fire(self):
        # Success output containing the word "error" must not be flagged.
        for txt in (
            "0 errors, all checks passed",
            "No errors found.",
            "lint: error-free",
            "Good signature from key",
        ):
            evs = tool_use_pair(
                "u1", "Bash", {"command": "make lint"}, txt, is_error=False
            )
            self.assert_not_signal(evs, "A1")

    def test_A1_real_error_text_fires_without_flag(self):
        # A genuine error marker fires even when is_error is not set.
        evs = tool_use_pair(
            "u1",
            "Bash",
            {"command": "git status"},
            "fatal: not a git repository",
            is_error=False,
        )
        self.assert_signal(evs, "A1")

    def test_A1_code_grep_mentioning_error_does_not_fire(self):
        # Grepping code that mentions error handling is not a tool error.
        evs = tool_use_pair(
            "u1",
            "Grep",
            {"pattern": "Error"},
            "src/Handler.php: class ErrorHandler {",
            is_error=False,
        )
        self.assert_not_signal(evs, "A1")

    def test_A14_commit_after_checkout_main_fires(self):
        evs = tool_use_pair(
            "c", "Bash", {"command": "git checkout main"}, "Switched to branch 'main'"
        )
        evs += tool_use_pair(
            "u1", "Bash", {"command": "git commit -m wip"}, "1 file changed"
        )
        self.assert_signal(evs, "A14")

    def test_A14_worktree_feature_branch_does_not_fire(self):
        # The user's worktree workflow: each worktree is already a feature branch.
        evs = tool_use_pair(
            "w",
            "Bash",
            {"command": "git worktree add ../feat feat"},
            "Preparing worktree",
        )
        evs += tool_use_pair(
            "u1", "Bash", {"command": "git commit -m wip"}, "1 file changed"
        )
        self.assert_not_signal(evs, "A14")

    def test_A14_main_in_commit_message_does_not_fire(self):
        # "main" appearing in the commit message must not trip A14.
        evs = tool_use_pair(
            "u1",
            "Bash",
            {"command": 'git commit -m "fix main menu parser"'},
            "1 file changed",
        )
        self.assert_not_signal(evs, "A14")

    def test_A2_retry_cluster(self):
        evs = []
        for i in range(3):
            evs.extend(tool_use_pair(f"u{i}", "Bash", {"command": "echo hi"}, "hi"))
        self.assert_signal(evs, "A2")

    def test_A3_verbose_output(self):
        big = "x" * 10000
        evs = tool_use_pair("u1", "Bash", {"command": "cat huge"}, big)
        self.assert_signal(evs, "A3")

    def test_A6_user_correction(self):
        evs = [user_msg("no, that's wrong")]
        self.assert_signal(evs, "A6")

    def test_A7_prompt_repetition(self):
        evs = [
            user_msg("please run the tests now"),
            user_msg("please run the tests now"),
        ]
        self.assert_signal(evs, "A7")

    def test_A16_outdated_tool(self):
        evs = tool_use_pair(
            "u1", "Bash", {"command": "npm i"}, "npm WARN deprecated: use yarn instead"
        )
        self.assert_signal(evs, "A16")

    def test_A17_upstream_failure(self):
        evs = tool_use_pair(
            "u1",
            "Bash",
            {"command": "git push origin main"},
            "remote: rejected",
            is_error=True,
        )
        self.assert_signal(evs, "A17")

    def test_A4_tool_call_inefficiency(self):
        # 25 tool calls vs 2 user messages → ratio 12.5, well over threshold
        evs = [user_msg("do a lot of work"), user_msg("keep going")]
        for i in range(25):
            evs.extend(tool_use_pair(f"u{i}", "Bash", {"command": f"echo {i}"}, "ok"))
        self.assert_signal(evs, "A4")

    def test_A4_small_session_does_not_fire(self):
        # Below A4_MIN_TOOL_USES — must not fire even with extreme ratio.
        evs = [user_msg("hi")]
        for i in range(5):
            evs.extend(tool_use_pair(f"u{i}", "Bash", {"command": f"echo {i}"}, "ok"))
        self.assert_not_signal(evs, "A4")

    def test_A5_three_separate_reads_fire(self):
        # Each Read in its own assistant message → serial; should fire A5.
        evs = []
        for i, path in enumerate(["/a.py", "/b.py", "/c.py", "/d.py"]):
            evs.extend(tool_use_pair(f"u{i}", "Read", {"file_path": path}, "ok"))
        self.assert_signal(evs, "A5")

    def test_A5_parallel_batch_does_not_fire(self):
        # All three tool_use blocks live in ONE assistant message → parallel; must not fire.
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "p1",
                            "name": "Read",
                            "input": {"file_path": "/a.py"},
                        },
                        {
                            "type": "tool_use",
                            "id": "p2",
                            "name": "Read",
                            "input": {"file_path": "/b.py"},
                        },
                        {
                            "type": "tool_use",
                            "id": "p3",
                            "name": "Read",
                            "input": {"file_path": "/c.py"},
                        },
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "p1",
                            "content": "ok",
                            "is_error": False,
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "p2",
                            "content": "ok",
                            "is_error": False,
                        },
                        {
                            "type": "tool_result",
                            "tool_use_id": "p3",
                            "content": "ok",
                            "is_error": False,
                        },
                    ]
                },
            },
        ]
        self.assert_not_signal(events, "A5")

    def test_A11_grep_on_json(self):
        evs = tool_use_pair(
            "u1", "Bash", {"command": "grep version package.json"}, "..."
        )
        self.assert_signal(evs, "A11")

    def test_A11_grep_via_pipe_does_not_fire(self):
        # grep on stdin (piped) is fine — only a direct file argument is the misuse.
        evs = tool_use_pair(
            "u1", "Bash", {"command": "jq . package.json | grep version"}, "..."
        )
        self.assert_not_signal(evs, "A11")

    def test_A11_cat_instead_of_read(self):
        evs = tool_use_pair("u1", "Bash", {"command": "cat README.md"}, "...")
        self.assert_signal(evs, "A11")

    def test_A13_claim_without_verification(self):
        evs = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "All tests pass now, the bug is fixed.",
                        }
                    ]
                },
            },
        ]
        self.assert_signal(evs, "A13")

    def test_A13_claim_with_prior_test_run_does_not_fire(self):
        evs = tool_use_pair("u1", "Bash", {"command": "pytest tests/"}, "5 passed")
        evs.append(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "All tests pass now."}]
                },
            }
        )
        self.assert_not_signal(evs, "A13")

    def test_A18_permission_reapproval_spread(self):
        # Same `git status` 4× spread far apart → allowlist candidate.
        evs = []
        for i in range(4):
            evs.extend(
                tool_use_pair(f"u{i}", "Bash", {"command": "git status"}, "clean")
            )
            # Inject filler tool calls to spread occurrences apart.
            for j in range(15):
                evs.extend(
                    tool_use_pair(
                        f"f{i}_{j}", "Read", {"file_path": f"/x{i}{j}.py"}, "ok"
                    )
                )
        self.assert_signal(evs, "A18")

    def test_A18_burst_does_not_fire(self):
        # 3× back-to-back is a retry burst (A2), not a permission re-approval (A18).
        evs = []
        for i in range(3):
            evs.extend(
                tool_use_pair(f"u{i}", "Bash", {"command": "git status"}, "clean")
            )
        self.assert_not_signal(evs, "A18")

    def test_A18_repeated_read_does_not_fire(self):
        # A18 is restricted to Bash; Read is permission-scoped by tool name
        # and repeated invocations would be noise.
        evs = []
        for i in range(6):
            evs.extend(tool_use_pair(f"u{i}", "Read", {"file_path": f"/x{i}.py"}, "ok"))
            for j in range(15):
                evs.extend(
                    tool_use_pair(
                        f"f{i}_{j}", "Bash", {"command": f"echo {i}{j}"}, "ok"
                    )
                )
        self.assert_not_signal(evs, "A18")

    def test_A11_sed_with_pipes_in_program(self):
        # Quoted sed body containing | must tokenize correctly with shlex.
        evs = tool_use_pair(
            "u1", "Bash", {"command": "sed -i 's|foo|bar|g' config.yaml"}, ""
        )
        self.assert_signal(evs, "A11")

    def test_A11_grep_with_alternation_pattern(self):
        # `grep -E 'a|b' file.yaml` — alternation in the regex, structured file arg.
        evs = tool_use_pair(
            "u1", "Bash", {"command": "grep -E 'a|b' config.yaml"}, "ok"
        )
        self.assert_signal(evs, "A11")

    def test_A11_cat_piped_does_not_fire(self):
        # `cat file | wc -l` uses cat as a pipeline source; Read can't replace it.
        evs = tool_use_pair("u1", "Bash", {"command": "cat file.log | wc -l"}, "42")
        self.assert_not_signal(evs, "A11")

    def test_A4_multi_block_user_message_counts_as_one(self):
        # User event with two text blocks must not count as two messages.
        # 21 tool calls / 1 user event = 21.0 (fires); / 2 text blocks = 10.5 (also fires) —
        # so check the reported user_messages value rather than just the signal presence.
        events = [
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "text", "text": "first part"},
                        {"type": "text", "text": "second part"},
                    ]
                },
            }
        ]
        for k in range(21):
            events.extend(
                tool_use_pair(f"u{k}", "Bash", {"command": f"echo {k}"}, "ok")
            )
        path = write_jsonl(events)
        try:
            loaded = detect.load_jsonl(path)
            tool_uses = detect.extract_tool_uses(loaded)
            user_texts = detect.extract_user_texts(loaded)
            findings = detect.signal_tool_count_vs_task(tool_uses, user_texts)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["user_messages"], 1)
        finally:
            path.unlink(missing_ok=True)


class TestHelpers(unittest.TestCase):
    def test_extract_user_texts_handles_string_content(self):
        events = [{"type": "user", "message": {"content": "hello"}}]
        result = detect.extract_user_texts(events)
        self.assertEqual(result, [(0, "hello")])

    def test_extract_tool_uses_returns_5tuple_with_is_error(self):
        events = tool_use_pair("u1", "Read", {"file_path": "/x"}, "ok", is_error=False)
        result = detect.extract_tool_uses(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 5)
        i, name, inp, res, is_error = result[0]
        self.assertEqual(name, "Read")
        self.assertFalse(is_error)


if __name__ == "__main__":
    unittest.main()
