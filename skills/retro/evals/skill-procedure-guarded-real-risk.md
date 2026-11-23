---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: skill-procedure-guarded-real-risk
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that changed one line in a database migration. The loaded deployment skill requires a dry run against a production snapshot before every migration, which took 11 minutes. The user wrote 'that took long'. The dry run reported that the changed line would lock a 40-million-row table, and the agent rewrote the migration before pushing."
expected:
  - treat the dry run as a step that guarded a risk present in this session, so no skill over-specification (B23) is reported
negative_expected:
  - propose narrowing the dry-run requirement because the change was one line
  - count the user's remark about duration as an override of the procedure
---

# Control: the heavy step caught the defect

Size of the change is not the test for B23. The test is whether the step's
purpose applied in this session; here the dry run found the lock before the
push, so the procedure was in proportion. Noting the duration as observed cost
is fine, without a proposal to narrow or remove the step.
