---
id: description-no-match-not-conclusive
skill_under_test: retro
mode: spotlight
trigger: "Friction: I forgot that deleting a GHCR package requires both read:packages and delete:packages scopes. No skill description obviously mentions GHCR package deletion."
expected:
  - open the top 1-2 candidate skills' contents (SKILL.md + references/) before concluding "no owning skill" — a description-level no-match is not conclusive
  - find that github-project owns the gh-CLI reference and classify the finding as skill-update against that owning skill
  - route platform/tool ownership to the owning skill even when its one-line description ("GitHub repository setup and platform-specific features") does not obviously match
negative_expected:
  - fall back to user-memory or project-rule because no description string matched
  - classify it as new-skill on the strength of the description-level no-match alone
  - skip inspecting candidate skills' contents and route to memory as the last resort prematurely
---

# Scenario: a description-level no-match is not conclusive

A shallow scan of one-line `description` fields can miss the real owner: a
"GHCR package deletion scopes" finding belongs in github-project's gh-CLI
reference, but its description says only "GitHub repository setup and
platform-specific features". For any tool / platform / workflow finding, retro
must open the top candidate skills' `SKILL.md` and `references/` and check for a
fitting section *before* concluding no skill owns the topic and falling back to
`project-rule` or `user-memory`. The discriminator is *"did I inspect the
candidate skills' contents?"*, not *"did a description string match?"*. Memory
is the last resort, reached only after a content check fails.
