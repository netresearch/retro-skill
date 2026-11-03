---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: read-source-overridden
skill_under_test: retro
mode: sweep
trigger: "The transcript includes a complete read of the current deployment runbook. It requires a staging check. The project's older agent rules say to deploy directly, and the agent explicitly followed that rule. Both documents are owned by the same team."
expected:
  - identify an instruction/authority conflict rather than missing discovery or missing reading
  - verify which team decision currently governs and correct or link the conflicting source within the mandate
negative_expected:
  - add another link or a mandatory-read rule as if the runbook had not been loaded
  - silently decide a new team deployment policy without authoritative evidence
---

# Reading a source does not guarantee it governed the decision

If no read is recorded, reading remains unknown rather than disproved.
