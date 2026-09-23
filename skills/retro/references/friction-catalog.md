# Friction Catalog

All signals retro-skill detects, organized in four layers (Schichten) by
detection mechanism and a fifth (constitutional) for cross-session architectural
analysis.

Despite the name, this catalog covers **two classes**: *friction* (things that
went wrong) and *reusable learnings* (knowledge that went right but is not
captured anywhere — Schicht B, signals B16–B20). Both are first-class retro
findings; a signal-free stretch of a session can still carry a learning worth
propagating.

## Scope and honest limitations

This catalog covers what retro-skill **can** detect from session transcripts, post-session git/PR history, cross-session JSONL data, and the feedback written on the session's PRs, MRs, linked issues and Jira tickets (`collect-review-findings.py`, see [Feedback from outside the transcript](#feedback-from-outside-the-transcript)).

**It does NOT detect:**
- Architectural choices that are wrong but "work" (no friction signal)
- External feedback outside forge and tracker (production alerts, customer complaints, Slack/Matrix mentions)
- Slow constitutional drift unless `/retro audit` mode is run with sufficient history

Ingestion of error trackers, monitoring and chat is out of scope — see "Future directions" at the bottom.

## Implementation status (v0.1.1)

| Schicht | Catalog signals | Implemented in code |
|---|---|---|
| A — Mechanical | 18 | 18 (all of A1–A18) |
| B — LLM inference | 20 | LLM-driven; B16–B20 are reusable-learning signals, B18–B20 read the output of `collect-review-findings.py` |
| C — Cross-session | 5 | Partial (script `scan-cross-session.py`) |
| D — Outcome | 12 | D4 and D6 read `collect-review-findings.py`; the others are LLM-driven. D11 (codify-success) and D12 (prune-superseded-copy) are the positive signals |
| E — Constitutional (audit) | 6 | Planned for v0.1.x |

Schicht A is feature-complete. See `references/destination-taxonomy.md` for what each signal class routes to.

## Schicht A — Mechanical (Python pre-pass)

Fast, deterministic, regex/count-based. Runs before LLM pass to reduce token cost. See `${CLAUDE_SKILL_DIR}/scripts/detect-mechanical.py`.

| # | Signal | Detection | Hint at |
|---|---|---|---|
| A1 | Tool error rate | `exit_code != 0` or `is_error: true` in tool_use_result | Wrong tool, wrong args, missing tool |
| A2 | Tool retry cluster | Same tool + similar args ≥3× within N turns | Tool misunderstanding, missing docs |
| A3 | Tool output verbosity | `len(tool_result) > X` without subsequent filter | Token waste, wrong tool (cat vs head, full Read vs Range) |
| A4 | Tool call count vs task | Total tool calls / user messages ratio above threshold | Inefficiency for simple task |
| A5 | Sequential vs parallel | Multiple independent calls serial in separate blocks | Performance waste |
| A6 | User correction phrases | Line-start openers (EN + DE: `no\|nope\|stop\|don't\|wrong\|nein\|nicht\|falsch\|quatsch\|warum\|wieso\|manno` …) **plus** curated mid-line DE phrases (`raus damit`, `endlich mal`, `so nicht`, `mach … selber`, `sei genau` …), ALL CAPS, `!!!` | Classic friction — DE speakers correct mid-sentence, which line-anchored EN openers miss |
| A7 | Prompt repetition | Semantic similarity of user messages within N turns | Assistant didn't understand |
| A8 | Prompt sequence repetition | n-gram match (n=2..5) over user message sequence | Workflow ripe for snippet/command |
| A9 | Tool sequence repetition | n-gram match over tool_use names + arg templates | Composition opportunity, skill instruction gap |
| A10 | Skill in reminder vs invoke | `<command-name>` in system reminder, no matching Skill call | Skill not triggered |
| A11 | Wrong tool choice | `grep` on JSON, `sed` on YAML, `cat` for huge file (not: `tail` on a task output or log, which Read cannot do; not a presence/count/locate `grep -c/-q/-l/-n`, a `sed -n '5,80p'` read or a search for git conflict markers — the enforcing gate permits all of those, and no structured parser can answer them) | Tool-not-used / wrong tool |
| A12 | Re-read same file | Read tool same path ≥2× without intervening Edit | Caching opportunity |
| A13 | Skipped verification | Claim "tests pass" / "fixed" without prior test/build run | Verification skip |
| A14 | Worked on main/master | Git commands without prior `checkout -b` | Workflow violation |
| A15 | Bot attribution in commit | Commit message contains "Generated with Claude" / "Co-Authored-By: Claude" | Known user rule violated |
| A16 | Outdated tool warning | "deprecated", "is now", "use X instead" patterns in stderr | Out-of-date knowledge |
| A17 | Upstream failure | `git push` fails on pre-receive, `gh pr checks` fails post-push, post-commit lint fail | Pre-push verification gap (shift-left) |
| A18 | Permission re-approval | Same permission prompt approved ≥3× in session | Allowlist needed |
| A19 | Repeated command shape | One program+subcommand shape invoked >=8x (plumbing excluded, remote calls flagged) | The same derived answer recomputed by hand — script candidate |
| A20 | Wait-loop inefficiency | `until`/`while` + `sleep` polling, flagged when it exits only on a backlog counter reaching zero | Learns nothing until the slowest job ends; the first failure was workable much earlier |

## Schicht B — LLM Inference

Requires conversational context understanding. The LLM reads pre-pass output + relevant transcript excerpts.

| # | Signal | Hint at |
|---|---|---|
| B1 | Output quality mismatch | Assistant's verbosity / style differed from user's implicit expectation |
| B2 | Wrong skill choice | Skill X was triggered, Skill Y would have fit better |
| B3 | Skill capability gap | Skill triggered, lacked guidance for sub-task |
| B4 | Skill description mismatch | User question should have triggered Skill X, but its `description` doesn't match |
| B5 | Hallucination / fact check | Assistant claimed X, later refuted by verification or user |
| B6 | Convention violation | Code doesn't match project style — no lint fail, but off |
| B7 | Missing skill | Recurring task with no installed skill matching |
| B8 | Wrong-destination materialization | Assistant wrote learning to wrong file (e.g. AGENTS.md instead of feedback memory) |
| B9 | Repeated mistake in session | Same error N× in same session — lesson not learned |
| B10 | Approval bypassed | Assistant performed irreversible action without user confirmation |
| B11 | Plan / spec skipped | Non-trivial task started without TodoWrite/plan/spec |
| B12 | Assumption without asking | Assistant made an assumption later refuted; should have used spec-driven-development |
| B13 | Context re-discovery | Assistant re-explored repo structure already documented in AGENTS.md |
| B14 | Doc drift | Assistant used outdated API/library version when context7 would have helped |
| B15 | Skill trigger-coverage gap | A **systematic** pass (not opportunistic): load *every* installed skill's `description` via `${CLAUDE_SKILL_DIR}/scripts/find-installed-skills.sh`, then judge — given what this session actually did — which skills *should* have triggered but were never invoked. Each miss whose root cause is weak/missing trigger words → `skill-update` to that skill's `description`. (B2/B4 are the opportunistic, single-skill version; B15 is the exhaustive sweep across the whole inventory. See the trigger-coverage step in `SKILL.md`.) |

### Reusable-learning signals (B16–B20) — scan even when nothing went wrong

These are **positive** signals: the session produced knowledge worth propagating,
with **no** friction to trigger it. The mechanical pre-pass cannot see them (there
is no error, retry, or correction to count), so they exist only as LLM-inference
signals and must be looked for deliberately. The discriminator is *"would a future
agent re-derive this, and is it already in the owning skill?"* — not *"did
something go wrong?"* Grade them **at least `important`** (see
`classification-heuristic.md` → Severity) so they are not crowded out under the
≤10-proposal cap. The `skill-update` arrows below assume the authority check
(Axis 0 in `classification-heuristic.md`) has already run: a learning whose
substance is a fact about the world — tool behaviour, an API, a standard —
routes to `canonical-source` (the owning docs/code), with the skill keeping
only a reference plus the agent-specific delta.

| # | Signal | Hint at |
|---|---|---|
| B16 | Hard-won technique | A non-obvious command / flag / endpoint / API / workflow the session figured out — even cleanly and first-try — that is NOT in the owning skill. Root cause: real digging was needed. → `skill-update` |
| B17 | Proactive improvement | A better approach identified *during* the work (not prompted by a correction) — a cleaner pattern, a faster tool, a simpler structure worth codifying. → `skill-update` |
| B18 | Review-issue learning | A generalizable lesson from a code-review comment (given OR received) — a reviewer taught a rule that applies beyond the current diff. → `skill-update` (or `project-rule` if genuinely repo-specific) |
| B19 | Escaped defect | A finding the session's own checks did not catch before the push: a review thread resolved by a later commit (`resolved` plus `commit_after`), a `CHANGES_REQUESTED` review, a failed quality gate, a ticket sent back from QA (`ticket-transition`). The learning is the missing check, not the fix. Ask which check would have caught it before the push, and route there: the skill that owns that check, a hook, or an eval stub. → `skill-update` (or a gate) |
| B20 | Maintainer request | A human reviewer, maintainer or ticket owner states how work is done here — "please always link the ticket", "agree on rollouts across projects first". A convention the agent did not know, not a defect. → `project-rule` in the repo's `AGENTS.md` when it is about one repository; `skill-update` when it is a team convention across repositories |

### Feedback from outside the transcript

B18–B20 fire only on feedback somebody wrote down, and most of it never enters
the transcript: a bot review nobody opened, a thread answered after the session
ended, a team that does its acceptance in the ticket instead of the PR. Run the
pre-pass before judging them:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/collect-review-findings.py" \
    --transcript-file <session.jsonl> [--output-format json]
```

It reads every PR, MR and issue the session created or wrote to through `gh`,
`glab` (subcommands and `api`), the GitHub MCP tools, or git-workflow's
`pr-merge.sh`. A write counts when its **output reports** the target, never
from the command text alone: a report line is a URL alone on its line, a JSON
`html_url`/`web_url`, a CLI status line (`✓ …`, `- Creating issue in …`)
naming a URL, `owner/repo#N` or `#N`, or `pr-merge.sh`'s own `merged`,
`queued` and attestation lines. A link inside a PR body, a JSON answer or an
error message is running text and does not count. Each write takes only its
own number and its own `-R`; a bare `#N` needs that `-R`; several creates in
one call take one URL each, a create in a `for`/`while` loop takes every URL
of its kind, and a create never takes a URL a numbered write in the same call
reported. A REST write on a literal PR/MR/issue endpoint counts by the
endpoint, and claims the URL it prints itself (a JSON `html_url` line, or the
line `--jq .html_url` prints), matched by repository and number, so
`issues/5` of a PR claims the `pull/5` URL; a create, a variable (also a
whole endpoint held in one) or a
numeric project id in the path counts by the output's report line of that
path's kind and number, or stays unresolved; a REST write on any other
endpoint (code scanning, workflow runs) does not count at all. Continued lines
(`\` + newline) are one command. A write inside a heredoc or quoted text is
never attributed. Whenever a call that writes to a PR, MR or issue names a
target no write claimed — a report line, or any URL when a heredoc script may
have printed it — the call is listed as unresolved, so every write through
these tools ends attributed, unresolved or refused, never silently gone. A
call the harness refused (`is_error` without `Exit code N`) ran nothing. A
successful write that prints nothing counts only as `<verb> <number> -R <repo>`
outside any heredoc or quoted text. Output that reports a failure is not a
success: an `HTTP 4xx/5xx`, `GraphQL:` at a line start or after a colon, a
line starting with `x`/`X`/`✗`, `gh:`, `failed to` or `Cannot perform`, or a
background run. MCP writes count by their input. A `-R` with a scheme and a
host this run does not know (`-R https://x.org/g/p`), or naming `gitlab.com`,
`bitbucket.org` or `codeberg.org`, leaves the write unresolved; any other
dotted first segment is a GitLab group. Writes through other tools — `curl`
against a forge API, a script run in a later call, a script file the call did
not write itself — are not seen at all; name them by hand. A call that holds
a write in text (a heredoc, a quoted string, or a list-form call such as
`["gh", "pr", …]`) and also runs a program it carries is unresolved, whether
or not that program writes: a shell given its program (`bash <<…`,
`bash -lc '…'`); another interpreter's heredoc or inline program
(`python3 - <<…`, `python3 -c '…'`, `node -e '…'`) with a process call such
as `subprocess`; or a script file the call writes (`cat > x.sh <<…`,
`cat >> x.sh`, `cat <<… > x.sh`, `tee x.sh`) and names again later, in any
form (`./x.sh`, `bash -x x.sh`, `timeout 60 x.sh`). A script file is one with
a script suffix, no suffix, or a `#!` line. This errs towards unresolved: a
script that only reads is listed too, a lost write is not possible. A
`python3 -c` without a process call, such as a JSON parser on a pipe, and a
body file (`cat > pr.md <<…` then `--body-file pr.md`) change nothing.
`--dry-run` stops only the `pr-merge.sh` command it is given to. A status
line `! … #N is already …` means the write to `#N` found nothing to do.
It follows each one's linked issues (closing references,
issue URLs in the description) and the Jira key at the start of its title or in
a branch segment one level, plus the tickets the session ran a jira script
against or booked time on, and lists every comment by somebody else — each
answer inside a thread as its own `review-reply`. Jira goes through the
`jira-communication` skill's `jira-issue.py`; without that skill a ticket is
listed as not read. GitLab is read only on the hosts given with `--gitlab-host`
(default `$GITLAB_HOST`, else `gitlab.com`), because `glab` sends its token to any host it is
pointed at. The text output trims bodies; read a finding in full from
`--output-format json` before classifying it. Each finding carries:

| Field | Meaning |
|---|---|
| `source` | `review-thread`, `review-reply` (an answer by somebody else inside a thread, with `thread`, `path`, `resolved`; the opening bot's own follow-ups are not listed), `review`, `pr-comment`, `mr-comment`, `issue-comment`, `ticket-comment`, `ticket-transition` |
| `author_class` | `human`, `bot`, `self`. `self` is the account running the script plus `--self-login`; in Outcome mode run by another account, pass the session's login. The agent's own comments and replies are counted, not listed; in a thread it opened, the answers by others are listed as `review-reply` |
| `report` | a bot's comment on the whole PR/MR (quality gate, coverage, summary), or a bot review that says it did not review (quota, rate limit); rendered apart from the findings. Any other bot review is a finding: its body can carry findings outside the diff. Bot approvals, also those GitHub dismissed on a later push, are not listed |
| `resolved` | the forge's thread state, where it has one |
| `commit_after` | the first PR/MR commit dated after the finding. A necessary sign that the finding changed the code, not proof: any later commit qualifies, and a rebase re-dates them all. Read it with `resolved` and `last_self_reply` |
| `last_self_reply` | the agent's last answer in the thread — the reason, when it rejected the finding. A later `review-reply` by a human can overturn it |
| `last_activity` | the latest entry in the thread; `--since` keeps a thread whose latest entry is at or after it |

Read the `NOT READ` and `UNRESOLVED` lines first: an artefact that could not be
read, and a write whose target the transcript does not name, are unknowns, not
artefacts without findings. A `NO SUCH` line is a key-shaped name Jira does
not know (`TYPO3-14` in a branch) — an answer, not a read failure. A finding answered and followed by no commit was
rejected; when a bot's findings are rejected again and again, the learning is
the reviewer's configuration in that repository (`project-rule`), not the
agent's work. At session end many reviews have not arrived yet — Outcome mode
(D4, D6) runs the same script later.

## Schicht C — Cross-Session

Not detectable from a single session. Session-file scan across projects.

| # | Signal | Hint at | Source |
|---|---|---|---|
| C1 | Same friction again | Same correction across multiple sessions — memory didn't stick | Multi-session JSONL scan |
| C2 | Cross-project pattern | Same friction class in N≥2 projects | Multi-session JSONL grouped by project |
| C3 | Memory drift | `feedback_*.md` exists but assistant violated it anyway → skill needs it more prominently | JSONL diff against memory files |
| C4 | Skill update ineffective | Previous PR to skill X, same bug returned afterward | Git log of skill repo + JSONL |
| C6 | Written rule violated repeatedly | A signal fired >=3x while a matching rule already exists in the always-loaded instructions | Prose has demonstrably failed — needs a mechanical gate, unless one is already deployed (see below) |
| C5 | Follow-up-fix session | A later session exists primarily to fix what an earlier session broke (mentions earlier commits, works on same files within 7 days with reverting edits, or `git revert` of earlier commits) | Cross-session JSONL + git log |

A C6 finding carries `gate_observed`. It is true when a PreToolUse hook denied
a call in this same session for the rule C6 is escalating — the denial reaches
the transcript as that call's tool result, and two of the rule's keywords must
appear in it. Then the control already exists and the finding is not "build a
gate" but "find out why these N passed the one that is installed": the gate may
exempt the shape deliberately, or the detector may be counting what it permits.
False when nothing in the session is attributable to the rule, which is not
proof that no gate exists — check the configured hooks before proposing one.

## Schicht D — Outcome (Post-Session, requires latency)

What happened to the session's output **after** it left the session — good OR
bad? These signals require waiting (days to weeks) before they become reliable.
Best run periodically via `/retro outcome --since 30d`, not at session end.

D1–D10 are **failure** signals (output that didn't survive). **D11 is the
positive mirror:** output that *did* survive is a validated statement of "this is
the way," and its generalizable approach should be codified so future generated
code follows it. A commit is a hypothesis at commit time; it becomes a reliable
"new way" only once it is merged, unreverted, and CI-green — which is exactly what
latency-gated outcome mode confirms. (This mirrors the Schicht B fix: just as the
sweep was friction-only, outcome was failure-only.)

| # | Signal | Detection | Hint at |
|---|---|---|---|
| D1 | Session commit reverted | `git log --grep="revert" + ($commit_sha within revert body)` | Output was wrong |
| D2 | Session commit superseded | Same file touched again within 7 days, diff shows substantial revert of session's changes | Output unfinished or wrong direction |
| D3 | Session PR closed without merge | `gh pr view --json closedAt,merged,state` shows closed, not merged | Output rejected |
| D4 | Session PR required major changes | `collect-review-findings.py` lists human or bot review threads and replies, or findings with `commit_after` — GitHub and GitLab — or a `CHANGES_REQUESTED` review (GitHub; GitLab approvals are not read) | Output below standard; each finding is a B19 candidate |
| D5 | CI failed on session commit | `gh run list --commit $sha --json conclusion` | Output was broken |
| D6 | Issue or ticket feedback after the session | `collect-review-findings.py --since <session end>`: comments and status changes on the linked issues and Jira tickets; plus `gh issue list --search "filename after:$session_date"` for issues that link nothing | Output caused a bug, or the acceptance happened in the ticket |
| D7 | Follow-up session detected | Schicht C5 cross-referenced from outcome perspective | Session output didn't last |
| D8 | Regression in test suite | Test that passed at session end now fails on a later commit | Output regressed |
| D9 | Code reverted in same file within 30 days | Diff-based: session's net contribution to file is largely undone | Output not durable |
| D10 | External tracker mention (out-of-scope marker) | Issue/PR/Slack reference using session commit/PR ID (requires external integration; v0.2+) | Output had external impact |
| **D11** | **Durable improvement (positive)** | Session's change **survived** the window: merged (`gh pr view --json mergedAt,reviewDecision`), **not** reverted or superseded (inverse of D1/D2/D9), CI green (`gh run list --commit $sha --json conclusion`) — AND its approach generalizes but is not yet in any skill | Output is validated by surviving contact with reality → **codify the approach** so future generated code follows it → `skill-update` |
| **D12** | **Superseded temporary copy (positive/cleanup)** | A `canonical-source` upstream PR tracked by a labelled temporary copy (authority label + upstream PR/issue link + `Learning-Id`, per `destination-taxonomy.md` §7) **merged** during the window (`gh pr view <url> --json state,mergedAt`), while the skill still carries the copy | The fact now lives with its canonical owner → **prune the copy to a reference** (+ agent-specific delta) → `skill-update` (prune); find the copy via its `Learning-Id` |

### Stale-open is not an outcome

Read the diff, not the metadata. A PR/MR that is **still open and old** is
*undecided*, not rejected. It is
neither D3 (closed without merge) nor a failure signal — and it must never be
classified "obsolete" from metadata alone. Age, a `has_conflicts` flag, and a
title keyword ("migration", "drop X") are **identical** for a dead change and
for a *blocked cleanup change* that is exactly what should land once its
precondition is met. The difference lives only in the diff and in the current
state of the target branch.

Before calling any stale-open artefact obsolete:

1. **Read its diff.** What would merging it actually do?
2. **Read the target branch now.** Does `main` already contain what the diff
   would do? Only then is it genuinely obsolete → propose closing it.
3. **Otherwise it is blocked, not dead.** The classification is "blocked", and
   the useful question is *by what* — surface the precondition, do not propose a
   close.

A migration-completion or cleanup PR is the textbook trap: it looks abandoned
and is in fact the finish line waiting on a cutover.

### When NOT to use Schicht D

- Session is too recent (< 24h) — most D signals haven't had time to manifest
- Session was a refactor or doc-only change — D2/D9 fire spuriously
- Working on a long-lived feature branch — `git log --grep="revert"` is noisy
- Change is **local / specific with no transferable approach** — D11 must NOT fire; codifying a one-off is exactly the noise the generalizability filter exists to stop (see B16–B20: "would a future agent re-derive this?")
- A PR/MR is **open and stale** — that is not a D-signal at all; see [Stale-open is not an outcome](#stale-open-is-not-an-outcome) above before proposing to close it

D mode is best for **monthly retros over a 30-day window**, not real-time.

## Schicht E — Constitutional (Audit mode only)

Cross-session architectural patterns. Detectable only with longer horizon (weeks/months). Output class is "architectural finding", not "friction finding" — different severity logic, different destinations (often `project-rule` + ADR update, not `skill-update`).

| # | Signal | Detection | Hint at |
|---|---|---|---|
| E1 | ADR violation pattern | Active ADRs declare X; recent N sessions violated X | Design erosion |
| E2 | AGENTS.md rule compliance trend | `feedback_*.md` files exist but sessions repeatedly violate them | Rules aren't reaching the agent |
| E3 | Test coverage trend | Coverage over recent commits trending down | Regression in quality discipline |
| E4 | Skill-inventory drift | Skill count growing without corresponding scope; redundant skills present | Bloat / fragmentation |
| E5 | Dependency staleness trend | Outdated-tool warnings (A16) recurring across sessions | Library maintenance gap |
| E6 | Convention divergence | Style/naming patterns diverging across recent commits | Onboarding or review gap |

E mode is best for **monthly or quarterly reviews**, with tech-lead-level actor and ADR-style output (not per-developer per-session).

## Future directions (out of v0.1.x scope)

External-feedback ingestion would extend the catalog significantly:

- **Sentry / error tracker integration** — production crashes correlated to session-touched files
- **Jira / Linear bug filings not linked from the session's PRs** — `collect-review-findings.py` reads the tickets a PR/MR names; a ticket that mentions session output without being linked is not found
- **Slack / Matrix mentions** — customer/team feedback referencing session commits
- **PagerDuty / OnCall** — production incidents correlated to session output
- **Documentation drift detection** — docs changed but corresponding code didn't (or vice versa)

Each source needs an integration. Track interest before implementing.

## Notes

- **Pre-pass output is structured JSON** consumed by the LLM in Schicht B. The LLM doesn't re-scan the transcript for A-signals.
- **False positives are expected** in Schicht A; B filters them.
- **Schicht C is optional**. It scans session JSONL across projects; absence of multi-session history just means C-signals stay empty.
- **Schicht D requires latency.** Don't run at session end; run monthly with `--since 30d`.
- **Schicht E (audit mode) requires longer horizon.** Quarterly cadence; tech-lead actor.
- **Severity grading happens during classification**, not detection. A single A1 (tool error) might be trivial or critical depending on context — the LLM decides during enrichment.
