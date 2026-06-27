# retro — session retrospectives for Claude Code

**LLM-driven session retrospection for Claude Code agents.** After a session, `/retro` reads the conversation transcript, detects friction, and routes each finding to one of six homes — with per-proposal approval and no silent writes.

[![License: MIT AND CC-BY-SA-4.0](https://img.shields.io/badge/License-MIT%20AND%20CC--BY--SA--4.0-blue.svg)](LICENSE-MIT)
[![lint](https://github.com/netresearch/retro-skill/actions/workflows/lint.yml/badge.svg)](https://github.com/netresearch/retro-skill/actions/workflows/lint.yml)
![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-555.svg)

> Where continuous friction-detection hooks pile up write-only noise nobody triages, `/retro` reads what actually happened and hands you a short list of approved, durable learnings — global memory, project rules, or skill PRs.

## Contents

- [What it does](#what-it-does)
- [Why](#why)
- [Requirements](#requirements)
- [Install](#install)
- [Usage — the four modes](#usage--the-four-modes)
- [A worked example](#a-worked-example)
- [The six destinations](#the-six-destinations)
- [How it works](#how-it-works)
- [How it stays safe](#how-it-stays-safe)
- [Honest limitations](#honest-limitations)
- [Optional auto-trigger](#optional-auto-trigger)
- [Repository layout](#repository-layout)
- [Related projects](#related-projects)
- [Contributing](#contributing)
- [License](#license)

## What it does

`/retro` analyzes the current Claude Code session directly from the conversation transcript — no continuous background hooks. It detects friction (tool errors, repeated mistakes, skills that should have triggered but didn't, convention violations), classifies each finding into exactly one of six destinations, and materializes the approved learnings. Every write is gated behind explicit per-proposal approval.

A single sweep returns at most ten actionable proposals, grouped by destination, each with a short *why* and a *how-to-apply*.

## Why

The prior approach — the Coach plugin — used continuous friction-detection hooks that turned out to be write-only noise. The field evidence was stark:

- `~/.claude-coach/candidates.json` held **1011 pending / 0 approved / 0 rejected**.
- A **35 MB** `events.sqlite` produced roughly **35× duplicate fingerprints** of the same issue.

An LLM reading the *actual* transcript classifies friction more accurately and far more cheaply, and returns **≤10** actionable proposals instead of 1011 candidates nobody triages. That is the entire premise of `/retro`: one efficient pass over what really happened, not a firehose of background candidates.

## Requirements

| Tool | Used for |
|---|---|
| Claude Code | The host that runs the plugin and the `/retro` command |
| `python3` | Mechanical pre-pass and the cross-session scan |
| `jq` | Skill discovery, manifest parsing, and the optional hook |
| `gh` and/or `glab` | Creating pull/merge requests for skill updates |
| `git` | Cloning source repos and materializing changes |

## Install

`/retro` ships as a Claude Code plugin. A bare single-plugin repo can be added to the marketplace directly — no `marketplace.json` required. Run both steps inside Claude Code:

```text
/plugin marketplace add netresearch/retro-skill
/plugin install retro@netresearch/retro-skill
```

Alternatively, install via Composer (the skill-repo convention):

```bash
composer require netresearch/retro-skill
```

## Usage — the four modes

| Command | Mode | When to use |
|---|---|---|
| `/retro` | **Sweep** — analyze the entire current session; returns ≤10 proposals grouped by destination | At session end, or when friction has accumulated |
| `/retro "<problem>"` | **Spotlight** — focus on one described issue; fewer tokens than a full sweep | Mid-session, for a direct fix |
| `/retro outcome [session-id\|--since N]` | **Outcome** (layer D) — replay a *past* session through what happened to its output afterwards (reverted commits, rejected PRs, CI failures, follow-up fix sessions) | Periodically, e.g. monthly. **Do not run within 24h of the session** — the outcomes have not landed yet |
| `/retro audit [--scope project\|repo\|skill]` | **Constitutional audit** — cross-session architectural review (design drift, convention erosion) over weeks/months | Monthly or quarterly health check |
| `/retro promote` | **Promote** — inventory accumulated project-local memory (all slugs) and re-home each note upward (skill-update › project-rule › user-memory; never project-local memory), draining the source only after the upward write is verified | When local memory has piled up and you want it shared and emptied |

Sweep and Spotlight answer *"what went wrong this session?"*. Outcome and Audit answer *"did our past decisions survive contact with reality?"* and *"is the system still on track?"* — friction that does not show up inside a single session.

## A worked example

The following is an **illustrative example** of a Sweep, not a captured transcript — your output will differ.

```text
> /retro

Analyzed session (4200 words). Mechanical pre-pass + LLM enrichment found 3 findings.

[skill-update] git-workflow — DCO sign-off missing
  Why:  Two commits this session were rejected by the DCO check; the skill
        never mentions `git commit -s`.
  How:  PR to the git-workflow SOURCE repo adding a sign-off rule + eval stub.

[project-rule] AGENTS.md — use bun, not npm
  Why:  You corrected the assistant twice ("we use bun here").
  How:  Append a titled rule to <project>/AGENTS.md.

[user-memory] CLAUDE.md — always fetch before reasoning about origin/<branch>
  Why:  A stale ref caused a rejected push, then a forced retry.
  How:  Append a titled rule to ~/.claude/CLAUDE.md.

Approve / edit / reject each? [1] a  [2] e  [3] r
> ...

Report
  PRs opened:   1  (git-workflow: feat: require DCO sign-off)
  Files written: 2 (<project>/AGENTS.md, ~/.claude/CLAUDE.md)
```

Each finding is one approval decision. Nothing is written, no PR is opened, until you say so.

## The six destinations

Every finding routes to exactly one destination:

| Destination | When | Materializes to |
|---|---|---|
| `user-memory` | A personal, cross-project preference | Append a titled rule to `~/.claude/CLAUDE.md` (the always-loaded global rules file) |
| `project-rule` | A convention for *this* project | Append a titled rule to `<project>/AGENTS.md` |
| `skill-update` | An existing skill is wrong, weak, under-triggering, or carries an obsolete instruction (removal is a valid edit) | Open a PR against the skill's **source repo** (never the plugin cache) |
| `new-skill` | A skill-shaped gap no skill covers | Scaffold a brand-new skill repo via the `skill-repo` convention |
| `checkpoint` | A mechanical check worth gating on | Add a YAML entry to the target skill's `checkpoints.yaml` |
| `harness-artefact` | A repo-infrastructure gap | Bootstrap a hook / CI / template via `agent-harness` |

## How it works

The pipeline is built in layers (the project calls them *Schicht* A/B/C/D — layer A/B/C/D). The deterministic layer runs first to cut token cost; the LLM is always the primary classifier.

1. **Mechanical pre-pass (layer A)** — `skills/retro/scripts/detect-mechanical.py` parses the transcript for exactly **18** deterministic signals (A1–A18): tool errors, retry clusters, output verbosity, tool-call inefficiency, sequential-vs-parallel, user-correction phrases, prompt/prompt-sequence/tool-sequence repetition, skill-reminder-vs-invoke, wrong-tool choice, re-read-same-file, skipped verification, work on `main`/`master`, bot attribution in commits, outdated-tool warnings, upstream failure, and permission re-approval. Deterministic; it does **not** classify.
2. **LLM enrichment (layer B)** — adds **14** inferential signals (wrong skill choice, skill capability gap, hallucination, convention violation, missing skill, repeated mistake, assumption-without-asking, doc drift, …) and filters layer-A false positives. Includes a trigger-coverage sweep over every installed skill's description.
3. **Cross-session enrichment (layer C, optional)** — if `~/.claude-coach/events.sqlite` exists, query it; otherwise scan `~/.claude/projects/<slug>/*.jsonl`. **5** signals: same-friction-again, cross-project pattern, memory drift, ineffective skill update, follow-up-fix session.
4. **Classification** — map each finding to one of the six destinations (`skills/retro/references/classification-heuristic.md`).
5. **Skill discovery (runtime)** — `skills/retro/scripts/find-installed-skills.sh` matches the friction topic against each `SKILL.md` description and resolves the source-repo URL.
6. **Eval consultation** — if the matched skill has an `evals/` directory, read it for context and propose an eval stub (TDD style). retro ships its **own** evals under `skills/retro/evals/` testing its classification, validated by `skills/retro/scripts/validate-evals.py`.
7. **Proposal generation** — per finding: a *Why* paragraph and a *How-to-apply* paragraph, grouped by destination, ≤10 items.
8. **Per-proposal approval** — approve / edit / reject, one decision per materialization.
9. **Materialization** — per-destination convention. PRs use Conventional Commits with DCO sign-off (`git commit -s`; without it the PR is **BLOCKED** even when all checks pass), preserve GPG signing, and require per-private-repo confirmation.
10. **Report** — a summary table of created PRs and written files.

The full signal catalog lives in [`skills/retro/references/friction-catalog.md`](skills/retro/references/friction-catalog.md).

## How it stays safe

- **No silent writes.** Every materialization needs explicit, per-proposal approval.
- **Patches target the source repo, never the cache.** `~/.claude/plugins/cache/` is overwritten on every plugin update; edits there would be lost. `/retro` clones the source repo (or uses an existing worktree) and opens a PR via `gh` / `glab`.
- **The LLM classifies; the pre-pass only saves tokens.** The deterministic layer A never decides a destination.
- **Never:** auto-merge; AI/bot attribution in commits or PRs; `--no-verify`; patching the cache; hardcoding a static skill list; generating 1000+ candidates.

## Honest limitations

`/retro` detects friction **observable in or near the session**. It does **not** detect:

- **Silent badness** — choices that "work" but are wrong and generate no friction signal.
- **External signals** — customer complaints, production alerts, Slack/Jira/Sentry feedback.
- **Constitutional drift over time** *without* `audit` mode — per-session retro can't see slow erosion.
- **Outcomes the agent never saw** — unless work was reverted, a PR rejected, or a follow-up session occurred.

For the last two, use `/retro outcome` (post-hoc) or `/retro audit` (cross-session). External-feedback ingestion is a **future direction**, not a shipped feature.

## Optional auto-trigger

There is an opt-in `SessionEnd` hook (`hooks/session-end.json`) that **only prints a reminder** for sessions over 1000 words — it never auto-runs `/retro`:

```text
Session was non-trivial (4200 words). Run /retro to extract learnings.
```

It is **off by default**. Claude Code does **not** load hooks from a `~/.claude/hooks/` directory — hooks are read only from `settings.json`. To enable the reminder, copy the `hooks` object out of `hooks/session-end.json` and **merge** it into `~/.claude/settings.json` (all projects) or `.claude/settings.json` (one project):

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'tp=$(jq -r \".transcript_path // empty\" 2>/dev/null); [ -z \"$tp\" ] || [ ! -r \"$tp\" ] && exit 0; tokens=$(wc -w < \"$tp\" 2>/dev/null || echo 0); if [ \"${tokens:-0}\" -gt 1000 ]; then printf \"Session was non-trivial (%s words). Run /retro to extract learnings.\\n\" \"$tokens\"; fi'"
          }
        ]
      }
    ]
  }
}
```

Do not rename the file to `hooks/hooks.json` — that would make Claude Code auto-load it and break the off-by-default contract.

## Repository layout

```text
retro-skill/
├── skills/retro/                     # the self-contained skill subtree (ships via npx-skills)
│   ├── SKILL.md                  # main skill definition (the four modes)
│   ├── checkpoints.yaml          # skill quality gates
│   ├── references/               # 7 reference docs
│   │   ├── friction-catalog.md
│   │   ├── destination-taxonomy.md
│   │   ├── classification-heuristic.md
│   │   ├── skill-discovery.md
│   │   ├── patch-workflow.md
│   │   ├── eval-integration.md
│   │   └── workflow.md
│   ├── evals/                    # retro's own classification evals (dogfood)
│   │   ├── README.md
│   │   └── *.md                  # validated by skills/retro/scripts/validate-evals.py
│   └── scripts/
│       ├── detect-mechanical.py      # layer-A pre-pass
│       ├── find-installed-skills.sh  # runtime skill discovery
│       ├── extract-coach-events.py   # optional Coach data reader
│       ├── scan-cross-session.py     # layer-C JSONL fallback
│       └── validate-evals.py         # validates retro's own evals (RT-40..42)
├── commands/retro.md             # /retro slash command (Claude Code plugin only)
├── hooks/session-end.json        # optional auto-trigger (off by default)
├── tests/
│   ├── test_detect_mechanical.py
│   └── test_validate_evals.py
├── docs/specs/retro-skill.md     # authoritative specification
├── .github/workflows/            # lint.yml, release.yml
├── AGENTS.md
├── composer.json
├── .claude-plugin/plugin.json
├── LICENSE-MIT
└── LICENSE-CC-BY-SA-4.0
```

## Related projects

`/retro` materializes into conventions defined by sibling skills:

| Project | Role |
|---|---|
| [agent-harness-skill](https://github.com/netresearch/agent-harness-skill) | Verifies integration points; bootstraps `harness-artefact` materializations |
| [agent-rules-skill](https://github.com/netresearch/agent-rules-skill) | Feedback-memory schema for `project-rule` materialization |
| [skill-repo-skill](https://github.com/netresearch/skill-repo-skill) | PR/branch convention for `skill-update`; scaffolding for `new-skill` |
| [automated-assessment-skill](https://github.com/netresearch/automated-assessment-skill) | Checkpoint YAML schema for `checkpoint` materialization |
| [claude-coach-plugin](https://github.com/netresearch/claude-coach-plugin) | Optional, read-only layer-C data source |

Deeper reading: the authoritative spec at [`docs/specs/retro-skill.md`](docs/specs/retro-skill.md), the [`skills/retro/references/`](skills/retro/references/) docs, and [`AGENTS.md`](AGENTS.md).

## Contributing

Issues and PRs are welcome at <https://github.com/netresearch/retro-skill/issues>.

- **DCO sign-off is required** — commit with `git commit -s`. Without the `Signed-off-by` trailer the PR is blocked even when all checks pass.
- Use **Conventional Commits** (`feat:`, `fix:`, `chore:`, …).
- The `lint` workflow runs python compile, bash syntax, shellcheck, JSON/YAML validation, the unit tests, and the DCO check — run them locally before pushing.

## License

Code is licensed under [MIT](LICENSE-MIT); content under [CC-BY-SA-4.0](LICENSE-CC-BY-SA-4.0). SPDX: `(MIT AND CC-BY-SA-4.0)`.

Maintained by **Netresearch DTT GmbH** · <https://www.netresearch.de/>
