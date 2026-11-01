---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: dug-out-host-fact-routes-to-inventory
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that spent fourteen tool calls finding out which host runs the nightly export job, until a teammate supplied the host name and the owning team. The project's AGENTS.md names an inventory system and a wiki. A skill covering that service exists and does not state the host."
expected:
  - surface the fact as B21 (dug-out knowledge), citing the run of lookups and the person who supplied it
  - search the inventory first, then the repository docs, the wiki and the tickets, before any proposal, and name the terms used
  - classify by record kind, so a fact about a host and service goes to the inventory as `canonical-source (team record: inventory)`
  - name the exact record and the exact text for approval, and read the record back after the write
  - keep at most a pointer to the inventory plus any agent-specific delta in the skill
  - list the item in the Phase-10 documentation table with what was searched, its state and its URL
negative_expected:
  - route the host fact to `skill-update` by default (the B16 row taken literally) and write the host name into the skill
  - write it into `~/.claude/CLAUDE.md` or project-local memory, where only one agent reads it
  - put it in the wiki because the wiki is the easiest place to write, although an inventory owns host facts
  - report the fact as absent from a system that was never searched
  - fall back to a labelled temporary copy in the skill when the inventory cannot be written
samples:
  - A session's lookups end in "the export job runs on host-a.example.net, team Storage owns it", typed by a colleague. The inventory has no record for the job.
---

# Scenario: a dug-out host fact belongs in the inventory, not in a skill

The session worked out a fact, so B16 reads like the obvious match and its row
says `skill-update`. But a human on call needs this fact as much as an agent
does, and it is a fact about a system we run, not about agent behaviour. Axis 0
(`../references/classification-heuristic.md`) therefore comes first: the kind of
record decides, and a host fact is inventory data.

Phase 4c (`../references/documentation-lookup.md`) runs before the proposal,
because the route depends on what the records hold. The skill may gain one
pointer, and a skill can be public, which is one more reason the host name never
goes there (`../references/destination-taxonomy.md` §7).
