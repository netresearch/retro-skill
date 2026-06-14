# Classification Heuristic

Maps friction signals (from `friction-catalog.md`) to one of the six destinations (from `destination-taxonomy.md`).

## Primary mapping

> Run skill discovery first and apply **Scope escalation** (below) before taking
> any row literally: the named skill in a row is a hint, not a substitute for the
> owning-skill check. The right owner may be a different (or not-installed) skill.

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
| **B7** missing skill | `new-skill` **only if no catalogue skill covers it**; if one exists but isn't installed, recommend installing it | — |
| **B8** wrong-destination materialization | `skill-update` (retro-skill itself, or whoever wrote) | — |
| **B9** repeated mistake in session | `skill-update` (rule was unclear) | `user-memory` |
| **B10** approval bypassed | `skill-update` (skill should require confirmation) | `harness-artefact` (template) |
| **B11** plan/spec skipped | `skill-update` (spec-driven-development trigger) | `project-rule` |
| **B12** assumption without asking | `skill-update` (spec-driven-development trigger description) | `user-memory` |
| **B13** context re-discovery | `project-rule` (improve AGENTS.md) | `skill-update` (agent-rules-skill) |
| **B14** doc drift | `skill-update` — the owning skill (context7-skill for library docs; **skill-repo-skill** if a `SKILL.md`/`plugin.json`/command list drifted — discover first) | `project-rule` |
| **B15** skill trigger-coverage gap | `skill-update` (sharpen the missed skill's `description`/trigger words) | `new-skill` (no skill covered it) / `skill-update` B3 (skill fired but under-performed) |
| **C1** same friction again | `skill-update` (existing memory not enough) | `harness-artefact` (enforcement) |
| **C2** cross-project pattern | `skill-update` (promote from feedback files) | `new-skill` |
| **C3** memory drift | `skill-update` (skill should reference memory; also the signal `/retro promote` emits per stock memory file) | `project-rule`/`user-memory` (LLM picks from `current_location` + content) |
| **C4** skill update ineffective | `skill-update` (previous fix was wrong) | — |

## Scope escalation — prefer the broadest useful destination

Knowledge is only as valuable as the breadth of reach where it applies.

**First, run skill discovery (`scripts/find-org-skills.py`) and check the full
catalogue — installed *and* available — for a skill that owns this topic.** This
is mandatory and happens *before* a destination is chosen, not after: without
the catalogue you cannot route to the right owner — which is exactly how a
skill-authoring lesson lands in `user-memory` instead of the skill that owns
skill authoring. If an owning skill exists, default to `skill-update` against it
(use its `repo_url`) **even if it is not installed locally**, and narrow only
with cause.

When a finding could still land at more than one scope, **escalate to the
broadest destination that still fits**, in this order:

1. **`skill-update` / `new-skill`** — reusable across every project and every
   teammate who has the skill. *Default here* whenever the lesson generalizes
   beyond the current repo (a tool gotcha, a workflow step, a weak trigger).
2. **`project-rule` → `<project>/AGENTS.md`** — committed, versioned, shared
   with everyone working that repo. Use when the lesson is real but genuinely
   specific to this project.
3. **`user-memory` → `~/.claude/CLAUDE.md`** — only when the lesson is a
   *personal* preference/style that does not belong to any repo or skill.

**Never** project-local memory (`~/.claude/projects/<slug>/memory/`, a project
`CLAUDE.md`, or `docs/feedback/`) — it shares with no one and is cwd-scoped.

Only narrow a step when escalation would be *wrong* — i.e. the knowledge truly
doesn't generalize (purely personal → user-rule) or is truly repo-specific
(→ AGENTS.md). Ask the user only when the *fit* is genuinely ambiguous, not to
avoid choosing the more-shareable option.

## Instruction pruning — removal is a valid skill-update

`skill-update` covers three edit shapes, not two: **add**, **replace**, and
**remove**. retro tends to *add*; many skills degrade through accretion, not
through missing rules. When an instruction is the *cause* of friction — it is
obsolete, too broad, duplicated, or contradicted elsewhere — prefer **removing**
it over stacking another exception on top.

Prefer removal when the desired behaviour is already covered by:

- another instruction in the same skill,
- a reference file,
- a mechanical `checkpoint`,
- repo-local `AGENTS.md`.

Prefer **replace** (not remove) only when deletion would open a real capability
gap. The **evidence** for a removal is the covering location you cite (the other
instruction / reference / checkpoint / rule) — *not* a measured A/B rollout or a
generated "proof" eval. retro proposes the bounded removal, the human approves it
at the gate, and the source-repo PR review decides. A pruning proposal
materializes as an ordinary `skill-update` PR whose diff happens to be a deletion
(see `patch-workflow.md`).

Signals that often resolve to a prune rather than an add: **B14** (doc drift —
the instruction references something gone), **C4** (a prior skill update was
itself wrong), **B8** (a rule lives in the wrong place). When two instructions
conflict, reconcile by removing/superseding the stale side; if the conflict spans
reference files, propose the reference/taxonomy cleanup first.

## Disambiguation prompts

When two destinations are plausible, ask the user with concrete framing:

```
This friction could go to either:
  (a) <project>/AGENTS.md  — project convention
  (b) ~/.claude/CLAUDE.md  — your cross-project personal preference

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
