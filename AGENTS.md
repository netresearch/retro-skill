# retro-skill

LLM-driven session retrospection skill. Detects friction in agent sessions and materializes learnings into correct destinations.

## Structure

- `skills/retro/SKILL.md` — Main skill definition (sweep, spotlight, outcome, audit, promote, auto modes)
- `skills/retro/checkpoints.yaml` — Skill quality gates
- `commands/retro.md` — `/retro` slash command definition
- `hooks/session-end.json` — Optional auto-trigger hook (off by default)
- `references/` — Friction catalog, destination taxonomy, classification heuristic, skill discovery, patch workflow, eval integration, workflow modes
- `scripts/detect-mechanical.py` — Schicht-A pre-pass (mechanical friction detection)
- `scripts/find-installed-skills.sh` — Skill discovery helper
- `scripts/extract-coach-events.py` — Optional Coach data reader
- `scripts/scan-cross-session.py` — Cross-session JSONL scanner (Schicht-C fallback)
- `docs/specs/retro-skill.md` — Mirror of authoritative spec

## Commands

- `/retro` — Sweep: analyze entire current session
- `/retro "<problem>"` — Spotlight: focus on specific issue
- `/retro outcome [session-id|--since N]` — Outcome: post-hoc review of a past session
- `/retro audit [--scope project|repo|skill]` — Audit: cross-session architectural review
- `/retro promote` — Promote: re-home accumulated local memory upward

## Rules

- LLM is primary classifier; mechanical pre-pass reduces token cost but does not classify
- Patches always go to source repo, never to local cache
- Per-private-repo confirmation before any PR
- One approval per materialization (not per candidate)
- No auto-merge; no continuous background hooks (except optional SessionEnd)

## Relationships

- `agent-harness-skill` — verifies integration points (PR retro question, optional SessionEnd hook)
- `agent-rules-skill` — defines feedback-memory schema for project-rule materialization
- `skill-repo-skill` — defines PR/branch convention for skill-update materialization
- `automated-assessment-skill` — defines YAML schema for checkpoint materialization
- `claude-coach-plugin` — optional Schicht-C data source (read-only)

## See also

- [Spec](docs/specs/retro-skill.md) — Authoritative specification
