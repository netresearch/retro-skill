# Workflow

The modes of `/retro` and how they share the underlying pipeline.

## Modes

### Sweep — `/retro` (no arguments)

Full session analysis. Use at end of session — whether or not friction
accumulated. The sweep captures **both** classes: friction *and* reusable
learnings (hard-won techniques, proactive improvements, code-review lessons;
Schicht B, B16–B18). A session that went smoothly is not exempt — it still owes
its learnings.

```
Input: entire current session transcript
Output: ≤10 actionable proposals grouped by destination
        (friction + reusable-learnings; learnings protected from cap crowd-out)
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

### Outcome — `/retro outcome [session-id|--since N]`

Replay a past session through the lens of what happened to its output afterwards.

```
Input: past session id (or all sessions within --since window)
Output: Schicht D findings (commits reverted, PRs rejected, etc.) for that session
Use case: monthly look-back at decisions that didn't survive contact with reality
```

Requires latency. Don't run within 24h of the session. Best run with `--since 30d` for the previous month.

### Audit — `/retro audit [--scope project|repo|skill]`

Constitutional review: cross-session architectural patterns vs declared design.

```
Input: scope (which project / repo / skill to audit)
Output: Schicht E findings (architectural drift, convention erosion, ADR violations)
Use case: quarterly or monthly system health check
```

Different output class from per-session retro. Destinations typically include ADR creation/update (via project-rule).

### Promote — `/retro promote`

Inventory the already-written memory **stock** (all project slugs) and re-home
each note upward, instead of detecting session friction.

```
Input: filesystem inventory of ~/.claude/projects/<slug>/memory/*.md (ALL slugs)
Output: C3/B8 findings -> the same classify -> materialize pipeline
Use case: drain accumulated local memory upward; empty the silo
```

Reads the stock, not the session flow. Reuses the scope-escalation rule
(skill-update > project-rule > user-memory; never project-local memory) and
drains the source LAST, only after the upward write is verified. Full detail:
`references/promote-mode.md`.

### Auto — SessionEnd hook (off by default)

Optional automated trigger. Activate by merging the `hooks` object from `hooks/session-end.json` into `~/.claude/settings.json` (or a project `.claude/settings.json`); Claude Code does not load hooks from a `~/.claude/hooks/` directory.

```
Trigger: SessionEnd event
Behavior: Prints reminder to run /retro if session was non-trivial (>1000 words).
          Reads transcript_path from stdin JSON (the SessionEnd hook input format).
Use case: developers who want a nudge after long sessions
```

Currently the hook only prints a reminder; invoking slash commands from hooks varies by client.

## Shared pipeline

All six modes use the same underlying flow (with mode-specific Schicht selection):

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

| Phase | Sweep | Spotlight | Outcome | Audit | Auto |
|---|---|---|---|---|---|
| 1 (mechanical A) | Full transcript | Argument-filtered turns | Skipped (past session) | Skipped | Full transcript |
| 2 (LLM enrich B) | Full transcript | Argument-focused | Past session highlights | Cross-session prose | Full transcript |
| 2b (trigger-coverage B15) | Yes | Only the argument's skill area | Skipped | **Exhaustive** (whole inventory) | Yes |
| 3 (cross-session C) | Yes | Yes (filtered) | Yes | Yes (wider window) | Yes |
| 3b (outcome D) | No | No | **Primary** | Some | No |
| 3c (constitutional E) | No | No | No | **Primary** | No |
| 4-10 | Same | Same (fewer findings) | D-focused | E-focused | Same |
| 11 (report) | Detailed | Targeted | Outcome-table | Architectural-table | Reminder only |

**Promote** substitutes Phase 1 with `scripts/scan-memory-inventory.py` (a
filesystem inventory of every slug's `memory/`, not a transcript), skips Phases
2/2b/3/3b/3c, runs Phases 4–10, and adds a verified **materialize-then-drain**
post-step to Phase 9 — drain via `scan-memory-inventory.py drain <path>` only
after the upward write is confirmed (tombstone move, never `rm`). The Phase-11
report gains a "Source drained?" column.

## Efficiency targets

| Metric | Target | Why |
|---|---|---|
| LLM passes per `/retro` | 1 | No multi-round polling |
| `detect-mechanical.py` invocations | 1 | Capture the JSON once, post-process the saved output; never re-run the detector just to reshape/bucket its output (a full second transcript scan for nothing) |
| Tool calls for skill discovery | ≤5 | Cached per session |
| Proposals presented | ≤10 | Not 1011 (Coach anti-pattern); reserve slots for top reusable-learnings so friction can't crowd them all out |
| Total token cost vs Coach baseline | Dramatically below | TBD after first measurement |
| Setup time before first proposal | <30 seconds | Mechanical pre-pass + discovery cache |

## Phase transparency

The mode table above is the *contract*. When a run deviates — skips a phase,
or substitutes an ad-hoc step for the prescribed script — **say so in one line**,
with the reason:

```
Phase 3 (cross-session): skipped — no ~/.claude-coach/events.sqlite and a single-project session.
Phase 5 (skill discovery): used `find … SKILL.md | grep` instead of find-installed-skills.sh because <reason>.
```

Silent skips make the Phase-11 report read as "all phases ran" when they did
not — which is itself a friction signal a future retro will (correctly) flag.
Prefer the prescribed scripts (`find-installed-skills.sh`, `extract-coach-events.py`)
over ad-hoc substitutes; reach for an ad-hoc step only when the script genuinely
cannot serve, and announce it when you do.

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

A rejected skill-update edit is recorded in `~/.claude/retro/rejected-edits.md`
(target skill · edit summary · reason · date) and suppressed in later sessions,
so the same rejected edit is not proposed again.

## Honest limitations

retro detects friction *and* reusable learnings observable in or near the session
(Sweep / Spotlight) or in the stored backlog (Promote). A learning is detectable
only when it surfaced in the session (a technique the agent worked out, an
improvement it named, a review comment it received); retro does **not** detect:
silent badness (architecturally wrong but friction-free choices the agent never
recognized as a learning); external signals (customer
complaints, prod alerts, Slack / Jira / Sentry); slow constitutional drift
without `audit`; or outcomes the agent never saw (a reverted commit or rejected
PR is seen, an unspoken "the customer hated it" is not). For those, run
`/retro outcome` (post-hoc) or `/retro audit` (cross-session).

## See also

- `references/friction-catalog.md` — What is detected
- `references/destination-taxonomy.md` — Where it goes
- `references/classification-heuristic.md` — How it's routed
- Spec: `docs/specs/retro-skill.md`
