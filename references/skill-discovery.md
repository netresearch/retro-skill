# Skill Discovery

Runtime discovery of installed skills. Used for `skill-update` and `new-skill` destinations to identify the correct target.

## Search paths (in order)

1. `<project>/.claude/skills/` — project-local skills
2. `~/.claude/skills/` — user-installed skills
3. `~/.claude/plugins/cache/*/skills/` — marketplace + private plugin skills
4. `~/.claude/plugins/installed.json` (or equivalent registry) for repo URLs

The helper script:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/find-installed-skills.sh
```

returns a JSON array of `{name, path, description, repo_url}` objects.

## Match heuristic

1. Read each `SKILL.md` frontmatter `description` field
2. LLM matches the friction topic against descriptions
3. Outcome:
   - **1 match** → propose `skill-update` against that skill
   - **multiple matches** → ask user with disambiguation prompt
   - **no match** → propose `new-skill`

Cache discovered skills per session to avoid re-scanning.

## Repo URL extraction

For each matched skill, try these sources in order:

1. `<skill-root>/.claude-plugin/plugin.json` → `repository` field
2. `<skill-root>/composer.json` → `support.source` or `homepage`
3. `<skill-root>/.git/config` → `remote.origin.url` (if skill is a git repo)
4. Plugin manifest in `~/.claude/plugins/installed.json`
5. Last resort: ask user

Convert SSH URLs to HTTPS for display:
- `git@github.com:org/repo.git` → `https://github.com/org/repo`
- `git@git.netresearch.de:org/repo.git` → `https://git.netresearch.de/org/repo`

## Eval discovery

If matched skill has `evals/` directory:

```
<skill-root>/evals/
├── *.md          # Eval scenarios
├── *.yaml        # Eval configurations
└── results/      # Optional historical results
```

Read evals during classification for context. See `references/eval-integration.md`.

## Private repo handling

Auto-discover via search paths regardless of host. Before any patch:

```
Target: git.netresearch.de/x/y (private host)
This will create a PR on a private host. Proceed? [y/N]
```

Decisions are remembered per (session, repo URL) to avoid repeat prompts within a session.

If discovery fails (no manifest, no git remote, no user input):
- For `skill-update`: degrade gracefully — propose local-only edit with warning
- For `new-skill`: proceed with scaffolding into user's home org by default

## Edge cases

| Case | Behavior |
|---|---|
| Skill in `~/.claude/skills/<name>/` with no git remote | User-local; ask "edit locally, or scaffold new repo?" |
| Skill in `<project>/.claude/skills/` | Patch goes to project repo (not skill repo) |
| Cache diverged from source (manual hack) | Show diff, ask user before proceeding |
| Private repo unauthenticated | Graceful failure with instruction |
| Source URL unresolvable | Ask user; offer scaffolding fallback |
| User's git worktree dirty | Skip worktree, use /tmp clone |

## Performance

- Cache skill list per session (`~/.cache/retro-skill/discovered-<session>.json`)
- Lazy-read SKILL.md only on first match attempt
- Keyword pre-filter before LLM match (skip skills with descriptions clearly unrelated)
- Hard cap on number of skills considered: 50 (prefer most-recently-modified)

## See also

- `scripts/find-installed-skills.sh` — Mechanical helper
- `references/patch-workflow.md` — What to do after a skill is matched
- `references/eval-integration.md` — Using evals for context
