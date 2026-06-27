---
id: mechanical-failure-not-skill-update
skill_under_test: retro
mode: sweep
trigger: "The mechanical pre-pass flagged three tool errors, but all three were a flaky network timeout to an external registry that succeeded on retry."
expected:
  - filter the mechanical signal as a false positive during LLM enrichment (Schicht B) — a transient environment failure is not a skill defect
  - propose NO skill-update for it
  - route to a checkpoint / harness-artefact only if a real, repeatable gate (e.g. a retry guard) would genuinely have helped — otherwise no action
  - keep the proposal list focused; do not let a mechanical A-signal auto-become a finding
negative_expected:
  - turn the transient tool error into a skill-update that bloats a SKILL.md with environment-specific advice
  - propose a durable rule for a one-off infrastructure hiccup
  - treat every Schicht-A signal as a materializable finding
---

# Scenario: mechanical failure is not a skill-update

Schicht A is deterministic and over-fires by design; Schicht B filters it (see
[`../references/friction-catalog.md`](../references/friction-catalog.md)). A flaky
external timeout is mechanical noise, not friction a skill can fix. The default
for a non-repeatable, environment-caused failure is **no materialization** —
protecting the ≤10-proposal, anti-Coach discipline. Only escalate to a
checkpoint/harness when a concrete mechanical gate would actually have prevented it.
