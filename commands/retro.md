---
description: "Session retrospection — detect friction AND reusable learnings, classify into destinations, materialize approved learnings"
---

# /retro — Session Retrospective

A retrospective captures **two equally-weighted classes**, and every run scans
for BOTH:

1. **Friction** — things that went wrong (errors, corrections, retries,
   violations, inefficiencies).
2. **Reusable knowledge that went RIGHT but is not captured anywhere yet** — a
   learning worth propagating so nobody re-derives it. It leaves no error signal,
   so you must look for it deliberately; a smooth session is **not** an empty
   retro.

Analyze the current session for both, then classify and materialize into the
correct destination.

## Usage

```
/retro                                Sweep — full current session
/retro "<problem description>"        Spotlight — focus on one issue
/retro outcome [session-id|--since N] Outcome — post-hoc review of past session(s)
/retro audit [--scope X]              Audit — cross-session architectural review
/retro promote [--scope cwd|all]      Promote — re-home accumulated local memory upward
```

## Phase 1: Mechanical Pre-Pass

Run the deterministic friction detector against the session transcript:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/detect-mechanical.py \
  --transcript-file ~/.claude/projects/<slug>/<session-id>.jsonl \
  --output-format json
```

Output is a structured list of candidate findings. Read this before scanning the transcript yourself — it saves tokens.

## Phase 2: LLM Enrichment

For each pre-pass candidate, validate against the conversational context. Add
inferential findings the pre-pass cannot catch — in **both** classes below.

### Friction findings

- Wrong skill choice (Skill X triggered, Skill Y would have fit better)
- Skill capability gap (skill triggered, lacked sub-task guidance)
- Hallucination / fact-check failures
- Convention violations
- Missing skills
- Repeated mistakes within same session
- Assumption-without-asking patterns
- Doc drift

### Reusable-learning findings (scan even when nothing went wrong)

The pre-pass is friction-only; these leave no error signal, so surface them here
or they are lost. A clean session still owes these findings.

- **Hard-won technique (B16):** a non-obvious command, flag, endpoint, or
  workflow the session figured out — even cleanly, first try — that is NOT in the
  owning skill. Root cause: "we had to dig this out." → `skill-update`.
- **Proactive improvement (B17):** a better approach identified during the work
  (not as a correction). → `skill-update`.
- **Review-issue learning (B18):** a generalizable lesson from a code-review
  comment (given OR received) — a reviewer taught a rule that applies beyond this
  diff. → `skill-update` (or `project-rule` if repo-specific).

For each learning ask: **"Would a future agent re-derive this, and does an
existing skill already say it?"** If re-derivable and not covered → it is a
finding.

See `skills/retro/references/friction-catalog.md` Schicht B for the full list.

## Phase 3: Cross-Session (Optional)

If `~/.claude-coach/events.sqlite` exists:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/extract-coach-events.py --since "30 days ago"
```

Otherwise fall back to JSONL scan:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/scan-cross-session.py --pattern "<fingerprint>"
```

## Phase 4: Classification

Run **Phase 5 skill discovery first** — the catalogue of all skills (installed
*and* available) is a required input to classification, not a consequence of it.
Then map each finding to one of six destinations using
`skills/retro/references/classification-heuristic.md`, checking the catalogue for an owning
skill before any narrower destination. When uncertain, ask the user.

## Phase 5: Skill Discovery

Run up front, for **every** candidate learning (not only once a destination is
chosen) — discover the full catalogue:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/find-org-skills.py
```

Returns every skill in every configured marketplace — installed or not —
`{name, description, repo_url, marketplace, installed}` (offline, generic). Match
the friction topic against the catalogue `description` fields:

- match → `skill-update` against the owning skill's `repo_url` (even if not
  installed locally — note it's available-not-installed so it can be installed)
- multiple matches → ask the user
- no catalogue match → `new-skill`

A description-level **no-match is not conclusive**. One-line descriptions
routinely under-state what a skill owns (e.g. a "GHCR package deletion scopes"
finding belongs in github-project's gh-CLI reference, though its description says
only "GitHub repository setup and platform-specific features"). For any
tool / platform / workflow finding, before concluding "no owning skill" and
falling back to `project-rule` or `user-memory`, you **MUST open the top 1–2
candidate skills** (inferred from the skill name, category, or domain) — their `SKILL.md` and `references/` files — and check for a
fitting section. Only after that content check fails is `new-skill` (or a
narrower destination) correct.

For installed skills' on-disk paths / git remotes when patching, also:
`bash ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/find-installed-skills.sh`.

## Phase 6: Eval Consultation

If matched skill has `evals/` directory: read evals for context. If proposing a skill-update, also propose an eval stub (TDD style) when no existing eval covers the area. If the matched skill is **retro itself**, its own `evals/` apply — they test retro's classification (see `skills/retro/references/eval-integration.md`).

## Phase 7: Proposal Generation

Per finding, generate prose:
- **Why:** 1-2 paragraphs explaining the friction and its root cause
- **How to apply:** 1-2 paragraphs describing the concrete fix

Group proposals by destination. Show ≤10 items, ranked by severity (see
`skills/retro/references/classification-heuristic.md` → "Severity inference").

**Do not let friction crowd out learnings.** When more than 10 candidates exist
and the list is trimmed to fit, reserve slots so the top reusable-learning
findings (B16–B18) survive — a friction-free learning is graded *at least*
`important`, never auto-`nice-to-have`, precisely so it is not the first thing
dropped. A retro that returns 10 friction items and zero learnings on a session
that produced learnings has failed its second class.

For **skill-update** proposals, also include a **Skill instruction delta**:

- **Current instruction(s):** the exact line(s) being changed or removed.
- **Proposed edit:** add / replace / **remove** (removal is valid — see
  `skills/retro/references/classification-heuristic.md` → "Instruction pruning").
- **Why bounded:** what the edit does *not* touch.

Cite eval evidence only when an eval **already** covers the area (read, never a
fabricated "without-skill / with-skill" comparison — retro runs one pass and does
not re-execute tasks). Before listing a skill-update edit, read
`~/.claude/retro/rejected-edits.md` (if present) and **suppress any edit already
recorded there** — do not re-propose what the user has already rejected.

## Phase 8: User Approval

Present grouped proposals. Per item:
- ✅ Approve → materialize
- ✏️ Edit → modify before materializing
- ❌ Reject → skip, and for a skill-update edit append a one-line entry to
  `~/.claude/retro/rejected-edits.md` (target skill · edit summary · reason ·
  date) so it is not re-proposed in a later session

## Phase 9: Materialization

Per destination, follow `skills/retro/references/patch-workflow.md` and the destination-specific convention. **Patches go to source repos, never to cache.**

For each created PR / file:
- Use Conventional Commits format
- No bot attribution in commit messages or PR bodies
- Per-private-repo confirmation before push
- Preserve commit signing (no `--no-gpg-sign`)

## Phase 10: Report

Summary table:

```
| Destination | Action | Target | Status |
|---|---|---|---|
| user-memory | wrote | ~/.claude/.../feedback_X.md | ✓ |
| skill-update | opened PR | netresearch/typo3-conformance-skill#456 | ✓ |
| checkpoint | added AH-22 | agent-harness-skill | ✓ |
```

## Spotlight Mode

When invoked with a `"<problem description>"` argument:

```
/retro "the assistant kept using npm instead of bun"
```

- Skip Phase 1 full-transcript mechanical pre-pass; instead extract argument-matching turns
- Run LLM enrichment on those turns only
- Run Phase 3 (cross-session) in filtered mode (same friction signature)
- Skip Phases 3b and 3c
- Proceed with Phases 4–10

Faster and uses fewer tokens than a full sweep.

## Outcome Mode

```
/retro outcome <session-id>          # Specific past session
/retro outcome --since 30d           # All sessions in last 30 days
```

Outcome mode reviews **what happened to the output — good OR bad**, not failures
only. It has two jobs, co-equal:

- **Learn from failure** — output that was reverted, rejected, or broke CI
  (D1–D10) → fix the process so it does not recur.
- **Codify success** — a change that **survived** (merged, unreverted, CI-green;
  **D11**) is a validated statement of "this is the way." Where its approach
  generalizes and isn't in a skill, propagate it so future generated code follows
  it. This is the "every stuck commit is a statement" case: durability, confirmed
  by latency, is what upgrades a commit from hypothesis to codifiable rule.

Steps:

- Skip Phases 1 and 2 (the session is in the past; mechanical pre-pass on a stale transcript is low value)
- Phase 3 runs against the target session(s)
- **Phase 3b is the primary detection step:** walk forward from session end with `git log`, `gh pr view`, `gh run list`, `gh issue list`. Detect Schicht D signals (D1–D11) — both the failures **and** the durable successes.
- Phase 3c may also fire if the window is large
- Phases 4–10 proceed; destinations skew toward `skill-update` — the skill should learn both what to avoid (D1–D10) and what to codify (D11) — and `user-memory` for personal patterns
- Guard D11 with the same generalizability filter as B16–B18: a local, one-off change that merged cleanly is **not** a learning; codifying it is noise

Requires latency. Don't run within 24h of the session — most D signals (including D11's "survived the window") haven't manifested yet.

## Audit Mode

```
/retro audit                         # All sessions, repo + skill scope
/retro audit --scope project         # Project-level only
/retro audit --scope skill           # Skill drift only
```

- Skip Phases 1 and 2
- **Phase 3c is the primary detection step:** ADR adherence, AGENTS.md rule compliance trends, coverage trends, skill-inventory drift
- Output class is "architectural finding", not friction
- Destinations skew toward `project-rule` (new ADR or AGENTS.md update) and `harness-artefact` (enforcement hook)
- Cadence: monthly or quarterly. Tech-lead actor.

## Promote Mode

```
/retro promote                       # cwd-scoped memory store
/retro promote --scope all           # every slug holding a memory/ dir
```

Re-homes already-written local memory (the **stock**, not the session flow)
upward into its correct destination, draining the source once the upward write
is confirmed. Full detail in `skills/retro/references/promote-mode.md`.

- **Phase 1 is substituted** by `skills/retro/scripts/scan-memory-inventory.py` — a
  filesystem inventory of `~/.claude/projects/<slug>/memory/*.md`, not a
  transcript:

  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/scan-memory-inventory.py \
    --scope cwd --output-format json
  ```

- Skip Phases 2, 2b, 3b, 3c (no transcript) — announce the skip in one line
- Phases 4–10 run verbatim; destination skew is **upward** per scope-escalation
  (skill-update › project-rule › user-memory), **never** project-local memory
- Phase 8 adds a mandatory default-**N** warning on every `project-rule` /
  `skill-update` proposal: "promoting this makes it team-visible; source is
  currently private"
- **Phase 9 gains a post-step:** after the upward write is *verified* (rule text
  re-read, or PR URL returned), drain the source via
  `scan-memory-inventory.py drain <path> --expect-sha256 <sha>` — a tombstone
  move to `.promoted/` plus a `MEMORY.md` prune, **never** `rm`. On verify
  failure, keep the source. For `skill-update`, drain only after the PR is opened.
- Phase 10 report gains a **Source drained?** column
  (`tombstoned` / `kept — verify failed` / `kept — source changed`)
- The scanner is read-only; if `--scope cwd` finds nothing, retry `--scope all`
  (the real stock often lives under a sibling slug)
