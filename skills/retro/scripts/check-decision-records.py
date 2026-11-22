#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "markdown-it-py==4.3.0",
#     "mdit-py-plugins==0.7.0",
#     "PyYAML==6.0.4",
# ]
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
Frontmatter that is not valid YAML (a glob starting with * must be quoted
there) is reported in the record as frontmatter_error.

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
text after it (the adr-tools layout). Markdown is parsed by markdown-it-py
(CommonMark) and frontmatter by PyYAML; only the field names inside a line of
text are matched with patterns here. Changed paths are relative to --repo; an
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
from urllib.parse import unquote

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.front_matter import front_matter_plugin

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

# The field patterns match one line of text that the Markdown parser has
# already taken out of its block. Each has one unbounded group at its end, so
# no input backtracks super-linearly; separators after it are stripped in Python.
_BOLD = r"(?:\*\*|__)?"
_DECL = re.compile(
    rf"^{_BOLD}ADRs?{_BOLD}\s*:{_BOLD}\s*(yes|no|ja|nein)\b(.*)$", re.IGNORECASE
)
_FIELD = re.compile(rf"^{_BOLD}(status|touches){_BOLD}\s*:{_BOLD}(.*)$", re.IGNORECASE)
_ANY_FIELD = re.compile(r"^(?:\*\*|__)?[\w-]+(?: [\w-]+)*(?:\*\*|__)?:")
_SEPARATORS = " \t—–:-"
NON_BINDING_STATUSES = ("proposed", "draft", "vorgeschlagen", "entwurf")
_MD = MarkdownIt("commonmark").use(front_matter_plugin)

Line = tuple[str, list[str], list[str], bool]


def _lines(inline: Token) -> list[Line]:
    """The source lines of a block's text, each with its code spans, link
    targets and whether it is indented. The text is taken as written, so a
    path keeps its __ and **."""
    raw = inline.content.split("\n")
    groups: list[tuple[list[str], list[str]]] = [([], [])]
    codes: list[str] = []
    links: list[tuple[str, str]] = []
    for child in inline.children or []:
        if child.type in ("softbreak", "hardbreak"):
            groups.append(([], []))
        elif child.type == "code_inline":
            groups[-1][0].append(child.content)
            codes.append(child.content)
        elif child.type == "link_open":
            href = str(child.attrs.get("href", ""))
            groups[-1][1].append(unquote(href))
            links.append((href, unquote(href)))
    if len(groups) != len(raw):
        # A code span runs across a line break, so the breaks no longer
        # number the lines: give each line the spans and link targets
        # written whole on it.
        groups = [
            (
                [c for c in codes if f"`{c}`" in r],
                [u for h, u in links if f"]({h}" in r or f"]({u}" in r],
            )
            for r in raw
        ]
    return [(r.strip(), c, ls, r[:1] in (" ", "\t")) for r, (c, ls) in zip(raw, groups)]


def _inside(repo: Path, rel: str) -> Path | None:
    """The path below the repository root, or None when it leaves the root."""
    p = (repo / rel).resolve()
    return p if p == repo or p.is_relative_to(repo) else None


def _declarations(text: str) -> list[tuple[int, str, str, str]]:
    """(line, answer, rest of the line, named directory) per declaration;
    code blocks are examples, the parser leaves them out."""
    decls = []
    for tok in _MD.parse(text):
        if tok.type != "inline" or not tok.map:
            continue
        for n, (line, codes, links, _) in enumerate(_lines(tok), tok.map[0] + 1):
            m = _DECL.match(line)
            if m:
                answer = "yes" if m.group(1).lower() in ("yes", "ja") else "no"
                rest = m.group(2).strip(_SEPARATORS)
                decls.append((n, answer, rest, _dir_key(rest, codes, links)))
    return decls


def _dir_key(rest: str, codes: list[str], links: list[str]) -> str:
    """The directory a yes-declaration names: code span, link target or first word."""
    if codes:
        first = codes[0]
    elif links:
        first = links[0]
    else:
        first = (rest.split() or [""])[0]
    return _strip_dot_slash(first.strip().rstrip(".,;")).rstrip("/")


def _check_adr_dir(target: str, repo: Path) -> tuple[str | None, list[str]]:
    """The directory a yes-declaration names, and what the repository says about it."""
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
    policy["lines"] = [d[0] for d in decls]
    yes_dirs = {d[3] for d in decls if d[1] == "yes"}
    if len({d[1] for d in decls}) > 1 or len(yes_dirs) > 1:
        policy["status"] = "inconsistent"
        lines = ", ".join(str(d[0]) for d in decls)
        policy["problems"].append(
            f"{AGENTS_MD} gives disagreeing ADR declarations (lines {lines})"
        )
        return policy
    _, answer, rest, target = decls[0]
    policy["status"] = answer
    if answer == "no":
        policy["alternative"] = rest or None
        if not rest:
            policy["problems"].append(
                "'ADRs: no' names no place where decisions are recorded instead"
            )
    else:
        policy["adr_dir"], problems = _check_adr_dir(target, repo)
        policy["problems"] += problems
    if policy["problems"]:
        policy["status"] = "inconsistent"
    return policy


def _split_paths(value: str, codes: list[str]) -> list[str]:
    """The paths of a Touches value: its code spans, else its comma- or
    space-separated words."""
    items = codes or re.split(r"[,\s]+", value.strip().strip("[]"))
    return [i.strip().strip("'\"`") for i in items if i.strip().strip("'\"`")]


class _StrictLoader(yaml.BaseLoader):
    """A YAML loader that keeps every scalar as written (no dates, no numbers,
    so 001 stays 001) and rejects a repeated key."""

    def construct_mapping(self, node, deep=False):
        seen: set[str] = set()
        for key_node, _ in node.value:
            key = str(self.construct_scalar(key_node)).lower()
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"repeated key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep)


def _frontmatter(tokens: list[Token]) -> tuple[str | None, list[str], str | None]:
    """status, touches and a parse error from a record's YAML frontmatter."""
    if not tokens or tokens[0].type != "front_matter":
        return None, [], None
    try:
        # BaseLoader builds strings, lists and mappings only; it resolves no tag
        # to a Python object, so this is no less safe than safe_load.
        data = yaml.load(tokens[0].content, Loader=_StrictLoader)  # NOSONAR
    except yaml.YAMLError as e:
        problem = getattr(e, "problem", None) or e
        return None, [], f"frontmatter is not valid YAML: {problem}"
    if not isinstance(data, dict):
        return None, [], None
    fields = {str(k).lower(): v for k, v in data.items()}
    status, touches = fields.get("status"), fields.get("touches") or []
    if isinstance(touches, list):
        paths = [t.strip() for t in touches if isinstance(t, str) and t.strip()]
    else:
        paths = _split_paths(str(touches), [])
    return (status if isinstance(status, str) and status else None), paths, None


class _RecordReader:
    """title, status and touches from the parsed blocks of a record: bold or
    plain fields, a "## Status" heading with the text after it (adr-tools),
    and a Touches field continued by a list or by a line after a comma."""

    def __init__(self) -> None:
        self.title: str | None = None
        self.status: str | None = None
        self.touches: list[str] = []
        self.await_list = False  # an empty Touches field: the next list holds it
        self.status_next = False  # a Status heading: the next text holds it

    def read(self, tokens: list[Token]) -> None:
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if self.await_list and tok.type in (
                "bullet_list_open",
                "ordered_list_open",
            ):
                i = self._list(tokens, i)
            elif tok.type == "heading_open":
                self._heading(tok.tag, tokens[i + 1].content.strip())
                i += 3
            else:
                if tok.type == "inline":
                    self._text(tok)
                i += 1

    def _list(self, tokens: list[Token], start: int) -> int:
        """Read the list that starts at tokens[start]; the index after it. An
        item that is a field ends the paths; it and the rest are read as text."""
        self.await_list = False
        depth, paths = 0, True
        for j in range(start, len(tokens)):
            depth += tokens[j].nesting
            if tokens[j].type == "inline":
                lines = _lines(tokens[j])
                paths = paths and not _ANY_FIELD.match(lines[0][0])
                if paths:
                    for text, codes, _, _ in lines:
                        self.touches += _split_paths(text, codes)
                else:
                    self._text(tokens[j])
            if depth == 0:
                return j + 1
        return len(tokens)

    def _heading(self, tag: str, text: str) -> None:
        self.await_list = False
        if tag == "h1" and self.title is None:
            self.title = text
        self.status_next = tag in ("h2", "h3") and text.lower() == "status"

    def _text(self, inline: Token) -> None:
        lines = _lines(inline)
        if self.status_next:
            self.status_next = False
            if self.status is None and lines[0][0]:
                self.status = lines[0][0]
            lines = lines[1:]
        wrap = False
        for text, codes, _, indented in lines:
            self.await_list = False
            continued = indented or text.startswith("`")
            if wrap and continued and not _ANY_FIELD.match(text):
                self.touches += _split_paths(text, codes)
                wrap = text.endswith(",")
                continue
            wrap = False
            m = _FIELD.match(text)
            if m:
                wrap = self._field(m.group(1).lower(), m.group(2).strip(), codes)

    def _field(self, key: str, val: str, codes: list[str]) -> bool:
        """Record one field; whether the next line continues it."""
        if key == "status":
            if self.status is None and val:
                self.status = val
            return False
        self.touches += _split_paths(val, codes)
        self.await_list = not val
        return val.endswith(",")


def _read_blocks(tokens: list[Token]) -> dict:
    reader = _RecordReader()
    reader.read(tokens)
    return {"title": reader.title, "status": reader.status, "touches": reader.touches}


def parse_record(text: str) -> dict:
    """Title, status and Touches of one record (frontmatter or fields in the body)."""
    tokens = _MD.parse(text)
    fm_status, fm_touches, fm_error = _frontmatter(tokens)
    body = _read_blocks(tokens)
    rec = {
        "title": body["title"],
        "status": fm_status or body["status"],
        "touches": list(dict.fromkeys(fm_touches + body["touches"])),
    }
    if fm_error:
        rec["frontmatter_error"] = fm_error
    return rec


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
            body = pattern[i + 1 : j].replace("\\", "\\\\").replace("[", "\\[")
            out.append(
                "[^" + body[1:] + "]" if body.startswith("!") else "[" + body + "]"
            )
            i = j + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    try:
        return re.compile("".join(out) + r"\Z")
    except re.error:
        # An unbalanced character class: match the pattern as written.
        return re.compile(re.escape(pattern) + r"\Z")


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


def _exists_as_written(repo: Path, touch: str) -> bool:
    """Whether the anchor names an existing path without glob expansion."""
    p = _anchor_path(touch)
    if ".." in Path(p).parts:
        return False
    target = _inside(repo, p)
    return target is not None and target.exists()


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


def anchor_covers(touch: str, changed: str, literal: bool = False) -> bool:
    """Whether a changed path is the anchor, lies below it, or lies below a
    directory its glob names."""
    p = _anchor_path(touch).rstrip("/")
    c = _strip_dot_slash(changed)
    if p in ("", ".") or c == p or c.startswith(p + "/"):
        return True
    if literal or not any(ch in p for ch in GLOB_CHARS):
        return False
    rx = _glob_regex(p)
    parts = c.split("/")
    return any(rx.match("/".join(parts[:i])) for i in range(1, len(parts) + 1))


def agents_sections(text: str) -> list[tuple[str, list[Token]]]:
    """The ## / ### sections of AGENTS.md as (heading, parsed blocks) pairs."""
    tokens = _MD.parse(text)
    sections: list[tuple[str, list[Token]]] = []
    head, start = None, 0
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open" and tok.level == 0 and tok.tag in ("h2", "h3"):
            if head is not None:
                sections.append((head, tokens[start:i]))
            head, start = tokens[i + 1].content.strip(), i + 3
    if head is not None:
        sections.append((head, tokens[start:]))
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
        for head, blocks in agents_sections(text):
            rec = _read_blocks(blocks)
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
        rec["literal"] = [t for t in rec["touches"] if _exists_as_written(repo, t)]
    return records


def changed_hits(records: list[dict], changed: list[str]) -> list[dict]:
    hits = []
    for c in changed:
        hit = [
            r
            for r in records
            if r["active"]
            and any(
                anchor_covers(t, c, t in r.get("literal", ())) for t in r["touches"]
            )
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


def _git_unquote(path: str) -> str:
    """A path as git prints it with core.quotePath: "src/\\303\\274ber.py" -> src/über.py."""
    if not (len(path) >= 2 and path[0] == path[-1] == '"'):
        return path
    inner = path[1:-1]
    try:
        raw = inner.encode("ascii").decode("unicode_escape")
        return raw.encode("latin-1").decode("utf-8")
    except UnicodeError:
        # Not git's escaped ASCII form (quotePath=false leaves UTF-8 as is).
        return inner


def _relative_changes(repo: Path, changed: list[str]) -> tuple[list[str], list[str]]:
    """Changed paths relative to the root; an absolute path inside the root is
    made relative, one outside it is listed as ignored."""
    kept, ignored = [], []
    for c in map(_git_unquote, changed):
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
