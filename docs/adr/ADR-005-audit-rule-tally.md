<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR-005: Tally rule applicability per audit run, from the transcripts

**Status:** Proposed
**Date:** 2026-11-23
**Touches:** `skills/retro/scripts/scan-cross-session.py`, `skills/retro/references/friction-catalog.md`, `skills/retro/references/learning-contract.md`, `skills/retro/references/classification-heuristic.md`, `skills/retro/references/workflow.md`, `commands/retro.md`

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
audit run and stores nothing. markdown-it-py parses the file; a rule is a
top-level list item. Its id is its `[→A123]` anchors, else a hash of its
text. Its keywords are its code spans, cut before a placeholder. The script
counts, per rule, the sessions whose tool-call inputs (their string values),
tool results or user turns name a keyword as a word of its own, and marks those where such a text
was a failed call that was not a refusal, or a user correction. Texts quoting
the rule's opening, tally output, and whole sessions that ran a tally are
skipped. Below `--min-sessions` (30) scanned sessions, `never_applicable`
is `null`. The model reads the sessions and judges followed or violated. A
never-applicable rule is a candidate for the existing pruning path
(`classification-heuristic.md`), never a removal.

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
code spans are `not_measurable`: 167 of 356 items in one real
`CLAUDE.md`. Over 30 scanned real sessions of three days one run took 28 s
and reported 25 rules never applicable; one alternation regex over all
keywords took 111 s on the same data, so each keyword is searched as a
substring and then checked for word boundaries (added 2026-11-24, after these
runs). A backticked example output is a quote,
not a topic, and makes a rule look unused. Subagent transcripts are not read.
A rule that prevents its mistake silently also looks unused, which is why a hit only
starts the pruning comparison.
