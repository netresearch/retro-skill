---
id: signal-count-validated-before-escalation
skill_under_test: retro
mode: sweep
trigger: "C6 reports that A11 fired 9 times while the matching rule is already in the always-loaded instructions, and recommends proposing a mechanical gate."
expected:
  - "Open the flagged commands before accepting the count: a signal that mirrors a harness gate is only friction where the gate would actually have denied."
  - "Compare the detector's predicate against the gate's own exemptions, and report the gap as a detector defect routed to skill-update against retro-skill."
  - "Cite the measured split (how many of the N hits the gate permits) rather than the raw tally."
negative_expected:
  - "Propose a new PreToolUse gate for a rule whose gate already exists and deliberately permits the flagged forms."
  - "Report the raw C6 tally as evidence that prose has failed, without opening a single flagged command."
  - "Route the finding to personal-rule as 'stop using grep on JSON' when the commands were presence or locate greps."
---

# Scenario: a signal count is a claim about the detector until its hits are read

C6 escalates by counting A11. That makes A11's precision load-bearing: every
false positive is a vote that a written rule has failed, and the remedy C6
recommends — build a gate — is expensive and, where the gate already exists,
actively wrong.

The session that produced this fixture reported nine `structured_file_misuse`
hits. All nine were `grep -n`, `grep -rn` or `grep -rl` against a `.json` or
`.yml`. The harness gate this signal mirrors, `bash-tool-nudge.py`, exempts
exactly those: it requires an extraction shape (`grep … | cut`, `grep -o`,
`awk -F … {print}`) and skips `-c/-q/-l` and a lone `grep -n`, because those are
the only way to find a **comment**, which no structured parser can see. The
detector carried no such exemption, so it reported as friction what the rule
permits.

The correct output is a `skill-update` against retro-skill fixing the predicate,
with the split stated — nine of nine permitted — not a proposal to gate
something already gated. The sibling function had already learned this lesson
for paths and carries a comment saying so; the flag half simply had not been
ported.

The general form: **before a mechanical signal becomes a finding, read the
commands it flagged.** A count is a claim about the query that produced it.
