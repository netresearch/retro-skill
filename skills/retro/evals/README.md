<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# retro's own evals

These scenarios test **retro's own classification behaviour** — the Phase-5
judgement calls that are retro's entire value: skill-bug vs skill-gap, when to
prune an instruction, and when *not* to propose anything at all. retro ships
them so it is a regression target for its own reasoning, and so that
`/retro "fix the retro skill"` has real fixtures to read.

## What these are (and are not)

- **Retro-owned, repo-scoped fixtures.** They test the router, not any other skill.
- **They do NOT impose a schema on other skills' evals.** retro still *reads*
  every other skill's `evals/` leniently and schema-free — see
  [`../references/eval-integration.md`](../references/eval-integration.md). The
  small frontmatter schema below is retro's own local business only.
- **They are LLM-graded.** `expected` / `negative_expected` are behavioural
  assertions a human or model checks against a real `/retro` run.
  `scripts/validate-evals.py` checks *well-formedness*, not behavior.
  `scripts/prepare-behavior-evals.py` freezes selected prompts and adapts them
  to the existing shared runner; preparing inputs does not execute or grade them.

## Format

```markdown
---
id: <slug — must equal the filename without .md>
skill_under_test: retro
mode: sweep | spotlight | outcome | audit | promote | done
trigger: <one-line friction or user statement that starts the scenario>
expected:
  - <behaviour retro should exhibit — classification + bounded action>
negative_expected:
  - <behaviour that would be wrong>
fixture: fixtures/<optional raw input directory>
---

# Scenario: <short human-readable title>

<prose: the context, the correct classification, and the evidence retro should cite>
```

Required keys (enforced by `scripts/validate-evals.py`): `id`, `trigger`,
`expected` (non-empty list), `negative_expected` (non-empty list). `id` must
equal the filename stem and be unique.

## Running them

```bash
uv run skills/retro/scripts/validate-evals.py # from repository root; structure only
```

For real runs, use the bounded procedure in
[`../references/eval-integration.md`](../references/eval-integration.md).
Give the execution agent only its frozen prompt, selected context and raw
inputs. Give `expected`, `negative_expected` and the scenario explanation to
the evaluator separately. A proposed command, a transcript, and a passed
structure validator are different from an accepted task outcome.

## Initial acceptance coverage

These are the 26 agreed acceptance scenarios, mapped to maintained fixtures.
Existing cases remain in their original format; this is an index, not a second
copy of their expected answers.

| # | Acceptance area | Fixture |
| --- | --- | --- |
| 1 | First successful technique | [first-success-procedure](first-success-procedure.md) |
| 2 | No reusable learning | [no-action-low-confidence](no-action-low-confidence.md) |
| 3 | Unconfirmed cause | [hypothesis-not-fact](hypothesis-not-fact.md) |
| 4 | Correct but hard-to-find source | [reachable-doc-gets-a-link-not-a-page](reachable-doc-gets-a-link-not-a-page.md) |
| 5 | Read source overridden | [read-source-overridden](read-source-overridden.md) |
| 6 | Old loaded version, corrected source | [loaded-version-behind-source](loaded-version-behind-source.md) |
| 7 | Duplicate mechanism | [duplicate-learning-consolidated](duplicate-learning-consolidated.md) |
| 8 | Rejected promotion | [promotion-pr-rejected](promotion-pr-rejected.md) |
| 9 | Canonical replacement of a copy | [superseded-copy-pruned](superseded-copy-pruned.md) |
| 10 | Already authorized edit | [authorized-reversible-change](authorized-reversible-change.md) |
| 11 | Decision outside mandate | [decision-outside-mandate](decision-outside-mandate.md) |
| 12 | Unnecessary rule | [unnecessary-rule-simplified](unnecessary-rule-simplified.md) |
| 13 | Repeated setup prerequisite | [environment-prerequisite](environment-prerequisite.md) |
| 14 | Unfulfilled goal without error | [unfulfilled-goal-sad](unfulfilled-goal-sad.md) |
| 15 | Deferred effectiveness | [deferred-effect-not-done-blocker](deferred-effect-not-done-blocker.md) |
| 16 | Durable but unused change | [durable-change-codified](durable-change-codified.md) |
| 17 | Correct application without benefit | [applied-change-no-benefit](applied-change-no-benefit.md) |
| 18 | No relevant later opportunity | [no-matching-opportunity](no-matching-opportunity.md) |
| 19 | Unknown and inclusive usage | [usage-unknown-inclusive](usage-unknown-inclusive.md) |
| 20 | Shifted human rework | [human-rework-hidden](human-rework-hidden.md) |
| 21 | Reviewer versus intended executor | [reviewer-not-target-config](reviewer-not-target-config.md) |
| 22 | Shorter skill regresses for actual target | [shorter-skill-target-regression](shorter-skill-target-regression.md) |
| 23 | False or outdated instruction | [obsolete-instruction-removal](obsolete-instruction-removal.md) |
| 24 | Possibly ineffective correct instruction | [bounded-instruction-ablation](bounded-instruction-ablation.md) |
| 25 | Environment enables affordable quality | [environment-enables-economics](environment-enables-economics.md) |
| 26 | Cheaper output fails required quality | [cheap-quality-regression](cheap-quality-regression.md) |

The full corpus also retains earlier routing and completion regressions.
No-op, authorized variants and valid alternative wording are controls, not
failures to make the test discriminating.

## Tool-enabled integration inputs

Four cases carry a `fixture` directory with synthetic raw artifacts. The adapter
copies it into an isolated execution directory; modify only that copy.

| Case | Observable outcome to evaluate |
| --- | --- |
| Source lookup | Inspect the entry point and runbook; review the actual link diff and ensure the authoritative procedure was not duplicated. |
| Loaded version | Inspect the captured installed content and current source; verify the source stayed intact and any authorized local distribution correction matches it. |
| Promotion | Read the closed-unmerged status and destination; verify the active learning remains reachable and the bridge's status is truthful. |
| Environment | Run the original command from a fresh copy to reproduce failure, then inspect the change and rerun from fresh state and consecutively. The checker must still validate the database. |

Keep those outcome checks with the evaluator. The tested agent receives the
raw task in `session.txt`, not this table or the scenario's expected solution.
The environment fixture uses local SQLite only; it requires no network service.

## Selecting actual targets

Start with the configuration actually used for the task. Include an existing
cheaper/faster path when an important change or observed difference warrants it;
one real configuration is sufficient if no second path is in use. Record model
roles, unresolved aliases, reasoning budget when known, context, tools, runtime
and frozen skill/eval hashes. Do not invent a universal model ranking.

Instruction removal, tool choice, recovery, discovery changes and observed
configuration regressions merit targeted comparisons. A normal retro does not
require a second model round, and correction of false content or reliable
duplicate consolidation does not require a broad model campaign.
