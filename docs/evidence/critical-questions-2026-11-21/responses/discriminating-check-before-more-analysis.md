<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Response: discriminating-check-before-more-analysis

Executor report, unchanged except that its headings are one level lower.

## Retro report: Spotlight on "the agent ignored the release checklist again"

### Result

The cause is not known yet, so this report makes no proposal. That includes the proposal to reword the checklist more forcefully. One cheap check of the session transcript decides between the two explanations, and the right fix depends on which one holds. That check comes first, before any more analysis and before any change to the release skill's `SKILL.md`.

### The check to run first

The transcript records every Skill tool call with its name. Search it for a Skill call naming the release skill, made before the release work began.

- **What a hit looks like:** a Skill tool call whose skill name is the release skill, at a turn before the first release step. That supports "loaded, then skipped".
- **What a miss looks like:** no such call anywhere in the transcript. That supports "not loaded".
- **Scope of the search:** the whole transcript, not only the last N turns that a Spotlight normally reads. The release may have started well before this invocation. A search that covers only a slice and finds nothing proves nothing.
- **Mandate:** this is a read of the session's own transcript, which the retro mandate already covers. Nobody needs to approve it.

I could not run it. The task gave me only a prose description and no transcript, and I was told not to run commands. The real run would do it with `detect-mechanical.py --transcript-file <transcript located by content>`, or with a direct search for the Skill call.

### Why rewording is not proposed

**Branch A, the skill was not loaded.** The agent never read the checklist, so stronger wording cannot change anything. The defect is in how the skill gets triggered:
- its `description` triggers, or
- a missing hook or prompt that should load it when release work starts.

The destination would be a `skill-update` to the release skill's description, or a `harness-artefact` that loads or requires the skill. Each needs an eval: a release prompt where the skill must trigger, plus a counterexample where it must not.

**Branch B, the skill was loaded and the checklist was skipped.** This is a written rule broken more than once ("again"). The classification heuristic routes that as C1 (same friction again) and C6 (written rule violated repeatedly) to a `harness-artefact`: a gate, script or checkpoint that makes skipping the checklist detectable or impossible. For C6 it says "never another prose rule — that is what already failed".

Before adding a gate, Axis 1 requires a purpose check:
- Is the checklist still valid and applicable?
- Was a step skipped because it conflicts with something or does not apply?

Rewording would itself be one more prose rule. It is acceptable here only if the transcript shows that the agent misread an ambiguous step. In that case it is a clarification, not "more forceful" wording.

So in neither branch is "reword more forcefully" the indicated measure. I recommend against it until the check says otherwise.

### Prior attempts (Phase 3)

"Again" means there is a history. Before choosing a fix, the history of earlier attempts has to be read:
- earlier sessions with the same symptom (session index, Orca search where available);
- earlier changes to the release skill's checklist or description: `git log` in its source repository, including rejected or reverted PRs and any `Learning-Id`.

If the checklist has already been reworded once and the skip came back, that is C4 (skill update ineffective). It would be direct evidence against rewording again.

Before calling an earlier measure ineffective, two things must be established: that it was available and that it was loaded in the failing session. That is the same question as the transcript check above. For each earlier attempt, record its prediction, what was observed, and the decision that followed.

### Deviation lines

- Phase 1 (mechanical pre-pass): not run. No transcript was available to this executor, and shell commands were not allowed. The decisive Skill-call check is still open.
- Phase 3 (prior attempts): not run. No session index or skill repository history was available, so recurrence and earlier rewording attempts are unknown, not absent.
- Phase 4 (skill discovery): `find-org-skills.py` not run, for the same reason. The owner is presumed to be the release skill, but that is not confirmed by the catalogue.
- Phase 6 (evals): the release skill's `evals/` were not read. An eval stub follows once a branch is confirmed.
- Phase 9 (materialize): nothing written, because no proposal stands yet.

### Phase 11 (self-check)

Nothing found: 0 script errors, because no scripts ran. The deviations are the ones listed above, all caused by the setup. The invocation was unambiguous: a described problem, so a Spotlight.

### Closing question

There is no open proposal, so the `complete` / `noted` / `propose` question is not asked yet. Two things are for the user:

1. Please confirm that the check runs over the whole session transcript before any change to the checklist. This is not a request for permission, which the read already has.
2. When it reports, which branch holds? If you still want rewording after the result, please name the checklist step that was misread, so the change is a clarification of that step rather than general emphasis.

### Contradiction in the instructions

The Spotlight input is defined as "user-described problem + last N turns". This problem's evidence, the Skill call, can sit anywhere earlier in the session. Prior-attempts.md and the Mad/Sad/Glad check of the sources used imply a wider search. The Spotlight definition says nothing about widening the window when the evidence that decides between explanations lies outside it.
