<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# ADR-002: Bound the collector's transcript scan with its own option, not with `--since`

**Status:** Accepted
**Date:** 2026-11-22
**Touches:** `skills/retro/scripts/collect-review-findings.py`, `skills/retro/scripts/derive-session-scope.py`, `skills/retro/references/workflow.md`

## Context

`collect-review-findings.py --transcript-file <session> --since <time>` read
every artefact the whole session and its subagents named, then dropped
comments older than `--since`. On a 382 MB session with 1,091 subagent
transcripts (3.8 GB) it named 1,072 PRs, MRs and issues. Scanning took 68 s;
reading them from the forge at 0.7 s per GitHub PR and 2.2 s per GitLab MR
would have taken an estimated 15 minutes, and the run was killed at 500 s.
The window the caller cared about, the last hour, named 13.

Outcome mode passes `--since <session end>` to see feedback that arrived
after a past session (`commands/retro.md`, friction catalog D6). There every
artefact sits before `--since`.

## Decision

`--scan-since <ISO>` bounds the scan: an event with an older top-level
timestamp is not read, and a subagent transcript whose file was last written
before it is not opened. Events without a timestamp are read, a call made
before the cutoff whose result arrives after it counts, and each line is
checked on its own, because timestamps in a transcript are not in order
(23,673 of 155,526 main-transcript lines, 758 of 1,091 subagent files).
The output names the skipped files and counts the skipped events.
`--since` keeps its meaning: it decides which comments are listed.

## Ruled out

- **Let `--since` bound the scan.** Outcome mode would find no artefact
  before the session end and report no feedback. The session end is typed by
  the agent, so it can also fall before the last event.
- **Skip a subagent file by its last line's timestamp.** Most files are not
  in order; the file's modification time bounded every event in all 1,091.
- **Read only the `--ref` artefacts when refs are given.** `--ref` adds to the
  transcript's artefacts; with the scan bounded, the network work is already
  the refs plus the window.

## Consequences

A caller that wants a window of a long session passes `--scan-since`, and
usually `--since` with the same time. An artefact named only before the cutoff
is not read even when its feedback arrived later; the text output says so.
A transcript copied with a newer modification time is scanned line by line,
which costs time and changes no result.
