#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Unit tests for skills/retro/scripts/check-decision-records.py."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = REPO_ROOT / "skills" / "retro" / "scripts" / "check-decision-records.py"
    spec = importlib.util.spec_from_file_location("check_decision_records", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cdr = _load()

# The field layout of the ADRs in netresearch/agent-harness-skill and
# netresearch/coding_agent_cli_toolset: bold fields, no frontmatter, no anchors.
REAL_FORMAT_ADR = """# ADR-001: Verify-First Design

**Status:** Accepted
**Date:** 2026-03-22
**Context:** The skill could be a generator or a verifier.
**Decision:** The skill is primarily a verifier.
"""


class Repo:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def write(self, rel: str, text: str = "") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def report(self, changed=()):
        return cdr.build_report(self.root, list(changed))

    def close(self):
        self._tmp.cleanup()


def signals(report):
    return [f["signal"] for f in report["findings"]]


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_missing_agents_md_is_undefined(self):
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "undefined")
        self.assertEqual(signals(r), ["E7"])

    def test_agents_md_without_a_declaration_is_undefined(self):
        self.repo.write("AGENTS.md", "# Project\n\n## Commands\n\n- make test\n")
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "undefined")
        self.assertEqual(signals(r), ["E7"])

    def test_no_with_a_named_place_passes(self):
        self.repo.write(
            "AGENTS.md",
            "## Key Decisions\n\n- **ADRs:** no — decisions are recorded in the PR description\n",
        )
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "no")
        self.assertEqual(
            r["policy"]["alternative"], "decisions are recorded in the PR description"
        )
        self.assertEqual(r["findings"], [])

    def test_bare_no_is_inconsistent(self):
        self.repo.write("AGENTS.md", "ADRs: no\n")
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "inconsistent")
        self.assertEqual(signals(r), ["E7"])

    def test_yes_with_directory_and_its_agents_md_passes(self):
        self.repo.write("AGENTS.md", "## Decision records\n\nADRs: yes — `docs/adr/`\n")
        self.repo.write("docs/adr/AGENTS.md", "# How we write ADRs\n")
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "yes")
        self.assertEqual(r["policy"]["adr_dir"], "docs/adr/")
        self.assertEqual(r["findings"], [])

    def test_yes_with_missing_directory_is_inconsistent(self):
        self.repo.write("AGENTS.md", "**ADRs:** yes — `docs/adr/`\n")
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "inconsistent")
        self.assertIn("does not exist", r["policy"]["problems"][0])

    def test_yes_without_the_directory_agents_md_is_inconsistent(self):
        self.repo.write("AGENTS.md", "ADRs: yes — docs/adr\n")
        self.repo.write("docs/adr/ADR-001.md", REAL_FORMAT_ADR)
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "inconsistent")
        self.assertIn("no AGENTS.md of its own", r["policy"]["problems"][0])

    def test_contradicting_lines_are_inconsistent(self):
        self.repo.write("AGENTS.md", "ADRs: yes — `docs/adr/`\n\nADRs: no — none\n")
        self.repo.write("docs/adr/AGENTS.md", "x\n")
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "inconsistent")

    def test_two_yes_lines_naming_different_directories_are_inconsistent(self):
        self.repo.write(
            "AGENTS.md", "**ADRs:** yes — `docs/adr/`\n\n**ADRs:** yes — `decisions/`\n"
        )
        self.repo.write("docs/adr/AGENTS.md", "x\n")
        self.repo.write("decisions/AGENTS.md", "x\n")
        self.assertEqual(self.repo.report()["policy"]["status"], "inconsistent")

    def test_markdown_link_names_the_directory(self):
        self.repo.write("AGENTS.md", "- **ADRs:** yes — [docs/adr/](docs/adr/)\n")
        self.repo.write("docs/adr/AGENTS.md", "x\n")
        r = self.repo.report()
        self.assertEqual(
            (r["policy"]["status"], r["policy"]["adr_dir"]), ("yes", "docs/adr/")
        )

    def test_declaration_inside_a_code_fence_is_an_example(self):
        self.repo.write(
            "AGENTS.md",
            "## Example\n\n```markdown\n**ADRs:** no — PR descriptions\n```\n",
        )
        self.assertEqual(self.repo.report()["policy"]["status"], "undefined")

    def test_leading_slash_in_the_declared_directory_means_the_root(self):
        self.repo.write("AGENTS.md", "ADRs: yes — `/docs/adr/`\n")
        self.repo.write("docs/adr/AGENTS.md", "x\n")
        r = self.repo.report()
        self.assertEqual(
            (r["policy"]["status"], r["policy"]["adr_dir"]), ("yes", "docs/adr/")
        )

    def test_fence_with_info_string_does_not_close_a_fence(self):
        self.repo.write(
            "AGENTS.md",
            "## Example\n\n~~~text\n~~~example\nADRs: no — PR descriptions\n~~~\n",
        )
        self.assertEqual(self.repo.report()["policy"]["status"], "undefined")

    def test_german_answer_is_read(self):
        self.repo.write(
            "AGENTS.md", "- ADRs: nein — Entscheidungen stehen in der PR-Beschreibung\n"
        )
        self.assertEqual(self.repo.report()["policy"]["status"], "no")


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write(
            "AGENTS.md", "## Key Decisions\n\n**ADRs:** yes — `docs/adr/`\n"
        )
        self.repo.write("docs/adr/AGENTS.md", "# How we write ADRs\n")
        self.repo.write("docs/adr/README.md", "# Index\n")

    def tearDown(self):
        self.repo.close()

    def test_real_format_record_is_unanchored_not_an_error(self):
        self.repo.write("docs/adr/ADR-001-verify-first.md", REAL_FORMAT_ADR)
        r = self.repo.report()
        self.assertEqual(r["summary"]["adr_records"], 1)
        self.assertEqual(r["summary"]["unanchored_adr_records"], 1)
        rec = r["records"][0]
        self.assertEqual(rec["status"], "Accepted")
        self.assertEqual(rec["title"], "ADR-001: Verify-First Design")
        self.assertTrue(rec["active"])
        self.assertEqual(r["findings"], [])

    def test_index_and_agents_files_are_not_records(self):
        r = self.repo.report()
        self.assertEqual(r["summary"]["adr_records"], 0)

    def test_missing_anchor_of_an_active_record_is_e8(self):
        self.repo.write("config/retry.yaml", "max: 4\n")
        self.repo.write(
            "docs/adr/ADR-002-retries.md",
            REAL_FORMAT_ADR.replace(
                "**Date:**", "**Touches:** `src/retry.py`, `config/`\n**Date:**"
            ),
        )
        r = self.repo.report()
        e8 = [f for f in r["findings"] if f["signal"] == "E8"]
        self.assertEqual(len(e8), 1)
        self.assertEqual(e8[0]["missing"], ["src/retry.py"])
        self.assertEqual(e8[0]["record"], "docs/adr/ADR-002-retries.md")

    def test_superseded_record_is_neither_stale_nor_crossed(self):
        self.repo.write(
            "docs/adr/ADR-003-old.md",
            "# ADR-003\n\n**Status:** Superseded by ADR-004\n**Touches:** `gone.py`, `config/`\n",
        )
        self.repo.write("config/retry.yaml", "max: 4\n")
        r = self.repo.report(changed=["config/retry.yaml"])
        self.assertFalse(r["records"][0]["active"])
        self.assertEqual(r["findings"], [])

    def test_frontmatter_touches_and_symbol_suffix(self):
        self.repo.write("src/client.go", "const defaultRetryMax = 4\n")
        self.repo.write(
            "docs/adr/0005-retry-max.md",
            "---\nstatus: accepted\ntouches:\n  - src/client.go#defaultRetryMax\n  - src/gone.go\n---\n\n# Keep retries at 4\n",
        )
        r = self.repo.report(changed=["src/client.go"])
        rec = r["records"][0]
        self.assertEqual(
            rec["touches"], ["src/client.go#defaultRetryMax", "src/gone.go"]
        )
        self.assertEqual(rec["missing"], ["src/gone.go"])
        self.assertEqual(sorted(signals(r)), ["E1", "E8"])

    def test_changed_file_under_a_directory_anchor_is_a_candidate(self):
        self.repo.write("config/retry.yaml", "max: 4\n")
        self.repo.write(
            "docs/adr/ADR-002.md",
            "# ADR-002: Retries\n\n**Status:** Accepted\n**Touches:** `config/`\n",
        )
        r = self.repo.report(
            changed=["config/retry.yaml", "README.md", "configuration.md"]
        )
        e1 = [f for f in r["findings"] if f["signal"] == "E1"]
        self.assertEqual([f["file"] for f in e1], ["config/retry.yaml"])
        self.assertTrue(e1[0]["candidate"])
        self.assertEqual(e1[0]["records"][0]["title"], "ADR-002: Retries")

    def test_bold_markers_inside_code_spans_are_kept(self):
        self.repo.write("src/pkg/__init__.py", "")
        self.repo.write("src/pkg/sub/mod.py", "")
        self.repo.write(
            "docs/adr/ADR-007.md",
            "# ADR-007\n\n**Status:** Accepted\n**Touches:** `src/pkg/__init__.py`, `src/**/*.py`\n",
        )
        r = self.repo.report(
            changed=["src/pkg/__init__.py", "src/pkg/sub/mod.py", "README.md"]
        )
        self.assertEqual(
            r["records"][0]["touches"], ["src/pkg/__init__.py", "src/**/*.py"]
        )
        self.assertEqual(r["records"][0]["missing"], [])
        self.assertEqual(
            [h["file"] for h in r["changed_hits"]],
            ["src/pkg/__init__.py", "src/pkg/sub/mod.py"],
        )

    def test_single_star_stays_within_one_directory_for_e1_and_e8(self):
        self.repo.write("docs/sub/deep.md", "")
        self.repo.write(
            "docs/adr/ADR-008.md",
            "# ADR-008\n\n**Status:** Accepted\n**Touches:** `docs/*.md`\n",
        )
        r = self.repo.report(changed=["docs/sub/deep.md", "docs/top.md"])
        self.assertEqual(r["records"][0]["missing"], ["docs/*.md"])
        self.assertEqual([h["file"] for h in r["changed_hits"]], ["docs/top.md"])

    def test_leading_slash_means_the_repository_root(self):
        self.repo.write("src/a.py", "")
        self.repo.write(
            "docs/adr/ADR-009.md",
            "# ADR-009\n\n**Status:** Accepted\n**Touches:** `/src/*.py`, `/src/a.py`\n",
        )
        r = self.repo.report(changed=["src/a.py"])
        self.assertEqual(r["records"][0]["missing"], [])
        self.assertEqual(len(r["changed_hits"]), 1)

    def test_proposed_record_does_not_bind(self):
        self.repo.write(
            "docs/adr/ADR-010.md",
            "# ADR-010\n\n**Status:** Proposed\n**Touches:** `gone.py`, `src/`\n",
        )
        r = self.repo.report(changed=["src/x.py"])
        self.assertFalse(r["records"][0]["active"])
        self.assertEqual(r["findings"], [])

    def test_route_file_with_brackets_is_a_literal_path(self):
        self.repo.write("app/[slug]/page.tsx", "")
        self.repo.write(
            "docs/adr/ADR-012.md",
            "# ADR-012\n\n**Status:** Accepted\n**Touches:** `app/[slug]/page.tsx`\n",
        )
        r = self.repo.report(changed=["app/[slug]/page.tsx"])
        self.assertEqual(r["records"][0]["missing"], [])
        self.assertEqual(len(r["changed_hits"]), 1)

    def test_glob_naming_a_directory_covers_the_files_below(self):
        self.repo.write("packages/a/config/x.yml", "")
        self.repo.write(
            "docs/adr/ADR-013.md",
            "# ADR-013\n\n**Status:** Accepted\n**Touches:** `packages/*/config/`\n",
        )
        r = self.repo.report(changed=["packages/a/config/x.yml", "packages/a/src/y.py"])
        self.assertEqual(
            [h["file"] for h in r["changed_hits"]], ["packages/a/config/x.yml"]
        )
        self.assertEqual(r["records"][0]["missing"], [])

    def test_double_star_inside_a_segment_does_not_crash(self):
        self.repo.write("src/a.py", "")
        self.repo.write(
            "docs/adr/ADR-014.md",
            "# ADR-014\n\n**Status:** Accepted\n**Touches:** `src/**.py`\n",
        )
        r = self.repo.report(changed=["src/a.py"])
        self.assertEqual(r["records"][0]["missing"], [])
        self.assertEqual(len(r["changed_hits"]), 1)

    def test_status_heading_of_adr_tools_is_read(self):
        self.repo.write(
            "docs/adr/0003-old.md",
            "# 3. Old choice\n\n## Status\n\nSuperseded by 0004\n\n**Touches:** `gone.py`, `src/`\n",
        )
        r = self.repo.report(changed=["src/x.py"])
        self.assertEqual(r["records"][0]["status"], "Superseded by 0004")
        self.assertEqual(r["findings"], [])

    def test_paths_without_backticks_keep_their_underscores_and_stars(self):
        self.repo.write("src/pkg/__init__.py", "")
        self.repo.write(
            "docs/adr/ADR-015.md",
            "# ADR-015\n\n**Status:** Accepted\n**Touches:** src/pkg/__init__.py, src/**/*.py\n",
        )
        r = self.repo.report()
        self.assertEqual(
            r["records"][0]["touches"], ["src/pkg/__init__.py", "src/**/*.py"]
        )
        self.assertEqual(r["records"][0]["missing"], [])

    def test_yaml_comment_is_not_an_anchor(self):
        self.repo.write("src/a.py", "")
        self.repo.write(
            "docs/adr/0016.md",
            "---\nstatus: accepted\ntouches:\n  - src/a.py  # retry loop\n---\n# Retry\n",
        )
        self.assertEqual(self.repo.report()["records"][0]["touches"], ["src/a.py"])

    def test_absolute_changed_paths_are_made_relative(self):
        self.repo.write("src/a.py", "")
        self.repo.write(
            "docs/adr/ADR-017.md",
            "# ADR-017\n\n**Status:** Accepted\n**Touches:** `src/a.py`\n",
        )
        r = self.repo.report(
            changed=[str(self.repo.root / "src/a.py"), "/elsewhere/b.py"]
        )
        self.assertEqual([h["file"] for h in r["changed_hits"]], ["src/a.py"])
        self.assertEqual(r["ignored_changed_files"], ["/elsewhere/b.py"])

    def test_touches_as_a_list_or_wrapped_line_in_the_body(self):
        self.repo.write("src/retry.py", "")
        self.repo.write(
            "docs/adr/ADR-018.md",
            "# ADR-018\n\n**Status:** Accepted\n**Touches:**\n- `src/retry.py`\n- `src/gone.py`\n\n## Context\n",
        )
        self.repo.write(
            "docs/adr/ADR-019.md",
            "# ADR-019\n\n**Status:** Accepted\n**Touches:** `src/retry.py`,\n  `src/gone2.py`\n**Date:** 2026-11-22\n",
        )
        recs = {r["path"]: r for r in self.repo.report()["records"]}
        self.assertEqual(recs["docs/adr/ADR-018.md"]["missing"], ["src/gone.py"])
        self.assertEqual(
            recs["docs/adr/ADR-019.md"]["touches"], ["src/retry.py", "src/gone2.py"]
        )

    def test_unindented_frontmatter_list(self):
        self.repo.write("src/retry.py", "")
        self.repo.write(
            "docs/adr/0020.md",
            "---\nstatus: accepted\ntouches:\n- src/retry.py\n- src/gone.py\n---\n# Retry\n",
        )
        self.assertEqual(self.repo.report()["records"][0]["missing"], ["src/gone.py"])

    def test_madr_template_is_not_a_record(self):
        self.repo.write(
            "docs/adr/adr-template.md",
            '---\nstatus: "{proposed | accepted}"\ntouches:\n  - path/to/file\n---\n',
        )
        self.assertEqual(self.repo.report()["records"], [])

    def test_german_superseded_status_does_not_bind(self):
        self.repo.write(
            "docs/adr/ADR-021.md",
            "# ADR-021\n\n**Status:** Abgelöst durch ADR-022\n**Touches:** `config/`\n",
        )
        r = self.repo.report(changed=["config/retry.yaml"])
        self.assertEqual(r["findings"], [])

    def test_rules_in_a_nested_agents_md_are_checked(self):
        self.repo.write(
            "src/AGENTS.md",
            "## Retry rule\n\nKeep 4.\n**Touches:** `src/gone.py`, `config/retry.yaml`\n",
        )
        self.repo.write("config/retry.yaml", "")
        r = self.repo.report(changed=["config/retry.yaml"])
        rule = next(x for x in r["records"] if x["kind"] == "rule")
        self.assertEqual(
            (rule["path"], rule["missing"]), ("src/AGENTS.md", ["src/gone.py"])
        )
        self.assertEqual(len(r["changed_hits"]), 1)

    def test_list_items_after_a_filled_touches_field_are_not_anchors(self):
        self.repo.write("src/a.py", "")
        self.repo.write(
            "docs/adr/0001-madr.md",
            "# Use X\n\n* Status: accepted\n* Touches: `src/a.py`\n* Deciders: Alice, Bob\n* Date: 2026-01-01\n",
        )
        self.repo.write(
            "docs/adr/ADR-022.md",
            "# ADR-022\n\n- **Touches:** `src/a.py`\n- **Status:** Superseded by ADR-023\n",
        )
        self.repo.write(
            "src/AGENTS.md",
            "## Retries\n\n**Touches:** `src/a.py`\n- Always retry three times\n- Never retry on 4xx\n",
        )
        recs = {(r["path"], r["title"]): r for r in self.repo.report()["records"]}
        self.assertEqual(
            recs[("docs/adr/0001-madr.md", "Use X")]["touches"], ["src/a.py"]
        )
        self.assertEqual(recs[("docs/adr/0001-madr.md", "Use X")]["status"], "accepted")
        self.assertFalse(recs[("docs/adr/ADR-022.md", "ADR-022")]["active"])
        self.assertEqual(recs[("src/AGENTS.md", "Retries")]["touches"], ["src/a.py"])
        self.assertEqual(self.repo.report()["findings"], [])

    def test_formatted_touches_list_with_blank_lines_and_numbers(self):
        self.repo.write("src/a.py", "")
        self.repo.write(
            "docs/adr/ADR-024.md",
            "# ADR-024\n\n**Status:** Accepted\n**Touches:**\n\n- `src/a.py`\n\n- `src/gone.py`\n\nProse after the list.\n",
        )
        self.repo.write(
            "docs/adr/ADR-025.md",
            "# ADR-025\n\n**Status:** Accepted\n**Touches:**\n1. src/a.py\n2. src/gone.py\n",
        )
        recs = {r["path"]: r for r in self.repo.report()["records"]}
        self.assertEqual(
            recs["docs/adr/ADR-024.md"]["touches"], ["src/a.py", "src/gone.py"]
        )
        self.assertEqual(
            recs["docs/adr/ADR-025.md"]["touches"], ["src/a.py", "src/gone.py"]
        )

    def test_repository_root_anchor_covers_every_change(self):
        self.repo.write(
            "docs/adr/ADR-026.md",
            "# ADR-026\n\n**Status:** Accepted\n**Touches:** `.`, `./`\n",
        )
        r = self.repo.report(changed=["src/client.py"])
        self.assertEqual(r["records"][0]["missing"], [])
        self.assertEqual(len(r["changed_hits"]), 1)

    def test_absolute_glob_anchor_is_read_from_the_root(self):
        self.repo.write("tmp/a.py", "")
        self.repo.write(
            "docs/adr/ADR-027.md",
            "# ADR-027\n\n**Status:** Accepted\n**Touches:** `/tmp/*.py`\n",
        )
        r = self.repo.report(changed=["tmp/a.py"])
        self.assertEqual(r["records"][0]["missing"], [])
        self.assertEqual(len(r["changed_hits"]), 1)

    def test_literal_route_anchor_is_not_a_glob_for_changes(self):
        self.repo.write("app/[slug]/page.tsx", "")
        self.repo.write(
            "docs/adr/ADR-028.md",
            "# ADR-028\n\n**Status:** Accepted\n**Touches:** `app/[slug]/page.tsx`\n",
        )
        r = self.repo.report(changed=["app/s/page.tsx", "app/[slug]/page.tsx"])
        self.assertEqual(
            [h["file"] for h in r["changed_hits"]], ["app/[slug]/page.tsx"]
        )

    def test_unbalanced_bracket_glob_does_not_crash(self):
        self.repo.write(
            "docs/adr/ADR-029.md",
            "# ADR-029\n\n**Status:** Accepted\n**Touches:** `app/[[]slug[]]/page.tsx`\n",
        )
        r = self.repo.report(changed=["app/x/page.tsx"])
        self.assertEqual(r["changed_hits"], [])

    def test_git_quoted_changed_path_is_decoded(self):
        self.repo.write("src/über.py", "")
        self.repo.write(
            "docs/adr/ADR-030.md",
            "# ADR-030\n\n**Status:** Accepted\n**Touches:** `src/über.py`\n",
        )
        r = self.repo.report(changed=['"src/\\303\\274ber.py"'])
        self.assertEqual([h["file"] for h in r["changed_hits"]], ["src/über.py"])

    def test_quoted_path_with_raw_utf8_is_kept(self):
        self.repo.write("docs/日本.md", "")
        self.repo.write(
            "docs/adr/ADR-031.md",
            "# ADR-031\n\n**Status:** Accepted\n**Touches:** `docs/`\n",
        )
        r = self.repo.report(changed=['"docs/日本.md"'])
        self.assertEqual([h["file"] for h in r["changed_hits"]], ["docs/日本.md"])

    def test_glob_anchor(self):
        self.repo.write("src/a_test.py", "")
        self.repo.write(
            "docs/adr/ADR-006.md",
            "# ADR-006\n\n**Status:** Accepted\n**Touches:** `src/*_test.py`\n",
        )
        r = self.repo.report(changed=["src/a_test.py", "src/a.py"])
        self.assertEqual([h["file"] for h in r["changed_hits"]], ["src/a_test.py"])
        self.assertEqual(r["records"][0]["missing"], [])


class ConfinementTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_adr_directory_outside_the_repository_is_inconsistent(self):
        self.repo.write("AGENTS.md", "ADRs: yes — `../elsewhere/`\n")
        r = self.repo.report()
        self.assertEqual(r["policy"]["status"], "inconsistent")
        self.assertIn("outside the repository", r["policy"]["problems"][0])
        self.assertEqual(r["records"], [])

    def test_anchor_outside_the_repository_counts_as_gone(self):
        outside = self.repo.root.parent / "check-decision-records-outside.txt"
        outside.write_text("x", encoding="utf-8")
        self.addCleanup(outside.unlink)
        self.repo.write(
            "AGENTS.md",
            "ADRs: no — PR descriptions\n\n## A rule\n\n**Touches:** `../check-decision-records-outside.txt`, `../*.txt`\n",
        )
        r = self.repo.report()
        self.assertEqual(
            r["records"][0]["missing"],
            ["../check-decision-records-outside.txt", "../*.txt"],
        )

    def test_dotfile_anchor_keeps_its_leading_dot(self):
        self.repo.write(".github/workflows/ci.yml", "on: push\n")
        self.repo.write(
            "AGENTS.md",
            "ADRs: no — PR descriptions\n\n## CI\n\n**Touches:** `.github/workflows/ci.yml`, `./.github/`\n",
        )
        r = self.repo.report(
            changed=[".github/workflows/ci.yml", "github/workflows/ci.yml"]
        )
        self.assertEqual(r["records"][0]["missing"], [])
        self.assertEqual(
            [h["file"] for h in r["changed_hits"]], [".github/workflows/ci.yml"]
        )

    def test_symlinks_out_of_the_repository_are_not_followed(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        (outside / "secret.md").write_text(
            "# SECRET TITLE\n\n**Status:** Accepted\n", encoding="utf-8"
        )
        (outside / "f.txt").write_text("x", encoding="utf-8")
        self.repo.write(
            "AGENTS.md",
            "**ADRs:** yes — `docs/adr/`\n\n## Rule\n\n**Touches:** `lnk/*.txt`, `lnk/f.txt`\n",
        )
        self.repo.write("docs/adr/AGENTS.md", "x\n")
        (self.repo.root / "docs/adr/ADR-011.md").symlink_to(outside / "secret.md")
        (self.repo.root / "lnk").symlink_to(outside, target_is_directory=True)
        r = self.repo.report()
        self.assertNotIn("SECRET TITLE", json.dumps(r))
        self.assertEqual(r["records"][0]["missing"], ["lnk/*.txt", "lnk/f.txt"])

    def test_rule_example_in_a_code_fence_is_not_a_record(self):
        self.repo.write(
            "AGENTS.md",
            "ADRs: no — PR descriptions\n\n## Form\n\n```markdown\n## <title>\n\n**Touches:** `src/retry.py`\n```\n",
        )
        self.assertEqual(self.repo.report()["records"], [])

    def test_long_separator_run_is_read_in_linear_time(self):
        self.repo.write("AGENTS.md", "ADRs: no " + "-" * 50000 + " PR descriptions\n")
        self.assertEqual(self.repo.report()["policy"]["alternative"], "PR descriptions")


class RuleAnchorTest(unittest.TestCase):
    def test_agents_md_rule_with_touches_is_a_record(self):
        repo = Repo()
        try:
            repo.write(
                "AGENTS.md",
                "**ADRs:** no — decisions are recorded in the PR description\n\n"
                "## Keep the report summary short\n\nThe on-call page reads per-host errors.\n"
                "**Touches:** `after/report.py`, `docs/operations/on-call.md`\n",
            )
            repo.write("after/report.py", "")
            r = repo.report(changed=["after/report.py"])
            self.assertEqual(r["records"][0]["kind"], "rule")
            self.assertEqual(r["records"][0]["missing"], ["docs/operations/on-call.md"])
            self.assertEqual(sorted(signals(r)), ["E1", "E8"])
        finally:
            repo.close()


class CliTest(unittest.TestCase):
    def test_json_output_and_changed_files_from(self):
        repo = Repo()
        try:
            repo.write("AGENTS.md", "ADRs: no — PR descriptions\n")
            lst = repo.write("changed.txt", "a.py\n\nb.py\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cdr.main(
                    ["--repo", str(repo.root), "--changed-files-from", str(lst)]
                )
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue())
            self.assertEqual(out["summary"]["changed_files"], 2)
            self.assertEqual(out["policy"]["status"], "no")
        finally:
            repo.close()

    def test_missing_repository_is_a_usage_error(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(
                cdr.main(["--repo", "/nonexistent/check-decision-records"]), 2
            )
        self.assertIn("not a directory", err.getvalue())


if __name__ == "__main__":
    unittest.main()
