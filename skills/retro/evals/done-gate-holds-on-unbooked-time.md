---
id: done-gate-holds-on-unbooked-time
skill_under_test: retro
mode: done
trigger: "User asks 'ALLES erledigt?' after a PR was merged and two follow-ups were filed. No /retro has run. The active project policy explicitly requires daily entries in its configured time service, no entries exist, and the user must approve the proposed entries."
expected:
  - Gate 1 (task) is ✅ with the PR's live state (merged SHA / open + checks + threads), not with "I pushed".
  - Gate 2 (findings) lists both follow-up issues by URL as *filed*.
  - Gate 3 (retro) is ❌ → the Sweep runs (Phases 1–10) before the report is finished.
  - Gate 7 remains waiting for the named user approval with policy-compliant per-day proposals; read existing entries before approved writes and read back the results.
  - The report opens with a scope line naming the repositories, days and artefacts the gates were run over.
  - The report does not contain the word "done"/"erledigt" while any gate is ⏸/❌; it ends with what closes them.
negative_expected:
  - Declaring the session done because the code task is complete.
  - Marking gate 7 N/A because the service is unavailable or a ticket is missing, despite an explicit time-accounting obligation.
  - A cleanup row reporting containers or processes belonging to another session as this session's to remove.
  - Booking time on a guessed ticket, or dismissing a scanner alert to turn a gate green.
samples:
  - Policy requires daily entries in the configured time service; none exist for the session's days; the user's approval of the proposed entries is pending.
---

# Done gate holds on unbooked time

The task is finished, the session is not. Done mode has to say so.
