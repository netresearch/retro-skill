# Project-Harness Inspection

The counterpart to skill discovery: what the **repo the session worked in**
could have caught, automated, or documented so the friction never reaches an
agent's judgement.

## Why this is its own phase

The destinations already cover it — `project-rule` writes to `<project>/AGENTS.md`,
and `harness-artefact` targets *"the repo the session was working in"* with
hooks, CI jobs, linter rules, templates and scaffolding. What was missing is a
step that makes anyone **look**.

Skill discovery is mandatory and scripted (`find-org-skills.py`); nothing
equivalent pointed at the repo. The result is a structural bias toward
skill-shaped answers, and it is measurable: in the run that produced this file,
six proposals went out — five to skills, one to a machine-local hook, **zero to
the repo** — while three qualifying findings sat in plain sight, including a
documented six-suite pre-push gate that existed only as a list to execute by
hand.

A skill teaches an agent. A repo gate stops everyone, including the humans and
the agents that never load the skill. Where both are possible, "Routing —
enforceability first" already prefers the gate; this phase is what makes the
gate *visible* as an option.

## What to inspect

Read these against what the session actually did. Each row is a question about
this session, not a checklist to fill in.

| Surface | The question |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | Did the agent re-derive something already true but unwritten? Did it follow a rule that is stated in **more than one place, differently**? |
| One-command entry points (`Makefile`, `composer.json` scripts, `package.json`) | Did the session run a documented sequence by hand? A gate described as a list is a gate whose last two steps get skipped. |
| Hook config (lefthook, captainhook, husky, pre-commit) | Did something reach CI that a sub-second local check would have caught? |
| CI workflows | Is the failing check **repo-local and missing**, rather than a skill gap? Does a fast check exist in CI but not as a hook (parity)? |
| Linter / analyzer config | Would a rule in a tool the repo already runs have failed on this? That is the cheapest gate available. |
| Dev environment (`.ddev`, containers, `.Build`, lockfiles) | Did the session lose time to environment shape rather than to the problem? |
| Templates (PR/MR, issue) | Did a review round ask for something a template could have prompted? |

## Two traps

**A CI check without its hook is half-materialized.** `patch-workflow.md`
("CI/hook parity") requires a fast, deterministic check to land in both, in the
same PR. State it rather than shipping the half.

**Verify before bootstrapping.** A hook config, a CI workflow and a PR template
are almost never absent outright — the finding is usually that the existing one
does not cover *this* check. Extend it; never overwrite a config with a
template.

## What this phase is not

It is not a repo audit. The scope is what **this session** touched or tripped
over. A finding that needs a survey of the repo rather than a memory of the
session belongs in `/retro audit`, not here.

It is also not a licence to narrow: a lesson that generalizes past this repo
still routes to `skill-update` under "Axis 2 — reach". Many findings produce a
**pair** — the gate here, the recipe for installing it in the owning skill.

## See also

- `references/destination-taxonomy.md` — `project-rule` and `harness-artefact`
- `references/classification-heuristic.md` — enforceability before reach
- `references/patch-workflow.md` — "Harness artefacts": target selection,
  verify-before-bootstrap, CI/hook parity, server-side instruments
