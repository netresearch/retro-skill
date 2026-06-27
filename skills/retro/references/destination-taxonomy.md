# Destination Taxonomy

Every friction finding maps to exactly one of six destinations. Each destination owns a specific materialization format defined by a specialist skill.

## The Six

| # | Destination | When | Owner Skill (materialization format) | Storage Location |
|---|---|---|---|---|
| 1 | `user-memory` | Personal preference, style, recurring quirk across projects | retro-skill (appends a rule) | `~/.claude/CLAUDE.md` (the always-loaded global rules file) |
| 2 | `project-rule` | Project-specific convention or command | retro-skill (appends a rule) | `<project>/AGENTS.md` |
| 3 | `skill-update` | Existing skill missing instruction or has wrong guidance | `skill-repo-skill` (defines `materialization-contract`) | PR to skill **source repo** (never cache) |
| 4 | `new-skill` | Friction is skill-shaped gap, no existing skill matches | `skill-repo-skill` (defines scaffolding) | New repo via scaffolding workflow |
| 5 | `checkpoint` | Mechanically detectable rule, regex/script possible | `automated-assessment-skill` (defines YAML schema) | Entry in target skill's `checkpoints.yaml` |
| 6 | `harness-artefact` | Repo missing hook / CI / template | `agent-harness-skill` (defines artefact templates) | Hook / CI workflow / PR template in target repo |

## Format details

### 1. `user-memory` — append a rule to `~/.claude/CLAUDE.md`

A cross-project personal preference belongs in the **always-loaded global rules
file**, `~/.claude/CLAUDE.md`. Append a short, titled rule:

```markdown
## <Short rule title>

<1-2 sentences: what to do and why. State the trigger and the action.>
```

**Do NOT** write to `~/.claude/projects/<slug>/memory/`. That directory is
**cwd-scoped** — a file written there while working in `~/p/foo` is only
recalled when the cwd resolves to that same project slug, so it is *not* a
global memory at all. It silently fragments "personal preferences" across
projects (the failure this skill exists to surface). Global rules go in
`~/.claude/CLAUDE.md`; nothing else is reliably loaded everywhere. The
`/retro promote` mode exists to drain memories already written to this
cwd-scoped location upward into the correct destination — see
`references/promote-mode.md`.

### 2. `project-rule` — append a rule to `<project>/AGENTS.md`

A project-specific convention belongs in that repo's `AGENTS.md` (committed,
versioned, loaded for everyone working the repo). Append a titled rule in the
same form as above. Do not create `<project>/CLAUDE.md` or
`<project>/docs/feedback/` files — `AGENTS.md` is the single project rule store.

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

**Prefer the broadest useful scope.** Read the table top-to-bottom but bias
*upward in reach*: `skill-update`/`new-skill` (shared with everyone) › project
`AGENTS.md` (shared with the repo) › global `~/.claude/CLAUDE.md` (personal).
Only narrow when escalation would be wrong (the lesson is genuinely personal or
repo-specific). Never project-local memory. See "Scope escalation" in
`classification-heuristic.md`. When the *fit* is truly ambiguous, ask the user.

## See also

- `references/classification-heuristic.md` — Friction signal → destination mapping
- `references/patch-workflow.md` — Materialization mechanics for skill-update / new-skill
- Spec: `docs/specs/retro-skill.md`
