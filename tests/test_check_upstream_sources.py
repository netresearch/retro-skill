#!/usr/bin/env python3
"""Unit tests for skills/retro/scripts/check-upstream-sources.py (offline paths only)."""

from __future__ import annotations

import datetime
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = REPO_ROOT / "skills" / "retro" / "scripts" / "check-upstream-sources.py"
    spec = importlib.util.spec_from_file_location("check_upstream_sources", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cus = _load()


class FixtureMixin(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        (self.dir / "references").mkdir()
        (self.dir / "SKILL.md").write_text("# Fixture skill\n")


class TestCollectMarkdown(FixtureMixin):
    def test_labelled_link_is_collected_adjacent_line_included(self):
        (self.dir / "references" / "a.md").write_text(
            "See [Foo](https://example.org/foo.html)\n"
            "`[upstream]` — canonical.\n"
            "\n"
            "Unlabelled [Bar](https://example.org/bar.html) elsewhere.\n"
        )
        urls = {o["url"] for o in cus.collect_markdown(self.dir)}
        self.assertIn("https://example.org/foo.html", urls)
        self.assertNotIn("https://example.org/bar.html", urls)

    def test_no_labels_means_no_urls(self):
        (self.dir / "references" / "a.md").write_text(
            "Only [Bar](https://example.org/bar.html), no label anywhere.\n"
        )
        self.assertEqual(cus.collect_markdown(self.dir), [])


class TestCollectCheckpoints(FixtureMixin):
    def test_source_url_and_verified_date_are_attributed_to_the_entry(self):
        (self.dir / "checkpoints.yaml").write_text(
            "mechanical:\n"
            "  - id: XX-01\n"
            "    type: file_exists\n"
            "    target: README.md\n"
            '    source: "https://example.org/spec — see note"\n'
            "    verified: 2020-01-01\n"
        )
        urls, verified = cus.collect_checkpoints(self.dir)
        self.assertEqual(urls[0]["url"], "https://example.org/spec")
        self.assertIn("XX-01", urls[0]["origin"])
        self.assertEqual(verified[0]["checkpoint"], "XX-01")
        self.assertEqual(verified[0]["date"], "2020-01-01")

    def test_non_url_source_yields_no_url_occurrence(self):
        (self.dir / "checkpoints.yaml").write_text(
            "mechanical:\n"
            "  - id: XX-02\n"
            '    source: "observed in session 0815, no URL"\n'
        )
        urls, verified = cus.collect_checkpoints(self.dir)
        self.assertEqual(urls, [])
        self.assertEqual(verified, [])


class TestStaleFindings(unittest.TestCase):
    def test_old_date_flags_and_fresh_date_stays_quiet(self):
        old = {"checkpoint": "XX-01", "date": "2020-01-01", "file": "c.yaml", "line": 5}
        fresh = {
            "checkpoint": "XX-02",
            "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
            "file": "c.yaml",
            "line": 9,
        }
        findings = cus.stale_findings([old, fresh], max_age_days=180)
        self.assertEqual([f["checkpoint"] for f in findings], ["XX-01"])
        self.assertEqual(findings[0]["signal"], "B14")
        self.assertEqual(findings[0]["name"], "upstream_verification_stale")


class TestUrlCleanup(unittest.TestCase):
    def test_trailing_punctuation_is_stripped(self):
        self.assertEqual(
            cus._clean_url("https://example.org/x.html;"), "https://example.org/x.html"
        )


if __name__ == "__main__":
    unittest.main()
