#!/usr/bin/env python3
"""check-upstream-sources.py — mechanical upstream-drift pre-pass for
`/retro audit --scope skill`.

Scans a skill repository for claims that delegate authority to an external
canonical source and checks the *mechanically checkable* half of the drift
question:

- markdown links on lines carrying an ``[upstream]`` provenance label in
  ``references/*.md`` (and the skill's ``SKILL.md``) — is the URL still
  alive?
- ``source:`` URLs in ``checkpoints.yaml`` entries — alive? — and their
  ``verified:`` dates — older than ``--max-age-days``?

Whether the live page still *says* what the local summary claims is the LLM
half of the audit and is deliberately out of scope here; this script only
tells the auditor which sources are dead, redirected away, or overdue for a
re-read.

Probe discipline: a failed request is a transport fact before it is a
finding. Only 404/410 count as ``upstream_source_dead``; timeouts, TLS
errors, 403s and 5xx are emitted as ``upstream_probe_failed`` (unknown →
re-check), never as "the page is gone".

Output mirrors detect-mechanical.py: a JSON envelope with ``findings``
carrying ``signal: B14`` (doc drift) candidates for the classifier. Exit
code is 0 unless ``--strict`` is given and at least one dead or stale
finding exists.

checkpoints.yaml is read line-based for three scalar keys (``provenance:``,
``source:``, ``verified:``) so the script stays stdlib-only; the keys are
flat scalars by schema, so this is safe.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import http.client
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

MD_LINK = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
BARE_URL = re.compile(r"(?<!\()(https?://[^\s)\"'`>]+)")
UPSTREAM_MARK = re.compile(r"\[upstream\]", re.IGNORECASE)
VERIFIED_RE = re.compile(r"^\s*verified:\s*[\"']?(\d{4}-\d{2}-\d{2})")
SOURCE_RE = re.compile(r"^\s*source:\s*(.*)$")
ID_RE = re.compile(r"^\s*-\s+id:\s*[\"']?([A-Za-z0-9_-]+)")

USER_AGENT = (
    "retro-skill-upstream-check/1.0 (+https://github.com/netresearch/retro-skill)"
)
# One line of context on each side: the label and its link are frequently
# split across a wrapped line ("[Foo](url)\n`[upstream]`").
LABEL_WINDOW = 1


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:")


def collect_markdown(root: Path) -> list[dict]:
    """URLs on (or one line around) an [upstream]-labelled line."""
    out: list[dict] = []
    files = sorted(root.glob("references/*.md")) + [
        p for p in [root / "SKILL.md"] if p.is_file()
    ]
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        marked = {i for i, line in enumerate(lines) if UPSTREAM_MARK.search(line)}
        wanted: set[int] = set()
        for i in marked:
            for j in range(i - LABEL_WINDOW, i + LABEL_WINDOW + 1):
                if 0 <= j < len(lines):
                    wanted.add(j)
        for i in sorted(wanted):
            for match in MD_LINK.finditer(lines[i]):
                out.append(
                    {
                        "url": _clean_url(match.group(1)),
                        "file": str(path.relative_to(root)),
                        "line": i + 1,
                        "origin": "markdown [upstream] label",
                    }
                )
    return out


def _scan_checkpoint_line(
    line: str, lineno: int, rel: str, current_id: str, urls: list, verified: list
) -> str:
    """Handle one checkpoints.yaml line; returns the (possibly new) entry id."""
    m = ID_RE.match(line)
    if m:
        return m.group(1)
    m = SOURCE_RE.match(line)
    if m:
        value = m.group(1).strip().strip("\"'")
        for match in BARE_URL.finditer(value):
            urls.append(
                {
                    "url": _clean_url(match.group(0)),
                    "file": rel,
                    "line": lineno,
                    "origin": f"checkpoint {current_id} source",
                }
            )
        return current_id
    m = VERIFIED_RE.match(line)
    if m:
        verified.append(
            {
                "checkpoint": current_id,
                "date": m.group(1),
                "file": rel,
                "line": lineno,
            }
        )
    return current_id


def collect_checkpoints(root: Path) -> tuple[list[dict], list[dict]]:
    """(url occurrences, stale-candidates) from checkpoints.yaml source:/verified:."""
    urls: list[dict] = []
    verified: list[dict] = []
    path = root / "checkpoints.yaml"
    if not path.is_file():
        return urls, verified
    rel = str(path.relative_to(root))
    current_id = "?"
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        current_id = _scan_checkpoint_line(line, i + 1, rel, current_id, urls, verified)
    return urls, verified


def probe(url: str, timeout: float) -> tuple[str, int | None, str]:
    """→ (verdict, status, detail); verdict ∈ ok|dead|probe_failed."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    last_status: int | None = None
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(
            url, method=method, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return "ok", resp.status, ""
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            if exc.code in (404, 410):
                return "dead", exc.code, f"HTTP {exc.code}"
            if exc.code == 405 and method == "HEAD":
                continue  # server rejects HEAD; retry as GET
            return "probe_failed", exc.code, f"HTTP {exc.code} (not proof of absence)"
        except (OSError, http.client.HTTPException, ValueError) as exc:
            # timeout, TLS, DNS, malformed URL — transport, not absence
            return "probe_failed", last_status, f"{type(exc).__name__}: {exc}"
    return "probe_failed", last_status, "HEAD and GET both rejected"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--skill-dir",
        default=".",
        help="skill directory (containing SKILL.md/references/checkpoints.yaml); "
        "repo roots are searched under skills/*/",
    )
    ap.add_argument("--max-age-days", type=int, default=180)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--offline", action="store_true", help="skip network probes")
    ap.add_argument("--output-format", choices=["json", "text"], default="json")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when dead links or stale verifications were found",
    )
    args = ap.parse_args()

    base = Path(args.skill_dir)
    roots = [base]
    if not (base / "SKILL.md").is_file():
        roots = sorted(p.parent for p in base.glob("skills/*/SKILL.md"))
    if not roots:
        print(f"error: no SKILL.md under {base}", file=sys.stderr)
        return 2

    occurrences: list[dict] = []
    stale_candidates: list[dict] = []
    for root in roots:
        occurrences.extend(collect_markdown(root))
        urls, verified = collect_checkpoints(root)
        occurrences.extend(urls)
        stale_candidates.extend(verified)

    findings = stale_findings(stale_candidates, args.max_age_days)

    unique: dict[str, list[dict]] = {}
    for occ in occurrences:
        unique.setdefault(occ["url"], []).append(occ)

    probed = 0
    if not args.offline:
        findings.extend(probe_findings(unique, args.timeout))
        probed = len(unique)

    envelope = {
        "skill_dirs": [str(r) for r in roots],
        "urls_total": len(unique),
        "urls_probed": probed,
        "verified_dates_total": len(stale_candidates),
        "findings_total": len(findings),
        "findings": findings,
    }
    render(envelope, args.output_format)

    if args.strict and any(
        f["name"] in ("upstream_source_dead", "upstream_verification_stale")
        for f in findings
    ):
        return 1
    return 0


def stale_findings(candidates: list[dict], max_age_days: int) -> list[dict]:
    out: list[dict] = []
    today = _dt.datetime.now(_dt.timezone.utc).date()
    for entry in candidates:
        age = (today - _dt.date.fromisoformat(entry["date"])).days
        if age > max_age_days:
            out.append(
                {
                    "signal": "B14",
                    "name": "upstream_verification_stale",
                    "file": entry["file"],
                    "line": entry["line"],
                    "checkpoint": entry["checkpoint"],
                    "verified": entry["date"],
                    "age_days": age,
                    "detail": f"verified {age} days ago (max {max_age_days}) — re-read the source",
                }
            )
    return out


def probe_findings(unique: dict[str, list[dict]], timeout: float) -> list[dict]:
    out: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(
            zip(
                sorted(unique),
                pool.map(lambda u: probe(u, timeout), sorted(unique)),
            )
        )
    for url, occs in sorted(unique.items()):
        verdict, status, detail = results[url]
        if verdict == "ok":
            continue
        name = "upstream_source_dead" if verdict == "dead" else "upstream_probe_failed"
        for occ in occs:
            out.append(
                {
                    "signal": "B14",
                    "name": name,
                    "url": url,
                    "file": occ["file"],
                    "line": occ["line"],
                    "origin": occ["origin"],
                    "status": status,
                    "detail": detail,
                }
            )
    return out


def render(envelope: dict, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(envelope, indent=2))
        return
    print(
        f"URLs: {envelope['urls_total']} ({envelope['urls_probed']} probed) — "
        f"verified dates: {envelope['verified_dates_total']} — "
        f"findings: {envelope['findings_total']}"
    )
    for f in envelope["findings"]:
        loc = f"{f['file']}:{f['line']}"
        print(
            f"  [{f['name']}] {loc} {f.get('url', f.get('checkpoint', ''))} — {f['detail']}"
        )


if __name__ == "__main__":
    sys.exit(main())
