---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
name: retro
description: "Use when a Claude Code or Codex session ends or is declared finished, a friction needs fixing, a reusable learning needs capturing, local memory needs promoting upward, or for cross-session audits — detect friction AND learnings, route each to the right destination, including team documentation, and gate 'done'. Triggers: /retro, /retro done, 'retrospective', 'capture this learning', 'fix this skill', 'promote memory', 'audit', 'alles erledigt'."
license: "(MIT AND CC-BY-SA-4.0). See LICENSE-MIT and LICENSE-CC-BY-SA-4.0"
compatibility: "Requires uv (runs the scripts on Python 3.11 or later), jq, and gh and/or glab (PR creation)."
metadata:
  author: Netresearch DTT GmbH
  version: "3.1.0"
  repository: https://github.com/netresearch/retro-skill
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/*) Bash(${CLAUDE_SKILL_DIR}/scripts/*) Bash(uv run ${CLAUDE_SKILL_DIR}/scripts/*) Bash(gh:*) Bash(glab:*) Bash(git:*) Bash(find:*) Bash(grep:*) Bash(jq:*) Read Write Edit Glob Grep Task
---

# Retro — LLM-driven Session Retrospection

On Codex, resolve script paths from this loaded skill directory and use the
native discovery reader (`find-org-skills.py --host codex`), not Claude cache
paths. Host selection and coverage limits: `references/skill-discovery.md`.

Improve accepted task completion at the required quality within economically
feasible time and cost, across models, knowledge, tools and environment. One
LLM pass detects **friction and reusable learnings**, routes them to seven
destinations, and follows their availability, later use and observed benefit.
Read `references/learning-contract.md` for evidence, Mad/Sad/Glad perspectives,
configuration limits and justified no-op/pruning outcomes.

**Core principle:** No silent writes — verify existing authorization for the
target, action and audience; execute covered changes and ask only for uncovered
decisions. Process critique grants no new authority.

## Modes

- **`/retro`** — Sweep: the whole current session.
- **`/retro "<problem>"`** — Spotlight: one described issue.
- **`/retro outcome [session-id|--since N]`** — replay a past session by its
  outcomes.
- **`/retro audit [--scope project|repo|skill]`** — cross-session architectural
  drift.
- **`/retro promote`** — re-home already-written local memory upward (never
  project-local memory); keep active access until the accepted target is
  delivered and reachable, then drain. See `references/promote-mode.md`.
- **`/retro done`** — definition-of-done gate: eight evidence-backed checks
  (task, findings, retro, cleanup, questions, tickets, time, docs), each ✅ / ❌ /
  ⏸ / N/A. **⏸ only when a named person can close it with a named action;
  what is structurally absent is N/A with its reason** — a ⏸ nobody can close
  makes the whole table get skipped. Say **done** when every row is ✅ or N/A.
  See `references/done-mode.md`.
- **Auto** — optional SessionEnd hook, off by default. It is plugin-level, not
  part of this skill directory: `hooks/session-end.json` at the repository root
  (see README, "Optional auto-trigger").

## Pipeline (all modes)

1. Mechanical pre-pass — `uv run ${CLAUDE_SKILL_DIR}/scripts/detect-mechanical.py` (Promote:
   `uv run ${CLAUDE_SKILL_DIR}/scripts/scan-memory-inventory.py`). Every Python
   script runs through `uv run`: its header declares Python 3.11 or later, and
   `python3` can be an older interpreter (macOS ships 3.9). It requires `--transcript-file`, and the
   transcript is located **by content** — a token from this session — never by
   mtime: several sessions share one project slug, so the newest JSONL is
   regularly somebody else's. Codex rollout JSONL must first be converted with
   `scripts/codex-transcript.py`; on Windows set `PYTHONUTF8=1` before
   `uv run`. Invocation and adapter limits are in `references/workflow.md`.
   Then `uv run ${CLAUDE_SKILL_DIR}/scripts/collect-review-findings.py` on the
   same transcript (its header also declares the tree-sitter parser; plain
   `python3` stops with a message): review threads, bot reviews,
   and comments on the session's PRs/MRs, their linked issues, plus normalized tracker feedback supplied via
   `--feedback-file` (input for B18–B20, D4, D6). The subagents' transcripts
   (`<session id>/subagents/agent-*.jsonl`) are read with it; `transcripts`
   in the output lists every file read. PRs a script opened (a
   fleet driver's `opened.jsonl`) are not in the transcript: pass that file
   with `--pr-list`. Resolve relevant opaque
   hints through the owning integration, never by key shape. See
   `references/feedback-contract.md`; incomplete coverage is not silence.
2. LLM enrichment — Mad/Sad/Glad perspectives, both classes (friction +
   learnings B16–B21); distinguish observations, hypotheses and decisions;
   filter false positives. A prior failure is not required for a learning.
3. Cross-session enrichment (optional) — JSONL scan via `${CLAUDE_SKILL_DIR}/scripts/scan-cross-session.py`.
4. Discover skills — `${CLAUDE_SKILL_DIR}/scripts/find-org-skills.py` — and the repo's harness (`project-harness-inspection.md`). For each B21 candidate, search the team's records and state what was searched (`documentation-lookup.md`): not searched is unknown, never absent.
5. Classify (`classification-heuristic.md`) — authority and rule purpose before
   enforcement and reach; consider simplification, tools or environment changes;
   never project-local memory.
6. Evals — read a matched skill's `evals/`; propose a TDD stub.
   For targeted native or shared-runner comparisons, prepare isolated inputs
   with `scripts/prepare-behavior-evals.py`; follow `references/eval-integration.md`.
7. Proposals — prose Why + How-to-apply, grouped, ≤10; learnings survive the
   trim.
8. Authorization — reuse the valid mandate; present concrete uncovered decisions
   for approve / edit / reject. Do not request the same permission again.
9. Materialize per destination; for Promote, drain the source last (verified).
10. Report.
11. Self-check — the retro's own scripts, phases and reading of the invocation:
    `detect-mechanical.py --since-command retro`, three closed questions, a
    finding only with evidence, at most two `skill-update`s against retro-skill,
    otherwise one "nothing found" line. See `references/workflow.md` § Phase 11.

When a material outcome or cost claim needs host data, use
`scripts/collect-session-metrics.py`; for evidence-backed later opportunities,
use `scripts/scan-cross-session.py --learning-observations <file>`. Read
`references/session-metrics.md` for counter scope, unknowns and provenance.

## Boundaries

**Scope:** session-end/cross-session analysis, skill-PR routing, done gate.
Tracker identity and access belong to the owning integration; QA and time
policy belong to project/organization rules. No implicit tracker, CLI discovery
or organization-specific billing defaults in the core.

**Always:** LLM is primary classifier. Patches go to source repos, never the
cache. Verify private-repo and audience authorization. Conventional Commits. DCO sign-off
(`git commit -s`). Preserve commit signing.

**Ask first when not already covered:** material skill-match ambiguity,
auto-mode activation, private-repo access/push, a dirty-worktree fallback that
risks existing work, and promotion to a new audience. New product decisions,
team norms and permissions require the responsible authority.

**Never:** auto-merge, silent writes, harness-invented attribution (a disclosure
the user's rules prescribe is required), skip hooks (`--no-verify`),
patch the cache, hardcode a static skill list, `rm` a drained memory (tombstone);
from Done mode: merge, tag or deploy, or touch another session's containers,
processes or worktrees.

## References

| File | Purpose |
|---|---|
| `references/learning-contract.md` | Purpose, evidence, quality and configuration bounds |
| `references/session-metrics.md` | Observed usage/time and later application evidence |
| `references/feedback-contract.md` | Tracker-neutral evidence and reference resolution |
| `references/friction-catalog.md` | All signals: friction + learnings (A/B/C, B16–B21) |
| `references/destination-taxonomy.md` | The seven destinations |
| `references/classification-heuristic.md` | Friction → destination mapping |
| `references/skill-discovery.md` | Finding skills at runtime |
| `references/documentation-lookup.md` | Phase 4c: what the team's records already say |
| `references/patch-workflow.md` | Source-repo patching (never cache) |
| `references/eval-integration.md` | Evals for context + TDD stubs |
| `references/promote-mode.md` | Promote: materialize-then-drain |
| `references/done-mode.md` | Done: eight-gate finish check |
| `references/project-harness-inspection.md` | Rule purpose, environment and session signals |
| `references/workflow.md` | All modes + phase selection |
