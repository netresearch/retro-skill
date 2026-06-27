#!/usr/bin/env python3
"""Unit tests for skills/retro/scripts/scan-memory-inventory.py (the /retro promote front-end)."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = REPO_ROOT / "skills" / "retro" / "scripts" / "scan-memory-inventory.py"
    spec = importlib.util.spec_from_file_location("scan_memory_inventory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smi = _load()

FEEDBACK = """---
name: feedback-german-number-formatting
description: "For German output use a period as thousand separator (8.008)."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 9d74b3aa-07df-4f72-aa2f-964c8670c122
---

In German prose, format thousands with a period: `8.008`, `1.273`.

**Why:** The user flagged "8 008" as visually wrong — they expect the period style (ä ö ü ß).

**How to apply:** Whenever emitting German numbers, use the period separator.
"""


def _make_root(slug: str = "-home-sme") -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp())
    memory = root / slug / "memory"
    memory.mkdir(parents=True)
    return root, memory


def _write(memory: Path, name: str, content: str) -> Path:
    path = memory / name
    path.write_text(content, encoding="utf-8")
    return path


def _run_scan(**kwargs) -> dict:
    args = smi.argparse.Namespace(
        command=None,
        project=kwargs.get("project"),
        memory_root=kwargs["memory_root"],
        include_flagged_locations=kwargs.get("include_flagged_locations", False),
        project_dir=kwargs.get("project_dir"),
        output_format=kwargs.get("output_format", "json"),
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = smi.cmd_scan(args)
    out = buf.getvalue()
    return {
        "rc": rc,
        "json": json.loads(out) if args.output_format == "json" else out,
        "raw": out,
    }


def _run_drain(path: Path, memory_root: Path, expect_sha256: str | None = None) -> dict:
    args = smi.argparse.Namespace(
        command="drain", path=path, memory_root=memory_root, expect_sha256=expect_sha256
    )
    buf = io.StringIO()
    err = io.StringIO()
    real_err = sys.stderr
    sys.stderr = err
    try:
        with redirect_stdout(buf):
            rc = smi.cmd_drain(args)
    finally:
        sys.stderr = real_err
    return {"rc": rc, "stdout": buf.getvalue(), "stderr": err.getvalue()}


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.root, self.memory = _make_root()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_feedback_file_emits_finding(self):
        _write(self.memory, "feedback_x.md", FEEDBACK)
        res = _run_scan(memory_root=self.root)
        self.assertTrue(res["json"]["available"])
        self.assertEqual(res["json"]["findings_total"], 1)
        f = res["json"]["findings"][0]
        self.assertEqual(f["signal"], "C3")
        self.assertEqual(f["name"], "memory_drift")
        self.assertTrue(f["content_sha256"])
        self.assertIn("period", f["why"])
        self.assertIn("German numbers", f["how_to_apply"])
        self.assertEqual(f["origin_session_id"], "9d74b3aa-07df-4f72-aa2f-964c8670c122")
        self.assertEqual(f["current_location"], "project-local-memory")

    def test_memory_md_index_not_a_finding(self):
        _write(self.memory, "MEMORY.md", "- [x](feedback_x.md) — hook\n")
        _write(self.memory, "feedback_x.md", FEEDBACK)
        res = _run_scan(memory_root=self.root)
        self.assertEqual(res["json"]["findings_total"], 1)
        sources = [Path(f["source_path"]).name for f in res["json"]["findings"]]
        self.assertNotIn("MEMORY.md", sources)

    def test_tombstoned_file_skipped(self):
        _write(self.memory, "feedback_x.md", FEEDBACK)
        promoted = self.memory / ".promoted"
        promoted.mkdir()
        (promoted / "feedback_old.md").write_text(FEEDBACK, encoding="utf-8")
        res = _run_scan(memory_root=self.root)
        self.assertEqual(res["json"]["findings_total"], 1)

    def test_missing_root_graceful_absence(self):
        res = _run_scan(memory_root=Path(tempfile.gettempdir()) / "does-not-exist-xyz")
        self.assertEqual(res["rc"], 0)
        self.assertFalse(res["json"]["available"])
        self.assertIn("no project-scoped memory", res["json"]["reason"])

    def test_german_umlauts_round_trip(self):
        _write(self.memory, "feedback_x.md", FEEDBACK)
        res = _run_scan(memory_root=self.root)
        self.assertIn("ä ö ü ß", res["raw"])  # ensure_ascii=False kept umlauts verbatim

    def test_flagged_location_emits_b8(self):
        project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        (project / "CLAUDE.md").write_text(
            "# Local rules\n\nUse bun not npm.\n\n**Why:** team uses bun.\n",
            encoding="utf-8",
        )
        res = _run_scan(
            memory_root=self.root,
            project_dir=str(project),
            include_flagged_locations=True,
        )
        b8 = [f for f in res["json"]["findings"] if f["signal"] == "B8"]
        self.assertEqual(len(b8), 1)
        self.assertEqual(b8[0]["name"], "wrong_destination_materialization")
        self.assertEqual(b8[0]["which_wrong_file"], "project-CLAUDE.md")

    def test_scans_all_slugs_by_default(self):
        other = self.root / "-home-sme-p-other" / "memory"
        other.mkdir(parents=True)
        _write(self.memory, "feedback_a.md", FEEDBACK)
        _write(other, "feedback_b.md", FEEDBACK)
        res = _run_scan(memory_root=self.root)
        self.assertEqual(res["json"]["findings_total"], 2)
        self.assertEqual(len(res["json"]["slugs_scanned"]), 2)

    def test_project_narrows_to_one_slug(self):
        other = self.root / "-home-sme-p-other" / "memory"
        other.mkdir(parents=True)
        _write(self.memory, "feedback_a.md", FEEDBACK)
        _write(other, "feedback_b.md", FEEDBACK)
        res = _run_scan(memory_root=self.root, project="-home-sme")
        self.assertEqual(res["json"]["findings_total"], 1)
        self.assertEqual(len(res["json"]["slugs_scanned"]), 1)

    def test_text_output(self):
        _write(self.memory, "feedback_x.md", FEEDBACK)
        res = _run_scan(memory_root=self.root, output_format="text")
        self.assertIn("[C3]", res["raw"])
        self.assertIn("-home-sme", res["raw"])

    def test_bare_prose_file_no_frontmatter(self):
        _write(
            self.memory,
            "feedback_bare.md",
            "Just a note, no frontmatter, no markers.\n",
        )
        res = _run_scan(memory_root=self.root)
        f = res["json"]["findings"][0]
        self.assertEqual(f["title"], "feedback_bare")  # falls back to stem
        self.assertEqual(f["why"], "")
        self.assertEqual(f["how_to_apply"], "")

    def test_unterminated_frontmatter_treated_as_none(self):
        # opening '---' but no closing fence -> parsed as having no frontmatter
        _write(self.memory, "feedback_bad.md", "---\nname: x\nno closing fence here\n")
        res = _run_scan(memory_root=self.root)
        f = res["json"]["findings"][0]
        self.assertEqual(f["title"], "feedback_bad")  # frontmatter ignored -> stem


class DrainTest(unittest.TestCase):
    def setUp(self):
        self.root, self.memory = _make_root()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_drain_refuses_path_outside_store(self):
        stray = self.root / "stray.md"
        stray.write_text(FEEDBACK, encoding="utf-8")
        res = _run_drain(stray, self.root)
        self.assertEqual(res["rc"], 2)
        self.assertIn("is not inside", res["stderr"])

    def test_drain_refuses_memory_dir_outside_root(self):
        # parent IS named 'memory', but it is not under the given --memory-root
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        rogue = other / "slug" / "memory"
        rogue.mkdir(parents=True)
        victim = rogue / "feedback_x.md"
        victim.write_text(FEEDBACK, encoding="utf-8")
        res = _run_drain(victim, self.root)  # memory-root is self.root, not `other`
        self.assertEqual(res["rc"], 2)
        self.assertTrue(victim.is_file())  # untouched

    def test_drain_does_not_clobber_existing_tombstone(self):
        promoted = self.memory / ".promoted"
        promoted.mkdir()
        (promoted / "feedback_x.md").write_text("OLD TOMBSTONE", encoding="utf-8")
        path = _write(self.memory, "feedback_x.md", "NEW LIVE CONTENT")
        res = _run_drain(path, self.root)
        self.assertEqual(res["rc"], 0)
        self.assertEqual(
            (promoted / "feedback_x.md").read_text(encoding="utf-8"), "OLD TOMBSTONE"
        )
        # the new content was tombstoned under a disambiguated name, not lost
        survivors = [p.read_text(encoding="utf-8") for p in promoted.glob("*.md")]
        self.assertIn("NEW LIVE CONTENT", survivors)
        self.assertIn("OLD TOMBSTONE", survivors)

    def test_drain_prune_is_anchored_to_link_target(self):
        path = _write(self.memory, "feedback_x.md", FEEDBACK)
        _write(
            self.memory,
            "MEMORY.md",
            "- prose mentions (feedback_x.md) but is not a link\n"
            "- [x](feedback_x.md) — the real link\n",
        )
        res = _run_drain(path, self.root)
        self.assertEqual(res["rc"], 0)
        index = (self.memory / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("prose mentions", index)  # unanchored mention kept
        self.assertNotIn("the real link", index)  # only the link line dropped

    def test_drain_refuses_on_sha_mismatch(self):
        path = _write(self.memory, "feedback_x.md", FEEDBACK)
        res = _run_drain(path, self.root, expect_sha256="deadbeef")
        self.assertEqual(res["rc"], 2)
        self.assertIn("changed since scan", res["stderr"])
        self.assertTrue(path.is_file())  # not drained

    def test_drain_tombstones_and_prunes_index(self):
        path = _write(self.memory, "feedback_x.md", FEEDBACK)
        _write(
            self.memory,
            "MEMORY.md",
            "- [keep](other.md) — k\n- [x](feedback_x.md) — hook\n",
        )
        res = _run_drain(path, self.root)
        self.assertEqual(res["rc"], 0)
        self.assertFalse(path.is_file())
        self.assertTrue((self.memory / ".promoted" / "feedback_x.md").is_file())
        index = (self.memory / "MEMORY.md").read_text(encoding="utf-8")
        self.assertNotIn("feedback_x.md", index)
        self.assertIn("other.md", index)


if __name__ == "__main__":
    unittest.main()
