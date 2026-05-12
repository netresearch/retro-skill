---
description: "Session retrospection — detect friction, classify into destinations, materialize approved learnings"
---

# /retro — Session Retrospective

Analyze the current session for friction patterns and materialize learnings into the correct destination.

## Usage

```
/retro                                Sweep — full current session
/retro "<problem description>"        Spotlight — focus on one issue
/retro outcome [session-id|--since N] Outcome — post-hoc review of past session(s)
/retro audit [--scope X]              Audit — cross-session architectural review
```

## Phase 1: Mechanical Pre-Pass

Run the deterministic friction detector against the session transcript:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/detect-mechanical.py \
  --transcript-file ~/.claude/projects/<slug>/<session-id>.jsonl \
  --output-format json
```

Output is a structured list of candidate findings. Read this before scanning the transcript yourself — it saves tokens.

## Phase 2: LLM Enrichment

For each pre-pass candidate, validate against the conversational context. Add inferential findings the pre-pass cannot catch:

- Wrong skill choice (Skill X triggered, Skill Y would have fit better)
- Skill capability gap (skill triggered, lacked sub-task guidance)
- Hallucination / fact-check failures
- Convention violations
- Missing skills
- Repeated mistakes within same session
- Assumption-without-asking patterns
- Doc drift

See `references/friction-catalog.md` Schicht B for the full list.

## Phase 3: Cross-Session (Optional)

If `~/.claude-coach/events.sqlite` exists:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/extract-coach-events.py --since "30 days ago"
```

Otherwise fall back to JSONL scan:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scan-cross-session.py --pattern "<fingerprint>"
```

## Phase 4: Classification

Map each finding to one of six destinations using `references/classification-heuristic.md`. When uncertain, ask the user.

## Phase 5: Skill Discovery

For `skill-update` / `new-skill` destinations:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/find-installed-skills.sh
```

Match the friction topic against SKILL.md `description` frontmatter. If multiple matches → ask user. If no match → propose `new-skill`.

## Phase 6: Eval Consultation

If matched skill has `evals/` directory: read evals for context. If proposing a skill-update, also propose an eval stub (TDD style) when no existing eval covers the area.

## Phase 7: Proposal Generation

Per finding, generate prose:
- **Why:** 1-2 paragraphs explaining the friction and its root cause
- **How to apply:** 1-2 paragraphs describing the concrete fix

Group proposals by destination. Show ≤10 items.

## Phase 8: User Approval

Present grouped proposals. Per item:
- ✅ Approve → materialize
- ✏️ Edit → modify before materializing
- ❌ Reject → skip

## Phase 9: Materialization

Per destination, follow `references/patch-workflow.md` and the destination-specific convention. **Patches go to source repos, never to cache.**

For each created PR / file:
- Use Conventional Commits format
- No bot attribution in commit messages or PR bodies
- Per-private-repo confirmation before push
- Preserve commit signing (no `--no-gpg-sign`)

## Phase 10: Report

Summary table:

```
| Destination | Action | Target | Status |
|---|---|---|---|
| user-memory | wrote | ~/.claude/.../feedback_X.md | ✓ |
| skill-update | opened PR | netresearch/typo3-conformance-skill#456 | ✓ |
| checkpoint | added AH-22 | agent-harness-skill | ✓ |
```

## Spotlight Mode

When invoked with a `"<problem description>"` argument:

```
/retro "the assistant kept using npm instead of bun"
```

- Skip Phase 1 full-transcript mechanical pre-pass; instead extract argument-matching turns
- Run LLM enrichment on those turns only
- Run Phase 3 (cross-session) in filtered mode (same friction signature)
- Skip Phases 3b and 3c
- Proceed with Phases 4–10

Faster and uses fewer tokens than a full sweep.

## Outcome Mode

```
/retro outcome <session-id>          # Specific past session
/retro outcome --since 30d           # All sessions in last 30 days
```

- Skip Phases 1 and 2 (the session is in the past; mechanical pre-pass on a stale transcript is low value)
- Phase 3 runs against the target session(s)
- **Phase 3b is the primary detection step:** walk forward from session end with `git log`, `gh pr view`, `gh run list`, `gh issue list`. Detect Schicht D signals (D1–D10).
- Phase 3c may also fire if the window is large
- Phases 4–10 proceed; Destinations skew toward `user-memory` (personal pattern) and `skill-update` (skill should learn from outcome)

Requires latency. Don't run within 24h of the session — most D signals haven't manifested yet.

## Audit Mode

```
/retro audit                         # All sessions, repo + skill scope
/retro audit --scope project         # Project-level only
/retro audit --scope skill           # Skill drift only
```

- Skip Phases 1 and 2
- **Phase 3c is the primary detection step:** ADR adherence, AGENTS.md rule compliance trends, coverage trends, skill-inventory drift
- Output class is "architectural finding", not friction
- Destinations skew toward `project-rule` (new ADR or AGENTS.md update) and `harness-artefact` (enforcement hook)
- Cadence: monthly or quarterly. Tech-lead actor.
