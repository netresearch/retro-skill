# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""The Python 3.11 floor is declared where the scripts start, not only in the README.

`detect-mechanical.py` crashed on macOS (#201): the docs said `python3`, and the
Command Line Tools' `python3` is 3.9, where `itertools.pairwise` and
`datetime.UTC` do not exist. Each script that runs as a command now declares
`requires-python = ">=3.11"` in a PEP 723 block and is started with `uv run`,
which picks a matching interpreter. These tests keep the headers and every
documented invocation in step.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "retro" / "scripts"
FLOOR = ">=3.11"

# Loaded by path from the other scripts, never run as a command.
LOADED_BY_PATH = {"feedback-contract.py", "mask-secrets.py"}

# The PEP 723 reference regex.
BLOCK = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
)

# A script started by an interpreter name instead of `uv run`:
# `python3 …/scripts/x.py`, `python x.py`, `py -3 -X utf8 "…\x.py"`.
DIRECT_CALL = re.compile(
    # `-X` and `-W` take a separate argument (`-X utf8`, `-W ignore`); the two
    # option alternatives exclude each other, so neither backtracks into the other.
    r"(?<![\w.-])(?:python3?|py\s+-3)(?:\s+-(?:[XW]\s+[^\s-]\S*|(?![XW]\s)[\w-]+))*\s+"
    # The alternatives are disjoint (`$(` only as a substitution), so a run of
    # `$()` has one way to match and cannot backtrack exponentially.
    r"(?:\$\([^)]*\)|\$(?!\()|\"|[^\s\"$])*?[\w-]+\.py\b"
)


def direct_calls(line: str) -> list[str]:
    # `uv run --python X python script.py` is the CI form: --python picks the
    # interpreter. Without --python, uv takes it from `.python-version` or the
    # system and ignores the script's block. The command the interpreter
    # belongs to starts after the last `;`, `&` or `|`.
    found = []
    for m in DIRECT_CALL.finditer(line):
        segment = re.split(r"[;&|]", line[: m.start()])[-1]
        if re.search(r"\buv run\b", segment) and re.search(r"--python\b", segment):
            continue
        found.append(m.group(0))
    return found


def script_metadata(path: Path) -> dict:
    blocks = [
        m
        for m in BLOCK.finditer(path.read_text(encoding="utf-8"))
        if m.group("type") == "script"
    ]
    if len(blocks) != 1:
        return {}
    content = "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in blocks[0].group("content").splitlines(keepends=True)
    )
    return tomllib.loads(content)


def documents() -> list[Path]:
    paths = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "skills" / "retro" / "SKILL.md",
        REPO_ROOT / "skills" / "retro" / "evals" / "README.md",
    ]
    # checkpoints.yaml is not listed: automated-assessment's checkpoint runner
    # allows `python3` but not `uv` as a command, and the RT-* checks it runs
    # (py_compile, validate-evals.py) need nothing newer than 3.9.
    paths += sorted((REPO_ROOT / "commands").glob("*.md"))
    paths += sorted((REPO_ROOT / "skills" / "retro" / "references").glob("*.md"))
    # docs/specs/retro-skill.md is superseded and kept as a historical record.
    paths += sorted(
        p
        for p in (REPO_ROOT / "docs").rglob("*.md")
        if p.relative_to(REPO_ROOT).as_posix() != "docs/specs/retro-skill.md"
    )
    paths += sorted(SCRIPTS.glob("*.sh"))
    return paths


class PythonFloorTest(unittest.TestCase):
    def test_every_command_script_declares_the_floor(self):
        commands = sorted(
            p for p in SCRIPTS.glob("*.py") if p.name not in LOADED_BY_PATH
        )
        self.assertGreaterEqual(len(commands), 11)
        for path in commands:
            with self.subTest(script=path.name):
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(lines[0], "#!/usr/bin/env -S uv run --script")
                self.assertEqual(script_metadata(path).get("requires-python"), FLOOR)

    def test_no_document_starts_a_script_with_python3(self):
        found = []
        for path in documents():
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                for call in direct_calls(line):
                    found.append(f"{path.relative_to(REPO_ROOT)}:{number}: {call}")
        self.assertEqual(found, [], "start these with `uv run`")

    def test_pattern_catches_the_shapes_that_were_documented(self):
        # Copied from the documents before #201: the pattern must flag each one.
        for line in (
            "python3 ${CLAUDE_PLUGIN_ROOT}/skills/retro/scripts/detect-mechanical.py \\",
            'python3 "${CLAUDE_SKILL_DIR}/scripts/detect-mechanical.py" \\',
            '  if python3 "${CLAUDE_SKILL_DIR}/scripts/codex-transcript.py" --transcript-file "$f"',
            'py -3 -X utf8 "$skillDir\\scripts\\detect-mechanical.py" --transcript-file $normalized',
            "python3 scripts/validate-evals.py            # well-formedness",
            '    python3 "$(dirname "$0")/check-eval-samples.py" --repo "$wt" -- "$@" \\',
            "uv run a.py && python3 scripts/b.py",
            "python3 -W ignore scripts/b.py",
            "python3 -X dev scripts/b.py",
            "uv run python skills/retro/scripts/validate-evals.py",
        ):
            with self.subTest(line=line):
                self.assertNotEqual(direct_calls(line), [])
        for line in (
            'uv run "${CLAUDE_SKILL_DIR}/scripts/detect-mechanical.py"',
            'uv run --python "$PYTHON_VERSION" python skills/retro/scripts/validate-evals.py',
            "python3 -m py_compile skills/retro/scripts/detect-mechanical.py",
            "`python3 - <<'PY' … PY`, then `gh pr edit 89 -R o/r`,",
        ):
            with self.subTest(line=line):
                self.assertEqual(direct_calls(line), [])

    def test_floor_matches_ruff_target(self):
        ruff = tomllib.loads((REPO_ROOT / ".ruff.toml").read_text(encoding="utf-8"))
        self.assertEqual(ruff["target-version"], "py311")


if __name__ == "__main__":
    unittest.main()
