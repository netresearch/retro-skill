# Eval Integration

How `/retro` consults skill `evals/` directories to inform classification and propose TDD-style stubs.

## When evals are consulted

After a skill is matched for `skill-update` destination, check if it has `evals/`:

```
<skill-root>/evals/
├── evals.json    # Eval scenarios — the common case by a wide margin
├── *.md          # Eval scenarios (retro's own layout; rare elsewhere)
└── results/      # Optional historical results
```

Check `skills/<name>/evals/` too — skills that ship under a `skills/` directory
usually keep their evals beside them rather than at the repo root.

If yes, read evals before generating the proposal.

## Three uses

### 1. Classification context

The LLM reads relevant eval scenarios to validate the friction interpretation:

> "Skill X claims (via eval `evals/handle-bun-projects.md`) to support bun. The friction shows the opposite. This is a skill bug, not a skill gap — different fix."

This distinguishes:
- **Skill bug** — eval covers the case, behavior diverged → fix the skill or the eval
- **Skill gap** — eval doesn't cover the case → add capability AND eval

When a skill-update proposal cites eval evidence, it cites evals that **already
exist** (read) — never a fabricated "without-skill / with-skill" comparison retro
did not run. retro analyzes one real session in one pass; it does not re-execute
tasks to score them.

### 2. TDD stub for skill-update

When proposing a `skill-update` and no eval covers the friction area, propose an eval stub alongside the fix:

```markdown
## Proposed change
1. Update SKILL.md description to include "bun"
2. Add eval: `evals/handle-bun-projects.md` covering bun-vs-npm choice

## Eval stub
\`\`\`markdown
---
scenario: handle-bun-projects
trigger: User says "this is a bun project"
expected: Skill triggers and suggests bun commands (bun install, bun run)
\`\`\`
```

This is TDD style: eval that would have caught the friction goes in with the fix.

### 3. Pre-emptive findings (CI integration)

If the target skill repo has CI accessible via `gh api`:

```bash
gh api repos/<org>/<repo>/actions/runs --jq '.workflow_runs[0]'
```

Read recent eval failures. These are friction the user hasn't hit yet — pre-emptive `/retro` findings.

Only do this when:
- The skill is being actively worked on (recent commits)
- Eval failures exist
- The user opts in (configurable)

## Eval format (lightweight, no enforced schema)

Different skills may use different eval formats. `/retro` reads them as text and gives the content to the LLM for context.

In practice almost every skill repo uses a single `evals/evals.json`, in one of
two container shapes. Both hold the same kind of record, so read whichever key is
present rather than assuming one:

```json
[ { "name": "…", "prompt": "…", "assertions": [ "…" ] } ]
```

```json
{ "skill_name": "…",
  "evals": [ { "id": 1, "name": "…", "prompt": "…", "expected_output": "…" } ] }
```

The Markdown-with-frontmatter form below is retro's own layout and is rare
elsewhere:

```markdown
---
scenario: <name>
trigger: <user prompt or condition>
expected: <expected behavior>
---
<optional explanation>
```

`/retro` does not enforce a format — it adapts to what each skill uses. Read the
file before assuming a shape: a top-level array and an object with an `evals` key
are both current, and a repo may name the file something other than `evals.json`.

## retro's own evals (dogfooding)

retro ships its **own** `evals/` directory testing its **own** classification
behaviour — skill-bug vs skill-gap, when to prune, when to propose nothing. These
are repo-scoped fixtures (see `evals/README.md`), validated for well-formedness by
`${CLAUDE_SKILL_DIR}/scripts/validate-evals.py` and gated by checkpoints RT-40–RT-42.

This is the one place retro uses a small, fixed local schema
(`id` / `trigger` / `expected` / `negative_expected`). It applies **only** to
retro's own evals and does **not** change the rule above: when *reading other
skills'* evals, retro stays schema-free and tolerant. Running
`/retro "fix the retro skill"` reads these fixtures as classification context,
exactly like any other skill's evals.

## Limitations

- Evals are not always present (most skills don't have them yet)
- Eval coverage varies; absence of eval ≠ absence of capability
- Eval format heterogeneity makes mechanical analysis hard; LLM reading is the practical approach

### What grades an eval, and what does not

The files read like tests, so it is worth being exact about which half runs.

**The assertions ARE executed — against the file's own samples.**
`validate-evals.sh` (skill-repo-skill, run by the `eval-validate` workflow)
applies every assertion carrying a pattern to `samples.passing` and to each
`samples.failing` entry, honouring the direction of `must_not`, and fails the job
when a passing sample violates an assertion or a failing sample satisfies all of
them. That is a real self-consistency gate, and it is worth feeding: measured
across the 22 `evals.json` files in the fleet, **7 of 492 evals carry samples**,
so for the other 485 the gate has nothing to compare and validates shape only.

**What does not exist is a runner that produces an answer and grades it.** No CI
job feeds a prompt to a model and applies the assertions to what comes back, and
`claude plugin eval` expects a different layout entirely (`<eval dir>/**/case.yaml`,
or `prompt.md` plus `graders/*.md`). So a green `eval-validate` says the eval
file is internally coherent — not that the skill passes it. `/retro` itself reads
these files as text and hands them to the LLM as context.

**Negation does exist.** The grader handles `must_not` and `not_content`, and the
same measurement counts `content` 617, `must_not` 58, `content_regex` 43,
`tool_use` 35, `not_content` 5. What is uneven is adoption: only **2 of the 22
files** use a negative assertion at all. Where the wrong answer carries the same
keyword as the right one — `target`, `default branch`, `--onto` have all been in
that state — a positive assertion cannot separate them, and the type that can is
already available.

Two consequences for anyone writing or reviewing one:

- **Add `samples` to the eval you tighten.** Without them the assertion is
  documentation of intent that nothing compares against; with them CI checks it
  both ways on every push.
- **Reach for `must_not` / `not_content` before treating an exclusion as
  inexpressible.** Whether a *regex* could also express it depends on the engine,
  and the grader's is `grader_matches` in `validate-evals.sh` — read it before
  relying on a lookahead.

`negative_expected` is separate: it belongs to retro's own fixture schema above,
which applies to retro's own evals and nothing else.

Where this should go next — adopting the `claude plugin eval` layout for real
answer-grading, or requiring `samples` — is open in
[retro-skill#92](https://github.com/netresearch/retro-skill/issues/92).

## See also

- `references/skill-discovery.md` — How evals are located
- `references/classification-heuristic.md` — Where eval context informs decisions
- `references/patch-workflow.md` — How eval stubs land alongside skill-update PRs

## Running nested `claude -p` targets: isolate the config dir

Shelling out to `claude -p` inside an active Claude Code session (an A/B "with vs without skill" harness, an optimizer's target) inherits this session's plugins, whose SessionStart hooks inject their banner into the nested context — weak tasks echo it into the output and contaminate any scorer. Verified isolation that keeps auth and removes the leak:

```bash
CLEAN=$(mktemp -d)                      # per-run dir — never a fixed /tmp path
trap 'rm -rf "$CLEAN"' EXIT             # credentials must not outlive the run
cp ~/.claude/.credentials.json "$CLEAN/" && chmod 600 "$CLEAN/.credentials.json"
printf '%s\n' '{"hasCompletedOnboarding": true}' > "$CLEAN/settings.json"
CLAUDE_CONFIG_DIR="$CLEAN" claude -p --output-format json --disable-slash-commands "…" < /dev/null
```

What does NOT work (tested): `--bare` drops auth ("Not logged in"); `--settings '{"hooks":{}}'` and an empty `--plugin-dir` do not stop plugin SessionStart hooks. Prefixing `CLAUDE_CONFIG_DIR="$CLEAN"` isolates that one process; `export CLAUDE_CONFIG_DIR="$CLEAN"` before launching a harness isolates every nested `claude` call it spawns — use the export form for multi-call harnesses. Feed stdin from `/dev/null` to skip the CLI's stdin wait.

## Eval-oracle design: the eval is the lever, and a wrong eval makes optimization harmful

From a measured skill-optimization experiment (64 labeled cases):

- **The optimizer loop is commodity; the oracle is everything.** It optimizes whatever the eval rewards — including the eval's mistakes: a benchmark that encoded a wrong idiom had the optimizer "improve" the skill toward it. A wrong eval is worse than none.
- **No cheap oracle is perfect** — string-match blesses broken output and fails valid variants; render-vs-reference fails correct markup for environment reasons; render-standalone rubber-stamps most wrong output. The measured winner: an intent-judge plus deterministic hard guards (0.89 → 0.97 after targeted disambiguations), with the safety property that guards must NEVER reject valid output (FN 0).
- **~0.97 is the practical ceiling**: the residuals are LLM non-determinism on semantic boundaries and genuine policy-vs-fact boundaries — not fixable knowledge gaps.
- **The ground truth is as fallible as the evaluator**: an authoritative renderer exposed errors in the hand-authored gold labels themselves. Validate labels against reality before blaming the judge.
