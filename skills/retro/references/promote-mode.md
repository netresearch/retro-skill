<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Promote Mode — `/retro promote`

Every other retro mode reads the session **flow** (a transcript) and detects
friction as it happens. Promote reads the accumulated **stock**: the
cwd-scoped memory files Claude Code's default memory behaviour writes to
`~/.claude/projects/<slug>/memory/`. It re-homes each note upward to its correct
destination and drains the source — turning the "never project-local memory"
rule from a *going-forward* policy into an action you can run on the backlog.

It is a new **front-end** for the existing pipeline, not a new pipeline: it
replaces Phases 1–3 (transcript detection) with a filesystem inventory and
reuses Phases 4–10 (classify → check mandate → materialize → report).

## Why this mode exists

Project-local memory (`~/.claude/projects/<slug>/memory/`, a project
`CLAUDE.md`, `docs/feedback/`) is a **knowledge silo**: cwd-scoped, shared with
no one, and invisible from any other slug. A note written while `cwd` resolved
to `-home-sme` is never recalled while working in `-home-sme-p-retro-skill`.
Promote drains that silo into the shareable destinations the taxonomy already
defines, in priority order: **canonical-source › skill-update › project-rule
(`AGENTS.md`) › personal-rule (`~/.claude/CLAUDE.md`)** — see the authority axis
and the scope-escalation rule in `classification-heuristic.md`. A note whose
substance is a fact owned outside the agent system (upstream docs, code, a
schema) promotes to that owner; the skill keeps at most a reference plus the
agent-specific delta.

## What the scanner reads (and excludes)

`${CLAUDE_SKILL_DIR}/scripts/scan-memory-inventory.py` scans read-only; only its `drain` subcommand writes. It emits the
same envelope shape as `detect-mechanical.py`, so Phases 4–10 consume it as-is.

| Scanned | Signal | Note |
|---|---|---|
| `<slug>/memory/*.md` (feedback notes) | `C3` memory_drift | The canonical promotable stock |
| `<slug>/memory/MEMORY.md`, one finding per inline unit | `C3` memory_drift, `current_location: project-local-memory-inline` | Read twice: as the index of the note files (pruned on a note drain) and for knowledge written into it directly — see "Inline units in `MEMORY.md`" |
| `<slug>/memory/.promoted/*.md` | — | Tombstones (already drained) — skipped, never re-emitted |
| `<project>/CLAUDE.md`, `docs/feedback/*.md` | `B8` wrong_destination | **Opt-in** via `--include-flagged-locations` |
| `~/.claude/CLAUDE.md`, one finding per `##` section | `C2` cross_project_pattern | **Opt-in** via `--include-global-rules` — see "Draining the global rules file" |

**Excluded by construction** (never part of the scan surface — the scanner only
globs `<slug>/memory/*.md`, so these are never enumerated in the first place):
`~/.claude/CLAUDE.md` unless `--include-global-rules` is passed and
`<project>/AGENTS.md` always (they are correct *destinations* — re-promoting
them by default loops), and `.serena/memories/*.md` (project-overview
context, not behaviour rules — would pollute global memory).

### Draining the global rules file (`--include-global-rules`)

The global rules file is where personal preferences *land*, so it is not a
default source. It still accumulates a second kind of content: learned rules
whose substance is team-usable procedure or domain fact (a CLI gotcha, a
release recipe, an API trap). Those reach more people as a `skill-update` than
as private prose, and this opt-in surfaces each `##` section so the classifier
can judge it. Three binding rules:

1. **Always-on behavior never leaves the file.** A skill loads only when
   triggered. Rules that must hold in every turn — bans, tone rules,
   assumption-marking, verification discipline — are not promotable to a
   skill; at most they *pair* with an enforcement gate (hook/checkpoint) while
   the prose stays. When in doubt, the section stays.
2. **Two-direction test.** Promote a section only when BOTH hold: the content
   generalizes beyond this user, AND losing it from always-loaded context is
   safe because the owning skill reliably triggers when the content matters.
3. **Drain is an agent edit, not the `drain` subcommand.** The subcommand
   refuses paths outside `<slug>/memory/` by design. Only after the destination
   is accepted, available and reliably discoverable when needed, remove the
   section within the authorized scope, re-checking the scan's `content_sha256` against the
   section text first (same race-check semantics). One section per edit.
   Section-removal is markdown surgery and boundary regexes are FENCE-BLIND: a
   `#`-anchored section-heading boundary also matches `#` comment lines inside code
   fences, leaving orphaned section tails (observed live). Remove sections
   fence-aware (track ``` state, or operate on a parsed structure), and verify
   afterwards that fences are balanced and the section count dropped by exactly
   the number removed.

Each finding carries the source note's verbatim `**Why:**` / `**How to apply:**`
prose, its `origin_session_id`, a `current_location` tag (the load-bearing
evidence the LLM reads at Phase 5), and a `content_sha256` used as both an
idempotency key and a drain race-check.

### Inline units in `MEMORY.md`

Older stores hold their knowledge as text inside `MEMORY.md` itself — `##`
sections with bullets and code fences — and have no note files. Reading
`MEMORY.md` only as an index reported those stores as empty, so their content
was never re-homed. The scanner therefore also splits `MEMORY.md` into units:

- each `##` section (a later `#` heading opens one too; a `###` stays inside its
  section), and the text before the first heading other than a leading `#`
  title, reported as `preamble`. Headings are found fence-aware: a `#` line
  inside a ``` or `~~~` fence is a comment, not a boundary;
- a line that links to a note file **present in the store** — at its start or
  mid-sentence, as in "See [x](x.md) for … · Handoff …" — is that note's index
  entry: it is left out of the unit, so an inline drain never takes the only
  pointer to a live note or its pending handoff. Only a note drain prunes it,
  and the prose it keeps becomes unit content on the next scan. A link to a
  note that no longer exists is content — its hook text is the last copy of
  what the note said. Only a plain `[text](name.md)` link outside a code fence
  counts: `./name.md`, `name.md#part`, a titled or reference-style link reads
  as content, and a code fence left open to the end of the file swallows every
  later heading. Check such a store by hand before draining it;
- a unit with nothing left once index entries are removed is not emitted.

An inline finding carries `content` (the unit's text: heading plus its other
lines), `inline_unit` (the heading line or `preamble`), `inline_ordinal`, and a
`content_sha256` over the unit's heading and its non-index lines as they stand
in the file. `content` is that text
with secrets masked, so the two differ only where something was masked; the
drain hashes the file, not the scan output. Since the text sits in the file
every session loads, any pending-state phrase in it sets
`pending_state_in_index`.

### Scope

`--project` with a leading-dash slug needs the equals form (`--project=-home-user-projects`) — argparse consumes the bare form as an option and errors "expected one argument".

By default the scanner enumerates **every** slug that has a `memory/` dir;
`--project=<slug>` narrows it to one. There is no `--scope` flag and there never
was — earlier versions of this page and of the command documented `--scope
cwd|all`, which the script rejects with exit 2, so every documented promote run
died at argument parsing. The scanner **always** reports `slugs_scanned`, so an
empty result reads as "scanned X, found nothing" rather than a silent skip; that
guards the worktree-vs-parent slug split, since the real stock often lives
under a sibling slug. Narrow with `--project=` only when you know which slug
holds it.

## Batch semantics — a proposal absorbs notes, the cap counts proposals

A backlog drain meets hundreds of notes; per-note proposals under the ≤10 cap
would spread one drain across dozens of sessions. In promote mode a **proposal
is destination-shaped, not note-shaped**: one proposal = one materialization
target (one skill PR, one AGENTS.md append), absorbing every scanned note that
classifies to it. Rules:

- The proposal lists every absorbed note by path, with its `content_sha256`.
  Check existing authorization for that set, target, action and audience;
  request approval only for uncovered decisions. The user can strike
  individual notes from the list.
- One proposal counts once against the ≤10 cap regardless of how many notes it
  absorbs.
- The mechanical halves of a materialization repeat identically per proposal —
  use `${CLAUDE_SKILL_DIR}/scripts/materialize-pr.sh` (`start` = fetch + fresh worktree off the
  default branch; `finish` = stage ONLY named files, signed commit, push, PR
  via `--body-file`) instead of hand-typing the sequence dozens of times.
- Drain stays per-note: each absorbed note is drained individually only after
  the availability check below, so pending or partially-landed proposals leave
  their active knowledge and handoff reference in place.

### Classifying a large backlog

Past roughly fifty notes, reading every note and every candidate target in the
main context does not fit. What worked on a 190-note store:

1. Split the inventory into topic buckets of 20–60 notes (one forge, one
   tracker, the skill fleet, one product family, general behaviour rules), so
   each bucket has two to five candidate target skills.
2. Give each bucket to a read-only classifier agent with the bucket's file list
   and `content_sha256` values. It fetches each candidate skill repo and greps
   its `origin/main` (never the installed copy), checks the global rules file,
   and returns one verdict per note — covered, partial, new, stale, historical
   — with a `file:line` it actually saw. Run at most three at a time.
3. Build the destination-shaped proposals from the merged verdict tables, and
   keep the tables in a durable file next to the proposals.
4. Materialize one agent per target repository, again read-only except for its
   own worktree. Read back its PR or MR URL, record the handoff, and drain each
   note only after the destination's availability is verified.

The classifier verdicts are claims. Before a correction ("the skill says X,
which is false") reaches the user, re-check its `file:line` yourself.

## Verify before promoting — stale facts, paraphrase duplicates, generalization

Three checks run at Phase 7, before a note enters a proposal:

- **Stale-check.** Every note records what was true when written — not only
  `reference` notes. Verify its load-bearing claim against reality before it
  enters a proposal, and know which of two kinds of claim it makes:
  - **Existence** — a path, flag, endpoint or version. Check that it still
    exists.
  - **State** — something is still open, not yet done, unreleased, waiting on
    someone. This kind turns false the moment the thing happens, without a
    word of the note changing, and an existence check passes it. The scanner
    marks these in English and German (`noch nicht`, `steht aus`, `noch
    offen`, …): `pending_state` lists the phrases, and
    `pending_state_in_index` is true when one sits in the description.

    The flag is a reason to look, not a verdict. It skips `feedback` notes,
    because a rule speaks in conditionals and "still open" inside a rule is
    not a claim that something is open now. And it deliberately does not
    match `blocked`: on a real store that word never once marked a pending
    claim — it named merge states, status enums and resolver behaviour.

  Check the **description first**. It is the line `MEMORY.md` carries, loaded
  into every session, while the body is read only on demand — so a stale state
  in the description misleads each session and a stale state in the body only
  whoever opens it. The note that prompted this was accurate on the day it was
  written, resolved the next day, and stood in the index for a week reading
  "all wait on one unreleased repo"; its body stayed historically correct
  throughout. A stale note is proposed for **tombstone-only drain** (no upward
  write), clearly labeled — or, where part of it is still true, for a rewrite
  that keeps only that part.
- **Paraphrase dedup.** `content_sha256` catches identical text, not the same
  rule reworded — and stock notes are often already duplicated into
  `~/.claude/CLAUDE.md` or the target skill. Read the *target* location and
  compare mechanisms (not titles): if the target already covers the same
  mechanism, the note is proposed for tombstone-only drain with the covering
  location and its availability for intended readers verified; if the target
  covers an adjacent mechanism only, promote and say what is genuinely new.
  This is the same read-the-target rule as
  "Instruction pruning" in `classification-heuristic.md`.
- **Generalization check.** A note records a command that ran once, in one
  context, for the person who wrote it. Promoted, the same lines become a
  recipe for every reader of the target, and the context that made them safe
  or sufficient is gone. Before a command block or a step list enters a
  proposal, read it as a reader who has only the target text and ask three
  questions:
  - **Does it complete the action?** Where the note's purpose is a change, a
    block that ends at `--dry-run`, a `--check`, a preview or a "then do the
    same for real" leaves the reader with nothing done. Write out the step
    that changes state. A note whose purpose is the preview itself stays a
    preview.
  - **Are its defaults safe for anyone who copies it?** Host-key handling
    (`StrictHostKeyChecking=accept-new`, an unchecked `known_hosts`), a
    forwarded SSH agent or a mounted credential, a disabled TLS check, a
    secret on the command line: each was the writer's own trade-off on their
    own machine. Replace it with the safe form, or state the condition under
    which the shortcut is acceptable.
  - **Which condition of the original context is missing?** The version, the
    host, the setting that was already in place, the reason a step could be
    skipped. Name it in the text, or narrow the claim to where it holds.

  The 2026-11-04 promote run of 136 notes opened 31 documentation PRs. Their
  bot reviews raised 48 threads, nine of them graded major. Neither the
  stale-check nor the author's own review had caught them. Among them: an
  accept-new host key and a forwarded SSH agent in one deploy recipe, a block
  that ended at `--dry-run`, and an HTTP-only setup that kept the backend's
  `lockSSL`. Every one was a statement that had been true for the writer and
  was incomplete for the reader.

## Materialize, verify availability, then drain (Phase 9)

Retiring the active source is **last**, per item. Use the existing Learning-Id
and proposal/PR to track the states in `patch-workflow.md`; do not create a
competing permanent learning store.

1. **Write/PR first** — append the titled rule to `~/.claude/CLAUDE.md` or
   `<project>/AGENTS.md`, write the team record, or open the `feat/retro-<slug>`
   PR with a signed (`git commit -s`) commit.
2. **Read back and retain the bridge** — confirm the target text or PR exists.
   A PR URL proves preparation, not acceptance or availability. While pending,
   leave the source note and its existing `MEMORY.md` entry active; add a short
   handoff reference there if authorized: Learning-Id, target URL, pending state
   and the condition for retiring it. The note still supplies the needed
   knowledge when the next session reads that entry. A link only inside
   `.promoted/` is not an active bridge. If changing the note, re-scan and use
   its new `content_sha256` for any later drain.
3. **Verify availability** — a file or team record must contain the intended
   content and be accessible from the intended reader's normal entry point.
   A PR-based target must be accepted and delivered where those readers get
   it: for a skill, check the relevant distribution/installed version and
   discovery route, not only `main`. Unknown delivery remains pending. An
   open, rejected, closed-unmerged or not-yet-distributed PR never passes this
   check. Record evidence of availability; later application and benefit are
   separate checks and do not delay this handoff.
4. **Drain only now** — `scan-memory-inventory.py drain <path> --expect-sha256 <sha>`
   tombstone-**moves** the source into `<slug>/memory/.promoted/` (never `rm`)
   and prunes its `MEMORY.md` entry: only the link to the note goes, with its
   own hook text and one ` · ` separator. The bullet marker, a leading label,
   sibling links and rule text outside the link stay; the line goes only when
   nothing but the marker and a label remains. The `--expect-sha256`
   race-check aborts the drain if the file changed since the scan.

   An inline unit drains with `scan-memory-inventory.py drain
   <slug>/memory/MEMORY.md --expect-sha256 <its content_sha256>`. The hash is
   required and selects the unit; when no unit has it any more, the text
   changed and nothing moves. The unit is appended to
   `.promoted/MEMORY-inline-<YYYY-MM-DD>.md` under a
   `<!-- retro promote drain: sha256=… -->` line, then removed from
   `MEMORY.md`; index entries inside it stay, with their heading. Everything
   else in `MEMORY.md` is left byte-identical. The tombstone is written before
   `MEMORY.md` is replaced, so a failure in between leaves the text in both
   places, and a retry that finds the complete block already in a tombstone
   does not append it twice (a hash line in front of a partial copy does not
   count). The unchanged-check sits directly before the replace, so a memory
   another session saves during the drain is kept: the drain re-reads and
   retries. A note drain can change an
   inline unit's hash (the prose its pruned index line keeps joins the unit),
   so re-scan before an inline drain that follows a note drain; a stale hash
   is refused, not misapplied. When a section holds both a live note's index
   entry and inline text, drain the note first, re-scan, then the inline unit:
   in the other order the note drain leaves an empty heading behind, which no
   later scan reports. A bare `drain MEMORY.md`
   without a hash is refused: it would tombstone the whole index. Do not leave
   a pointer sentence ("moved to `.promoted/`") in `MEMORY.md` — the scanner
   reads such a sentence as a preamble unit on every later run.

On any verification failure, **keep the active source** and report it. For a
rejected or closed PR, update the handoff state and re-evaluate the learning:
revise its route or scope, retain a still-valid instruction, or retire a
disproved/stale note with the reason. Rejected proposals are never drained
merely because a PR once existed. After confirmed delivery, remove the
transition reference with the final drain. The low-level `drain` command checks
path and hash, not remote delivery; the agent performs and records that gate
before invoking it.

**A memory store that is itself versioned needs a sync after the drain.** When
the store is backed up in a dotfiles repository, the drained notes still sit in
that repository. An installer that copies the repository back onto the machine
then restores every drained note, and a capture that copies only tracked files
from the machine neither removes them nor picks up the new tombstones. After
the drain, mirror the store's directory into the repository — note removals
and new `.promoted/` files included — and commit it before anyone runs the
installer. Git records each drained note as a rename into `.promoted/`.

## Risk controls

1. **Naming.** `promote` names exactly what Phases 7–9 do (re-home upward by
   reach) and fits the `/retro <verb>` convention. (`dream` / `upsert` rejected.)
2. **Team-visibility of personal notes.** Two layers: (a) at Phase 5, personal
   content (a `$HOME` path, an "I prefer…" style note) is **not** auto-escalated
   past personal-rule; (b) at Phase 8, every `project-rule` / `skill-update` /
   team-record `canonical-source` proposal states exactly where it becomes
   team-visible and that the source is currently private. Existing explicit
   authorization must cover this audience and content; otherwise ask before
   disclosure. Promotion and its paired drain are one authorization unit.
3. **Deletion timing / data loss.** Strict write → verify availability → drain ordering;
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
- `references/destination-taxonomy.md` — the seven destinations
- `references/workflow.md` — the other modes
- `docs/specs/retro-promote-mode.md` — historical implementation proposal; this
  reference defines the current availability and authorization gates
