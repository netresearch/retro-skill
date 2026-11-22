#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Smoke corpus for skills/retro/scripts/check-decision-records.py.

Each tests/fixtures/decision-records/<repo>.json holds AGENTS.md and the
decision-record files of one public Netresearch repository, copied at the
commit named in its "source" block. The three repositories write records in
three ways: a "## Status" heading (ldap-manager), bold fields
(composer-agent-skill-plugin), and bold fields with Touches under an ADR
declaration in AGENTS.md (retro-skill). <repo>.expected.json holds what the script
reads from them: the report, and every record file parsed on its own,
whether or not the AGENTS.md of that repository declares an ADR directory.

The unit tests cover the edge cases. This test covers files people actually
wrote, so a change that breaks a common format shows up here. It does not
replace a differential run over more files: the pre-markdown-it parser gives
the same output on this corpus. When a change is intended, regenerate the expected files and
explain each difference in the pull request:

    uv run --with markdown-it-py==4.3.0 --with mdit-py-plugins==0.7.0 \\
        --with PyYAML==6.0.4 python tests/test_decision_record_corpus.py --update
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "tests" / "fixtures" / "decision-records"


def _load():
    path = REPO_ROOT / "skills" / "retro" / "scripts" / "check-decision-records.py"
    spec = importlib.util.spec_from_file_location("check_decision_records", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cdr = _load()


def corpus_files() -> list[Path]:
    return sorted(
        p for p in CORPUS.glob("*.json") if not p.name.endswith(".expected.json")
    )


def observe(files: dict[str, str]) -> dict:
    """What the script reads from one repository's files."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        report = cdr.build_report(root, [])
    report.pop("repo")
    records = {
        rel: cdr.parse_record(text)
        for rel, text in files.items()
        if Path(rel).name != cdr.AGENTS_MD and cdr._is_record_file(Path(rel))
    }
    return {"report": report, "records": records}


def expected_path(corpus: Path) -> Path:
    return corpus.with_name(corpus.stem + ".expected.json")


def update() -> None:
    for corpus in corpus_files():
        files = json.loads(corpus.read_text(encoding="utf-8"))["files"]
        out = json.dumps(observe(files), indent=2, ensure_ascii=False) + "\n"
        expected_path(corpus).write_text(out, encoding="utf-8")
        print(f"wrote {expected_path(corpus).relative_to(REPO_ROOT)}")


class CorpusTest(unittest.TestCase):
    def test_corpus_is_present(self):
        self.assertGreaterEqual(len(corpus_files()), 3)

    def test_output_matches_expected(self):
        for corpus in corpus_files():
            with self.subTest(repo=corpus.stem):
                files = json.loads(corpus.read_text(encoding="utf-8"))["files"]
                expected = json.loads(expected_path(corpus).read_text(encoding="utf-8"))
                actual = json.loads(json.dumps(observe(files)))
                for part in ("report", "records"):
                    if part == "records":
                        self.assertEqual(sorted(actual[part]), sorted(expected[part]))
                        for rel in expected[part]:
                            self.assertEqual(
                                actual[part][rel],
                                expected[part][rel],
                                f"{corpus.stem}: {rel}",
                            )
                    else:
                        self.assertEqual(
                            actual[part], expected[part], f"{corpus.stem}: {part}"
                        )


if __name__ == "__main__":
    if "--update" in sys.argv:
        update()
        sys.exit(0)
    unittest.main()
