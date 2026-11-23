<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR-003: The slash command carries every Sweep phase, and an existing control does not close a friction

**Status:** Accepted
**Date:** 2026-11-23
**Touches:** `commands/retro.md`, `skills/retro/SKILL.md`, `skills/retro/references/classification-heuristic.md`, `skills/retro/references/friction-catalog.md`, `skills/retro/references/project-harness-inspection.md`, `tests/test_command_phase_parity.py`

## Context

On 2026-11-22 a Sweep and a second retrospective (`mattpocock-skills:retro`,
which asks only for changes to the agent's environment) ran over the same five
sessions. The second retrospective ran later in each session, so part of its
candidates came from work done after the Sweep. Of the candidates that
predate the Sweep, the Sweep had seen several and closed each with a reason of
one kind, a control already existed. In one session it closed 17 GitHub
rate-limit failures as "documented in the watcher reference", the hook
refusals as "the gates worked", and a Windows-only defect found in the fourth
review round as "no missed check". In another session it closed its own script
time-out as "the session is too long".

`/retro` loads `commands/retro.md`, not `SKILL.md` or the references. The
mode table in `references/workflow.md` runs Phases 2b (trigger coverage) and
4b (project-harness inspection) in the Sweep, but the command had no section
for either. In the four sessions whose reads are visible in the main
transcript, no run opened `project-harness-inspection.md`.

## Decision

1. Every phase that the mode table runs in the Sweep has a `## Phase <id>`
   section in `commands/retro.md`. `tests/test_command_phase_parity.py`
   enforces this; on the previous command it reports 2b and 4b missing.
2. Phase 4b in the command names three surfaces (guardrails, steering files
   that load in every turn, tool output and errors) and one report line.
3. A rule, document or gate that existed does not close a friction that
   happened anyway. Classification names what the control left open: a gate
   false positive, prose that a correct gate makes redundant, a warning that
   did not prevent the cost, a check missing before review, a script defect,
   or a document out of reach. "No action" stays valid with its cost stated.

## Ruled out

- **A new mechanical signal for each lens.** The Sweep had detected most of
  these frictions; it closed them. A detector does not change a disposition.
- **Copying the second retrospective's category list.** Its categories map to
  existing destinations and to `project-harness-inspection.md`; the gap was
  that the loaded command did not lead there.
- **Measuring with described cases alone.** Five described cases passed with
  the unchanged command too, because each trigger states the decisive facts
  already sorted. The comparison that separates the two texts uses the real
  session evidence (`docs/evidence/existing-control-2026-11-23/`).

## Consequences

- An eval that freezes `SKILL.md` and references does not measure the text a
  `/retro` run loads. `prepare-behavior-evals.py` accepts only files inside
  the skill directory and always adds `SKILL.md`; a comparison of the
  command text copies the command into the context by hand.
- The control case `existing-control-negligible-refusal` pins that a correct
  refusal with a negligible cost still yields no proposal.
