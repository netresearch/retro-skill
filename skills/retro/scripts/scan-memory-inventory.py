#!/usr/bin/env python3
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
    python3 scan-memory-inventory.py [--project SLUG] [--memory-root PATH] \
        [--include-flagged-locations] [--project-dir PATH] \
        [--include-global-rules] [--global-rules-file PATH] \
        [--output-format json|text]
    python3 scan-memory-inventory.py drain PATH [--memory-root PATH] [--expect-sha256 HEX]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
INDEX_FILE = "MEMORY.md"
TOMBSTONE_DIR = ".promoted"
WHY_MARKER = "**Why:**"
HOWTO_MARKER = "**How to apply:**"
SECTION_MARKER = re.compile(r"^\*\*[A-Za-z].*?:\*\*", re.MULTILINE)
# Files inside a memory/ dir that are never themselves promotable stock.
SKIP_NAMES = {INDEX_FILE}


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
    for line in lines:
        if line.startswith("## "):
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
                "description": body.splitlines()[0][:200],
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


def _print_text(envelope: dict[str, Any]) -> None:
    if not envelope.get("available"):
        print(f"available: false — {envelope.get('reason')}")
    for s in envelope.get("slugs_scanned", []):
        flag = "" if s["present"] else "  (no memory/ dir)"
        print(f"slug {s['slug']}: {s['items']} item(s){flag}")
    for f in envelope.get("findings", []):
        print(f"  [{f['signal']}] {f['title']} <- {f['source_path']}")


INDEX_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")


def _prune_index_line(line: str, name: str) -> str | None:
    """Remove one note's entry from an index line; None drops the whole line.

    MEMORY.md lines are often grouped bullets holding several links separated
    by " · " — dropping the whole line on a match would take the sibling
    entries' links with it (observed: a drain of one note removed a 8-link
    group line). Only when the target link is the line's sole link does the
    line itself go.
    """
    links = INDEX_LINK.findall(line)
    target = f"]({name})"
    if sum(target in link for link in links) == len(links):
        return None
    if " · " not in line:
        return None
    eol = "\n" if line.endswith("\n") else ""
    content = line.rstrip("\n")
    prefix, sep, rest = content.partition(": ")
    if not sep or target in prefix:
        prefix, rest = "", content
        sep = ""
    segments = [s for s in rest.split(" · ") if target not in s]
    if not segments:
        return None
    return prefix + sep + " · ".join(segments) + eol


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
    tombstone = tombstone_dir / resolved.name
    # Never clobber an existing tombstone — disambiguate by content hash.
    if tombstone.exists():
        tombstone = (
            tombstone_dir / f"{resolved.stem}.{source_sha[:12]}{resolved.suffix}"
        )
        n = 1
        while tombstone.exists():
            tombstone = (
                tombstone_dir
                / f"{resolved.stem}.{source_sha[:12]}.{n}{resolved.suffix}"
            )
            n += 1
    os.replace(resolved, tombstone)

    index_path = memory_dir / INDEX_FILE
    index_pruned = False
    if index_path.is_file():
        kept = []
        for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines(
            keepends=True
        ):
            if f"]({resolved.name})" not in line:
                kept.append(line)
                continue
            pruned = _prune_index_line(line, resolved.name)
            if pruned is not None:
                kept.append(pruned)
        index_path.write_text("".join(kept), encoding="utf-8")
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
