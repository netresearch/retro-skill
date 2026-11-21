---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: green-session-unwired-checks
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that changed request validation in `src/api/` of a service repository. Before finishing, the agent ran `make test` and `make lint` by hand; both passed and the user accepted the change. The repository has no hook configuration. Its only CI workflow, `.github/workflows/build.yml`, builds the container image and runs neither target. `AGENTS.md` says 'run make test and make lint before pushing'. Nothing failed in the session."
expected:
  - recognise that the checks the session relied on are enforced by nobody, although this session passed them
  - propose wiring the existing `make test` and `make lint` targets into CI (and a fast one as a hook) as a harness-artefact against this repository
  - name the inspected surfaces (CI workflow, hook configuration, AGENTS.md) as the evidence
negative_expected:
  - conclude that a green session with no friction yields no harness finding
  - propose new or additional test suites instead of wiring the existing targets
  - widen the finding into a survey of the whole repository's quality tooling
samples:
  - build.yml runs no test or lint step, and no hook configuration exists.
---

# Scenario: a passing session can expose an unprotected procedure

The next change in `src/api/` depends on someone remembering both commands.
Compare `green-session-checks-already-wired`, the control where CI already
runs them.
