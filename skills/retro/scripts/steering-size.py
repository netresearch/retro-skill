#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""Report the size of the steering files that load in every turn.

A report, never a gate: it prints sizes and exits 0 whatever they are.

Files read (a missing one is listed with "exists": false):

- <repo>/AGENTS.md and <repo>/CLAUDE.md, the repository root only
- <home>/.claude/CLAUDE.md, the global rules file of Claude Code
- <home>/.codex/AGENTS.md, the global instructions of Codex

An "@AGENTS.md" or "@./AGENTS.md" token in the repo CLAUDE.md, outside code
spans and fenced blocks, imports that file, so it loads for Claude Code too
("imported_by_claude_md": true). Other imports are not followed. Without a
CLAUDE.md, Claude Code 2.1.277 or later reads AGENTS.md directly
(code.claude.com/docs/en/memory, read 2026-11-23).

approx_tokens is bytes / 4, a rough figure for English text and no
tokenizer's count. With --proposed TARGET=FILE, where FILE holds the whole
proposed content of TARGET, the entry for TARGET gains the signed delta in
lines and bytes.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CLAUDE_MD = "CLAUDE.md"
CODE_SPAN = re.compile(r"(`+).*?\1", re.DOTALL)
IMPORT = re.compile(r"(?<!\S)@(?:\./)?AGENTS\.md(?![^\s])")


def measure(path: Path) -> dict:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    data = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "lines": len(data.splitlines()),
        "bytes": len(data),
        "approx_tokens": len(data) // 4,
    }


def strip_fences(text: str) -> str:
    """Drop fenced code blocks line by line (a regex here backtracks)."""
    kept, fence = [], None
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence is None and stripped.startswith(("```", "~~~")):
            fence = stripped[: len(stripped) - len(stripped.lstrip(stripped[0]))]
        elif fence is not None and stripped.startswith(fence):
            if not stripped.rstrip().strip(fence[0]):
                fence = None
        elif fence is None:
            kept.append(line)
    return "\n".join(kept)


def imports_agents_md(claude_md: Path) -> bool:
    if not claude_md.is_file():
        return False
    text = claude_md.read_text(encoding="utf-8", errors="replace")
    return bool(IMPORT.search(CODE_SPAN.sub("", strip_fences(text))))


def build_report(repo: Path | None, home: Path, proposed: dict[str, Path]) -> dict:
    files = []
    if repo is not None:
        files.append(measure(repo / "AGENTS.md"))
        files[0]["imported_by_claude_md"] = imports_agents_md(repo / CLAUDE_MD)
        files.append(measure(repo / CLAUDE_MD))
    files.append(measure(home / ".claude" / CLAUDE_MD))
    files.append(measure(home / ".codex" / "AGENTS.md"))
    by_path = {str(Path(f["path"]).resolve()): f for f in files}
    for target, new_file in proposed.items():
        entry = by_path.get(str(Path(target).expanduser().resolve()))
        if entry is None:
            raise SystemExit(
                f"--proposed target is not an always-loaded file: {target}"
            )
        new = measure(new_file)
        if not new["exists"]:
            raise SystemExit(f"--proposed file not found: {new_file}")
        entry["proposed_delta"] = {
            "lines": new["lines"] - entry.get("lines", 0),
            "bytes": new["bytes"] - entry.get("bytes", 0),
        }
    return {"files": files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo", type=Path, help="repository root the session worked in"
    )
    parser.add_argument(
        "--home", type=Path, default=Path.home(), help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--proposed",
        action="append",
        default=[],
        metavar="TARGET=FILE",
        help="whole proposed content of an always-loaded file; repeatable",
    )
    args = parser.parse_args(argv)
    proposed = {}
    for item in args.proposed:
        target, sep, new_file = item.partition("=")
        if not sep:
            parser.error(f"--proposed needs TARGET=FILE, got {item!r}")
        proposed[target] = Path(new_file)
    print(json.dumps(build_report(args.repo, args.home, proposed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
