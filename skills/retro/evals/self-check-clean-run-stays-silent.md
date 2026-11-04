---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: self-check-clean-run-stays-silent
skill_under_test: retro
mode: sweep
trigger: "End of a `/retro` run. `detect-mechanical.py --signals A1,A2 --since-command retro` lists two errors, both from Phase 9: a `git push` the forge rejected with `Internal Server Error` and a hook denial of `git add -A` in the target repository. Every retro script exited 0, every phase ran or was announced as skipped, and the invocation was a bare `/retro`."
expected:
  - print exactly one Phase 11 line stating nothing was found, with the counts it checked
  - leave the two Phase 9 errors to the target's own handling, because they are failures of the materialized work, not of retro
negative_expected:
  - propose an edit to retro-skill because the phase must produce something
  - turn the forge error or the hook denial into a self-check finding
  - repeat earlier findings about the session in the self-check
samples:
  - tests/test_detect_mechanical_since_command.py
---

# Scenario: a clean run produces one line

The self-check must not create churn in retro-skill. With no evidence of a
fault in retro's own instruments, procedure or reading of the invocation, the
only output is the "nothing found" line. Errors from Phase 9 belong to the
repository being changed.
