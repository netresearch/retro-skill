#!/usr/bin/env python3
"""Unit tests for scripts/find-org-skills.py (org+installed skill discovery)."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = REPO_ROOT / "scripts" / "find-org-skills.py"
    spec = importlib.util.spec_from_file_location("find_org_skills", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fos = _load()


def _make_home() -> Path:
    """Build a synthetic ~/.claude with two marketplaces and one installed plugin."""
    home = Path(tempfile.mkdtemp())
    plugins = home / "plugins"
    (plugins / "cache" / "gh-mp" / "alpha" / "1.0.0" / "skills").mkdir(parents=True)
    # marketplace A (github source) — alpha installed, beta not
    mp_a = plugins / "marketplaces" / "gh-mp" / ".claude-plugin"
    mp_a.mkdir(parents=True)
    (mp_a / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "gh-mp",
                "plugins": [
                    {
                        "name": "alpha",
                        "description": "Alpha skill",
                        "source": {"source": "github", "repo": "org/alpha-skill"},
                        "category": "x",
                    },
                    {
                        "name": "beta",
                        "description": "Beta skill (ä ö ü)",
                        "source": {"source": "github", "repo": "org/beta-skill"},
                        "category": "y",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    # marketplace B (git url source) — gamma not installed
    mp_b = plugins / "marketplaces" / "git-mp" / ".claude-plugin"
    mp_b.mkdir(parents=True)
    (mp_b / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "git-mp",
                "plugins": [
                    {
                        "name": "gamma",
                        "description": "Gamma skill",
                        "source": {
                            "source": "git",
                            "url": "git@example.com:org/gamma.git",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (plugins / "known_marketplaces.json").write_text(
        json.dumps(
            {
                "gh-mp": {
                    "source": {"source": "github", "repo": "org/gh-mp"},
                    "installLocation": str(plugins / "marketplaces" / "gh-mp"),
                },
                "git-mp": {
                    "source": {
                        "source": "git",
                        "url": "git@example.com:org/git-mp.git",
                    },
                    "installLocation": str(plugins / "marketplaces" / "git-mp"),
                },
            }
        ),
        encoding="utf-8",
    )
    return home


class FindOrgSkillsTest(unittest.TestCase):
    def setUp(self):
        self.home = _make_home()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def test_collect_all_marketplaces(self):
        skills = fos.collect(self.home)
        names = {s["name"] for s in skills}
        self.assertEqual(names, {"alpha", "beta", "gamma"})
        self.assertEqual(len({s["marketplace"] for s in skills}), 2)

    def test_installed_flag(self):
        by = {s["name"]: s for s in fos.collect(self.home)}
        self.assertTrue(by["alpha"]["installed"])  # present in cache
        self.assertFalse(by["beta"]["installed"])  # catalogue only
        self.assertFalse(by["gamma"]["installed"])

    def test_repo_url_github_and_git(self):
        by = {s["name"]: s for s in fos.collect(self.home)}
        self.assertEqual(by["alpha"]["repo_url"], "https://github.com/org/alpha-skill")
        self.assertEqual(by["gamma"]["repo_url"], "git@example.com:org/gamma.git")

    def test_available_not_installed_detectable(self):
        # the load-bearing capability: skills that exist org-wide but aren't here
        skills = fos.collect(self.home)
        available = [s["name"] for s in skills if not s["installed"]]
        self.assertIn("beta", available)
        self.assertIn("gamma", available)

    def test_missing_known_marketplaces_graceful(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        self.assertEqual(fos.collect(empty), [])

    def test_missing_manifest_skipped(self):
        # a configured marketplace whose manifest is absent is skipped, not fatal
        shutil.rmtree(self.home / "plugins" / "marketplaces" / "git-mp")
        names = {s["name"] for s in fos.collect(self.home)}
        self.assertEqual(names, {"alpha", "beta"})

    def test_text_output_marks_availability_and_umlauts(self):
        out = _run_main(self.home, "text")
        self.assertIn("AVAILABLE (not installed)", out)
        self.assertIn("ä ö ü", out)  # verbatim description, no mojibake


def _minimal_home(plugins, mp_source=None, skills=()):
    home = Path(tempfile.mkdtemp())
    plug = home / "plugins"
    mp = plug / "marketplaces" / "mp" / ".claude-plugin"
    mp.mkdir(parents=True)
    (mp / "marketplace.json").write_text(
        json.dumps({"name": "mp", "plugins": plugins}), encoding="utf-8"
    )
    known = {"mp": {"installLocation": str(plug / "marketplaces" / "mp")}}
    if mp_source is not None:
        known["mp"]["source"] = mp_source
    (plug / "known_marketplaces.json").write_text(json.dumps(known), encoding="utf-8")
    for s in skills:
        (home / "skills" / s).mkdir(parents=True)
    return home


class FixesTest(unittest.TestCase):
    def test_skills_dir_does_not_falsely_mark_installed(self):
        # A standalone ~/.claude/skills dir whose name collides with a catalogue
        # plugin must NOT mark it installed — only the plugin cache counts.
        home = _minimal_home(
            [
                {
                    "name": "context7",
                    "description": "d",
                    "source": {"source": "github", "repo": "o/context7-skill"},
                }
            ],
            skills=("context7",),
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.assertFalse(fos.collect(home)[0]["installed"])

    def test_null_description_does_not_crash_text(self):
        home = _minimal_home(
            [
                {
                    "name": "x",
                    "description": None,
                    "source": {"source": "github", "repo": "o/x"},
                }
            ]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.assertEqual(fos.collect(home)[0]["description"], "")
        self.assertIn("x", _run_main(home, "text"))  # must not raise

    def test_monorepo_string_source_falls_back_to_marketplace(self):
        home = _minimal_home(
            [{"name": "x", "description": "d", "source": "./plugins/x"}],
            mp_source={"source": "github", "repo": "o/monorepo"},
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.assertEqual(
            fos.collect(home)[0]["repo_url"], "https://github.com/o/monorepo"
        )

    def test_full_url_repo_not_double_prefixed(self):
        home = _minimal_home(
            [
                {
                    "name": "x",
                    "description": "d",
                    "source": {"repo": "https://github.com/o/x"},
                }
            ]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.assertEqual(fos.collect(home)[0]["repo_url"], "https://github.com/o/x")


def _run_main(home: Path, fmt: str) -> str:
    import sys

    argv = sys.argv
    sys.argv = [
        "find-org-skills.py",
        "--claude-home",
        str(home),
        "--output-format",
        fmt,
    ]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            fos.main()
    finally:
        sys.argv = argv
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
