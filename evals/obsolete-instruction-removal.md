---
id: obsolete-instruction-removal
skill_under_test: retro
mode: spotlight
trigger: "A skill keeps recommending `npm install`, but the repo is a bun project and the skill already has an eval requiring bun commands."
expected:
  - classify as a skill bug, not a new gap
  - propose REMOVING (or replacing) the npm-biased instruction — removal is a valid skill-update
  - cite where the correct behaviour is already covered (the existing bun eval) as the evidence for removal
  - keep the edit bounded to the contradicted instruction
negative_expected:
  - add a new broad package-manager instruction while leaving the npm instruction in place
  - require an A/B rollout or a generated eval to "prove" the removal before proposing it
  - create a duplicate bun eval that already exists
  - ignore the existing eval coverage
---

# Scenario: obsolete instruction removal

This is the pruning path (see
[`../references/classification-heuristic.md`](../references/classification-heuristic.md)
→ "Instruction pruning"). retro tends to *add*; here the right edit is to
*delete* the stale npm instruction, because the desired behaviour is already
covered by the existing bun eval. The evidence for removal is the covering
location (the eval), not a measured A/B score — retro proposes, the human
approves, and the source-repo PR review decides. Prefer removal over stacking
another exception.
