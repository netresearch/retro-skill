---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: reachable-doc-gets-a-link-not-a-page
skill_under_test: retro
mode: sweep
fixture: fixtures/source-lookup
trigger: "`/retro` over a session that re-derived the restore order of a database over eleven tool calls. A wiki page states that order correctly, and the session never opened it. The database's inventory record, where the session started, does not link to the page."
expected:
  - surface the fact as B21 and search before proposing; the wiki hit is opened and read
  - answer all three questions, a document exists, it is correct, a reader cannot reach it from the inventory record, and report the state `found-unreachable`
  - propose one change, a link from the inventory record to the wiki page, as `canonical-source (team record: inventory)` with the exact record and text for approval
  - count the added link as written in the Phase-10 table and in gate 8, with the record URL read back
negative_expected:
  - propose a new page, or copy the restore order into the inventory record
  - move the page to the inventory because the inventory comes first in the routing order
  - classify it as B13 with no write, although nothing leads from the starting point to the page
  - write the fact into a skill
samples:
  - Report row — restore order · inventory record · wiki ("restore order") · found-unreachable · link added https://inventory.example/assets/17 → https://wiki.example/pages/9.
---

# Scenario: a correct document nobody reached needs a link

The document exists and it is right, so the session's effort says nothing about
its content. It says the path from the reader's starting point is missing. A
second copy would add a record that can go stale and leave the first one as hard
to find as before (`../references/documentation-lookup.md`).
