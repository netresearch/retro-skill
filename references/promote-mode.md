# Promote Mode — `/retro promote`

Every other retro mode reads the session **flow** (a transcript) and detects
friction as it happens. Promote reads the accumulated **stock**: the
cwd-scoped memory files Claude Code's default memory behaviour writes to
`~/.claude/projects/<slug>/memory/`. It re-homes each note upward to its correct
destination and drains the source — turning the "never project-local memory"
rule from a *going-forward* policy into an action you can run on the backlog.

It is a new **front-end** for the existing pipeline, not a new pipeline: it
replaces Phases 1–3 (transcript detection) with a filesystem inventory and
reuses Phases 4–10 (classify → approve → materialize → report) unchanged.

## Why this mode exists

Project-local memory (`~/.claude/projects/<slug>/memory/`, a project
`CLAUDE.md`, `docs/feedback/`) is a **knowledge silo**: cwd-scoped, shared with
no one, and invisible from any other slug. A note written while `cwd` resolved
to `-home-sme` is never recalled while working in `-home-sme-p-retro-skill`.
Promote drains that silo into the shareable destinations the taxonomy already
defines, in priority order: **skill-update › project-rule (`AGENTS.md`) ›
user-memory (`~/.claude/CLAUDE.md`)** — see the scope-escalation rule in
`classification-heuristic.md`.

## What the scanner reads (and excludes)

`scripts/scan-memory-inventory.py` is read-only by construction. It emits the
same envelope shape as `detect-mechanical.py`, so Phases 4–10 consume it as-is.

| Scanned | Signal | Note |
|---|---|---|
| `<slug>/memory/*.md` (feedback notes) | `C3` memory_drift | The canonical promotable stock |
| `<slug>/memory/MEMORY.md` | — | Read as the index; pruned on drain, never itself a finding |
| `<slug>/memory/.promoted/*.md` | — | Tombstones (already drained) — skipped, never re-emitted |
| `<project>/CLAUDE.md`, `docs/feedback/*.md` | `B8` wrong_destination | **Opt-in** via `--include-flagged-locations` |

**Excluded by construction** (never part of the scan surface — the scanner only
globs `<slug>/memory/*.md`, so these are never enumerated in the first place):
`~/.claude/CLAUDE.md` and `<project>/AGENTS.md` (correct *destinations*, not
sources — re-promoting them loops), and `.serena/memories/*.md` (project-overview
context, not behaviour rules — would pollute global memory).

Each finding carries the source note's verbatim `**Why:**` / `**How to apply:**`
prose, its `origin_session_id`, a `current_location` tag (the load-bearing
evidence the LLM reads at Phase 4), and a `content_sha256` used as both an
idempotency key and a drain race-check.

### Scope

`--scope cwd` (default) scans only the slug derived from the cwd; `--scope all`
enumerates every slug that has a `memory/` dir. The scanner **always** reports
`slugs_scanned` so an empty result reads as "scanned X, found nothing" rather
than a silent skip — this guards the worktree-vs-parent slug split (the real
stock often lives under a sibling slug). If `cwd` finds nothing, re-run with
`--scope all`.

## Materialize-then-drain (Phase 9)

Source deletion is **last** and **gated on confirmed materialization**, per item:

1. **Write/PR first** — append the titled rule to `~/.claude/CLAUDE.md` or
   `<project>/AGENTS.md`, or open the `feat/retro-<slug>` PR with a signed
   (`git commit -s`) commit.
2. **Verify** — for file appends, re-read the target and confirm the rule text
   is present; for PRs, confirm `gh`/`glab` returned a URL (PR *exists* =
   materialized; merge is not required).
3. **Drain only now** — `scan-memory-inventory.py drain <path> --expect-sha256 <sha>`
   tombstone-**moves** the source into `<slug>/memory/.promoted/` (never `rm`)
   and prunes its `MEMORY.md` bullet. The `--expect-sha256` race-check aborts
   the drain if the file changed since the scan.

On any verification failure, **keep the source** and report it. Rejected
proposals are never drained.

## Risk controls

1. **Naming.** `promote` names exactly what Phases 7–9 do (re-home upward by
   reach) and fits the `/retro <verb>` convention. (`dream` / `upsert` rejected.)
2. **Team-visibility of personal notes.** Two layers: (a) at Phase 4, personal
   content (a `$HOME` path, an "I prefer…" style note) is **not** auto-escalated
   past user-memory; (b) at Phase 8, every `project-rule` / `skill-update`
   proposal triggers a mandatory, default-**N** warning stating exactly where it
   becomes team-visible and that the source is currently private. The promotion
   and its paired drain are one approval unit.
3. **Deletion timing / data loss.** Strict write → verify → drain ordering;
   drain is a reversible tombstone move, never `rm`; no verified success → no
   drain, ever; sha256 race-check guards concurrent edits.
4. **Not everything should escalate.** Store-class discrimination keeps the
   scanner to genuine silos; correct destinations and Serena context are never
   emitted; the `drain` subcommand refuses any path not under a `<slug>/memory/`
   store, so a drained note can't be re-filed downward.
5. **Separation from `audit`.** Clean seam by input and output: `audit` reads
   cross-session transcripts/git history over weeks and skews to ADR/harness
   destinations; `promote` reads the filesystem stock of memory files (no
   transcript, no time window) and skews to user/project/skill destinations.

## See also

- `references/classification-heuristic.md` — the C3/B8 routing and scope-escalation
- `references/destination-taxonomy.md` — the six destinations
- `references/workflow.md` — the other modes
- `docs/specs/retro-promote-mode.md` — full spec
