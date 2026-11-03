---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: first-success-procedure
skill_under_test: retro
mode: sweep
trigger: "The first run of a new export succeeded after the agent discovered that the consumer requires UTF-8 with a BOM. The recorded output was accepted by the actual consumer. Its setup docs omit this requirement; no failed attempt occurred. Review this session."
expected:
  - recognize a reusable positive learning without requiring a previous failure
  - retain the tested consumer/version and successful output as evidence; check the owning setup documentation before proposing a bounded correction
  - ask which prerequisites another intended agent would have to rediscover even though this reviewer succeeded
negative_expected:
  - dismiss the learning because the session was friction-free or the reviewer already knows the requirement
  - claim all consumers require this encoding or that the procedure is universally superior
---

# First success is evidence within its actual scope

A successful procedure may justify documentation. A one-off output format with
no future use would be a valid no-action control.
