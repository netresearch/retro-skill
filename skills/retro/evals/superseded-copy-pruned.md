---
id: superseded-copy-pruned
skill_under_test: retro
mode: outcome
trigger: "`/retro outcome --since 30d` over a window in which an upstream docs PR — tracked by a labelled temporary copy in a skill (authority label + upstream PR link + `Learning-Id: retro-20260701-output-container-path`) — was merged 12 days ago. The skill still carries the full copied fact."
expected:
  - detect the merged upstream PR as a D12 finding (gh pr view on the tracked URL shows state MERGED within the window)
  - locate the temporary copy via its Learning-Id and propose a `skill-update` whose diff REDUCES the copy to a reference to the now-canonical upstream section plus any agent-specific delta
  - verify the upstream page actually contains the fact before proposing the prune (merged PR is the trigger, the live page is the evidence)
  - keep the proposal a prune, not a delete — the reference and the agent-specific delta survive
negative_expected:
  - leave the copy in place because "it is labelled" — the label plus merged upstream PR is precisely the prune trigger
  - delete the entire section including the agent-specific delta or the reference (losing knowledge the upstream page does not carry)
  - propose the prune while the upstream PR is still open or was closed unmerged (a hypothesis is not a landed fact)
  - route to `personal-rule` or a new prose rule instead of the owning skill's `skill-update`
---

# Scenario: a landed upstream PR retires the skill's temporary copy

The `canonical-source` fallback (destination-taxonomy §7) deliberately leaves
a labelled copy in the skill while upstream cannot take the fact yet — with
authority label, upstream PR link and `Learning-Id` as the recorded prune
trigger. Outcome mode closes that loop: once the tracked upstream PR merges,
the fact lives with its canonical owner, and keeping the local copy re-opens
the authority-drift window the label was supposed to bound.

D12 is the positive/cleanup mirror of D11: nothing went wrong — the system
worked — and the correct materialization is a **removal**. The discriminators:
the upstream PR must actually be merged (not open, not closed-unmerged), the
live page must carry the fact, and the prune must preserve the reference and
any agent-specific delta (`../references/friction-catalog.md` D12,
`../references/destination-taxonomy.md` §7).
