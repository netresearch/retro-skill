---
id: durable-change-codified
skill_under_test: retro
mode: outcome
trigger: "`/retro outcome --since 30d` over a past session whose PR merged 20 days ago, was never reverted or superseded, passed CI, and introduced a non-obvious approach (a caching pattern for an expensive call) that no installed skill currently documents. The same window also contains a second session whose commit was reverted after 3 days."
expected:
  - surface the reverted commit as a D1/D9 failure finding (learn what to avoid)
  - ALSO surface the merged, unreverted, CI-green change as a D11 durable-improvement finding — a positive outcome, not only failures
  - route the D11 finding to `skill-update` to codify the validated approach so future generated code follows it, graded at least `important`
  - confirm durability from the outcome evidence (merged + no revert in window + CI green) before codifying — treat the commit as validated, not hypothetical
negative_expected:
  - report only the failure (reverted commit) and treat the successful merged change as "nothing to do"
  - codify the merged change even though its approach is local/one-off with no transferable rule (generalizability filter must gate D11)
  - codify the change at commit time without waiting for the latency window (a fresh, unreverted commit is a hypothesis, not yet a durable statement)
  - grade the durable-improvement finding `nice-to-have` and let it drop
---

# Scenario: a durable success must be codified, not just failures learned from

Outcome mode historically detected only **failure** (D1–D10: reverted commits,
rejected PRs, broken CI). D11 is the positive mirror: a change that **survived**
the window — merged, unreverted, CI-green — is a validated statement of "this is
the way," and where its approach generalizes and is not already in a skill it
should be codified so future generated code follows it (see
[`../references/friction-catalog.md`](../references/friction-catalog.md) D11 and
the "good OR bad" framing of Schicht D).

The discriminator is the same generalizability filter as B16–B18 — *"would a
future agent re-derive this, and does a skill already say it?"* — plus a
durability gate unique to outcome mode: a commit is a hypothesis at commit time
and becomes codifiable only once latency confirms it survived. A local one-off
that merged cleanly is not a learning; a generalizable approach that survived is.
