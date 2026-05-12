---
name: retro
description: "Use at end of a Claude Code session, or on-demand for specific issues, to detect friction patterns in the conversation and materialize learnings into the correct destination (user memory, project rules, skill PRs, checkpoints, or harness artefacts). Triggers: /retro command, 'retrospective', 'review the session', 'fix this skill', 'we keep hitting this'."
license: "(MIT AND CC-BY-SA-4.0). See LICENSE-MIT and LICENSE-CC-BY-SA-4.0"
compatibility: "Requires python3 (mechanical pre-pass + cross-session scan), gh and/or glab for PR creation."
metadata:
  author: Netresearch DTT GmbH
  version: "0.1.0"
  repository: https://github.com/netresearch/retro-skill
allowed-tools: Bash(python3:*) Bash(gh:*) Bash(glab:*) Bash(git:*) Bash(find:*) Bash(grep:*) Bash(jq:*) Read Write Edit Glob Grep Agent
---

# Retro — LLM-driven Session Retrospection

This skill replaces continuous friction-detection hooks with a single efficient LLM pass over the session transcript. It detects friction, classifies into one of six destinations, and materializes approved learnings.

**Core principle:** No silent writes. Every materialization requires explicit user approval per proposal.

## Modes

### `/retro` — Sweep
Analyze the entire current session. Returns ≤10 actionable proposals grouped by destination. Use at session end or when you sense friction accumulated.

### `/retro "<problem>"` — Spotlight
Focus on a specific issue described in the argument. Returns proposals only for that issue. Use mid-session for direct fixes (e.g. "the assistant kept forgetting we use bun, not npm").

### Auto (off by default)
Optional SessionEnd hook (`hooks/session-end.json`). Activate per user opt-in. Skips trivial sessions via length heuristic.

## Workflow

1. **Mechanical pre-pass** — `scripts/detect-mechanical.py` parses the transcript for ~14 deterministic signals (tool errors, retry clusters, output verbosity, correction phrases, prompt/tool sequence repetition, skipped verification, upstream failures, etc.). Output: structured candidate list.

2. **LLM enrichment** — Read pre-pass output + relevant transcript excerpts. Add inferential signals (skill capability gaps, wrong skill choice, hallucinations, convention violations, missing skills, repeated mistakes, assumption-without-asking, doc drift). Filter false positives.

3. **Cross-session enrichment (optional)** — If `~/.claude-coach/events.sqlite` present, query for related events. Otherwise scan `~/.claude/projects/<slug>/*.jsonl` for similar friction. Detects: same-friction-again, cross-project patterns, memory drift, ineffective skill updates.

4. **Classification** — Per finding, map to 1 of 6 destinations using `references/classification-heuristic.md`.

5. **Discovery (runtime)** — For `skill-update` / `new-skill` destinations: find installed skills via `scripts/find-installed-skills.sh`, match by SKILL.md description, resolve source repo URL.

6. **Eval consultation** — If matched skill has `evals/`, read them for context. Propose eval stub alongside skill-update (TDD style).

7. **Proposal generation** — Per finding, generate 2-3 paragraph Why + How-to-apply prose. Group by destination.

8. **User approval** — Present grouped proposals. Approve / reject / edit per proposal.

9. **Materialization** — Per destination:
   - `user-memory` → write `~/.claude/projects/<slug>/memory/feedback_<slug>.md`
   - `project-rule` → write `<project>/docs/feedback/<slug>.md` + AGENTS.md index entry
   - `skill-update` → clone source repo (or use existing `~/p/<name>/main/` worktree), branch, commit, push, open PR
   - `new-skill` → invoke `skill-repo` scaffolding
   - `checkpoint` → YAML entry in target skill's `checkpoints.yaml`
   - `harness-artefact` → invoke `agent-harness` bootstrap

10. **Report** — Summary of created PRs, written files.

## Boundaries

**Always:** LLM is primary classifier. Patches go to source repos, never cache. Per-private-repo confirmation. Conventional Commits. Preserve commit signing.

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
