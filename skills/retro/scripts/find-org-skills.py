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
    """Sort key that orders '1.10.0' after '1.9.1' (plain string sort does not).

    Each segment is tagged numeric-or-not before comparison. A tuple mixing
    bare ints and strs raises TypeError the moment one cache directory is not
    a plain version ('latest', 'dev', 'v1.0.0' beside '1.2.3'), and that
    exception would come out of `sorted()` and take the whole scan down.
    """
    return tuple(
        (0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"[.\-+]", name)
    )


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
    installed = _recorded_installs(claude_home)
    for key, path in _cached_installs(claude_home).items():
        # A recorded plugin whose installPath no longer resolves is exactly the
        # case the cache is a fallback for, so the test is "do we already have a
        # path", not "is the key present".
        if not installed.get(key):
            installed[key] = path
    return installed


def _recorded_install_path(installs: Any) -> Path | None:
    """The first installPath in one installed_plugins.json record that exists."""
    if not isinstance(installs, list):
        return None
    for entry in installs:
        if not isinstance(entry, dict) or not entry.get("installPath"):
            continue
        candidate = Path(entry["installPath"])
        if candidate.is_dir():
            return candidate
    return None


def _recorded_installs(claude_home: Path) -> dict[tuple[str, str], Path | None]:
    """{(marketplace, plugin): install path} from installed_plugins.json (v2)."""
    record = _load_json(claude_home / "plugins" / "installed_plugins.json")
    plugins = record.get("plugins") if isinstance(record, dict) else None
    if not isinstance(plugins, dict):
        return {}
    out: dict[tuple[str, str], Path | None] = {}
    for key, installs in plugins.items():
        if "@" not in key:
            continue
        name, mp = key.rsplit("@", 1)
        out[(mp, name)] = _recorded_install_path(installs)
    return out


def _cached_installs(claude_home: Path) -> dict[tuple[str, str], Path | None]:
    """{(marketplace, plugin): highest cached version} from the plugin cache."""
    cache = claude_home / "plugins" / "cache"
    if not cache.is_dir():
        return {}
    out: dict[tuple[str, str], Path | None] = {}
    for mp_dir in cache.iterdir():
        if not mp_dir.is_dir():
            continue
        for plugin in mp_dir.iterdir():
            if not plugin.is_dir():
                continue
            versions = sorted(
                (v for v in plugin.iterdir() if v.is_dir()),
                key=lambda v: _version_key(v.name),
            )
            out[(mp_dir.name, plugin.name)] = versions[-1] if versions else None
    return out


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
        if lines[i].strip() == "---":
            break
        m = _FRONTMATTER_KEY.match(lines[i])
        if not m:
            i += 1
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw[:1] in ("|", ">"):
            fields[key], i = _block_scalar(lines, i + 1, raw[0] == ">")
            continue
        fields[key] = (
            _quoted_scalar(raw, raw[0]) if raw[:1] in ("'", '"') else _plain_scalar(raw)
        )
        i += 1
    return fields


def _block_scalar(lines: list[str], start: int, fold: bool) -> tuple[str, int]:
    """A `|`/`>` block's text, and the index of the first line after it."""
    block: list[str] = []
    i = start
    while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
        if lines[i].strip() == "---":
            break
        block.append(lines[i].strip())
        i += 1
    joined = " ".join(b for b in block if b) if fold else "\n".join(block)
    return joined.strip(), i


def _quoted_scalar(raw: str, quote: str) -> str:
    """The contents of a quoted scalar; inside `"`, `\\"` does not end it."""
    end = raw.find(quote, 1)
    if quote == '"':
        while end != -1 and raw[end - 1] == "\\":
            end = raw.find(quote, end + 1)
    value = raw[1:end] if end != -1 else raw[1:]
    return value.replace('\\"', '"') if quote == '"' else value


def _plain_scalar(raw: str) -> str:
    """A plain scalar, minus a trailing ` # comment`.

    `\\s#` rather than `\\s+#`: the quantified form backtracks super-linearly
    over a run of whitespace (Sonar S8786), and both cut at the same place once
    the result is stripped.
    """
    m = re.search(r"\s#", raw)
    return (raw[: m.start()] if m else raw).strip()


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
    root = install_path.resolve()
    for entry in declared:
        if not isinstance(entry, str):
            continue
        target = (install_path / re.sub(r"^\./", "", entry)).resolve()
        # A plugin manifest is third-party data. An absolute entry, or one with
        # `..`, would otherwise make this read a SKILL.md outside the plugin the
        # manifest describes and publish its description as that plugin's.
        if target != root and root not in target.parents:
            continue
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
            # A multi-skill plugin qualifies every one of its skills, including
            # the one whose name matches the plugin: `foo` and `foo:bar` in one
            # listing reads as two plugins.
            bare = len(skills) == 1
            for skill, description in skills:
                out.append(
                    {
                        "name": name if bare and skill == name else f"{name}:{skill}",
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
