#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
scan-memory-inventory.py — inventory already-written local memory stores and emit promotable findings.

Front-end for the `/retro promote` mode. Where detect-mechanical.py reads a
session transcript (the "flow"), this scans the accumulated, cwd-scoped memory
files (the "stock") that Claude Code's default memory behaviour writes to
~/.claude/projects/<slug>/memory/, and emits findings the existing retro
pipeline (classify -> approve -> materialize) can promote upward to their
correct destination (skill-update > project-rule > personal-rule; never
project-local memory). A separate `drain` subcommand tombstones a source file
AFTER its upward write has been confirmed — it never deletes.

The output envelope mirrors detect-mechanical.py so pipeline stages 4-10 consume
it unchanged. Each finding carries an existing classification-heuristic signal
(C3 memory_drift for memory-store files, B8 wrong_destination for opt-in flagged
project-local stores) plus the verbatim Why / How-to-apply prose and a
content_sha256 used as both an idempotency key and a drain race-check.

Promote checks ALL memories: by default every project slug under the memory
root is scanned, not just the current one.

A second opt-in source (--include-global-rules) enumerates the `## ` sections
of the always-loaded global rules file (~/.claude/CLAUDE.md) as C2
cross-project-pattern findings, so rules that outgrew the personal scope can be
promoted into the owning skill. This source is scan-only: the `drain`
subcommand keeps refusing anything outside a <slug>/memory/ store — a
global-rule drain is an approval-gated agent edit that removes the section
only after the upward write is verified (see references/promote-mode.md).

Usage:
    uv run scan-memory-inventory.py [--project SLUG] [--memory-root PATH] \
        [--include-flagged-locations] [--project-dir PATH] \
        [--include-global-rules] [--global-rules-file PATH] \
        [--output-format json|text]
    uv run scan-memory-inventory.py drain PATH [--memory-root PATH] [--expect-sha256 HEX]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


def _load_masking():
    """mask-secrets.py, loaded by path: its name is hyphenated like ours."""
    path = Path(__file__).resolve().parent / "mask-secrets.py"
    spec = importlib.util.spec_from_file_location("mask_secrets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_masking = _load_masking()

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
INDEX_FILE = "MEMORY.md"
TOMBSTONE_DIR = ".promoted"
WHY_MARKER = "**Why:**"
HOWTO_MARKER = "**How to apply:**"
SECTION_MARKER = re.compile(r"^\*\*[A-Za-z].*?:\*\*", re.MULTILINE)
# Files inside a memory/ dir that are never themselves promotable stock.
SKIP_NAMES = {INDEX_FILE}

# Language that asserts a PENDING state: something still open, not yet done,
# waiting on someone. A note carrying it was true when written and turns false
# the moment the awaited thing happens, without a word of its text changing -
# so it is the one class of note that has to be re-verified rather than merely
# promoted. The index line matters most: MEMORY.md is loaded into every
# session, so a stale pending claim there misleads each one.
#
# Chosen by reading, not by listing likely words. The first version flagged 51
# of 335 notes on a real multi-project store, 7 of them genuinely pending: 14%.
# Reading every hit showed where the noise came from. `blocked`/`blocks` gave
# ~15 hits and not one pending claim - `mergeState=BLOCKED`, a status enum,
# `content-blocks`, "composer blocks ^12" are mechanisms. Bare `waiting` and
# `pending` were exit codes and API states. And 125 of the 335 notes are German,
# where the English pattern saw nothing; German state words were 6 of 8
# correct. This version flags 19, 13 of them pending (68%), missing none of the
# 13 the first one or this one found. Those numbers come from the same notes
# the words were chosen on, so expect lower precision on notes not yet seen.
#
# `unreleased` stays - it is the word the note that prompted this carried on
# its index line - but not as `[Unreleased]` (a CHANGELOG heading) or as the
# tail of a compound like `merged-but-unreleased` (a past event).
PENDING_STATE_RE = re.compile(
    r"(?:\b(?:still open|remains open|not yet|waits? on|waiting (?:on|for)|"
    r"until (?:it|they|then)|pending (?:user|review|approval|decision|choice)|"
    r"steht aus|stehen aus|ausstehend|noch nicht|noch offen|bleibt offen|"
    r"wartet auf|warten auf)\b"
    r"|(?<![\[\w-])(?:unreleased|unveröffentlicht)\b)",
    re.IGNORECASE,
)

# A feedback note states a rule, and a rule speaks in conditionals - "until the
# gate is green", "not yet merged means…". None of that is a claim that
# something is open now, and feedback notes carried most of the noise in both
# languages, so they are not examined for pending state at all.
PENDING_STATE_SKIP_TYPES = {"feedback"}


def _pending_state_phrases(text: str) -> list[str]:
    """The distinct pending-state phrases in `text`, lower-cased and sorted."""
    return sorted({m.group(0).lower() for m in PENDING_STATE_RE.finditer(text)})


def _iter_slug_dirs(memory_root: Path, project: str | None) -> list[tuple[str, Path]]:
    """Return [(slug, memory_dir)] to scan.

    Promote's aim is to check ALL memories, so by default every project slug
    that has a memory/ dir is scanned (de-siloing the worktree-vs-parent split).
    --project narrows to one explicit slug.
    """
    if project:
        slugs = [project]
    elif memory_root.exists():
        slugs = sorted(
            p.name
            for p in memory_root.iterdir()
            if p.is_dir() and (p / "memory").is_dir()
        )
    else:
        slugs = []
    return [(slug, memory_root / slug / "memory") for slug in slugs]


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Tolerant YAML-frontmatter splitter (stdlib-only — no pyyaml).

    Returns the top-level key/value pairs; a key with an empty value followed by
    indented `key: value` lines (e.g. `metadata:`) becomes a nested dict.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict[str, Any] = {}
    last_map_key: str | None = None
    closed = False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        content = line.strip()
        if not content or content[0] == "#" or ":" not in content:
            continue
        key, _, value = content.partition(":")
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip("\"'")
        indent = line[:1] in (" ", "\t")
        if indent and last_map_key and isinstance(fm.get(last_map_key), dict):
            fm[last_map_key][key] = value
        elif value == "":
            fm[key] = {}
            last_map_key = key
        else:
            fm[key] = value
            last_map_key = None
    return fm if closed else {}


def _frontmatter_end(text: str) -> int:
    """Index of the first character after the closing frontmatter fence."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return 0
    pos = len(lines[0])
    for line in lines[1:]:
        pos += len(line)
        if line.strip() == "---":
            return pos
    return 0


def _extract_section(body: str, marker: str) -> str | None:
    """Return the prose of a `**Marker:**` section up to the next bold marker."""
    idx = body.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    nxt = SECTION_MARKER.search(body, start)
    end = nxt.start() if nxt else len(body)
    section = body[start:end].strip()
    return section or None


def _read_finding(
    path: Path, slug: str, index_path: Path | None
) -> dict[str, Any] | None:
    """Build one C3 promotable-memory finding from a memory file, or None."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    fm = _parse_frontmatter(text)
    body = text[_frontmatter_end(text) :].strip()
    metadata = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    description = str(fm.get("description", ""))
    note_type = str(metadata.get("type") or fm.get("type") or "")
    if note_type in PENDING_STATE_SKIP_TYPES:
        pending, pending_in_index = [], False
    else:
        pending = _pending_state_phrases(body + "\n" + description)
        pending_in_index = bool(_pending_state_phrases(description))
    return {
        "signal": "C3",
        "name": "memory_drift",
        "source_path": str(path),
        "source_slug": slug,
        "index_path": str(index_path) if index_path else None,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "title": fm.get("name") or fm.get("description") or path.stem,
        "description": fm.get("description", ""),
        "why": _extract_section(body, WHY_MARKER) or "",
        "how_to_apply": _extract_section(body, HOWTO_MARKER) or "",
        "origin_session_id": metadata.get("originSessionId", ""),
        "current_location": "project-local-memory",
        # Re-verify before promoting. `pending_state_in_index` is the sharper
        # of the two: a match in the description is a match in MEMORY.md.
        "pending_state": pending,
        "pending_state_in_index": pending_in_index,
    }


def _flagged_findings(cwd: Path) -> list[dict[str, Any]]:
    """Opt-in B8 findings for deprecated project-local rule stores."""
    findings: list[dict[str, Any]] = []
    candidates: list[tuple[Path, str]] = [(cwd / "CLAUDE.md", "project-CLAUDE.md")]
    feedback_dir = cwd / "docs" / "feedback"
    if feedback_dir.is_dir():
        candidates += [(p, "docs/feedback") for p in sorted(feedback_dir.glob("*.md"))]
    for path, which in candidates:
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        text = raw.decode("utf-8", errors="replace")
        body = text[_frontmatter_end(text) :].strip()
        fm = _parse_frontmatter(text)
        findings.append(
            {
                "signal": "B8",
                "name": "wrong_destination_materialization",
                "source_path": str(path),
                "which_wrong_file": which,
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "title": fm.get("name") or path.stem,
                "description": fm.get("description", ""),
                "why": _extract_section(body, WHY_MARKER) or "",
                "how_to_apply": _extract_section(body, HOWTO_MARKER) or "",
                "current_location": "project-local-rule",
            }
        )
    return findings


_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")


def _global_rules_findings(rules_file: Path) -> list[dict[str, Any]]:
    """Opt-in C2 findings: one per `## ` section of the global rules file.

    The global rules file is a *destination* for personal preferences, so it is
    never scanned by default (re-promoting a correct destination loops). The
    opt-in exists for the one legitimate upward move out of it: a rule whose
    content generalizes beyond the person — a tool gotcha, a workflow recipe,
    domain facts — belongs in the owning skill (team-shared), and this source
    surfaces each section so the classifier can judge it. Always-on behavioral
    rules must NOT leave the file (a skill loads only on trigger); that filter
    is the classifier's call, not this scanner's.
    """
    if not rules_file.is_file():
        return []
    try:
        text = rules_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    findings: list[dict[str, Any]] = []
    lines = text.splitlines(keepends=True)
    section_start: int | None = None
    title = ""
    offset = 0
    spans: list[tuple[str, int, int]] = []
    fence = ""  # the open ``` / ~~~ run; a `# ` line inside is a comment
    for line in lines:
        marker = _FENCE.match(line)
        if fence:
            # Closed by a bare run of the same character, at least as long.
            if (
                marker
                and marker.group(1)[0] == fence[0]
                and len(marker.group(1)) >= len(fence)
                and not line[marker.end() :].strip()
            ):
                fence = ""
        elif marker and not (marker.group(1)[0] == "`" and "`" in line[marker.end() :]):
            # A backtick fence's info string cannot hold a backtick
            # (CommonMark); ```python`x is text, not a fence.
            fence = marker.group(1)
        elif line.startswith("## "):
            if section_start is not None:
                spans.append((title, section_start, offset))
            section_start = offset
            title = line[3:].strip()
        elif line.startswith("# ") and section_start is not None:
            spans.append((title, section_start, offset))
            section_start = None
        offset += len(line)
    if section_start is not None:
        spans.append((title, section_start, offset))
    for title, start, end in spans:
        # Hash the exact slice, un-normalized — same race-check semantics as the
        # raw-byte hashing of memory files (a whitespace-only edit is an edit).
        raw_section = text[start:end]
        section = raw_section.strip()
        body = section.partition("\n")[2].strip()
        if not body:
            continue
        findings.append(
            {
                "signal": "C2",
                "name": "cross_project_pattern",
                "source_path": str(rules_file),
                "section_title": title,
                "content_sha256": hashlib.sha256(
                    raw_section.encode("utf-8")
                ).hexdigest(),
                "title": title,
                # Masked before it is cut: a token cut short no longer matches
                # its pattern, and its head would be printed.
                "description": _masking.mask(body.splitlines()[0])[:200],
                "why": _extract_section(body, WHY_MARKER) or "",
                "how_to_apply": _extract_section(body, HOWTO_MARKER) or "",
                "current_location": "global-claude-md",
            }
        )
    return findings


def cmd_scan(args) -> int:
    memory_root: Path = args.memory_root
    slug_dirs = _iter_slug_dirs(memory_root, args.project)

    slugs_scanned: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for slug, memory_dir in slug_dirs:
        present = memory_dir.is_dir()
        items = 0
        if present:
            index_path = memory_dir / INDEX_FILE
            index = index_path if index_path.is_file() else None
            for md in sorted(memory_dir.glob("*.md")):
                if md.name in SKIP_NAMES:
                    continue
                finding = _read_finding(md, slug, index)
                if finding:
                    findings.append(finding)
                    items += 1
        slugs_scanned.append(
            {"slug": slug, "path": str(memory_dir), "present": present, "items": items}
        )

    if args.include_flagged_locations:
        project_dir = Path(args.project_dir) if args.project_dir else Path(os.getcwd())
        findings.extend(_flagged_findings(project_dir))

    if getattr(args, "include_global_rules", False):
        findings.extend(_global_rules_findings(args.global_rules_file))

    findings = [_masked_finding(f) for f in findings]

    if not findings and not any(s["present"] for s in slugs_scanned):
        envelope: dict[str, Any] = {
            "available": False,
            "reason": "no project-scoped memory files found",
            "slugs_scanned": slugs_scanned,
        }
    else:
        envelope = {
            "available": True,
            "source": "memory-inventory",
            "memory_root": str(memory_root),
            "slugs_scanned": slugs_scanned,
            "items_total": sum(s["items"] for s in slugs_scanned),
            "findings_total": len(findings),
            "findings": findings,
        }

    if args.output_format == "text":
        _print_text(envelope)
    else:
        print(json.dumps(envelope, indent=2, ensure_ascii=False))
    return 0


# A finding's own file paths are printed as they are, like
# `slugs_scanned[].path`: `drain` takes `source_path` back, and both name a
# file the reader has to find. Only a finding's top-level fields
# qualify: a key of the same name inside a note's frontmatter is note text.
PATH_FIELDS = frozenset({"source_path", "index_path"})


def _masked_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item if key in PATH_FIELDS else _masked(item)
        for key, item in finding.items()
    }


def _masked(value: Any) -> Any:
    """Mask every string in a value: all of its text comes from a note."""
    if isinstance(value, str):
        return _masking.mask(value)
    if isinstance(value, dict):
        masked: dict[Any, Any] = {}
        for key, item in value.items():
            name = _masked(key)
            # Two keys can mask to the same text; number the later ones so
            # no entry is dropped.
            unique, n = name, 2
            while unique in masked:
                unique, n = f"{name} ({n})", n + 1
            masked[unique] = _masked(item)
        return masked
    if isinstance(value, list):
        return [_masked(item) for item in value]
    return value


def _print_text(envelope: dict[str, Any]) -> None:
    if not envelope.get("available"):
        print(f"available: false — {envelope.get('reason')}")
    for s in envelope.get("slugs_scanned", []):
        flag = "" if s["present"] else "  (no memory/ dir)"
        print(f"slug {s['slug']}: {s['items']} item(s){flag}")
    for f in envelope.get("findings", []):
        print(f"  [{f['signal']}] {f['title']} <- {f['source_path']}")


INDEX_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
INDEX_SEPARATOR = " · "


def _prune_segment(segment: str, link: re.Pattern[str]) -> str:
    """Remove the target link from one " · "-separated segment.

    A link that opens the segment (optionally after a ``label:``) is an index
    entry: it goes together with its trailing hook text, up to the segment's
    end. A link inside prose goes alone — with the parentheses when it is
    their only content — so the surrounding sentence survives.
    """
    while (m := link.search(segment)) is not None:
        before = segment[: m.start()]
        if not before.strip() or before.rstrip().endswith(":"):
            segment = before.rstrip()
            continue
        start, end = m.start(), m.end()
        if segment[start - 1 : start] == "(" and segment[end : end + 1] == ")":
            start, end = start - 1, end + 1
        if segment[start - 1 : start] == " ":
            start -= 1
        segment = segment[:start] + segment[end:]
    return segment


def _prune_index_line(line: str, name: str) -> str | None:
    """Remove one note's entry from an index line; None drops the whole line.

    MEMORY.md lines are often grouped bullets holding several links separated
    by " · ", or a rule written in prose followed by a link to its note. Only
    the target link goes, with its own hook text and one adjacent separator;
    the bullet marker, a leading label, sibling links and any text outside the
    link stay. The line itself goes only when nothing but the marker, a label
    and separators remains.
    """
    eol = "\n" if line.endswith("\n") else ""
    content = line.rstrip("\n")
    marker_match = INDEX_MARKER.match(content)
    marker = marker_match.group(0) if marker_match else ""
    body = content[len(marker) :]
    link = re.compile(r"\[[^\]]*\]\(" + re.escape(name) + r"\)")

    segments: list[str] = []
    bare_label = False
    for index, segment in enumerate(body.split(INDEX_SEPARATOR)):
        if not link.search(segment):
            segments.append(segment)
            continue
        pruned = _prune_segment(segment, link)
        if not pruned.strip():
            continue
        if pruned.rstrip().endswith(":"):
            if index > 0:
                continue  # a mid-line label with nothing left to introduce
            bare_label = True
        segments.append(pruned)

    if bare_label:
        # A label whose first link went ("**G**: [one](a.md) · [two](b.md)")
        # joins the next entry with a space rather than a separator, and a
        # label with nothing left to introduce goes with the line.
        if len(segments) == 1:
            return None
        segments[:2] = [segments[0].rstrip() + " " + segments[1].lstrip()]
    if not "".join(segments).strip():
        return None
    return marker + INDEX_SEPARATOR.join(segments) + eol


def _tombstone_names(tombstone_dir: Path, source: Path, sha: str):
    """The file's own name, then names disambiguated by content hash."""
    yield tombstone_dir / source.name
    yield tombstone_dir / f"{source.stem}.{sha[:12]}{source.suffix}"
    n = 1
    while True:
        yield tombstone_dir / f"{source.stem}.{sha[:12]}.{n}{source.suffix}"
        n += 1


def _place(path: Path, names) -> Path | None:
    """Move `path` to the first of `names` that does not exist yet.

    A hard link fails when its target exists, so a file another process put
    there in the meantime is never replaced; where hard links are not
    supported, the name is claimed with an exclusive create first. Returns None when every name is
    taken (only a finite list can run out)."""
    for name in names:
        try:
            os.link(path, name)
        except FileExistsError:
            continue
        except OSError:
            # A file system without hard links: claim the name by creating it
            # exclusively, then move the file over the placeholder.
            try:
                os.close(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            except FileExistsError:
                continue
            os.replace(path, name)
            return name
        os.unlink(path)
        return name
    return None


def _rewrite_index(index_path: Path, name: str) -> None:
    """Drop the entry for `name` from MEMORY.md and replace the file in one step.

    The new index is written to a temporary file beside it and renamed over it,
    so a reader sees the old or the new index, never a partial one. If the
    index changed while it was being rewritten, the rewrite starts again from
    the new text. A write that lands between the last check and the rename is
    still lost; there is no lock against a concurrent writer."""
    for _attempt in range(5):
        before = index_path.read_bytes()
        kept = []
        for line in before.decode("utf-8", errors="replace").splitlines(keepends=True):
            if f"]({name})" not in line:
                kept.append(line)
                continue
            pruned = _prune_index_line(line, name)
            if pruned is not None:
                kept.append(pruned)
        fd, tmp = tempfile.mkstemp(prefix=f".{INDEX_FILE}.", dir=index_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("".join(kept))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, index_path.stat().st_mode & 0o7777)
            if index_path.read_bytes() != before:
                continue
            os.replace(tmp, index_path)
            return
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    raise RuntimeError(
        f"{index_path} kept changing; the entry for {name} is still in it"
    )


def cmd_drain(args) -> int:
    path: Path = args.path
    try:
        resolved = path.resolve()
    except OSError:
        print(f"drain: cannot resolve {path}", file=sys.stderr)
        return 2
    if not resolved.is_file():
        print(f"drain: not a file: {resolved}", file=sys.stderr)
        return 2
    # Refuse anything not shaped like <memory-root>/<slug>/memory/<file>, so a
    # drain can only ever touch a genuine project-memory store.
    memory_root = args.memory_root.resolve()
    if resolved.parent.name != "memory" or resolved.parent.parent.parent != memory_root:
        print(
            f"drain refused: {resolved} is not inside a "
            "<memory-root>/<slug>/memory/ store",
            file=sys.stderr,
        )
        return 2
    try:
        raw = resolved.read_bytes()
    except OSError:
        print(f"drain refused: cannot read source {resolved}", file=sys.stderr)
        return 2
    source_sha = hashlib.sha256(raw).hexdigest()
    if args.expect_sha256 and source_sha != args.expect_sha256:
        print(
            "drain refused: source changed since scan "
            f"(expected {args.expect_sha256[:12]}, found {source_sha[:12]})",
            file=sys.stderr,
        )
        return 2

    memory_dir = resolved.parent
    tombstone_dir = memory_dir / TOMBSTONE_DIR
    tombstone_dir.mkdir(exist_ok=True)
    # Take the file out of the store first, into a directory of its own, and
    # judge the bytes that were taken: a check of the path followed by a move
    # of the path could move something written in between.
    staging = Path(tempfile.mkdtemp(prefix=".drain-", dir=tombstone_dir))
    taken = staging / resolved.name
    try:
        os.rename(resolved, taken)
    except OSError:
        staging.rmdir()
        print(f"drain refused: cannot move source {resolved}", file=sys.stderr)
        return 2
    taken_sha = hashlib.sha256(taken.read_bytes()).hexdigest()
    if args.expect_sha256 and taken_sha != args.expect_sha256:
        restored = _place(taken, [resolved])
        if restored is not None:
            staging.rmdir()
        print(
            "drain refused: source changed since scan "
            f"(expected {args.expect_sha256[:12]}, found {taken_sha[:12]})"
            + ("" if restored else f"; the file is kept at {taken}"),
            file=sys.stderr,
        )
        return 2
    tombstone = _place(taken, _tombstone_names(tombstone_dir, resolved, taken_sha))
    staging.rmdir()

    index_path = memory_dir / INDEX_FILE
    index_pruned = False
    if index_path.is_file():
        try:
            _rewrite_index(index_path, resolved.name)
        except RuntimeError as exc:
            print(f"drain: tombstoned to {tombstone}, but {exc}", file=sys.stderr)
            return 1
        index_pruned = True

    print(
        json.dumps(
            {
                "drained": True,
                "source": str(resolved),
                "tombstone": str(tombstone),
                "index_pruned": index_pruned,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")

    parser.add_argument(
        "--project", default=None, help="Scan one explicit slug instead of all"
    )
    parser.add_argument("--memory-root", type=Path, default=DEFAULT_PROJECTS_DIR)
    parser.add_argument("--include-flagged-locations", action="store_true")
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project dir checked for deprecated local rule stores "
        "(with --include-flagged-locations); default cwd",
    )
    parser.add_argument(
        "--include-global-rules",
        action="store_true",
        help="Also emit one C2 finding per `## ` section of the global rules "
        "file, so rules that outgrew the personal scope can be promoted "
        "into the owning skill (scan-only; drain stays an agent edit)",
    )
    parser.add_argument(
        "--global-rules-file",
        type=Path,
        default=Path.home() / ".claude" / "CLAUDE.md",
        help="Global rules file scanned by --include-global-rules",
    )
    parser.add_argument("--output-format", choices=["json", "text"], default="json")

    drain = sub.add_parser(
        "drain", help="Tombstone one materialized source (never deletes)"
    )
    drain.add_argument("path", type=Path)
    drain.add_argument("--memory-root", type=Path, default=DEFAULT_PROJECTS_DIR)
    drain.add_argument(
        "--expect-sha256", default=None, help="Abort if source bytes differ"
    )

    args = parser.parse_args()
    if args.command == "drain":
        return cmd_drain(args)
    return cmd_scan(args)


if __name__ == "__main__":
    sys.exit(main())
