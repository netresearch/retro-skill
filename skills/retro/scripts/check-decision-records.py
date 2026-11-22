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

INACTIVE_STATUSES = ("superseded", "deprecated", "rejected", "withdrawn", "retired")
NON_RECORD_NAMES = {"agents.md", "readme.md", "index.md", "claude.md"}

_DECL = re.compile(r"^ADRs?\s*:\s*(yes|no|ja|nein)\b\s*[—–:-]?\s*(.*)$", re.IGNORECASE)
_FIELD = re.compile(r"^(status|touches)\s*:\s*(.*)$", re.IGNORECASE)
_BACKTICK = re.compile(r"`([^`]+)`")


def _plain(line: str) -> str:
    """A line without list markers, bold markers and surrounding space."""
    s = line.strip()
    s = re.sub(r"^(?:[-*+]|\d+\.)\s+", "", s)
    return s.replace("**", "").replace("__", "").strip()


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
        policy["problems"].append("the repository has no root AGENTS.md")
        return policy
    decls = []
    for n, line in enumerate(text.splitlines(), 1):
        m = _DECL.match(_plain(line))
        if m:
            answer = "yes" if m.group(1).lower() in ("yes", "ja") else "no"
            decls.append((n, answer, m.group(2).strip()))
    if not decls:
        policy["problems"].append(
            "AGENTS.md does not say whether the project keeps ADRs"
        )
        return policy
    policy["lines"] = [n for n, _, _ in decls]
    answers = {a for _, a, _ in decls}
    if len(answers) > 1:
        policy["status"] = "inconsistent"
        policy["problems"].append(
            "AGENTS.md answers both yes and no (lines {})".format(
                ", ".join(str(n) for n, _, _ in decls)
            )
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
        ticks = _BACKTICK.findall(rest)
        target = (
            (ticks[0] if ticks else (rest.split() or [""])[0]).strip().rstrip(".,;")
        )
        if not target:
            policy["problems"].append("'ADRs: yes' names no directory")
        else:
            policy["adr_dir"] = target.rstrip("/") + "/"
            d = repo / target
            if not d.is_dir():
                policy["problems"].append(
                    "the declared ADR directory {} does not exist".format(
                        policy["adr_dir"]
                    )
                )
            elif not any(p.name.lower() == "agents.md" for p in d.iterdir()):
                policy["problems"].append(
                    "the declared ADR directory {} has no AGENTS.md of its own".format(
                        policy["adr_dir"]
                    )
                )
    if policy["problems"]:
        policy["status"] = "inconsistent"
    return policy


def _split_paths(value: str) -> list[str]:
    ticks = _BACKTICK.findall(value)
    items = ticks if ticks else re.split(r"[,\s]+", value.strip().strip("[]"))
    return [i.strip().strip("'\"") for i in items if i.strip().strip("'\"")]


def parse_record(text: str) -> dict:
    """Title, status and Touches of one record (frontmatter or bold fields)."""
    status, touches, title = None, [], None
    lines = text.splitlines()
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
        fm = lines[1 : body_start - 1] if body_start else []
        current = None
        for raw in fm:
            m = _FIELD.match(raw.strip())
            if m and not raw.startswith((" ", "\t")):
                current = m.group(1).lower()
                val = m.group(2).strip()
                if current == "status" and val:
                    status = val.strip("'\"")
                elif current == "touches" and val:
                    touches += _split_paths(val)
                continue
            if not raw.startswith((" ", "\t")):
                current = None
            elif current == "touches" and raw.strip().startswith("- "):
                touches += _split_paths(raw.strip()[2:])
    for raw in lines[body_start:]:
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
    return {"title": title, "status": status, "touches": list(dict.fromkeys(touches))}


def _is_active(status: str | None) -> bool:
    return not (status and status.strip().lower().startswith(INACTIVE_STATUSES))


def _anchor_path(touch: str) -> str:
    return touch.split("#", 1)[0].strip().lstrip("./") or touch


def anchor_exists(repo: Path, touch: str) -> bool:
    p = _anchor_path(touch)
    if any(c in p for c in "*?["):
        return any(True for _ in repo.glob(p))
    return (repo / p).exists()


def anchor_covers(touch: str, changed: str) -> bool:
    p = _anchor_path(touch).rstrip("/")
    c = changed.lstrip("./")
    if any(ch in p for ch in "*?["):
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


def collect_records(repo: Path, agents_text: str | None, policy: dict) -> list[dict]:
    records = []
    if agents_text:
        for head, body in agents_sections(agents_text):
            rec = parse_record(body)
            if rec["touches"]:
                records.append(
                    {"path": "AGENTS.md", "kind": "rule", "title": head, **rec}
                )
    if policy["status"] == "yes" and policy["adr_dir"]:
        d = repo / policy["adr_dir"]
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if (
                    f.suffix.lower() != ".md"
                    or f.name.lower() in NON_RECORD_NAMES
                    or f.name.lower().startswith("template")
                ):
                    continue
                rec = parse_record(f.read_text(encoding="utf-8", errors="replace"))
                records.append(
                    {"path": f.relative_to(repo).as_posix(), "kind": "adr", **rec}
                )
    for rec in records:
        rec["active"] = _is_active(rec["status"])
        rec["missing"] = [t for t in rec["touches"] if not anchor_exists(repo, t)]
    return records


def build_report(repo: Path, changed: list[str]) -> dict:
    agents = repo / "AGENTS.md"
    agents_text = (
        agents.read_text(encoding="utf-8", errors="replace")
        if agents.is_file()
        else None
    )
    policy = read_policy(agents_text, repo)
    records = collect_records(repo, agents_text, policy)
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
    for rec in records:
        if rec["active"] and rec["missing"]:
            findings.append(
                {
                    "signal": "E8",
                    "name": "decision_anchor_missing",
                    "record": rec["path"],
                    "title": rec["title"],
                    "missing": rec["missing"],
                }
            )
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
    for h in hits:
        findings.append(
            {
                "signal": "E1",
                "name": "decision_record_crossed",
                "file": h["file"],
                "records": h["records"],
                "candidate": True,
            }
        )
    anchored = [r for r in records if r["touches"]]
    adr_files = 0
    if (
        policy["status"] == "yes"
        and policy["adr_dir"]
        and (repo / policy["adr_dir"]).is_dir()
    ):
        adr_files = sum(1 for r in records if r["kind"] == "adr")
    return {
        "script": "check-decision-records.py",
        "repo": str(repo),
        "agents_md": "AGENTS.md" if agents_text is not None else None,
        "policy": policy,
        "summary": {
            "adr_records": adr_files,
            "anchored_records": len(anchored),
            "unanchored_adr_records": sum(
                1 for r in records if r["kind"] == "adr" and not r["touches"]
            ),
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
                else Path(args.changed_files_from).read_text(encoding="utf-8")
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
