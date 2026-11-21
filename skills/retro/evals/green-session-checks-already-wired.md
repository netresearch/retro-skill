---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: green-session-checks-already-wired
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that changed request validation in `src/api/` of a service repository. Before finishing, the agent ran `make test` and `make lint` by hand; both passed and the user accepted the change. `.github/workflows/ci.yml` runs `make lint` and `make test` on every pull request, and `.pre-commit-config.yaml` runs the linter on commit. Nothing failed in the session."
expected:
  - recognise that the checks the session ran are already enforced by CI and a hook
  - propose no harness-artefact for these checks
negative_expected:
  - propose adding the same checks to CI or a hook a second time
  - propose a new prose rule telling agents to run the checks
samples:
  - ci.yml already runs both targets, and the hook runs the linter.
---

# Scenario: the protection already exists

Control for `green-session-unwired-checks`.
