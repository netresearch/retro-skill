# Destination Taxonomy

Every friction finding maps to exactly one of six destinations. Each destination owns a specific materialization format defined by a specialist skill.

## The Six

| # | Destination | When | Owner Skill (materialization format) | Storage Location |
|---|---|---|---|---|
| 1 | `user-memory` | Personal preference, style, recurring quirk across projects | retro-skill (writes `feedback_<slug>.md` directly) | `~/.claude/projects/<slug>/memory/feedback_<slug>.md` |
| 2 | `project-rule` | Project-specific convention or command | `agent-rules-skill` (defines `feedback-memory-schema`) | `<project>/docs/feedback/<slug>.md` + AGENTS.md index entry |
| 3 | `skill-update` | Existing skill missing instruction or has wrong guidance | `skill-repo-skill` (defines `materialization-contract`) | PR to skill **source repo** (never cache) |
| 4 | `new-skill` | Friction is skill-shaped gap, no existing skill matches | `skill-repo-skill` (defines scaffolding) | New repo via scaffolding workflow |
| 5 | `checkpoint` | Mechanically detectable rule, regex/script possible | `automated-assessment-skill` (defines YAML schema) | Entry in target skill's `checkpoints.yaml` |
| 6 | `harness-artefact` | Repo missing hook / CI / template | `agent-harness-skill` (defines artefact templates) | Hook / CI workflow / PR template in target repo |

## Format details

### 1. `user-memory` — `feedback_<slug>.md`

Canonical schema (matches existing 8 files in `~/.claude/projects/-home-sme-p/memory/`):

```markdown
---
name: <kebab-case-slug>
description: <one-line summary used for relevance scoring>
type: feedback
originSessionId: <session-id-from-jsonl-filename>
---
**Why:** <1-2 paragraphs explaining the friction and root cause>

**How to apply:** <1-2 paragraphs describing how the assistant should behave next time>
```

### 2. `project-rule` — `<project>/docs/feedback/<slug>.md`

Same schema as user-memory but committed to the project repo. Plus an entry in the project's AGENTS.md index linking to it. See `agent-rules-skill/references/feedback-memory-schema.md`.

### 3. `skill-update` — PR to source repo

Branch: `feat/retro-<slug>`
Commit: Conventional Commits format, no bot attribution
PR body: references the friction, describes the change, includes "Came from /retro: yes"

See `references/patch-workflow.md` for full workflow including worktree-vs-clone selection, signing, and per-private-repo confirmation.

### 4. `new-skill` — Scaffolding

Invokes `skill-repo-skill` scaffolding with:
- Proposed skill name (kebab-case)
- Initial trigger description
- Initial reference doc covering the friction pattern
- Initial eval covering the friction (TDD)

User confirms before scaffolding. Marketplace listing is a separate manual step (out of scope).

### 5. `checkpoint` — YAML entry

Added to target skill's `checkpoints.yaml`. See `automated-assessment-skill/references/learning-derived-checkpoints.md` for the schema.

Example:
```yaml
- id: <skill-prefix>-<number>
  type: regex|file_exists|command
  target: <path>
  value: <pattern>
  severity: error|warning|info
  desc: "<what the check enforces>"
```

### 6. `harness-artefact` — Bootstrap

Invokes `agent-harness-skill` bootstrap for a specific artefact:
- pre-commit hook (lefthook / captainhook / husky)
- PR or MR template
- CI workflow file
- AGENTS.md / docs/ scaffolding

## Choosing between adjacent destinations

| Question | Answer | Pick |
|---|---|---|
| Is the rule mechanical (regex / script)? | yes | `checkpoint` |
| Is the rule mechanical but enforces a workflow gate? | yes | `harness-artefact` (pre-commit / CI) |
| Is it a permanent personal preference? | yes | `user-memory` |
| Is it specific to this project? | yes | `project-rule` |
| Would another project benefit from the same fix? | yes | `skill-update` |
| Does the friction reveal a missing capability category? | yes | `new-skill` |

When two destinations are plausible, ask the user.

## See also

- `references/classification-heuristic.md` — Friction signal → destination mapping
- `references/patch-workflow.md` — Materialization mechanics for skill-update / new-skill
- Spec: `docs/specs/retro-skill.md`
