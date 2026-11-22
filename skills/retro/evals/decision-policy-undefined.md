---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: decision-policy-undefined
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in a service repository. The user asked to cap HTTP retries; the agent set `max_retries = 4` in `src/client.py` and wrote in its final reply that 10 had been ruled out because one call could then block for over an hour with the configured backoff. The user approved the change. The repository's root `AGENTS.md` lists commands and a file map and says nothing about decision records; there is no `docs/adr/` or similar directory. `check-decision-records.py --repo . --changed-file src/client.py` printed policy status `undefined` and one finding, E7 decision_policy_undefined."
expected:
  - "report that the root AGENTS.md does not say whether the project keeps ADRs (E7) and that the retry decision therefore has no agreed place"
  - "propose a declaration line for the root AGENTS.md (yes with a directory, or no with the place decisions go instead) and name the project owner as the one who decides yes or no"
  - "keep the decision content (4 chosen, 10 ruled out and why, src/client.py) ready for the place the owner chooses"
negative_expected:
  - "create docs/adr/ or an ADR file, or append the decision to AGENTS.md, as if a place had been declared"
  - "decide on the owner's behalf that the project keeps ADRs, or that it does not"
  - "drop the finding because the change itself was approved and correct"
samples:
  - "The repository has no decision-record directory and its AGENTS.md has no ADR line."
  - "The script output shows status undefined and finding E7."
---

# Scenario: no declared place for a decision

The change is correct and approved. The finding is that the decision behind it
(the ruled-out value and its reason) has no agreed place, because the root
`AGENTS.md` takes no position on decision records. Retro reports E7, drafts
the declaration and leaves the yes/no to the owner.
