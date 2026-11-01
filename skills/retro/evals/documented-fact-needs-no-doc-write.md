---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: documented-fact-needs-no-doc-write
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that took twenty minutes to find which local services the test suite needs. The repository README states it correctly in its testing section, and the session never opened that section. It also read the current CI status once, which is not written down anywhere."
expected:
  - hold the fact as a B21 candidate until Phase 4c has searched, then reclassify it as B13 because the state is `found-correct` — the README is where a reader starts, and it answers
  - propose no documentation change for it, neither new text nor a link; anything further follows B13's own route
  - drop the current CI status, because a value that is one read away and changes daily is not worth documenting
negative_expected:
  - propose adding the fact to the README or the wiki a second time
  - keep it as a dug-out item in the Done gate although nothing needs writing
  - propose documenting volatile state
samples:
  - The README's testing section lists the services; the session's transcript shows no read of that section.
---

# Scenario: a fact that was already documented is not a documentation gap

B21 asks three questions, and here all three are yes: the document exists, it is
correct, and the reader's starting point holds it. The effort was real, but
nothing in the records is missing. Duplicating the fact would create the stale
copy this signal exists to prevent. Compare
`reachable-doc-gets-a-link-not-a-page.md`, where the third answer is no.
