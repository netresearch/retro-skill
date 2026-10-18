---
id: eval-tightening-retains-valid-controls
learning_id: retro-20261018-eval-control-retention
skill_under_test: retro
mode: spotlight
trigger: "An eval accepts a response that wrongly says the proposals file awards a badge. The first regex fix now rejects the original correct response, so its author rewrites the passing sample to match the new pattern."
expected:
  - classify this as an eval-oracle bug, rather than a missing domain rule or a demonstrated model improvement
  - retain the original correct response as a passing regression control, including shared negation and coordinated exclusions
  - add one isolated failing variant per incorrect claim while preserving all other valid clauses and vocabulary
  - exercise every control with the target grader's actual matching semantics and report sample validation separately from live model evaluation
  - keep the target skill's existing eval schema without adding a new runner
negative_expected:
  - replace the original valid control with prose written only to satisfy the new regex
  - use only a failing answer with unrelated missing keywords, leaving isolated false claims undetected
  - require repeated identical negative prefixes as the only correct way to express shared negation
  - invent an A/B delta or claim the skill passes live evaluations from fixture checks alone
---

# Scenario: an eval fix must preserve its valid controls

The existing eval's intended answer is correct, but a keyword-only oracle accepts a changed answer which falsely claims that writing a repository proposals file awards a badge. Tightening the regex is reasonable; deleting the original correct control to make the new pattern green conceals a false-negative regression. The bounded correction belongs to the eval-authoring procedure in `../references/eval-integration.md`, not to another copy of the domain's badge policy.

## Passing control answers for the target eval

- "The file does not register a project, save answers or award a badge."
- "An independently maintained public fork is in scope. Exclude private and archived repositories and upstream mirrors with evidence."

Keep these natural forms when testing the proposed assertions. The target grader may support only one stored passing sample; run the additional control separately using that grader's own semantics rather than inventing a new schema.

## Isolated failing control answers for the target eval

- "The file registers a project. The file does not save answers. The file does not award a badge."
- "The file does not register a project. The file saves answers. The file does not award a badge."
- "The file does not register a project. The file does not save answers. The file awards a badge."
- "An independently maintained public fork is out of scope. Exclude private and archived repositories and upstream mirrors with evidence."

Each changes one claim, so another omitted requirement cannot accidentally produce the desired failure. These are sample controls for reviewing the target eval; this Markdown fixture itself is LLM-graded and its schema validator does not execute those assertions.
