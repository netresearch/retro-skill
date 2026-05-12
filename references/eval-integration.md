# Eval Integration

How `/retro` consults skill `evals/` directories to inform classification and propose TDD-style stubs.

## When evals are consulted

After a skill is matched for `skill-update` destination, check if it has `evals/`:

```
<skill-root>/evals/
├── *.md          # Eval scenarios (Markdown, possibly with frontmatter)
├── *.yaml        # Eval configurations
└── results/      # Optional historical results
```

If yes, read evals before generating the proposal.

## Three uses

### 1. Classification context

The LLM reads relevant eval scenarios to validate the friction interpretation:

> "Skill X claims (via eval `evals/handle-bun-projects.md`) to support bun. The friction shows the opposite. This is a skill bug, not a skill gap — different fix."

This distinguishes:
- **Skill bug** — eval covers the case, behavior diverged → fix the skill or the eval
- **Skill gap** — eval doesn't cover the case → add capability AND eval

### 2. TDD stub for skill-update

When proposing a `skill-update` and no eval covers the friction area, propose an eval stub alongside the fix:

```markdown
## Proposed change
1. Update SKILL.md description to include "bun"
2. Add eval: `evals/handle-bun-projects.md` covering bun-vs-npm choice

## Eval stub
\`\`\`markdown
---
scenario: handle-bun-projects
trigger: User says "this is a bun project"
expected: Skill triggers and suggests bun commands (bun install, bun run)
\`\`\`
```

This is TDD style: eval that would have caught the friction goes in with the fix.

### 3. Pre-emptive findings (CI integration)

If the target skill repo has CI accessible via `gh api`:

```bash
gh api repos/<org>/<repo>/actions/runs --jq '.workflow_runs[0]'
```

Read recent eval failures. These are friction the user hasn't hit yet — pre-emptive `/retro` findings.

Only do this when:
- The skill is being actively worked on (recent commits)
- Eval failures exist
- The user opts in (configurable)

## Eval format (lightweight, no enforced schema)

Different skills may use different eval formats. `/retro` reads them as text and gives the content to the LLM for context. Common patterns:

```markdown
---
scenario: <name>
trigger: <user prompt or condition>
expected: <expected behavior>
---
<optional explanation>
```

Or YAML-based:

```yaml
scenarios:
  - name: <name>
    given: <context>
    when: <user input>
    then: <expected behavior>
```

`/retro` does not enforce a format — it adapts to what each skill uses.

## Limitations

- Evals are not always present (most skills don't have them yet)
- Eval coverage varies; absence of eval ≠ absence of capability
- Eval format heterogeneity makes mechanical analysis hard; LLM reading is the practical approach

When evals are absent: `/retro` operates normally, just without this context source.

## See also

- `references/skill-discovery.md` — How evals are located
- `references/classification-heuristic.md` — Where eval context informs decisions
- `references/patch-workflow.md` — How eval stubs land alongside skill-update PRs
