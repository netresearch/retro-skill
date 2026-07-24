#!/usr/bin/env python3
"""Validate retro's own eval scenarios under ``evals/``.

These fixtures test retro's *own* classification behaviour. This validator only
checks that they are well-formed (frontmatter present, required keys, unique
ids, filename == id, minimum inventory). It does NOT run retro against them — the
scenarios are LLM-graded (see ``evals/README.md``).

Repo-scoped on purpose: this enforces a schema on retro's OWN evals only. It does
NOT change retro's lenient, schema-free reading of *other* skills' evals
(see ``references/eval-integration.md``).

Exit 0 if every scenario is well-formed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REQUIRED_SCALARS = ("id", "trigger")
REQUIRED_LISTS = ("expected", "negative_expected")


def _unquote(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _is_key_line(line: str) -> bool:
    """True for an unindented ``key: ...`` line with an identifier-like key."""
    if line[:1].isspace() or ":" not in line:
        return False
    key = line.partition(":")[0].strip()
    return bool(key) and key.replace("_", "").isalnum()


def _apply_line(line: str, fm: dict, current_key: str | None) -> str | None:
    """Apply one frontmatter line to ``fm``; return the new current block key.

    Plain string parsing (no regex) of the controlled format in
    ``evals/README.md``: unindented ``key: value`` scalars and ``  - item``
    block-sequence entries.
    """
    stripped = line.strip()
    if current_key is not None and stripped.startswith("- "):
        bucket = fm.setdefault(current_key, [])
        if isinstance(bucket, list):
            bucket.append(_unquote(stripped[2:]))
        return current_key
    if _is_key_line(line):
        key, _, inline = line.partition(":")
        key = key.strip()
        inline = inline.strip()
        if inline:
            fm[key] = _unquote(inline)
            return None
        fm[key] = []
        return key
    return current_key


def parse_frontmatter(text: str) -> dict[str, object] | None:
    """Parse a tiny YAML subset (scalars + block lists) from leading ``---`` frontmatter.

    Returns a dict mapping each key to a ``str`` (scalar) or ``list[str]`` (block
    sequence), or ``None`` when no terminated frontmatter block is present. This is
    deliberately minimal: it covers exactly the controlled format documented in
    ``evals/README.md``, with no external YAML dependency.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fm: dict[str, object] = {}
    current_key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return fm
        if line.strip():
            current_key = _apply_line(line, fm, current_key)
    return None  # unterminated frontmatter


def _scenario_files(evals_dir: Path) -> list[Path]:
    return sorted(p for p in evals_dir.glob("*.md") if p.name.lower() != "readme.md")


def _is_nonempty_strlist(value: object) -> bool:
    return (
        isinstance(value, list) and bool(value) and all(str(x).strip() for x in value)
    )


def _check_id(path: Path, fm: dict, seen_ids: dict[str, str]) -> list[str]:
    ev_id = fm.get("id")
    if not isinstance(ev_id, str) or not ev_id.strip():
        return []
    errors = []
    if ev_id != path.stem:
        errors.append(
            f"{path.name}: id '{ev_id}' does not match filename stem '{path.stem}'"
        )
    if ev_id in seen_ids:
        errors.append(
            f"{path.name}: duplicate id '{ev_id}' (also in {seen_ids[ev_id]})"
        )
    else:
        seen_ids[ev_id] = path.name
    return errors


def _validate_scenario(path: Path, seen_ids: dict[str, str]) -> list[str]:
    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    if fm is None:
        return [f"{path.name}: missing or unterminated YAML frontmatter"]
    errors = [
        f"{path.name}: missing/empty scalar '{key}'"
        for key in REQUIRED_SCALARS
        if not isinstance(fm.get(key), str) or not fm[key].strip()
    ]
    errors += [
        f"{path.name}: '{key}' must be a non-empty list with no blank items"
        for key in REQUIRED_LISTS
        if not _is_nonempty_strlist(fm.get(key))
    ]
    errors += _check_id(path, fm, seen_ids)
    return errors


def validate(evals_dir: Path, min_scenarios: int) -> list[str]:
    """Return a list of human-readable problems; empty list means valid."""
    if not evals_dir.is_dir():
        return [f"evals directory not found: {evals_dir}"]

    files = _scenario_files(evals_dir)
    errors: list[str] = []
    if len(files) < min_scenarios:
        errors.append(f"too few scenarios: found {len(files)}, need >= {min_scenarios}")

    seen_ids: dict[str, str] = {}
    for path in files:
        errors += _validate_scenario(path, seen_ids)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate retro's own eval scenarios.")
    parser.add_argument(
        "--evals-dir",
        type=Path,
        default=None,
        help="Path to the evals/ directory (default: <skill-dir>/evals).",
    )
    parser.add_argument(
        "--min-scenarios",
        type=int,
        default=5,
        help="Minimum number of scenario files required (default: 5).",
    )
    args = parser.parse_args(argv)

    evals_dir = args.evals_dir or (Path(__file__).resolve().parent.parent / "evals")
    errors = validate(evals_dir, args.min_scenarios)
    if errors:
        print(f"FAIL: {len(errors)} problem(s) in {evals_dir}:", file=sys.stderr)
        for problem in errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    count = len(_scenario_files(evals_dir))
    print(f"OK: {count} retro eval scenario(s) well-formed in {evals_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
