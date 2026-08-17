---
id: harness-artefact-over-prose
skill_under_test: retro
mode: sweep
trigger: "Push succeeded, then CI failed 90 seconds later on a formatting violation. The repo runs `composer lint` in CI; its lefthook.yml exists but only runs the test suite, not the linter."
expected:
  - classify as A17 (upstream failure) and route to `harness-artefact`, not to a prose destination — a check could have failed on this friction exactly as it occurred
  - propose adding the CI fast-check command to the repo's existing hook config, citing CI/hook parity (`agent-harness-skill/references/enforcement-mechanisms.md`) — the absence of the hook is the bug, not the operator's care
  - verify the existing artefact first (the `AH-*` globs name the hook-config filenames) and extend `lefthook.yml`, leaving the test-suite entry intact
  - if prose accompanies the gate, it is the recipe for installing the same gate in sibling repos, carried by the owning skill — paired with the gate as one proposal
negative_expected:
  - route to `personal-rule` or `project-rule` as a reminder to run the linter before pushing
  - propose the hook without checking whether a hook config already exists, or overwrite `lefthook.yml` with a template and drop the test-suite entry
  - propose a CI-side change when CI already catches this — the gap is the local layer
  - apply the reach ladder first and default to `skill-update` because a skill reaches more repos
---

# Scenario: a gate outranks a sentence

This is the routing case the enforceability axis exists for (see
[`../references/classification-heuristic.md`](../references/classification-heuristic.md),
"Routing — enforceability first, then reach"). The friction is mechanical,
deterministic, and under the fast-check threshold, so tier 1 is available: the
lesson can be *enforced* rather than *stated*.

The reach ladder pulls the other way — a `skill-update` reaches every repo the
skill touches, while a hook entry reaches one. That pull is what the axis order
exists to resolve. Reach decides where the *prose* goes, and only after
enforceability has claimed what it can. A "remember to run the linter" rule in
`~/.claude/CLAUDE.md` is the wrong destination even though it reaches further:
it restates what the gate would enforce, and the model can still skip it.

The artefact already exists, which is the usual shape of an `AH-*` finding — the
hook config is present but hollow. Extending it is the materialization;
replacing it drops what the team already enforces. See
[`../references/patch-workflow.md`](../references/patch-workflow.md),
"Harness artefacts".
