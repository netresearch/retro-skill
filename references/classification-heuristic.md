# Classification Heuristic

Maps friction signals (from `friction-catalog.md`) to one of the six destinations (from `destination-taxonomy.md`).

## Primary mapping

| Friction signal | Primary destination | Alternate (LLM decides from context) |
|---|---|---|
| **A1** tool error | `skill-update` (tool-owner skill) | `user-memory` (if user-specific config issue) |
| **A2** tool retry cluster | `skill-update` (tool-owner) | `user-memory` |
| **A3** tool output verbosity | `skill-update` (tool-owner: file-search, data-tools) | `user-memory` |
| **A4** too many tool calls | `skill-update` (workflow guidance) | `user-memory` |
| **A5** sequential vs parallel | `skill-update` (workflow skill) | — |
| **A6** user correction phrase | `user-memory` (style) OR `project-rule` (convention) | LLM reads correction content to decide |
| **A7** prompt repetition | `skill-update` (description didn't match) | `agent-rules-skill` PR (AGENTS.md unclear) |
| **A8** prompt sequence repetition | Snippet/Custom Command OR `skill-update` (workflow) | `new-skill` if pattern is rich |
| **A9** tool sequence repetition | `skill-update` (composition guidance) | `new-skill` |
| **A10** skill in reminder vs invoke | `skill-update` (description or trigger words) | `harness-artefact` (delegation map) |
| **A11** wrong tool choice | `skill-update` (tool-owner skill) | `user-memory` |
| **A12** re-read same file | `skill-update` (workflow / context retention) | — |
| **A13** skipped verification | `harness-artefact` (PR template) OR `project-rule` (CLAUDE.md) | `skill-update` (skill should require verification step) |
| **A14** worked on main/master | `harness-artefact` (branch protection / pre-commit) | `user-memory` if user-pattern |
| **A15** bot attribution in commit | `user-memory` (rule violated) → `skill-update` (skill should know rule) | — |
| **A16** outdated tool warning | `skill-update` (tool-owner, version bump) | `user-memory` (user's setup outdated) |
| **A17** upstream failure | `harness-artefact` (pre-commit hook) OR `skill-update` (verification step) OR `checkpoint` (mechanical check) OR `project-rule` | LLM picks based on what would have caught it |
| **A18** permission re-approval | `user-memory` + invoke `update-config` skill | — |
| **B1** output quality mismatch | `user-memory` (preference) OR `skill-update` (output style) | — |
| **B2** wrong skill choice | `skill-update` (description of unused skill) | — |
| **B3** skill capability gap | `skill-update` (add guidance) | `new-skill` if gap is large |
| **B4** skill description mismatch | `skill-update` (description) | — |
| **B5** hallucination / fact check | `skill-update` (context7 / verification) | `user-memory` |
| **B6** convention violation | `project-rule` | `skill-update` (project-aware skill) |
| **B7** missing skill | `new-skill` | — |
| **B8** wrong-destination materialization | `skill-update` (retro-skill itself, or whoever wrote) | — |
| **B9** repeated mistake in session | `skill-update` (rule was unclear) | `user-memory` |
| **B10** approval bypassed | `skill-update` (skill should require confirmation) | `harness-artefact` (template) |
| **B11** plan/spec skipped | `skill-update` (spec-driven-development trigger) | `project-rule` |
| **B12** assumption without asking | `skill-update` (spec-driven-development trigger description) | `user-memory` |
| **B13** context re-discovery | `project-rule` (improve AGENTS.md) | `skill-update` (agent-rules-skill) |
| **B14** doc drift | `skill-update` (context7-skill trigger) | `project-rule` (pin lib version) |
| **C1** same friction again | `skill-update` (existing memory not enough) | `harness-artefact` (enforcement) |
| **C2** cross-project pattern | `skill-update` (promote from feedback files) | `new-skill` |
| **C3** memory drift | `skill-update` (skill should reference memory) | — |
| **C4** skill update ineffective | `skill-update` (previous fix was wrong) | — |

## Disambiguation prompts

When two destinations are plausible, ask the user with concrete framing:

```
This friction could go to either:
  (a) <project>/docs/feedback/<slug>.md  — project convention
  (b) ~/.claude/projects/<slug>/memory/feedback_<slug>.md  — your personal preference

The friction was: "<one-line summary>"
Which fits better?
```

## Severity inference

Severity is set during classification, not during detection:

- `critical` — Recurring (C-layer match) OR caused upstream failure (A17) OR user-visible bug
- `important` — User correction phrase present (A6) OR known rule violated (A15)
- `nice-to-have` — Efficiency / style / convention (most other cases)

Use severity to rank proposals in the output. Higher severity first.

## See also

- `references/friction-catalog.md` — Signal definitions
- `references/destination-taxonomy.md` — Destination definitions
- `references/workflow.md` — Where this fits in the overall flow
