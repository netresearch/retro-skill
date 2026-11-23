<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR-004: The Sweep stops after Phase 1b for a short session with no finding

**Status:** Proposed
**Date:** 2026-11-23
**Touches:** `commands/retro.md`, `skills/retro/SKILL.md`, `skills/retro/references/done-mode.md`, `skills/retro/references/friction-catalog.md`, `skills/retro/references/workflow.md`, `skills/retro/evals/sweep-fast-exit-short-clean-session.md`, `skills/retro/evals/sweep-fast-exit-not-on-autonomous-run.md`

## Context

`references/workflow.md` documents the Sweep as "Token cost: highest (full
transcript pass)". `learning-contract.md` accepts "no useful change" as an
outcome, but every Sweep reached it only after the LLM phases, Phase 4
skill discovery and Phase 4b harness inspection. Other retrospective skills
stop early when nothing happened.

The Sweep section and the command both say a smooth session is not exempt:
the pre-pass detects friction only, so a session without friction can still
hold a reusable learning (B16–B21). A pre-pass with no finding therefore says
nothing about learnings. Only the size of the session can carry an early stop.

The detector reports `coverage.status` as `supported`, `empty` or
`unsupported`; none of these says that every content block was measured.
The review collector's `complete` flag says whether each artefact was read
whole and every forge write was resolved.

## Decision

After Phase 1b, a Sweep reports one `Fast exit: …` line and skips Phases
2–9 when all of these hold:

1. `detect-mechanical.py` exited 0, `coverage.status` is `supported` and
   `findings_total` is 0.
2. `collect-review-findings.py`, run without `--scan-since` and read as
   JSON, exited 0 with `complete: true`, empty `findings`, empty
   `unresolved_forge_commands` and exactly one entry in `transcripts`. The
   detector reads only the main transcript; a subagent transcript is work it
   did not measure. `--scan-since` would leave earlier events unread.
3. `user_messages` is at most 3 and `tool_uses` at most 10, counted over the
   whole transcript, also on a repeat `/retro`.
4. The transcript is a Claude Code transcript, located and confirmed by its
   token. A Codex or opencode rollout never takes the exit: the converted file
   has no subagent directory beside it, so `transcripts` always has one
   entry, and the Codex adapter reports incomplete coverage only on stderr.

The `Fast exit:` line names the transcript path, which gives Done gate 3 its
scope. When a condition fails, one line names it and the Sweep continues. The
report also carries one deviation line for the skipped phases,
`B21: none (fast exit)` so that Done gate 8 does not re-run Phase 2, and the
Phase 11 line; Phase 11 still runs. `/retro --full` forces the full Sweep;
like an answer word, `--full` is not a Spotlight problem, and with a problem
or a mode name it has no effect. A fast-exit report is no previous retro for
the repeat-run filter, so `--full` after it reads the whole session. The fast exit never
applies in Spotlight, Outcome, Audit, Promote or Done mode, nor in a Sweep
that Done chains for gate 3; an earlier fast-exit report is a reasoned no-op
for that gate.

The thresholds are set below the detector's own line for a tiny session:
A4 (`A4_MIN_TOOL_USES = 20`) does not fire below 20 tool uses, so below that
size the pre-pass is weakest at telling a long autonomous run from a short
one. Ten tool uses is half that line. A hard-won technique (B16) usually takes
retries or a search, and with a clean pre-pass and at most ten calls there is
little room for either. Three user messages leave room for a request, one
follow-up and one confirmation. A correction that the A6 patterns recognize
blocks the exit; one they miss is part of the residual risk. `user_messages`
counts text blocks, which can only raise the count; the `/retro` invocation
itself is a `<command-message>` turn and is not counted (checked on a
three-event transcript: `user_messages` 1). `tool_uses` does include the
calls the running retro made to locate and confirm the transcript, and a
retro started by a natural-language trigger adds its user message and Skill
call; both make the exit rarer, never wrong.

These numbers are a judgment, not a measurement over recorded sessions. The
signature that would expose them is a later `/retro --full` or Outcome run
on a fast-exited session that finds a B16–B21 learning.

## Ruled out

- **A new detector field for completeness.** It would need code and tests for
  a flag the existing exit codes, `coverage.status` and the collector's
  `complete` already approximate.
- **`findings_total == 0` alone.** The pre-pass does not look for learnings;
  a smooth long session would skip exactly the scan the Sweep exists for.
- **`user_messages` alone.** One prompt followed by a long autonomous run has
  one user message and the most room for a dug-out technique.
- **A bare word such as `full` to force the Sweep.** Any bare word reads as a
  Spotlight problem; a flag-shaped argument does not.

## Consequences

- A short clean Sweep costs two script runs and Phase 11 instead of the LLM
  phases.
- Residual risk: a convention the user stated in a single message (B20), or a
  technique found without a failed call (B16), is not proposed. The fast-exit
  line names `/retro --full` for that case.
- ADR-003 still holds: the command carries every Sweep phase. The fast exit
  skips Phases 2–9, including 4b, only under the conditions above and with an
  announced deviation line.
- On the host where this was written, the seven smallest top-level
  transcripts that ran `/retro` had 87 to 1,038 tool uses and 40 to 351
  pre-pass findings; none would have taken the exit. It targets sessions that
  rarely run a retro today.
- The mode table keeps its Sweep cells; the exit lives in Phase 1b of
  `commands/retro.md`, so `tests/test_command_phase_parity.py` is unchanged.
