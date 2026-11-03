<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Learning Contract

Use this contract when enriching, classifying or pruning a finding, and when
reporting what a previous measure achieved. Reuse the existing `Learning-Id`;
keep the evidence in the proposal, PR or report, not a second knowledge store.

## Purpose and quality boundary

Improve the agent system's ability to finish comparable tasks in the required
quality, within economically feasible time and cost. The system includes models,
instructions, knowledge, tools, environment and collaboration. Improvement is a
direction, not a promise that every subsequent session is easier or cheaper.

Required quality and authorized scope remain binding. Count execution, retro,
implementation, checks, delegation, maintenance and human rework. Saving tokens
while increasing defects or shifting work to people is not an improvement.
Making the same accepted result feasible with a cheaper configuration can be.
If quality, budget and deadline cannot all be met, surface the conflict for the
responsible decision; do not silently lower acceptance criteria.

## What the evidence says

| Statement kind | Preserve | Do not infer |
|---|---|---|
| Observation | Event, context, result | A universal cause from one failure |
| Verified fact | Source, version, verification | Validity beyond that source's scope |
| Decision | Responsible authority, scope, reason | A team norm from a personal request |
| Preference | Whose preference, applicable context | A universal product requirement |
| Hypothesis | Supporting evidence, uncertainty, counterevidence | A confirmed explanation |
| Reusable procedure | Preconditions, steps, result, limits | Superiority from one success |
| Open question | Conflicting evidence, decision needed | Certainty because a field must be filled |

For each relevant finding, make the **claim and kind, evidence, scope, owning
source or authority, and expected future behavior** recoverable. Scope includes
task/project/version and relevant agent configuration when known. Explicit
decisions by a responsible person can be valid after one statement; repetitions
of that same statement or copied transcripts are not independent confirmations.
An inferred intent is labelled as inferred; preserve unknowns and objections.

Material measures also name their target, implementation and availability state,
and what would confirm, refute or leave their expected benefit untested. Record
the next suitable review occasion, not a mandatory ongoing monitoring process.

## Mad, Sad, Glad

Use three brief perspectives in the same enrichment pass:

- **Mad:** What caused avoidable friction? Look for retries, corrections,
  contradictory duties, redundant approvals and tool/environment problems.
- **Sad:** What intended benefit or subgoal remains unmet? Include abandoned
  goals, unused relevant knowledge and avoidable rework even without an error.
  A supposed missed opportunity remains a hypothesis until supported.
- **Glad:** What worked under which conditions? Include useful delegation,
  autonomous decisions, checks and a prerequisite the agent quietly supplied.
  Ask whether another intended executor could find those prerequisites.

These are attention prompts, not claims of emotions or causal proof. A smooth
first success can justify a bounded reusable procedure without a prior failure.
An uneventful session can also end with **no useful change**, with reasons and
coverage stated. Never invent a rule or fill a proposal quota. Missing evidence
is distinct from a supported no-op.

## Configuration bounds and pruning

Distinguish the original executor, retro reviewer, eval executor and eval judge.
They can share a model; their roles and evidence remain distinct. Preserve known
model/version, reasoning budget, context, tools, environment and loaded skill
revision; do not invent unavailable metadata or resolve an alias by guessing.

The reviewer's own competence and absence of friction do not prove an instruction
unnecessary. A powerful reviewer may miss information a cheaper intended
executor needs. Keep transfer to other configurations explicitly untested unless
they actually execute suitable cases. Asking one model to imagine another's
behavior produces a hypothesis.

Correct false or obsolete instructions, and consolidate demonstrably equivalent
coverage, without an indiscriminate model campaign. For removal of action-guiding
instructions, discovery/tool/error-handling changes or observed differences,
select small comparisons on configurations actually used for the task. One real
configuration does not require inventing a second. A no-benefit result is bounded
to its cases and configurations; speculative usefulness to any possible model is
not a permanent retention guarantee. See `eval-integration.md`.

## Claims about later benefit

Prepared, accepted, available, applied and effective are separate claims. A
merged, unreverted change with green CI demonstrates persistence and the checks
that ran. It does not demonstrate adoption, use, superiority or causal benefit.
Before calling a measure ineffective, establish availability, the loaded version,
applicability, actual application and a relevant outcome. Without a suitable
later opportunity, benefit remains untested. A revert can reflect changed
requirements; a CI failure can reflect infrastructure. Read the cause.

Count independent failures relative to suitable opportunities, with successful
counterexamples and missing coverage. Do not treat three failures in four uses
like three in a thousand, or duplicate records as new failures. Future benefit
may remain open after the original task and its authorized changes are complete.
