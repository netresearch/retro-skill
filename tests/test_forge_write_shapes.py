#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Forge writes that kept `complete` false although their target is known (#188).

Each recorded case is a tool call copied byte for byte from session e72080f1
(`fixtures/review-findings/forge-write-shapes-188.json`, 2026-10-18). Only two
shapes are resolved offline: a numbered write printing nothing after heredocs
bash does not expand (quoted delimiter, closed where the grammar closes it),
and a numbered write run in the background. Everything the parsing cannot
prove stays unresolved, as on main: unquoted heredocs, `pr-merge.sh` calls
and review-thread writes named by a forge id.
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


class HeredocShapesTest(unittest.TestCase):
    def test_a_numbered_edit_after_a_quoted_heredoc(self):
        # `python3 - <<'PY' … PY`, then `gh pr edit 19 -R … >/dev/null`.
        scan = _scan("quoted_heredoc")
        self.assertEqual(scan["origins"], {f"{GH}/t3x-nr-wellknown/pull/19": "acted"})
        self.assertEqual(scan["unresolved"], [])

    def test_a_numbered_edit_after_an_unquoted_heredoc_stays_unresolved(self):
        # `<<PY` with `$S` in the body: bash expands it, and a backtick or
        # `$(…)` there would run a command the parsing does not model.
        scan = _scan("unquoted_heredoc")
        self.assertEqual(scan["origins"], {})
        self.assertEqual(
            scan["unresolved"],
            [dss.squeeze(CASES["unquoted_heredoc"]["command"], 200)],
        )

    def test_a_backtick_in_an_unquoted_heredoc_stays_unresolved(self):
        # Bash runs the backtick write to #90; the grammar reads it as text
        # (review round 3). Neither PR may be named, the call is unresolved.
        command = (
            "cat > b.md <<EOF\n`gh pr edit 90 -R o/r --add-label x`\nEOF\n"
            "gh pr edit 89 -R o/r --body-file b.md"
        )
        scan = _case("quoted_heredoc", command=command, result="")
        self.assertEqual(scan["origins"], {})
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_every_quoting_of_the_delimiter_counts(self):
        for start in ("<<'EOF'", '<<"EOF"', "<<\\EOF"):
            command = (
                f"cat > b.md {start}\n`x` $(y)\nEOF\n"
                "gh pr edit 89 -R o/r --body-file b.md"
            )
            with self.subTest(start=start):
                scan = _case("quoted_heredoc", command=command, result="")
                self.assertEqual(
                    scan["origins"], {"https://github.com/o/r/pull/89": "acted"}
                )
        # `<<E'O'F` is quoted for bash, but the grammar does not end it where
        # bash does: fail closed, nothing is named.
        command = "cat > b.md <<E'O'F\nx\nEOF\ngh pr edit 89 -R o/r --body-file b.md"
        scan = _case("quoted_heredoc", command=command, result="")
        self.assertEqual(scan["origins"], {})

    def test_a_numbered_edit_inside_an_unclosed_heredoc_is_not_attributed(self):
        # Without its `PY` line the heredoc runs to the end: the edit is text
        # fed to python, not a command, and never a silent success.
        command = CASES["quoted_heredoc"]["command"].replace("\nPY\n", "\n", 1)
        self.assertNotEqual(command, CASES["quoted_heredoc"]["command"])
        self.assertEqual(_case("quoted_heredoc", command=command)["origins"], {})

    def test_a_numbered_edit_the_parser_cannot_read_whole_stays_unresolved(self):
        # An unclosed quoted delimiter is an ERROR node: the extent is unknown.
        command = "python3 - <<'PY'\nprint(1)\ngh pr edit 89 -R o/r --body-file b.md"
        scan = _case("quoted_heredoc", command=command, result="")
        self.assertEqual(scan["origins"], {})
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_heredoc_bash_does_not_close_hides_the_edit(self):
        # tree-sitter-bash ends a heredoc at `EOF `, `  EOF` or a tab-indented
        # `EOF` without `<<-`; bash reads on to the end, and the edit is
        # heredoc text (review rounds 1 and 2).
        for end in ("EOF ", "  EOF", "\tEOF"):
            command = (
                f"cat > /tmp/b.md <<'EOF'\nbody\n{end}\n"
                "gh pr edit 89 -R o/r --body-file /tmp/b.md"
            )
            with self.subTest(end=end):
                scan = _case("quoted_heredoc", command=command, result="")
                self.assertEqual(scan["origins"], {})
                self.assertEqual(len(scan["unresolved"]), 1)
        # `<<-` strips leading tabs only: a tab-indented end closes it.
        command = (
            "cat > /tmp/b.md <<-'EOF'\n\tbody\n\tEOF\n"
            "gh pr edit 89 -R o/r --body-file /tmp/b.md"
        )
        scan = _case("quoted_heredoc", command=command, result="")
        self.assertEqual(scan["origins"], {"https://github.com/o/r/pull/89": "acted"})

    def test_a_heredoc_program_that_carries_a_write_stays_unresolved(self):
        command = (
            "python3 - <<'PY'\nimport subprocess\n"
            "subprocess.run(['gh', 'pr', 'comment', '7', '-R', 'o/r', '-b', 'x'])\nPY\n"
            "gh pr edit 89 -R netresearch/typo3-ddev-skill --body-file b.md >/dev/null && echo ok"
        )
        scan = _case("quoted_heredoc", command=command, result="ok")
        self.assertEqual(len(scan["unresolved"]), 1)

    def test_more_end_lines_bash_does_not_take_under_a_dash(self):
        # `<<-` strips tabs, never spaces (review round 4).
        for end in ("\t EOF", "  EOF"):
            command = (
                f"cat > /tmp/b.md <<-'EOF'\nbody\n{end}\n"
                "gh pr edit 89 -R o/r --body-file /tmp/b.md"
            )
            with self.subTest(end=end):
                scan = _case("quoted_heredoc", command=command, result="")
                self.assertEqual(scan["origins"], {})
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_backslash_inside_a_quoted_delimiter_is_not_modelled(self):
        # Bash keeps it: `<<'E\F'` ends at `E\F`, not at `EF` (review round 4).
        for start in ("<<'E\\F'", "<<-'E\\F'", '<<"E\\F"'):
            command = (
                f"cat > b.md {start}\nbody\nEF\n"
                "gh pr edit 89 -R o/r --body-file b.md\nE\\F\necho done"
            )
            with self.subTest(start=start):
                scan = _case("quoted_heredoc", command=command, result="")
                self.assertEqual(scan["origins"], {})

    def test_a_quoted_heredoc_a_shell_runs_stays_unresolved(self):
        # Bash runs the body; the write to #90 in it, or one no pattern
        # sees (`$G pr comment …`), must not leave the call complete.
        for command in (
            "source /dev/stdin <<'EOF'\ngh pr comment 90 -R o/r -b x\nEOF\n",
            ". /dev/stdin <<'EOF'\ngh pr comment 90 -R o/r -b x\nEOF\n",
            "eval \"$(cat <<'EOF'\ngh pr comment 90 -R o/r -b x\nEOF\n)\"\n",
            "bash <<'EOF'\nG=gh; $G pr comment 90 -R o/r -b x\nEOF\n",
            "cat <<'EOF' | bash\nG=gh; $G pr comment 90 -R o/r -b x\nEOF\n",
            "cat > x.sh <<'EOF'\nG=gh; $G pr comment 90 -R o/r -b x\nEOF\nbash x.sh\n",
            'bash <<< "$CMD"\n',
        ):
            command += "gh pr edit 89 -R o/r --body-file b.md"
            with self.subTest(command=command[:30]):
                scan = _case("quoted_heredoc", command=command, result="")
                self.assertNotIn("https://github.com/o/r/pull/89", scan["origins"])
                self.assertEqual(len(scan["unresolved"]), 1)

    def test_a_heredoc_after_a_list_feeds_its_last_command(self):
        command = (
            "cd /tmp && python3 - <<'PY'\nprint(1)\nPY\n"
            "gh pr edit 89 -R o/r --body-file b.md >/dev/null"
        )
        scan = _case("quoted_heredoc", command=command, result="")
        self.assertEqual(scan["origins"], {"https://github.com/o/r/pull/89": "acted"})


class BackgroundShapesTest(unittest.TestCase):
    def test_a_numbered_write_run_in_the_background(self):
        # Its output is in a task file; its words name the PR.
        scan = _scan("background_numbered")
        self.assertEqual(scan["origins"], {f"{GH}/nr-landingpage/pull/84": "acted"})
        self.assertEqual(scan["unresolved"], [])

    def test_a_rest_write_run_in_the_background_stays_unresolved(self):
        # Only a numbered subcommand names its target in its words; a REST
        # write's output is elsewhere, so it is unresolved (review round 4).
        scan = _case(
            "background_numbered",
            command="gh api -X PUT repos/o/r/pulls/5/merge",
            result="Command running in background with ID: b1.",
        )
        self.assertEqual(scan["origins"], {})
        self.assertEqual(len(scan["unresolved"]), 1)


if __name__ == "__main__":
    unittest.main()
