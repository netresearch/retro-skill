<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR-001: Declare decision records in AGENTS.md and anchor them by path

**Status:** Accepted
**Date:** 2026-11-22
**Touches:** `skills/retro/scripts/check-decision-records.py`, `skills/retro/references/destination-taxonomy.md`, `AGENTS.md`

## Context

Retro routes decisions to project rules, but a project's `AGENTS.md` often
does not say whether it keeps ADRs or where. A decision then lands in a
commit, a comment or nowhere, and a later session cannot find it. A review of
trailhq/Trail-Code, which binds learnings to code paths, raised the question
of what retro should take over.

## Decision

- The root `AGENTS.md` of a project states `**ADRs:** yes — <directory>` or
  `**ADRs:** no — <place>` in its Key Decisions. A missing or contradicted
  declaration is a finding (E7). Retro never picks the place; the project
  owner decides yes or no.
- With `yes`, the directory has its own `AGENTS.md` that says how records
  are written.
- A record names the paths it governs in `**Touches:**`. Retro reports
  anchors that are gone (E8) and changes below an anchor (E1, a candidate
  until the record is read).
- retro-skill itself keeps ADRs in `docs/adr/`.

## Ruled out

- **Matching names in a record's prose against the code.** Trail-Code
  measured this and recorded that 9 of the 10 learnings it flagged still
  matched the code (learning `l-3cfeb3b1`).
- **A pre-PR conflict check inside retro.** Retro runs after a session. The
  check before a pull request belongs to the repository's CI, owned by
  agent-harness-skill.
- **YAML frontmatter as the only record form.** The ADRs read in two
  organisation repositories use bold fields; the reader accepts both.

## Consequences

- Existing ADRs without `**Touches:**` are reported as unanchored, not as
  findings, so E1 and E8 apply only to records written with anchors.
- agent-rules-skill has to write the declaration when it generates an
  `AGENTS.md`, and agent-harness-skill has to enforce it.
