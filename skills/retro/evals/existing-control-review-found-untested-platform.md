---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: existing-control-review-found-untested-platform
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that changed config-path handling in a Go command-line tool. The pull request went through five review rounds by review agents. The fourth round found that on Windows `\\` is a path separator, so every Windows config path looked like a glob pattern and the existence check passed for paths that did not exist. The agent fixed it, and the fifth round found only edge cases. `.goreleaser.yml` builds release binaries for linux, darwin and windows. The pull-request workflows run `go test ./...` on `ubuntu-latest` only. The test `TestBoot_MissingConfigStillServesWeb` covers the failing path."
expected:
  - "treat the Windows defect as a check that is missing before review, although the review process found it"
  - "propose a CI job on a Windows runner for the affected package, or a decision by the maintainers to drop the Windows release, as a harness-artefact or decision against this repository"
  - "name the evidence: the release targets in .goreleaser.yml against the runners in the pull-request workflows"
negative_expected:
  - "conclude that the review rounds worked, so no check was missed"
  - "propose only a skill reference about Windows paths without a check in the repository"
  - "propose more review rounds"
samples:
  - "The release builds windows, and no pull-request job runs the tests on Windows."
---

# Scenario: review found what a platform job would have found

Review agents are the most expensive place to find a platform defect. The
repository builds a Windows binary and never tests one, so the gap is a
missing CI job, not a working review.
