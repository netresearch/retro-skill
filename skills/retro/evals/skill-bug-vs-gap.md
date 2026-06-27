---
id: skill-bug-vs-gap
skill_under_test: retro
mode: spotlight
trigger: "Skill git-workflow has an eval covering signed commits, but this session it told me to use --no-gpg-sign to get a commit through."
expected:
  - classify the friction as a skill BUG (an existing eval covers the behaviour, the skill diverged), not a skill GAP
  - cite the existing eval as evidence that this case is already in scope
  - propose a bounded skill-update that fixes only the contradicted guidance
  - do NOT add a new eval that duplicates the existing coverage
negative_expected:
  - classify it as a missing capability / skill gap and propose a brand-new eval
  - route it to new-skill
  - propose a broad rewrite of the commit section beyond the contradicted line
---

# Scenario: skill bug vs skill gap

A skill **bug** is when an eval already covers the case and the skill's behaviour
diverged from it; a skill **gap** is when no eval covers the case at all (see
[`../references/eval-integration.md`](../references/eval-integration.md) use #1).
Here `git-workflow/evals/` already asserts signed commits, so the `--no-gpg-sign`
advice is a regression against existing coverage — fix the skill, reference the
eval, and do not add a duplicate eval. The discriminator is *"does an eval already
cover this?"*, not *"is the behaviour wrong?"*.
