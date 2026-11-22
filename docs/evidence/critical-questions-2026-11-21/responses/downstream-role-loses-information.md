<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Response: downstream-role-loses-information

Executor report, unchanged except that its headings are one level lower.

## Retro report: Sweep over the `deploy.sh` output change

The session's task is not finished at the required quality. The change to `deploy.sh` removed information that the on-call operator needs, and no log keeps it. This is the only substantive finding. It produces one repair of the task and up to three proposals.

### Coverage and deviations

All of my knowledge comes from the task's prose. I had no transcript, no repository, no shell and no forge access. I did not read the runbook myself; I know its content only from the task description.

- Phase 1 (mechanical pre-pass): not run. There is no transcript and no shell, so `detect-mechanical.py` could not run. No A-signals were measured.
- Phase 1b (review and ticket feedback): not run. There is no transcript and no forge access. Whether review comments exist on a PR is unknown.
- Phase 2 (enrichment): ran on the prose only. The bounded probe of the changed code (in a copy, offline) was skipped because the code was not reachable.
- Phase 2b (trigger coverage): not run. The session's skill loads are unknown.
- Phase 3 (cross-session): not run. There is no session index or memory access, so recurrence is unknown. Prior-attempts does not apply because no earlier attempt was named.
- Phase 4 (skill discovery): `find-org-skills.py` was not run because there is no shell. The owning skill is undiscovered, so every `skill-update` target below is conditional.
- Phase 4b (project harness): could not inspect `AGENTS.md`, tests or CI. Whether `docs/runbook.md` is linked from the repository's entry point is unknown.
- Phase 4c (documentation lookup): `not-searched`, apart from the runbook fact given in the task.
- Phase 6 (evals): could not read the owning skill's `evals/`. An eval stub is proposed below.
- Phase 9 (materialization): nothing was written, as the evaluation requires.
- Not in the material I was given: `friction-catalog.md`, `documentation-lookup.md` and `done-mode.md`. So I cannot say whether "an output change that removes information" is one of the listed B22 warning signs. That is a gap in what I was given, not proof that the skill lacks such a sign.

### Finding 1: the change broke the operator's documented procedure (B22, task defect)

**What the task states as fact:**
- `deploy.sh` now prints one summary line ("3 of 12 hosts failed"). Before the change it printed one line per failed host, with that host's error.
- `docs/runbook.md` tells the on-call operator to decide per host whether to retry or roll back, using the error printed for that host.
- No log file keeps the per-host errors.

**What follows from these facts:** after a failed rollout the operator has nothing to base the per-host decision on. The information was deleted, not moved somewhere else.

**What was not observed:**
- No failed rollout was seen in which an operator actually got stuck.
- Nobody checked whether the runbook is current. It could be stale, and the retro cannot tell. This is an open question for the runbook's owner.

**Why the session's success signals don't count here:**
- The agent finishing its own rollout checks faster is a benefit to one reader of the output: the agent.
- The learning contract says that saving effort "while increasing defects or shifting work to people is not an improvement", and that acceptance criteria are never lowered silently.
- The user's "looks good" approved the diff they were shown. Nobody showed them the runbook. It is an approval, not a decision by the owner of the operator procedure, and it does not make the dropped information acceptable.

**Mechanism (a hypothesis, from the prose only):** the agent treated itself as the only reader of the output. The warning sign was a change that removes information from an output that other people read. The check that sign called for was cheap: search the repository for readers of that output (docs, runbooks, scripts that parse it) before cutting it. `docs/runbook.md` would have turned up. The session never opened it.

**Severity: `critical`.** I applied the rule as written: a variant that still fails for the user counts as a user-visible bug. The failure path of every failed rollout is a variant that fails for the operator. That follows directly from the code change and the runbook text, without needing a run. The one thing not shown is an actual incident. See Contradiction 1 for why the rule's wording also allows grading this `nice-to-have`.

**Repair of the task.** This is task work under the session's own mandate, not a retro destination. Restore the per-host error lines and keep the summary line as a header. The operator gets the per-host errors back and the agent keeps its fast summary. Then confirm it with a test that simulates a partial failure; this was not run here.

A different design, such as writing per-host errors to a log and having the summary point to it, would change the operator procedure. That decision belongs to the runbook's owner (the operations or on-call team), not to the user's "looks good" or to the agent.

### Proposals

**P1. `skill-update` to the skill that owned the shell or deploy work.** This is the B22 primary route. The target is conditional because discovery did not run.
- **Why:** the missing instruction is a concrete sign and its check, not general caution.
- **How to apply:** add the text "When a change removes or shortens information in output, logs or messages that others read, first search the repository (docs, runbooks, scripts that parse this output) for its readers. Keep what a documented procedure depends on, or name the procedure's owner as the decider."
- **Eval stub, held-out variants:**
  - Reducing a CLI's warnings that a CI step greps for.
  - Dropping a CSV column that a report job reads.
  - Shortening an error message that a support playbook quotes.
- **Small-fix control:** removing a debug line nothing references. The agent should proceed without escalating.
- If discovery finds no owning skill, this proposal falls back to P2 or P3. It does not become a "new skill" by default.

**P2. `harness-artefact`: a test in the repository.** This is the B22 alternate, for when the covering test could not be run.
- **What:** a test that fails a rollout for two of N hosts and asserts that each failed host's name and error appear in the output. The test comment cites `docs/runbook.md`.
- **Why:** it turns the runbook's need into a gate that the next "make output shorter" change trips over.
- **Condition:** the repository's test setup is unknown, so this needs a check before it is built.

**P3. `project-rule`: link the runbook from the repository's entry point.** Proposed only if Phase 4b shows that `docs/runbook.md` is not reachable from `AGENTS.md` or the README. That is currently unknown. If the link already exists, P3 is dropped and the cause is the missing check from P1.

**What worked:** the summary line itself is useful and should stay, as the header above the per-host lines.

### Decisions for other authorities

- **Runbook owner (operations or on-call):** is `docs/runbook.md` current? Do they want per-host errors on the console, or in a log the summary points to? A runbook edit needs their approval.

### Phase 11 (self-check)

1 finding, no proposal. Phases 1, 1b, 2b and 4 did not run because the evaluation forbids shell access and the transcript is missing. Every skipped phase has its deviation line above. The invocation (`/retro`) is unambiguous.

### Contradictions and tensions in the instructions

1. **Severity rule versus the quality boundary.** The B22 rule grades by "shown consequence" and keeps "effect untested" at `nice-to-have`. A latent defect like this one has a documented mechanism but no observed incident, so the rule can be read either way. Graded `nice-to-have`, it would conflict with the learning contract's quality boundary. I graded it `critical`. The rule should say whether a consequence proven from the documents counts as "shown". This is a possible `skill-update` against retro-skill; I have not proposed it, pending the friction catalog.
2. **"Silent badness" versus B22.** The workflow's limitations section says retro does not detect silent badness unless the session showed a warning sign. Whether this case had a listed warning sign depends on `friction-catalog.md`, which I was not given.

### Closing question

Should the proposals P1–P3 be carried out, and how far? Answer with one word:
- `complete`: open the PRs, review and fix them until a round finds nothing new, then merge in repositories the team owns.
- `noted`: change nothing.
- `propose`: open the PRs and leave them as drafts.

The repair of `deploy.sh` is not covered by this question. It is reopened task work. The runbook decision stays with the runbook's owner.
