# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Unit tests for scripts/check-local.py."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

mock = unittest.mock
REPO_ROOT = Path(__file__).resolve().parent.parent


def load():
    path = REPO_ROOT / "scripts" / "check-local.py"
    spec = importlib.util.spec_from_file_location("check_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_local = load()


class CheckLocalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.git("init", "-q")

    def git(self, *args):
        subprocess.run(
            ["git", *args], cwd=self.repo, env=check_local.clean_env(), check=True
        )

    def lint(self, text):
        path = self.repo / ".github" / "workflows" / "lint.yml"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")

    def test_reads_this_repositorys_command_and_matrix(self):
        command, versions = check_local.read_lint(REPO_ROOT)
        for part in ("py_compile", "unittest discover -s tests", "validate-evals.py"):
            self.assertIn(part, command)
        self.assertEqual(versions[0], "3.11")

    def test_a_lint_file_without_the_command_is_refused(self):
        self.lint("jobs:\n  test:\n    with: {python-versions: '[\"3.11\"]'}\n")
        with self.assertRaises(SystemExit):
            check_local.read_lint(self.repo)

    def test_an_empty_command_is_refused(self):
        self.lint(
            "jobs:\n  test:\n    with: {test-command: '', python-versions: '[\"3.11\"]'}\n"
        )
        with self.assertRaises(SystemExit):
            check_local.read_lint(self.repo)

    def test_the_first_failing_line_fails_the_command(self):
        self.assertFalse(
            check_local.run_test_command("false\ntrue\n", "3.11", self.repo)
        )

    def test_the_command_gets_the_version_and_runs_in_the_repository(self):
        command = (
            'test "$PYTHON_VERSION:$UV_PYTHON" = 3.12:3.12\n'
            f'test "$(pwd -P)" = "{self.repo.resolve()}"\n'
        )
        self.assertTrue(check_local.run_test_command(command, "3.12", self.repo))

    def test_the_scripts_own_virtualenv_does_not_reach_the_steps(self):
        with mock.patch.dict(
            "os.environ", {"VIRTUAL_ENV": "/v", "PATH": "/v/bin:/usr/bin:/bin"}
        ):
            env = check_local.clean_env()
            self.assertTrue(
                check_local.run_test_command(
                    'test -z "${VIRTUAL_ENV:-}"', "3.11", self.repo
                )
            )
            done = subprocess.CompletedProcess([], 0)
            with mock.patch.object(
                check_local.subprocess, "run", return_value=done
            ) as run:
                check_local.run_pre_commit(self.repo)
        self.assertNotIn("VIRTUAL_ENV", run.call_args.kwargs["env"])
        self.assertNotIn("VIRTUAL_ENV", env)
        self.assertEqual(env["PATH"], "/usr/bin:/bin")

    def test_untracked_files_fail_and_tracked_ones_do_not(self):
        (self.repo / "new.py").write_text("", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(check_local.no_untracked(self.repo))
        self.assertIn("new.py", out.getvalue())
        self.git("add", "new.py")
        self.assertTrue(check_local.no_untracked(self.repo))

    def test_a_git_location_of_the_caller_does_not_redirect_the_steps(self):
        (self.repo / "new.py").write_text("", encoding="utf-8")
        with tempfile.TemporaryDirectory() as other:
            subprocess.run(
                ["git", "init", "-q"],
                cwd=other,
                env=check_local.clean_env(),
                check=True,
            )
            location = {"GIT_DIR": f"{other}/.git", "GIT_WORK_TREE": other}
            with (
                mock.patch.dict("os.environ", location),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertFalse(check_local.no_untracked(self.repo))
        for name in check_local.GIT_LOCATION:
            with (
                self.subTest(name=name),
                mock.patch.dict("os.environ", {name: "/elsewhere"}),
            ):
                unset = f'test -z "${{{name}:-}}"'
                self.assertTrue(check_local.run_test_command(unset, "3.11", self.repo))
        self.assertLessEqual(
            {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"},
            set(check_local.GIT_LOCATION),
        )

    def test_a_missing_pre_commit_fails(self):
        with (
            mock.patch.object(
                check_local.subprocess, "run", side_effect=FileNotFoundError
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(check_local.run_pre_commit(self.repo))

    def test_pre_commit_runs_over_all_files(self):
        done = subprocess.CompletedProcess([], 0)
        with mock.patch.object(check_local.subprocess, "run", return_value=done) as run:
            self.assertTrue(check_local.run_pre_commit(self.repo))
        self.assertEqual(run.call_args.args[0], ["pre-commit", "run", "--all-files"])
        failed = subprocess.CompletedProcess([], 1)
        with mock.patch.object(check_local.subprocess, "run", return_value=failed):
            self.assertFalse(check_local.run_pre_commit(self.repo))

    def run_main(self, argv, **results):
        steps = {"run_test_command": True, "run_pre_commit": True, "no_untracked": True}
        steps |= results
        mocks = {
            name: mock.patch.object(check_local, name, return_value=value)
            for name, value in steps.items()
        }
        with (
            mock.patch.object(
                check_local, "read_lint", return_value=("x", ["3.11", "3.12"])
            ),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            started = {name: m.start() for name, m in mocks.items()}
            try:
                code = check_local.main(argv, repo=self.repo)
            finally:
                for m in mocks.values():
                    m.stop()
        return code, out.getvalue(), started

    def test_any_failing_step_fails_the_run_and_the_others_still_run(self):
        self.assertEqual(self.run_main([])[0], 0)
        for step in ("run_test_command", "run_pre_commit", "no_untracked"):
            with self.subTest(step=step):
                code, out, started = self.run_main([], **{step: False})
                self.assertEqual(code, 1)
                self.assertEqual(out.count("FAIL  "), 1)
                for mocked in started.values():
                    mocked.assert_called_once()

    def test_all_pythons_runs_every_version_of_the_matrix(self):
        started = self.run_main(["--all-pythons"])[2]
        versions = [c.args[1] for c in started["run_test_command"].call_args_list]
        self.assertEqual(versions, ["3.11", "3.12"])


if __name__ == "__main__":
    unittest.main()
