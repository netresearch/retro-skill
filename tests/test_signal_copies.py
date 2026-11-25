# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""A catalog signal reaches its routing row and the files that restate it.

B23 and B24 were added to the catalog and the routing table first, and reviews
of #274 then found them missing from SKILL.md, workflow.md and done-mode.md.
The catalog's status table counted six E signals when its table held eight.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "retro"
CATALOG = SKILL / "references" / "friction-catalog.md"
ROUTING = SKILL / "references" / "classification-heuristic.md"
COMMAND = REPO_ROOT / "commands" / "retro.md"
README = REPO_ROOT / "README.md"
DONE = SKILL / "references" / "done-mode.md"

ROW = re.compile(r"(?m)^\| \**([A-E][0-9]+)\b\**")
COUNT = re.compile(r"(?m)^\| ([A-E]) — [^|]+\| ([0-9]+) \|")
NOT_ASSESSABLE = re.compile(r"([A-E][0-9]+) not assessable")

# These layers have one route for the whole layer, stated in the command.
LAYER_ROUTES = {
    "D": "destinations skew toward `skill-update`",
    "E": "Destinations skew toward `project-rule`",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load():
    path = REPO_ROOT / "scripts" / "find-copies.py"
    spec = importlib.util.spec_from_file_location("find_copies", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


find_copies = load()


def named(path: Path) -> set[str]:
    return {signal for _, signal in find_copies.signal_mentions(read(path))}


class SignalCopies(unittest.TestCase):
    def setUp(self):
        self.catalog = ROW.findall(read(CATALOG))
        self.routed = ROW.findall(read(ROUTING))

    def test_both_tables_are_read(self):
        for signal in ("A1", "A21", "B1", "B24", "C7", "D11", "E8"):
            self.assertIn(signal, self.catalog)
        self.assertIn("B24", self.routed)
        for name, ids in (("catalog", self.catalog), ("routing", self.routed)):
            self.assertEqual(len(ids), len(set(ids)), f"duplicate row in {name}")

    def test_every_signal_has_a_route(self):
        command = read(COMMAND)
        for layer, route in LAYER_ROUTES.items():
            self.assertIn(route, command, f"the route of layer {layer} is gone")
        missing = [
            s for s in self.catalog if s not in self.routed and s[0] not in LAYER_ROUTES
        ]
        self.assertEqual(missing, [], "no row in classification-heuristic.md")

    def test_every_route_belongs_to_a_signal(self):
        self.assertEqual([s for s in self.routed if s not in self.catalog], [])

    def test_the_status_table_counts_the_rows(self):
        stated = {layer: int(n) for layer, n in COUNT.findall(read(CATALOG))}
        actual = {layer: sum(s[0] == layer for s in self.catalog) for layer in "ABCDE"}
        self.assertEqual(stated, actual)

    def test_the_readme_states_the_same_counts(self):
        stated = re.findall(r"\(layer ([ABC])[^)]*\)\*\*.*?\*\*(\d+)\*\*", read(README))
        actual = [(x, str(sum(s[0] == x for s in self.catalog))) for x in "ABC"]
        self.assertEqual(stated, actual)

    def test_the_later_b_signals_are_named_where_a_run_reads_them(self):
        # Of B1 to B15 these files describe most by name only.
        wanted = {s for s in self.catalog if s[0] == "B" and int(s[1:]) >= 16}
        for path in (COMMAND, SKILL / "SKILL.md", SKILL / "references" / "workflow.md"):
            with self.subTest(file=path.name):
                self.assertEqual(sorted(wanted - named(path)), [])

    def test_done_mode_knows_every_not_assessable_line(self):
        lines = set(NOT_ASSESSABLE.findall(read(COMMAND)))
        self.assertIn("B24", lines)
        self.assertEqual(lines, set(NOT_ASSESSABLE.findall(read(DONE))))


class FindCopies(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        (self.repo / "commands").mkdir()

    def find(self, text, *terms):
        (self.repo / "commands" / "x.md").write_text(text, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = find_copies.main(list(terms), repo=self.repo)
        return code, out.getvalue()

    def test_an_id_is_found_in_a_range_and_alone(self):
        code, out = self.find("a\nB16–B21\nB19 here\n", "B19")
        self.assertEqual(code, 0)
        self.assertIn("x.md:2: B16–B21", out)
        self.assertIn("x.md:3: B19 here", out)

    def test_an_id_is_not_found_in_a_longer_id_or_outside_the_range(self):
        self.assertEqual(self.find("B19 B16–B18\n", "B1")[0], 1)
        self.assertEqual(self.find("B16–B21\n", "B22")[0], 1)

    def test_a_phrase_is_found_across_a_line_break_in_any_case(self):
        code, out = self.find("x\na Reasoned\nno-op\n", "reasoned no-op")
        self.assertEqual(code, 0)
        self.assertIn("x.md:2:", out)

    def test_a_phrase_is_found_across_the_lines_of_a_quote_or_a_comment(self):
        for prefix in ("> ", "# ", "    # ", "> > "):
            with self.subTest(prefix=prefix):
                text = f"x\n{prefix}a Reasoned\n{prefix}no-op\n"
                code, out = self.find(text, "reasoned no-op")
                self.assertEqual(code, 0)
                self.assertIn("x.md:2:", out)
        self.assertEqual(self.find("reasoned > no-op\n", "reasoned no-op")[0], 1)

    def test_a_phrase_is_found_on_one_line(self):
        self.assertEqual(self.find("a reasoned  no-op\n", "reasoned no-op")[0], 0)

    def test_a_lettered_phase_is_found_as_its_bare_id(self):
        code, out = self.find(
            "Phase 4b\n2b/3/4b\n| 4b (x) |\n14b x4b 4bx\n", "Phase 4b"
        )
        self.assertEqual(code, 0)
        self.assertIn("== Phase 4b: 3 lines", out)

    def test_one_missing_term_fails_the_run(self):
        self.assertEqual(self.find("alpha\n", "alpha", "beta")[0], 1)
        self.assertEqual(self.find("alpha\n", "beta", "alpha")[0], 1)


if __name__ == "__main__":
    unittest.main()
