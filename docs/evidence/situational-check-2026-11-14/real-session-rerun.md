<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Real-session rerun with code access

This page records the comparison that the [synthetic experiment](README.md)
named as missing: the original real session, rerun with access to the code it
produced. The session digest and the raw run records stay private, because the
session contains private ticket content. Only setup and counts are recorded here.

## Setup

- **Session:** a Claude Code session that reviewed and merged
  [jira-skill#325](https://github.com/netresearch/jira-skill/pull/325). The
  digest was cut before the later note that reported the defect, so no executor
  saw the answer.
- **Defect under test:** with equal status sets and an unreadable workflow
  scheme, `jira-move.py` passed its pre-check, and its post-check could not see
  the case either. [jira-skill#330](https://github.com/netresearch/jira-skill/pull/330)
  later turned that case into a refusal.
- **Code:** jira-skill at `a1297b55` (merge of #325), exported with
  `git archive`, so no later history was visible.
- **Skill versions:** `main` at `c6ee86f` (no B22), the original B22 text at
  `8c2d3ed`, and the withdrawn revision at `c3cd1be`.
- **Runtime:** `claude -p` with model `claude-fable-5-2`, Claude Code 2.1.325, a
  fresh configuration directory, and a working directory that loaded no user
  instructions. A control prompt per batch confirmed the isolation.
- **Grading:** blind grader agents against one oracle per question, written
  before grading, with the arm labels mapped separately.

## Results

| Setup | `main` | original B22 | revised B22 |
| --- | --- | --- | --- |
| Digest only, no code (first run) | missed | missed | not run |
| Code readable, no execution (5 runs each) | 0 found, 1 partial, 4 missed | 3 found, 1 partial, 1 missed | 3 found, 2 partial |
| Code readable, tests and probes allowed in a sandbox (3 runs each) | 3 found | 3 found | 3 found |

The grader marked two results as borderline: one partial of the revised B22 in
the read-only batch, and one find of the original B22 in the execution batch.
In the execution batch every arm ran the test suite and built its own probe
against a fake Jira. Three `main` runs of the read-only batch called the
post-check a working backstop, which the code rules out.

A correct-fix control used a later part of the same session and the code at
`1da6832` (merge of #330), with the same sandbox. All six runs (two per skill
version) were graded clean: 22 code-defect claims, none of them false. The
claims that held included two real defects;
[jira-skill#334](https://github.com/netresearch/jira-skill/pull/334) proposes
fixes for them.

## Conclusion and limits

- Read-only, both B22 versions found the defect in 3 of 5 runs and `main` in
  0 of 5; with tests and probes allowed, every arm found it in 3 of 3. The
  samples are too small to separate the effect of the skill text from that of
  execution. The revision found the defect no more often than the original
  text and was withdrawn.
- Samples are small: one session and one model; one run per cell without
  code (two cells), five read-only, three with execution, two in the control.
- The read-only finding needed only one link: a code comment already admitted
  that equal status sets pass the pre-check.
- The instruction added afterwards (run the tests and one bounded probe in a
  copy) was not run as a separate arm.
