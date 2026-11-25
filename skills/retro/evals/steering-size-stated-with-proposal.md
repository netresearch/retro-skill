---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: steering-size-stated-with-proposal
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in which the agent ran a migration command by hand three times in one repository before finding it in `docs/migrations.md`, which the repository's root `AGENTS.md` does not link. `steering-size.py --repo .` reports `AGENTS.md` with 180 lines and 9,400 bytes, and `~/.claude/CLAUDE.md` with 420 lines. The draft proposal adds a 12-line section with the migration procedure to `AGENTS.md`."
expected:
  - "state the current size of the repository AGENTS.md (180 lines, 9,400 bytes) and the delta of the proposal in lines and bytes"
  - "say why the procedure cannot live in docs/migrations.md with a one-line link from AGENTS.md, or change the proposal to that link"
negative_expected:
  - "withhold or block the proposal because AGENTS.md exceeds about 100 lines"
  - "present the 100-line figure as a limit or omit its source"
  - "propose the 12-line section without its size delta"
samples:
  - "AGENTS.md has 180 lines (9,400 bytes). Instead of the 12-line section, add one line that links the procedure, `- Database migrations: [docs/migrations.md](docs/migrations.md)`: +1 line, +64 bytes."
---

# Scenario: a proposal to an always-loaded file states its size

The procedure already exists in a repository document; the agent could not
reach it. `destination-taxonomy.md` § `project-rule` counts a linked
document as part of the rule store, so the smaller edit is a link. Either way,
the proposal states the file's size and its delta. The size never blocks it.
