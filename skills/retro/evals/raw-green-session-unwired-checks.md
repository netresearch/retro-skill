---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: raw-green-session-unwired-checks
skill_under_test: retro
mode: sweep
trigger: "/retro — inspect session.txt and the local artifacts it references."
fixture: fixtures/critical-questions/unwired
expected:
  - "find, from the repository files, that no hook configuration exists and that .github/workflows/build.yml runs neither make test nor make lint, although AGENTS.md asks for both before pushing"
  - "propose running the existing make targets in CI, and the fast lint as a hook, against this repository"
  - "name the files read as the evidence"
negative_expected:
  - "conclude there is nothing to report because the session passed and the user accepted the change"
  - "propose new test suites or new checks instead of wiring the existing targets"
  - "require a hook for a check without stating whether it meets the fast-check definition"
---

# Scenario: green session unwired checks, from raw material

The raw-material counterpart of `green-session-unwired-checks`. This is a synthetic
session; the commands in `session.txt` were run against the supplied files, and
`tests/test_critical_question_fixtures.py` checks that. The executor receives
only the neutral trigger and the fixture, so the deciding facts must be found in
the files, not read from the trigger.
