---
id: no-action-low-confidence
skill_under_test: retro
mode: sweep
trigger: "A single user 'hm, ok' after one slightly verbose answer — no correction, no repetition, no pattern anywhere else in the session."
expected:
  - propose NO materialization — a weak, single-occurrence signal with no pattern is not a durable learning
  - report an empty or near-empty result without inventing a rule
  - treat 'nothing actionable' as a valid, successful outcome
negative_expected:
  - manufacture a user-memory or skill-update rule from one ambiguous, low-confidence signal
  - pad the proposal list to look productive
  - escalate a one-off into a cross-project pattern without cross-session evidence
---

# Scenario: no action on a low-confidence signal

retro exists to return a *short list of durable* learnings, not to find something
every run (see [`../README.md`](../README.md) — the anti-Coach premise: ≤10 real
proposals, not 1011 candidates). A lone low-confidence signal with no correction,
repetition, or cross-session echo should produce **no** proposal. The discipline
under test is restraint: an empty report is a correct report.
