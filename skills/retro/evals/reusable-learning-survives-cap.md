---
id: reusable-learning-survives-cap
skill_under_test: retro
mode: sweep
trigger: "A busy session with ~14 friction items (push rejected, phpstan-after-push, commit on main, banned co-author trailer, wrong-repo correction, hallucinated API, ...) PLUS two friction-free learnings: the session discovered `jira-worklog-query.py --tempo-account` filters per account (plain query returns all) with no error, and a reviewer taught that a named constant does not clear SonarCloud php:S1313."
expected:
  - surface BOTH friction-free learnings as findings even though neither produced an error, retry, or correction — the hard-won technique as B16 and the review lesson as B18
  - grade each reusable-learning finding at least `important`, not `nice-to-have`
  - retain both learnings within the ≤10-proposal cap (reserve slots so friction does not crowd them out)
  - route both to `skill-update` against the owning skill (jira skill; SonarCloud/php skill)
negative_expected:
  - return 10 friction proposals and zero learnings because friction filled the cap
  - grade a friction-free learning `nice-to-have` and drop it first when trimming
  - only surface the review lesson by reframing it as a *recurring* friction (critical) while silently dropping the clean technique
  - treat the smooth stretch of the session as producing no findings
---

# Scenario: a friction-free learning must survive the proposal cap

The default sweep is friction-tuned: the mechanical pre-pass counts errors,
retries, and corrections, and severity grades most non-friction findings
`nice-to-have`. In a busy session, friction findings are numerous and easy to
grade high, so under the ≤10-proposal cap they crowd out exactly the
friction-free learnings the retrospective exists to also capture (see
[`../references/friction-catalog.md`](../references/friction-catalog.md) B16–B18
and [`../references/classification-heuristic.md`](../references/classification-heuristic.md)
→ Severity → "Cap protection").

The discriminator for a reusable learning is *"would a future agent re-derive
this, and does an existing skill already say it?"* — not *"did something go
wrong?"* A hard-won `--tempo-account` flag (no error) and a code-review lesson
(no in-session failure) are both first-class findings, graded at least
`important`, and both must appear in the final proposal set even when a dozen
friction items compete for the same ten slots.
