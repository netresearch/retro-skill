<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR-005: Tally rule applicability per audit run, from the transcripts

**Status:** Proposed
**Date:** 2026-11-23
**Touches:** `skills/retro/scripts/scan-cross-session.py`, `skills/retro/references/friction-catalog.md`, `skills/retro/references/learning-contract.md`

## Context

retro prunes instructions ("Instruction pruning" in
`classification-heuristic.md`) and counts repeated violations (C6), but it
cannot name a rule that no session needed. ExpeL (arXiv 2308.10144, § 4.2)
keeps an importance count per insight and drops one at zero; ACE (arXiv
2510.04618, § 3.1) keeps helpful and harmful counters per bullet. Both
references come from the task description and were not re-read for this
record.

## Decision

`scan-cross-session.py --rule-tally <file>` (C7) computes the tally on each
audit run and stores nothing. A rule is a top-level list item. Its id is its
`[→A123]` anchor, else a hash of its text. Its keywords are its backticked
spans. The script counts, per rule, the sessions whose tool calls, tool
results or user turns name a keyword, and marks those where such a text was a
failed call or a user correction. Texts quoting the rule's opening or an
earlier tally are skipped. Below `--min-sessions` (30) sessions read,
`never_applicable` is `null`. The model reads the sessions and judges
followed or violated. A never-applicable rule is a candidate for the existing
pruning path and its bounded comparison, never a removal.

## Ruled out

- **A persistent counter per rule.** `learning-contract.md` keeps evidence in
  the proposal or report, not in a second store; a counter also goes stale
  when a rule's wording changes.
- **Script-judged followed or violated.** A keyword in a failed call does not
  show that the call broke the rule.
- **Keywords from every word of the rule.** Common words match every session,
  so no rule would ever look unused.

## Consequences

The threshold of 30 sessions is a choice, not a measurement. Rules without
backticked spans are `not_measurable`: 164 of 356 items in one real
`CLAUDE.md`. Over 30 real sessions of three days the run took 68 s and
reported 28 rules never applicable. A backticked example output is a quote,
not a topic, and makes a rule look unused. Subagent transcripts are not read. A rule that
prevents its mistake silently also looks unused, which is why a hit only
starts the pruning comparison.
