# Workflow

The three modes of `/retro` and how they share the underlying pipeline.

## Modes

### Sweep — `/retro` (no arguments)

Full session analysis. Use at end of session or when friction has accumulated.

```
Input: entire current session transcript
Output: ≤10 actionable proposals grouped by destination
Use case: explicit end-of-session retrospective
Token cost: highest (full transcript pass)
```

### Spotlight — `/retro "<problem>"`

Focused analysis. Use mid-session for direct fixes.

```
Input: User-described problem + last N turns of context
Output: proposals only for the described issue
Use case: "fix this specific thing now"
Token cost: low (targeted, narrow context)
```

Examples:
```
/retro "the assistant kept forgetting we use bun not npm"
/retro "skill X didn't trigger when it clearly should have"
/retro "git push failed because we missed phpstan"
```

### Auto — SessionEnd hook (off by default)

Optional automated trigger. Activate by copying `hooks/session-end.json` to `~/.claude/hooks/` or `<project>/.claude/hooks/`.

```
Trigger: SessionEnd event
Behavior: Prints reminder to run /retro if session was non-trivial (>1000 words)
Use case: developers who want a nudge after long sessions
```

Currently the hook only prints a reminder; invoking slash commands from hooks varies by client.

## Shared pipeline

All three modes use the same underlying flow:

```
1. Mechanical pre-pass (Schicht A)
2. LLM enrichment (Schicht B)
3. Cross-session enrichment (Schicht C, optional)
4. Classification → 6 destinations
5. Skill discovery (for skill-update / new-skill)
6. Eval consultation (when present)
7. Proposal generation (prose Why + How-to-apply)
8. Grouped presentation to user
9. Per-proposal approval
10. Materialization per destination convention
11. Report
```

Differences between modes:

| Phase | Sweep | Spotlight | Auto |
|---|---|---|---|
| 1 (mechanical) | Full transcript | Last N turns or argument-matched | Full transcript |
| 2 (LLM enrich) | Full transcript | Argument-focused | Full transcript |
| 3 (cross-session) | Yes | Yes (filtered) | Yes |
| 4-10 | Same | Same (fewer findings) | Same |
| 11 (report) | Detailed | Targeted | Detailed |

## Efficiency targets

| Metric | Target | Why |
|---|---|---|
| LLM passes per `/retro` | 1 | No multi-round polling |
| Tool calls for skill discovery | ≤5 | Cached per session |
| Proposals presented | ≤10 | Not 1011 (Coach anti-pattern) |
| Total token cost vs Coach baseline | Dramatically below | TBD after first measurement |
| Setup time before first proposal | <30 seconds | Mechanical pre-pass + discovery cache |

## Failure modes and graceful degradation

| Issue | Fallback |
|---|---|
| Coach data missing | JSONL scan fallback for Schicht C |
| JSONL scan slow | Limit to current project's sessions, last 30 days |
| Skill discovery returns no matches | Propose `new-skill` instead |
| Source repo URL unresolvable | Ask user; offer local-edit fallback |
| Worktree dirty | Use /tmp clone (with notification) |
| Private repo not authenticated | Graceful failure with login instruction |
| All proposals rejected by user | Report empty; no error |
| Pre-pass script errors | Log + continue with LLM-only |

## Manual escape hatches

User can always:
- Edit a proposal before approving
- Reject all proposals
- Run `/retro` again with `--no-cross-session` (if implemented) for faster mode
- Materialize manually after /retro shows proposals (no approval, just inspect output)

## See also

- `references/friction-catalog.md` — What is detected
- `references/destination-taxonomy.md` — Where it goes
- `references/classification-heuristic.md` — How it's routed
- Spec: `docs/specs/retro-skill.md`
