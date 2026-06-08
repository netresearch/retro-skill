# Spec: `retro-skill` — LLM-driven Session Retrospection

| | |
|---|---|
| **Status** | Draft (Phase 1 — for review) |
| **Owner Repo** | `agent-harness-skill` (this spec) |
| **Implementation Repo** | `netresearch/retro-skill` (new, to be created) |
| **Companion Changes** | 4 existing skill repos (small edits) |
| **Author** | Sebastian Mendel |
| **Date** | 2026-05-11 |

## Objective

Provide LLM-driven session retrospection as a reusable skill (`/retro`). Detect friction directly from the session transcript, classify into 6 destinations, materialize with per-proposal user approval. Replace the unused Coach approval pipeline with a single efficient pass.

## Anlass (Why Now)

Field investigation of the user's own workflow (subagent report, session 2026-05-11):

- **Coach pipeline is write-only** — `~/.claude-coach/candidates.json` holds 1011 pending / 0 approved / 0 rejected. The hooks-driven detection pipeline (35 MB `events.sqlite`) produces noise (35× duplicates of "Correct syntax for gh pr" with different fingerprints due to flag reordering).
- **The user does skill improvement manually and well**, but no reusable skill captures that workflow — team members cannot reproduce it.
- **An LLM with the actual session transcript** is more accurate and more efficient than continuous regex-based hook detection.
- **Existing canonical artefact:** `~/.claude/projects/-home-sme-p/memory/feedback_<slug>.md` (8 files, consistent schema). The materialization format already exists; the workflow that produces it is what's missing.

## Scope

| | |
|---|---|
| **NEW** | `netresearch/retro-skill` — own repo, own marketplace entry |
| **EDIT (small)** | 4 repos for materialization conventions: `agent-harness-skill`, `agent-rules-skill`, `skill-repo-skill`, `automated-assessment-skill` |
| **NO CHANGE** | `claude-coach-plugin` — Coach stays as-is, optionally read by retro-skill as a data source |
| **OUT** | Versioning/release coordination, auto-merge, marketplace listing automation, migration of existing Coach candidates |

## Repo Layout — `retro-skill`

```
retro-skill/
├── plugin.json
├── composer.json
├── README.md
├── LICENSE-MIT
├── LICENSE-CC-BY-SA-4.0
├── skills/retro/
│   ├── SKILL.md
│   └── checkpoints.yaml          (own quality gates)
├── commands/
│   └── retro.md                  (slash command definition)
├── hooks/
│   └── session-end.json          (off by default)
├── references/
│   ├── friction-catalog.md       (Schichten A/B/C)
│   ├── destination-taxonomy.md   (6 categories)
│   ├── classification-heuristic.md (friction → destination)
│   ├── skill-discovery.md        (where + how to find skills)
│   ├── patch-workflow.md         (source-repo, not cache)
│   ├── eval-integration.md       (how evals inform retro)
│   └── workflow.md               (sweep + spotlight + auto modes)
├── scripts/
│   ├── detect-mechanical.py      (Schicht A pre-pass)
│   ├── find-installed-skills.sh  (mechanical discovery helper)
│   ├── extract-coach-events.py   (optional — reads ~/.claude-coach/ if present)
│   └── scan-cross-session.py     (fallback for Schicht C if Coach absent)
└── docs/specs/
    └── retro-skill.md            (mirror of this spec post-bootstrap)
```

## Commands

```
/retro                              Sweep: analyze entire current session
/retro "<problem description>"      Spotlight: focus on specific issue
```

Plus optional auto-trigger via SessionEnd hook (off by default; user opts in).

## Core Workflow

```
1. Read session transcript (current session, or last N turns)

2. Mechanical pre-pass (Schicht A — Python, fast, deterministic)
   - Tool error rates, retry clusters, output verbosity scores
   - User correction phrases, prompt repetition, sequence patterns
   - Tool sequence n-grams, wrong-tool patterns
   - Skipped verification, upstream failures (post-facto)
   - Permission re-approval, context re-discovery
   → produces structured "candidate findings" list

3. LLM enrichment + inference (Schicht B)
   - Reads pre-pass findings + relevant transcript excerpts
   - Adds: skill-capability gaps, wrong skill choice, hallucination,
     convention violations, missing skill, repeated mistakes,
     assumption-without-asking, doc drift
   - Filters out false positives from Schicht A

4. Cross-session enrichment (Schicht C — optional)
   - If ~/.claude-coach/events.sqlite present: query for related events
   - Else: scan ~/.claude/projects/<slug>/*.jsonl for similar friction
   - Identifies: "same friction again", cross-project patterns, memory drift

5. Classification per finding → 1 of 6 destinations
   - Uses references/classification-heuristic.md

6. For each finding, resolve target:
   - skill-update / new-skill: invoke Skill Discovery
   - user-memory: determine memory file path
   - project-rule: locate project AGENTS.md or docs/feedback/
   - checkpoint: identify target skill's checkpoints.yaml
   - harness-artefact: identify which agent-harness artefact

7. Read evals (if available for matched skill) for context

8. Generate prose proposal per finding (Why + How-to-apply, ~2-3 paragraphs)

9. Present grouped proposals to user
   - Group by destination
   - Show ≤10 actionable items (not 1011)

10. Per-proposal approval: approve / reject / edit

11. Materialize approved proposals via destination-specific workflow
    - PRs go to source repos (never cache)
    - Per-private-repo confirmation
    - Branch + atomic commits + PR

12. Report: created PRs, written files, summary
```

## Friction Detection Catalog

### Schicht A — Mechanical Pre-Pass (`scripts/detect-mechanical.py`)

Fast, deterministic, regex/count-based. Runs before LLM pass to reduce token cost.

| Signal | Detection | Hint at |
|---|---|---|
| **Tool error rate** | `exit_code != 0` or `is_error: true` in tool_use_result | Wrong tool, wrong args, missing tool |
| **Tool retry cluster** | Same tool + similar args ≥3× within N turns | Tool misunderstanding, missing docs |
| **Tool output verbosity** | `len(tool_result) > X` without subsequent filter call | Token waste, wrong tool (`cat` vs `head`, full Read vs Range) |
| **Tool call count vs task** | Total tool calls / user messages ratio | Inefficiency for simple task |
| **Sequential vs parallel** | Multiple independent calls in serial blocks | Performance waste |
| **User correction phrases** | Regex: `^(no\|nein\|stop\|don't\|wrong\|NEIN\|nicht so)`, ALL CAPS, `!!!` | Classic friction |
| **Prompt repetition** | Semantic similarity of user messages within N turns | Assistant didn't understand |
| **Prompt sequence repetition** | n-gram match (n=2..5) over user message sequence | Workflow ripe for snippet/command |
| **Tool sequence repetition** | n-gram match over tool_use names + arg templates | Composition opportunity, skill instruction gap |
| **Skill in reminder vs invoke** | `<command-name>` in reminder, no matching Skill call | Skill not triggered |
| **Wrong tool choice** | `grep` on JSON, `sed` on YAML, `cat` for huge file | Tool-not-used / wrong tool |
| **Re-read same file** | Read tool same path ≥2× without intervening Edit | Caching opportunity |
| **Skipped verification** | Claim "tests pass" / "fixed" without prior test/build run | Verification skip |
| **Worked on main/master** | Git commands without prior `checkout -b` | Workflow violation |
| **Bot attribution in commit** | Commit message contains "Generated with Claude" / "Co-Authored-By: Claude" | Known user rule violated |
| **Outdated tool warning** | "deprecated", "is now", "use X instead" patterns in stderr | Out-of-date knowledge |
| **Upstream failure** | `git push` fails on pre-receive, `gh pr checks` fails post-push, post-commit lint fail | Pre-push verification gap (shift-left) |
| **Permission re-approval** | Same permission prompt approved ≥3× in session | Allowlist needed |

### Schicht B — LLM Inference

Requires conversational context understanding. Cannot be done mechanically.

| Signal | Hint at |
|---|---|
| **Output quality mismatch** | Assistant's verbosity / style differed from user's implicit expectation |
| **Wrong skill choice** | Skill X was triggered, Skill Y would have fit better |
| **Skill capability gap** | Skill triggered, lacked guidance for sub-task |
| **Skill description mismatch** | User question should have triggered Skill X, but its `description` doesn't match |
| **Hallucination / fact check** | Assistant claimed X, later refuted by verification or user |
| **Convention violation** | Code doesn't match project style — no lint fail, but off |
| **Missing skill** | Recurring task with no installed skill matching |
| **Wrong-destination materialization** | Assistant wrote learning to wrong file (e.g. AGENTS.md instead of feedback memory) |
| **Repeated mistake in session** | Same error N× in same session — lesson not learned |
| **Approval bypassed** | Assistant performed irreversible action without user confirmation |
| **Plan / spec skipped** | Non-trivial task started without TodoWrite/plan/spec |
| **Assumption without asking** | Assistant made an assumption later refuted; should have used spec-driven-development |
| **Context re-discovery** | Assistant re-explored repo structure already documented in AGENTS.md |
| **Doc drift** | Assistant used outdated API/library version when context7 would have helped |

### Schicht C — Cross-Session (Persistence Required)

Not detectable from a single session. Optional Coach-events read; otherwise session-file scan.

| Signal | Hint at | Source |
|---|---|---|
| **Same friction again** | Same correction across multiple sessions — memory didn't stick | Coach events OR session JSONL scan |
| **Cross-project pattern** | Same friction class in N≥2 projects | Multi-session JSONL scan grouped by project |
| **Memory drift** | feedback_*.md exists but assistant violated it anyway → skill needs it more prominently | Session JSONL diff against memory files |
| **Skill update ineffective** | Previous PR to skill X, same bug returned afterward | Git log of skill repo + session JSONL |

**Persistence strategy:** if `~/.claude-coach/events.sqlite` exists, query it (fast, indexed). Else scan `~/.claude/projects/<slug>/*.jsonl` (always present, slower). No new state introduced by retro-skill.

## Destination Taxonomy

Six categories, statically documented in `references/destination-taxonomy.md`.

| Destination | When | Materialization Format |
|---|---|---|
| `user-memory` | Personal preference, style, recurring quirk across projects | Append a titled rule to `~/.claude/CLAUDE.md` (the always-loaded global rules file; not the cwd-scoped `~/.claude/projects/<slug>/memory/`) |
| `project-rule` | Project-specific convention or command | Append a titled rule to `<project>/AGENTS.md` (not `<project>/CLAUDE.md`, not `docs/feedback/`) |
| `skill-update` | Existing skill missing instruction or has wrong guidance | PR to skill **source repo** (not cache) via `skill-repo` convention |
| `new-skill` | Friction is skill-shaped gap, no existing skill matches | Invoke `skill-repo` scaffolding for new repo |
| `checkpoint` | Mechanically detectable rule, regex/script possible | YAML entry in target skill's `checkpoints.yaml` (via `automated-assessment` schema) |
| `harness-artefact` | Repo missing hook / CI / template | Invoke `agent-harness` bootstrap for specific artefact (pre-commit hook, PR template, CI workflow) |

## Classification Heuristic (Friction → Destination)

Excerpt; full table in `references/classification-heuristic.md`.

```
Tool output verbosity        → skill-update on tool-owner skill
                                (e.g. file-search, data-tools)

User correction (style)      → user-memory (~/.claude/CLAUDE.md)

User correction (convention) → project-rule (<project>/AGENTS.md)

Skill not triggered          → skill-update (description) OR
                                agent-harness (delegation map)
                                — LLM decides from context

Wrong tool choice            → skill-update on tool-owner
                                OR cli-tools-skill (selection heuristic)

Known rule violated          → skill-update — skill is ignoring user-memory

Skipped verification         → harness-artefact (PR-template question)
                                OR project-rule (CLAUDE.md rule)

Upstream failure             → harness-artefact (pre-commit hook)
                                OR skill-update (verification step)
                                OR checkpoint (mechanical check)
                                OR project-rule

Outdated tool                → skill-update on tool-owner (version bump)
                                OR user-memory (user uses outdated setup)

Missing skill                → new-skill via skill-repo

Cross-project pattern        → skill-update (promotion from feedback files)

Permission re-approval       → user-memory + invoke update-config skill

Context re-discovery         → project-rule — improve AGENTS.md
                                OR skill-update on agent-rules-skill

Assumption without asking    → skill-update on spec-driven-development
                                (trigger description) OR user-memory

Doc drift                    → skill-update on context7-skill trigger
                                OR project-rule
```

## Skill Discovery (Runtime)

Documented in `references/skill-discovery.md`.

**Search paths (in order):**

1. `<project>/.claude/skills/` — project-local
2. `~/.claude/skills/` — user-installed
3. `~/.claude/plugins/cache/*/skills/` — marketplace + private plugins
4. Plugin manifests (`~/.claude/plugins/installed.json` or equivalent) for repo URLs

**Match heuristic:**

1. Read each `SKILL.md` frontmatter `description`
2. LLM matches friction-topic against descriptions (uses pre-extracted keyword index for speed)
3. If 1 match → propose
4. If multiple matches → ask user
5. If no match → propose `new-skill`

**Repo-URL extraction (for patch target):**

1. `plugin.json` `metadata.repository`
2. `composer.json` `support.source` or `homepage`
3. Git remote in skill directory (if it's a git repo)
4. Last resort: ask user

**Evals integration (if present):**

When matched skill has `evals/` directory:
- Read eval files for context during classification ("does this friction contradict an eval?")
- For skill-update proposals: check if eval covers the area; if not, propose eval stub alongside fix (TDD-style)
- For CI eval failures (via `gh api repos/<org>/<repo>/actions/runs`): pre-emptive findings even without user friction

**Private skill handling:**

Auto-discover via search paths. Before any PR creation:
> "Target repo `git.netresearch.de/x/y` (private). Proceed? [yes/no]"

Mitigates accidental leak of patches into wrong/public repos.

## Patch Workflow (Source Repo, Never Cache)

Documented in `references/patch-workflow.md`.

**Core rule:** patches always target the source repo. Cache (`~/.claude/plugins/cache/`) is overwritten on plugin update; edits there are lost.

**Workflow:**

```
1. Discovery returns skill location + source repo URL

2. Workspace selection (in this order):
   a. ~/p/<skill-name>/main/ exists as worktree AND is clean → use it
      (matches user's setup, enables manual follow-up)
   b. Else: clone fresh into /tmp/retro-workspace/<skill>/
   
3. Branch: feat/retro-<short-slug>
   - Slug derived from finding title

4. Edit + atomic commit per logical change
   - No --no-verify (preserve hooks)
   - No --no-gpg-sign (preserve user's SSH signing — see user memory)
   - No bot attribution in commit message (see user memory)
   - Conventional Commits format

5. Push branch + create PR via gh / glab
   - PR body references the friction it resolves
   - PR title follows Conventional Commits
   - For private hosts: use $GITLAB_HOST or --hostname git.netresearch.de

6. Cache stays unchanged. Plugin update mechanism is responsible
   for pulling the new skill version after merge.
   /retro does not trigger plugin updates.
```

**Edge cases:**

| Case | Behavior |
|---|---|
| Skill in `~/.claude/skills/<name>/` no git remote | User-local, no source. Ask user: "edit locally, or scaffold a new repo?" |
| Skill in `<project>/.claude/skills/` | Patch goes to project repo (not skill repo) |
| Cache diverged from source (manual hack) | Show diff, ask user before proceeding |
| Private repo unauthenticated | Graceful failure, user instruction |
| Source repo URL unresolvable | Ask user; offer to scaffold new repo |
| User on detached HEAD or dirty worktree | Skip worktree, use /tmp clone |

## Companion Repo Changes

### `agent-harness-skill`

- **EDIT** `skills/agent-harness/SKILL.md`:
  - Add Key Principle: *"Does not own learning. Delegates session learning to retro-skill. Verifies that integration points exist."*
  - Add Delegation entry: *Session retrospectives and learning materialization → `@retro`*
- **EDIT** `references/skill-integration-map.md`: new section "retro-skill" describing what Harness expects (PR-template retro question, optional SessionEnd hook configured)
- **EDIT** `references/harness-engineering-overview.md`: add line *"Harness does not store learning itself. It provides rails (memory files, rule files, CI checks, hooks, review templates). Learning is performed by retro-skill."*
- **EDIT** `templates/pull_request_template.md.tmpl` and `templates/merge_request_template.md.tmpl`:
  ```markdown
  ## Retro
  - [ ] Was a reusable pattern detected? If yes, was it routed via /retro?
  ```
- **NEW Checkpoint AH-22** (warning, Level 3):
  ```yaml
  - id: AH-22
    type: regex
    target: "{.github/pull_request_template.md,.github/PULL_REQUEST_TEMPLATE/*,.gitlab/merge_request_templates/*}"
    value: "(?i)retro|reusable.*pattern"
    severity: warning
    desc: "PR/MR template includes retro question for agent-authored work"
  ```
- **NEW Checkpoint AH-23** (info, Level 3):
  ```yaml
  - id: AH-23
    type: file_exists
    target: ".claude/hooks/session-end.json"
    severity: info
    desc: "SessionEnd hook configured if auto-retro is desired (optional)"
  ```

### `agent-rules-skill`

- **NEW** `references/feedback-memory-schema.md`: documents the existing `feedback_<slug>.md` format as canonical project-rule materialization. Frontmatter (`name`, `description`, `type: feedback`, `originSessionId`) + body (`**Why:**`, `**How to apply:**`).
- **EDIT** `assets/root-thin.md`: optional reference to `docs/feedback/` directory if it exists.
- **EDIT** `references/output-structure.md`: clarify *project rules live in `<project>/AGENTS.md`* (the routing this PR adopts; superseding the earlier `docs/feedback/<slug>.md` plan).

### `skill-repo-skill`

- **NEW** `assets/.github/ISSUE_TEMPLATE/skill-learning.yml`:
  ```yaml
  name: Skill learning
  description: Capture a reusable learning from an agent session
  body:
    - type: textarea
      id: observed
      attributes: {label: Observed friction}
    - type: textarea
      id: expected
      attributes: {label: Desired future behavior}
    - type: textarea
      id: proposed-change
      attributes: {label: Proposed skill change}
    - type: dropdown
      id: target
      attributes:
        label: Target area
        options: [SKILL.md, references/, scripts/, templates/, checkpoints.yaml, evals/]
  ```
- **EDIT** PR template — add "Learning Source" block: *"Came from /retro? Reusable beyond one project? Stays focused, no project-specific rules?"*
- **NEW** `references/materialization-contract.md`: contract between retro-skill and skill repos (branch convention `feat/retro-<slug>`, commit format Conventional Commits, PR-body schema, requirement to read `evals/` if present).

### `automated-assessment-skill`

- **NEW** `references/learning-derived-checkpoints.md`: YAML schema spec + examples for friction-derived checkpoints. When retro-skill proposes destination=`checkpoint`, this reference is the contract for the YAML it should produce.

### `claude-coach-plugin`

**No changes.** Coach stays installed and unchanged. retro-skill optionally reads `~/.claude-coach/events.sqlite` for Schicht C; absence is graceful (falls back to JSONL scan).

## Boundaries

**Always do:**
- LLM is the primary classifier (no Coach-hook-pipeline dependency)
- 1 approval per materialization (not per candidate)
- Per-private-repo confirmation before PR
- Materialization format follows owner-skill convention
- Patches go to source repo, never cache
- Preserve commit signing (no `--no-gpg-sign`)
- Conventional Commits in commit messages and PR titles

**Ask first:**
- Skill-match ambiguity (>1 possible skill)
- Auto-mode activation (SessionEnd hook)
- Private repo targets
- Cache diverged from source
- User-local skills with no git remote

**Never:**
- Auto-merge of PRs
- Write to user/project memory without approval
- Generate 1000+ candidates (Coach anti-pattern)
- Continuous background hooks (Coach anti-pattern; only optional SessionEnd)
- Hardcode static skill list
- Add bot attribution to commits or PRs
- Skip hooks (`--no-verify`)
- Patch the cache directory

## Success Criteria

1. **Sweep mode** delivers ≤10 actionable proposals per medium session (not 1011)
2. **One LLM pass** for analysis + classification (no multi-round polling)
3. **≤5 tool calls** for skill discovery (cached per session)
4. **Token budget:** `/retro` of a 2-hour session stays under target X (X tbd post-prototype, dramatically below continuous Coach pipeline)
5. **Discovery** finds local + marketplace + private skills
6. **Materialization** follows owner-skill convention (smoke test per destination)
7. **Spotlight mode** works without full session context ("describe the problem")
8. **Coach independence:** `/retro` runs cleanly without Coach installed
9. **Coach integration:** when present, Coach events accelerate Schicht C
10. **Patches land in source repo**, never cache
11. **Evals consulted** when target skill has them
12. **AH-22 + AH-23** checkpoints green in test repo
13. **All 18 Schicht-A signals** detected by `detect-mechanical.py`
14. **All 14 Schicht-B signals** in `friction-catalog.md` with prose example each
15. **All 5 Schicht-C signals** documented with persistence strategy

## Verification Plan

| Step | Who | How |
|---|---|---|
| Discovery finds skills in 4 paths | mechanical | `find-installed-skills.sh` against synthetic test layout |
| Mechanical pre-pass detects all Schicht-A signals | mechanical | unit test: synthetic transcript with each signal, assert detection |
| Classification covers 6 destinations | manual | test sessions with known friction patterns |
| Token budget held | mechanical | telemetry per `/retro` run, fail CI if regression |
| Materialization smoke per destination | manual | one friction per destination → one materialization |
| Private-repo confirmation triggers | mechanical | mock run with `git.netresearch.de` URL |
| Coach optional | mechanical | `/retro` without `~/.claude-coach/` runs clean |
| Coach integration | mechanical | `/retro` with `~/.claude-coach/` reads events |
| Patch goes to source not cache | mechanical | assert PR target is repo URL, never `~/.claude/plugins/cache/` |
| Worktree preference | mechanical | when `~/p/<name>/main/` clean → workspace selected; when dirty → /tmp fallback |
| Evals read when present | mechanical | mock skill with `evals/` → assert evals in LLM context payload |
| Commit signing preserved | mechanical | post-commit `git log --show-signature` shows G |
| No bot attribution | mechanical | grep commit messages for known anti-patterns |

## Open Questions

All resolved during Phase-1 elicitation.

| ID | Question | Resolution |
|---|---|---|
| Q1 (orig) | Coach candidates schema migration | N/A — Coach unchanged |
| Q2 (orig) | Classifier: Python vs LLM | Python for Schicht A (mechanical), LLM for Schicht B (inference) |
| Q3 (orig) | Cross-repo promotion trigger | Manual ("fix it for all skills"), no algorithm |
| Q4 | Coach fate | Keep as optional data source, not modified |
| Q5 | New skill home | New repo `netresearch/retro-skill` |
| Q6 | Commands | `/retro` (sweep + spotlight via argument) + optional SessionEnd hook |
| Q7 | Routing contract necessity | Static taxonomy (6 destinations) + dynamic skill discovery — best of both |
| Q8 | Skill name | `retro` (not `compound-engineering`, not `skill-ratchet` — too narrow/buzzy) |
| Q9 | Spotlight granularity | Single command with optional argument; no separate `/fix-skill` |
| Q10 | Discovery scope | Auto-discovery including private; per-PR confirmation gates leak risk |
| Q11 | Friction catalog scope | All A + all B + all C in v0.1 (no MVP cut) |
| Q12 | Patch location | Source repo, never cache |
| Q13 | Evals integration | Yes, both for context and as TDD-stub for new updates |

## Out of Scope

- Coach internal changes (separate task; Coach has independent backlog)
- Migration of existing 1011 Coach candidates (separate cleanup task)
- Versioning / release coordination of the 4 companion skills (separate per-skill release flow)
- Auto-merge or CI integration for PRs created by `/retro`
- Multi-session aggregation beyond Schicht C detection (each `/retro` is self-contained)
- Marketplace listing automation for `new-skill` destination
- Cross-organization skill promotion (e.g. open-sourcing private learnings)
- Telemetry storage / dashboards (focus on per-session efficacy)

## References

- Subagent field report (session 2026-05-11): manual workflow analysis showing Coach unused, `feedback_*.md` schema canonical
- `~/.claude-coach/candidates.json`: 1011 pending / 0 approved evidence
- `~/.claude/projects/-home-sme-p/memory/feedback_*.md`: 8 existing files demonstrating canonical format
- Addy Osmani, "Agent Harness Engineering": ratchet concept, but materialization belongs in retro-skill not in agent-harness
- `~/p/agent-harness-skill/main/skills/agent-harness/checkpoints.yaml`: existing AH-* numbering scheme (Level 3 = 20s; AH-22, AH-23 free)
- `~/p/claude-coach-plugin/skills/coach/SKILL.md`: existing Coach signal taxonomy (informs Schicht A patterns)

## What's Next (post-approval)

- **Phase 2 (PLAN):** Implementation order — `retro-skill` bootstrap first, then 4 companion PRs in parallel; risks; verification gates
- **Phase 3 (TASKS):** Per-repo file-level tasks with acceptance + verify
- **Phase 4 (IMPLEMENT):** Parallel execution via subagents
