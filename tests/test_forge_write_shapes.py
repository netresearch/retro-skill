#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Forge writes that kept `complete` false although their target is known (#188).

Each case is a tool call copied byte for byte from session e72080f1
(`fixtures/review-findings/forge-write-shapes-188.json`, 2026-10-18). Before
#188 every one of them was listed in `unresolved_forge_commands`; 96 of the
213 such calls in that session named their target in their own words or
output. Review-thread writes named by a forge id are not covered here: they
stay resolved online by collect-review-findings.py's thread lookup.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "retro" / "scripts"
FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "review-findings"
    / "forge-write-shapes-188.json"
)


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dss = _load("derive_session_scope", "derive-session-scope.py")
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))
TMP = tempfile.TemporaryDirectory()


def _transcript(*pairs: tuple[str, str, bool]) -> Path:
    lines = [{"timestamp": "2026-10-18T09:00:00.000Z", "message": {"content": "start"}}]
    for i, (command, result, error) in enumerate(pairs):
        lines.append(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"t{i}",
                            "name": "Bash",
                            "input": {"command": command},
                        }
                    ]
                },
            }
        )
        lines.append(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"t{i}",
                            "content": result,
                            "is_error": error,
                        }
                    ]
                },
            }
        )
    path = Path(TMP.name) / f"t{len(list(Path(TMP.name).iterdir()))}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def _scan(*names: str) -> dict:
    pairs = [
        (CASES[n]["command"], CASES[n]["result"], CASES[n]["is_error"]) for n in names
    ]
    data = dss.collect_artefacts(_transcript(*pairs))
    return {
        "origins": {
            a["url"]: a["origin"]
            for a in data["artefacts"]
            if a["origin"] != "mentioned"
        },
        "unresolved": data["unresolved_forge_commands"],
        "pending": data["review_thread_writes"],
    }


def _case(name: str, command: str | None = None, result: str | None = None) -> dict:
    """A recorded case, or a variant of it with one field replaced."""
    case = CASES[name]
    pairs = [
        (
            case["command"] if command is None else command,
            case["result"] if result is None else result,
            case["is_error"],
        )
    ]
    data = dss.collect_artefacts(_transcript(*pairs))
    return {
        "origins": {
            a["url"]: a["origin"]
            for a in data["artefacts"]
            if a["origin"] != "mentioned"
        },
        "unresolved": data["unresolved_forge_commands"],
        "pending": data["review_thread_writes"],
    }


GH = "https://github.com/netresearch"


class WrapperShapesTest(unittest.TestCase):
    """git-workflow's `pr-merge.sh`."""

    def test_a_reader_given_the_script_does_not_run_it(self):
        # `grep … pr-merge.sh | head -30`: 22 such calls in the session.
        self.assertEqual(
            _scan("reader"), {"origins": {}, "unresolved": [], "pending": []}
        )

    def test_a_mention_the_words_do_not_place_still_counts(self):
        # Neither a run nor a reader: `xargs` may run it.
        scan = _case("reader", command="ls | xargs pr-merge.sh -R o/r", result="")
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_its_help_writes_nothing(self):
        self.assertEqual(
            _scan("help"), {"origins": {}, "unresolved": [], "pending": []}
        )

    def test_a_report_in_a_file_is_named_by_its_literal_target(self):
        # `pr-merge.sh -R o/r N > merge.txt`: every write it makes goes to o/r#N.
        scan = _scan("report_in_file")
        self.assertEqual(scan["origins"], {f"{GH}/t3x-nr-saml-auth/pull/120": "acted"})
        self.assertEqual(scan["unresolved"], [])

    def test_a_target_from_a_loop_variable_stays_unresolved(self):
        scan = _scan("loop_variable_target")
        self.assertEqual(scan["origins"], {})
        self.assertEqual(
            scan["unresolved"],
            [dss.squeeze(CASES["loop_variable_target"]["command"], 200)],
        )

    def test_an_echoed_report_of_a_loop_variable_target_stays_unresolved(self):
        # `echo "$1 exit=$? $(head -c 200 merge-$1.txt)"`: the echoed line
        # names a PR, but any text can quote such a line (review round 1).
        scan = _scan("echoed_report")
        self.assertEqual(scan["origins"], {})
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_report_naming_another_pr_does_not_replace_the_literal_target(self):
        for command, printed in (
            (
                "pr-merge.sh -R o/r 7 > m.txt 2>&1; cat notes.md",
                "see pr-merge: o/r#5 merged (--merge)",
            ),
            (
                "pr-merge.sh -R o/r 5; pr-merge.sh -R o/r 7 > m.txt",
                "pr-merge: o/r#5 merged",
            ),
        ):
            with self.subTest(command=command):
                scan = _case("reader", command=command, result=printed)
                self.assertIn("https://github.com/o/r/pull/7", scan["origins"])
                self.assertEqual(scan["unresolved"], [])

    def test_a_literal_target_its_own_report_shuts_wrote_nothing(self):
        scan = _case(
            "reader",
            command="pr-merge.sh -R o/r 7 2>&1 | tail -1",
            result="pr-merge: not merging o/r#7 — request-review: no review",
        )
        self.assertEqual(scan, {"origins": {}, "unresolved": [], "pending": []})

    def test_an_attestation_before_not_merging_is_a_write(self):
        # Verbatim from the session: the attestation was posted, the merge not.
        command = "/home/cybot/.claude/skills/git-workflow/scripts/pr-merge.sh --self-reviewed -R netresearch/timalytics 32; echo EXIT $?"
        printed = (
            "pr-merge: posted Self-review attestation for 82e500c1515e on netresearch/timalytics#32\n"
            "pr-merge: not merging netresearch/timalytics#32 — wait: UNSTABLE while 5 non-required check(s) have not finished (1 running, 4 queued) — nothing has failed\n"
            "EXIT 1"
        )
        scan = _case("reader", command=command, result=printed)
        self.assertEqual(scan["origins"], {f"{GH}/timalytics/pull/32": "acted"})
        self.assertEqual(scan["unresolved"], [])

    def test_a_shut_line_in_other_text_does_not_cancel_a_redirected_run(self):
        for command, printed in (
            (
                "cat notes.md; pr-merge.sh -R o/r 5 > m.txt 2>&1",
                "earlier: pr-merge: not merging o/r#5 — no review",
            ),
            (
                "pr-merge.sh -R o/r 5; pr-merge.sh -R o/r 5 --self-reviewed > m.txt",
                "pr-merge: not merging o/r#5 — request-review: no review",
            ),
            (
                # A line-start quote from a file, the run's own report elsewhere.
                "cat notes.md; pr-merge.sh -R o/r 5 > m.txt 2>&1",
                "pr-merge: not merging o/r#5 — no review",
            ),
        ):
            with self.subTest(command=command):
                scan = _case("reader", command=command, result=printed)
                self.assertEqual(
                    scan["origins"], {"https://github.com/o/r/pull/5": "acted"}
                )

    def test_the_last_number_is_the_pr(self):
        # pr-merge.sh keeps the last positional argument.
        scan = _case("reader", command="pr-merge.sh -R o/r 5 6 > m.txt", result="")
        self.assertEqual(scan["origins"], {"https://github.com/o/r/pull/6": "acted"})

    def test_a_last_positional_that_is_no_number_names_no_target(self):
        # pr-merge.sh takes its last positional argument as the PR.
        for command in (
            "pr-merge.sh -R o/r 5 https://github.com/o/r/pull/7 > m.txt 2>&1",
            "pr-merge.sh -R o/r 5 feature-x > m.txt 2>&1",
        ):
            with self.subTest(command=command):
                scan = _case("reader", command=command, result="")
                self.assertEqual(scan["origins"], {})
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_refusal_on_standard_error_shows_beside_a_stdout_redirect(self):
        scan = _case(
            "reader",
            command="pr-merge.sh -R o/r 5 > /dev/null",
            result="pr-merge: not merging o/r#5 — request-review: no review",
        )
        self.assertEqual(scan, {"origins": {}, "unresolved": [], "pending": []})

    def test_redirects_apply_left_to_right(self):
        # `2>&1 > m.txt`: standard error still reaches the transcript.
        scan = _case(
            "reader",
            command="pr-merge.sh -R o/r 5 2>&1 > m.txt",
            result="pr-merge: not merging o/r#5 — request-review: no review",
        )
        self.assertEqual(scan, {"origins": {}, "unresolved": [], "pending": []})

    def test_an_argument_the_script_rejects_names_no_target(self):
        # pr-merge.sh knows `-R`/`--repo <value>` and four flags; any other
        # dash word ends it in `unknown flag` before it writes.
        for command, printed in (
            ("pr-merge.sh --repo=o/r 5 > m.txt 2>&1", ""),
            ("pr-merge.sh -R o/r -- 5 > m.txt 2>&1", ""),
            (
                "pr-merge.sh -R o/r 5 --merge",
                "Exit code 2\npr-merge: unknown flag: --merge",
            ),
        ):
            with self.subTest(command=command):
                scan = _case("reader", command=command, result=printed)
                self.assertEqual(scan["origins"], {})
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_report_line_naming_no_pr_is_a_stop(self):
        # `die` prints `pr-merge: <message>` without `repo#N`.
        for printed in (
            "Exit code 2\npr-merge: --self-reviewed refused: the attestation must come from the PR author (a); gh is authenticated as b",
            "Exit code 2\npr-merge: pr-status.sh failed",
        ):
            with self.subTest(printed=printed[:40]):
                scan = _case(
                    "reader",
                    command="pr-merge.sh -R o/r 5 --self-reviewed",
                    result=printed,
                )
                self.assertEqual(scan["origins"], {})
                self.assertEqual(len(scan["unresolved"]), 1)
        # A stop after the attestation: the attestation line still counts.
        scan = _case(
            "reader",
            command="pr-merge.sh -R o/r 5 --self-reviewed",
            result="pr-merge: posted Self-review attestation for abc on o/r#5\n"
            "pr-merge: pr-status.sh failed",
        )
        self.assertEqual(scan["origins"], {"https://github.com/o/r/pull/5": "acted"})

    def test_a_reader_that_writes_or_runs_may_run_it(self):
        for command in (
            "> /tmp/m.sh cat pr-merge.sh; bash /tmp/m.sh -R o/r 5",
            "sed -n 'w /tmp/m.sh' pr-merge.sh; bash /tmp/m.sh -R o/r 5",
            "git show --output=/tmp/m.sh HEAD:pr-merge.sh; bash /tmp/m.sh -R o/r 5",
            """awk 'NR==1{system("bash " FILENAME " -R o/r 5")}' pr-merge.sh""",
        ):
            with self.subTest(command=command):
                scan = _case("reader", command=command, result="")
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_redirect_before_the_run_hides_its_report_too(self):
        # A stop line from `notes.md` does not cancel the run, wherever its
        # own redirect stands.
        scan = _case(
            "reader",
            command="cat notes.md; >m.txt 2>&1 pr-merge.sh -R o/r 5",
            result="pr-merge: not merging o/r#5 — x: y",
        )
        self.assertEqual(scan["origins"], {"https://github.com/o/r/pull/5": "acted"})

    def test_a_reader_piped_into_a_shell_may_run_it(self):
        for command in (
            "cat pr-merge.sh | bash -s -- -R o/r 5",
            "sed -n 1,400p pr-merge.sh | bash -s -- -R o/r 5",
            "{ cat pr-merge.sh; } | bash -s -- -R o/r 5",
            "( cat pr-merge.sh ) | bash -s -- -R o/r 5",
            "bash <(cat pr-merge.sh) -R o/r 5",
            'eval "$(cat pr-merge.sh)"',
            "cat pr-merge.sh > /tmp/m.sh; bash /tmp/m.sh -R o/r 5",
        ):
            with self.subTest(command=command):
                scan = _case("reader", command=command, result="")
                self.assertEqual(len(scan["unresolved"]), 1)


class SubcommandShapesTest(unittest.TestCase):
    def test_a_numbered_edit_after_a_closed_heredoc(self):
        # `python3 - <<PY … PY` then `gh pr edit 89 -R … >/dev/null`: 48 calls.
        scan = _scan("closed_heredoc")
        self.assertEqual(scan["origins"], {f"{GH}/typo3-ddev-skill/pull/89": "acted"})
        self.assertEqual(scan["unresolved"], [])

    def test_a_numbered_edit_inside_an_unclosed_heredoc_is_not_attributed(self):
        # Without its `PY` line the heredoc runs to the end: the edit is text
        # fed to python, not a command, and never a silent success.
        command = CASES["closed_heredoc"]["command"].replace("\nPY\n", "\n", 1)
        self.assertNotEqual(command, CASES["closed_heredoc"]["command"])
        self.assertEqual(_case("closed_heredoc", command=command)["origins"], {})

    def test_a_numbered_edit_the_parser_cannot_read_whole_stays_unresolved(self):
        # An unclosed quoted delimiter is an ERROR node: the extent is unknown.
        command = "python3 - <<'PY'\nprint(1)\ngh pr edit 89 -R o/r --body-file b.md"
        scan = _case("closed_heredoc", command=command, result="")
        self.assertEqual(scan["origins"], {})
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_heredoc_bash_does_not_close_hides_the_edit(self):
        # tree-sitter-bash ends a heredoc at `EOF ` or `  EOF`; bash reads
        # on to the end and the edit is heredoc text (review round 1).
        for end in ("EOF ", "  EOF"):
            command = (
                f"cat > /tmp/b.md <<'EOF'\nbody\n{end}\n"
                "gh pr edit 89 -R o/r --body-file /tmp/b.md"
            )
            with self.subTest(end=end):
                scan = _case("closed_heredoc", command=command, result="")
                self.assertEqual(scan["origins"], {})
                self.assertEqual(len(scan["unresolved"]), 1)
        # `<<-` strips leading tabs only: a tab-indented end closes it.
        command = (
            "cat > /tmp/b.md <<-EOF\n\tbody\n\tEOF\n"
            "gh pr edit 89 -R o/r --body-file /tmp/b.md"
        )
        scan = _case("closed_heredoc", command=command, result="")
        self.assertEqual(scan["origins"], {"https://github.com/o/r/pull/89": "acted"})

    def test_a_heredoc_program_that_carries_a_write_stays_unresolved(self):
        command = (
            "python3 - <<'PY'\nimport subprocess\n"
            "subprocess.run(['gh', 'pr', 'comment', '7', '-R', 'o/r', '-b', 'x'])\nPY\n"
            "gh pr edit 89 -R netresearch/typo3-ddev-skill --body-file b.md >/dev/null && echo ok"
        )
        scan = _case("closed_heredoc", command=command, result="ok")
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_numbered_write_run_in_the_background(self):
        # Its output is in a task file; its words name the PR.
        scan = _scan("background_numbered")
        self.assertEqual(scan["origins"], {f"{GH}/nr-landingpage/pull/84": "acted"})
        self.assertEqual(scan["unresolved"], [])


if __name__ == "__main__":
    unittest.main()
