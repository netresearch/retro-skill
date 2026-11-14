<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Situational-check discovery experiment

**Decision: keep PR #232 in draft. No additional detection or repair success
was observed in this experiment.** The revised procedure is executable, but
these results do not establish that it improves the existing skill.

## Why the revision exists

The initial PR classified a visible warning as a missed situational check.
It did not specify how to discover the warning when a session and its reviews
appeared successful. Its seven scenarios supplied the diagnosis and some
oracles required vocabulary absent from `main`. The original PR description
also recorded a real-session failure: both arms missed the quiet defect.

The revision adds a bounded search from the original requirement through the
changed implementation to the check of that same property. A concrete gap
leads to code inspection or a small safe counter-probe before classification.
It adds an explicit `/retro check` entry for use during authorized work,
separates defect evidence from future remedy benefit, and makes the old
classification oracles neutral to signal names.

Those are implementation changes, not measured benefits. The original
real-session digest, underlying revision and raw execution records were not
available here; this experiment does not replace or overturn that failure.

## Protocol and scope

- **Original:** PR head `8c2d3ed9379380940d22bbc3a1cac2b367dfbb4d`.
- **Main:** `c6ee86f1578af299f6c71b6bb414395f01577b0b`, sampled on case A only.
- **Revised:** frozen worktree snapshot; file hashes are in
  [manifest.json](manifest.json). Extracting and applying the `patch` field of
  [candidate-snapshot.json](candidate-snapshot.json) to the original PR revision
  reconstructs the executor-visible skill; all file hashes were independently
  checked after reconstruction. JSON preserves the patch's whitespace.
- **Runtime:** fresh native collaboration threads with `fork_turns=none`.
  The model was inherited from the parent; its resolved provider version was
  not independently exposed. This was not the original Claude configuration.
- **Sampling:** one run per arm and case, eleven executions total. No variance
  or general success rate can be estimated from this sample.
- **Inputs:** synthetic chronological sessions and executable before/after
  files, saved API/content responses and recorded check outputs. There was no
  later defect report in the executor input. Expected answers remained outside
  executor directories, and the copied skills excluded their eval directory.
- **Isolation:** execution agents received no implementation conversation or
  outcome oracle. Shared host developer instructions still applied; filesystem
  scope was instruction-enforced, not an OS sandbox.
- **Task:** read the supplied skill and retrospectively review the recorded
  work, read-only, offline and within the run directory. Check executions were
  explicitly asked to inspect the current decision and continue the authorized
  local task. Both arms received that instruction even though the original
  skill had no dedicated Check mode.

The existing `prepare-behavior-evals.py` adapter froze the five scenarios and
their private oracles. Execution used a complete copied skill, without evals,
so each agent could load relevant references itself. Case D was held out from
core revision development and first exercised after the source freeze. Its
fixture unit test was read after that freeze. It is now an exposed regression
case, not a reusable unseen holdout.

## Observed outcomes

| Case | Required distinction | Original PR | Revised | Main |
|---|---|---|---|---|
| A | Find the unreported pagination omission despite green checks | Found and reproduced | Found and reproduced | Found and reproduced |
| B | Accept a correct small pagination repair | No defect alleged | No defect alleged | Not run |
| C | Preserve uncertainty when delegated implementation and checks are missing | Not assessable | Not assessable | Not run |
| D | Transfer to a page/language cache-key omission | Found and reproduced | Found and reproduced | Not run |
| Check | Repair the incomplete inventory under the existing mandate | Repaired; 4 tests passed | Repaired; 4 tests passed | Not run |

The parent independently replayed both Check results: all four tests passed
and both commands returned `["build", "deploy"]`. The original arm repaired a
disposable `work/` copy; the revised arm repaired its disposable `inputs/after`
copy. Both satisfy the functional task. Snapshot hashes confirmed that every
read-only run preserved its inputs and skill; Check changed only the authorized
implementation and tests, and neither Check changed its skill.

The original arm interpreted the explicit Check request successfully using
its existing focused-review behavior. The new named mode therefore has no
demonstrated incremental repair benefit in this experiment. Automatic skill
selection or timely invocation during ordinary coding was not tested.

These cases show that the revised instructions can be followed and that the
selected correct/unknown controls were handled. They provide **zero observed
incremental successes** over the original PR. A different label or a shorter
report is not a detection gain. No token, cost or latency benefit is claimed.

## Records and evidence limits

The `runs/` JSON records preserve each agent's report and self-recorded command
log. Check records also include final code and the parent's independent replay
outputs. These logs are not an automatically captured complete native tool
transcript. The grading inputs used neutral item IDs and functional criteria;
[grading-map.json](grading-map.json) records the arm mapping separately.

The independent [grades](grades.json) accept all nine retrospective reports on
their functional content and verify both final repair outcomes. Of 29 expected
criteria, 25 are met and four remain partly verified: the pre-repair probes and
execution order rely on agent-written logs rather than independent raw traces.
No prohibited behavior is supported, but complete access/write history remains
unknown. This is not an eleven-of-eleven fully audited execution claim; see the
[grading summary](grading-summary.json).

[source-review.json](source-review.json) records the independent source review.
It found three integration inconsistencies, corrected after the behavior
snapshot: Check must not reset the next Sweep's scope or count as gate-3
evidence; a correct result alone does not prove a historical check; and the
self-check phase applies to retrospective runs. Those corrections were not
behavior-rerun. Their file hashes are distinguished from the tested snapshot
in the manifest. The seven revised classification scenarios were structurally
validated, not executed in this native experiment. Final validation also
normalized the description's required `Use when` prefix and formatted three
original fixture files. The manifest preserves tested hashes/content for every
fixture changed after execution, including the CI follow-up below.

The blind grader detected that the first grading-pack anonymizer had replaced
legitimate synthetic job names inside embedded test code. Before grading, the
pack was regenerated from unchanged executor artifacts and every embedded
Check file was verified against the observer's hashes. Criteria were unchanged;
[grading-provenance.json](grading-provenance.json) records this correction.

## Technical validation

- The full unit suite passed: **962 tests**, using the repository's pinned
  tree-sitter dependencies.
- `validate-evals.py` accepted **65** scenario definitions. This validates their
  structure, not agent behavior on every scenario.
- `pre-commit run --all-files` passed all configured hooks, including skill
  structure/version parity, Markdown, YAML, workflow, Python and shell checks.

Hook installation needed task-local npm 11.21.1 for the upstream `allow-git=root`
fix and Go 1.27.4 because the host's `go` executable was not the Go compiler.
The pre-commit hook configuration was unchanged.

### CI follow-up

The first published revision triggered seven Betterleaks findings for the
manifest's `mask-secrets.py` and `api.json` digests. Each value was independently
recomputed from the recorded file bytes and confirmed to be a public content
hash. The exception is limited to `generic-api-key`, this exact manifest path
and the two complete JSON field/value lines, with an AND condition. The full
history scan remains enabled and passes. A disposable Git-repository control
confirms that an altered digest at the same path and the same digest at an
unrelated path are still detected.

SonarCloud also flagged the three fixture commands' arbitrary argument-to-file
reads. Their mains now read only the bundled `api.json` or `content.json` next
to the fixture; `collect` and `render` are unchanged. All six synthetic commands
were rerun and their records regenerated, and all five fixture invariant tests
passed. These are post-experiment wrapper changes, not new native agent trials.
The manifest retains the exact original input bytes for reconstructing the
reported experiment.

## Evidence still needed for an efficacy claim

Recover the original real session's pre-report input and matching artifacts,
preserve a separate oracle, and compare the original and revised sources in
the target runtime with equal context and tool access. Retain correct-fix and
missing-evidence controls. If prevention is claimed, separately observe that
the check is selected before the decision in ordinary work; an explicit
`/retro check` request cannot establish that.

Do not tune a new fixture until only the revised arm wins or reinterpret these
equal results as a benefit. If representative comparisons continue to show no
gain, narrow or remove the added instructions rather than adding more general
rules. Technical validation and source review alone do not resolve this PR's
efficacy objection.
