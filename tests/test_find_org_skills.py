#!/usr/bin/env python3
"""Unit tests for skills/retro/scripts/find-org-skills.py (org+installed skill discovery)."""

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
    path = REPO_ROOT / "skills" / "retro" / "scripts" / "find-org-skills.py"
    spec = importlib.util.spec_from_file_location("find_org_skills", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fos = _load()


def _make_home() -> Path:
    """Build a synthetic ~/.claude with two marketplaces and one installed plugin."""
    home = Path(tempfile.mkdtemp())
    plugins = home / "plugins"
    alpha_skill = plugins / "cache" / "gh-mp" / "alpha" / "1.0.0" / "skills" / "alpha"
    alpha_skill.mkdir(parents=True)
    (alpha_skill / "SKILL.md").write_text(
        '---\nname: alpha\ndescription: "Use when routing alpha work"\n---\n# Alpha\n',
        encoding="utf-8",
    )
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


def _cached_plugin(
    home: Path, mp: str, plugin: str, version: str, skills: dict[str, str]
):
    """Write <cache>/<mp>/<plugin>/<version>/skills/<skill>/SKILL.md per entry."""
    root = home / "plugins" / "cache" / mp / plugin / version
    for skill, description in skills.items():
        d = root / "skills" / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: {description}\n---\n# {skill}\n",
            encoding="utf-8",
        )
    return root


class RoutingDescriptionTest(unittest.TestCase):
    """#83: the description that routes is SKILL.md's, not the catalogue's."""

    def setUp(self):
        self.home = _make_home()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def test_installed_plugin_carries_skill_md_description(self):
        by = {s["name"]: s for s in fos.collect(self.home)}
        self.assertEqual(by["alpha"]["description"], "Use when routing alpha work")
        self.assertEqual(by["alpha"]["description_source"], "skill")
        self.assertEqual(by["alpha"]["catalogue_description"], "Alpha skill")
        self.assertEqual(by["alpha"]["skill"], "alpha")

    def test_uninstalled_plugin_is_labelled_catalogue(self):
        by = {s["name"]: s for s in fos.collect(self.home)}
        self.assertEqual(by["beta"]["description"], "Beta skill (ä ö ü)")
        self.assertEqual(by["beta"]["description_source"], "catalogue")
        self.assertEqual(by["beta"]["catalogue_description"], "Beta skill (ä ö ü)")
        self.assertEqual(by["beta"]["skill"], "")

    def test_multi_skill_plugin_emits_one_entry_per_skill(self):
        home = _minimal_home(
            [{"name": "multi", "description": "d", "source": {"repo": "o/multi"}}]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        _cached_plugin(
            home, "mp", "multi", "2.0.0", {"one": "Use when one", "two": "Use when two"}
        )
        by = {s["name"]: s for s in fos.collect(home)}
        self.assertEqual(set(by), {"multi:one", "multi:two"})
        self.assertEqual(by["multi:two"]["description"], "Use when two")
        self.assertEqual(by["multi:two"]["plugin"], "multi")
        self.assertEqual(by["multi:two"]["skill"], "two")
        self.assertTrue(by["multi:two"]["installed"])

    def test_installed_plugins_json_selects_the_installed_version(self):
        # The cache keeps old versions next to the current one; the record
        # Claude Code writes names the one in use, and the highest is not it.
        home = _minimal_home(
            [{"name": "x", "description": "d", "source": {"repo": "o/x"}}]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        _cached_plugin(home, "mp", "x", "1.9.0", {"x": "Use when 1.9"})
        _cached_plugin(home, "mp", "x", "1.10.0", {"x": "Use when 1.10"})
        installed = home / "plugins" / "cache" / "mp" / "x" / "1.9.0"
        (home / "plugins" / "installed_plugins.json").write_text(
            json.dumps(
                {"version": 2, "plugins": {"x@mp": [{"installPath": str(installed)}]}}
            ),
            encoding="utf-8",
        )
        self.assertEqual(fos.collect(home)[0]["description"], "Use when 1.9")

    def test_cache_fallback_picks_highest_version_numerically(self):
        home = _minimal_home(
            [{"name": "x", "description": "d", "source": {"repo": "o/x"}}]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        _cached_plugin(home, "mp", "x", "1.9.0", {"x": "Use when 1.9"})
        _cached_plugin(home, "mp", "x", "1.10.0", {"x": "Use when 1.10"})
        self.assertEqual(fos.collect(home)[0]["description"], "Use when 1.10")

    def test_cache_fallback_survives_a_non_version_directory(self):
        # Cache directories are not guaranteed to be plain versions. Comparing
        # a tagged key keeps `sorted()` from raising TypeError on ('latest',)
        # against (1, 0, 0) and taking the whole scan down with it.
        home = _minimal_home(
            [{"name": "x", "description": "d", "source": {"repo": "o/x"}}]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        _cached_plugin(home, "mp", "x", "1.0.0", {"x": "Use when 1.0"})
        _cached_plugin(home, "mp", "x", "latest", {"x": "Use when latest"})
        entry = fos.collect(home)[0]
        self.assertEqual(entry["description_source"], "skill")

    def test_cache_fallback_runs_when_the_recorded_path_is_gone(self):
        # installed_plugins.json outlives the directory it names (a pruned
        # version, a moved cache). That is the case the cache is a fallback
        # for, so a recorded plugin with no resolvable path must still reach it.
        home = _minimal_home(
            [{"name": "x", "description": "d", "source": {"repo": "o/x"}}]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        _cached_plugin(home, "mp", "x", "1.0.0", {"x": "Use when cached"})
        (home / "plugins" / "installed_plugins.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "plugins": {"x@mp": [{"installPath": str(home / "gone")}]},
                }
            ),
            encoding="utf-8",
        )
        entry = fos.collect(home)[0]
        self.assertEqual(entry["description"], "Use when cached")
        self.assertEqual(entry["description_source"], "skill")

    def test_multi_skill_plugin_qualifies_even_the_eponymous_skill(self):
        # `foo` and `foo:bar` side by side read as two plugins.
        home = _minimal_home(
            [{"name": "foo", "description": "d", "source": {"repo": "o/foo"}}]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        _cached_plugin(
            home, "mp", "foo", "1.0.0", {"foo": "Use when foo", "bar": "Use when bar"}
        )
        self.assertEqual({s["name"] for s in fos.collect(home)}, {"foo:foo", "foo:bar"})

    def test_manifest_skill_path_outside_the_install_root_is_ignored(self):
        # A plugin manifest is third-party data; `..` must not reach a SKILL.md
        # belonging to another plugin and publish it as this one's.
        home = _minimal_home(
            [{"name": "p", "description": "d", "source": {"repo": "o/p"}}]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        root = home / "plugins" / "cache" / "mp" / "p" / "1.0.0"
        outside = home / "outside" / "secret"
        outside.mkdir(parents=True)
        (outside / "SKILL.md").write_text(
            "---\nname: secret\ndescription: Use when leaked\n---\n", encoding="utf-8"
        )
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(
                {"name": "p", "skills": ["../../../../../outside/secret", str(outside)]}
            ),
            encoding="utf-8",
        )
        entry = fos.collect(home)[0]
        self.assertEqual(entry["description_source"], "catalogue")
        self.assertNotIn("leaked", entry["description"])

    def test_installed_plugin_without_skills_falls_back_to_catalogue(self):
        # LSP / command-only plugins ship no skills/*/SKILL.md.
        home = _minimal_home(
            [
                {
                    "name": "lsp",
                    "description": "Language server",
                    "source": {"repo": "o/l"},
                }
            ]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        (home / "plugins" / "cache" / "mp" / "lsp" / "1.0.0").mkdir(parents=True)
        entry = fos.collect(home)[0]
        self.assertTrue(entry["installed"])
        self.assertEqual(entry["description_source"], "catalogue")
        self.assertEqual(entry["description"], "Language server")

    def test_manifest_skills_field_overrides_default_layout(self):
        # plugin.json may name the skill dirs (list) or one dir holding several
        # (string) -- ui-ux-pro-max ships `"skills": "./.claude/skills/"`.
        home = _minimal_home(
            [{"name": "p", "description": "d", "source": {"repo": "o/p"}}]
        )
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        root = home / "plugins" / "cache" / "mp" / "p" / "1.0.0"
        for skill in ("one", "two"):
            d = root / ".claude" / "skills" / skill
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: Use when {skill}\n---\n",
                encoding="utf-8",
            )
        (root / ".claude-plugin").mkdir()
        (root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "p", "skills": "./.claude/skills/"}), encoding="utf-8"
        )
        self.assertEqual({s["name"] for s in fos.collect(home)}, {"p:one", "p:two"})
        (root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "p", "skills": ["./.claude/skills/two"]}),
            encoding="utf-8",
        )
        self.assertEqual({s["name"] for s in fos.collect(home)}, {"p:two"})

    def test_text_output_names_the_source(self):
        out = _run_main(self.home, "text")
        self.assertIn("[installed · routing text] alpha", out)
        self.assertIn("[AVAILABLE (not installed) · catalogue text] beta", out)


class FrontmatterTest(unittest.TestCase):
    def test_scalar_styles(self):
        cases = {
            'description: "Use when \\"quoted\\" x"': 'Use when "quoted" x',
            "description: 'Use when single'": "Use when single",
            "description: Use when plain  # comment": "Use when plain",
            "description: >-\n  Use when folded\n  across lines": "Use when folded across lines",
            "description: |\n  Use when literal\n  second": "Use when literal\nsecond",
        }
        for raw, want in cases.items():
            text = f"---\nname: t\n{raw}\nmetadata:\n  author: a\n---\n# T\n"
            self.assertEqual(fos._frontmatter(text)["description"], want, raw)
            self.assertEqual(fos._frontmatter(text)["name"], "t", raw)

    def test_no_frontmatter(self):
        self.assertEqual(fos._frontmatter("# just a title\n"), {})


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
