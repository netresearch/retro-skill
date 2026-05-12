# Friction Catalog

All friction signals retro-skill detects, organized in three layers (Schichten) by detection mechanism.

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

## Schicht C — Cross-Session

Not detectable from a single session. Optional Coach-events read; otherwise session-file scan.

| # | Signal | Hint at | Source |
|---|---|---|---|
| C1 | Same friction again | Same correction across multiple sessions — memory didn't stick | Coach events OR JSONL scan |
| C2 | Cross-project pattern | Same friction class in N≥2 projects | Multi-session JSONL grouped by project |
| C3 | Memory drift | `feedback_*.md` exists but assistant violated it anyway → skill needs it more prominently | JSONL diff against memory files |
| C4 | Skill update ineffective | Previous PR to skill X, same bug returned afterward | Git log of skill repo + JSONL |

## Notes

- **Pre-pass output is structured JSON** consumed by the LLM in Schicht B. The LLM doesn't re-scan the transcript for A-signals.
- **False positives are expected** in Schicht A; B filters them.
- **Schicht C is optional**. Absence of Coach data triggers JSONL fallback; absence of multi-session history just means C-signals stay empty.
- **Severity grading happens during classification**, not detection. A single A1 (tool error) might be trivial or critical depending on context — the LLM decides during enrichment.
