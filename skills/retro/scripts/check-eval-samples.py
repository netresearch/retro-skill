#!/usr/bin/env python3
"""Refuse an eval retro adds or tightens that carries no ``samples``.

``samples`` is the only thing the fleet's eval gate can execute:
skill-repo-skill's ``validate-evals.sh`` applies every pattern-bearing
assertion to ``samples.passing`` and to each ``samples.failing`` entry and
fails the job when a passing sample violates an assertion or a failing sample
satisfies all of them. Measured across the 23 ``evals.json`` files in the
fleet, 12 of 518 evals carry samples.passing, so for the rest that gate has
nothing to compare and validates shape only (retro-skill#92).

This check closes that on the evals *retro itself writes*: it compares the
eval records in an ``evals.json`` against the same file at a base revision and
rejects an eval that is new, or whose assertions changed, while carrying no
samples. Untouched evals are never looked at - nothing is retrofitted.

Scope, deliberately: only pattern-bearing assertions can be sampled. An eval
graded solely by ``expectations`` (LLM-as-judge strings) has nothing for the
grader to grep, and ``validate-evals.sh`` *fails* samples that no assertion
pattern backs - so such evals are skipped rather than demanded.

Usage:
    check-eval-samples.py --repo <dir> [--base <rev>] <path>...

Paths are repo-relative. Anything that is not an eval container (recognised by
shape, as in ``validate-evals.py``) is skipped. Exit 0 if nothing is missing
samples, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ASSERTION_PATTERN_KEYS = ("pattern", "value")

# The revision and the paths arrive as CLI arguments an agent composed, so they
# are data and must never reach git as options. Both halves are needed: the
# allowlist rejects an option-shaped value before git runs, and
# ``--end-of-options`` stops git reading whatever survives as a flag.
SAFE_REVISION = re.compile(r"\A[0-9A-Za-z][0-9A-Za-z._/^~@{}-]*\Z")
SAFE_PATH = re.compile(r"\A[0-9A-Za-z][0-9A-Za-z._/-]*\Z")


def _records(data: object) -> list[dict] | None:
    """Return the eval records of a recognised container, else ``None``.

    Both container shapes are current in the fleet: a top-level array of eval
    objects, and an object with an ``evals`` array.
    """
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        return data
    if isinstance(data, dict) and isinstance(data.get("evals"), list):
        return [x for x in data["evals"] if isinstance(x, dict)]
    return None


def _identity(record: dict, index: int) -> str:
    for key in ("eval_name", "name", "id"):
        value = record.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return f"{key}={value}"
    return f"index={index}"


def _pattern_assertions(record: dict) -> list[dict]:
    assertions = record.get("assertions")
    if not isinstance(assertions, list):
        return []
    return [
        a
        for a in assertions
        if isinstance(a, dict)
        and any(str(a.get(k, "")).strip() for k in ASSERTION_PATTERN_KEYS)
    ]


def _has_samples(record: dict) -> bool:
    samples = record.get("samples")
    if not isinstance(samples, dict):
        return False
    passing = samples.get("passing")
    return isinstance(passing, str) and bool(passing.strip())


def _base_text(repo: Path, base: str, path: str) -> str | None:
    """File contents at ``base``, or ``None`` when it did not exist there.

    An unreadable base makes every eval in the file count as new, so refusing a
    malformed revision or path here fails toward the stricter answer.
    """
    if not SAFE_REVISION.match(base) or not SAFE_PATH.match(path):
        return None
    result = subprocess.run(
        ["git", "-C", str(repo), "show", "--end-of-options", f"{base}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _base_index(repo: Path, base: str, path: str) -> dict[str, dict]:
    text = _base_text(repo, base, path)
    if text is None:
        return {}
    try:
        records = _records(json.loads(text))
    except ValueError:
        return {}
    if records is None:
        return {}
    return {_identity(r, i): r for i, r in enumerate(records)}


def check_file(repo: Path, base: str, path: str) -> list[str]:
    """Return one message per eval in ``path`` that is new/tightened without samples."""
    full = repo / path
    try:
        records = _records(json.loads(full.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []
    if records is None:
        return []

    before = _base_index(repo, base, path)
    problems = []
    for index, record in enumerate(records):
        if not _pattern_assertions(record) or _has_samples(record):
            continue
        identity = _identity(record, index)
        previous = before.get(identity)
        if previous is None:
            state = "new eval"
        elif previous.get("assertions") != record.get("assertions"):
            state = "tightened assertions"
        else:
            continue
        problems.append(
            f"{path}: {identity}: {state} without 'samples' - add "
            "samples.passing and at least one samples.failing so "
            "validate-evals.sh grades the assertion both ways "
            "(references/eval-integration.md)"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refuse a new or tightened eval that carries no samples."
    )
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--base",
        default="HEAD",
        help="Revision the files are compared against (default: HEAD).",
    )
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)

    problems: list[str] = []
    for path in args.paths:
        problems += check_file(args.repo, args.base, path)

    if problems:
        print(f"FAIL: {len(problems)} eval(s) without samples:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
