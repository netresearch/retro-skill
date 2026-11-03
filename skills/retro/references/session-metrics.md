<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Session metrics and later applications

Read when an outcome, audit or material improvement needs a time, usage or
effectiveness claim. Collect existing host evidence first; no extra model call
or full cost-accounting deployment is required for an ordinary retro.

## Observed host metrics

```bash
uv run "${CLAUDE_SKILL_DIR}/scripts/collect-session-metrics.py" \
  --transcript-file rollout.jsonl
```

The input may be a raw Codex rollout or Claude-shaped JSONL. Codex cumulative
`total_token_usage` snapshots replace earlier snapshots; their corresponding
`last_token_usage` values are not added again. A decreasing cumulative counter
has unresolved scope and returns unknown usage. Claude `message.usage` updates
replace earlier usage of the same message id; records without an id cannot be
safely deduplicated. This is normalization of recorded values, not independent
verification of the host counters. Missing components remain `null`.

Codex input tokens include cached input; Claude's uncached, cache-read and
cache-write counts are distinct. The report preserves that distinction and
never adds reasoning tokens to output a second time. A recorded cumulative
total may include work outside a truncated excerpt. `complete_session: null`
is not complete coverage. Cost is unknown without a supported actual source;
no model alias is silently resolved to a version or price.

The span between first and last observed timestamps is reported separately
from active work, human waiting and time to an accepted result, which remain
unknown without their own evidence. The adapter `codex-transcript.py` embeds
this summary as `retro_metrics` on its first ordinary message event, preserving
the original time and usage context without inventing an extra user turn.

For supplied child transcripts:

```bash
uv run "${CLAUDE_SKILL_DIR}/scripts/collect-session-metrics.py" \
  --transcript-file parent.jsonl --subagent-transcript child.jsonl \
  --subagent-usage unknown
```

`unknown` is the default: individual reports remain available but aggregate
usage is unknown. Use `included` only with evidence that the parent counter
already contains all supplied children; use `excluded` for disjoint counters.
Intervals are unioned for observed time, never summed as parallel wall time.
Supplying the same path twice is an error. Different transcript copies and
unreported children still require the caller to establish coverage.

The provenance distinguishes the reported execution model from the retro
reviewer, eval executor and eval judge. Roles, exact model version, loaded
skill revisions, tool environment and eval version that the host does not
provide remain unknown. Record additional verified provenance once per run
and reference it from Learning-Ids; never fill unknown fields from the current
reviewer's configuration. An unexpanded alias remains an alias.

Compare the whole task, retro, implementation, verification, delegation,
maintenance and human rework. Unmeasured stages remain explicitly open.
Required quality and authority boundaries are acceptance constraints: fewer
tokens or a faster model are no gain when the result needs more human repair
or misses required quality. Conversely, equal accepted quality made affordable
by a better environment is a valid improvement without a new instruction.

## C4: evidence-backed later opportunities

```bash
uv run "${CLAUDE_SKILL_DIR}/scripts/scan-cross-session.py" \
  --learning-observations observations.json
```

The input is a small JSON array supplied by the reviewer after checking the
relevant sessions. Each item contains nonempty `learning_id`, `opportunity_id`
and `evidence` strings. The stable opportunity id identifies one actual later
task/application across copied transcripts. States `adopted`, `available`,
`loaded`, `applicable`, `applied` and `success` are booleans or `null` (omitting
one also means unknown). A state needs its own supporting evidence. `success`
means the previously stated acceptance criterion was met, including required
quality; it does not mean merely that a PR merged or CI stayed green.

The scanner deduplicates identical Learning-Id/opportunity pairs, refuses
conflicting copies, and counts applicable opportunities separately from fully
observed applications. Only adopted, available, loaded, applicable and applied
changes with a known outcome enter the application success rate. An unloaded
fix, absent opportunity or unknown state is unassessed rather than a failed
intervention. All supplied observations and unknown-state counts remain
visible. Coverage is always `supplied_observations_only`, never a claim to have
searched every relevant session.

The resulting rate describes observed outcomes, not causality or superiority
to an old skill version. Repeated failures need a denominator of comparable
opportunities and successful counterexamples. Check changes in requirements,
infrastructure failures and transcript coverage before attributing a revert
or failure. A correctly applied, unsuccessful measure can warrant revision
of its causal hypothesis; a stale loaded version instead warrants a delivery
check. State confirming, refuting and inconclusive outcomes before making a
material effectiveness claim. Later evidence may confirm, narrow or undo the
measure without blocking completion of the original task.
