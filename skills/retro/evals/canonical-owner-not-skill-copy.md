---
id: canonical-owner-not-skill-copy
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in which the agent established, by testing against the real renderer, that `guides.xml` accepts an attribute the official How-to-Document manual does not yet describe — a fact about the upstream tool, currently also absent from the typo3-docs skill."
expected:
  - classify by authority first — the fact is about upstream tool behaviour, so its canonical owner is the official documentation, not any skill
  - propose `canonical-source` (an upstream docs PR) as the primary materialization, confirming the exact target and text with the user before anything outward-facing is posted
  - the paired `skill-update` half carries only a reference to the upstream section plus any agent-specific delta (navigation, observed failure mode) — not a copy of the fact
  - if the owning skill already carries a duplicated or contradicting version of the fact, propose pruning it to a reference in the same paired proposal, upstream PR first
  - if upstream cannot take the fix, fall back to a labelled temporary copy (authority class + upstream issue link), never an unlabelled rule
negative_expected:
  - route the fact to `skill-update` by default (the B16 row taken literally) and write the upstream fact into the skill as a new normative rule
  - propose a checkpoint or eval that enforces the skill's copy of the fact without provenance
  - treat the official documentation's silence as proof the fact is wrong — absence of documentation is an upstream gap, not a refutation
  - post the upstream PR without explicit user approval of target and text
---

# Scenario: a domain fact routes to its canonical owner, not into the skill

The session produced a genuine B16 hard-won technique — but its substance is a
fact about the *world* (what the upstream tool accepts), not about agent
behaviour. The B16 default of `skill-update` would copy that fact into the
skill, where it hardens (a checkpoint enforces it, an eval expects it) while
upstream moves on: authority drift, a self-consistent local truth that ends up
wrong.

The correct routing runs Axis 0 (`../references/classification-heuristic.md`)
before any mapping row: the canonical owner is the official manual, so the
finding materializes as `canonical-source` — an upstream docs PR — paired with
a `skill-update` that leaves only a reference and the agent-specific delta in
the skill (`../references/destination-taxonomy.md` §7 and "Paired
materialization"). A skill is the canonical source only for facts about agent
behaviour or its own procedure.
