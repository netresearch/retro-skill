---
name: retro
description: "Use at end of a Claude Code session, on-demand for specific issues, or periodically for cross-session audits, to detect friction patterns and materialize learnings into the correct destination (user memory, project rules, skill PRs, checkpoints, or harness artefacts). Triggers: /retro command, 'retrospective', 'review the session', 'fix this skill', 'we keep hitting this', 'audit the architecture'."
license: "(MIT AND CC-BY-SA-4.0). See LICENSE-MIT and LICENSE-CC-BY-SA-4.0"
compatibility: "Requires python3 (pre-pass + cross-session scan), jq (skill discovery + manifest parsing), gh and/or glab (PR creation)."
metadata:
  author: Netresearch DTT GmbH
  version: "0.3.0"
  repository: https://github.com/netresearch/retro-skill
allowed-tools: Bash(python3:*) Bash(gh:*) Bash(glab:*) Bash(git:*) Bash(find:*) Bash(grep:*) Bash(jq:*) Read Write Edit Glob Grep Task
---

# Retro — LLM-driven Session Retrospection

This skill replaces continuous friction-detection hooks with a single efficient LLM pass over the session transcript. It detects friction, classifies into one of six destinations, and materializes approved learnings.

**Core principle:** No silent writes. Every materialization requires explicit user approval per proposal.

## Modes

### `/retro` — Sweep
Analyze the entire current session. Returns ≤10 actionable proposals grouped by destination. Use at session end or when you sense friction accumulated.

### `/retro "<problem>"` — Spotlight
Focus on a specific issue described in the argument. Returns proposals only for that issue. Use mid-session for direct fixes (e.g. "the assistant kept forgetting we use bun, not npm").

### `/retro outcome [session-id|--since N]` — Outcome (Schicht D)
Replay a past session through the lens of what happened to its output afterwards. Detects: commits reverted, PRs rejected, CI failures, follow-up sessions fixing earlier work, issues filed referencing session files. Use periodically (e.g. monthly) or when you suspect a past decision was wrong.

### `/retro audit [--scope project|repo|skill]` — Constitutional audit
Cross-session architectural review with a longer horizon (weeks/months). Detects design drift, convention erosion, and patterns that don't manifest as per-session friction but accumulate over time. Same skill, broader window. Use when you want a "is the system on track?" health check, not a "what went wrong this session?" view.

### Auto (off by default)
Optional SessionEnd hook (`hooks/session-end.json`). Activate per user opt-in. Skips trivial sessions via length heuristic.

## Honest limitations

retro-skill detects friction **observable in or near the session**. It does **not** detect:

- **Silent badness:** architectural choices that "work" but are wrong — these don't generate friction signals.
- **External signals:** customer complaints, production alerts, Slack/Jira/Sentry feedback. Out of scope; document via `external-feedback` integration if needed.
- **Constitutional drift over time** *without* `audit` mode: per-session retro can't see slow erosion.
- **Outcomes the agent never saw:** unless the work was reverted, the PR rejected, or a follow-up session occurred, retro-skill is blind to "the customer hated it but no one told us".

For these, run `/retro outcome` (post-hoc) or `/retro audit` (cross-session). External-feedback ingestion is a future direction.

## Workflow

1. **Mechanical pre-pass** — `scripts/detect-mechanical.py` parses the transcript for 18 deterministic signals (tool errors, retry clusters, output verbosity, tool-call inefficiency, sequential-vs-parallel, correction phrases, prompt/tool sequence repetition, wrong tool choice, skipped verification, upstream failures, permission re-approval, etc.). Output: structured candidate list.

2. **LLM enrichment** — Read pre-pass output + relevant transcript excerpts. Add inferential signals (skill capability gaps, wrong skill choice, hallucinations, convention violations, missing skills, repeated mistakes, assumption-without-asking, doc drift). Filter false positives.

2b. **Skill trigger-coverage sweep (B15)** — Run `scripts/find-installed-skills.sh` to get **every** installed skill's `name` + `description`, then in a single reasoning pass ask, for each: *given what this session actually did, should this skill have triggered — and was it invoked?* This is the systematic version of B2/B4 (which only catch a skill the LLM happens to notice). For each skill that should have fired but didn't:
   - **Weak/missing trigger words** in the skill's `description` → `skill-update` (the highest-value fix: a sharper `description` makes the skill fire for the whole team, every future session).
   - The right skill *was* invoked but under-performed → `skill-update` (capability gap, B3).
   - No skill covers the work at all → `new-skill` (B7).

   Keep it bounded: one pass over the compact description list against a session summary — not one call per skill. Standard in `sweep`; exhaustive (with the cross-session window) in `audit` mode. Don't flag a skill whose non-triggering was correct.

3. **Cross-session enrichment (optional)** — If `~/.claude-coach/events.sqlite` present, query for related events. Otherwise scan `~/.claude/projects/<slug>/*.jsonl` for similar friction. Detects: same-friction-again, cross-project patterns, memory drift, ineffective skill updates, follow-up-fix sessions.

3b. **Outcome enrichment (Schicht D — only in `/retro outcome` mode)** — Walk forward from session end: `git log` for revert/amend/supersede on session commits, `gh pr view` for session PRs (closed without merge? major changes requested?), CI history, follow-up sessions referencing this one. Detects: rejected output, retrospective errors, decisions that didn't survive contact with reality.

3c. **Constitutional analysis (only in `/retro audit` mode)** — Cross-session architectural patterns vs declared design: ADR adherence, AGENTS.md rule compliance over recent sessions, coverage trends, skill-inventory drift. Different output class (architectural findings, not friction findings).

4. **Classification** — Per finding, map to 1 of 6 destinations using `references/classification-heuristic.md`.

5. **Discovery (runtime)** — For `skill-update` / `new-skill` destinations: find installed skills via `scripts/find-installed-skills.sh`, match by SKILL.md description, resolve source repo URL.

6. **Eval consultation** — If matched skill has `evals/`, read them for context. Propose eval stub alongside skill-update (TDD style).

7. **Proposal generation** — Per finding, generate 2-3 paragraph Why + How-to-apply prose. Group by destination.

8. **User approval** — Present grouped proposals. Approve / reject / edit per proposal.

9. **Materialization** — Per destination:
   - `user-memory` → append a rule to `~/.claude/CLAUDE.md` (the always-loaded global rules file). **Never** `~/.claude/projects/<slug>/memory/` — that dir is cwd-scoped and not loaded globally.
   - `project-rule` → append a rule to `<project>/AGENTS.md` (not `<project>/CLAUDE.md`, not `docs/feedback/`)
   - `skill-update` → clone source repo (or use existing `~/p/<name>/main/` worktree), branch, commit **with `-s` (DCO sign-off) — without it the PR is BLOCKED even when all checks pass**, push, open PR
   - `new-skill` → invoke `skill-repo` scaffolding
   - `checkpoint` → YAML entry in target skill's `checkpoints.yaml`
   - `harness-artefact` → invoke `agent-harness` bootstrap

10. **Report** — Summary of created PRs, written files.

## Boundaries

**Always:** LLM is primary classifier. Patches go to source repos, never cache. Per-private-repo confirmation. Conventional Commits. DCO sign-off (`git commit -s`). Preserve commit signing (GPG and DCO are independent — both are required).

**Ask first:** Skill-match ambiguity. Auto-mode activation. Private repo targets. Dirty worktree fallback.

**Never:** Auto-merge. Silent writes. Bot attribution in commits/PRs. Skip hooks (`--no-verify`). Patch the cache directory. Hardcode static skill list. Generate 1000+ candidates.

## References

| File | Purpose |
|---|---|
| `references/friction-catalog.md` | All ~32 friction signals across Schichten A/B/C |
| `references/destination-taxonomy.md` | The six destination categories |
| `references/classification-heuristic.md` | Friction → destination mapping |
| `references/skill-discovery.md` | How to find skills at runtime |
| `references/patch-workflow.md` | Source-repo patching (never cache) |
| `references/eval-integration.md` | Using `evals/` for context and TDD stubs |
| `references/workflow.md` | Sweep / Spotlight / Auto modes in detail |
