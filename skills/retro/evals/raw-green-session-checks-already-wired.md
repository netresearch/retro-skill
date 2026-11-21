---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: raw-green-session-checks-already-wired
skill_under_test: retro
mode: sweep
trigger: "/retro — inspect session.txt and the local artifacts it references."
fixture: fixtures/critical-questions/wired
expected:
  - "find, from the repository files, that .github/workflows/ci.yml runs make lint and make test and .pre-commit-config.yaml runs the linter"
  - "propose no harness change for these checks"
negative_expected:
  - "propose adding the same checks to CI or a hook again"
  - "propose a prose rule telling agents to run the checks"
---

# Scenario: green session checks already wired, from raw material

The raw-material counterpart of `green-session-checks-already-wired`. This is a synthetic
session; the commands in `session.txt` were run against the supplied files, and
`tests/test_critical_question_fixtures.py` checks that. The executor receives
only the neutral trigger and the fixture, so the deciding facts must be found in
the files, not read from the trigger.
