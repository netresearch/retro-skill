# Skill Discovery

Runtime discovery of **all** skills available to the user — installed *and*
not-installed. Run it **before** classifying a learning (a mandatory input to
classification), not only after a destination is already chosen. Discovering
only installed skills mis-routes a learning to `user-memory`/`project-rule`
when an org skill already owns it, and proposes a `new-skill` that already
exists somewhere in the org.

## The complete catalogue (primary)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/find-org-skills.py
```

returns every skill in every configured marketplace — installed or not — as a
JSON array of `{name, description, repo_url, marketplace, category, installed}`.
It reads the locally-synced marketplace manifests
(`~/.claude/plugins/known_marketplaces.json` →
`<installLocation>/.claude-plugin/marketplace.json`), so it is **offline** and
**generic**: it covers whatever marketplaces are configured, never a hardcoded
org. This is the authoritative ownership map.

If no marketplaces are configured (or their manifests aren't synced locally) the
catalogue is empty — fall back to the installed-only scan below and **say so**:
coverage is reduced to local installs, so ownership routing and "missing skill"
detection are best-effort until a marketplace is configured.

## Installed-only detail (secondary)

For installed skills' on-disk paths / git remotes (e.g. to prefer an existing
worktree when patching):

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/find-installed-skills.sh
```

returns `{name, path, description, repo_url}` for skills under
`<project>/.claude/skills/`, `~/.claude/skills/`, and the plugin cache.

## Match heuristic

Match the friction topic against the **full catalogue** `description` fields
(installed + available), not just installed skills:

- **1 match, installed** → `skill-update` against that skill (use its `repo_url`)
- **1 match, available but not installed** → `skill-update` against its
  `repo_url`, *and* surface that the skill exists org-wide but isn't installed
  here (recommend installing it — a teammate may simply be missing it)
- **multiple matches** → ask the user with a disambiguation prompt
- **no match anywhere in the catalogue** → propose `new-skill` (a confident
  conclusion now: the whole org catalogue was checked, not just local installs)

Cache the catalogue per session to avoid re-scanning.

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

- The catalogue is a single JSON read with descriptions inline — no per-skill
  `SKILL.md` reads are needed to match.
- Cache the catalogue per session (`~/.cache/retro-skill/catalogue-<session>.json`)
- The catalogue can hold hundreds of skills across marketplaces — keyword/
  category pre-filter before the LLM match, don't feed all descriptions at once.

## See also

- `scripts/find-org-skills.py` — full catalogue (installed + available)
- `scripts/find-installed-skills.sh` — installed-only detail (paths, git remotes)
- `references/patch-workflow.md` — What to do after a skill is matched
- `references/eval-integration.md` — Using evals for context
