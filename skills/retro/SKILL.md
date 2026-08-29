---
name: retro
description: "Use when a Claude Code session ends or is declared finished, a friction needs fixing, a reusable learning needs capturing, local memory needs promoting upward, or for cross-session audits — detect friction AND learnings, route each to the right destination, and gate 'done'. Triggers: /retro, /retro done, 'retrospective', 'capture this learning', 'fix this skill', 'promote memory', 'audit', 'alles erledigt'."
license: "(MIT AND CC-BY-SA-4.0). See LICENSE-MIT and LICENSE-CC-BY-SA-4.0"
compatibility: "Requires python3, jq, and gh and/or glab (PR creation)."
metadata:
  author: Netresearch DTT GmbH
  version: "1.8.0"
  repository: https://github.com/netresearch/retro-skill
allowed-tools: Bash(python3:*) Bash(gh:*) Bash(glab:*) Bash(git:*) Bash(find:*) Bash(grep:*) Bash(jq:*) Read Write Edit Glob Grep Task
---

# Retro — LLM-driven Session Retrospection

One LLM pass over a session or the memory backlog detects **friction and
reusable learnings**, classifies each into one of seven destinations, and
materializes approved ones.

**Core principle:** No silent writes — every materialization needs
approval.

## Modes

- **`/retro`** — Sweep: the whole current session.
- **`/retro "<problem>"`** — Spotlight: one described issue.
- **`/retro outcome [session-id|--since N]`** — replay a past session by its
  outcomes.
- **`/retro audit [--scope project|repo|skill]`** — cross-session architectural
  drift.
- **`/retro promote`** — re-home already-written local memory upward (never
  project-local memory); drain the source only after the upward write is
  verified. See `references/promote-mode.md`.
- **`/retro done`** — definition-of-done gate: seven evidence-backed checks
  (task, findings, retro, cleanup, questions, tickets, time), each ✅ / ❌ /
  ⏸ / N/A. **⏸ only when a named person can close it with a named action;
  what is structurally absent is N/A with its reason** — a ⏸ nobody can close
  makes the whole table get skipped. Say **done** when every row is ✅ or N/A.
  See `references/done-mode.md`.
- **Auto** — optional SessionEnd hook, off by default. It is plugin-level, not
  part of this skill directory: `hooks/session-end.json` at the repository root
  (see README, "Optional SessionEnd hook").

## Pipeline (all modes)

1. Mechanical pre-pass — `scripts/detect-mechanical.py` (Promote:
   `scripts/scan-memory-inventory.py`). It requires `--transcript-file`, and the
   transcript is located **by content** — a token from this session — never by
   mtime: several sessions share one project slug, so the newest JSONL is
   regularly somebody else's. Invocation in `references/workflow.md`.
2. LLM enrichment — inferential signals, both classes (friction + learnings
   B16–B18); filter false positives.
3. Cross-session enrichment (optional) — JSONL scan via `scripts/scan-cross-session.py`.
4. Discover skills — `scripts/find-org-skills.py` — and the repo's harness (`project-harness-inspection.md`).
5. Classify (`classification-heuristic.md`) — authority first, then broadest
   scope; never project-local memory.
6. Evals — read a matched skill's `evals/`; propose a TDD stub.
7. Proposals — prose Why + How-to-apply, grouped, ≤10; learnings survive the
   trim.
8. Approval — approve / edit / reject per proposal.
9. Materialize per destination; for Promote, drain the source last (verified).
10. Report.

## Boundaries

**Scope:** session-end/cross-session analysis, skill-PR routing, done gate.

**Always:** LLM is primary classifier. Patches go to source repos, never the
cache. Per-private-repo confirmation. Conventional Commits. DCO sign-off
(`git commit -s`). Preserve commit signing.

**Ask first:** skill-match ambiguity, auto-mode activation, private-repo targets,
dirty-worktree fallback, any promotion making a note team-visible.

**Never:** auto-merge, silent writes, bot attribution, skip hooks (`--no-verify`),
patch the cache, hardcode a static skill list, `rm` a drained memory (tombstone);
from Done mode: merge, tag or deploy, or touch another session's containers,
processes or worktrees.

## References

| File | Purpose |
|---|---|
| `references/friction-catalog.md` | All signals: friction + learnings (A/B/C, B16–B18) |
| `references/destination-taxonomy.md` | The seven destinations |
| `references/classification-heuristic.md` | Friction → destination mapping |
| `references/skill-discovery.md` | Finding skills at runtime |
| `references/patch-workflow.md` | Source-repo patching (never cache) |
| `references/eval-integration.md` | Evals for context + TDD stubs |
| `references/promote-mode.md` | Promote: materialize-then-drain |
| `references/done-mode.md` | Done: seven-gate finish check |
| `references/workflow.md` | All modes + phase selection |
