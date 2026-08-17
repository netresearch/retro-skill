---
id: personal-rule-alias-accepted
skill_under_test: retro
mode: sweep
trigger: "The user says 'that one is a user-memory thing, put it in my global rules' about a cross-project preference they corrected twice this session."
expected:
  - route the finding to `personal-rule` and materialize it as a titled rule in `~/.claude/CLAUDE.md`
  - accept `user-memory` as input without asking the user to rephrase — it is a documented deprecated alias
  - name the destination `personal-rule` in the proposal and in the Phase-11 report, not the alias the user typed
negative_expected:
  - reject or query the destination because `user-memory` is not in the current seven
  - report the destination back as `user-memory`, leaving two names in circulation for one destination
  - treat the word "memory" as a signal to write into `~/.claude/projects/<slug>/memory/`
---

# Scenario: the deprecated destination name still routes

`personal-rule` was called `user-memory` in earlier versions, and that name is
still in circulation — in users' phrasing, in older proposals, and in archived
reports. The alias is documented in
[`../references/destination-taxonomy.md`](../references/destination-taxonomy.md)
and must be accepted on input.

Two failure directions are under test. Refusing the alias makes retro brittle
against its own history for no gain. Echoing it back keeps two names alive for
one destination, which is exactly what the rename removed: what this
destination writes is a durable *instruction* in the always-loaded global rules
file, not a recollection of past sessions. The word "memory" in the user's
sentence is also not a routing signal toward project-local memory — that
location remains forbidden as a destination and is only ever a *source* for
`/retro promote`.
