<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Response: reader-and-timing-of-moved-rules

Executor report, unchanged except that its headings are one level lower.

## Retro report: `/retro promote` for slimming `AGENTS.md`

### Answer first

Move the roughly 120 lines of review heuristics into `docs/review-guide.md`. Keep the `tenant_id` rule in `AGENTS.md`.

The deciding question for each rule is who reads it, and at what moment.

- **Review heuristics.** Their stated reader is the review agent, at review time. `docs/review-guide.md` is described as loaded by that agent for every review. So it reaches the same reader at the moment the content matters.
- **The `tenant_id` rule.** It matters whenever anyone writes a query, at authoring time, whether or not a review runs. In the review guide it would only be caught after the query exists, and only by the review agent. Any agent writing code without a review would never see it.

Nothing was materialized. I had no shell or write access, and everything below rests on the prose description of the session. Every claim about repository contents is marked as unverified.

### Contradictions in the instructions

1. **This mode does not scan `AGENTS.md`.** `promote-mode.md` says `<project>/AGENTS.md` is "excluded by construction (… a correct *destination* — re-promoting it by default loops)". `scan-memory-inventory.py` therefore never emits a finding for it. The user's request (slim `AGENTS.md`) has no prescribed mode. I applied promote's rules for the other always-loaded file ("Draining the global rules file": always-on behaviour stays, the two-direction test, fence-aware drain) by analogy. That is an interpretation, not a prescribed path.
2. **"Upward" does not fit this move.** Promote "re-homes upward by reach" (skill-update › project-rule › personal-rule). Moving text from `AGENTS.md` to `docs/review-guide.md` goes sideways and narrows the audience to one reader. That narrowing is what the slimming is for. The escalation order does not decide this case.
3. **The two-direction test names the wrong kind of destination.** It asks whether "the owning skill reliably triggers". Here the destination is a repository doc that a configured agent loads, not a skill. I read it as: the destination is reliably loaded by the reader who needs the content, when they need it.

### Findings and proposals

#### 1. Move the review heuristics to `docs/review-guide.md` (`project-rule`; prune plus relocate inside the same repo)

**Evidence.** These are the facts the task description gives:
- `AGENTS.md` is always loaded and has 300 lines.
- About 120 of them are review heuristics (naming, comment style, readability) that the review agent applies to diffs.
- The review agent is configured to load `docs/review-guide.md` for every review.

**Why.** Holding about 40% of the file in every agent's context costs context on every turn. The intended reader gets the content anyway through its own entry point.

**Steps.** Each step must be verified before the next one:
1. **Check what the configuration does.** Open the review agent's actual configuration, not a description of it, and confirm it loads `docs/review-guide.md` on every review, including the review path CI uses. Not verified.
2. **Check for duplicates.** Read `docs/review-guide.md` and compare mechanisms rule by rule. A heuristic it already covers is removed from `AGENTS.md` and cited with its covering line. A partly covered one moves only its delta. A heuristic with no counterpart is appended. If generic readability rules duplicate an installed code-review skill, they are a pruning candidate. Skill discovery (`find-org-skills.py`) was not run, so that is unknown.
3. **Check for other readers.** Do authoring agents apply the naming and comment-style rules when they write code? If so, moving them to review time turns prevention into rework. In that case keep a one-line pointer in `AGENTS.md`, for example "Naming and comment conventions: `docs/review-guide.md`". That pointer is the link from the reader's starting point.
4. **Order the change: write, verify, then drain.** First add the content to `review-guide.md` by PR. Only after it is merged, and the review agent's next run is shown to load it, remove the lines from `AGENTS.md`. Remove them fence-aware, because a `#` comment inside a code fence matches a heading boundary. Then check that the code fences are still balanced and that the section count dropped by exactly the number removed. Both edits can go in one PR, because the agent reads the merged state. The verification after the merge still applies.
5. **Consider a gate (axis 1).** Purely mechanical naming rules may be expressible as a linter rule the repository already runs. If so, propose it as a calibrated `harness-artefact`: firing count measured on the codebase, with cases that must not fire. Do not force judgment rules such as readability into a regex.

#### 2. Keep the `tenant_id` rule in `AGENTS.md`, and propose a gate beside it (`harness-artefact`, prose stays)

**Evidence.** The task describes it as "every database query must filter by `tenant_id`". It is a security and data-isolation invariant that applies whenever a query is written.

**Why it stays.** Promote's rule 1 applies by analogy: "Always-on behavior never leaves the file … at most they *pair* with an enforcement gate while the prose stays." It fails the second half of the two-direction test. Losing it from always-loaded context is not safe, because the only destination on offer reaches one reader after the code is already written.

**Proposal.** A mechanical check, if the stack allows one: a query-builder scope, a static-analysis rule, or a test that fails on an unscoped query. It would go in this repository's CI and the matching pre-commit hook, to keep CI and hooks in step. It needs calibration against the existing queries before it is proposed in earnest. The prose rule stays either way. I don't know the stack, so this is a hypothesis about feasibility.

#### 3. Self-check finding against retro-skill (`skill-update`, 1 of at most 2)

**Evidence.** Promote mode gives binding reader and timing rules only for `~/.claude/CLAUDE.md`. It excludes `AGENTS.md` and phrases its safety test only in terms of a skill triggering. The request "slim the always-loaded `AGENTS.md`" fell into that gap (see the contradictions above).

**Change.** Add a short section to `references/promote-mode.md`, or to `classification-heuristic.md` § Instruction pruning, called "Slimming an always-loaded file on request". It would say:
- For each rule to move, name its reader and the moment it is needed.
- Move a rule only where the destination is loaded by that reader at that moment. That can be a skill that triggers, or a doc an agent is configured to load, with the loading verified in the configuration.
- Rules needed at authoring time, and invariants (security, data isolation), stay and at most get a gate beside them.
- Keep a pointer for any secondary reader.

Also state in `SKILL.md` § Modes that promote does not scan `AGENTS.md`, and which mode covers such a request instead. An eval stub would use this scenario plus a control case where every candidate rule is review-only.

### Deviations from the prescribed phases

- **Phase 1:** `scan-memory-inventory.py` was not run (no shell). It would not emit `AGENTS.md` anyway, so the inventory came from the task prose.
- **Phases 2–3:** replaced by the promote front-end. No attempt history was searched.
- **Phase 4:** `find-org-skills.py` and the harness inspection were not run, so it is unknown whether a skill owns these review heuristics.
- **Phase 6:** no skill's `evals/` were read.
- **Phases 8–9:** nothing was materialized. The authorization assessment is below.
- **Phase 11:** `detect-mechanical.py --since-command retro` was not run. The self-check is limited to finding 3.

### Authorization

"Slim `AGENTS.md`" covers editing `AGENTS.md`. Relocating content into `docs/review-guide.md` stays within the same repository and audience. I read it as covered when done through the repository's normal PR flow. The gate in finding 2 and the retro-skill change in finding 3 go beyond the request and need a decision.

### Questions for the user

1. Do authoring agents also rely on the naming and comment-style rules when writing code, or only the review agent? This decides whether `AGENTS.md` keeps a pointer.
2. Should a mechanical `tenant_id` gate be built? It depends on the stack, and it would be calibrated against the existing queries first.

### Closing question

Answer in one word:
- `complete`: carry out findings 1–3 as described.
- `noted`: record them and change nothing.
- `propose`: prepare them as drafts for review.
