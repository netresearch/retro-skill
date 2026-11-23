# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Every grader-input hash an evidence record cites resolves to a tracked file.

An evidence record under docs/evidence/ that cites the sha256 of what a grader
read lets a reader check the grade only if those bytes are in the repository.
This test walks every JSON file there and collects each value under a key
ending in ``input_sha256`` (today ``final_input_sha256`` and
``grading_input_sha256``). Each value must equal the sha256 of a file that
``git ls-files`` lists, or the record must be in DOCUMENTED_GAPS with the
exact number of unresolved values and where the loss is stated.

Other ``*sha256`` keys are out of scope: ``sources``, ``contexts``,
``source_sha256``, ``files_sha256``, ``tested_sha256``, ``final_sha256`` and
the like hash skill files or executor packets at the commit a record names,
so they stop matching the tree whenever those files change. Cases'
``inputs[].sha256`` name executor inputs, not grader inputs. See
https://github.com/netresearch/retro-skill/issues/277.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import unittest.mock
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = "docs/evidence/"
SUFFIX = "input_sha256"
# GIT_DIR and its siblings choose the repository ahead of `-C`; a git hook
# or the caller's shell would otherwise list another repository's files.
GIT_LOCATION_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
    }
)

# (record, key) -> (unresolved count, where the record states the loss)
DOCUMENTED_GAPS = {
    (
        "docs/evidence/situational-check-2026-11-14/grades.json",
        "final_input_sha256",
    ): (
        11,
        "README.md beside it: inputs not committed (727225b), note of 2026-11-23",
    ),
    ("docs/evidence/prior-attempts-2026-11-18.json", "grading_input_sha256"): (
        9,
        (
            "not stated in the record, which is left as written; measured "
            "2026-11-23 in issue 277: none matches a tracked file or a blob in history"
        ),
    ),
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
        env={k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARS},
    ).stdout.decode()
    return [p for p in out.split("\0") if p]


def tracked_hashes(paths: list[str]) -> set[str]:
    hashes = set()
    for rel in paths:
        path = REPO_ROOT / rel
        if path.is_file():
            hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    return hashes


def input_hashes(node) -> list[tuple[str, str]]:
    """(key, value) for every string under a key ending in SUFFIX."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith(SUFFIX):
                if isinstance(value, dict):
                    values = list(value.values())
                elif isinstance(value, list):
                    values = value
                else:
                    values = [value]
                found += [(key, v) for v in values if isinstance(v, str)]
            else:
                found += input_hashes(value)
    elif isinstance(node, list):
        for item in node:
            found += input_hashes(item)
    return found


def unresolved(records: dict[str, object], known: set[str]) -> Counter:
    """Unresolved values per (record, key), with resolved keys counted as 0."""
    counts: Counter = Counter()
    for path, data in records.items():
        for key, value in input_hashes(data):
            counts[(path, key)] += value not in known
    return counts


def evidence_records(paths: list[str]) -> dict[str, object]:
    return {
        p: json.loads((REPO_ROOT / p).read_text(encoding="utf-8"))
        for p in paths
        if p.startswith(EVIDENCE) and p.endswith(".json")
    }


class InputHashHelpers(unittest.TestCase):
    def test_collects_nested_mappings_and_lists(self):
        data = {
            "a": {"final_input_sha256": {"x.json": "1", "y.json": "2"}},
            "answers": [{"grading_input_sha256": "3"}, {"sha256": "4"}],
            "source_sha256": "5",
        }
        self.assertEqual(
            sorted(input_hashes(data)),
            [
                ("final_input_sha256", "1"),
                ("final_input_sha256", "2"),
                ("grading_input_sha256", "3"),
            ],
        )

    def test_resolved_value_counts_zero(self):
        known = {hashlib.sha256(b"kept").hexdigest()}
        records = {
            "r.json": {
                "grading_input_sha256": [
                    hashlib.sha256(b"kept").hexdigest(),
                    hashlib.sha256(b"lost").hexdigest(),
                ]
            }
        }
        self.assertEqual(
            unresolved(records, known), Counter({("r.json", "grading_input_sha256"): 1})
        )


class EvidenceInputHashes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths = tracked_files()
        cls.records = evidence_records(paths)
        cls.counts = unresolved(cls.records, tracked_hashes(paths))

    def test_records_are_found(self):
        self.assertGreater(len(self.records), 0)
        self.assertLessEqual(set(DOCUMENTED_GAPS), set(self.counts))

    def test_input_hashes_resolve_or_are_documented(self):
        for (path, key), count in sorted(self.counts.items()):
            with self.subTest(record=path, key=key):
                expected = DOCUMENTED_GAPS.get((path, key), (0, ""))[0]
                self.assertEqual(
                    count,
                    expected,
                    f"{path}: {count} {key} value(s) match no tracked file; "
                    "commit the input or state the loss in the record and "
                    "add it to DOCUMENTED_GAPS",
                )


class GitEnvTest(unittest.TestCase):
    def test_a_foreign_git_dir_does_not_change_the_listing(self) -> None:

        with tempfile.TemporaryDirectory() as other:
            subprocess.run(["git", "init", "-q", other], check=True)
            with unittest.mock.patch.dict(
                os.environ, {"GIT_DIR": os.path.join(other, ".git")}
            ):
                self.assertIn("AGENTS.md", tracked_files())


if __name__ == "__main__":
    unittest.main()
