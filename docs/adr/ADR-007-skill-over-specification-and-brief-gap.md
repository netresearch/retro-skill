<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR-007: Skill over-specification and brief gap as B-signals

**Status:** Proposed
**Date:** 2026-11-23
**Touches:** `skills/retro/references/friction-catalog.md`, `skills/retro/references/classification-heuristic.md`, `commands/retro.md`

## Context

Schicht B judged an instruction only in one direction. B3 finds guidance a
skill lacked; nothing found guidance that was too much for the work it
governed. Pruning existed as an action (*Instruction pruning* in
`classification-heuristic.md`), but no signal fed it from a session.

Subagent transcripts were already read (`SKILL.md`, Phase 1), but only for the
subagent's own friction. A subagent that lost time because its brief lacked a
fact the caller held was reported, if at all, as the subagent's error.

Two published retro skills name these cases: `giannimassi/agent-retro` lists
over-specification ("too rigid") among skill issues, and
`bitwarden/ai-plugins` (`retrospecting`) asks whether each subagent's brief
was sufficient.

## Decision

Add two LLM-judged signals:

- **B23 Skill over-specification**: a procedure out of proportion to the work,
  with a cost visible in the session. It routes to the skill that prescribed it,
  as a narrowed trigger condition or a removal through *Instruction pruning*.
- **B24 Brief gap**: a brief lacking something the caller held, judged from the
  subagent's transcript. It routes to whatever wrote the brief.

Both carry an exclusion that keeps them from reversing the existing signals: a
step that guarded a risk present in the session is no B23, and a complete
brief with a subagent error is no B24.

## Ruled out

- **Asking a subagent about its brief** (`retrospecting` interviews
  subagents). A finished agent cannot be asked; its "opinion" would be a new
  generation, not evidence.
- **A mechanical B23 based on size** (diff lines against procedure length).
  The test is whether the step's purpose applied, which size does not show.
- **Folding B24 into B3**. B3 routes to the skill whose guidance was missing;
  a brief gap routes to the caller's template, a different owner.

## Consequences

- Instruction pruning now has a session-level inlet besides audit mode.
- A user remark about duration alone does not make B23; the control evals
  check that.
- Both signals depend on reading subagent transcripts. A missing subagent
  transcript makes B24 not assessable, not absent.
