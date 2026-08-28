# Done Mode — `/retro done`

Every other retro mode asks *what did we learn*. Done mode asks *are we actually
finished* — and refuses to say so until seven gates hold with evidence. It
exists because "done" was being declared with the retro not run and the time
not booked: the original task was complete, the session was not.

It is a **gate**, not a detector: it reuses the pipeline's approval and
materialization phases (8–10) for the writes it triggers (bookings, ticket
comments) and chains the Sweep for gate 3 when no retro has run yet.

## The seven gates

A gate is ✅ only with evidence from the system that owns the truth — a status
read back, a URL, a command's output — never from what the agent remembers
doing.

| Mark | Meaning | Closes by |
|------|---------|-----------|
| ✅ | holds, with evidence | — |
| ❌ | work remains | doing it |
| ⏸ | **waiting on the user**, and the user can close it | one named answer or action |
| N/A | does not apply here, with the reason | nothing — it is already settled |

**⏸ and N/A are not interchangeable, and confusing them breaks the gate.** A
session on a skill or infrastructure repo has no ticket, so gate 7 can never
reach ✅ — booking without a ticket is forbidden two sections down. Marked ⏸ it
reads as "waiting for something", but nothing will ever arrive: the row stands
forever, `done` can never be said, and after the third run the whole table gets
skipped, including the rows that report something real. Marked `N/A — no ticket,
no billable context: skill-repo work` it is settled and visible.

So: **⏸ only when a named person can close it with a named action.** Everything
structurally absent is N/A with its reason. `done` may be said when every row is
✅ or N/A.

| # | Gate | Evidence that closes it |
|---|------|-------------------------|
| 1 | **Task** — the original request, as the user phrased it, is delivered | Every artefact named with its live state: PR/MR (state, checks, threads, `mergeStateStatus` / `detailed_merge_status`), issue, tag, deploy. "I pushed" is not a state. |
| 2 | **Findings** — every interim finding is *fixed*, *filed* or *rejected* | One row per finding: fixed (commit SHA) · filed (issue/ticket URL in the row — "filed" without a URL is not filed) · rejected (one-line reason the user has seen). |
| 3 | **Retro** — the Sweep ran for this session | A materialized artefact from it: a memory file written, a skill PR opened, a rule edited — each named with its path or URL. "I ran it" is the same self-report the other gates refuse. No such artefact and no explicit *all rejected* record → Done mode runs the Sweep now (Phases 1–10) before continuing. |
| 4 | **Cleanup** — nothing of the session's own making is left running or lying around | The sweep list below, each line with its command output. |
| 5 | **Questions** — nothing is pending on the user that the task still needs | Either no open question, or exactly one human-gated decision stated once with the exact command, and the loop stopped there. Re-listing a parked decision is a ❌. |
| 6 | **Tickets** — every ticket touched carries the outcome | Per ticket: comment with what/why/evidence, assignee or reviewer set, transition done or hand-back posted; the last work summary is current (`netresearch-jira` › QA Best Practices › keep the work summary current). **N/A** when the session touched no ticket — say which work it was instead. |
| 7 | **Time** — every day of the session is booked | TimeTracker entries listed per day with ticket, project, activity, minutes. See *Booking* below. **N/A** when there is no ticket and no billable context (skill or infrastructure work) — never ⏸, which would wait for something that does not exist. |

## Cleanup sweep (gate 4)

**Name the scope before running anything.** The sweep is only as wide as the set
it runs over, and `git worktree list` in the wrong repository returns clean —
a ✅ that measured nothing. So the report states, above the table:

- **which repositories** the session touched (from the transcript: every path a
  write, a `cd` or a `git` command named — there is no command that produces
  this list, so it is an input, not an output),
- **which days** it spans,
- **which artefacts** it created (PRs, tags, releases, issues).

Then run all of it; a subset is how "cleaned up" turns out false.

```bash
# $SCRATCH is the scratchpad path from the system prompt — it is NOT in the
# environment, and unset it would expand to `du -sh /*`, walking the root
# filesystem. Set it explicitly and let the sweep fail loudly if it is missing.
SCRATCH="${SCRATCH:?paste the scratchpad path from the system prompt}"

pgrep -af 'php -S|node|python -m http'          # dev servers a subagent started
pgrep -af "$SCRATCH|make gate|runTests|--watch|until gh"   # this session's own
docker ps -a                                    # see the ownership note below
du -sh "$SCRATCH"/*                             # scratch disk

for r in <the repositories named above>; do     # per repo, never just the cwd
  git -C "$r" worktree list
  git -C "$r" branch -vv | grep ': gone]'       # remote deleted
  git -C "$r" stash list                        # lives in the repo, not a worktree
  git -C "$r" status --porcelain
done

ls -d /tmp/phpstan /tmp/cache/PHPStan /tmp/rector_cached_files 2>/dev/null
```

**Two process shapes, not one.** The first `pgrep` finds dev servers — the
classic subagent leftover. The second finds what a verification-heavy session
leaves: a backgrounded `make gate`, a `runTests.sh`, a `--watch` on a pull
request, an `until gh run …` loop. Neither pattern catches the other's shape.

**Containers are reported, never stopped.** `docker ps -a` lists every session's
containers, and a machine running several agents shows mostly foreign ones.
Under a heading called *Cleanup* that reads as an instruction; stopping another
session's e2e stack is worse than the mess this gate exists to prevent. Compare
against what was running when the session started, name only the difference as
yours, and list the rest as *foreign — untouched*.

Plus: subagents stopped (`TaskStop`), background watchers ended, no `/loop`
armed. **Before removing a worktree or branch:** `git status --porcelain`,
`git stash list`, `git cherry -v origin/main <branch>` — anything unpushed
stays, and the report says so.

**Stashes are their own row, not a footnote to worktree removal.** They live in
the repository, not in a worktree, so a repo can report a clean tree, no
worktrees and no stray branches while still holding them — and a stash whose
branch is gone is invisible from every other check. Read each one before
dropping it: `git stash show --stat`, then look for its content in the target
(`git stash show -p | grep '^+'` and search a distinctive line on `main`).
Three stashes from March, April and June were each already merged by another
route; the SHA goes in the report so the drop stays reversible.

**Three more rows the obvious list misses.** Each one produced a false "all
done" in the session this mode came out of:

| Check | Why it is not covered above |
|---|---|
| Memory-store consistency: no orphaned notes, no dead index links | A note deleted this session can leave `[[wikilinks]]` in surviving notes; an unindexed note is invisible at session start although the file exists |
| **Author** of every open PR before classifying it | "Renovate handles those" was wrong for one of five — it was an own PR with 14 red checks, waved through by the label rather than read |
| Consumer cache after a release (`~/.claude/plugins/cache/<marketplace>/<skill>/`) | A published release is not an installed one; "consumers have the fix" is false until the cache shows the version |

## Booking (gate 7)

- **TimeTracker, never a Jira worklog.** TimeTracker (`tt` MCP, `log_time`)
  syncs into Tempo; a direct Jira worklog double-books.
- **Per day, not per session.** A session can span days; derive the days from
  commit timestamps, scratch-file mtimes and the transcript, not from "today".
- **`get_day` immediately before every `log_time`** — a parallel session may
  have booked the same window (or your own work) already.
- **Project/activity from precedent:** `list_recent_entries` (write the result
  to a file and `jq` it — it overflows the context), match the ticket prefix.
- **Dual-write:** `agentWalltimeMinutes` + `humanMinutes` + `touchpoints`
  (`prompts`, `reviews`, `interventions`), description ≤255 characters, factual.
- **No ticket, no booking.** If the ticket key is unknown, search the tracker
  (JQL: `project = "<KEY>" AND text ~ "<repo>"`) before asking. Then the two
  cases part: a ticket that plausibly exists but was not found is **⏸** with the
  proposed entries and one question. Work that has no ticket by its nature —
  a skill repository, own tooling, infrastructure — is **N/A** with that reason.
  Asking for a ticket key that will never exist is the failure this distinction
  prevents.

## Forge and tracker bindings

| System | Read the state with | Write with |
|--------|---------------------|------------|
| GitHub | `git-workflow`'s `pr-status.sh -R owner/repo <pr>` (checks, reviews, rulesets, threads, `NEXT:`) | `gh pr edit/comment`, `gh issue create`, GraphQL `resolveReviewThread` |
| GitLab | `glab api projects/:id/merge_requests/<iid>` → `detailed_merge_status`; `…/discussions` for unresolved threads (`pr-status.sh` is GitHub-only) | `glab mr note`, `glab issue create` |
| Jira | `netresearch-jira` conventions; status + assignee from the issue itself | comment, transition, assignee |
| TimeTracker | `get_day`, `list_recent_entries` | `log_time` (dual-write) |

## Pipeline mapping

- Phases 1–3 (detection) are skipped — announce it in one line — unless gate 3
  triggers the Sweep, which then runs in full.
- Phase 8 (approval) applies to every write Done mode proposes: each booking,
  each ticket comment, each worktree removal with anything unpushed.
- Phase 10 report is the scope line plus the gate table; the word **done**
  appears only when every row is ✅ or N/A.

## Report format

The scope line comes first — without it the table says only "the checks I chose
to run passed", and a reader cannot tell whether gate 4 swept three repositories
or one.

```
Scope: t3x-nr-llm, agent-rules-skill, retro-skill · 26.–28.08. · PRs #872 #91 #95, tag v3.15.3

| # | Gate      | State | Evidence / next step |
|---|-----------|-------|----------------------|
| 1 | Task      | ✅    | PR #174 OPEN, 71/71 checks, 0 threads, CLEAN; assignee aseemann |
| 2 | Findings  | ✅    | 2 filed: #175, #176 · 1 fixed: 234b50b · 0 rejected |
| 3 | Retro     | ✅    | 3 memory files written (paths), 1 skill PR #81 |
| 4 | Cleanup   | ✅    | 3 repos swept: 0 own containers (6 foreign, untouched), 0 processes, 0 stashes, worktree pr169 removed, pr174 kept (PR open) |
| 5 | Questions | ✅    | none; CI wiring parked by user (stated once) |
| 6 | Tickets   | N/A   | no ticket touched — skill-repo work |
| 7 | Time      | N/A   | no ticket, no billable context |
```

A ⏸ or ❌ row ends the report with what is needed to close it — not with
"erledigt". An N/A row needs no follow-up: it carries its reason and is settled.
The word **done** may be said when every row is ✅ or N/A.

## Boundaries

**Never:** stop or remove a container, process or worktree belonging to another
session; mark a structurally impossible row ⏸ instead of N/A; merge, tag or
deploy from Done mode (those are the task's own,
explicitly authorized steps); book time without a ticket; dismiss a scanner
alert to turn a gate green; delete a worktree or branch holding unpushed
commits; declare done with a ⏸ or ❌ in the table.

**Ask first:** the ticket key when no precedent exists; removal of anything
with unpushed work; any ticket transition that closes a ticket someone else
owns.

## Evals

`../evals/done-gate-holds-on-unbooked-time.md` — the gate must refuse "done"
when the retro or the booking is missing, even though the code task is
complete.
