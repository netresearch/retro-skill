#!/usr/bin/env python3
"""
find-org-skills.py — discover every skill available to the user, installed or not.

Reads the marketplaces Claude Code has configured (~/.claude/plugins/
known_marketplaces.json) and each one's locally-cloned catalogue
(<installLocation>/.claude-plugin/marketplace.json), then marks which catalogue
entries are actually installed (~/.claude/plugins/installed_plugins.json, with
the plugin cache as fallback).

Two descriptions exist for a skill, written for two readers. The catalogue
`description` is a listing summary for a human browsing plugins. The
`description` in the skill's own SKILL.md frontmatter is the routing text an
agent reads to decide whether to load the skill — and it is the only text that
answers "does a skill claim work X". Measured over one org marketplace they
differ for 37 of 38 skills (retro-skill#83). So for an installed plugin this
script reads every `skills/*/SKILL.md` under its install path and emits one
entry per skill carrying the routing description (`description_source:
"skill"`); a plugin that is not installed has no SKILL.md on disk, so its
entry carries the catalogue text and says so (`description_source:
"catalogue"`). `catalogue_description` is always present.

Offline by design: the catalogue manifests are kept in sync on disk by Claude
Code, so no network or `gh` auth is required. Generic by design: it reads
whatever marketplaces are configured, never a hardcoded org.

Usage:
    python3 find-org-skills.py [--claude-home PATH] [--output-format json|text]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def _version_key(name: str) -> tuple[Any, ...]:
    """Sort key that orders '1.10.0' after '1.9.1' (plain string sort does not)."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.\-+]", name))


def _installed_plugins(claude_home: Path) -> dict[tuple[str, str], Path | None]:
    """Installed plugins as {(marketplace, plugin): install path}.

    Primary source is installed_plugins.json (v2: `plugins` keyed
    `<plugin>@<marketplace>`, each a list of installs with `installPath`) — the
    record Claude Code writes on install, naming the version actually in use.
    Fallback is the plugin cache (cache/<marketplace>/<plugin>/<version>/), which
    can hold several versions of one plugin; the highest is taken then. The cache
    is keyed by plugin name, matching catalogue plugin names. ~/.claude/skills is
    deliberately NOT consulted: it is keyed by individual *skill* name (a
    multi-skill plugin installs skills whose names differ from the plugin), so
    mixing the two namespaces produces both false negatives and false positives.
    """
    installed: dict[tuple[str, str], Path | None] = {}
    record = _load_json(claude_home / "plugins" / "installed_plugins.json")
    plugins = record.get("plugins") if isinstance(record, dict) else None
    if isinstance(plugins, dict):
        for key, installs in plugins.items():
            if "@" not in key or not isinstance(installs, list):
                continue
            name, mp = key.rsplit("@", 1)
            path = None
            for entry in installs:
                if isinstance(entry, dict) and entry.get("installPath"):
                    candidate = Path(entry["installPath"])
                    if candidate.is_dir():
                        path = candidate
                        break
            installed[(mp, name)] = path
    cache = claude_home / "plugins" / "cache"
    if cache.is_dir():
        for mp_dir in cache.iterdir():
            if not mp_dir.is_dir():
                continue
            for plugin in mp_dir.iterdir():
                if not plugin.is_dir() or (mp_dir.name, plugin.name) in installed:
                    continue
                versions = sorted(
                    (v for v in plugin.iterdir() if v.is_dir()),
                    key=lambda v: _version_key(v.name),
                )
                installed[(mp_dir.name, plugin.name)] = (
                    versions[-1] if versions else None
                )
    return installed


_FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9_-]+):(.*)$")


def _frontmatter(text: str) -> dict[str, str]:
    """Top-level scalar fields of a SKILL.md frontmatter, without PyYAML.

    Handles plain, single-quoted, double-quoted (with `\\"` escapes) and block
    scalars (`|`, `>`, with `-`/`+` chomping). Nested mappings (e.g. `metadata:`)
    are skipped. Enough for `name` and `description`, which the Agent Skills
    spec defines as scalars.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        m = _FRONTMATTER_KEY.match(line)
        if not m:
            i += 1
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw[:1] in ("|", ">"):
            fold = raw[0] == ">"
            block: list[str] = []
            i += 1
            while i < len(lines) and (
                lines[i].startswith((" ", "\t")) or not lines[i].strip()
            ):
                if lines[i].strip() == "---":
                    break
                block.append(lines[i].strip())
                i += 1
            joined = " ".join(b for b in block if b) if fold else "\n".join(block)
            fields[key] = joined.strip()
            continue
        if raw.startswith('"'):
            end = raw.find('"', 1)
            while end != -1 and raw[end - 1] == "\\":
                end = raw.find('"', end + 1)
            value = raw[1:end] if end != -1 else raw[1:]
            fields[key] = value.replace('\\"', '"')
        elif raw.startswith("'"):
            end = raw.find("'", 1)
            fields[key] = raw[1:end] if end != -1 else raw[1:]
        else:
            fields[key] = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        i += 1
    return fields


def _skill_files(install_path: Path) -> list[Path]:
    """Every SKILL.md a plugin ships, honouring its manifest's `skills` field.

    `.claude-plugin/plugin.json` may point at skill directories explicitly
    (`["./skills/x"]`) or at one directory holding several (`"./.claude/skills/"`);
    without a manifest entry the spec default `skills/*/SKILL.md` applies.
    """
    manifest = _load_json(install_path / ".claude-plugin" / "plugin.json")
    declared = manifest.get("skills") if isinstance(manifest, dict) else None
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, list) or not declared:
        return sorted(install_path.glob("skills/*/SKILL.md"))
    files: list[Path] = []
    for entry in declared:
        if not isinstance(entry, str):
            continue
        target = install_path / re.sub(r"^\./", "", entry)
        if target.is_file():
            files.append(target)
        elif (target / "SKILL.md").is_file():
            files.append(target / "SKILL.md")
        elif target.is_dir():
            files.extend(sorted(target.glob("*/SKILL.md")))
    return files


def _installed_skills(install_path: Path) -> list[tuple[str, str]]:
    """(skill name, routing description) for every SKILL.md a plugin ships."""
    out: list[tuple[str, str]] = []
    for skill_md in _skill_files(install_path):
        try:
            fm = _frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        out.append((fm.get("name") or skill_md.parent.name, fm.get("description", "")))
    return out


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
    installed = _installed_plugins(claude_home)
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
            catalogue = plugin.get("description") or ""
            base = {
                "plugin": name,
                "catalogue_description": catalogue,
                "repo_url": _repo_url(plugin.get("source")) or mp_url,
                "marketplace": mp_name,
                "category": plugin.get("category") or "",
                "installed": (mp_name, name) in installed,
            }
            install_path = installed.get((mp_name, name))
            skills = _installed_skills(install_path) if install_path else []
            if not skills:
                out.append(
                    {
                        "name": name,
                        "skill": "",
                        "description": catalogue,
                        "description_source": "catalogue",
                        **base,
                    }
                )
                continue
            for skill, description in skills:
                out.append(
                    {
                        "name": name if skill == name else f"{name}:{skill}",
                        "skill": skill,
                        "description": description,
                        "description_source": "skill",
                        **base,
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
            source = (
                "routing text"
                if s["description_source"] == "skill"
                else "catalogue text"
            )
            print(
                f"[{flag} · {source}] {s['name']} ({s['marketplace']}) — "
                f"{s['description'][:80]}"
            )
        return 0

    print(json.dumps(skills, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
