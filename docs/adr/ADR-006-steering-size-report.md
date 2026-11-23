<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR-006: Report the size of the steering files, never gate on it

**Status:** Proposed
**Date:** 2026-11-23
**Touches:** `skills/retro/scripts/steering-size.py`, `tests/test_steering_size.py`, `skills/retro/references/project-harness-inspection.md`, `commands/retro.md`, `skills/retro/references/workflow.md`

## Context

The files that load in every turn (the repository's root `AGENTS.md` and
`CLAUDE.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`) cost context in
every turn. `project-harness-inspection.md` said so but measured nothing, and
retro's own `personal-rule` and `project-rule` proposals add lines to these
files. On the day of this record the global rules file of the maintainer had
414 lines and 127,756 bytes. OpenAI describes keeping its repository
`AGENTS.md` at about 100 lines, as a map to other documents ("Harness
engineering: leveraging Codex in an agent-first world").

## Decision

1. `scripts/steering-size.py` prints, as JSON, lines, bytes and
   `approx_tokens` (bytes / 4, labelled approximate; no tokenizer dependency)
   for each of these files, marks a repository `AGENTS.md` that a
   `CLAUDE.md` line `@AGENTS.md` imports, and with `--proposed` adds the
   signed delta of a proposed whole file. It exits 0 whatever the sizes.
2. Phase 4b states the sizes. Phase 7 states the delta of every proposal that
   edits one of these files, and a proposal that adds lines says why the
   content cannot live in a linked document or a skill. The criteria are the
   existing ones: `destination-taxonomy.md` § `project-rule` and the
   two-direction test in `promote-mode.md`.
3. The 100-line figure is quoted as a reference with its source, never as a
   limit.

This extends ADR-003's Phase 4b without changing its shape: the size goes into
the existing steering-files surface, and the report line stays one line.

## Ruled out

- **A threshold that blocks or downgrades a proposal.** A rule that must hold in
  every turn belongs in these files whatever their size (`promote-mode.md`,
  rule 1); a size gate would push such rules out.
- **A tokenizer dependency for an exact count.** Counts differ per model, and
  lines and bytes already show growth.
- **New pointer-versus-content criteria.** The destination rules already state
  them; a second copy would drift.
- **Following every `@` import.** Only `@AGENTS.md` is marked, the import that
  makes a repository `AGENTS.md` load for Claude Code; other imports are not
  measured.

## Consequences

- A proposal to an always-loaded file carries its cost in numbers, so growth
  shows in each retro report. Whether that slows growth is not measured yet.
- `approx_tokens` is rough for prose and code alike; quote lines and bytes
  as the measurement.
- `.claude/CLAUDE.md` in a repository and nested `AGENTS.md` files are not
  measured.
