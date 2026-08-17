# Destination Taxonomy

Every friction finding maps to one of seven destinations — or, in the bounded
pair shapes below ("Paired materialization"), to two coupled parts approved as
one proposal. Each destination owns a specific materialization format defined
by a specialist skill.

## The Seven

| # | Destination | When | Owner Skill (materialization format) | Storage Location |
|---|---|---|---|---|
| 1 | `personal-rule` | Personal preference, style, recurring quirk across projects | retro-skill (appends a rule) | `~/.claude/CLAUDE.md` (the always-loaded global rules file) |
| 2 | `project-rule` | Project-specific convention or command | retro-skill (appends a rule) | `<project>/AGENTS.md` |
| 3 | `skill-update` | Existing skill missing instruction or has wrong guidance | `skill-repo-skill` (defines `materialization-contract`) | PR to skill **source repo** (never cache) |
| 4 | `new-skill` | Friction is skill-shaped gap, no existing skill matches | `skill-repo-skill` (defines scaffolding) | New repo via scaffolding workflow |
| 5 | `checkpoint` | Mechanically detectable rule, regex/script possible | `automated-assessment-skill` (defines YAML schema) | Entry in target skill's `checkpoints.yaml` |
| 6 | `harness-artefact` | Repo missing hook / CI / template | `agent-harness-skill` (defines artefact templates) | Hook / CI workflow / PR template in target repo |
| 7 | `canonical-source` | The fact's canonical owner is an artefact outside the agent system: upstream docs, code, schema, handbook (Axis 0 in `classification-heuristic.md`) | Domain skill's contribution reference (e.g. `typo3-docs`'s `upstream-docs-contribution.md`); mechanics per `patch-workflow.md` | PR/patch to the canonical source (docs repo, defining code, manifest) |

## Format details

### 1. `personal-rule` — append a rule to `~/.claude/CLAUDE.md`

> Renamed from `user-memory`. That name is a **deprecated alias**: accept it
> wherever a destination is read (a user's phrasing, an older proposal, an
> archived report), and always emit `personal-rule` in output. What this
> destination materializes is a line in the always-loaded global rules file —
> a durable *instruction*, not a recollection of past sessions. Calling it
> memory put it in the same category as the session transcript, which is the
> one category it is not.

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
  pattern: <pattern>
  severity: error|warning|info
  desc: "<what the check enforces>"
  provenance: regression          # authority class; see the schema reference
  source: <session/issue/PR where the failure was observed>
  learning_id: retro-YYYYMMDD-<slug>   # provenance chain back to the finding
```

### 6. `harness-artefact` — Bootstrap

Invokes `agent-harness-skill` bootstrap for a specific artefact:
- **agent-harness hook** — a Claude Code `PreToolUse`/`Stop` hook wired in
  `~/.claude/settings.json` (deny or systemMessage nudge). This is the
  instrument for rules the *agent* keeps violating across every repo — a
  merge gate on `gh pr merge`, a deny on hand-rolled poll loops. Reach is one
  machine/user, not a team; when the same gate belongs to teammates, pair it
  with a `skill-update` carrying the install recipe (script + settings.json
  wiring), per "Paired materialization" below.
- pre-commit hook (lefthook / captainhook / husky / pre-commit)
- linter or static-analysis rule — a new ESLint/PHPStan/golangci-lint rule, a
  raised analyzer level, a `.yamllint.yml` rule, `fail_level: error` on a
  reviewdog action. Ships where the analyzer already runs, so it needs no new
  instrument; often the cheapest gate available.
- CI workflow file, or a job/step added to an existing one
- branch protection / ruleset — server-side, the only instrument nobody bypasses
- PR or MR template
- AGENTS.md / docs/ scaffolding

Materialization mechanics — target-repo selection, verify-before-bootstrap,
CI/hook parity, and why server-side rules cannot be a PR — are in
`references/patch-workflow.md` ("Harness artefacts").

### 7. `canonical-source` — PR/patch to the owning artefact

For facts whose canonical owner sits outside the agent system (Axis 0 in
`classification-heuristic.md`): official upstream documentation, the code that
defines the value (a `configure()` method, a schema, a manifest), an org
handbook.

- Materialize as a PR/patch **to the owning artefact**, following the owning
  project's contribution workflow. A domain skill often documents that path
  (e.g. `typo3-docs`'s `references/upstream-docs-contribution.md`); branch,
  commit, and sign-off mechanics as in `references/patch-workflow.md`.
- The skill involved keeps at most a **reference + agent-specific delta**. Any
  duplicate it already carries is pruned in the same proposal — pair the
  upstream PR with that `skill-update` cleanup ("Paired materialization"
  below).
- If the owner cannot take the fix now (no contribution path, upstream gap),
  fall back to a **labelled temporary copy** in the skill: authority class,
  the upstream issue/PR link, and the finding's `Learning-Id`. That triple is
  the prune trigger: `/retro outcome` detects the merged upstream PR (**D12**)
  and proposes reducing the copy to a reference; `/retro audit --scope skill`
  catches whatever outcome mode missed.
- An upstream PR is an **outward-facing artefact in a foreign project**:
  confirm the exact target and text with the user before posting. Nothing is
  posted silently.

Choose the instrument by enforcement strength, not by convenience:
`agent-harness-skill/references/enforcement-mechanisms.md` ranks all ten from
server-side to convention-based, and requires **CI/hook parity** — every fast,
deterministic check in CI must also run as a pre-commit hook. A proposal that
adds a CI check meeting the fast-check definition without the matching hook is
half-materialized.

## Choosing between adjacent destinations

| Question | Answer | Pick |
|---|---|---|
| Is the fact owned by an artefact outside the agent system (official docs / code / schema / handbook)? | yes | `canonical-source` (+ paired `skill-update` reference/cleanup) |
| Is the rule mechanical (regex / script)? | yes | `checkpoint` (`mechanical:`) |
| Is the rule mechanical but enforces a workflow gate? | yes | `harness-artefact` (pre-commit / CI / linter rule) |
| Is it checkable but by judgment, not by pattern? | yes | `checkpoint` (`llm_reviews:`) |
| Is it a permanent personal preference? | yes | `personal-rule` |
| Is it specific to this project? | yes | `project-rule` |
| Would another project benefit from the same fix? | yes | `skill-update` |
| Does the friction reveal a missing capability category? | yes | `new-skill` |

**Three axes, in order: authority, then enforceability, then reach.** Read the
table top-to-bottom — the first row is the authority axis (who owns the truth),
the next three rows are the enforceability axis, and they come first on
purpose. A fact fixed at its owner outranks a local copy; a gate that fails
the build outranks a sentence that asks for care. Route to
`checkpoint`/`harness-artefact` whenever the friction is one a check could
have failed on.

For whatever remains prose, bias *upward in reach*: `skill-update`/`new-skill`
(shared with everyone) › project `AGENTS.md` (shared with the repo) › global
`~/.claude/CLAUDE.md` (personal). The two axes pull against each other — a gate
lands in one repo, a skill reaches all of them — so where a gate is possible,
the prose that belongs beside it is the *recipe for installing that gate
elsewhere*, not a restatement of the rule the gate already enforces.

Only narrow when escalation would be wrong (the lesson is genuinely personal or
repo-specific). Never project-local memory. See "Routing — enforceability first,
then reach" in `classification-heuristic.md`. When the *fit* is truly ambiguous,
ask the user.

## Paired materialization — the bounded exceptions to "one destination"

Two pair shapes are recognized; both materialize as **one proposal with two
coupled parts**:

| Pair shape | Part 1 | Part 2 |
|---|---|---|
| **Gate + propagation** — the finding is enforceable in the repo it occurred in *and* the same gate belongs in sibling repos | `harness-artefact` or `checkpoint`: the check, in the repo the friction happened in | `skill-update`: the recipe for installing that gate elsewhere, in the skill that owns the topic |
| **Canonical fix + cleanup** — the fact's owner is outside the agent system *and* a skill currently duplicates or contradicts it | `canonical-source`: PR/patch to the owning artefact | `skill-update`: replace the skill's copy with a reference (+ agent-specific delta) |

Rules, all binding:

- **A pair is one proposal, approved once, and counts as one against the ≤10
  cap.** Splitting it into two proposals allows one half to be approved while
  the other is rejected — a prose rule without its gate reproduces the failure
  the enforceability axis exists to prevent, and a skill cleanup without its
  upstream PR deletes knowledge before its new home exists.
- **The approval line names both targets**, because they are usually two
  different repos and one of them is not the repo the user is standing in:
  `harness-artefact → <repo> (lefthook.yml) + skill-update → <skill> (install recipe)`.
- **The propagation half must not restate the rule.** It carries how to add the
  gate and how to tell whether a repo already has it. If the prose you are
  writing would still make sense with the gate deleted, it is a restatement —
  drop it and ship the gate alone.
- **The cleanup half must not keep the fact.** After a canonical-fix pair, the
  skill states *where the truth lives* plus the agent-specific delta. If the
  skill text still asserts the fact itself, it is a copy, not a reference.
  Ordering is materialize-then-drain, as in promote mode: the upstream PR must
  exist before the skill's copy is reduced to a reference.
- **Two parts maximum.** No three-part materializations. If a finding seems to
  need a third, it is more than one finding.
- **Both parts appear as separate rows in the Phase-11 report**, so a pair that
  half-fails is visible rather than reported as done.

Pair only when the second half is real. A gate that is meaningful in exactly
one repo — a project-specific path, a one-off migration guard — is a plain
`harness-artefact` with no second half; an upstream fact no skill currently
duplicates is a plain `canonical-source` with no second half.

## See also

- `references/classification-heuristic.md` — Friction signal → destination mapping
- `references/patch-workflow.md` — Materialization mechanics for skill-update / new-skill
- Spec: `docs/specs/retro-skill.md`
