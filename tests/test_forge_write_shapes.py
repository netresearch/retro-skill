#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Forge writes that kept `complete` false although their target is known (#188).

Each case is a tool call copied byte for byte from session e72080f1
(`fixtures/review-findings/forge-write-shapes-188.json`, 2026-10-18). Before
#188 every one of them was listed in `unresolved_forge_commands`: 109 of the
213 such calls in that session named their target in their own words or
output, and 67 named it by a forge id that collect-review-findings.py looks up.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


crf = _load("collect_review_findings", "collect-review-findings.py")
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

    def test_a_rate_limited_create_stays_unresolved(self):
        # Review round 4: gh prints `pull request update failed: … rate limit`
        # after it created the PR and failed to add labels or reviewers, so
        # the limit proves nothing about the create.
        for result in (
            CASES["create_rate_limited"]["result"],
            "Exit code 1\npull request update failed: GraphQL: API rate limit already exceeded for user ID 1.",
        ):
            with self.subTest(result=result[:40]):
                scan = _case("create_rate_limited", result=result)
                self.assertEqual(scan["origins"], {})
                self.assertEqual(
                    scan["unresolved"],
                    [dss.squeeze(CASES["create_rate_limited"]["command"], 200)],
                )

    def test_a_create_without_its_body_file_stays_unresolved(self):
        # Kept unresolved (review rounds 3-5): telling gh's own message from
        # one another program, a log or a replayed variable printed took a
        # guard per round, for one call in the session.
        scan = _scan("create_missing_body_file")
        self.assertEqual(scan["origins"], {})
        self.assertEqual(
            scan["unresolved"],
            [dss.squeeze(CASES["create_missing_body_file"]["command"], 200)],
        )


class ApiShapesTest(unittest.TestCase):
    def test_a_rest_create_whose_jq_prints_the_url_in_text_stays_unresolved(self):
        # Kept unresolved (review round 3): a `--jq` filter can print the
        # body, the author's URL or the API URL beside the created one, and
        # telling them apart means reading jq. These PRs are attributed by
        # other calls of the session.
        for name in (
            "rest_create_jq_text",
            "rest_create_jq_url_first",
            "rest_create_jq_object",
        ):
            with self.subTest(name=name):
                scan = _scan(name)
                self.assertEqual(scan["origins"], {})
                self.assertEqual(
                    scan["unresolved"], [dss.squeeze(CASES[name]["command"], 200)]
                )

    def test_a_graphql_document_from_elsewhere_may_be_a_mutation(self):
        for command in (
            'gh api graphql -f query="$(cat m.graphql)" -f id=PRRT_a',
            'Q=$(cat m.graphql); gh api graphql -f query="$Q" -f id=PRRT_a',
            'read -r Q < m.graphql; gh api graphql -f query="$Q"',
            "gh api graphql --input body.json",
        ):
            with self.subTest(command=command):
                scan = _case("query_beside_mutation", command=command, result="{}")
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_query_built_from_other_variables_may_be_a_mutation(self):
        # Shape from the session: `q='query{'; … q="$q r$i: …"; gh api graphql -f query="$q"`.
        command = (
            'q=\'query{\'; for r in a b; do q="$q $r: repository(owner:\\"o\\",name:\\"$r\\"){name}"; done;'
            ' q="$q}"\ngh api graphql -f query="$q" > repos.json'
        )
        scan = _case("query_beside_mutation", command=command, result="")
        # Review round 9: a value built from other variables is not text
        # the call shows; base read it as a query.
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_query_in_a_variable_holding_plain_text(self):
        # Review round 10: the plain-text branch, both ways.
        scan = _case(
            "query_beside_mutation",
            command="Q='query{viewer{login}}'; gh api graphql -f query=\"$Q\"",
            result='{"data":{"viewer":{"login":"x"}}}',
        )
        self.assertEqual(scan, {"origins": {}, "unresolved": [], "pending": []})
        scan = _case(
            "query_beside_mutation",
            command='Q=\'mutation{resolveReviewThread(input:{threadId:"PRRT_kwDOa"})'
            '{thread{isResolved}}}\'; gh api graphql -f query="$Q"',
            result="{}",
        )
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_second_query_field_is_read_too(self):
        for command in (
            (
                "S='x'; Q=$(cat m.graphql); gh api graphql -f subquery=\"$S\""
                ' -f query="$Q" -f id=PRRT_kwDOa'
            ),
            # gh sends the last `query`; the first one is plain text.
            (
                "S='x'; Q=$(cat m.graphql); gh api graphql -f query=\"$S\""
                ' -F query="$Q" -f id=PRRT_kwDOa'
            ),
        ):
            with self.subTest(command=command[30:60]):
                scan = _case("query_beside_mutation", command=command, result="{}")
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_graphql_query_beside_a_mutation_is_no_write(self):
        scan = _scan("query_beside_mutation")
        self.assertEqual(scan["unresolved"], [])
        (write,) = scan["pending"]
        self.assertEqual(write["thread_ids"], ["PRRT_kwDORYjMY86pzuzd"])
        self.assertTrue(write["only_review_threads"])


class PendingLookupTest(unittest.TestCase):
    """Writes the transcript names by a forge id: pending, not unresolved."""

    def _pending(self, name: str) -> dict:
        scan = _scan(name)
        self.assertEqual(scan["unresolved"], [])
        (write,) = scan["pending"]
        self.assertTrue(write["only_review_threads"])
        return write

    def test_thread_ids_passed_to_a_function(self):
        write = self._pending("thread_id_function")
        self.assertEqual(
            write["thread_ids"],
            ["PRRT_kwDOT80IaM6py9wL", "PRRT_kwDOT80IaM6py9wR", "PRRT_kwDOT80IaM6py9wW"],
        )

    def test_a_thread_id_in_a_named_variable_stays_unresolved(self):
        # Review round 15: which value a named variable holds when the write
        # runs depends on every command in the call (`printf -vt`, `read
        # "$v"`, `${t:=…}`), so a named variable is not traced at all.
        for name in ("thread_id_assignment", "thread_id_pair_loop"):
            with self.subTest(name=name):
                scan = _scan(name)
                self.assertEqual(scan["pending"], [])
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_for_list_of_thread_ids_stays_known(self):
        # The form the scope read before #188: a loop over literal ids.
        command = (
            "for t in PRRT_kwDOa PRRT_kwDOb; do gh api graphql -f query='mutation($t:ID!)"
            '{resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}\' -f t="$t"; done'
        )
        scan = _case("thread_id_assignment", command=command, result="true\ntrue")
        self.assertEqual(scan["unresolved"], [])
        (write,) = scan["pending"]
        self.assertEqual(write["thread_ids"], ["PRRT_kwDOa", "PRRT_kwDOb"])

    def test_a_thread_id_read_at_run_time_stays_unresolved(self):
        # A later value from a command replaces the literal one.
        command = CASES["thread_id_assignment"]["command"].replace(
            "t=PRRT_kwDOSPv4I86p3NCI;",
            "t=PRRT_kwDOSPv4I86p3NCI; t=$(jq -r .id thread.json);",
            1,
        )
        self.assertNotEqual(command, CASES["thread_id_assignment"]["command"])
        scan = _case("thread_id_assignment", command=command)
        self.assertEqual(scan["pending"], [])
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_variable_id_beside_a_literal_one_leaves_the_call_unresolved(self):
        command = (
            't=PRRT_kwDOb; gh api graphql -f query="mutation{a:resolveReviewThread('
            'input:{threadId:\\"PRRT_kwDOa\\"}){thread{isResolved}} b:resolveReviewThread('
            'input:{threadId:\\"$t\\"}){thread{isResolved}}}"'
        )
        scan = _case("thread_id_assignment", command=command, result="{}")
        # The literal id is still looked up; the call stays unresolved.
        (write,) = scan["pending"]
        self.assertEqual(
            (write["thread_ids"], write["only_review_threads"]), (["PRRT_kwDOa"], False)
        )
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_function_that_moves_its_parameters_is_not_traced(self):
        mutation = (
            "gh api graphql -f query='mutation($t:ID!){resolveReviewThread("
            'input:{threadId:$t}){thread{isResolved}}}\' -f t="$1"'
        )
        for command in (
            "r(){ shift; " + mutation + "; }; r PRRT_kwDOa PRRT_kwDOb",
            "r(){ set -- PRRT_kwDOb; " + mutation + "; }; r PRRT_kwDOa",
            "r(){ while [ $# -gt 0 ]; do "
            + mutation
            + "; shift; done; }; r PRRT_kwDOa PRRT_kwDOb",
        ):
            with self.subTest(command=command[:30]):
                scan = _case("thread_id_function", command=command, result="true")
                self.assertEqual(scan["pending"], [])
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_every_id_argument_must_be_accounted_for(self):
        # Review round 6: beside a literal id, an argument in another form
        # left the call complete and its own thread unread.
        mutation = (
            '{a:resolveReviewThread(input:{threadId:\\"PRRT_kwDOa\\"}){thread{isResolved}} '
            "b:resolveReviewThread(input:{threadId:{ref}}){thread{isResolved}}}"
        )
        for command, traced in (
            (
                '-f id=PRRT_kwDOb -f query="mutation(\\$id:ID!)'
                + mutation.replace("{ref}", "\\$id")
                + '"',
                ["PRRT_kwDOa", "PRRT_kwDOb"],
            ),
            (
                "-f query='mutation"
                + mutation.replace('\\"', '"').replace("{ref}", '"\'"$T"\'"')
                + "'",
                None,
            ),
        ):
            with self.subTest(command=command[:30]):
                scan = _case(
                    "thread_id_assignment",
                    command="gh api graphql " + command,
                    result="{}",
                )
                if traced:
                    (write,) = scan["pending"]
                    self.assertEqual(write["thread_ids"], traced)
                    self.assertEqual(scan["unresolved"], [])
                else:
                    self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_function_called_other_than_by_its_name_is_not_traced(self):
        define = (
            "r(){ gh api graphql -f query='mutation($t:ID!){resolveReviewThread("
            'input:{threadId:$t}){thread{isResolved}}}\' -f t="$1"; }; r PRRT_kwDOa; '
        )
        for call in (
            "f=r; $f PRRT_kwDOb",
            "\\r PRRT_kwDOb",
            'retry(){ "$@"; }; retry r PRRT_kwDOb',
            "for fn in r; do $fn PRRT_kwDOb; done",
            "c=(r); ${c[0]} PRRT_kwDOb",
            "trap 'r PRRT_kwDOb' EXIT",
            "$(echo r) PRRT_kwDOb",
            # Review round 8: the name beside `-` or `.`, and calls that
            # never spell it.
            "f=${F:-r}; $f PRRT_kwDOb",
            "./later.sh r PRRT_kwDOb",
            "x=r.; ${x%.} PRRT_kwDOb",
            ". ./more.sh",
            '"${FUNCNAME[0]}" PRRT_kwDOb',
            "$(printf '\\162') PRRT_kwDOb",
        ):
            with self.subTest(call=call):
                scan = _case(
                    "thread_id_function", command=define + call, result="true\ntrue"
                )
                self.assertEqual(scan["pending"], [])
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_graphql_variable_named_like_its_argument(self):
        command = (
            "gh api graphql -f threadId=PRRT_kwDOb -f query='mutation($threadId:ID!)"
            "{resolveReviewThread(input:{threadId:$threadId}){thread{isResolved}}}'"
        )
        scan = _case("thread_id_assignment", command=command, result="true")
        (write,) = scan["pending"]
        self.assertEqual(
            (write["thread_ids"], write["only_review_threads"]), (["PRRT_kwDOb"], True)
        )

    def test_a_mutation_from_a_file_is_never_complete(self):
        for command in (
            (
                "gh api graphql -F query=@q.graphql -f note='threadId:\"PRRT_kwDOa\"'"
                " # resolveReviewThread"
            ),
            "gh api graphql -Fquery=@resolve.graphql -f id=PRRT_kwDOa",
            (
                'read -r Q < m.graphql; gh api graphql -f query="$Q" -f id=PRRT_kwDOa'
                " # resolveReviewThread(input:{threadId:$id})"
            ),
            # Review round 9: other spellings of a value from elsewhere.
            'Q=$(cat m.graphql); gh api graphql -fquery="$Q" -f id=PRRT_kwDOa',
            'Q=; Q+=$(cat m.graphql); gh api graphql -f query="$Q" -f id=PRRT_kwDOa',
            'printf -v Q %s "$(cat m)"; gh api graphql -f query="$Q" -f id=PRRT_kwDOa',
            'B=$(cat m); Q="$B"; gh api graphql -f query="$Q" -f id=PRRT_kwDOa',
            'gh api graphql -f query="$Q" -f id=PRRT_kwDOa',
            # Review round 11: a positional or special parameter.
            (
                'set -- "$(cat m.graphql)"; gh api graphql -f query="$1"'
                " -f threadId=PRRT_kwDOabc"
            ),
            'r(){ gh api graphql -f query="$@"; }; r "$(cat m.graphql)"',
        ):
            with self.subTest(command=command[:40]):
                scan = _case("thread_id_assignment", command=command, result="{}")
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_thread_id_in_a_body_or_note_is_not_asked_for(self):
        for command in (
            (
                "gh api graphql -f query='mutation{addPullRequestReviewThreadReply("
                'input:{pullRequestReviewThreadId:"PRRT_kwDOt",body:"dup of PRRT_kwDOq"})'
                "{comment{id}}}'"
            ),
            (
                "gh api graphql -f query='mutation{resolveReviewThread("
                'input:{threadId:"PRRT_kwDOt"}){thread{isResolved}}}\' -f note=PRRT_kwDOq'
            ),
        ):
            with self.subTest(command=command[-30:]):
                scan = _case("thread_id_assignment", command=command, result="{}")
                (write,) = scan["pending"]
                self.assertEqual(write["thread_ids"], ["PRRT_kwDOt"])

    def test_a_plain_text_query_rewritten_at_run_time_is_a_write(self):
        # A query variable assigned plain text is no write, unless a later
        # command may give it another value.
        plain = "Q='query{viewer{login}}'; "
        send = 'gh api graphql -f query="$Q"'
        for setter in (
            # CodeRabbit on #190: a later setter replaces the literal value.
            'printf -v Q %s "$(cat m)"; ',
            'declare Q="$(cat m)"; ',
            # Review round 13: setters behind `builtin`/`command`, `eval`,
            # and an array element.
            'builtin printf -v Q %s "$(cat m)"; ',
            "command read Q < m; ",
            "eval 'Q=$(cat m)'; ",
            # Review round 14: any other command that names the variable.
            "IFS= builtin read Q < m; ",
            "command -p read Q < m; ",
            "eval 'read Q < m'; ",
            "\\read Q < m; ",
            'printf -v "Q[0]" %s "$(cat m)"; ',
            # Review round 15: the name joined to the flag.
            'printf -vQ %s "$(cat m)"; ',
        ):
            with self.subTest(setter=setter):
                scan = _case("query_beside_mutation", command=plain + setter + send)
                self.assertEqual(len(scan["unresolved"]), 1)
        for harmless in ("", "printf 'Q: %s\\n' \"$Q\"; ", "echo Q; "):
            with self.subTest(harmless=harmless):
                scan = _case(
                    "query_beside_mutation",
                    command=plain + harmless + send,
                    result='{"data":{"viewer":{"login":"x"}}}',
                )
                self.assertEqual(scan["unresolved"], [])

    def test_a_parameter_that_is_no_literal_id_stays_unresolved(self):
        define = (
            "r(){ gh api graphql -f query='mutation($t:ID!){resolveReviewThread("
            'input:{threadId:$t}){thread{isResolved}}}\' -f t="{ref}"; }; '
        )
        for command in (
            define.replace("{ref}", "$1") + 'r PRRT_kwDOa; r "$X"',
            define.replace("{ref}", "$1") + "r PRRT_kwDOa; r notanid",
            define.replace("{ref}", "${1/PRRT_kwDOa/PRRT_kwDOb}") + "r PRRT_kwDOa",
        ):
            with self.subTest(command=command[-30:]):
                scan = _case("thread_id_function", command=command, result="true\ntrue")
                self.assertEqual(scan["pending"], [])
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_variable_comment_id_beside_a_literal_one_stays_unknown(self):
        command = (
            "C=$(cat c); gh api graphql -f query='mutation($c:ID!){"
            'a:updatePullRequestReviewComment(input:{pullRequestReviewCommentId:"PRRC_kwDOa",body:"x"}){clientMutationId} '
            'b:updatePullRequestReviewComment(input:{pullRequestReviewCommentId:$c,body:"y"}){clientMutationId}}\' -f c=$C'
        )
        scan = _case("review_comment_node", command=command, result="{}")
        (write,) = scan["pending"]
        self.assertEqual(
            (write["thread_ids"], write["only_review_threads"]), (["PRRC_kwDOa"], False)
        )
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_comment_id_in_an_edit_body_is_not_asked_for(self):
        command = (
            "gh api graphql -f query='mutation{updatePullRequestReviewComment("
            'input:{pullRequestReviewCommentId:"PRRC_kwDOa",body:"same as PRRC_kwDOother"})'
            "{clientMutationId}}'"
        )
        scan = _case("review_comment_node", command=command, result="{}")
        (write,) = scan["pending"]
        self.assertEqual(write["thread_ids"], ["PRRC_kwDOa"])

    def test_a_comment_id_in_a_reply_body_is_not_asked_for(self):
        command = (
            "gh api graphql -f query='mutation{addPullRequestReviewThreadReply("
            'input:{pullRequestReviewThreadId:"PRRT_kwDOa",body:"see PRRC_kwDOother"})'
            "{comment{id}}}'"
        )
        scan = _case("thread_id_assignment", command=command, result="{}")
        (write,) = scan["pending"]
        self.assertEqual(write["thread_ids"], ["PRRT_kwDOa"])

    def test_a_deleted_comment_stays_unresolved(self):
        # Nothing is left on the forge to name its PR.
        for command in (
            "gh api -X DELETE repos/o/r/issues/comments/5",
            (
                "gh api graphql -f query='mutation{deletePullRequestReviewComment("
                'input:{id:"PRRC_kwDOa"}){clientMutationId}}\''
            ),
        ):
            with self.subTest(command=command[:30]):
                scan = _case("rest_comment_by_id", command=command, result="")
                self.assertEqual(scan["pending"], [])
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_review_comment_edited_by_node_id(self):
        write = self._pending("review_comment_node")
        self.assertEqual(write["thread_ids"], ["PRRC_kwDOMsI9BM73NDW3"])

    def test_a_comment_edited_by_its_rest_path(self):
        write = self._pending("rest_comment_by_id")
        self.assertEqual(
            (write["thread_ids"], write["comment_endpoints"]),
            (
                [],
                [
                    "repos/netresearch/docker-development-skill/issues/comments/5917853122"
                ],
            ),
        )


class CollectorLookupTest(unittest.TestCase):
    """`complete` is true when every pending write resolved on the forge."""

    PR = f"{GH}/docker-development-skill/pull/104"

    def _main(self, transcript: Path, comment_answer):
        def fake(command, **_):
            if command[:2] == ["gh", "api"] and command[2].startswith("repos/"):
                return comment_answer(command)
            return subprocess.CompletedProcess(command, 1, "", "HTTP 404: Not Found")

        out = io.StringIO()
        with (
            mock.patch.object(crf.subprocess, "run", side_effect=fake),
            contextlib.redirect_stdout(out),
        ):
            crf.main(
                ["x", "--transcript-file", str(transcript), "--output-format", "json"]
            )
        return json.loads(out.getvalue())

    def _transcript(self) -> Path:
        case = CASES["rest_comment_by_id"]
        return _transcript((case["command"], case["result"], case["is_error"]))

    def test_a_comment_path_resolves_to_its_pull_request(self):
        def answer(command):
            body = {"html_url": f"{self.PR}#issuecomment-5917853122"}
            return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

        result = self._main(self._transcript(), answer)
        self.assertEqual(result["unresolved_forge_commands"], [])
        self.assertEqual(result["review_thread_lookup_failures"], [])
        (pr,) = [a for a in result["artefacts"] if a["url"] == self.PR]
        self.assertEqual(pr["origin"], "acted")

    def test_a_failed_comment_lookup_makes_the_write_unresolved(self):
        def answer(command):
            return subprocess.CompletedProcess(
                command, 1, "", "gh: Not Found (HTTP 404)"
            )

        result = self._main(self._transcript(), answer)
        self.assertEqual(
            result["unresolved_forge_commands"],
            [dss.squeeze(CASES["rest_comment_by_id"]["command"], 200)],
        )
        (failure,) = result["review_thread_lookup_failures"]
        self.assertIn("HTTP 404", failure["reason"])
        self.assertFalse(result["complete"])


if __name__ == "__main__":
    unittest.main()
