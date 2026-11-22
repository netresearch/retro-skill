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
- E8 decision_anchor_missing — a binding record names a path that no longer
  exists. The record may describe code that has moved or gone.
- E1 decision_record_crossed — with --changed-file, a changed path lies under
  the anchor of a binding record. This is a candidate only: the
  reading pass decides whether the change contradicts the decision.

Only paths are matched. Names in a record's prose are not compared with the
code: Trail-Code measured that approach on 2026-10-29 and 9 of the 10 records
it flagged still matched the code (trailhq/Trail-Code, learning l-3cfeb3b1).
A record without a Touches field is reported as unanchored, not as an error.

Accepted declaration lines in AGENTS.md (list markers and bold are ignored):

    ADRs: yes — `docs/adr/`
    ADRs: no — decisions are recorded in the PR description

Accepted anchors in a record (an ADR file, or a section of any AGENTS.md in
the repository), on one line, wrapped, or as a list below the field:

    **Touches:** `src/retry.py`, `config/`
    touches:            (YAML frontmatter list)
      - src/retry.py

A path is relative to the repository root, also with a leading slash. It may
name a file, a directory (everything below it) or a glob, where * and ? stay
within one directory and ** spans directories. A `#Symbol` suffix is accepted
and ignored, and so is a YAML comment. A path that exists as written is not
read as a glob. A record binds unless its status starts with superseded,
deprecated, rejected, withdrawn, retired, proposed or draft, or a German
form of these. Lines inside
fenced code blocks are examples, not declarations or records. The status is
read from a bold or frontmatter field, or from a "## Status" heading and the
line after it (the adr-tools layout). Changed paths are relative to --repo; an
absolute one inside it is made relative, one outside it is listed as ignored.

Usage:
    uv run check-decision-records.py [--repo DIR] [--changed-file PATH ...]
        [--changed-files-from FILE|-] [--output-format json|text]

Exit status: 0 when the check ran (findings are in the output), 2 on a usage
error or an unreadable repository.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

AGENTS_MD = "AGENTS.md"
INACTIVE_STATUSES = (
    "superseded",
    "deprecated",
    "rejected",
    "withdrawn",
    "retired",
    "abgelöst",
    "ersetzt",
    "verworfen",
    "zurückgezogen",
)
NON_RECORD_NAMES = {"agents.md", "readme.md", "index.md", "claude.md"}
GLOB_CHARS = "*?["

# Each pattern has one unbounded group at its end, so no input backtracks
# super-linearly; separators after it are stripped in Python.
_BOLD = r"(?:\*\*|__)?"
_DECL = re.compile(
    rf"^{_BOLD}ADRs?{_BOLD}\s*:{_BOLD}\s*(yes|no|ja|nein)\b(.*)$", re.IGNORECASE
)
_FIELD = re.compile(rf"^{_BOLD}(status|touches){_BOLD}\s*:{_BOLD}(.*)$", re.IGNORECASE)
_STATUS_HEADING = re.compile(r"^#{2,3}\s+status\s*$", re.IGNORECASE)
_BACKTICK = re.compile(r"`([^`]+)`")
_LIST_MARKER = re.compile(r"^(?:[-*+]|\d+\.)\s+")
_SEPARATORS = " \t—–:-"
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
NON_BINDING_STATUSES = ("proposed", "draft", "vorgeschlagen", "entwurf")


def _plain(line: str) -> str:
    """A line without its list marker; bold around a field name is matched by
    the field patterns, so paths keep their __ and **."""
    return _LIST_MARKER.sub("", line.strip()).strip()


def _unfenced(lines: list[str]) -> list[str]:
    """The lines outside fenced code blocks; examples in fences are not records."""
    out, fence = [], None
    for line in lines:
        m = _FENCE.match(line)
        if m and (
            fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)
        ):
            fence = m.group(1) if fence is None else None
            continue
        if fence is None:
            out.append(line)
    return out


def _inside(repo: Path, rel: str) -> Path | None:
    """The path below the repository root, or None when it leaves the root."""
    p = (repo / rel).resolve()
    return p if p == repo or p.is_relative_to(repo) else None


def _declarations(text: str) -> list[tuple[int, str, str]]:
    decls = []
    lines = text.splitlines()
    kept = set(map(id, _unfenced(lines)))
    for n, line in enumerate(lines, 1):
        if id(line) not in kept:
            continue
        m = _DECL.match(_plain(line))
        if m:
            answer = "yes" if m.group(1).lower() in ("yes", "ja") else "no"
            decls.append((n, answer, m.group(2).strip(_SEPARATORS)))
    return decls


def _strip_yaml_comment(value: str) -> str:
    """The value without a trailing YAML comment (a # after whitespace)."""
    for i in range(1, len(value)):
        if value[i] == "#" and value[i - 1].isspace():
            return value[:i].rstrip()
    return value


def _dir_key(rest: str) -> str:
    """The directory a yes-declaration names: code span, link target or first word."""
    ticks = _BACKTICK.findall(rest)
    links = _LINK.findall(rest)
    if ticks:
        first = ticks[0]
    elif links:
        first = links[0]
    else:
        first = (rest.split() or [""])[0]
    return _strip_dot_slash(first.strip().rstrip(".,;")).rstrip("/")


def _check_adr_dir(rest: str, repo: Path) -> tuple[str | None, list[str]]:
    """The directory a yes-declaration names, and what the repository says about it."""
    target = _dir_key(rest)
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
    yes_dirs = {_dir_key(r) for _, a, r in decls if a == "yes"}
    if len({a for _, a, _ in decls}) > 1 or len(yes_dirs) > 1:
        policy["status"] = "inconsistent"
        lines = ", ".join(str(n) for n, _, _ in decls)
        policy["problems"].append(
            f"{AGENTS_MD} gives disagreeing ADR declarations (lines {lines})"
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


def _frontmatter_list_item(raw: str) -> str | None:
    """The value of a YAML list item, at column 0 or indented, else None."""
    item = raw.strip()
    return _strip_yaml_comment(item[2:]) if item.startswith("- ") else None


class _FrontmatterReader:
    """status and touches from YAML-like frontmatter lines (no YAML loader)."""

    def __init__(self) -> None:
        self.status: str | None = None
        self.touches: list[str] = []
        self.current: str | None = None

    def feed(self, raw: str) -> None:
        indented = raw.startswith((" ", "\t"))
        m = None if indented else _FIELD.match(raw.strip())
        if m:
            self._field(m.group(1).lower(), _strip_yaml_comment(m.group(2).strip()))
        elif self.current == "touches" and (indented or raw.startswith("- ")):
            item = _frontmatter_list_item(raw)
            if item is not None:
                self.touches += _split_paths(item)
        elif not indented:
            self.current = None

    def _field(self, key: str, val: str) -> None:
        self.current = key
        if key == "status" and val:
            self.status = val.strip("'\"")
        elif key == "touches" and val:
            self.touches += _split_paths(val)


def _frontmatter_fields(lines: list[str]) -> tuple[str | None, list[str]]:
    """status and touches from YAML-like frontmatter lines (no YAML loader)."""
    reader = _FrontmatterReader()
    for raw in lines:
        reader.feed(raw)
    return reader.status, reader.touches


_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_ANY_FIELD = re.compile(r"^(?:\*\*|__)?[\w-]+(?: [\w-]+)*(?:\*\*|__)?:")


def _touches_continuation(raw: str, mode: str) -> bool:
    """Whether a line continues a Touches field. After an empty value, list
    items continue it ("list"); after a value ending in a comma, one indented
    or code-span line does ("wrap"). A line that is itself a field ends it."""
    item = _plain(raw)
    if not raw.strip():
        # A formatter puts a blank line between a field and its list (MD032).
        return mode == "list"
    if raw.startswith("#") or _ANY_FIELD.match(item):
        return False
    if mode == "list":
        return _LIST_ITEM.match(raw) is not None
    return mode == "wrap" and (
        raw.startswith((" ", "\t")) or raw.lstrip().startswith("`")
    )


def _touches_mode_after(value: str, mode: str) -> str:
    """How a Touches field continues after a line with this value."""
    if value.rstrip().endswith(","):
        return "wrap"
    if mode == "list":
        return "list"
    return ""


def _touches_mode_for_field(value: str) -> str:
    """How a Touches field continues after its own line."""
    if not value:
        return "list"
    return "wrap" if value.endswith(",") else ""


def _status_after_heading(raw: str) -> str | None:
    """The status written on the line after a "## Status" heading."""
    return None if raw.lstrip().startswith("#") else _plain(raw)


class _BodyReader:
    """title, status and touches from a record body: bold fields, or a
    "## Status" heading followed by its value (the adr-tools layout)."""

    def __init__(self) -> None:
        self.title: str | None = None
        self.status: str | None = None
        self.touches: list[str] = []
        self.status_next = False
        self.touches_mode = ""

    def feed(self, raw: str) -> None:
        if self._continue_touches(raw):
            return
        if self.title is None and raw.startswith("# "):
            self.title = raw[2:].strip()
        if self._status_heading(raw):
            return
        m = _FIELD.match(_plain(raw))
        if m:
            self._field(m.group(1).lower(), m.group(2).strip())

    def _continue_touches(self, raw: str) -> bool:
        if not self.touches_mode:
            return False
        if not _touches_continuation(raw, self.touches_mode):
            self.touches_mode = ""
            return False
        if raw.strip():
            line = _plain(raw)
            self.touches += _split_paths(line)
            self.touches_mode = _touches_mode_after(line, self.touches_mode)
        return True

    def _status_heading(self, raw: str) -> bool:
        if _STATUS_HEADING.match(raw.strip()):
            self.status_next = True
            return True
        if not (self.status_next and raw.strip()):
            return False
        self.status_next = False
        self.status = self.status or _status_after_heading(raw)
        return True

    def _field(self, key: str, val: str) -> None:
        if key == "status" and self.status is None and val:
            self.status = val
        elif key == "touches":
            self.touches += _split_paths(val)
            self.touches_mode = _touches_mode_for_field(val)


def _body_fields(lines: list[str]) -> tuple[str | None, str | None, list[str]]:
    """title, status and touches from a record body."""
    reader = _BodyReader()
    for raw in _unfenced(lines):
        reader.feed(raw)
    return reader.title, reader.status, reader.touches


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
    """Whether a record binds: not superseded or retired, and not merely proposed."""
    s = (status or "").strip().lower()
    return not s.startswith(INACTIVE_STATUSES + NON_BINDING_STATUSES)


def _strip_dot_slash(path: str) -> str:
    """The path without leading "./" segments; "../" and dotfiles stay as written."""
    while path.startswith(("./", "/")):
        path = path[2:] if path.startswith("./") else path[1:]
    return path


def _anchor_path(touch: str) -> str:
    return _strip_dot_slash(touch.split("#", 1)[0].strip()) or touch


def _glob_regex(pattern: str) -> re.Pattern:
    """A glob as a regular expression with Path.glob's meaning: * and ? stay
    within one path segment, ** spans segments."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[" and "]" in pattern[i + 1 :]:
            j = pattern.index("]", i + 1)
            body = pattern[i + 1 : j].replace("\\", "\\\\")
            out.append(
                "[^" + body[1:] + "]" if body.startswith("!") else "[" + body + "]"
            )
            i = j + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _glob_matches(repo: Path, pattern: str) -> bool:
    """Whether a glob matches a path below the root, without leaving it."""
    try:
        matches = repo.glob(pattern)
        return any(_inside(repo, str(m.relative_to(repo))) is not None for m in matches)
    except (ValueError, NotImplementedError):
        # Path.glob refuses some patterns (** inside a segment on 3.11); match
        # the walked tree with the same meaning instead.
        rx = _glob_regex(pattern)
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d != ".git"]
            base = Path(root).relative_to(repo)
            for name in dirs + files:
                if rx.match((base / name).as_posix()):
                    return True
        return False


def anchor_exists(repo: Path, touch: str) -> bool:
    """Whether the anchored path exists below the root; an anchor outside it,
    also through a symbolic link, counts as gone. A path that exists as
    written (a route file such as app/[slug]/page.tsx) is not read as a glob."""
    p = _anchor_path(touch)
    if ".." in Path(p).parts:
        return False
    target = _inside(repo, p)
    if target is not None and target.exists():
        return True
    return any(c in p for c in GLOB_CHARS) and _glob_matches(repo, p)


def anchor_covers(touch: str, changed: str) -> bool:
    """Whether a changed path is the anchor, lies below it, or lies below a
    directory its glob names."""
    p = _anchor_path(touch).rstrip("/")
    c = _strip_dot_slash(changed)
    if p in ("", ".") or c == p or c.startswith(p + "/"):
        return True
    if not any(ch in p for ch in GLOB_CHARS):
        return False
    rx = _glob_regex(p)
    parts = c.split("/")
    return any(rx.match("/".join(parts[:i])) for i in range(1, len(parts) + 1))


def agents_sections(text: str) -> list[tuple[str, str]]:
    """The ## / ### sections of AGENTS.md as (heading, body) pairs."""
    sections, head, buf = [], None, []
    for line in _unfenced(text.splitlines()):
        if re.match(r"^#{2,3} ", line):
            if head is not None:
                sections.append((head, "\n".join(buf)))
            head, buf = line.lstrip("#").strip(), []
        elif head is not None:
            buf.append(line)
    if head is not None:
        sections.append((head, "\n".join(buf)))
    return sections


SKIP_DIRS = {".git", "node_modules", "vendor", ".venv"}


def _agents_files(repo: Path) -> list[Path]:
    """Every AGENTS.md below the root, the root file first."""
    found = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        if AGENTS_MD in files:
            found.append(Path(root) / AGENTS_MD)
    return found


def _rule_records(repo: Path) -> list[dict]:
    """Sections with a Touches field in any AGENTS.md of the repository."""
    records = []
    for path in _agents_files(repo):
        if _inside(repo, str(path.relative_to(repo))) is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for head, body in agents_sections(text):
            rec = parse_record(body)
            if rec["touches"]:
                records.append(
                    {
                        "path": path.relative_to(repo).as_posix(),
                        "kind": "rule",
                        **rec,
                        "title": head,
                    }
                )
    return records


def _is_record_file(f: Path) -> bool:
    name = f.name.lower()
    return (
        f.suffix.lower() == ".md"
        and name not in NON_RECORD_NAMES
        and "template" not in name
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
        if f.is_file()
        and _is_record_file(f)
        and _inside(repo, str(f.relative_to(repo))) is not None
    ]


def collect_records(repo: Path, policy: dict) -> list[dict]:
    records = _rule_records(repo) + _adr_records(repo, policy)
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


def _relative_changes(repo: Path, changed: list[str]) -> tuple[list[str], list[str]]:
    """Changed paths relative to the root; an absolute path inside the root is
    made relative, one outside it is listed as ignored."""
    kept, ignored = [], []
    for c in changed:
        if Path(c).is_absolute():
            try:
                kept.append(Path(c).resolve().relative_to(repo).as_posix())
            except ValueError:
                ignored.append(c)
        else:
            kept.append(c)
    return kept, ignored


def build_report(repo: Path, changed: list[str]) -> dict:
    agents = repo / AGENTS_MD
    agents_text = (
        agents.read_text(encoding="utf-8", errors="replace")
        if agents.is_file()
        else None
    )
    policy = read_policy(agents_text, repo)
    records = collect_records(repo, policy)
    changed, ignored = _relative_changes(repo, changed)
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
        "ignored_changed_files": ignored,
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


def _read_changed_list(source: str) -> str:
    """The changed-path list named by --changed-files-from, or stdin for "-"."""
    if source == "-":
        return sys.stdin.read()
    # S8707: an explicit caller-selected list, read-only at the caller's
    # privilege; no path read from repository content is opened here.
    # See docs/SECURITY-ASSURANCE.md.
    return Path(source).read_text(encoding="utf-8")  # NOSONAR


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
            src = _read_changed_list(args.changed_files_from)
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
