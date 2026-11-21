---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: reader-and-timing-of-moved-rules
skill_under_test: retro
mode: promote
trigger: "`/retro promote` over a repository whose always-loaded `AGENTS.md` has grown to 300 lines. About 120 of them are review heuristics (naming, comment style, readability checks) that the repository's review agent applies to diffs. One section states that every database query must filter by `tenant_id`. The repository also has `docs/review-guide.md`, which its review agent is configured to load for every review. The user asked to slim `AGENTS.md`."
expected:
  - move the review heuristics to the review guide, because the review agent reads it for every review
  - keep the tenant filter rule where the implementing agent reads it before writing queries
  - say for each moved part which agent reads it and what triggers that read
negative_expected:
  - move the tenant rule to the review guide, where it is read only after the queries are written
  - move everything that a review could check out of AGENTS.md
  - keep all 120 review lines in the always-loaded file without a reason
samples:
  - The review guide is loaded for every review; AGENTS.md is the only file the implementer reads before coding.
---

# Scenario: a rule moves to the reader who needs it, at the time it is needed

A constraint on how code is designed must reach the implementer before the
design decision. A heuristic applied to a finished diff can live with the
reviewer, provided the reviewer reliably loads it.
