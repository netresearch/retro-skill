---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: self-check-unread-feedback-source
skill_under_test: retro
mode: sweep
trigger: "End of a `/retro` run. The session created an issue in a Redmine tracker with `curl -X POST … /issues.json` and got id 111323 back. Phase 1b `collect-review-findings.py` printed `0 artefacts: 0 read … 0 unresolved references; 0 findings` and `2 artefacts only mentioned in the transcript were not read`. The run then queried the tracker by hand and found no reply yet; its report said 'no reviewer feedback'."
expected:
  - in Phase 11, report that Phase 1b missed a write the session made — the collector listed no artefact and no UNRESOLVED line for the POST — and name the turn of the curl call
  - keep the hand-made tracker read as coverage of that gap in this run, and say so, rather than as proof the collector works
  - propose a bounded skill-update against retro-skill for the collector or the feedback contract (an outward write to an unrecognised tracker becomes an UNRESOLVED line), tracker-neutral
negative_expected:
  - read `0 artefacts` as 'the session wrote to nothing'
  - add tracker-specific discovery (a hard-coded Redmine or Forge client) to the core
  - leave the gap out because the hand-made read happened to find nothing
samples:
  - tests/test_collect_review_findings.py
---

# Scenario: the collector did not see a write the session made

Phase 1b exists because review feedback rarely enters the transcript. A write
the collector does not recognise turns into silence that reads like "nothing
there". The self-check notices because the transcript holds the write and the
collector's report holds neither an artefact nor an UNRESOLVED line for it. The
core stays tracker-neutral (see `../references/feedback-contract.md`): the fix
is to surface the write as unresolved, not to learn one tracker.
