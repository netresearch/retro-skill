<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Eval Integration

Use existing evals to inform classification and make important behavior changes
reviewable. Keep fixture validity, actual agent decisions, tool state and later
practical benefit separate.

## Contents

- [Consult the target's existing evals](#consult-the-targets-existing-evals)
- [Add or tighten an eval](#add-or-tighten-an-eval)
- [Prepare bounded behavioral comparisons](#prepare-bounded-behavioral-comparisons)
- [Reuse the shared text runner](#reuse-the-shared-text-runner)
- [Run tool-enabled integration cases](#run-tool-enabled-integration-cases)
- [Choose actual configurations and preserve provenance](#choose-actual-configurations-and-preserve-provenance)
- [Report evidence at its actual level](#report-evidence-at-its-actual-level)

## Consult the target's existing evals

After matching a `skill-update`, inspect `<skill-root>/evals/` and, if applicable,
`skills/<name>/evals/`. Read the files before assuming a schema. Other skills may
use a JSON array, an object containing `evals`, or Markdown scenarios. Retro's
own fixed Markdown schema does not impose a format on them.

Existing coverage can distinguish a **skill bug** (a covered behavior diverged)
from a **skill gap** (the needed behavior is absent). An absent eval does not
prove missing capability. Cite a real scenario or run; never invent an A/B
comparison that did not occur. A normal retrospective analyzes its evidence;
it does not require re-executing every original task.

When an actively maintained target has accessible CI eval failures, those can
inform a requested pre-emptive review. Do not infer failure from an inaccessible
run or start unrelated investigations from an unverified status.

## Add or tighten an eval

Use the destination's existing layout. For a JSON eval with pattern-bearing
assertions, write both a valid sample and isolated failing variants:

```json
{
  "eval_name": "handle-bun-projects",
  "prompt": "This is a bun project. Install the dependencies.",
  "assertions": [
    {"type": "content", "pattern": "bun install"},
    {"type": "must_not", "pattern": "npm install"}
  ],
  "samples": {
    "passing": "Run bun install to add the dependencies.",
    "failing": ["Run npm install to add the dependencies."]
  }
}
```

`check-eval-samples.py` refuses a new or tightened pattern-based JSON eval
without `samples.passing`; write `samples.failing` too so both directions are
checked. `materialize-pr.sh finish` runs that gate; a hand-written patch runs it
before commit:

```bash
uv run ${CLAUDE_SKILL_DIR}/scripts/check-eval-samples.py --repo . <path>/evals.json
```

The requirement is scoped to touched JSON evals and assertions supported by the
sample validator. Plain-string assertions, expectations-only cases and retro's
Markdown fixtures have different semantics; do not retrofit a fleet or force
samples that their grader cannot evaluate. The shared JSON validator reads
assertion objects' `pattern` or `value`, while the runtime runner can also use
bare strings. Inspect the selected grader rather than assuming equivalence.

Retain the original correct sample when tightening. Add variants changing one
required claim at a time, and valid alternate wording, including coordinated
negation. Run the actual grader's matching semantics. Reach for `must_not` or
`not_content` where supported; a positive keyword cannot distinguish a wrong
claim containing the same word. Do not rewrite a valid control merely to satisfy
a narrower regex. An erroneous oracle can optimize a skill toward worse behavior.

Retro's own `id`, `trigger`, `expected`, `negative_expected` schema is documented
in `evals/README.md`. `validate-evals.py` checks its structure and inventory,
not agent behavior. JSON assertion/sample checks establish internal consistency,
not actual model success. `claude plugin eval` uses another layout; migrating to
it or introducing another runner is unnecessary for this integration.

## Prepare bounded behavioral comparisons

`scripts/prepare-behavior-evals.py` adapts the existing Markdown corpus and
writes into a new isolated run directory:

- `execution/`: trigger-only prompts, raw fixture copies and explicitly selected
  skill context snapshots. Expected answers and scenario explanations stay out.
- `grading/`: the private `expected` and `negative_expected` oracle.
- `shared/evals.json`: prompts and expectations in the shared runner's schema.
  Its executor reads `prompt`; its separate judge reads `expectations`.
- `manifest.json`: preparation status, intended configuration, adapter and input
  hashes. It is **not a run receipt**.

From the repository root, prepare only relevant cases:

```bash
uv run skills/retro/scripts/prepare-behavior-evals.py \
  --case loaded-version-behind-source \
  --case promotion-pr-rejected \
  --reference references/skill-discovery.md \
  --reference references/promote-mode.md \
  --target-label actual-primary --model ACTUAL_MODEL_ALIAS \
  --runtime ACTUAL_RUNTIME_VERSION \
  --output-dir /path/to/new-isolated-run
```

Replace the configuration placeholders with actual intended values. `--all`
prepares the entire corpus when useful; preparation calls no models. Supply
`--baseline-dir /path/to/old/skills/retro` to freeze a second context for the same
cases. Each selected reference must exist in both snapshots; a missing file is
an error. For a newly added reference, use `--candidate-reference` explicitly;
it is recorded only in the candidate snapshot. This makes a deliberate loading
change visible rather than inventing baseline content. Snapshots record explicit
loading, not automatic discovery.

With a baseline, candidate cases live at `execution/<id>/` and independent
baseline copies at `execution/baseline-cases/<id>/`; edits cannot contaminate the
other arm. The manifest records both paths. Run each target only on its own arm.

Give the tested agent only its frozen context, prompt and copied raw inputs.
Keep scenario frontmatter, prose explanations and expected answers with the
independent evaluator. The 26 initial acceptance cases map to maintained
Markdown fixtures in `evals/README.md`; earlier regressions remain intact.

The `situational-check-*` cases classify described situations; they do not
demonstrate discovery from raw session material. Grade the supported behavior,
not the signal ID, outcome vocabulary or report format. An equally supported
finding from an older catalog receives equal credit.

For discovery comparisons, use the raw `session-reconciliation-*` cases. Give
both arms identical inputs and tools, with no later defect report or expected
diagnosis in their prompts. Require the original property, the implementation
evidence and the inadequacy of the recorded check to support the finding.
Accept code inspection as well as execution evidence. Correct implementations
and missing historical coverage are controls, not invitations to invent a
finding. A Check-mode execution case separately tests the in-work entry and
its bounded correction; a retrospective report alone cannot establish that.

Freeze the cases and criteria before comparing, and keep development cases
separate from a first-use transfer case. Once its result informed a revision,
that case is no longer held out. Report all arms and failures, including a zero
delta. Passing new synthetic artifacts neither reruns nor repairs an earlier
real-session result whose raw inputs are unavailable.

The adapter does not stage inputs. For hindsight, give the target only the
session prefix at the decision point and preserve its response before exposing
later evidence in a separate turn. Later information may legitimately change
the artifact assessment; it must not be treated as knowledge the earlier agent
already had. Do not infer hindsight merely because the later verdict changes.

## Reuse the shared text runner

Use
[`skill-repo-skill/scripts/run-ab-evals.sh`](https://github.com/netresearch/skill-repo-skill/blob/72f4464a7406a0ed74314bdc81aedaac06e87a76/scripts/run-ab-evals.sh)
for classification and response comparisons. At that verified revision it
serves no tools or MCP, fixes executor/judge aliases to `sonnet`/`haiku`, and
writes into its checkout's `scripts/ab-results`. The adapter's `--model` records
an intended native configuration; it does not reconfigure this runner. Read
its actual result provenance before saying which model ran. Unresolved aliases
are not exact model versions.

For old/new contexts, use separate clean runner checkouts so the fixed output
path cannot overwrite earlier artifacts. Set these variables to actual absolute
locations, then invoke the existing runner:

```bash
bash "$SHARED_BASELINE/scripts/run-ab-evals.sh" \
  --evals="$RUN_DIR/shared/evals.json" \
  --skill="$RUN_DIR/execution/baseline-context.md" --samples=3 1
bash "$SHARED_CANDIDATE/scripts/run-ab-evals.sh" \
  --evals="$RUN_DIR/shared/evals.json" \
  --skill="$RUN_DIR/execution/candidate-context.md" --samples=3 1
```

Each invocation compares no-skill with its selected context. Compare the two
with-skill results only for matching cases/configurations and disclose separate
runs rather than a direct randomized old/new experiment. Repeated samples help
with consequential claims; retain valid controls and inspect uncertain or
conflicting judgments. A zero observed delta is scoped to the tested cases and
configuration. It does not prove universal uselessness.

`--no-llm` skips expectations grading, so expectations-only cases yield no
behavioral verdict. Current workflow and credential state must be checked when
running; an old schedule or credential observation is not current evidence.
Nested CLI runs need isolated configuration so host plugins/hooks do not
contaminate one arm. Use the provider's supported authentication and a fresh
per-run configuration; preserve the observed isolation in run metadata.

The existing nested-Claude check found that SessionStart plugin hooks leaked
into target answers. Its measured workaround used a fresh `CLAUDE_CONFIG_DIR`,
with a restricted copy of the operator's existing credentials, removed on exit:

```bash
RETRO_EVAL_CONFIG=$(mktemp -d)
trap 'rm -rf "$RETRO_EVAL_CONFIG"' EXIT
cp ~/.claude/.credentials.json "$RETRO_EVAL_CONFIG/"
chmod 600 "$RETRO_EVAL_CONFIG/.credentials.json"
printf '%s\n' '{"hasCompletedOnboarding": true}' > "$RETRO_EVAL_CONFIG/settings.json"
export CLAUDE_CONFIG_DIR="$RETRO_EVAL_CONFIG"
```

Export once around a multi-call runner so every nested call gets that directory;
feed the CLI stdin from `/dev/null` when needed to avoid its stdin wait. In that
earlier check, `--bare` lost authentication, and an empty `--plugin-dir` or
`--settings '{"hooks":{}}'` did not suppress plugin SessionStart hooks. These
are recorded host/version observations: recheck effective isolation for the
runtime used, without printing credentials. Keep this CLI-specific setup out of
native child evaluations that do not launch that CLI.

## Run tool-enabled integration cases

The four synthetic fixtures indexed in `evals/README.md` exercise source lookup,
loaded-version diagnosis, a rejected promotion and a local setup command. Their
raw `session.txt` supplies the local task and mandate. The adapter copies each
fixture into its execution directory; operate only on that disposable copy.

A native target must actually inspect and act on its inputs. Record its tool
trace, file diff and executed checks, then have an independent evaluator inspect
the result against the private oracle and original artifacts. Saying a command
was run is insufficient: verify the exit result or actual file state. A text-only
runner cannot establish those integration outcomes.

A fresh-context child with only the frozen inputs provides independent forward
evidence. A reviewer inheriting the implementation chat remains useful for
review but already knows intended answers; label that boundary. If the host
cannot supply a fresh target, record the limitation instead of claiming a blind
test. Its own host instructions still govern the execution agent.

## Choose actual configurations and preserve provenance

Start with the actual primary configuration. Include an actually used cheaper
or faster path for an important change or observed difference; do not create an
artificial second configuration or universal model matrix. Instruction removal,
discovery, tool choice, recovery changes and observed model differences are
triggers for targeted comparisons. A normal retro needs no extra model round.
Correction of false content or reliable consolidation needs no broad campaign.

Record effective executor, reviewer and judge roles separately; retain model
versions when available, unresolved aliases otherwise, reasoning budget, runtime,
context, tools, actual skill/eval hashes, completed samples, errors and outputs.
Preparation metadata describes intention until a run proves the effective
configuration. A strong reviewer's guess about another model is a hypothesis,
not execution evidence.

## Report evidence at its actual level

| Evidence | Supported claim |
| --- | --- |
| Adapter unit tests and frozen fixtures | Technical transformation and oracle separation work for tested inputs. |
| Markdown validation or assertion/sample checks | Shape or internal consistency; no agent decision observed. |
| Actual target response judged against held-out oracle | A decision passed under the recorded configuration. |
| Tool trace and independently checked file/command state | Tested integration behavior occurred in the isolated case. |
| Later comparable real task applies the available change | Scoped evidence about practical use and effect. |

Missing outputs, timeouts, unavailable runtimes and API limits are incomplete,
not passes. Unknown costs remain unknown. Total effort includes evaluation,
implementation, delegation, maintenance and human rework. Passing a behavior
case does not itself prove sustained benefit or authorize publication.

See also `references/skill-discovery.md`, `references/classification-heuristic.md`
and `references/patch-workflow.md` for discovery, routing and materialization.
