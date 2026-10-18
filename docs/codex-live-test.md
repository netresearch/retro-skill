<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->
<!-- SPDX-FileCopyrightText: Netresearch DTT GmbH -->

# Codex discovery live check

Checked on macOS on 2026-10-15 with `codex-cli 0.155.0`, using the native
`codex plugin list --json` output rather than a hand-built marketplace file.

```sh
python3 skills/retro/scripts/find-org-skills.py --host codex > catalogue.json
```

The inventory returned 385 entries, 377 with readable skill paths. It included
standalone Codex skills, sibling `.agents` skills, and skills from the enabled
plugin versions named by the CLI. Eight catalogue-only plugin entries had no
readable skill file. The new `retro` installation was included. All rows reported
`native-cli-and-local-skills`; the native available-plugin list was empty, which
does not establish absence of remote organization skills.

The discovery and existing Claude-discovery tests pass. The full suite passes
with a canonical temporary directory (722 tests). Under macOS's default aliased temporary
path, the existing bare-worktree path test also fails in the unmodified adapter
branch; this discovery patch does not change that scanner.

The pinned skill-repository validator passed on Ubuntu ARM64 with GNU sed and
GNU awk: zero errors, 18 warnings. The macOS hook stops on its GNU-sed
expression; Minimal Ubuntu's default mawk also fails on the validator's fence
expression. Temporary extracted GNU awk packages were used for the check,
without changing system packages. Markdown lint, Ruff, whitespace and version
parity hooks passed on macOS.

## Linux re-check

Checked on Linux (WSL2) on 2026-10-18 with `codex-cli 0.163.0` after the review
fixes. The inventory returned 152 entries, 146 with readable skill paths, all
`native-cli-and-local-skills`; the CLI wrote nothing to stderr. The one entry
dropped against the earlier reader was `my-skill-name`, a template at
`~/.agents/skills/automated-assessment/assets/skill-template/SKILL.md`. The 13
plugin directories in the Codex cache all carry `.codex-plugin/plugin.json`; the ones with
skills declare `"skills": "./skills/"`.
