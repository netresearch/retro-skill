# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Every Python call of git or a shell names the environment it runs in.

Without `env=`, a GIT_DIR exported by a git hook sends the call to another
repository, whatever `-C` or `cwd` says. Seen here: the calls that hand
`subprocess` a list literal starting with "git" or a shell, since a shell script
may call git. A list built elsewhere and a Python script that calls git are not
seen, nor whether a named environment is really clean.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPE = ("scripts/*.py", "skills/*/scripts/*.py", "tests/*.py")
PROGRAMS = {"git", "bash", "sh"}
RUNNERS = {"run", "Popen", "call", "check_call", "check_output"}
# The caller's environment as it is.
UNCHANGED = {"None", "os.environ", "os.environ.copy()", "dict(os.environ)"}


def _may_run_git(call: ast.Call) -> bool:
    argv = call.args[0] if call.args else None
    if argv is None:
        argv = next((k.value for k in call.keywords if k.arg == "args"), None)
    return (
        isinstance(argv, (ast.List, ast.Tuple))
        and bool(argv.elts)
        and isinstance(argv.elts[0], ast.Constant)
        and argv.elts[0].value in PROGRAMS
    )


def _passes_the_callers(env: ast.expr) -> bool:
    if isinstance(env, ast.Dict):
        return any(
            key is None and ast.unparse(value) in UNCHANGED
            for key, value in zip(env.keys, env.values, strict=True)
        )
    return ast.unparse(env) in UNCHANGED


def unclean_calls(source: str) -> list[int]:
    """Lines of the calls that run in the caller's environment."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if name not in RUNNERS or not _may_run_git(node):
            continue
        env = next((k.value for k in node.keywords if k.arg == "env"), None)
        if env is None or _passes_the_callers(env):
            lines.append(node.lineno)
    return lines


class GitSubprocessEnvTest(unittest.TestCase):
    def test_every_git_call_names_a_clean_environment(self):
        seen = 0
        for pattern in SCOPE:
            for path in sorted(REPO_ROOT.glob(pattern)):
                source = path.read_text(encoding="utf-8")
                seen += source.count('["git"')
                with self.subTest(file=str(path.relative_to(REPO_ROOT))):
                    self.assertEqual(
                        unclean_calls(source),
                        [],
                        "call without its own env= (tests: git_env.clean_git_env())",
                    )
        self.assertGreater(seen, 10, "the scope finds no git calls")

    def test_the_callers_environment_is_refused(self):
        for call in (
            'subprocess.run(["git", "init"])',
            'run(("git", "init"))',
            'subprocess.check_output(args=["git", "init"])',
            'subprocess.run(["bash", "x.sh"])',
            'subprocess.run(["git", "init"], env=None)',
            'subprocess.run(["git", "init"], env=os.environ)',
            'subprocess.run(["git", "init"], env=os.environ.copy())',
            'subprocess.Popen(["git", "init"], env=dict(os.environ))',
            'subprocess.run(["git", "init"], env={**os.environ, "A": "b"})',
        ):
            with self.subTest(call=call):
                self.assertEqual(unclean_calls("x = 1\n" + call), [2])

    def test_another_environment_and_another_program_are_accepted(self):
        for call in (
            'subprocess.run(["git", "init"], env=clean_git_env())',
            'subprocess.run(["git", "init"], env={**clean, "A": "b"})',
            'subprocess.run(["jq", "."])',
            'print(["git", "init"])',
        ):
            with self.subTest(call=call):
                self.assertEqual(unclean_calls(call), [])


if __name__ == "__main__":
    unittest.main()
