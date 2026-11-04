---
# SPDX-License-Identifier: CC-BY-SA-4.0
# SPDX-FileCopyrightText: Netresearch DTT GmbH
id: self-check-guessed-script-output
skill_under_test: retro
mode: sweep
trigger: "End of a `/retro` run. In Phase 1 the run wrote `detect-mechanical.py --output-format json` to a file and read it with `jq -r '.[]? // .findings[]? | \"\\(.id // .code) \\(.summary // .message)\"'`; jq failed with `Cannot index string with string \"summary\"`. Two more jq calls followed before `jq 'keys'` showed the real keys (`findings`, `signal`, `name`, `snippet`). The Phase 10 report does not mention it."
expected:
  - in Phase 11, run `detect-mechanical.py --signals A1,A2 --since-command retro` and keep the jq error, because the failing call read a retro script's output
  - report one self-check finding with its evidence (the turn of the jq error and the field names it guessed)
  - propose a bounded skill-update against retro-skill that makes the output shape findable where Phase 1 is described (a field list or a pointer to it), not a general rule about reading JSON
negative_expected:
  - skip the self-check because the Phase 10 report is complete
  - count the jq error as friction of the session's original task
  - propose more than two self-check findings, or propose one without naming its evidence
samples:
  - tests/test_detect_mechanical_since_command.py
---

# Scenario: the run had to guess the shape of its own script's output

The pre-pass is retro's own instrument, so a reader that cannot use its output
without trial and error is retro's defect, not the session's. It leaves an A1
error inside the retro run, which `--since-command retro` isolates from the
work the retro analysed. The fix belongs where Phase 1 tells the reader what
the script prints.
