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

When proposing a `skill-update` and no eval covers the friction area, propose an eval stub alongside the fix. Write it in the layout the target repo already uses — almost always `evals/evals.json`:

```json
{
  "eval_name": "handle-bun-projects",
  "prompt": "This is a bun project. Install the dependencies.",
  "assertions": [
    {"type": "content", "pattern": "bun install"},
    {"type": "must_not", "pattern": "npm install"}
  ],
  "samples": {
    "passing": "Run bun install to add the dependencies.",
    "failing": ["Run npm install to add the dependencies."]
  }
}
```

This is TDD style: the eval that would have caught the friction goes in with the fix.

**`samples` is required on every eval retro adds or tightens** (decided in
[retro-skill#92](https://github.com/netresearch/retro-skill/issues/92), option A).
`samples.passing` is an answer every pattern-bearing assertion is satisfied by —
matching it, or for a `must_not` assertion not matching it;
`samples.failing` holds at least one answer at least one assertion must reject.
Without them the assertion is documentation of intent and
`validate-evals.sh` has nothing to compare it against. Measured across the 23
`evals.json` files installed here, 518 evals: 12 carry `samples.passing`, and
296 would be rejected by the gate if they were new. The rule is scoped to what
retro writes: an eval it does not touch is left alone, and existing evals are
not retrofitted — the same 23 files, compared against themselves, produce 0
rejections.

**What is enforced is `samples.passing`.** The gate in
[skill-repo-skill#338](https://github.com/netresearch/skill-repo-skill/pull/338)
requires that one field and names `samples.failing` in its message as the thing
to add alongside it. Both directions are what make the sample worth having, so
write both; only the first is refused for.

Two cases the requirement does not cover:

- An eval whose assertions carry no pattern — `validate-evals.sh` *fails*
  samples that no assertion pattern backs, so requiring them would make the
  eval unvalidatable. This covers an `expectations`-only eval, and also the
  plain-string assertions that 210 of the fleet's evals use: those *are*
  graded at run time, where `run-ab-evals.sh` falls back to the string itself
  as the pattern, but this validator's samples machinery reads only assertion
  *objects*, taking `pattern` or `value` from each — a bare string carries
  neither key. Bringing them in would change what `samples`
  means for the evals that already carry them, which is a decision for
  [#92](https://github.com/netresearch/retro-skill/issues/92) rather than a
  patch.
- retro's own Markdown fixtures under `evals/` — a different schema with no
  samples concept (see `evals/README.md`).

`skills/retro/scripts/check-eval-samples.py` enforces this. `materialize-pr.sh
finish` (promote mode) runs it over the files it is about to stage and refuses to
commit when a new or tightened eval carries no samples; on the hand-rolled
skill-update path it is a step in `patch-workflow.md`'s self-review, run before
the commit:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/check-eval-samples.py --repo . <path>/evals.json
```

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
across the 23 `evals.json` files installed here, **12 of 518 evals carry
`samples.passing`**, so for the rest the gate has nothing to compare and
validates shape only.

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

- **`samples` are mandatory on an eval you add or tighten** (see "TDD stub for
  skill-update" above, and `check-eval-samples.py`, which refuses the
  materialization without them). Without samples the assertion is documentation
  of intent that nothing compares against; with them CI checks it both ways on
  every push.
- **Reach for `must_not` / `not_content` before treating an exclusion as
  inexpressible.** Whether a *regex* could also express it depends on the engine,
  and the grader's is `grader_matches` in `validate-evals.sh` — read it before
  relying on a lookahead.

`negative_expected` is separate: it belongs to retro's own fixture schema above,
which applies to retro's own evals and nothing else.

[retro-skill#92](https://github.com/netresearch/retro-skill/issues/92) settled
which of those to build: requiring `samples` on new and tightened evals, which
arms the gate that already exists. Adopting the `claude plugin eval` layout for
real answer-grading was rejected there — it is a new runner, a second format and
a migration across 23 files, against one rule and one check.

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
