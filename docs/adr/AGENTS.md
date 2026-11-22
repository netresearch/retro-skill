<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Decision records

This directory holds the decision records (ADRs) of retro-skill. The root
`AGENTS.md` declares it with `**ADRs:** yes`, and
`skills/retro/scripts/check-decision-records.py` reads both.

## When a decision needs a record

Write a record when a change chooses between options that a later change
could reverse without knowing why: a routing rule, a script's contract, a
signal's meaning, a measured limit. A wording fix or a single bug fix needs
none; its pull request is its record.

## Form

One file per decision, `ADR-NNN-<slug>.md`, numbered in order. Use the bold
fields below, then the sections:

```markdown
# ADR-NNN: <Title>

**Status:** Proposed | Accepted | Superseded by ADR-NNN
**Date:** YYYY-MM-DD
**Touches:** `path/one`, `dir/`

## Context
## Decision
## Ruled out
## Consequences
```

- `**Touches:**` names the files, directories or globs the decision governs.
  `check-decision-records.py` reports a named path that is gone (E8) and a
  change below one (E1).
- `## Ruled out` names the options that were rejected and why.

## Changing a decision

Never edit an accepted record. Write a new record that states the new
decision and its reason, and set the old record's status to
`Superseded by ADR-NNN`. A typo, a broken link or a `**Touches:**` path
that moved with its code may be fixed in place.
