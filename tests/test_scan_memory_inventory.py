#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Unit tests for skills/retro/scripts/scan-memory-inventory.py (the /retro promote front-end)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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
        include_global_rules=kwargs.get("include_global_rules", False),
        global_rules_file=kwargs.get("global_rules_file", Path("/nonexistent")),
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

    def test_pending_state_in_the_index_line_is_flagged(self):
        # The note that prompted this: true on the day it was written, false a
        # day later, and its description - the line MEMORY.md loads into every
        # session - stood unchanged for a week. The flag has to fire on that
        # line specifically, because that is where the damage is.
        _write(
            self.memory,
            "project_blocked.md",
            "---\nname: demo-blocked\n"
            "description: Three things the demo needs sit unreleased on main.\n"
            "metadata:\n  type: project\n---\n\n"
            "Until it is released, the rollout waits.\n",
        )
        f = _run_scan(memory_root=self.root)["json"]["findings"][0]
        self.assertTrue(f["pending_state_in_index"])
        self.assertIn("unreleased", f["pending_state"])
        self.assertIn("until it", f["pending_state"])

    def test_pending_state_only_in_body_is_flagged_but_not_as_index(self):
        # Still worth re-verifying, but it misleads only whoever opens the
        # note, so it must not raise the sharper index flag.
        _write(
            self.memory,
            "project_body.md",
            "---\nname: gap\ndescription: A CLI command lacks an actor option.\n"
            "metadata:\n  type: project\n---\n\nUntil then, use the backend module.\n",
        )
        f = _run_scan(memory_root=self.root)["json"]["findings"][0]
        self.assertEqual(f["pending_state"], ["until then"])
        self.assertFalse(f["pending_state_in_index"])

    def test_mechanism_vocabulary_is_not_a_pending_claim(self):
        # Every line below comes from a real note that the first version of
        # the pattern flagged, and none of them claims that something is open
        # now: a merge state, a resolver rule, a block type, a CHANGELOG
        # heading, a past event, an exit code. `blocked`/`blocks` alone gave
        # about fifteen such hits and not one pending claim.
        for line in (
            "The merge gate refuses whenever mergeState=BLOCKED.",
            "4 is ELTS, so composer blocks ^12.",
            "The relaunch is built on content-blocks.",
            "The CHANGELOG [Unreleased] section covers every merged PR.",
            "Emergency hot-deploy of merged-but-unreleased fixes.",
            "Exit 2 is changes pending, exit 1 is an error.",
        ):
            with self.subTest(line=line):
                _write(
                    self.memory,
                    "reference_x.md",
                    "---\nname: x\ndescription: A mechanism.\n"
                    f"metadata:\n  type: reference\n---\n\n{line}\n",
                )
                f = _run_scan(memory_root=self.root)["json"]["findings"][0]
                self.assertEqual(f["pending_state"], [])

    def test_german_state_words_are_pending_claims(self):
        # 125 of 335 notes on the measured store are German, and the first
        # pattern saw none of them. These two lines are from real project
        # notes whose state was genuinely open.
        for line, phrase in (
            ("Pipeline grün, Merge noch nicht freigegeben.", "noch nicht"),
            ("Entfernen steht aus (Prod-Eingriff, Freigabe offen).", "steht aus"),
        ):
            with self.subTest(line=line):
                _write(
                    self.memory,
                    "project_x.md",
                    "---\nname: x\ndescription: Stand der Initiative.\n"
                    f"metadata:\n  type: project\n---\n\n{line}\n",
                )
                f = _run_scan(memory_root=self.root)["json"]["findings"][0]
                self.assertIn(phrase, f["pending_state"])

    def test_feedback_note_is_not_examined_for_pending_state(self):
        # A rule speaks in conditionals, and "still open" inside a rule is not a
        # claim that something is open now. Feedback notes carried most of the
        # noise in both languages.
        _write(
            self.memory,
            "feedback_y.md",
            "---\nname: y\ndescription: A PR that is still open is not merged.\n"
            "metadata:\n  type: feedback\n---\n\nNot yet merged means not shipped.\n",
        )
        f = _run_scan(memory_root=self.root)["json"]["findings"][0]
        self.assertEqual(f["pending_state"], [])
        self.assertFalse(f["pending_state_in_index"])

    def test_settled_note_carries_no_pending_state(self):
        # Guards precision: an ordinary lesson must not be flagged, or the
        # re-verify list becomes the whole store and is ignored.
        _write(self.memory, "feedback_x.md", FEEDBACK)
        f = _run_scan(memory_root=self.root)["json"]["findings"][0]
        self.assertEqual(f["pending_state"], [])
        self.assertFalse(f["pending_state_in_index"])

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

    def _on_first_move(self, action):
        """Run `action` right before the drain's first rename or replace."""
        real_rename, real_replace, fired = smi.os.rename, smi.os.replace, []

        def wrap(real):
            def move(src, dst):
                if not fired:
                    fired.append(True)
                    action()
                return real(src, dst)

            return move

        return mock.patch.multiple(
            smi.os, rename=wrap(real_rename), replace=wrap(real_replace)
        )

    def test_source_rewritten_during_the_drain_is_not_tombstoned(self):
        path = _write(self.memory, "feedback_x.md", FEEDBACK)
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        with self._on_first_move(
            lambda: path.write_text("REWRITTEN", encoding="utf-8")
        ):
            res = _run_drain(path, self.root, expect_sha256=expected)
        self.assertEqual(res["rc"], 2)
        self.assertIn("changed since scan", res["stderr"])
        self.assertEqual(path.read_text(encoding="utf-8"), "REWRITTEN")
        self.assertEqual(list((self.memory / ".promoted").iterdir()), [])

    def test_tombstone_created_during_the_drain_is_kept(self):
        promoted = self.memory / ".promoted"
        path = _write(self.memory, "feedback_x.md", "NEW LIVE CONTENT")

        def concurrent():
            promoted.mkdir(exist_ok=True)
            (promoted / "feedback_x.md").write_text("CONCURRENT", encoding="utf-8")

        with self._on_first_move(concurrent):
            res = _run_drain(path, self.root)
        self.assertEqual(res["rc"], 0)
        survivors = sorted(p.read_text(encoding="utf-8") for p in promoted.glob("*.md"))
        self.assertEqual(survivors, ["CONCURRENT", "NEW LIVE CONTENT"])
        self.assertEqual([p for p in promoted.iterdir() if p.is_dir()], [])

    def test_without_hard_links_an_existing_tombstone_is_kept(self):
        promoted = self.memory / ".promoted"
        promoted.mkdir()
        (promoted / "feedback_x.md").write_text("OLD TOMBSTONE", encoding="utf-8")
        path = _write(self.memory, "feedback_x.md", "NEW LIVE CONTENT")
        unsupported = OSError(1, "Operation not permitted")
        # `exists()` answering False stands for the name being taken between a
        # check and the move; only an exclusive create notices that.
        with (
            mock.patch.object(smi.os, "link", side_effect=unsupported),
            mock.patch.object(smi.Path, "exists", return_value=False),
        ):
            res = _run_drain(path, self.root)
        self.assertEqual(res["rc"], 0)
        survivors = sorted(p.read_text(encoding="utf-8") for p in promoted.glob("*.md"))
        self.assertEqual(survivors, ["NEW LIVE CONTENT", "OLD TOMBSTONE"])
        self.assertFalse(path.exists())

    def test_index_is_replaced_whole(self):
        """A reader holding MEMORY.md open keeps the complete old index."""
        path = _write(self.memory, "feedback_x.md", FEEDBACK)
        old = "- [keep](other.md) — k\n- [x](feedback_x.md) — hook\n"
        index = _write(self.memory, "MEMORY.md", old)
        index.chmod(0o640)
        with index.open(encoding="utf-8") as reader:
            res = _run_drain(path, self.root)
            self.assertEqual(reader.read(), old)
        self.assertEqual(res["rc"], 0)
        self.assertEqual(index.read_text(encoding="utf-8"), "- [keep](other.md) — k\n")
        self.assertEqual(index.stat().st_mode & 0o777, 0o640)
        self.assertEqual(
            sorted(p.name for p in self.memory.iterdir()), [".promoted", "MEMORY.md"]
        )


class ScanMaskingTest(unittest.TestCase):
    def test_note_text_is_masked(self):
        root, memory = _make_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        token = "glpat-" + "m4" * 12
        _write(
            memory,
            "feedback_token.md",
            FEEDBACK.replace("(8.008).", f"(8.008), token {token}.").replace(
                "use the period separator.", f"export GITLAB_TOKEN={token}"
            ),
        )
        res = _run_scan(memory_root=root)
        finding = res["json"]["findings"][0]
        self.assertNotIn(token, res["raw"])
        self.assertIn("[REDACTED]", finding["description"])
        self.assertIn("[REDACTED]", finding["how_to_apply"])

    def test_frontmatter_values_are_masked(self):
        root, memory = _make_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        token = "glpat-" + "s7" * 12
        _write(
            memory,
            "feedback_token.md",
            FEEDBACK.replace(
                "originSessionId: 9d74b3aa-07df-4f72-aa2f-964c8670c122",
                f"originSessionId: {token}",
            ),
        )
        res = _run_scan(memory_root=root)
        self.assertNotIn(token, res["raw"])
        self.assertEqual(res["json"]["findings"][0]["origin_session_id"], "[REDACTED]")

    def test_frontmatter_keys_are_masked(self):
        """An indented block under `name:` is parsed into a dict; its keys
        are note text too."""
        root, memory = _make_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        token = "glpat-" + "k8" * 12
        _write(memory, "feedback_key.md", f"---\nname:\n  {token}: x\n---\nbody\n")
        res = _run_scan(memory_root=root)
        self.assertNotIn(token, res["raw"])
        self.assertEqual(res["json"]["findings"][0]["title"], {"[REDACTED]": "x"})

    def test_the_source_path_stays_usable_for_drain(self):
        """A slug can look like a credential; drain needs the real path."""
        root, memory = _make_root("-home-u-projects-xoxb-slack-bot-integration")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        path = _write(memory, "feedback_a.md", FEEDBACK)
        index = _write(memory, "MEMORY.md", "- [a](feedback_a.md) — a\n")
        res = _run_scan(memory_root=root)
        finding = res["json"]["findings"][0]
        self.assertEqual(finding["source_path"], str(path))
        self.assertEqual(finding["index_path"], str(index))

    def test_path_named_keys_in_frontmatter_are_masked(self):
        """Only a finding's own path fields are exempt, not note text."""
        root, memory = _make_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        token = "glpat-" + "p9" * 12
        _write(
            memory,
            "feedback_p.md",
            f"---\nname:\n  source_path: {token}\n  index_path: {token}\n---\nbody\n",
        )
        res = _run_scan(memory_root=root)
        self.assertNotIn(token, res["raw"])

    def test_keys_that_mask_alike_are_all_kept(self):
        root, memory = _make_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        first, second = "glpat-" + "a1" * 12, "glpat-" + "b2" * 12
        _write(
            memory,
            "feedback_keys.md",
            f"---\nname:\n  {first}: one\n  {second}: two\n---\nbody\n",
        )
        res = _run_scan(memory_root=root)
        self.assertNotIn(first, res["raw"])
        self.assertEqual(
            res["json"]["findings"][0]["title"],
            {"[REDACTED]": "one", "[REDACTED] (2)": "two"},
        )


class GlobalRulesMaskingTest(unittest.TestCase):
    def test_a_token_at_the_cut_is_masked_whole(self):
        root, _memory = _make_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        token = "glpat-" + "Ab1" * 10
        rules = root / "CLAUDE.md"
        rules.write_text(
            "## Rule\n\n" + "x" * 175 + f" use {token}\n", encoding="utf-8"
        )
        res = _run_scan(
            memory_root=root, include_global_rules=True, global_rules_file=rules
        )
        self.assertNotIn("glpat-Ab1", res["raw"])


class PruneIndexLineTest(unittest.TestCase):
    def test_sole_link_drops_line(self):
        self.assertIsNone(smi._prune_index_line("- [x](a.md) — hook\n", "a.md"))

    def test_grouped_line_keeps_siblings(self):
        line = "- **CI hygiene**: [one](a.md) · [two](b.md) (@-note) · [three](c.md)\n"
        self.assertEqual(
            smi._prune_index_line(line, "b.md"),
            "- **CI hygiene**: [one](a.md) · [three](c.md)\n",
        )

    def test_grouped_drain_via_cmd(self):
        root, memory = _make_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        path = _write(memory, "b.md", FEEDBACK)
        _write(memory, "MEMORY.md", "- **G**: [one](a.md) · [two](b.md)\n")
        res = _run_drain(path, root)
        self.assertEqual(res["rc"], 0)
        index = (memory / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("[one](a.md)", index)
        self.assertNotIn("b.md", index)


class PruneIndexLineRealLinesTest(unittest.TestCase):
    """Lines taken verbatim from a real MEMORY.md drain that went wrong.

    Each case lost either the bullet marker, half of the removed link, or
    rule text that belongs to no link at all.
    """

    def test_leading_link_keeps_bullet(self):
        line = (
            "- [NR public service needs proxy routers]"
            "(reference_nr_public_service_proxy_routers.md) — intern AND extern"
            " · [IPv6 baseline; check allow-lists before AAAA]"
            "(feedback_ipv6_is_baseline_not_optional.md)\n"
        )
        self.assertEqual(
            smi._prune_index_line(line, "reference_nr_public_service_proxy_routers.md"),
            "- [IPv6 baseline; check allow-lists before AAAA]"
            "(feedback_ipv6_is_baseline_not_optional.md)\n",
        )

    def test_leading_link_with_hook_keeps_bullet_and_sibling_hook(self):
        line = (
            "- [No ghost-context docs](feedback_no_ghost_context_docs.md)"
            " — present tense · [ci-components/docker/build@1 limits]"
            "(reference_nr_ci_components.md) — hand-roll buildx\n"
        )
        self.assertEqual(
            smi._prune_index_line(line, "feedback_no_ghost_context_docs.md"),
            "- [ci-components/docker/build@1 limits]"
            "(reference_nr_ci_components.md) — hand-roll buildx\n",
        )

    def test_colon_inside_link_text_removes_whole_link(self):
        line = (
            "- [Secrets pasted in chat: work first, enforce revocation]"
            "(feedback_secrets_in_chat.md) · [gitleaks scans full history]"
            "(feedback_gitleaks_full_history_scan.md)\n"
        )
        self.assertEqual(
            smi._prune_index_line(line, "feedback_secrets_in_chat.md"),
            "- [gitleaks scans full history](feedback_gitleaks_full_history_scan.md)\n",
        )

    def test_leading_link_with_long_hook_keeps_bullet(self):
        line = (
            "- [nr-llm improvement roadmap](project_nr_llm_improvement_roadmap.md)"
            " — 12 WS, Reihenfolge + Status · [nr-ai-search × nr-llm integration]"
            "(project_nr_ai_search_nr_llm_integration.md) — PRs !37/#348-350\n"
        )
        self.assertEqual(
            smi._prune_index_line(line, "project_nr_llm_improvement_roadmap.md"),
            "- [nr-ai-search × nr-llm integration]"
            "(project_nr_ai_search_nr_llm_integration.md) — PRs !37/#348-350\n",
        )

    def test_two_drains_on_one_line_keep_bullet(self):
        line = (
            "- [NR runner read-only /etc/ssl/certs]"
            "(reference_nr_runner_readonly_ssl_certs.md)"
            " · [Measure from the execution vantage]"
            "(reference_measure_from_execution_vantage.md)"
            " · [Debian gpgv is a separate package]"
            "(reference_debian_gpgv_separate_package.md)\n"
        )
        once = smi._prune_index_line(line, "reference_nr_runner_readonly_ssl_certs.md")
        twice = smi._prune_index_line(once, "reference_debian_gpgv_separate_package.md")
        self.assertEqual(
            twice,
            "- [Measure from the execution vantage]"
            "(reference_measure_from_execution_vantage.md)\n",
        )

    def test_rule_text_outside_links_survives(self):
        line = (
            "- **Jira**: NEVER mcp-atlassian MCP. Use `jira:jira-communication`"
            " skill for jira.netresearch.de · [NR Atlassian split]"
            "(reference_nr_atlassian_split.md) — Confluence Cloud; Jira on-prem\n"
        )
        self.assertEqual(
            smi._prune_index_line(line, "reference_nr_atlassian_split.md"),
            "- **Jira**: NEVER mcp-atlassian MCP. Use `jira:jira-communication`"
            " skill for jira.netresearch.de\n",
        )

    def test_link_inside_prose_removes_only_the_link(self):
        head = (
            "- Repos: `usercentrics-widgets` (npm, Rollup IIFE+IE11, semistandard,"
            " **rebase-only**) · `ofelia` (Go scheduler fork, merge-queue,"
            " `release-slsa.yml`; dep `netresearch/go-cron`) ·"
            " `sdk-api-central-station` (PHP CRM SDK; common fix: stale PHPStan"
            " baseline) · glpi-docker-compose-stack (GLPI 11,"
            " ghcr.io/netresearch/glpi-php-fpm) · archived,"
            " unarchive→change→re-archive: vault-read"
        )
        line = head + " ([vault-read.md](vault-read.md)), node-vault, satis-git\n"
        self.assertEqual(
            smi._prune_index_line(line, "vault-read.md"),
            head + ", node-vault, satis-git\n",
        )

    def test_label_kept_when_its_first_link_goes(self):
        line = "- **G**: [one](a.md) — hook · [two](b.md)\n"
        self.assertEqual(
            smi._prune_index_line(line, "a.md"),
            "- **G**: [two](b.md)\n",
        )

    def test_mid_line_label_goes_with_its_only_link(self):
        line = "- Hosts: [a](a.md) · Other: [b](b.md) — hook\n"
        self.assertEqual(
            smi._prune_index_line(line, "b.md"),
            "- Hosts: [a](a.md)\n",
        )

    def test_label_only_remainder_drops_line(self):
        self.assertIsNone(
            smi._prune_index_line("- **G**: [one](a.md) — hook\n", "a.md")
        )

    def test_rule_text_survives_drain_via_cmd(self):
        root, memory = _make_root()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        path = _write(memory, "reference_nr_atlassian_split.md", FEEDBACK)
        _write(
            memory,
            "MEMORY.md",
            "- **Jira**: NEVER mcp-atlassian MCP. Use `jira:jira-communication`"
            " skill for jira.netresearch.de · [NR Atlassian split]"
            "(reference_nr_atlassian_split.md) — Confluence Cloud; Jira on-prem\n",
        )
        res = _run_drain(path, root)
        self.assertEqual(res["rc"], 0)
        index = (memory / "MEMORY.md").read_text(encoding="utf-8")
        self.assertEqual(
            index,
            "- **Jira**: NEVER mcp-atlassian MCP. Use `jira:jira-communication`"
            " skill for jira.netresearch.de\n",
        )


GLOBAL_RULES = """# Personal Preferences

- always be nice

## Signed Git Commits - MANDATORY
- WHEN: Creating git commits
- ALWAYS: Use explicit `-S` and `--signoff` flags
- **Why:** signing may silently fail in subprocess environments

## Empty Section

# Learned Rules

## CI Re-runs Replay Same Commit
- WHEN: Re-running failed CI workflows after pushing a fix
- DO: Push the fix first, then re-run the LATEST run
"""


class GlobalRulesSourceTest(unittest.TestCase):
    def setUp(self):
        self.root, self.memory = _make_root()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.rules = self.root / "CLAUDE.md"
        self.rules.write_text(GLOBAL_RULES, encoding="utf-8")

    def test_off_by_default(self):
        _write(self.memory, "feedback_x.md", FEEDBACK)
        res = _run_scan(memory_root=self.root, global_rules_file=self.rules)
        locations = {f["current_location"] for f in res["json"]["findings"]}
        self.assertNotIn("global-claude-md", locations)

    def test_emits_one_c2_per_nonempty_section(self):
        res = _run_scan(
            memory_root=self.root,
            include_global_rules=True,
            global_rules_file=self.rules,
        )
        c2 = [
            f
            for f in res["json"]["findings"]
            if f["current_location"] == "global-claude-md"
        ]
        titles = [f["title"] for f in c2]
        self.assertEqual(
            titles,
            ["Signed Git Commits - MANDATORY", "CI Re-runs Replay Same Commit"],
        )
        for f in c2:
            self.assertEqual(f["signal"], "C2")
            self.assertEqual(f["source_path"], str(self.rules))
            self.assertTrue(f["content_sha256"])
        self.assertIn("silently fail", c2[0]["why"])

    def test_hash_lines_inside_a_code_fence_are_not_headings(self):
        """`# ` and `## ` in a fenced shell block are comments; they neither end
        the section nor open a new one."""
        self.rules.write_text(
            "# Rules\n\n## Setup\n\n```bash\n# 1. create the dir\n"
            "## not a heading, a shell comment\nmkdir x\n```\n\n"
            "**Why:** the fence stays inside Setup.\n\n"
            "~~~\n## tilde fence too\n~~~\n\n## Other\n\nbody\n",
            encoding="utf-8",
        )
        res = _run_scan(
            memory_root=self.root,
            include_global_rules=True,
            global_rules_file=self.rules,
        )
        c2 = [
            f
            for f in res["json"]["findings"]
            if f["current_location"] == "global-claude-md"
        ]
        self.assertEqual([f["title"] for f in c2], ["Setup", "Other"])
        self.assertIn("fence stays inside Setup", c2[0]["why"])

    def test_backticks_in_the_info_string_open_no_fence(self):
        """```python`x is text (CommonMark): the heading after it still counts."""
        self.rules.write_text(
            "# Rules\n\n## Setup\n\n```python`x\nbody\n\n## Other\n\nbody\n",
            encoding="utf-8",
        )
        res = _run_scan(
            memory_root=self.root,
            include_global_rules=True,
            global_rules_file=self.rules,
        )
        titles = [
            f["title"]
            for f in res["json"]["findings"]
            if f["current_location"] == "global-claude-md"
        ]
        self.assertEqual(titles, ["Setup", "Other"])

    def test_missing_rules_file_is_not_an_error(self):
        res = _run_scan(
            memory_root=self.root,
            include_global_rules=True,
            global_rules_file=self.root / "absent.md",
        )
        self.assertEqual(res["rc"], 0)

    def test_drain_refuses_global_rules_file(self):
        res = _run_drain(self.rules, self.root)
        self.assertEqual(res["rc"], 2)
        self.assertTrue(self.rules.is_file())


# The go-cron store's MEMORY.md as it stood before a peer session drained it by
# hand on 2026-11-08: `##` sections, `###` subsections, links and bullets, and no
# note files at all. Copied byte for byte from that drain's tombstone.
GO_CRON_MEMORY = (
    REPO_ROOT / "tests" / "fixtures" / "memory" / "go-cron-MEMORY.txt"
).read_text(encoding="utf-8")

SHELL_SECTION = (
    "## Shell recipe\n"
    "\n"
    "```bash\n"
    "# not a heading, a shell comment\n"
    "## not a heading either\n"
    "make test\n"
    "```\n"
    "\n"
    "**Why:** fenced comments must stay inside the section.\n"
    "\n"
)

NOTES_SECTION = (
    "## Notes\n"
    "- [Kept note](feedback_x.md) — the index entry of a live note\n"
    "- Release from a signed tag only.\n"
    "- [Gone note](gone.md) — dangling link: this hook is the last copy\n"
    "\n"
)

INDEX_ONLY_SECTION = "## Index only\n- [Kept note](feedback_x.md) — a second entry\n\n"

INLINE_STORE = (
    GO_CRON_MEMORY + "\n" + SHELL_SECTION + NOTES_SECTION + INDEX_ONLY_SECTION
)

GO_CRON_TITLES = [
    "Current State (2026-03-08)",
    "v0.13.1 (2026-03-08)",
    "v0.11.0 Features (2026-02-12)",
    "v0.10.0 Features (2026-02-08)",
    "Dependents Analysis (2026-02-08, updated 2026-02-12)",
    "Technical Notes",
]


def _inline(findings: list[dict]) -> list[dict]:
    return [
        f for f in findings if f["current_location"] == "project-local-memory-inline"
    ]


def _span(text: str, heading: str, next_heading: str | None) -> tuple[int, int]:
    start = text.index(heading)
    end = text.index(next_heading, start) if next_heading else len(text)
    return start, end


class InlineMemoryScanTest(unittest.TestCase):
    def setUp(self):
        self.root, self.memory = _make_root()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _write(self.memory, "feedback_x.md", FEEDBACK)
        self.index = _write(self.memory, "MEMORY.md", INLINE_STORE)

    def _units(self) -> list[dict]:
        return _inline(_run_scan(memory_root=self.root)["json"]["findings"])

    def test_go_cron_sections_are_found_with_their_text(self):
        units = self._units()
        self.assertEqual(
            [u["title"] for u in units],
            GO_CRON_TITLES + ["Shell recipe", "Notes"],
        )
        by_title = {u["title"]: u for u in units}
        start, end = _span(INLINE_STORE, "## v0.11.0 Features", "## v0.10.0 Features")
        self.assertEqual(
            by_title["v0.11.0 Features (2026-02-12)"]["content"],
            INLINE_STORE[start:end],
        )
        # `###` subsections stay inside their `##` unit.
        dependents = by_title["Dependents Analysis (2026-02-08, updated 2026-02-12)"][
            "content"
        ]
        self.assertIn("### Intra-Fork PRs (all on v0.11.0)", dependents)
        self.assertIn("[CybotTM/zwfm-aerontoolbox PR #1]", dependents)
        for u in units:
            self.assertEqual(u["signal"], "C3")
            self.assertEqual(u["name"], "memory_drift")
            self.assertEqual(u["source_path"], str(self.index))
            self.assertEqual(u["source_slug"], "-home-sme")
            self.assertTrue(u["inline_unit"].startswith("## "))

    def test_index_entries_of_live_notes_are_not_content(self):
        notes = {u["title"]: u for u in self._units()}["Notes"]
        self.assertNotIn("Kept note", notes["content"])
        self.assertIn("Release from a signed tag only.", notes["content"])
        self.assertNotIn("Index only", [u["title"] for u in self._units()])

    def test_a_dangling_link_is_content(self):
        notes = {u["title"]: u for u in self._units()}["Notes"]
        self.assertIn("dangling link: this hook is the last copy", notes["content"])

    def test_hash_lines_inside_a_fence_are_not_headings(self):
        units = {u["title"]: u for u in self._units()}
        shell = units["Shell recipe"]["content"]
        self.assertIn("# not a heading, a shell comment\n", shell)
        self.assertIn("## not a heading either\n", shell)
        self.assertIn("fenced comments must stay inside", units["Shell recipe"]["why"])
        self.assertNotIn("not a heading either", units)

    def test_sha_covers_the_unit_text_and_only_it(self):
        first = {u["title"]: u["content_sha256"] for u in self._units()}
        for u in self._units():
            self.assertEqual(
                u["content_sha256"],
                hashlib.sha256(u["content"].encode("utf-8")).hexdigest(),
            )
        self.assertEqual(
            first, {u["title"]: u["content_sha256"] for u in self._units()}
        )
        # One byte changed in one section changes that sha and no other.
        self.index.write_text(
            INLINE_STORE.replace("Coverage**: ~97%+", "Coverage**: ~98%+"),
            encoding="utf-8",
        )
        second = {u["title"]: u["content_sha256"] for u in self._units()}
        changed = sorted(t for t in first if first[t] != second[t])
        self.assertEqual(changed, ["Current State (2026-03-08)"])

    def test_notes_and_inline_units_are_both_emitted(self):
        res = _run_scan(memory_root=self.root)["json"]
        locations = [f["current_location"] for f in res["findings"]]
        self.assertEqual(locations.count("project-local-memory"), 1)
        self.assertEqual(locations.count("project-local-memory-inline"), 8)
        slug = res["slugs_scanned"][0]
        self.assertEqual(slug["items"], 9)
        self.assertEqual(slug["inline_units"], 8)

    def test_preamble_is_a_unit_without_the_title(self):
        self.index.write_text(
            "# Memory\n\nLoose rule before any section.\n\n## A\n- a\n",
            encoding="utf-8",
        )
        units = self._units()
        self.assertEqual([u["inline_unit"] for u in units], ["preamble", "## A"])
        self.assertEqual(units[0]["content"], "\nLoose rule before any section.\n\n")

    def test_empty_and_index_only_units_emit_nothing(self):
        self.index.write_text(
            "# Memory Index\n\n## Empty\n\n## Index\n- [k](feedback_x.md) — hook\n",
            encoding="utf-8",
        )
        self.assertEqual(self._units(), [])

    def test_pending_state_in_an_inline_unit_is_in_the_index(self):
        self.index.write_text(
            "## Release\n- v2.0 still open, waiting on review\n", encoding="utf-8"
        )
        unit = self._units()[0]
        self.assertIn("still open", unit["pending_state"])
        self.assertTrue(unit["pending_state_in_index"])


class InlineMemoryDrainTest(unittest.TestCase):
    def setUp(self):
        self.root, self.memory = _make_root()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _write(self.memory, "feedback_x.md", FEEDBACK)
        self.index = _write(self.memory, "MEMORY.md", INLINE_STORE)

    def _unit(self, title: str) -> dict:
        res = _run_scan(memory_root=self.root)["json"]
        return {u["title"]: u for u in _inline(res["findings"])}[title]

    def _tombstones(self) -> list[Path]:
        return sorted((self.memory / ".promoted").glob("MEMORY-inline-*.md"))

    def test_drain_moves_exactly_one_section(self):
        unit = self._unit("v0.11.0 Features (2026-02-12)")
        others = {
            u["title"]: u["content_sha256"]
            for u in _inline(_run_scan(memory_root=self.root)["json"]["findings"])
            if u["title"] != unit["title"]
        }
        res = _run_drain(self.index, self.root, unit["content_sha256"])
        self.assertEqual(res["rc"], 0, res["stderr"])
        start, end = _span(INLINE_STORE, "## v0.11.0 Features", "## v0.10.0 Features")
        self.assertEqual(
            self.index.read_text(encoding="utf-8"),
            INLINE_STORE[:start] + INLINE_STORE[end:],
        )
        [tomb] = self._tombstones()
        self.assertIn(INLINE_STORE[start:end], tomb.read_text(encoding="utf-8"))
        self.assertIn(unit["content_sha256"], tomb.read_text(encoding="utf-8"))
        after = {
            u["title"]: u["content_sha256"]
            for u in _inline(_run_scan(memory_root=self.root)["json"]["findings"])
        }
        self.assertEqual(after, others)
        self.assertEqual(json.loads(res["stdout"])["tombstone"], str(tomb))

    def test_drain_keeps_the_heading_and_index_entries_of_a_section(self):
        unit = self._unit("Notes")
        res = _run_drain(self.index, self.root, unit["content_sha256"])
        self.assertEqual(res["rc"], 0, res["stderr"])
        start, end = _span(INLINE_STORE, "## Notes", "## Index only")
        kept = "## Notes\n- [Kept note](feedback_x.md) — the index entry of a live note\n\n"
        self.assertEqual(
            self.index.read_text(encoding="utf-8"),
            INLINE_STORE[:start] + kept + INLINE_STORE[end:],
        )
        self.assertTrue((self.memory / "feedback_x.md").is_file())

    def test_drain_keeps_a_mid_line_pointer_to_a_live_note(self):
        """The shape of a real render-guides line: the link sits mid-line and a
        pending handoff follows it. Draining the unit must not take the only
        pointer to the live note, nor the handoff bridge."""
        pointer = (
            "See [composer-workflows.md](feedback_x.md) for composer update "
            "strategies. · Handoff retro-1: https://github.com/o/r/pull/1 (draft, "
            "pending; retire the note once merged and released)\n"
        )
        self.index.write_text(
            "## Composer\n- Prefer `composer bump`.\n" + pointer + "\n## B\n- b\n",
            encoding="utf-8",
        )
        unit = self._unit("Composer")
        self.assertEqual(unit["content"], "## Composer\n- Prefer `composer bump`.\n\n")
        res = _run_drain(self.index, self.root, unit["content_sha256"])
        self.assertEqual(res["rc"], 0, res["stderr"])
        self.assertEqual(
            self.index.read_text(encoding="utf-8"),
            "## Composer\n" + pointer + "\n## B\n- b\n",
        )

    def test_drain_of_the_preamble(self):
        text = "# Memory\n\nLoose rule.\n\n## A\n- a\n"
        self.index.write_text(text, encoding="utf-8")
        units = _inline(_run_scan(memory_root=self.root)["json"]["findings"])
        res = _run_drain(self.index, self.root, units[0]["content_sha256"])
        self.assertEqual(res["rc"], 0, res["stderr"])
        self.assertEqual(
            self.index.read_text(encoding="utf-8"), "# Memory\n## A\n- a\n"
        )

    def test_drain_refuses_on_sha_mismatch(self):
        before = self.index.read_bytes()
        res = _run_drain(self.index, self.root, "0" * 64)
        self.assertEqual(res["rc"], 2)
        self.assertIn("changed since scan", res["stderr"])
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(self._tombstones(), [])

    def test_drain_without_a_sha_refuses_and_keeps_the_index(self):
        """A bare `drain MEMORY.md` used to tombstone the whole index."""
        before = self.index.read_bytes()
        res = _run_drain(self.index, self.root, None)
        self.assertEqual(res["rc"], 2)
        self.assertIn("--expect-sha256", res["stderr"])
        self.assertEqual(self.index.read_bytes(), before)
        self.assertFalse((self.memory / ".promoted").exists())

    def test_drain_refuses_a_memory_md_outside_a_store(self):
        unit = self._unit("Notes")
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        rogue = other / "slug" / "memory"
        rogue.mkdir(parents=True)
        stray = rogue / "MEMORY.md"
        stray.write_text(INLINE_STORE, encoding="utf-8")
        res = _run_drain(stray, self.root, unit["content_sha256"])
        self.assertEqual(res["rc"], 2)
        self.assertIn("is not inside", res["stderr"])
        self.assertEqual(stray.read_text(encoding="utf-8"), INLINE_STORE)

    def test_a_second_drain_of_the_same_unit_refuses(self):
        unit = self._unit("Technical Notes")
        self.assertEqual(
            _run_drain(self.index, self.root, unit["content_sha256"])["rc"], 0
        )
        res = _run_drain(self.index, self.root, unit["content_sha256"])
        self.assertEqual(res["rc"], 2)
        self.assertIn("changed since scan", res["stderr"])

    def test_retry_after_a_failed_replace_appends_once(self):
        """The tombstone is written before MEMORY.md is replaced: a failure in
        between leaves the text in both places, and the retry does not append
        it a second time."""
        unit = self._unit("Technical Notes")
        real_replace = smi.os.replace
        calls = {"n": 0}

        def failing_once(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("simulated")
            return real_replace(src, dst)

        before = self.index.read_bytes()
        with mock.patch.object(smi.os, "replace", failing_once):
            res = _run_drain(self.index, self.root, unit["content_sha256"])
        self.assertNotEqual(res["rc"], 0)
        self.assertEqual(self.index.read_bytes(), before)
        res = _run_drain(self.index, self.root, unit["content_sha256"])
        self.assertEqual(res["rc"], 0, res["stderr"])
        [tomb] = self._tombstones()
        self.assertEqual(
            tomb.read_text(encoding="utf-8").count(unit["content_sha256"]), 1
        )
        self.assertNotIn("## Technical Notes", self.index.read_text(encoding="utf-8"))

    def test_a_write_to_memory_md_during_the_tombstone_write_survives(self):
        """Another session saving a memory while the tombstone is written must
        not lose its line: the unchanged-check sits directly before the
        replace, and the retry finds the block already in the tombstone."""
        unit = self._unit("Technical Notes")
        real_append = smi._append_tombstone

        def concurrent_save(tombstone, block):
            real_append(tombstone, block)
            with open(self.index, "a", encoding="utf-8") as handle:
                handle.write("- saved by another session\n")

        with mock.patch.object(smi, "_append_tombstone", concurrent_save):
            res = _run_drain(self.index, self.root, unit["content_sha256"])
        self.assertEqual(res["rc"], 0, res["stderr"])
        text = self.index.read_text(encoding="utf-8")
        self.assertIn("- saved by another session", text)
        self.assertNotIn("## Technical Notes", text)
        [tomb] = self._tombstones()
        self.assertEqual(
            tomb.read_text(encoding="utf-8").count(unit["content_sha256"]), 1
        )

    def test_an_uppercase_hash_selects_the_unit(self):
        unit = self._unit("Technical Notes")
        res = _run_drain(self.index, self.root, unit["content_sha256"].upper())
        self.assertEqual(res["rc"], 0, res["stderr"])
        self.assertNotIn("## Technical Notes", self.index.read_text(encoding="utf-8"))

    def test_a_hash_line_before_a_partial_copy_is_not_a_copy(self):
        """A tombstone write cut short leaves the hash line and half the unit;
        the retry must still append the whole unit before taking it out."""
        unit = self._unit("Technical Notes")
        promoted = self.memory / ".promoted"
        promoted.mkdir()
        partial = (
            f"<!-- retro promote drain: sha256={unit['content_sha256']} -->\n"
            + unit["content"][: len(unit["content"]) // 2]
        )
        (promoted / "MEMORY-inline-2000-01-01.md").write_text(partial, encoding="utf-8")
        res = _run_drain(self.index, self.root, unit["content_sha256"])
        self.assertEqual(res["rc"], 0, res["stderr"])
        copies = "".join(p.read_text(encoding="utf-8") for p in self._tombstones())
        self.assertIn(
            f"<!-- retro promote drain: sha256={unit['content_sha256']} -->\n"
            + unit["content"],
            copies,
        )

    def test_note_drain_still_works_beside_inline_units(self):
        note = self.memory / "feedback_x.md"
        res = _run_drain(note, self.root)
        self.assertEqual(res["rc"], 0, res["stderr"])
        self.assertFalse(note.is_file())
        self.assertNotIn("feedback_x.md", self.index.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
