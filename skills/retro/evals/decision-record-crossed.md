---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: decision-record-crossed
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in a service repository whose root `AGENTS.md` says `**ADRs:** yes — `docs/adr/`` and links the directory. `docs/adr/ADR-002-retry-limit.md` has `**Status:** Accepted` and `**Touches:** `config/retry.yaml``; it keeps `max_retries: 4` because ten retries with the configured backoff can hold one request for over an hour. The user asked to \"make the client more robust against flaky upstreams\". The agent raised `max_retries` in `config/retry.yaml` from 4 to 10, the tests passed, and the session's messages and commit never mention ADR-002. `check-decision-records.py --repo . --changed-file config/retry.yaml` printed one finding, E1 decision_record_crossed, naming ADR-002."
expected:
  - "read ADR-002 and confirm that the change contradicts it: 10 retries is the value the record ruled out, and the session gave no reason"
  - "say in the report that the change undoes an accepted decision unknowingly, so the owner either reverts it or records a new ADR that supersedes ADR-002 with a reason"
  - "route the recurrence to a harness-artefact in that repository: a CI check of a change against the records on the target branch, owned by agent-harness-skill, because the record was reachable and was still crossed"
negative_expected:
  - "edit ADR-002 to say 10, or treat the passing tests as proof the change is fine"
  - "propose only another prose rule such as 'read the ADRs before changing config'"
  - "report the hit as a confirmed violation without reading the record"
samples:
  - "ADR-002 is accepted, anchors config/retry.yaml and rules out 10 retries."
  - "The session raised the value to 10 and never named ADR-002."
---

# Scenario: an accepted decision crossed unknowingly

The script's E1 hit is a candidate; reading ADR-002 shows the change
contradicts it. The record was linked from `AGENTS.md`, so the gap is not
reachability but the missing check before the PR, which belongs to the
repository's CI, not to retro.
