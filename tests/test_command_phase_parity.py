# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Every phase the Sweep runs has a section in the slash command.

`/retro` loads `commands/retro.md`, not `SKILL.md` or the references. A
phase that the mode table in `references/workflow.md` lists for the Sweep,
but that the command does not carry, never reaches the run: on 2026-11-22
Sweeps ran without Phase 4b (project-harness inspection) and closed the
harness findings a second retrospective then proposed. In the four of those
Sweeps whose reads are visible, no run opened project-harness-inspection.md
(ADR-003).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / "skills" / "retro" / "references" / "workflow.md"
COMMAND = REPO_ROOT / "commands" / "retro.md"

ROW = re.compile(
    r"^\| (?P<phase>[0-9][0-9a-z-]*)(?: \([^)]*\))? \| (?P<sweep>[^|]+)\|", re.MULTILINE
)
RANGE = re.compile(r"^(?P<lo>[0-9]+)-(?P<hi>[0-9]+)$")
NOT_RUN = {"no", "skipped"}


def sweep_phases(table: str) -> list[str]:
    """Phase ids whose Sweep cell in the mode table says the phase runs."""
    phases: list[str] = []
    for match in ROW.finditer(table):
        if match["sweep"].strip().strip("*").lower() in NOT_RUN:
            continue
        span = RANGE.match(match["phase"])
        if span:
            phases.extend(str(n) for n in range(int(span["lo"]), int(span["hi"]) + 1))
        else:
            phases.append(match["phase"])
    return phases


FENCE = re.compile(r"(?ms)^```.*?^```")


def command_phases(command: str) -> set[str]:
    """Phase ids with a level-2 heading outside fenced code blocks."""
    return set(re.findall(r"(?m)^## Phase ([0-9]+[a-z]?)\b", FENCE.sub("", command)))


class SweepPhasesInCommand(unittest.TestCase):
    def test_table_is_read(self) -> None:
        phases = sweep_phases(WORKFLOW.read_text(encoding="utf-8"))
        # The rows the Sweep runs today; a parse that finds fewer measures nothing.
        for expected in ("1", "1b", "2", "3", "4b", "4c", "5", "9", "10"):
            self.assertIn(expected, phases)
        self.assertNotIn("3b", phases)
        self.assertNotIn("3c", phases)

    def test_every_sweep_phase_has_a_command_section(self) -> None:
        phases = sweep_phases(WORKFLOW.read_text(encoding="utf-8"))
        present = command_phases(COMMAND.read_text(encoding="utf-8"))
        missing = [p for p in phases if p not in present]
        self.assertEqual(
            missing,
            [],
            f"commands/retro.md has no '## Phase <id>' section for {missing}, "
            "although references/workflow.md runs them in the Sweep",
        )


if __name__ == "__main__":
    unittest.main()
