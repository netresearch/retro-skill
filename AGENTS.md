# retro-skill

LLM-driven session retrospection skill. Detects friction in agent sessions and materializes learnings into correct destinations.

## Structure

- `skills/retro/SKILL.md` — Main skill definition (sweep, spotlight, outcome, audit, promote, auto modes)
- `skills/retro/checkpoints.yaml` — Skill quality gates
- `commands/retro.md` — `/retro` slash command definition
- `hooks/session-end.json` — Optional auto-trigger hook (off by default)
- `skills/retro/references/` — Friction catalog, destination taxonomy, classification heuristic, skill discovery, patch workflow, eval integration, workflow modes
- `skills/retro/scripts/detect-mechanical.py` — Schicht-A pre-pass (mechanical friction detection)
- `skills/retro/scripts/find-org-skills.py` — Skill discovery: every marketplace skill, installed or not
- `skills/retro/scripts/find-installed-skills.sh` — Installed-only detail (paths, git remotes)
- `skills/retro/scripts/scan-cross-session.py` — Cross-session JSONL scanner (Schicht-C)
- `skills/retro/scripts/scan-memory-inventory.py` — Promote-mode pre-pass over the memory backlog
- `skills/retro/scripts/check-upstream-sources.py` — Drift check against canonical sources
- `skills/retro/scripts/materialize-pr.sh` — Opens the skill-update PR against the source repo
- `skills/retro/scripts/validate-evals.py` — Validates retro's own eval scenarios (RT-40..42)
- `skills/retro/evals/` — retro's own classification evals (LLM-graded fixtures; see `skills/retro/evals/README.md`)
- `docs/specs/retro-skill.md` — Mirror of authoritative spec

## Commands

- `/retro` — Sweep: analyze entire current session
- `/retro "<problem>"` — Spotlight: focus on specific issue
- `/retro outcome [session-id|--since N]` — Outcome: post-hoc review of a past session
- `/retro audit [--scope project|repo|skill]` — Audit: cross-session architectural review
- `/retro promote` — Promote: re-home accumulated local memory upward
- `/retro done` — Done: seven-gate definition-of-done check (task, findings, retro, cleanup, questions, tickets, time)

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

## See also

- [Spec](docs/specs/retro-skill.md) — Authoritative specification
