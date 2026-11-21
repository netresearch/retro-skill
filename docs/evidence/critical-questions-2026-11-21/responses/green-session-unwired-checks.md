<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Response: green-session-unwired-checks

Executor report, unchanged except that its headings are one level lower.

## Retro report: Sweep (`/retro`) over the request-validation session

I found one finding and propose one change: wire the hand-run `make test` / `make lint` gate into the repository. Nothing in the session failed. Nothing came from user corrections or review feedback. The finding comes from the project-harness inspection, so it is a latent gap with no observed harm, and its severity is graded to match. I did not create a B22 (missed situational check) or C6 (written rule violated) finding, and I did not invent a rule to fill a quota.

### Mad / Sad / Glad

- **Mad (avoidable friction):** none. There were no retries, corrections, tool errors or rework.
- **Sad (unmet benefit):** the repository's pre-push gate exists only as a sentence in `AGENTS.md`. It held this time because this agent read that sentence and followed it. Nothing in the repository makes it hold for the next human or agent. This is an observation about the repository plus a hypothesis about future sessions, not an observed failure.
- **Glad (what worked):** the agent ran both documented targets before finishing, both passed, and the user accepted the change. The prerequisite was reachable from the documented starting point (`AGENTS.md`), so there is no B13 (context re-discovery) or B21 (dug-out knowledge) finding.

### Finding 1: a documented gate that exists only as a hand-run list

**Evidence (from the task description, the only source I have):**
- The session changed request validation in `src/api/`.
- `AGENTS.md` says "run make test and make lint before pushing".
- The repository has no hook configuration.
- The only CI workflow, `.github/workflows/build.yml`, builds the container image and runs neither target.
- The agent ran both targets by hand.

**Why this qualifies:** `project-harness-inspection.md` asks of every session: "Did the session run a documented sequence by hand? A gate described as a list is a gate whose last two steps get skipped." This session did exactly that. The motivating case in that reference is "a documented … pre-push gate that existed only as a list to execute by hand". On Axis 1, the rule still serves a valid quality goal: validation code is tested and linted before it lands. So the rule should be kept and enforced, not removed or simplified. Tier 1 (mechanical gate) is available, because both checks are exit codes, and the heuristic says to take that tier "whenever it is available at all".

**Classification:**
- Signal: a harness-inspection finding (closest catalog class: B17 proactive improvement). It is not B22, because the warning sign was answered and the check ran. It is not C6, because the rule was not violated.
- Severity: `nice-to-have`. The consequence is untested, because nothing failed.

**Destination:** `harness-artefact` in this service repository.
1. **Extend the existing workflow.** Add a job or step to `.github/workflows/build.yml` that runs `make lint` and `make test`. Verify-before-bootstrap applies: extend this file, do not replace it, and do not add a templated second workflow. CI is the only instrument here that also binds people who never read `AGENTS.md`.
2. **CI/hook parity.** `patch-workflow.md` and `destination-taxonomy.md` require every fast, deterministic CI check to run as a local hook too, in the same PR. `make lint` very likely meets that definition. Whether `make test` does is unknown, because its runtime and service dependencies are not in the evidence. The repository has no hook manager, so the hook would be a new config rather than an extension. The hook manager the team uses cannot be read from the evidence.
3. **Optional simplification (tools axis).** A single `make check` target running both would give CI, the hook and `AGENTS.md` one entry point instead of a two-item list. Add it only if the maintainers want it.

**Propagation half:** I am not proposing one yet. A Gate + propagation pair needs an owning skill that carries the recipe for installing the gate elsewhere, and Phase 4 did not run, so no owner is discovered. I will not assume one.

**`AGENTS.md`:** no change proposed. Once CI enforces the rule, the existing sentence stays valid as local guidance. Rewording it would only restate the gate.

**Calibration (as the heuristic requires for a tier-1 gate):** on this session's own run, the gate fires 0 times. That is the required "must not fire" control: a green change stays green. There is no incident for the gate to catch, so the second number, "the friction is among the hits", cannot be produced. The proposal therefore rests on the harness inspection, not on a measured incident. This is stated so the owner can weigh it.

**Authority:** the change touches the service repository's CI and adds a local hook, so it needs the repository owner's approval. Nothing in the task shows an existing mandate for it, so it is left open for the closing question.

**Open questions for the owner (in the report instead of asked):**
- Is `make test` fast and self-contained enough to run as a hook, or should only `make lint` run locally?
- Which hook manager does the team use?
- Does the same gap exist in sibling service repositories? That would make it a Gate + propagation pair.

### Phase deviations

- Phase 1 (mechanical pre-pass): `detect-mechanical.py` did not run. No transcript is available and shell commands are not permitted. All evidence comes from the prose description, and the coverage of mechanical signals is unknown, not clean.
- Phase 1b (review findings): `collect-review-findings.py` did not run, for the same reason. PR, review and tracker feedback is unknown. The description mentions only the user's acceptance.
- Phase 3 (prior attempts): skipped. Nothing points to a recurring problem or an earlier attempt, so history is not needed for this decision. Whether the gap was raised before is unknown.
- Phase 4 (skill discovery): `find-org-skills.py` did not run, because shell commands are not permitted. No owning skill was discovered, so no `skill-update` half is proposed.
- Phase 4 (harness inspection): ran, from the description only.
- Phase 6 (evals): not run. No skill was matched whose `evals/` I could read.
- Phase 9 (materialize): nothing written, because writes are not permitted and the decision is open.
- Phase 11 (self-check): skipped. No transcript of this session is available for `--since-command retro`.

### Contradictions and tensions in the instructions

1. **Calibration assumes an incident.** The tier-1 calibration rule asks "whether the friction that prompted it is among the hits". The harness inspection, however, explicitly produces gate proposals for sessions without friction, like this one. For such a finding the rule cannot be satisfied as written. Only the "must not fire" half applies. The text should say how to calibrate a gate for a latent gap.
2. **Pre-commit versus pre-push.** The parity rule names a "pre-commit hook". The repository's own rule says "before pushing". For a slow test suite, pre-push is the better fit. The parity text does not say whether pre-push satisfies it.
3. **Missing source.** The B22 warning-sign list (`friction-catalog.md` § Missed situational check) is cited but not included in the supplied context. My conclusion that this is not B22 rests on the routing table and the harness-inspection text.

### Closing question

One proposal is open: Finding 1. It adds `make lint` / `make test` to `.github/workflows/build.yml`, a hook for the fast checks, and optionally a `make check` target, all in the service repository. How far should it be carried out? Answer with one word:

- `complete`: create the PR, review and fix it until a round finds nothing new, and merge it once every gate is green. This applies if the team owns the repository; otherwise the PR is released from draft.
- `noted`: change nothing.
- `propose`: create the PR, review and fix it the same way, and leave it as a draft for you.
