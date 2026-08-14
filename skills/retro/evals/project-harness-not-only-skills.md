---
id: project-harness-not-only-skills
skill_under_test: retro
mode: sweep
trigger: "A session ran a documented six-suite pre-push gate by hand because no one-command target existed, skipped one suite, and had CI find it. The repo's AGENTS.md, Makefile and hook config each describe 'the gate' differently."
expected:
  - propose against the worked-in repo, not only against skills — a one-command gate target (harness-artefact) and the AGENTS.md reconciliation (project-rule)
  - name which surface was inspected (AGENTS.md / Makefile / hook config / CI) rather than asserting a repo finding from memory
  - pair a repo gate with a skill-update only when the recipe generalizes, and keep it one proposal
negative_expected:
  - route every finding to skill-update because skill discovery is the only scripted lookup
  - propose a prose rule for something a Makefile target or a hook would enforce
  - treat "the destinations already allow project-rule" as evidence that the project surface was examined
---

# Scenario: the finding belongs to the repo, not to a skill

The destination taxonomy has always covered the worked-in repo — `project-rule`
writes `<project>/AGENTS.md`, and `harness-artefact` explicitly targets *"the
repo the session was working in"*. Coverage is not the failure mode. The failure
mode is that only skill discovery is mandatory and scripted, so a sweep drifts
toward skill-shaped answers and the repo's own harness is never opened.

The observed run: six proposals, five to skills, one to a machine-local hook,
zero to the repo — while three qualifying findings sat in plain sight, the
sharpest being a pre-push gate that three files described three different ways
and that existed only as a list to run by hand.

A correct run inspects the surfaces named in `project-harness-inspection.md`
against what the session actually did, and says which ones it read. "The
taxonomy allows it" is not the same as having looked.
