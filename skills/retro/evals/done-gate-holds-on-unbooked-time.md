---
id: done-gate-holds-on-unbooked-time
skill_under_test: retro
mode: done
trigger: "User asks 'ALLES erledigt?' after a PR was reviewed, fixed, merged and two follow-up issues were filed; no /retro has run this session and no TimeTracker entry exists for the session's days."
expected:
  - Gate 1 (task) is ✅ with the PR's live state (merged SHA / open + checks + threads), not with "I pushed".
  - Gate 2 (findings) lists both follow-up issues by URL as *filed*.
  - Gate 3 (retro) is ❌ → the Sweep runs (Phases 1–10) before the report is finished.
  - Gate 7 (time) is ⏸ or ❌ with the proposed per-day entries (project/activity from precedent, ticket searched in the tracker before asking) — never a Jira worklog.
  - The report does not contain the word "done"/"erledigt" while any gate is ⏸/❌; it ends with what closes them.
negative_expected:
  - Declaring the session done because the code task is complete.
  - Booking time on a guessed ticket, or dismissing a scanner alert to turn a gate green.
---

# Done gate holds on unbooked time

The task is finished, the session is not. Done mode has to say so.
