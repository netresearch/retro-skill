#!/usr/bin/env python3
"""
find-org-skills.py — discover every skill available to the user, installed or not.

Reads the marketplaces Claude Code has configured (~/.claude/plugins/
known_marketplaces.json) and each one's locally-cloned catalogue
(<installLocation>/.claude-plugin/marketplace.json), then marks which catalogue
entries are actually installed (present in the local plugin cache, keyed by
plugin name).

This is the full picture retro-skill needs to classify a learning correctly:
the owning skill may exist in the org catalogue without being installed locally,
and a colleague may simply be missing a skill that already exists. Discovering
only *installed* skills (find-installed-skills.sh) cannot see either case.

Offline by design: the catalogue manifests are kept in sync on disk by Claude
Code, so no network or `gh` auth is required. Generic by design: it reads
whatever marketplaces are configured, never a hardcoded org.

Usage:
    python3 find-org-skills.py [--claude-home PATH] [--output-format json|text]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def _installed_plugin_names(claude_home: Path) -> set[str]:
    """Plugin names installed locally.

    The plugin cache (cache/<marketplace>/<plugin>/<version>/skills) is keyed by
    plugin name — the authoritative install marker that matches catalogue plugin
    names. ~/.claude/skills is deliberately NOT consulted: it is keyed by
    individual *skill* name (a multi-skill plugin installs skills whose names
    differ from the plugin), so mixing the two namespaces produces both false
    negatives and false positives.
    """
    names: set[str] = set()
    cache = claude_home / "plugins" / "cache"
    if cache.is_dir():
        for mp in cache.iterdir():
            if not mp.is_dir():
                continue
            for plugin in mp.iterdir():
                if plugin.is_dir():
                    names.add(plugin.name)
    return names


def _repo_url(source: Any) -> str:
    """Derive a repo URL from a `source` object, or '' if it has none.

    Handles `{repo: "owner/name"}` (GitHub shorthand), an already-resolved
    `repo`/`url` (full URL or SSH spec, returned as-is), and ignores relative
    string sources (monorepo paths) — the caller falls back to the
    marketplace-level source for those.
    """
    if not isinstance(source, dict):
        return ""
    repo = source.get("repo")
    if repo:
        first = repo.split("/", 1)[0]
        if "://" in repo or repo.startswith("git@") or ":" in first:
            return repo  # already a full URL / SSH spec
        return f"https://github.com/{repo}"
    return source.get("url") or ""


def collect(claude_home: Path) -> list[dict[str, Any]]:
    known = _load_json(claude_home / "plugins" / "known_marketplaces.json")
    if not isinstance(known, dict):
        return []
    installed = _installed_plugin_names(claude_home)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for mp_name, mp in known.items():
        if not isinstance(mp, dict):
            continue
        loc = mp.get("installLocation")
        if not loc:
            continue
        manifest = _load_json(Path(loc) / ".claude-plugin" / "marketplace.json")
        if not isinstance(manifest, dict):
            continue
        # Fallback for monorepo marketplaces whose plugins use relative-path
        # sources: resolve to the marketplace's own repository.
        mp_url = _repo_url(mp.get("source"))
        for plugin in manifest.get("plugins", []):
            if not isinstance(plugin, dict):
                continue
            name = plugin.get("name") or ""
            if not name or (mp_name, name) in seen:
                continue
            seen.add((mp_name, name))
            out.append(
                {
                    "name": name,
                    "description": plugin.get("description") or "",
                    "repo_url": _repo_url(plugin.get("source")) or mp_url,
                    "marketplace": mp_name,
                    "category": plugin.get("category") or "",
                    "installed": name in installed,
                }
            )
    out.sort(key=lambda s: (not s["installed"], s["marketplace"], s["name"]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    parser.add_argument("--output-format", choices=["json", "text"], default="json")
    args = parser.parse_args()

    skills = collect(args.claude_home)

    if args.output_format == "text":
        if not skills:
            print("no configured marketplaces found")
        for s in skills:
            flag = "installed" if s["installed"] else "AVAILABLE (not installed)"
            print(
                f"[{flag}] {s['name']} ({s['marketplace']}) — {s['description'][:80]}"
            )
        return 0

    print(json.dumps(skills, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
