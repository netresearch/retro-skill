# retro's own evals

These scenarios test **retro's own classification behaviour** — the Phase-4
judgement calls that are retro's entire value: skill-bug vs skill-gap, when to
prune an instruction, and when *not* to propose anything at all. retro ships
them so it is a regression target for its own reasoning, and so that
`/retro "fix the retro skill"` has real fixtures to read.

## What these are (and are not)

- **Retro-owned, repo-scoped fixtures.** They test the router, not any other skill.
- **They do NOT impose a schema on other skills' evals.** retro still *reads*
  every other skill's `evals/` leniently and schema-free — see
  [`../references/eval-integration.md`](../references/eval-integration.md). The
  small frontmatter schema below is retro's own local business only.
- **They are LLM-graded.** `expected` / `negative_expected` are behavioural
  assertions a human or model checks against a real `/retro` run; they are not
  executed by a runner in this repo. `scripts/validate-evals.py` only checks that
  the fixtures are *well-formed*, not that retro passes them.

## Format

```markdown
---
id: <slug — must equal the filename without .md>
skill_under_test: retro
mode: sweep | spotlight | outcome | audit | promote
trigger: <one-line friction or user statement that starts the scenario>
expected:
  - <behaviour retro should exhibit — classification + bounded action>
negative_expected:
  - <behaviour that would be wrong>
---

# Scenario: <short human-readable title>

<prose: the context, the correct classification, and the evidence retro should cite>
```

Required keys (enforced by `scripts/validate-evals.py`): `id`, `trigger`,
`expected` (non-empty list), `negative_expected` (non-empty list). `id` must
equal the filename stem and be unique.

## Running them

```bash
python3 scripts/validate-evals.py            # well-formedness + inventory (CI gates RT-40..42)
```

To exercise retro against them, run `/retro "fix the retro skill"` and judge the
proposals against each scenario's `expected` / `negative_expected`.
