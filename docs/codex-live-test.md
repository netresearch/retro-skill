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

The transcript conversion is a separate existing contribution:
[#168](https://github.com/netresearch/retro-skill/pull/168), head
`0a094677a6eba120b90ee5a019cd1cdbb414383e`. This discovery change does not
duplicate that adapter. Its five adapter tests and the detector tests passed
(141 tests). A real Desktop rollout produced by `codex_work_desktop`, recorded
as `0.155.0-alpha.9.2`, was converted and fed to the detector: it produced
nonempty messages and literal nested tool calls without an `exec` wrapper
command shape. Batched results and computed arguments remain outside that
adapter's mechanical coverage, as its docstring states. No private transcript
or source-machine path is included here.

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
