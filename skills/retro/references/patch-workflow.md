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

## Self-review before push

A `/retro` skill-update **authors content into another skill** — commands,
recipes, code examples. That content can be plausible but wrong, and once
merged it ships as authoritative guidance. Before pushing, re-read your own
diff and check:

- Every command/recipe you wrote **would actually run as written** (flags exist,
  quoting is correct, the example is internally consistent — e.g. don't claim an
  *unescaped* quote closes a string while showing an *escaped* one).
- Any "do X then Y" sequence is coherent (no step that contradicts a prior step).
- The root cause in the commit/PR body is one you **verified**, not inferred — if
  you didn't confirm it, say "suspected" rather than asserting it.
- **Prefer deletion over exception.** If the friction is caused by an obsolete or
  harmful instruction, a `skill-update` may be a pure *removal* diff — don't add a
  new exception alongside the bad rule (see `classification-heuristic.md` →
  "Instruction pruning"). Cite where the behaviour is already covered.
- **Reject wording-only churn.** If an edit only rephrases without changing
  behaviour, drop it — it is noise the next retro will re-flag.
- **Run the target skill's own gates locally — reading the diff is not enough.**
  Before pushing, run the destination repo's validator (`skill-repo`'s
  `validate-skill.sh`: SKILL.md word cap, frontmatter, structure), its linters,
  and any script self-tests. A structural gate like the 500-word SKILL.md limit
  fails in CI, never in a re-read — and note SKILL.md often sits *at* the cap, so
  put new prose in a reference file, not SKILL.md.
- **Change every occurrence of a recurring rule in one pass.** When the fix is a
  policy stated in more than one place (a SKILL.md step, a reference section, a
  script header/output), grep the term and update all of them together, then
  confirm no file still states the old rule. Reactive one-spot edits leave the
  skill contradicting itself.

Observed failures: a retro shipped a self-contradictory `--force-with-lease`
recipe and a contradictory escaping example, both caught only by an external
reviewer, plus a wrong "main lags origin" root cause that only the user caught. A
later retro broke the target's Skill Validation CI (the SKILL.md edit went over
the 500-word cap, invisible to a diff read), and a policy change patched one spot
at a time, leaving a SKILL.md step contradicting its own reference across several
review rounds until the user demanded it be done in one coherent pass. A
30-second self-review plus running the target's validator would have caught all
of these.

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
