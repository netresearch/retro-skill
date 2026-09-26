# retro-skill

LLM-driven session retrospection skill. Detects friction in agent sessions and materializes learnings into correct destinations.

## Structure

- `skills/retro/SKILL.md` — Main skill definition (sweep, spotlight, outcome, audit, promote, done, auto modes)
- `skills/retro/checkpoints.yaml` — Skill quality gates
- `commands/retro.md` — `/retro` slash command definition
- `hooks/session-end.json` — Optional SessionEnd hook: prints a reminder to run `/retro`, does not invoke it (off by default)
- `skills/retro/references/` — Friction catalog, destination taxonomy, classification heuristic, skill discovery, patch workflow, eval integration, workflow modes
- `skills/retro/scripts/detect-mechanical.py` — Schicht-A pre-pass (mechanical friction detection)
- `skills/retro/scripts/mask-secrets.py` — Credential masking shared by the scripts that emit transcript text (not a command)
- `skills/retro/scripts/opencode-transcript.py` — Renders an opencode session (SQLite) as the JSONL Schicht A reads
- `skills/retro/scripts/find-org-skills.py` — Skill discovery: every marketplace skill, installed or not
- `skills/retro/scripts/find-installed-skills.sh` — Installed-only detail (paths, git remotes)
- `skills/retro/scripts/scan-cross-session.py` — Cross-session JSONL scanner (Schicht-C)
- `skills/retro/scripts/collect-review-findings.py` — Review threads, bot reviews, native issue comments and supplied tracker feedback on the PRs/MRs a session wrote to (input for B18–B20, D4, D6); takes the artefact list from `derive-session-scope.py`
- `skills/retro/scripts/feedback-contract.py` — Validates local, tracker-neutral feedback; no discovery or execution
- `skills/retro/scripts/scan-memory-inventory.py` — Promote-mode pre-pass over the memory backlog
- `skills/retro/scripts/check-upstream-sources.py` — Drift check against canonical sources
- `skills/retro/scripts/materialize-pr.sh` — Opens the skill-update PR against the source repo
- `skills/retro/scripts/validate-evals.py` — Validates retro's own eval scenarios (RT-40..42)
- `skills/retro/scripts/check-eval-samples.py` — Refuses an eval retro adds or tightens without `samples` (called by `materialize-pr.sh finish`)
- `skills/retro/evals/` — retro's own classification evals (LLM-graded fixtures; see `skills/retro/evals/README.md`)
- `docs/specs/retro-skill.md` — Original spec, superseded (header says why); kept as a historical record

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
- Tracker-neutral core: no implicit tracker, external CLI discovery or organization billing policy; see `skills/retro/references/feedback-contract.md`

## Relationships

- `agent-harness-skill` — verifies integration points (PR retro question, optional SessionEnd hook)
- `agent-rules-skill` — defines feedback-memory schema for project-rule materialization
- `skill-repo-skill` — defines PR/branch convention for skill-update materialization
- `automated-assessment-skill` — defines YAML schema for checkpoint materialization

## See also

- [Spec](docs/specs/retro-skill.md) — Original specification, superseded; historical record
- [opencode live test](docs/opencode-live-test.md) — Checking `opencode-transcript.py` against a real, isolated opencode 2.x
