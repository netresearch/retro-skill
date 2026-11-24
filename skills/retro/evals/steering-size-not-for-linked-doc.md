---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: steering-size-not-for-linked-doc
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session in which a release took three attempts because the tag format was unknown. The repository's root `AGENTS.md` (40 lines) links `docs/release.md` as the release procedure, and the agent read it. `docs/release.md` does not state the tag format. The draft proposal adds two lines with the tag format to `docs/release.md` and none to `AGENTS.md`."
expected:
  - "propose the two lines in docs/release.md"
negative_expected:
  - "report a steering-file size delta for docs/release.md or treat it as a file that loads in every turn"
  - "ask why the tag format cannot live in a linked document"
samples:
  - "Add the tag format to docs/release.md, which AGENTS.md links."
---

# Scenario: an edit to a linked document carries no steering-size statement

Control for `steering-size-stated-with-proposal`. `docs/release.md` loads
only when the agent opens it, so its size costs no context in every turn and
the size statement of Phase 7 does not apply.
