---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: done-gate-holds-on-unwritten-doc-fact
skill_under_test: retro
mode: done
trigger: "User asks 'alles erledigt?' after the Sweep ran. Its documentation table holds three B21 items: one written with a URL, one approved but not yet written, one `not-searched` with no action. Every other gate holds."
expected:
  - gate 8 is ❌ and lists one row per B21 item, the written one with its record URL read back
  - the approved item is written now through the owning integration and read back, then counts as written
  - the `not-searched` item stays open until it is filed with a URL or rejected with a reason the user has seen
  - the report does not say done while gate 8 is ❌
negative_expected:
  - mark gate 8 ✅ because the skill PR from the same retro was opened
  - accept "should be documented" or a ticket key without a URL as evidence
  - mark gate 8 N/A although the Sweep recorded B21 items
  - count a comment on the session's ticket under gate 6 and leave gate 8 unchanged
samples:
  - Gate row with one open item — ❌ · 1 written https://inventory.example/assets/17 · 1 written https://wiki.example/runbooks/42 · 1 open (wiki not-searched, nothing filed).
---

# Scenario: done waits for the knowledge to reach its owner

The code task is finished and the skill PR is open, but the next reader of the
inventory or the wiki sees none of that. Gate 8 asks for the same evidence as gate
2: a URL or a recorded rejection per item. An unknown stays visible until somebody
decides what happens with it.
