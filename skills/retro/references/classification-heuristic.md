# Classification Heuristic

Maps friction signals (from `friction-catalog.md`) to one of the seven destinations (from `destination-taxonomy.md`).

## Primary mapping

> Run skill discovery first and apply **Routing — authority first, then
> enforceability, then reach** (below) before taking any row literally: the
> named skill in a row is a hint, not a substitute for the owning-skill check,
> and a row naming a prose destination does not rule out a gate. The right
> owner may be a different (or not-installed) skill — or no skill at all: a
> fact whose canonical owner is an artefact outside the agent system routes to
> `canonical-source` regardless of the row (Axis 0 below; B14 and B16–B18 are
> the main inlets).

| Friction signal | Primary destination | Alternate (LLM decides from context) |
|---|---|---|
| **A1** tool error | `skill-update` (tool-owner skill) | `personal-rule` (if user-specific config issue) |
| **A2** tool retry cluster | `harness-artefact` / skill **script** — the shape is known, wrap it | `skill-update` (tool-owner) |
| **A3** tool output verbosity | `skill-update` (tool-owner: file-search, data-tools) | `personal-rule` |
| **A4** too many tool calls | `harness-artefact` / skill **script** for the shapes in `top_shapes` | `skill-update` (workflow guidance) |
| **A5** sequential vs parallel | `skill-update` (workflow skill) | — |
| **A6** user correction phrase | `personal-rule` (style) OR `project-rule` (convention) | LLM reads correction content to decide |
| **A7** prompt repetition | `skill-update` (description didn't match) | `agent-rules-skill` PR (AGENTS.md unclear) |
| **A8** prompt sequence repetition | Snippet/Custom Command OR `skill-update` (workflow) | `new-skill` if pattern is rich |
| **A9** tool sequence repetition | `harness-artefact` / skill **script** | `skill-update` (composition guidance) |
| **A10** skill in reminder vs invoke | `skill-update` (description or trigger words) | `harness-artefact` (delegation map) |
| **A11** wrong tool choice | `skill-update` (tool-owner skill) | `personal-rule` |
| **A12** re-read same file | `skill-update` (workflow / context retention) | — |
| **A13** skipped verification | `harness-artefact` (PR template) OR `project-rule` (CLAUDE.md) | `skill-update` (skill should require verification step) |
| **A14** worked on main/master | `harness-artefact` (branch protection / pre-commit) | `personal-rule` if user-pattern |
| **A15** bot attribution in commit | `personal-rule` (rule violated) → `skill-update` (skill should know rule) | — |
| **A16** outdated tool warning | `skill-update` (tool-owner, version bump) | `personal-rule` (user's setup outdated) |
| **A17** upstream failure | `harness-artefact` (pre-commit hook) OR `skill-update` (verification step) OR `checkpoint` (mechanical check) OR `project-rule` | LLM picks based on what would have caught it |
| **A18** permission re-approval | `personal-rule` + invoke `update-config` skill | — |
| **A19** repeated command shape | `harness-artefact` / skill **script** that returns the whole answer in one call | `skill-update` only if a script already exists and was not used |
| **A20** wait-loop inefficiency | `harness-artefact` — a watch that returns on the first actionable event | `personal-rule` (waiting discipline) |
| **B1** output quality mismatch | `personal-rule` (preference) OR `skill-update` (output style) | — |
| **B2** wrong skill choice | `skill-update` (description of unused skill) | — |
| **B3** skill capability gap | `skill-update` (add guidance) | `new-skill` if gap is large |
| **B4** skill description mismatch | `skill-update` (description) | — |
| **B5** hallucination / fact check | `skill-update` (context7 / verification) | `personal-rule` |
| **B6** convention violation | `project-rule` | `skill-update` (project-aware skill) |
| **B7** missing skill | `new-skill` **only if no catalogue skill covers it**; if one exists but isn't installed, recommend installing it | — |
| **B8** wrong-destination materialization | `skill-update` (retro-skill itself, or whoever wrote) | — |
| **B9** repeated mistake in session | `skill-update` (rule was unclear) | `personal-rule` |
| **B10** approval bypassed | `skill-update` (skill should require confirmation) | `harness-artefact` (template) |
| **B11** plan/spec skipped | `skill-update` (spec-driven-development trigger) | `project-rule` |
| **B12** assumption without asking | `skill-update` (spec-driven-development trigger description) | `personal-rule` |
| **B13** context re-discovery | `project-rule` (improve AGENTS.md) | `skill-update` (agent-rules-skill) |
| **B14** doc drift | `skill-update` — the owning skill (context7-skill for library docs; **skill-repo-skill** if a `SKILL.md`/`plugin.json`/command list drifted — discover first) | `canonical-source` (the drifted doc itself is the canonical owner — fix it there) / `project-rule` |
| **B15** skill trigger-coverage gap | `skill-update` (sharpen the missed skill's `description`/trigger words) | `new-skill` (no skill covered it) / `skill-update` B3 (skill fired but under-performed) |
| **B16** hard-won technique | `skill-update` (add the command/flag/endpoint to the owning skill) | `canonical-source` (the fact is about the tool itself and its owner is upstream docs/code — Axis 0) / `new-skill` (no owning skill) |
| **B17** proactive improvement | `skill-update` (codify the better approach) | `project-rule` (repo-specific) |
| **B18** review-issue learning | `skill-update` (generalize the review lesson) | `project-rule` (genuinely repo-specific) |
| **C1** same friction again | `skill-update` (existing memory not enough) | `harness-artefact` (enforcement) |
| **C2** cross-project pattern | `skill-update` (promote from feedback files) | `new-skill` |
| **C3** memory drift | `skill-update` (skill should reference memory; also the signal `/retro promote` emits per stock memory file) | `project-rule`/`personal-rule` (LLM picks from `current_location` + content) |
| **C4** skill update ineffective | `skill-update` (previous fix was wrong) | — |
| **C6** written rule violated repeatedly | `harness-artefact` (hook/checkpoint that makes the violation impossible) | never another prose rule — that is what already failed |

## Routing — authority first, then enforceability, then reach

Three axes decide a destination, in this order. Axis 0 asks who should *own*
the truth; axis 1 asks whether the rule can be *enforced*; axis 2 asks how far
the remainder should *reach*.

### Axis 0 — authority: who should own this truth?

Do not ask "where can I store this learning?" first — ask "who should own this
truth?". Many findings are facts about the world, not about agent behaviour,
and most facts have a canonical owner *outside* the agent system:

| Truth class | Canonical owner | Example |
|---|---|---|
| Official standard, product/tool behaviour | Upstream documentation | "guides.xml accepts X" → the tool's official manual |
| Value derivable from an artefact | The code / manifest / schema itself | a CLI flag → the Command's `configure()`; a version → `ext_emconf.php` |
| Org-wide process or policy | Handbook / policy doc | escalation path, booking rules |
| Agent behaviour, agent workflow, observed agent failure mode | **A skill** | "`fullPage` screenshots clip the TYPO3 backend iframe" |

**A skill is the canonical source only for facts about agent behaviour or the
skill's own procedure.** When the canonical owner is outside the agent system,
route to `canonical-source` (a PR/patch to the owning artefact — see
`destination-taxonomy.md` §7); the skill involved keeps at most a *reference*
to the owner plus the agent-specific delta (navigation, guardrail, observed
failure mode) — never a copy of the fact.

Why this axis comes first: a duplicated upstream fact hardens locally — a
checkpoint enforces it, an eval expects it, everything stays green — while
upstream moves on. The result is **authority drift**: a self-consistent local
truth that is wrong. The `skill-update` default of B16–B18 is the main inlet
for this failure, so run the authority check before taking any mapping row
literally.

Three content grades may live inside a skill, each with its price of entry:

- a **duplicated upstream rule** needs justification and evidence — an
  observed failure that a mere reference did not prevent;
- an **agent-specific rule** needs an observed agent failure mode;
- a **deliberately stricter org policy** must be labelled as org policy,
  never presented as the upstream standard.

Everything else is removed or turned into a reference. When the canonical
owner cannot take the fix (no contribution path, upstream gap), the skill may
carry the fact *temporarily* — labelled with its authority and the upstream
issue/PR where one exists — and a later `/retro audit --scope skill`
reconciliation prunes it once upstream lands (see Instruction pruning, and
"Audit" in `workflow.md`).

### Axis 1 — enforceability: a gate outranks a sentence

An instruction depends on the reader following it. A check fails the build when
they don't. Ask first whether the finding is expressible as a gate, and only
then where the prose belongs.

`agent-harness-skill/references/enforcement-mechanisms.md` grades the ten
enforcement instruments by strength, server-side down to convention-based. Its
load-bearing rule transfers directly to retro's routing: *"when CI catches a
mechanical issue that a hook could have caught, the absence of the hook is the
bug. Strengthen the harness rather than asking the operator to be more
careful."* Substitute "prose rule" for "operator" and that is this axis.

Three tiers, strongest first:

1. **Mechanical gate** — the rule is a pattern, an exit code, or a file check →
   `checkpoint` (`mechanical:`) or `harness-artefact` (hook / CI job / linter
   rule / ruleset). Take this tier whenever it is available at all.
2. **LLM review** — checkable, but by judgment rather than pattern matching →
   `checkpoint` (`llm_reviews:`; see
   `automated-assessment-skill/references/learning-derived-checkpoints.md`,
   which owns the mechanical-vs-llm_reviews split).
3. **Prose instruction** — the rule needs context weighed at the time of use →
   `skill-update` / `project-rule` / `personal-rule`.

Most B16–B18 reusable learnings land in tier 3 legitimately; do not contort a
judgment lesson into a brittle regex to reach tier 1. The test is whether a
check could have *failed* on the friction as it actually occurred.

**A gate reaches one repo; prose reaches every repo the skill touches.** The two
axes therefore pull against each other. Where a mechanical gate is possible,
resolve it as a **pair**: the gate goes into the repo where the friction
happened, and the prose that accompanies it is the *recipe for installing that
gate elsewhere* — carried by the owning skill — not a restatement of the rule
the gate already enforces. The pair is one proposal with one approval and counts
once against the ≤10 cap; `destination-taxonomy.md` ("Paired materialization")
owns the binding rules.

**Calibrate a tier-1 gate against the transcript before proposing it.** The
transcript is a ready-made corpus of real commands, so the firing rate is
measurable rather than arguable: extract the tool inputs, run the candidate
predicate over them, and report the count. Two numbers make the proposal
reviewable — how often it fires, and whether the friction that prompted it is
among the hits.

```
6 of 296 Bash calls (2.0 %), and the incident itself is one of them
```

The first draft of that same rule fired 7 times; the extra hit was a false
positive (`git branch -D`, a write, matched a read-only pattern) and naming it
is what narrowed the rule. A gate nobody can silence gets tuned out, which
leaves the friction unguarded *and* costs a hook — so an uncalibrated tier-1
proposal is weaker than an honest tier-3 one.

The accompanying test must contain cases that **must not** fire, not only cases
that must: a test that only proves the gate speaks cannot show it can stay
quiet, and a gate that always fires is indistinguishable from one that is
broken.

**When the predicate reads content rather than command shape, the transcript is
not a wide enough corpus.** A rule matching prose, identifiers or file contents
will meet text nobody wrote for it, so calibrate against the widest negative
corpus available — assemble one if it does not exist, for instance every
document of the kind the gate inspects across the repositories it will run in —
not against the documents that motivated the gate. State how the corpus was
assembled, so the number can be reproduced and the next author can widen it. A German-prose gate for forge bodies passed calibration on the eight
bodies that caused it while carrying `mit` as a marker: also the licence every
skill repository names, 18 hits in a 63k-word English corpus that was never
consulted until a reviewer assembled it.

**And the two error directions do not cost the same.** In a gate that only
warns, a missed case costs a warning nobody got. In a gate that *denies*, a
false positive blocks legitimate work and gets the gate disabled — so its
threshold belongs where the negative corpus is silent, not at the edge of the
positive one. State both numbers in the proposal: what the incident scores, and
what the loudest negative document scores.

A repo that cannot host the gate (no CI, no analyzer, a repo the user does not
control) falls back to tier 3 for that repo only. That fallback is not a reason
to skip the gate where it *is* possible, and a skill instructing an agent is not
equivalent to a gate failing a build — it is the weaker tier, chosen because the
stronger one is unavailable.

### Axis 2 — reach: prefer the broadest useful destination

Knowledge is only as valuable as the breadth of reach where it applies. (Axis 0
has already routed away facts owned outside the agent system; this axis ranks
the remaining agent-behaviour prose.)

**First, run skill discovery (`scripts/find-org-skills.py`) and check the full
catalogue — installed *and* available — for a skill that owns this topic.** This
is mandatory and happens *before* a destination is chosen, not after: without
the catalogue you cannot route to the right owner — which is exactly how a
skill-authoring lesson lands in `personal-rule` instead of the skill that owns
skill authoring. If an owning skill exists, default to `skill-update` against it
(use its `repo_url`) **even if it is not installed locally**, and narrow only
with cause. "No owning skill" must be confirmed by inspecting the top candidate
skills' **contents** (`SKILL.md` + `references/`), not just their one-line
descriptions — descriptions under-state ownership; memory is the last resort.

When a finding could still land at more than one scope, **escalate to the
broadest destination that still fits**, in this order:

1. **`skill-update` / `new-skill`** — reusable across every project and every
   teammate who has the skill. *Default here* whenever the lesson generalizes
   beyond the current repo (a tool gotcha, a workflow step, a weak trigger).
2. **`project-rule` → `<project>/AGENTS.md`** — committed, versioned, shared
   with everyone working that repo. Use when the lesson is real but genuinely
   specific to this project.
3. **`personal-rule` → `~/.claude/CLAUDE.md`** — only when the lesson is a
   *personal* preference/style that does not belong to any repo or skill.

**Never** project-local memory (`~/.claude/projects/<slug>/memory/`, a project
`CLAUDE.md`, or `docs/feedback/`) — it shares with no one and is cwd-scoped.

Only narrow a step when escalation would be *wrong* — i.e. the knowledge truly
doesn't generalize (purely personal → user-rule) or is truly repo-specific
(→ AGENTS.md). Ask the user only when the *fit* is genuinely ambiguous, not to
avoid choosing the more-shareable option.

## Instruction pruning — removal is a valid skill-update

`skill-update` covers three edit shapes, not two: **add**, **replace**, and
**remove**. retro tends to *add*; many skills degrade through accretion, not
through missing rules. When an instruction is the *cause* of friction — it is
obsolete, too broad, duplicated, or contradicted elsewhere — prefer **removing**
it over stacking another exception on top.

Prefer removal when the desired behaviour is already covered by:

- another instruction in the same skill,
- a reference file,
- a mechanical `checkpoint`,
- repo-local `AGENTS.md`.

Prefer **replace** (not remove) only when deletion would open a real capability
gap. The **evidence** for a removal is the covering location you cite (the other
instruction / reference / checkpoint / rule) — *not* a measured A/B rollout or a
generated "proof" eval. **Open and read that location before citing it, and
confirm it covers the *same* mechanism** — a similar-sounding adjacent one is not
coverage. This applies equally when *dropping a fresh candidate* as
"already covered / redundant": read the target skill section first. (Observed
failure: a retro dropped a real learning — the per-release Contributors row is
driven by `mentions_count` — as "redundant" by conflating it with the *commit-based
repo contributor graph*, an adjacent mechanism the target skill didn't actually
document; the user overrode it.) retro proposes the bounded removal, the human approves it
at the gate, and the source-repo PR review decides. A pruning proposal
materializes as an ordinary `skill-update` PR whose diff happens to be a deletion
(see `patch-workflow.md`).

Signals that often resolve to a prune rather than an add: **B14** (doc drift —
the instruction references something gone), **C4** (a prior skill update was
itself wrong), **B8** (a rule lives in the wrong place). When two instructions
conflict, reconcile by removing/superseding the stale side; if the conflict spans
reference files, propose the reference/taxonomy cleanup first.

## Disambiguation prompts

When two destinations are plausible, ask the user with concrete framing:

```
This friction could go to either:
  (a) <project>/AGENTS.md  — project convention
  (b) ~/.claude/CLAUDE.md  — your cross-project personal preference

The friction was: "<one-line summary>"
Which fits better?
```

## Severity inference

Severity is set during classification, not during detection:

- `critical` — Recurring (C-layer match) OR caused upstream failure (A17) OR user-visible bug
- `important` — User correction phrase present (A6) OR known rule violated (A15) OR a **reusable-learning finding** (B16–B18, or D11 durable-improvement in outcome mode): knowledge a future agent will otherwise re-derive is *important* by definition — never auto-grade a genuine learning `nice-to-have`
- `nice-to-have` — Efficiency / style / convention (most other cases)

Use severity to rank proposals in the output. Higher severity first.

**Cap protection — friction must not crowd out learnings.** When there are more
than 10 candidates and the list is trimmed to the ≤10 cap, reserve slots so the
top reusable-learning findings (B16–B18) survive the trim. Friction findings are
usually more numerous and easier to grade high; without this rule a busy session
returns 10 friction items and zero learnings, silently dropping exactly the
knowledge the second class exists to capture. If learnings must still be dropped
for space, say so in the Phase-10 report rather than dropping them silently.

## See also

- `references/friction-catalog.md` — Signal definitions
- `references/destination-taxonomy.md` — Destination definitions
- `references/workflow.md` — Where this fits in the overall flow
