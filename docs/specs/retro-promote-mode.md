# Spec: `/retro promote` — Memory-Store Promotion Mode

| | |
|---|---|
| **Status** | Draft (for review) |
| **Implementation Repo** | `netresearch/retro-skill` |
| **Depends on** | Existing `/retro` pipeline (Phases 4–10), `classification-heuristic.md` |
| **Author** | Sebastian Mendel |
| **Date** | 2026-06-08 |

## Objective

Add a `/retro promote` mode that inventories already-written, cwd-scoped memory
stores (the accumulated **stock**) and re-homes each note upward to its correct
destination — `skill-update › project-rule › user-memory`, never project-local
memory — draining the source only after the upward write is confirmed. It makes
the taxonomy's existing "never project-local memory" stance actionable on the
backlog, not merely enforced going forward.

## Anlass (Why Now)

The other modes detect friction in the session **flow** (a transcript). None of
them act on the **stock** of memory files Claude Code's default memory behaviour
silently accumulates under `~/.claude/projects/<slug>/memory/`. That stock is a
knowledge silo: cwd-scoped, shared with no one, invisible from other slugs.

Verified on this machine (2026-06-08): the slug `-home-sme` holds 3 feedback
notes + `MEMORY.md`, while this worktree's slug `-home-sme-p-retro-skill` has no
`memory/` dir at all — so the knowledge is real but unreachable from where the
work happens. retro is currently blind to it.

## Scope

| | |
|---|---|
| **NEW** | `skills/retro/scripts/scan-memory-inventory.py` (read-only scan + `drain` subcommand), `tests/test_scan_memory_inventory.py`, `skills/retro/references/promote-mode.md` |
| **EDIT (small)** | `commands/retro.md` (mode section), `skills/retro/references/classification-heuristic.md` (C3 row), `skills/retro/references/destination-taxonomy.md` (forward pointer), `.github/workflows/lint.yml` (compile check), `skills/retro/SKILL.md` (terse mode stub — see Precondition) |
| **NO CHANGE** | `.claude-plugin/plugin.json` (declares only skills; commands are convention-discovered), the six destinations (promote invents none) |
| **OUT** | Tombstone-purge housekeeping, `.serena/memories` ingestion, external-feedback ingestion |

## Mode Definition

```
/retro promote [--scope cwd|all]
```

A new front-end that replaces Phases 1–3 (transcript detection) with a
filesystem inventory and reuses Phases 4–10 unchanged.

### Scan script — `skills/retro/scripts/scan-memory-inventory.py`

Read-only by construction; stdlib-only; emits the `detect-mechanical.py`
envelope so Phases 4–10 consume it as-is.

```
python3 scan-memory-inventory.py [--scope cwd|all] [--project SLUG] \
    [--memory-root PATH] [--cwd PATH] [--include-flagged-locations] \
    [--output-format json|text]
python3 scan-memory-inventory.py drain PATH [--memory-root PATH] [--expect-sha256 HEX]
```

| Scanned | Signal | Note |
|---|---|---|
| `<slug>/memory/*.md` | `C3` memory_drift | Canonical promotable stock |
| `<slug>/memory/MEMORY.md` | — | Index; pruned on drain, never a finding |
| `<slug>/memory/.promoted/*.md` | — | Tombstones — skipped (idempotency) |
| `<project>/CLAUDE.md`, `docs/feedback/*.md` | `B8` wrong_destination | Opt-in `--include-flagged-locations` |

**Excluded by construction** (never enumerated — the scanner only globs
`<slug>/memory/*.md`): `~/.claude/CLAUDE.md`, `<project>/AGENTS.md` (correct
destinations, not sources), `.serena/memories/*.md` (project context, not rules).

**Finding fields:** `signal`, `name`, `source_path`, `source_slug`, `index_path`,
`content_sha256` (idempotency + drain race-check), `title`, `description`, `why`,
`how_to_apply`, `origin_session_id`, `current_location`.

**Exit codes:** `0` success / graceful-absence / successful drain; `2` bad or
refused `drain` (path not under a `<slug>/memory/` store, or sha mismatch).

### Pipeline

| Phase | Promote behaviour |
|---|---|
| 1 | **Substituted** by `scan-memory-inventory.py` (one invocation) |
| 2, 2b, 3b, 3c | **Skipped** (no transcript) — announced in one line |
| 4 Classify | Unchanged; route C3/B8 + `current_location` via scope-escalation; personal content not auto-escalated past user-memory |
| 5–7 | Unchanged (discovery, eval, proposal — reuse the note's verbatim Why/How) |
| 8 Approval | Unchanged + mandatory default-**N** team-visibility warning on every project-rule / skill-update proposal |
| 9 Materialize | Unchanged + **materialize-then-drain** post-step (below) |
| 10 Report | Unchanged + **Source drained?** column |

### Materialize-then-drain (Phase 9, per item, deletion last)

1. **Write/PR** the upward destination (signed commit for PRs).
2. **Verify** — re-read confirms rule text, or `gh`/`glab` returned a PR URL
   (PR exists = materialized; merge not required).
3. **Drain** via `drain <path> --expect-sha256 <sha>`: tombstone-move to
   `.promoted/` + prune `MEMORY.md`. **Never `rm`.** Race-check aborts on change.

No verified success → no drain. Rejected proposals → never drained.

## Risk Controls

| Risk | Control |
|---|---|
| Opaque naming | `promote` = what Phases 7–9 do; fits `/retro <verb>` (`dream`/`upsert` rejected) |
| Personal note → team-visible | Phase 4 no auto-escalate past user-memory; Phase 8 default-N visibility warning |
| Deletion / data loss | write → verify → drain; reversible tombstone, never `rm`; sha race-check |
| Over-escalation | Store-class discrimination; destinations + Serena excluded; drain refuses non-`memory/` paths |
| Blur with `audit` | Distinct input (filesystem stock vs cross-session transcripts) and destination skew |

## Precondition (gate-blocking)

`skills/retro/SKILL.md` already **fails** `validate-skill` (v1.22.0) on `main`,
independently of this work:

- `SKILL.md is 1145 words (max 500)` — 2.3× over the hard cap.
- `Description must start with 'Use when'`.

Adding even a terse promote stub cannot ship green without also resolving these.
Because that touches authored prose and is a pre-existing failure, it is tracked
as an explicit decision rather than folded in silently (see Open Questions Q1).

## Verification Plan

| Step | How |
|---|---|
| Scan emits C3 finding from a feedback file | unit test (positive) |
| `MEMORY.md` / tombstones not emitted | unit tests (negative) |
| Missing root → graceful absence (`available:false`, rc 0) | unit test |
| German umlauts round-trip (`ensure_ascii=False`) | unit test |
| `--include-flagged-locations` emits B8 | unit test |
| `drain` refuses non-`memory/` path and sha mismatch | unit tests |
| `drain` tombstones + prunes index | unit test |
| Script compiles in CI | `lint.yml` py_compile line |
| Real-stock smoke | `--scope all` finds the `-home-sme` notes |

## Open Questions

| ID | Question | Recommendation |
|---|---|---|
| Q1 | SKILL.md is already over the 500-word cap + wrong description prefix. Fix in this change, a separate prep PR, or leave the stub out for now? | Separate prep PR that trims SKILL.md to a terse index and fixes the description; rebase this mode on top. Keeps this change reviewable and doesn't bundle a 700-word prose rewrite with a feature. |
| Q2 | `--scope` default: `cwd` or `all`? | Keep `cwd` for least-surprise, but always print `slugs_scanned` and document the `--scope all` fallback (the real stock often sits under a sibling slug). |
| Q3 | Signal id: reuse `C3`/`B8` or add a dedicated promote id? | Reuse — both already route correctly; a new id costs edits to two word-sensitive reference files for no routing benefit. |
| Q4 | Tombstone retention: purge `.promoted/` after PRs merge, or keep as an audit trail? | Keep indefinitely for now; a purge step is a separate roadmap item. |

## Out of Scope

- Tombstone-purge housekeeping; `.serena/memories` ingestion; external-feedback
  ingestion; auto-merge of promote PRs; marketplace automation.
