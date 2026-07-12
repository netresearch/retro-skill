# Friction Catalog

All signals retro-skill detects, organized in four layers (Schichten) by
detection mechanism and a fifth (constitutional) for cross-session architectural
analysis.

Despite the name, this catalog covers **two classes**: *friction* (things that
went wrong) and *reusable learnings* (knowledge that went right but is not
captured anywhere — Schicht B, signals B16–B18). Both are first-class retro
findings; a signal-free stretch of a session can still carry a learning worth
propagating.

## Scope and honest limitations

This catalog covers what retro-skill **can** detect from session transcripts, post-session git/PR history, and cross-session JSONL data.

**It does NOT detect:**
- Architectural choices that are wrong but "work" (no friction signal)
- External feedback the agent never saw (production alerts, customer complaints, Slack/Jira mentions)
- Slow constitutional drift unless `/retro audit` mode is run with sufficient history

External-feedback ingestion (Sentry, Jira, monitoring) is out of v0.1 scope — see "Future directions" at the bottom.

## Implementation status (v0.1.1)

| Schicht | Catalog signals | Implemented in code |
|---|---|---|
| A — Mechanical | 18 | 18 (all of A1–A18) |
| B — LLM inference | 18 | LLM-driven (no separate code); B16–B18 are reusable-learning signals |
| C — Cross-session | 5 | Partial (script `scan-cross-session.py`) |
| D — Outcome | 11 | Planned for v0.1.x; D11 is the positive (codify-success) signal |
| E — Constitutional (audit) | 6 | Planned for v0.1.x |

Schicht A is feature-complete. See `references/destination-taxonomy.md` for what each signal class routes to.

## Schicht A — Mechanical (Python pre-pass)

Fast, deterministic, regex/count-based. Runs before LLM pass to reduce token cost. See `scripts/detect-mechanical.py`.

| # | Signal | Detection | Hint at |
|---|---|---|---|
| A1 | Tool error rate | `exit_code != 0` or `is_error: true` in tool_use_result | Wrong tool, wrong args, missing tool |
| A2 | Tool retry cluster | Same tool + similar args ≥3× within N turns | Tool misunderstanding, missing docs |
| A3 | Tool output verbosity | `len(tool_result) > X` without subsequent filter | Token waste, wrong tool (cat vs head, full Read vs Range) |
| A4 | Tool call count vs task | Total tool calls / user messages ratio above threshold | Inefficiency for simple task |
| A5 | Sequential vs parallel | Multiple independent calls serial in separate blocks | Performance waste |
| A6 | User correction phrases | Regex: `^(no\|nein\|stop\|don't\|wrong\|NEIN\|nicht so)`, ALL CAPS, `!!!` | Classic friction |
| A7 | Prompt repetition | Semantic similarity of user messages within N turns | Assistant didn't understand |
| A8 | Prompt sequence repetition | n-gram match (n=2..5) over user message sequence | Workflow ripe for snippet/command |
| A9 | Tool sequence repetition | n-gram match over tool_use names + arg templates | Composition opportunity, skill instruction gap |
| A10 | Skill in reminder vs invoke | `<command-name>` in system reminder, no matching Skill call | Skill not triggered |
| A11 | Wrong tool choice | `grep` on JSON, `sed` on YAML, `cat` for huge file | Tool-not-used / wrong tool |
| A12 | Re-read same file | Read tool same path ≥2× without intervening Edit | Caching opportunity |
| A13 | Skipped verification | Claim "tests pass" / "fixed" without prior test/build run | Verification skip |
| A14 | Worked on main/master | Git commands without prior `checkout -b` | Workflow violation |
| A15 | Bot attribution in commit | Commit message contains "Generated with Claude" / "Co-Authored-By: Claude" | Known user rule violated |
| A16 | Outdated tool warning | "deprecated", "is now", "use X instead" patterns in stderr | Out-of-date knowledge |
| A17 | Upstream failure | `git push` fails on pre-receive, `gh pr checks` fails post-push, post-commit lint fail | Pre-push verification gap (shift-left) |
| A18 | Permission re-approval | Same permission prompt approved ≥3× in session | Allowlist needed |

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
| B15 | Skill trigger-coverage gap | A **systematic** pass (not opportunistic): load *every* installed skill's `description` via `scripts/find-installed-skills.sh`, then judge — given what this session actually did — which skills *should* have triggered but were never invoked. Each miss whose root cause is weak/missing trigger words → `skill-update` to that skill's `description`. (B2/B4 are the opportunistic, single-skill version; B15 is the exhaustive sweep across the whole inventory. See the trigger-coverage step in `SKILL.md`.) |

### Reusable-learning signals (B16–B18) — scan even when nothing went wrong

These are **positive** signals: the session produced knowledge worth propagating,
with **no** friction to trigger it. The mechanical pre-pass cannot see them (there
is no error, retry, or correction to count), so they exist only as LLM-inference
signals and must be looked for deliberately. The discriminator is *"would a future
agent re-derive this, and is it already in the owning skill?"* — not *"did
something go wrong?"* Grade them **at least `important`** (see
`classification-heuristic.md` → Severity) so they are not crowded out under the
≤10-proposal cap.

| # | Signal | Hint at |
|---|---|---|
| B16 | Hard-won technique | A non-obvious command / flag / endpoint / API / workflow the session figured out — even cleanly and first-try — that is NOT in the owning skill. Root cause: real digging was needed. → `skill-update` |
| B17 | Proactive improvement | A better approach identified *during* the work (not prompted by a correction) — a cleaner pattern, a faster tool, a simpler structure worth codifying. → `skill-update` |
| B18 | Review-issue learning | A generalizable lesson from a code-review comment (given OR received) — a reviewer taught a rule that applies beyond the current diff. → `skill-update` (or `project-rule` if genuinely repo-specific) |

## Schicht C — Cross-Session

Not detectable from a single session. Session-file scan across projects.

| # | Signal | Hint at | Source |
|---|---|---|---|
| C1 | Same friction again | Same correction across multiple sessions — memory didn't stick | Multi-session JSONL scan |
| C2 | Cross-project pattern | Same friction class in N≥2 projects | Multi-session JSONL grouped by project |
| C3 | Memory drift | `feedback_*.md` exists but assistant violated it anyway → skill needs it more prominently | JSONL diff against memory files |
| C4 | Skill update ineffective | Previous PR to skill X, same bug returned afterward | Git log of skill repo + JSONL |
| C5 | Follow-up-fix session | A later session exists primarily to fix what an earlier session broke (mentions earlier commits, works on same files within 7 days with reverting edits, or `git revert` of earlier commits) | Cross-session JSONL + git log |

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
| D4 | Session PR required major changes | `gh pr view --json reviews` has CHANGES_REQUESTED with substantive review body | Output below standard |
| D5 | CI failed on session commit | `gh run list --commit $sha --json conclusion` | Output was broken |
| D6 | Issue filed referencing session files | `gh issue list --search "filename after:$session_date"` | Output caused a bug |
| D7 | Follow-up session detected | Schicht C5 cross-referenced from outcome perspective | Session output didn't last |
| D8 | Regression in test suite | Test that passed at session end now fails on a later commit | Output regressed |
| D9 | Code reverted in same file within 30 days | Diff-based: session's net contribution to file is largely undone | Output not durable |
| D10 | External tracker mention (out-of-scope marker) | Issue/PR/Slack reference using session commit/PR ID (requires external integration; v0.2+) | Output had external impact |
| **D11** | **Durable improvement (positive)** | Session's change **survived** the window: merged (`gh pr view --json mergedAt,reviewDecision`), **not** reverted or superseded (inverse of D1/D2/D9), CI green (`gh run list --commit $sha --json conclusion`) — AND its approach generalizes but is not yet in any skill | Output is validated by surviving contact with reality → **codify the approach** so future generated code follows it → `skill-update` |

### When NOT to use Schicht D

- Session is too recent (< 24h) — most D signals haven't had time to manifest
- Session was a refactor or doc-only change — D2/D9 fire spuriously
- Working on a long-lived feature branch — `git log --grep="revert"` is noisy
- Change is **local / specific with no transferable approach** — D11 must NOT fire; codifying a one-off is exactly the noise the generalizability filter exists to stop (see B16–B18: "would a future agent re-derive this?")

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
- **Jira / Linear bug filings** — tickets mentioning session output
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
