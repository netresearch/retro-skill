# retro-skill

LLM-driven session retrospection for Claude Code agents.

[![License: MIT AND CC-BY-SA-4.0](https://img.shields.io/badge/License-MIT%20AND%20CC--BY--SA--4.0-blue.svg)](LICENSE-MIT)

## What it does

`/retro` analyzes the current Claude Code session, identifies friction patterns directly from the conversation transcript (no continuous hooks pipeline), classifies each into one of six destinations, and materializes approved learnings with per-proposal confirmation.

**Destinations:**
- `user-memory` — personal preference → append a rule to `~/.claude/CLAUDE.md`
- `project-rule` — project-specific convention → append a rule to `<project>/AGENTS.md`
- `skill-update` — improve existing skill → PR to source repo
- `new-skill` — skill-shaped gap → scaffold new repo
- `checkpoint` — mechanical check → `checkpoints.yaml` entry
- `harness-artefact` — repo infrastructure gap → hook/CI/template

## Why

The existing Coach plugin's continuous-hook pipeline produces high noise (1011 pending candidates / 0 approved in field testing). An LLM with the actual session transcript classifies more accurately with fewer tokens.

## Install

```bash
# Via Claude Code plugin marketplace
/plugin add netresearch/retro-skill

# Or via Composer (skill-repo convention)
composer require netresearch/retro-skill
```

## Use

```
/retro                          # Sweep mode — full session analysis
/retro "<problem description>"  # Spotlight mode — focus on one issue
```

Enable auto-trigger at session end (off by default):

```bash
mkdir -p ~/.claude/hooks
cp hooks/session-end.json ~/.claude/hooks/
# Or per-project: cp hooks/session-end.json <your-project>/.claude/hooks/
```

## How it works

```
1. Mechanical pre-pass (Schicht A)     → Python, deterministic, ~14 signals
2. LLM enrichment (Schicht B)          → ~14 inferential signals
3. Cross-session enrichment (Schicht C)→ Coach events OR JSONL scan, ~4 signals
4. Classification → 6 destinations
5. Skill discovery (runtime)
6. Per-proposal approval
7. Materialization (PR / file write)
```

See [docs/specs/retro-skill.md](docs/specs/retro-skill.md) for the full specification.

## Patches go to source repos

Cache (`~/.claude/plugins/cache/`) is overwritten on plugin update; patches there are lost. `/retro` always targets the source repository (clone or use existing `~/p/<skill>/main/` worktree) and creates a PR via `gh` / `glab`.

## License

Code under MIT, content under CC-BY-SA-4.0. See [LICENSE-MIT](LICENSE-MIT) and [LICENSE-CC-BY-SA-4.0](LICENSE-CC-BY-SA-4.0).
