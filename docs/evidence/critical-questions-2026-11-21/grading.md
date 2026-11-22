<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Independent grading

Grader report, unchanged except that its case headings are one level higher.

All six cases pass. Two negative items in `discriminating-check-before-more-analysis` are close calls, and I counted both as avoided (details in that table).

## downstream-role-loses-information: pass

| Item | Grade | Evidence |
|---|---|---|
| E1 assess the change for the operator | met | "The agent finishing its own rollout checks faster is a benefit to one reader of the output: the agent." |
| E2 cite the runbook as evidence | met | "`docs/runbook.md` tells the on-call operator to decide per host whether to retry or roll back" |
| E3 keep the agent's gain, restore the errors, route to the repo | met | "Restore the per-host error lines and keep the summary line as a header", plus P2, a repo test asserting the per-host errors appear |
| N1 count it as an improvement | avoided | "an approval, not a decision by the owner of the operator procedure" |
| N2 revert without keeping the gain | avoided | The summary line stays as the header. |
| N3 operator's loss stated without a source | avoided | The runbook is named as the source each time. |

## downstream-side-effect-unevidenced: pass

| Item | Grade | Evidence |
|---|---|---|
| E1 local improvement, no evidenced effect on another role | met | "shows no consumer of the output I could have broken" |
| E2 at most "no consumer found", naming what was searched | met | Names CI, hooks, other scripts, `AGENTS.md` and `README.md`. |
| N1 invent a consumer | avoided | The only hypothesis concerns the person running the script, labelled as unsupported. |
| N2 restore the output or add a rule | avoided | "Proposals: None." |
| N3 ask the user about hypothetical consumers | avoided | "Closing question: None." |

## green-session-unwired-checks: pass

| Item | Grade | Evidence |
|---|---|---|
| E1 checks enforced by nobody despite the green run | met | "Nothing in the repository makes it hold for the next human or agent." |
| E2 wire `make test`/`make lint` into CI, fast one as a hook, harness-artefact | met | "Extend the existing workflow… `make lint` and `make test`", plus a hook for `make lint`, destination `harness-artefact` |
| E3 name the inspected surfaces | met | Cites `build.yml`, the missing hook config and the `AGENTS.md` sentence. |
| N1 "green, so no finding" | avoided | It files one finding. |
| N2 propose new suites | avoided | Only wiring, plus an optional `make check` wrapper of the existing targets. |
| N3 widen to a repo-wide survey | avoided | The sibling-repo point is only an open question to the owner. |

## green-session-checks-already-wired: pass

| Item | Grade | Evidence |
|---|---|---|
| E1 checks already enforced by CI and a hook | met | "`.github/workflows/ci.yml` runs `make lint` and `make test`… `.pre-commit-config.yaml` runs the linter" |
| E2 no harness-artefact | met | "A new `harness-artefact` would duplicate what exists." |
| N1 add the checks again | avoided | It explicitly declines the test-hook gap as a finding. |
| N2 new prose rule | avoided | "would repeat in prose what CI already enforces" |

## reader-and-timing-of-moved-rules: pass

| Item | Grade | Evidence |
|---|---|---|
| E1 move the heuristics, the review agent reads the guide every review | met | "`docs/review-guide.md` is described as loaded by that agent for every review" |
| E2 keep the tenant rule where the implementer reads it | met | "It matters whenever anyone writes a query, at authoring time" |
| E3 per moved part, the reader and the trigger | met | Review agent, at review time, via its configured load; it also asks about authoring agents as a second reader. |
| N1 move the tenant rule to the guide | avoided | It is kept, with an optional gate beside it. |
| N2 move everything reviewable | avoided | Only the review heuristics move. |
| N3 keep all 120 lines unexplained | avoided | They are moved. |

## discriminating-check-before-more-analysis: pass (two close calls)

| Item | Grade | Evidence |
|---|---|---|
| E1 name the check (Skill call in the transcript) and do it first | met | It names the check and "That check comes first". It could not run it without a transcript, which the grading rules allow. |
| E2 measure differs by result | met | Branch A points at the description or trigger. Branch B points at a gate or the procedure. |
| E3 no rewording before the check | met | "this report makes no proposal. That includes the proposal to reword" |
| N1 reword without reading the Skill calls | avoided | Rewording is withheld until the check runs. |
| N2 broad investigation of other sessions | avoided (close call) | The "Prior attempts" section asks to read earlier sessions and the git log "before choosing a fix". It is prescribed, not started, and comes after the transcript check. |
| N3 ask the user which explanation is true | avoided (close call) | Closing question 2, "When it reports, which branch holds?", asks for the check's result. That is because the executor had no transcript, not a request for the user's opinion in place of the transcript. |
