<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# retro's own evals

These scenarios test **retro's discovery, classification and bounded checks**:
whether a gap is found in raw artifacts, how it is routed, and when *not* to
propose anything at all. retro ships them as regression targets, so that
`/retro "fix the retro skill"` has real fixtures to read.

## What these are (and are not)

- **Retro-owned, repo-scoped fixtures.** They test retro, not other skills.
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

Seven cases cover the missed situational check (B22) of
[`../references/friction-catalog.md`](../references/friction-catalog.md): one
omitted check ([situational-check-omitted](situational-check-omitted.md)), its
mirror ([situational-check-overgeneralization](situational-check-overgeneralization.md)),
a claim without the check
([situational-check-claimed-not-performed](situational-check-claimed-not-performed.md)),
and four controls that must not produce a finding: independent causes in one
file, a justified small fix, information that appeared only later, and evidence
retro cannot read (`situational-check-independent-causes`,
`-justified-small-fix`, `-later-information`, `-not-assessable`).
These are described classification cases. Score the substantive finding and
evidence equally under any signal ID; they do not measure unaided discovery.

### Raw session reconciliation

The `session-reconciliation-*` cases contain **synthetic sessions with executable
local artifacts**. Their recorded commands were run against the supplied files;
the fixture tests independently verify the relevant properties. They are not
captures of the earlier real-session experiment reported in PR #232.

| Case | Evaluation scope |
| --- | --- |
| [A](session-reconciliation-a.md) | Find an unmet requirement from the original request, implementation and green recorded checks, without a later defect report. |
| [B](session-reconciliation-b.md) | Accept the correct bounded change and its relevant verification. |
| [C](session-reconciliation-c.md) | Preserve uncertainty when delegated implementation and execution evidence are missing. |
| [D](session-reconciliation-d.md) | Transfer the procedure to a distinct requirement; reserve its first run until the instruction revision is frozen. |

The functional oracles do not require B22 vocabulary. A correct older-version
answer receives equal credit. The trigger supplies no diagnosis. Keep the
scenario frontmatter and explanations outside the executor's inputs; a later
revision informed by a case makes it development data, not an untouched test.

The [2026-11-14 native comparison](../../../docs/evidence/situational-check-2026-11-14/README.md)
records eleven executions and their limits. Original and revised instructions
gave the same functional outcomes; no detection or repair gain was observed.
Case D's first-use status was consumed by that run. The revision it compared,
including a separate in-work check mode, was later withdrawn; its records stay
as provenance.

## Tool-enabled integration inputs

The original four cases below and the reconciliation cases carry a `fixture`
directory. The adapter copies it into an isolated execution directory; modify
only that copy when its task authorizes changes.

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
