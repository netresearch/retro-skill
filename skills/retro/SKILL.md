---
name: retro
description: "Use when a Claude Code session ends, a friction needs fixing, a reusable learning needs capturing, local memory needs promoting upward, or for cross-session audits — detect friction AND learnings and route each to the right destination. Triggers: /retro, 'retrospective', 'capture this learning', 'fix this skill', 'promote memory', 'audit'."
license: "(MIT AND CC-BY-SA-4.0). See LICENSE-MIT and LICENSE-CC-BY-SA-4.0"
compatibility: "Requires python3 (pre-pass, scans, skill discovery), jq (installed-skill helper + manifests), gh and/or glab (PR creation)."
metadata:
  author: Netresearch DTT GmbH
  version: "1.0.1"
  repository: https://github.com/netresearch/retro-skill
allowed-tools: Bash(python3:*) Bash(gh:*) Bash(glab:*) Bash(git:*) Bash(find:*) Bash(grep:*) Bash(jq:*) Read Write Edit Glob Grep Task
---

# Retro — LLM-driven Session Retrospection

One efficient LLM pass over a session (or the stored memory backlog) detects
**friction and reusable learnings**, classifies each into one of six
destinations, and materializes approved ones.

**Core principle:** No silent writes — every materialization needs explicit
per-proposal approval.

## Modes

Detail per mode in `references/workflow.md`; full pipeline + commands in
`commands/retro.md`.

- **`/retro`** — Sweep: the whole current session.
- **`/retro "<problem>"`** — Spotlight: one described issue.
- **`/retro outcome [session-id|--since N]`** — replay a past session by what
  happened to its output afterward.
- **`/retro audit [--scope project|repo|skill]`** — cross-session architectural
  drift.
- **`/retro promote`** — inventory already-written local memory and re-home each
  note upward (never project-local memory); drain the source only after the
  upward write is verified. See `references/promote-mode.md`.
- **Auto** — optional SessionEnd hook (`hooks/session-end.json`), off by default.

## Pipeline (all modes)

1. Mechanical pre-pass — `scripts/detect-mechanical.py` (Promote substitutes
   `scripts/scan-memory-inventory.py`).
2. LLM enrichment — inferential signals, both classes (friction + learnings
   B16–B18); filter false positives.
3. Cross-session enrichment (optional) — JSONL scan via `scripts/scan-cross-session.py`.
4. Discover skills — `scripts/find-org-skills.py` (installed + org catalogue).
5. Classify (`classification-heuristic.md`) to the broadest useful scope; never
   project-local memory.
6. Eval consultation — read a matched skill's `evals/`; propose a TDD stub.
7. Proposal generation — prose Why + How-to-apply, grouped, ≤10; learnings
   survive the trim.
8. Approval — approve / edit / reject per proposal.
9. Materialize per destination; for Promote, drain the source last (verified).
10. Report.

## Boundaries

**Scope:** session-end/cross-session analysis + skill-PR routing.

**Always:** LLM is primary classifier. Patches go to source repos, never the
cache. Per-private-repo confirmation. Conventional Commits. DCO sign-off
(`git commit -s`). Preserve commit signing.

**Ask first:** skill-match ambiguity, auto-mode activation, private-repo targets,
dirty-worktree fallback, any promotion making a note team-visible.

**Never:** auto-merge, silent writes, bot attribution, skip hooks (`--no-verify`),
patch the cache, hardcode a static skill list, `rm` a drained memory (tombstone).

## References

| File | Purpose |
|---|---|
| `references/friction-catalog.md` | All signals: friction + learnings (A/B/C, B16–B18) |
| `references/destination-taxonomy.md` | The six destinations |
| `references/classification-heuristic.md` | Friction → destination mapping |
| `references/skill-discovery.md` | Finding skills at runtime |
| `references/patch-workflow.md` | Source-repo patching (never cache) |
| `references/eval-integration.md` | Evals for context + TDD stubs |
| `references/promote-mode.md` | Promote: materialize-then-drain |
| `references/workflow.md` | All modes + phase selection |
