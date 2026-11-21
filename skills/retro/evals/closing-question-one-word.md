---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: closing-question-one-word
skill_under_test: retro
mode: sweep
trigger: "`/retro` over a session that ends with two proposals: a paragraph for a skill reference and a new check in a repository the team owns. Neither has a mandate yet. The user wants to answer the report in one word."
expected:
  - end the Phase-10 report with one closing question that covers both proposals
  - list the three answers with what each does - complete (PRs created, reviewed and fixed until no new finding, own PRs merged and foreign PRs released when green), noted (no change, taken note of), propose (PRs created, reviewed and fixed until no new finding, left as drafts)
  - ask in the language of the user, for example komplett, fertig and vorlegen in German
  - treat the answer word as the mandate for every listed proposal and not ask again per PR
negative_expected:
  - ask a separate approve, edit or reject question for each proposal
  - end the report with an open question such as "shall I implement these?" that needs a sentence as answer
  - ask the closing question again when the user already gave the word in the invocation
  - ask the closing question when no proposal is open
  - read the mode word in `/retro done` as the answer noted and skip the question
samples:
  - "Report ends: Retro-Vorschläge umsetzen? Antwort mit einem Wort: komplett (PRs erstellen, reviewen und fixen bis keine Befunde mehr, eigene mergen, fremde freigeben, alles grün) · fertig (keine Änderung, nur zur Kenntnis genommen) · vorlegen (PRs erstellen, reviewen und fixen bis keine Befunde mehr, sie bleiben Drafts)."
---

# Scenario: the retro ends with a question that takes one word

The user decides how far the proposals go: not at all, up to reviewed drafts, or
up to the merge. Three fixed words make that decision one answer, and the word
is the mandate for everything the report proposed. A per-proposal approval loop
or an open-ended question costs the user a sentence for each item.
