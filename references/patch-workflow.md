# Patch Workflow

How `/retro` materializes `skill-update` and `new-skill` destinations.

## Core rule

**Patches always target the source repo. Never the local plugin cache.**

Cache (`~/.claude/plugins/cache/`) is overwritten on plugin update. Edits there are lost.

## Workspace selection

For each skill-update target, select a working directory in this order:

1. **Existing worktree:** `~/p/<skill-name>/main/` exists as worktree AND is clean
   → Use it. Enables seamless manual follow-up by user.
2. **Existing flat checkout:** `~/p/<skill-name>/` exists as flat git checkout AND is clean AND on main
   → Use it.
3. **Fresh clone:** Otherwise clone into `/tmp/retro-workspace/<skill-name>/`
   → Tell user where the clone lives in case they want to inspect.

If the existing checkout is **dirty** (uncommitted changes), do NOT use it — fall back to /tmp clone. Tell the user why:

```
~/p/<skill>/main/ has 3 uncommitted changes; using /tmp/retro-workspace/<skill>/ instead.
```

## Branch naming

```
feat/retro-<short-slug>
```

Slug derived from finding title, kebab-case, max 40 chars.

Examples:
- `feat/retro-add-bun-vs-npm-rule`
- `feat/retro-fix-yaml-parse-tool-choice`

## Commit conventions

- **Conventional Commits format:** `<type>(<scope>): <summary>`
  - Types: `feat`, `fix`, `docs`, `refactor`, `chore`
- **DCO sign-off (required).** Commit with `git commit -s` so a `Signed-off-by:`
  trailer matching the commit author is added. Netresearch skill repos enforce
  the DCO check — **without sign-off the PR is BLOCKED even when every other
  check is green** (this is the single most common reason retro-created PRs
  stall). Before pushing, verify:
  ```bash
  git log -1 --format='%(trailers:key=Signed-off-by)'   # must be non-empty
  ```
- **Pass the message via `-F <file>`, not inline `-m`,** whenever it contains
  quotes, backticks, or other shell-special characters — inline `-m` mangles
  them mid-shell and produces a corrupted or partial commit message.
- **No bot attribution.** Never add "Generated with Claude Code" or "Co-Authored-By: Claude" — see user memory.
- **Preserve signing.** Never pass `--no-gpg-sign` or `-c commit.gpgsign=false` — see user memory `feedback_preserve-commit-signing`. (GPG signing and DCO sign-off are independent — you need *both*.)
- **Preserve hooks.** Never pass `--no-verify`. If a hook fails, investigate.
- **Atomic.** One logical change per commit.

Commit message body should reference the friction:

```
feat(triggers): add bun detection to trigger description

A /retro session on 2026-05-11 found the assistant suggested npm
in 4 turns despite the project using bun. The skill description
didn't include 'bun' as a trigger keyword.
```

## PR creation

GitHub:
```bash
gh pr create --title "<title>" --body "<body>"
```

GitLab (Netresearch internal):
```bash
glab mr create --hostname git.netresearch.de --title "<title>" --description "<body>"
```

If `$GITLAB_HOST` is set, omit `--hostname`.

### PR body template

```markdown
## Summary

<1-2 sentences>

## Came from

`/retro` session on <date>: <session-id>
Finding: <friction signal id> — <one-line description>

## Change

<what was changed>

## Test plan

- [ ] <verification step>
- [ ] <verification step>
```

## Per-private-repo confirmation

Before pushing to a private host, prompt the user:

```
Target: git.netresearch.de/x/y (private)
This will push to a private host. Proceed? [y/N]
```

Decision is remembered for the (session, repo URL) pair.

## New-skill workflow

For `new-skill` destination:

1. Confirm name with user (kebab-case)
2. Confirm target org (default: same org as similar existing skills)
3. Invoke `skill-repo-skill` scaffolding (see its `references/materialization-contract.md`)
4. Initial commit includes:
   - Standard scaffolding (plugin.json, composer.json, licenses, README, AGENTS.md)
   - One reference doc covering the friction pattern
   - One eval covering the friction (TDD)
   - SKILL.md with initial trigger description and workflow

User confirms before push. Marketplace listing is a separate manual step (out of scope).

## Reporting

At end of `/retro`, output a table:

```
| # | Destination | Action | Target | Status |
|---|---|---|---|---|
| 1 | user-memory | wrote | ~/.claude/projects/.../feedback_X.md | ✓ |
| 2 | skill-update | opened PR | github.com/.../foo-skill#42 | ✓ |
| 3 | checkpoint | edited | bar-skill/checkpoints.yaml (AH-12) | ✓ pending push |
```

## See also

- `references/skill-discovery.md` — How targets are identified
- `references/destination-taxonomy.md` — Materialization formats per destination
- User memory: `feedback_preserve-commit-signing`, `feedback_merge-strategy`
