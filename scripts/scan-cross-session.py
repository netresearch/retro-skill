#!/usr/bin/env python3
"""
scan-cross-session.py — fallback Schicht-C data source when Coach absent.

Scans Claude Code session JSONL files across projects to find similar friction
patterns. Used to detect "same friction again" and "cross-project pattern" signals.

Usage:
    python3 scan-cross-session.py --pattern "<keyword or phrase>" [--days 30] [--project <slug>]
    python3 scan-cross-session.py --user-correction-summary [--days 7]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CORRECTION_PATTERNS = re.compile(
    r"^\s*(no\b|nein\b|stop\b|don't\b|wrong\b|NEIN\b|nicht so\b)",
    re.IGNORECASE | re.MULTILINE,
)


def session_files(
    projects_dir: Path, project_slug: str | None, days: int
) -> list[tuple[Path, str]]:
    """Return list of (jsonl_path, project_slug) within the last N days."""
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    if project_slug:
        candidates = [projects_dir / project_slug]
    else:
        candidates = [p for p in projects_dir.iterdir() if p.is_dir()]
    for proj_dir in candidates:
        if not proj_dir.exists():
            continue
        for f in proj_dir.glob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
            except OSError:
                continue
            if mtime >= cutoff:
                out.append((f, proj_dir.name))
    return out


def extract_user_texts(path: Path) -> list[str]:
    texts = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") != "user":
                    continue
                msg = ev.get("message", {}) or {}
                content = msg.get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
    except OSError:
        pass
    return texts


def cmd_pattern(args, files) -> int:
    pattern = re.compile(re.escape(args.pattern), re.IGNORECASE)
    hits = defaultdict(list)
    for path, proj in files:
        for txt in extract_user_texts(path):
            if pattern.search(txt):
                hits[proj].append(
                    {
                        "session": path.name,
                        "snippet": txt[:300],
                    }
                )
                break  # one hit per session is enough for cross-session signal
    print(
        json.dumps(
            {
                "pattern": args.pattern,
                "days": args.days,
                "projects_with_matches": len(hits),
                "matches": dict(hits),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_correction_summary(args, files) -> int:
    corrections_by_project: dict[str, Counter] = defaultdict(Counter)
    for path, proj in files:
        for txt in extract_user_texts(path):
            if not CORRECTION_PATTERNS.search(txt):
                continue
            # Normalize first 80 chars as a fingerprint
            key = re.sub(r"\s+", " ", txt.strip().lower())[:80]
            corrections_by_project[proj][key] += 1

    cross_project = Counter()
    for counter in corrections_by_project.values():
        for key in counter:
            cross_project[key] += 1

    output = {
        "days": args.days,
        "projects_scanned": len(files),
        "cross_project_corrections": [
            {"snippet": k, "projects_count": v}
            for k, v in cross_project.most_common(20)
            if v >= 2
        ],
        "by_project_top5": {
            proj: [{"snippet": k, "count": cnt} for k, cnt in c.most_common(5)]
            for proj, c in corrections_by_project.items()
            if c
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-dir", type=Path, default=DEFAULT_PROJECTS_DIR)
    parser.add_argument("--project", help="Specific project slug (e.g. -home-sme-p)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--pattern", help="Search for keyword/phrase in user messages")
    parser.add_argument(
        "--user-correction-summary",
        action="store_true",
        help="Summarize correction patterns across sessions",
    )
    args = parser.parse_args()

    if not args.projects_dir.exists():
        print(
            json.dumps(
                {"available": False, "reason": f"not found: {args.projects_dir}"}
            )
        )
        return 0

    files = session_files(args.projects_dir, args.project, args.days)
    if args.pattern:
        return cmd_pattern(args, files)
    elif args.user_correction_summary:
        return cmd_correction_summary(args, files)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
