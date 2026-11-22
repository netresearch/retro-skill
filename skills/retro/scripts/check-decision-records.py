#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
check-decision-records.py — read a repository's decision-record declaration and anchors.

The root AGENTS.md of a project must state whether the project keeps decision
records (ADRs) and where: an undefined state is a finding (signal E7). This
script reads that declaration, lists the records in the declared directory and
in AGENTS.md, and checks the paths each record names in its Touches field:

- E7 decision_policy_undefined — AGENTS.md states no ADR position, or states
  one that the repository contradicts (the directory is missing, it has no
  AGENTS.md of its own, "no" names no other place for decisions, or two lines
  disagree).
- E8 decision_anchor_missing — a record that is not superseded names a path
  that no longer exists. The record may describe code that has moved or gone.
- E1 decision_record_crossed — with --changed-file, a changed path lies under
  the anchor of a record that is not superseded. This is a candidate only: the
  reading pass decides whether the change contradicts the decision.

Only paths are matched. Names in a record's prose are not compared with the
code: Trail-Code measured that approach on 2026-10-29 and 9 of the 10 records
it flagged still matched the code (trailhq/Trail-Code, learning l-3cfeb3b1).
A record without a Touches field is reported as unanchored, not as an error.

Accepted declaration lines in AGENTS.md (list markers and bold are ignored):

    ADRs: yes — `docs/adr/`
    ADRs: no — decisions are recorded in the PR description

Accepted anchors in a record (an ADR file, or a section of AGENTS.md):

    **Touches:** `src/retry.py`, `config/`
    touches:            (YAML frontmatter list)
      - src/retry.py

A path may name a file, a directory (everything below it) or a glob. A
`#Symbol` suffix is accepted and ignored.

Usage:
    uv run check-decision-records.py [--repo DIR] [--changed-file PATH ...]
        [--changed-files-from FILE|-] [--output-format json|text]

Exit status: 0 when the check ran (findings are in the output), 2 on a usage
error or an unreadable repository.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

AGENTS_MD = "AGENTS.md"
INACTIVE_STATUSES = ("superseded", "deprecated", "rejected", "withdrawn", "retired")
NON_RECORD_NAMES = {"agents.md", "readme.md", "index.md", "claude.md"}
GLOB_CHARS = "*?["

# Each pattern has one unbounded group at its end, so no input backtracks
# super-linearly; separators after it are stripped in Python.
_DECL = re.compile(r"^ADRs?\s*:\s*(yes|no|ja|nein)\b(.*)$", re.IGNORECASE)
_FIELD = re.compile(r"^(status|touches)\s*:(.*)$", re.IGNORECASE)
_BACKTICK = re.compile(r"`([^`]+)`")
_LIST_MARKER = re.compile(r"^(?:[-*+]|\d+\.)\s+")
_SEPARATORS = " \t—–:-"


def _plain(line: str) -> str:
    """A line without list markers, bold markers and surrounding space."""
    s = _LIST_MARKER.sub("", line.strip())
    return s.replace("**", "").replace("__", "").strip()


def _inside(repo: Path, rel: str) -> Path | None:
    """The path below the repository root, or None when it leaves the root."""
    p = (repo / rel).resolve()
    return p if p == repo or p.is_relative_to(repo) else None


def _declarations(text: str) -> list[tuple[int, str, str]]:
    decls = []
    for n, line in enumerate(text.splitlines(), 1):
        m = _DECL.match(_plain(line))
        if m:
            answer = "yes" if m.group(1).lower() in ("yes", "ja") else "no"
            decls.append((n, answer, m.group(2).strip(_SEPARATORS)))
    return decls


def _check_adr_dir(rest: str, repo: Path) -> tuple[str | None, list[str]]:
    """The directory a yes-declaration names, and what the repository says about it."""
    ticks = _BACKTICK.findall(rest)
    target = (ticks[0] if ticks else (rest.split() or [""])[0]).strip().rstrip(".,;")
    if not target:
        return None, ["'ADRs: yes' names no directory"]
    adr_dir = target.rstrip("/") + "/"
    d = _inside(repo, target)
    if d is None:
        return adr_dir, [
            f"the declared ADR directory {adr_dir} lies outside the repository"
        ]
    if not d.is_dir():
        return adr_dir, [f"the declared ADR directory {adr_dir} does not exist"]
    if not any(p.name.lower() == "agents.md" for p in d.iterdir()):
        return adr_dir, [
            f"the declared ADR directory {adr_dir} has no {AGENTS_MD} of its own"
        ]
    return adr_dir, []


def read_policy(text: str | None, repo: Path) -> dict:
    """The ADR declaration of a root AGENTS.md, checked against the repository."""
    policy = {
        "status": "undefined",
        "adr_dir": None,
        "alternative": None,
        "lines": [],
        "problems": [],
    }
    if text is None:
        policy["problems"].append(f"the repository has no root {AGENTS_MD}")
        return policy
    decls = _declarations(text)
    if not decls:
        policy["problems"].append(
            f"{AGENTS_MD} does not say whether the project keeps ADRs"
        )
        return policy
    policy["lines"] = [n for n, _, _ in decls]
    if len({a for _, a, _ in decls}) > 1:
        policy["status"] = "inconsistent"
        lines = ", ".join(str(n) for n, _, _ in decls)
        policy["problems"].append(
            f"{AGENTS_MD} answers both yes and no (lines {lines})"
        )
        return policy
    _, answer, rest = decls[0]
    policy["status"] = answer
    if answer == "no":
        policy["alternative"] = rest or None
        if not rest:
            policy["problems"].append(
                "'ADRs: no' names no place where decisions are recorded instead"
            )
    else:
        policy["adr_dir"], problems = _check_adr_dir(rest, repo)
        policy["problems"] += problems
    if policy["problems"]:
        policy["status"] = "inconsistent"
    return policy


def _split_paths(value: str) -> list[str]:
    ticks = _BACKTICK.findall(value)
    items = ticks if ticks else re.split(r"[,\s]+", value.strip().strip("[]"))
    return [i.strip().strip("'\"") for i in items if i.strip().strip("'\"")]


def _frontmatter_end(lines: list[str]) -> int:
    """Index of the first body line; 0 when the text has no frontmatter."""
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i + 1
    return 0


def _frontmatter_fields(lines: list[str]) -> tuple[str | None, list[str]]:
    """status and touches from YAML-like frontmatter lines (no YAML loader)."""
    status, touches, current = None, [], None
    for raw in lines:
        indented = raw.startswith((" ", "\t"))
        m = None if indented else _FIELD.match(raw.strip())
        if m:
            current, val = m.group(1).lower(), m.group(2).strip()
            if current == "status" and val:
                status = val.strip("'\"")
            elif current == "touches" and val:
                touches += _split_paths(val)
        elif not indented:
            current = None
        elif current == "touches" and raw.strip().startswith("- "):
            touches += _split_paths(raw.strip()[2:])
    return status, touches


def _body_fields(lines: list[str]) -> tuple[str | None, str | None, list[str]]:
    """title, status and touches from a record body with bold fields."""
    title, status, touches = None, None, []
    for raw in lines:
        if title is None and raw.startswith("# "):
            title = raw[2:].strip()
        m = _FIELD.match(_plain(raw))
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip()
        if key == "status" and status is None and val:
            status = val
        elif key == "touches" and val:
            touches += _split_paths(val)
    return title, status, touches


def parse_record(text: str) -> dict:
    """Title, status and Touches of one record (frontmatter or bold fields)."""
    lines = text.splitlines()
    start = _frontmatter_end(lines)
    fm_status, fm_touches = _frontmatter_fields(lines[1 : start - 1] if start else [])
    title, body_status, body_touches = _body_fields(lines[start:])
    return {
        "title": title,
        "status": fm_status or body_status,
        "touches": list(dict.fromkeys(fm_touches + body_touches)),
    }


def _is_active(status: str | None) -> bool:
    return not (status and status.strip().lower().startswith(INACTIVE_STATUSES))


def _strip_dot_slash(path: str) -> str:
    """The path without leading "./" segments; "../" and dotfiles stay as written."""
    while path.startswith("./"):
        path = path[2:]
    return path


def _anchor_path(touch: str) -> str:
    return _strip_dot_slash(touch.split("#", 1)[0].strip()) or touch


def anchor_exists(repo: Path, touch: str) -> bool:
    """Whether the anchored path exists below the root; an anchor outside it counts as gone."""
    p = _anchor_path(touch)
    if any(c in p for c in GLOB_CHARS):
        return ".." not in Path(p).parts and any(True for _ in repo.glob(p))
    target = _inside(repo, p)
    return target is not None and target.exists()


def anchor_covers(touch: str, changed: str) -> bool:
    p = _anchor_path(touch).rstrip("/")
    c = _strip_dot_slash(changed)
    if any(ch in p for ch in GLOB_CHARS):
        return fnmatch.fnmatch(c, p)
    return c == p or c.startswith(p + "/")


def agents_sections(text: str) -> list[tuple[str, str]]:
    """The ## / ### sections of AGENTS.md as (heading, body) pairs."""
    sections, head, buf = [], None, []
    for line in text.splitlines():
        if re.match(r"^#{2,3} ", line):
            if head is not None:
                sections.append((head, "\n".join(buf)))
            head, buf = line.lstrip("#").strip(), []
        elif head is not None:
            buf.append(line)
    if head is not None:
        sections.append((head, "\n".join(buf)))
    return sections


def _rule_records(agents_text: str | None) -> list[dict]:
    records = []
    for head, body in agents_sections(agents_text or ""):
        rec = parse_record(body)
        if rec["touches"]:
            records.append({"path": AGENTS_MD, "kind": "rule", **rec, "title": head})
    return records


def _is_record_file(f: Path) -> bool:
    name = f.name.lower()
    return (
        f.suffix.lower() == ".md"
        and name not in NON_RECORD_NAMES
        and not name.startswith("template")
    )


def _adr_records(repo: Path, policy: dict) -> list[dict]:
    if policy["status"] != "yes" or not policy["adr_dir"]:
        return []
    d = _inside(repo, policy["adr_dir"])
    if d is None or not d.is_dir():
        return []
    return [
        {
            "path": f.relative_to(repo).as_posix(),
            "kind": "adr",
            **parse_record(f.read_text(encoding="utf-8", errors="replace")),
        }
        for f in sorted(d.iterdir())
        if f.is_file() and _is_record_file(f)
    ]


def collect_records(repo: Path, agents_text: str | None, policy: dict) -> list[dict]:
    records = _rule_records(agents_text) + _adr_records(repo, policy)
    for rec in records:
        rec["active"] = _is_active(rec["status"])
        rec["missing"] = [t for t in rec["touches"] if not anchor_exists(repo, t)]
    return records


def changed_hits(records: list[dict], changed: list[str]) -> list[dict]:
    hits = []
    for c in changed:
        hit = [
            r
            for r in records
            if r["active"] and any(anchor_covers(t, c) for t in r["touches"])
        ]
        if hit:
            hits.append(
                {
                    "file": c,
                    "records": [
                        {"path": r["path"], "title": r["title"], "status": r["status"]}
                        for r in hit
                    ],
                }
            )
    return hits


def findings_for(policy: dict, records: list[dict], hits: list[dict]) -> list[dict]:
    findings = []
    if policy["status"] in ("undefined", "inconsistent"):
        findings.append(
            {
                "signal": "E7",
                "name": "decision_policy_undefined",
                "status": policy["status"],
                "problems": policy["problems"],
            }
        )
    findings += [
        {
            "signal": "E8",
            "name": "decision_anchor_missing",
            "record": r["path"],
            "title": r["title"],
            "missing": r["missing"],
        }
        for r in records
        if r["active"] and r["missing"]
    ]
    findings += [
        {
            "signal": "E1",
            "name": "decision_record_crossed",
            "file": h["file"],
            "records": h["records"],
            "candidate": True,
        }
        for h in hits
    ]
    return findings


def build_report(repo: Path, changed: list[str]) -> dict:
    agents = repo / AGENTS_MD
    agents_text = (
        agents.read_text(encoding="utf-8", errors="replace")
        if agents.is_file()
        else None
    )
    policy = read_policy(agents_text, repo)
    records = collect_records(repo, agents_text, policy)
    hits = changed_hits(records, changed)
    findings = findings_for(policy, records, hits)
    adr = [r for r in records if r["kind"] == "adr"]
    return {
        "script": "check-decision-records.py",
        "repo": str(repo),
        "agents_md": AGENTS_MD if agents_text is not None else None,
        "policy": policy,
        "summary": {
            "adr_records": len(adr),
            "anchored_records": sum(1 for r in records if r["touches"]),
            "unanchored_adr_records": sum(1 for r in adr if not r["touches"]),
            "records_with_missing_anchors": sum(
                1 for r in records if r["active"] and r["missing"]
            ),
            "changed_files": len(changed),
        },
        "records": records,
        "changed_hits": hits,
        "findings_total": len(findings),
        "findings": findings,
    }


def _text(report: dict) -> str:
    p = report["policy"]
    out = [
        "ADR declaration: {}{}".format(
            p["status"], " ({})".format(p["adr_dir"]) if p["adr_dir"] else ""
        )
    ]
    out += [f"  problem: {x}" for x in p["problems"]]
    s = report["summary"]
    out.append(
        f"records: {s['adr_records']} ADR files, {s['anchored_records']} anchored, "
        f"{s['records_with_missing_anchors']} with missing anchors"
    )
    for f in report["findings"]:
        detail = f.get("missing") or f.get("file") or f.get("status")
        out.append("{} {}: {}".format(f["signal"], f["name"], detail))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read the decision-record declaration and anchors of a repository."
    )
    ap.add_argument(
        "--repo", default=".", help="repository root (default: current directory)"
    )
    ap.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="a path the session changed, relative to the repository root (repeatable)",
    )
    ap.add_argument(
        "--changed-files-from",
        help="file with one changed path per line, or - for stdin",
    )
    ap.add_argument("--output-format", choices=("json", "text"), default="json")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(
            f"check-decision-records.py: not a directory: {repo}",
            file=sys.stderr,
        )
        return 2
    changed = list(args.changed_file)
    if args.changed_files_from:
        try:
            src = (
                sys.stdin.read()
                if args.changed_files_from == "-"
                # S8707: an explicit caller-selected list, read-only at the
                # caller's privilege; no path read from repository content is
                # opened. See docs/SECURITY-ASSURANCE.md.
                else Path(args.changed_files_from).read_text(
                    encoding="utf-8"
                )  # NOSONAR
            )
        except OSError as e:
            print(
                f"check-decision-records.py: cannot read {args.changed_files_from}: {e}",
                file=sys.stderr,
            )
            return 2
        changed += [l.strip() for l in src.splitlines() if l.strip()]
    report = build_report(repo, list(dict.fromkeys(changed)))
    print(
        json.dumps(report, indent=2, ensure_ascii=False)
        if args.output_format == "json"
        else _text(report)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
