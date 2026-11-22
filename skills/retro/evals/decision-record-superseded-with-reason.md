---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: decision-record-superseded-with-reason
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in a service repository whose root `AGENTS.md` says `**ADRs:** yes — `docs/adr/``. `docs/adr/ADR-002-retry-limit.md` (Accepted, `**Touches:** `config/retry.yaml``) kept `max_retries: 4` because of the backoff. The user explained that the backoff was replaced by a capped jitter of at most 30 seconds in total and asked for 10 retries. The agent changed `config/retry.yaml` to 10, set ADR-002 to `**Status:** Superseded by ADR-007`, and added `docs/adr/ADR-007-retry-limit-after-capped-jitter.md` (Accepted, same Touches) with the reason; the commit message names both records. `check-decision-records.py --repo . --changed-file config/retry.yaml` printed one finding, E1, naming ADR-007."
expected:
  - "recognise that the change follows the new accepted record ADR-007, which supersedes ADR-002 with a stated reason"
  - "report no decision finding for this change"
negative_expected:
  - "report the change as a violation of ADR-002"
  - "propose a CI gate or a rule because of this change"
  - "propose editing ADR-002 back"
samples:
  - "ADR-002 is superseded by ADR-007 in the same change; ADR-007 states the reason and anchors the same file."
  - "The E1 hit names ADR-007, whose decision the change implements."
---

# Scenario: a deliberate change recorded by a superseding decision

Control for `decision-record-crossed`. An E1 hit only says that a change lies
under a record's anchor. Here the change implements the record that names it,
and the old record was superseded in the same change, so there is no finding.
