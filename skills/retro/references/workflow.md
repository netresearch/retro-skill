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

Replay a past session through the lens of what happened to its output afterwards
— **good or bad**.

```
Input: past session id (or all sessions within --since window)
Output: Schicht D findings — failures to learn from (D1–D10: reverted, rejected,
        CI-broken), durable successes to codify (D11: merged, unreverted,
        CI-green changes whose approach generalizes → skill-update), and
        superseded temporary copies to prune (D12: a tracked canonical-source
        upstream PR merged → prune the skill's labelled copy to a reference)
Use case: monthly look-back — both what didn't survive contact with reality and
          what did and should become the default
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

With `--scope skill`, run the mechanical drift pre-pass first:
`scripts/check-upstream-sources.py --skill-dir <repo>` probes every
`[upstream]`-labelled link and every checkpoint `source:` URL (dead links →
B14 candidates; a failed probe is transport, never "gone") and flags
checkpoint `verified:` dates older than the max age for an LLM re-read.

With `--scope skill`, the audit is also a **reconciliation** pass: classify the
skill's existing content by authority (upstream / code / org policy /
agent-evidence — Axis 0 in `classification-heuristic.md`). Content already
documented by its canonical owner → propose prune-to-reference; content humans
need that the owner lacks → propose `canonical-source` (upstream PR) paired
with the skill cleanup. Promote makes ephemeral knowledge durable; reconcile
moves already-durable knowledge to its rightful owner and dissolves the
duplicates. A learning system that can only ADD degrades — this is the REMOVE /
PROMOTE / MERGE half of the loop.

### Promote — `/retro promote`

Inventory the already-written memory **stock** (all project slugs) and re-home
each note upward, instead of detecting session friction.

```
Input: filesystem inventory of ~/.claude/projects/<slug>/memory/*.md (ALL slugs)
Output: C3/B8 findings -> the same classify -> materialize pipeline
Use case: drain accumulated local memory upward; empty the silo
```

Reads the stock, not the session flow. Reuses the scope-escalation rule
(skill-update > project-rule > personal-rule; never project-local memory) and
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

The mechanical pre-pass requires the session transcript path — it is NOT
auto-discovered, and **whichever way you guess at it, confirm the file by its
content before analysing it.** The transcript is usually named after the session
id (`~/.claude/projects/<slug>/<session-id>.jsonl`); when that file exists, it is
the right answer. It is not always there — measured on one host, 8 of 12 session
ids had a matching top-level transcript, the rest did not (sub-agent transcripts
live one level down, under `<uuid>/subagents/*.jsonl`). So treat the id-named
path as a first guess to be verified, and keep a fallback for when it is absent:

```bash
TOKEN='the exact sentence the user typed'   # see "choosing a token" below
TF=""

# First guess: the id-named file, accepted only if it also carries the token.
if [ -n "${SESSION_ID:-}" ]; then
  CAND=~/.claude/projects/"$(pwd | tr '/.' '--')"/"${SESSION_ID}".jsonl
  if [ -f "$CAND" ] && grep -qF -- "$TOKEN" "$CAND"; then TF="$CAND"; fi
fi

# Fallback: slug-independent sweep, newest first.
if [ -z "$TF" ]; then
  CANDIDATES="$(find ~/.claude/projects -maxdepth 2 -name '*.jsonl' \
    -printf '%T@ %p\n' 2>/dev/null | sort -rn | cut -d' ' -f2-)"
  [ -n "$CANDIDATES" ] || { echo "no transcripts on this host — wrong path or user"; exit 1; }
  for f in $CANDIDATES; do
    if grep -qF -- "$TOKEN" "$f"; then TF="$f"; break; fi
  done
fi
[ -n "$TF" ] || { echo "transcripts exist but none contain the token — pick another phrase"; exit 1; }
python3 "${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/detect-mechanical.py" \
  --transcript-file "$TF" --output-format json
```

Four things in that snippet are load-bearing:

**Search by content, not by mtime.** Several sessions share one project slug, so
the newest JSONL is frequently somebody else's: in one measured run six
transcripts under the same slug had been written within five minutes, the
runner-up one minute behind the winner, and one of them provably belonged to a
different conversation. `ls -t … | head -1` loses that race silently and every
downstream finding is then attributed to the wrong session. Newest-first here
only orders the candidates; the token decides.

**Do not derive the candidate list from `pwd`.** The slug encodes the directory
the session was *launched* from, not the current one. A session that entered a
worktree resolves `$(pwd | tr '/.' '--')` to a directory that does not exist —
verified: from `…/p/retro-skill/fix-transcript-selection` the derived slug misses
the live transcripts in `-home-sme-p` entirely. The `find` above sidesteps the
slug; if you do use a slug, take it from the launch directory.

**`grep -qF`, never bare `grep -q`.** The token is prose the user typed, and
prose contains regex metacharacters. Verified with ugrep 7.5: `grep -q
'config[0]'` does not match the literal text `config[0]` (it reads as a
character class), and an unmatched `[` exits 2 — which an `if` reads as "no
match", sending you to widen a token that was never the problem. `-F` makes it a
literal.

**The loop is deliberately pipe-free, and the candidate list avoids `ls`.**
`grep -l … | head -1` exits 141 under `pipefail` when `head` closes the pipe
early, and `grep -q … && TF=$f` as the last command of a loop body aborts under
`set -e` on the first non-matching candidate. Both fail in the direction that
reads as "no transcript found". `ls -t $(find …)` has the opposite failure: when
`find` matches nothing, `ls` receives no arguments and lists the *current
directory*, so the empty-candidates guard never fires and the loop greps
whatever happens to sit in the cwd. `find -printf | sort -rn` yields an empty
string when there is nothing to find, which is what the guard needs.

*Choosing a token:* a verbatim phrase the **user** typed in this conversation.
Not a repo name, PR number or ticket key — those are shared by every concurrent
session working the same thing, which is exactly the collision this procedure
exists to prevent. The two guards are separate on purpose: an empty candidate
list means the path or host is wrong, an empty `$TF` means the token is; the
remedies differ and one message for both sends you fixing the wrong one.

On a repeat `/retro` within one session, filter findings to turns after the
previous retro — earlier signals were already proposed and must not be
re-presented.

```
1. Mechanical pre-pass (Schicht A)
2. LLM enrichment (Schicht B)
3. Cross-session enrichment (Schicht C, optional)
4. Classification → 7 destinations (authority first)
5. Skill discovery (for skill-update / new-skill)
5b. Project-harness inspection (for project-rule / harness-artefact)
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
| 5b (project harness) | Yes | Only the argument's surface | Skipped | **Primary** (with E) | Yes |
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
| Proposals presented | ≤10 | Not 1011 (Coach anti-pattern); reserve slots for top reusable-learnings so friction can't crowd them all out. A gate+propagation pair (`destination-taxonomy.md`, "Paired materialization") counts as **one** |
| Total token cost vs Coach baseline | Dramatically below | TBD after first measurement |
| Setup time before first proposal | <30 seconds | Mechanical pre-pass + discovery cache |

## Phase transparency

The mode table above is the *contract*. When a run deviates — skips a phase,
or substitutes an ad-hoc step for the prescribed script — **say so in one line**,
with the reason:

```
Phase 3 (cross-session): skipped — single-project session, no cross-session pattern found.
Phase 5 (skill discovery): used `find … SKILL.md | grep` instead of find-installed-skills.sh because <reason>.
```

Silent skips make the Phase-11 report read as "all phases ran" when they did
not — which is itself a friction signal a future retro will (correctly) flag.
Prefer the prescribed scripts (`find-installed-skills.sh`, `scan-cross-session.py`)
over ad-hoc substitutes; reach for an ad-hoc step only when the script genuinely
cannot serve, and announce it when you do.

## Delegating a phase to subagents

Phases 1–3 over a large stock (Promote meets hundreds of notes) are worth
fanning out. Two constraints decide whether the fan-out returns anything:

**Ask for findings as text; write the file yourself.** Whether an agent may
write a report file is not something you can assume. In one promote run the two
agents dispatched directly wrote their reports fine, while the four *they* in
turn dispatched were refused — each reported "the Write tool blocked creation of
the report file, findings must be returned as text" and delivered its findings
as its final message instead. The discriminator was not established; the lesson
does not depend on it. An orchestrator that hands out "write your batch to
`report_batch_NN.md`" and then waits is betting on a capability it never
checked, and loses silently: the children finish, the files never appear, and
the absence is indistinguishable from work still in progress. Same defect class
as a poll loop with no failure branch — an outcome that *cannot* arrive is read
as one that has *not yet* arrived. Text always works, so make text the contract.

**A finished agent does not get more thorough by being poked.** Before nudging
or re-dispatching, check whether the result already landed somewhere else (a
task notification to the orchestrator, a sibling's message). Re-dispatching a
completed agent restarts it at full cost and returns the same answer.

Keep verification claims attributable: require each batch to return the command
and its output per finding, not a count. A batch that reports "2 stale" without
naming them cannot be merged into the report, and asking for the detail
afterwards costs a second round.

**Fan-out briefs must survive a host restart.** In-process subagents die with
the host and are not resumable by name — a killed fan-out is re-issued, not
resumed. Write briefs re-issuable: pin the tree state (SHA) they inspect,
keep scope deterministic, and commit worktree state before dispatching long
fan-outs (observed: the same three-agent classification fan-out was killed by
two restarts and re-ran verbatim only because the briefs were SHA-pinned).

## Failure modes and graceful degradation

| Issue | Fallback |
|---|---|
| Subagent reports its report file was blocked | Have it return findings as text; do not re-dispatch |
| Batch returns counts without evidence | Re-ask for the table; do not enter counts on trust |
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
- `references/project-harness-inspection.md` — What the worked-in repo could gate
- Spec: `docs/specs/retro-skill.md`
