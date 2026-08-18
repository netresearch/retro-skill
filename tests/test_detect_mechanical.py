"""Smoke tests for skills/retro/scripts/detect-mechanical.py.

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
    """Import skills/retro/scripts/detect-mechanical.py despite its hyphenated filename."""
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "skills" / "retro" / "scripts" / "detect-mechanical.py"
    spec = importlib.util.spec_from_file_location("detect_mechanical", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect = load_detect_module()


def write_jsonl(events: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)  # noqa: SIM115 -- path returned for later use; caller unlinks
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

    def _run_all(self, events: list[dict], rules_text: str = "") -> set:
        path = write_jsonl(events)
        try:
            events_loaded = detect.load_jsonl(path)
            user_texts = detect.extract_user_texts(events_loaded)
            assistant_texts = detect.extract_assistant_texts(events_loaded)
            tool_uses = detect.extract_tool_uses(events_loaded)
            findings = []
            for func in detect.SIGNAL_FUNCS.values():
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
                elif func is detect.signal_rule_exists_but_violated:
                    # Schicht C: takes the accumulated findings plus the rules
                    # text, not tool_uses. Run last, like main() does.
                    continue
                else:
                    findings.extend(func(tool_uses))
            findings.extend(
                detect.signal_rule_exists_but_violated(findings, rules_text)
            )
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

    def test_A1_is_error_flag_trusted_despite_benign_text(self):
        # An explicit harness failure must fire even if output reads benign.
        evs = tool_use_pair(
            "u1", "Bash", {"command": "make check"}, "0 errors", is_error=True
        )
        self.assert_signal(evs, "A1")

    def test_A11_head_on_repo_file_fires(self):
        evs = tool_use_pair(
            "h", "Bash", {"command": "head -60 tests/smoke.sh"}, "#!/usr/bin/env bash"
        )
        self.assert_signal(evs, "A11")

    def test_A11_head_on_repo_file_before_semicolon_still_fires(self):
        # The misuse is the first statement; the call doing something else
        # afterwards must not hide it.
        evs = tool_use_pair(
            "h",
            "Bash",
            {"command": "head -60 tests/smoke.sh; echo done"},
            "#!/usr/bin/env bash",
        )
        self.assert_signal(evs, "A11")

    def test_A11_tail_on_background_task_output_does_not_fire(self):
        # Read addresses files in the project and has no last-N-lines mode;
        # polling a background task's output with tail is what the harness
        # gate explicitly permits, so flagging it reports the rule's own
        # allowance as friction — and feeds C6 with it.
        evs = tool_use_pair(
            "t",
            "Bash",
            {"command": "tail -20 /tmp/claude-1001/proj/tasks/abc123.output"},
            "CHECKS EXIT: 0",
        )
        self.assert_not_signal(evs, "A11")

    def test_A11_tail_on_log_then_other_command_does_not_fire(self):
        evs = tool_use_pair(
            "t",
            "Bash",
            {"command": "tail -3 /var/log/deploy.log; git status --porcelain"},
            "done",
        )
        self.assert_not_signal(evs, "A11")

    def test_A11_cat_into_a_pipe_does_not_fire(self):
        evs = tool_use_pair("c", "Bash", {"command": "cat config.txt | wc -l"}, "12")
        self.assert_not_signal(evs, "A11")

    def test_A11_two_reads_in_one_call_count_once(self):
        # One call is one habit; counting it twice inflates the C6 tally that
        # decides whether the prose rule has failed.
        evs = tool_use_pair(
            "h",
            "Bash",
            {"command": "head -5 a.txt; head -5 b.txt"},
            "…",
        )
        path = write_jsonl(evs)
        try:
            tool_uses = detect.extract_tool_uses(detect.load_jsonl(path))
            hits = [
                f
                for f in detect.signal_wrong_tool_choice(tool_uses)
                if f.get("name") == "cat_instead_of_read"
            ]
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(hits), 1, f"expected one finding, got {hits}")

    def test_A14_checkout_main_with_flag_fires(self):
        # Optional flags (e.g. -f) before the branch name must not hide main.
        evs = tool_use_pair(
            "c",
            "Bash",
            {"command": "git checkout -f main"},
            "Switched to branch 'main'",
        )
        evs += tool_use_pair(
            "u1", "Bash", {"command": "git commit -m wip"}, "1 file changed"
        )
        self.assert_signal(evs, "A14")

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

    def test_A14_already_on_main_fires(self):
        # `git checkout main` when already there prints "Already on 'main'".
        evs = tool_use_pair(
            "c", "Bash", {"command": "git checkout main"}, "Already on 'main'"
        )
        evs += tool_use_pair(
            "u1", "Bash", {"command": "git commit -m wip"}, "1 file changed"
        )
        self.assert_signal(evs, "A14")

    def test_A14_push_to_main_prefixed_branch_does_not_fire(self):
        # Pushing a branch that merely starts with "main" must not fire.
        evs = tool_use_pair(
            "u1", "Bash", {"command": "git push origin main-menu"}, "done"
        )
        self.assert_not_signal(evs, "A14")

    def test_A14_tag_push_on_main_does_not_fire(self):
        # Pushing a release tag while standing on main is not branch work.
        evs = tool_use_pair(
            "c", "Bash", {"command": "git checkout main"}, "Already on 'main'"
        )
        evs += tool_use_pair(
            "u1",
            "Bash",
            {"command": "git tag -s v1.2.3 -m v1.2.3 && git push origin v1.2.3"},
            "new tag",
        )
        self.assert_not_signal(evs, "A14")

    def test_A14_push_to_main_branch_fires(self):
        # Pushing to the main branch itself is still a violation.
        evs = tool_use_pair(
            "u1", "Bash", {"command": "git push origin HEAD:main"}, "done"
        )
        self.assert_signal(evs, "A14")

    def test_A14_push_then_chained_log_of_main_does_not_fire(self):
        # A feature-branch push chained with a read-only command that mentions
        # main (`git log origin/main..HEAD`) is not work on main. The match must
        # stay inside the `git push` invocation and not run past `|` or `&&`.
        evs = tool_use_pair(
            "c",
            "Bash",
            {"command": "git checkout -b feat/x"},
            "Switched to a new branch 'feat/x'",
        )
        evs += tool_use_pair(
            "u1",
            "Bash",
            {
                "command": "git push 2>&1 | tail -2 && git log --oneline origin/main..HEAD"
            },
            "branch 'feat/x' set up to track",
        )
        self.assert_not_signal(evs, "A14")

    def test_A14_push_to_main_chained_with_another_command_fires(self):
        # The separator guard must not swallow a real violation: main is inside
        # the push invocation here, before the `&&`.
        evs = tool_use_pair(
            "u1", "Bash", {"command": "git push origin main && echo done"}, "done"
        )
        self.assert_signal(evs, "A14")

    def test_A14_checkout_main_then_feature_branch_does_not_fire(self):
        # A block that switches to main then creates a feature branch ends on
        # the feature branch; the final switch wins, so a later commit is fine.
        evs = tool_use_pair(
            "c",
            "Bash",
            {"command": "git checkout main && git checkout -b feat/x"},
            "Switched to branch 'main'\nSwitched to a new branch 'feat/x'",
        )
        evs += tool_use_pair(
            "u1", "Bash", {"command": "git commit -m wip"}, "1 file changed"
        )
        self.assert_not_signal(evs, "A14")

    def test_A2_retry_cluster(self):
        # Same command shape, differing arguments — the "similar args" half the
        # catalog has always described.
        evs = []
        for i in range(3):
            evs.extend(
                tool_use_pair(
                    f"u{i}", "Bash", {"command": f"gh pr view {i} --json state"}, "{}"
                )
            )
        self.assert_signal(evs, "A2")

    def test_A2_distinct_commands_do_not_cluster(self):
        # Three unrelated shell calls are a session, not a retry cluster.
        # Grouping by tool name alone made this fire on almost every transcript.
        cmds = ["gh pr view 1", "git status", "docker ps"]
        evs = []
        for i, c in enumerate(cmds):
            evs.extend(tool_use_pair(f"u{i}", "Bash", {"command": c}, "ok"))
        self.assert_not_signal(evs, "A2")

    def test_A3_verbose_output(self):
        big = "x" * 10000
        evs = tool_use_pair("u1", "Bash", {"command": "cat huge"}, big)
        self.assert_signal(evs, "A3")

    def test_A6_user_correction(self):
        evs = [user_msg("no, that's wrong")]
        self.assert_signal(evs, "A6")

    def test_A6_german_line_start_opener(self):
        evs = [user_msg("Falsch, das gehört da nicht hin")]
        self.assert_signal(evs, "A6")

    def test_A6_german_midline_correction_phrase(self):
        # Mid-sentence correction the anchored EN openers would miss.
        evs = [user_msg("du hast da wieder die harten Umbrüche drin, raus damit")]
        self.assert_signal(evs, "A6")

    def test_A6_german_sei_genau(self):
        evs = [user_msg("bitte sei genau und nicht so schludrig")]
        self.assert_signal(evs, "A6")

    def test_A6_ordinary_german_prose_does_not_fire(self):
        # Benign request containing no correction marker must not trip A6.
        evs = [user_msg("Bitte den Cache leeren und die Seite neu bauen")]
        self.assert_not_signal(evs, "A6")

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

    def test_A14_git_words_in_data_are_not_a_git_operation(self):
        """`git push … main` written into a file is not a push to main."""
        evs = tool_use_pair(
            "u1",
            "Bash",
            {"command": "python3 -c \"s = 'git push origin main'\""},
            "ok",
        )
        self.assert_not_signal(evs, "A14")

    def test_A14_flags_before_dash_b_still_create_a_branch(self):
        """`git checkout -q -b feat` creates a branch just as `-b feat` does."""
        evs = tool_use_pair(
            "c",
            "Bash",
            {"command": "git checkout -q main && git checkout -q -b feat/x"},
            "Switched to a new branch 'feat/x'",
        )
        evs += tool_use_pair(
            "u1", "Bash", {"command": "git commit -m wip"}, "1 file changed"
        )
        self.assert_not_signal(evs, "A14")

    def test_A14_wrapped_git_still_counts(self):
        """`sudo git push origin main` is a push to main."""
        for cmd in ("sudo git push origin main", "env git push origin main"):
            evs = tool_use_pair("u1", "Bash", {"command": cmd}, "ok")
            self.assert_signal(evs, "A14")

    def test_A14_wrapper_flag_values_do_not_hide_git(self):
        """`sudo -u root git push origin main` is still a push to main."""
        for cmd in (
            "sudo -u root git push origin main",
            "env -u GIT_DIR git push origin main",
            "timeout -s KILL 60 git push origin main",
            "nice -n 10 git push origin main",
        ):
            evs = tool_use_pair("u1", "Bash", {"command": cmd}, "ok")
            self.assert_signal(evs, "A14")

    def test_A14_status_header_sets_the_branch(self):
        """`On branch main` is the commonest way the branch appears in output."""
        evs = tool_use_pair("s", "Bash", {"command": "git status"}, "On branch main")
        evs += tool_use_pair(
            "u1", "Bash", {"command": "git commit -m wip"}, "1 file changed"
        )
        self.assert_signal(evs, "A14")


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
        _i, name, _inp, _res, is_error = result[0]
        self.assertEqual(name, "Read")
        self.assertFalse(is_error)


if __name__ == "__main__":
    unittest.main()


class TestMechanizableWaste(unittest.TestCase):
    """A19/A20/C6 — the signals that route to a tool rather than a paragraph."""

    def _findings(self, events, sig, rules_text=""):
        path = write_jsonl(events)
        try:
            loaded = detect.load_jsonl(path)
            tool_uses = detect.extract_tool_uses(loaded)
            if sig == "A19":
                return detect.signal_repeated_probe(tool_uses)
            if sig == "A20":
                return detect.signal_wait_loop_inefficiency(tool_uses)
            base = detect.signal_wrong_tool_choice(tool_uses)
            return detect.signal_rule_exists_but_violated(base, rules_text)
        finally:
            path.unlink(missing_ok=True)

    def test_A19_repeated_remote_probe_fires(self):
        evs = []
        for i in range(9):
            evs.extend(
                tool_use_pair(f"u{i}", "Bash", {"command": f"gh pr view {i}"}, "{}")
            )
        out = self._findings(evs, "A19")
        shapes = {f["shape"]: f for f in out}
        self.assertIn("gh pr view", shapes)
        self.assertEqual(shapes["gh pr view"]["count"], 9)
        self.assertTrue(shapes["gh pr view"]["remote"])

    def test_A19_ignores_text_plumbing(self):
        evs = []
        for i in range(12):
            evs.extend(tool_use_pair(f"u{i}", "Bash", {"command": f"head -{i} f"}, ""))
        self.assertEqual(self._findings(evs, "A19"), [])

    def test_A19_ignores_heredoc_bodies(self):
        # Document lines inside a heredoc are not commands; counting them
        # produced shapes like "EOF".
        body = "cat > f <<'EOF'\ngh pr view 1\ngh pr view 2\nEOF"
        evs = []
        for i in range(9):
            evs.extend(tool_use_pair(f"u{i}", "Bash", {"command": body}, ""))
        shapes = {f["shape"] for f in self._findings(evs, "A19")}
        self.assertNotIn("EOF", shapes)
        self.assertNotIn("gh pr view", shapes)

    def test_A20_terminal_wait_is_flagged(self):
        cmd = (
            'until [ "$(gh pr checks 1 --json bucket '
            '--jq \'[.[]|select(.bucket=="pending")]|length\')" = "0" ]; '
            "do sleep 30; done"
        )
        out = self._findings(tool_use_pair("u", "Bash", {"command": cmd}, ""), "A20")
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["waits_for_everything"])

    def test_A20_plain_command_does_not_fire(self):
        evs = tool_use_pair("u", "Bash", {"command": "gh pr checks 1"}, "")
        self.assertEqual(self._findings(evs, "A20"), [])

    def test_C6_fires_only_when_a_matching_rule_exists(self):
        evs = []
        for i in range(4):
            evs.extend(
                tool_use_pair(
                    f"u{i}", "Bash", {"command": f"grep foo conf{i}.yaml"}, ""
                )
            )
        with_rule = self._findings(evs, "C6", "never grep on a structured file")
        self.assertTrue(any(f["violated_signal"] == "A11" for f in with_rule))
        self.assertEqual(self._findings(evs, "C6", "unrelated prose"), [])

    def test_A19_unwraps_wrapper_commands(self):
        # timeout/sudo/env/time must not become the shape — the wrapped
        # command is the probe. `timeout 300 gh api ...` counted as "timeout".
        import importlib

        del importlib  # keep linters quiet; module already loaded above
        for cmd, want in (
            ("timeout 300 gh api repos/x", "gh api"),
            ("sudo gh pr view 1", "gh pr view"),
            ("env FOO=1 gh pr view 2", "gh pr view"),
            ("nice -n 5 docker ps", "docker ps"),
        ):
            self.assertEqual(detect.command_shapes(cmd), [want], cmd)

    def test_remote_flag_scoped_to_network_git(self):
        self.assertTrue(detect.is_remote_shape("git push"))
        self.assertTrue(detect.is_remote_shape("git fetch"))
        self.assertFalse(detect.is_remote_shape("git status"))
        self.assertFalse(detect.is_remote_shape("git log"))
        self.assertTrue(detect.is_remote_shape("gh api"))

    def test_git_subcommand_depth_is_one(self):
        # `git push origin main` and `git push` are the same probe.
        self.assertEqual(detect.command_shapes("git push origin main"), ["git push"])
        self.assertEqual(detect.command_shapes("git push"), ["git push"])
        # gh nests two deep.
        self.assertEqual(detect.command_shapes("gh pr view 1"), ["gh pr view"])

    def test_quoted_separators_are_not_statement_boundaries(self):
        """A pipe inside a jq program is jq syntax, not a second command."""
        self.assertEqual(
            detect.command_shapes(
                "gh pr checks 329 --repo x/y --json bucket "
                """--jq '[.[]|select(.bucket=="pending")] | length'"""
            ),
            ["gh pr checks"],
        )
        self.assertEqual(
            detect.command_shapes(
                """gh api repos/x/y --jq '.s[] | select(.c|startswith("cov"))'"""
            ),
            ["gh api"],
        )

    def test_newlines_inside_an_inline_script_are_not_boundaries(self):
        """`python3 -c "..."` is one command, not one per line of the script."""
        self.assertEqual(
            detect.command_shapes('/usr/bin/python3 -c "\nimport yaml\nprint(1)\n"'),
            ["python3"],
        )

    def test_real_separators_still_split(self):
        self.assertEqual(
            detect.command_shapes("git status && git push"), ["git status", "git push"]
        )
        self.assertEqual(
            detect.command_shapes("gh run list | head -3"), ["gh run list", "head"]
        )
        self.assertEqual(
            detect.command_shapes("cat f.txt | jq -r '.a|.b'"), ["cat", "jq"]
        )

    def test_command_substitution_inside_double_quotes_still_counts(self):
        """`$(...)` and backticks do expand inside double quotes."""
        self.assertEqual(
            detect.command_shapes('echo "$(git rev-parse HEAD)"'), ["git rev-parse"]
        )
        self.assertEqual(detect.command_shapes('X="`git describe`"'), ["git describe"])

    def test_command_after_a_substitution_is_not_lost(self):
        """Closing `$( )` must return to the command that wrapped it."""
        self.assertEqual(
            detect.command_shapes('FOO="$(git rev-parse HEAD)" gh pr view 1'),
            ["git rev-parse", "gh pr view"],
        )
        self.assertEqual(
            detect.command_shapes("X=$(git describe) && gh pr create"),
            ["git describe", "gh pr create"],
        )
        self.assertEqual(
            detect.command_shapes('echo "$(git log -1)" | gh pr comment 1'),
            ["git log", "gh pr comment"],
        )
