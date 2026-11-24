#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""List every line of the instruction files that names a term.

A signal, a phase or a rule is restated in several files. After changing one,
run this for its id or its wording and read each copy:

    uv run scripts/find-copies.py B19 "Phase 4b" "reasoned no-op"

A signal id (B19) is also found inside a range (B16–B21), a lettered phase
(Phase 4b) also as its bare id in a list or table, and a phrase across a line
break. Case is ignored for phrases. Whether a copy is out of date
is the reader's judgement; the exit code says only that every term was found
(0) or that one was not (1).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPE = (
    "commands/*.md",
    "skills/retro/SKILL.md",
    "skills/retro/checkpoints.yaml",
    "skills/retro/references/*.md",
    "skills/retro/evals/*.md",
    "tests/test_*.py",
    "docs/adr/*.md",
    "README.md",
    "AGENTS.md",
)
SIGNAL = re.compile(r"[A-E][0-9]{1,2}")
PHASE = re.compile(r"[Pp]hase ([0-9]{1,2}[a-z])")
# B16–B21, B16-B21, or one id.
MENTION = re.compile(r"\b([A-E])([0-9]{1,2})(?:\s?[–-]\s?\1([0-9]{1,2}))?\b")


def signal_mentions(text: str) -> list[tuple[int, str]]:
    """(offset, id) of every signal named in text, ranges expanded."""
    found = []
    for m in MENTION.finditer(text):
        first = int(m[2])
        last = int(m[3]) if m[3] else first
        found += [(m.start(), f"{m[1]}{n}") for n in range(first, last + 1)]
    return found


def offsets(term: str, text: str) -> list[int]:
    if SIGNAL.fullmatch(term):
        return [at for at, signal in signal_mentions(text) if signal == term]
    phase = PHASE.fullmatch(term)
    if phase:
        # A bare id stands in the mode table and in lists (3c and 4b, 2b/3/4b).
        bare = rf"\b{phase[1]}\b"
        return [m.start() for m in re.finditer(bare, text)]
    words = r"\s+".join(re.escape(word) for word in term.split())
    return [m.start() for m in re.finditer(words, text, re.IGNORECASE)]


def copies(term: str, repo: Path) -> list[str]:
    hits = []
    for pattern in SCOPE:
        for path in sorted(repo.glob(pattern)):
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            numbers = {text.count("\n", 0, at) for at in offsets(term, text)}
            hits += [
                f"{path.relative_to(repo)}:{n + 1}: {lines[n].strip()[:160]}"
                for n in sorted(numbers)
            ]
    return hits


def main(argv: list[str] | None = None, repo: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("term", nargs="+", help="signal id or phrase")
    missing = False
    for term in parser.parse_args(argv).term:
        if not term.strip():
            parser.error("empty term")
        hits = copies(term, repo)
        missing = missing or not hits
        print(f"== {term}: {len(hits)} lines")
        for hit in hits:
            print(hit)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
