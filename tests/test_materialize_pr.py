# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Tests for skills/retro/scripts/materialize-pr.sh.

Each case runs the real script against a throwaway local remote. Commit
signing goes through a stub ``gpg.program`` and ``gh`` is a stub on PATH that
records its working directory and arguments, so nothing leaves the temp dir.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from git_env import clean_git_env

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "retro" / "scripts" / "materialize-pr.sh"
# The provenance line `finish` requires (patch-workflow.md, PR body template).
PROVENANCE = (
    "Opened by a [netresearch/retro-skill]"
    "(https://github.com/netresearch/retro-skill) `/retro` run\n"
)
BODY = "## Summary\n\nx\n\n## Came from\n\n" + PROVENANCE

FAKE_GPG = """\
#!/bin/sh
cat >/dev/null
echo '[GNUPG:] SIG_CREATED ' >&2
printf -- '-----BEGIN PGP SIGNATURE-----\\n\\nfake\\n-----END PGP SIGNATURE-----\\n'
"""

FAKE_GH = """\
#!/bin/sh
{ echo "cwd=$(pwd)"; for a in "$@"; do echo "arg=$a"; done; } > "$GH_LOG"
echo "https://github.com/example/demo/pull/1"
"""


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=clean_git_env(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class MaterializePrTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in (("fake-gpg", FAKE_GPG), ("gh", FAKE_GH)):
            path = self.bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        self.gh_log = self.tmp / "gh.log"
        home = self.tmp / "home"
        home.mkdir()
        (home / ".gitconfig").write_text(
            textwrap.dedent(
                f"""\
                [user]
                    name = T
                    email = t@example.com
                [gpg]
                    program = {self.bin / "fake-gpg"}
                [init]
                    defaultBranch = main
                """
            ),
            encoding="utf-8",
        )
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "GH_LOG": str(self.gh_log),
        }
        # Remote with one commit on main.
        self.remote = self.tmp / "remote.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", str(self.remote)], check=True, env=self.env
        )
        seed = self.tmp / "seed"
        subprocess.run(
            ["git", "clone", "-q", str(self.remote), str(seed)],
            check=True,
            env=self.env,
            capture_output=True,
        )
        (seed / "README.md").write_text("seed\n", encoding="utf-8")
        for argv in (
            ["add", "README.md"],
            ["commit", "-q", "--no-gpg-sign", "-m", "seed"],
            ["push", "-q", "origin", "main"],
        ):
            subprocess.run(["git", "-C", str(seed), *argv], check=True, env=self.env)

    def _bare_project(
        self, name: str = "project", *, origin_head: bool = False
    ) -> Path:
        """Bare layout; refs/remotes/origin/HEAD only when ``origin_head``."""
        project = self.tmp / name
        project.mkdir()
        bare = project / ".bare"
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(self.remote), str(bare)],
            check=True,
            env=self.env,
        )
        for argv in (
            ["config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
            ["config", "remote.origin.followRemoteHEAD", "never"],
        ):
            subprocess.run(["git", "-C", str(bare), *argv], check=True, env=self.env)
        if origin_head:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(bare),
                    "symbolic-ref",
                    "refs/remotes/origin/HEAD",
                    "refs/remotes/origin/main",
                ],
                check=True,
                env=self.env,
            )
        return project

    def _run(self, *args: str, cwd: Path | None = None):
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            check=False,
            env=self.env,
            cwd=cwd or self.tmp,
        )

    def test_start_without_origin_head_falls_back_to_main(self):
        project = self._bare_project()
        result = self._run("start", str(project), "feat/x")
        self.assertEqual(result.returncode, 0, result.stderr)
        worktree = Path(result.stdout.strip())
        self.assertTrue((worktree / "README.md").is_file())

    def test_start_puts_the_worktree_inside_the_bare_project(self):
        """Two projects using the same branch name must not collide."""
        first = self._bare_project("one", origin_head=True)
        second = self._bare_project("two", origin_head=True)
        paths = []
        for project in (first, second):
            result = self._run("start", str(project), "feat/x")
            self.assertEqual(result.returncode, 0, result.stderr)
            paths.append(Path(result.stdout.strip()))
        self.assertEqual(paths, [first / "feat-x", second / "feat-x"])

    def test_finish_opens_the_pr_for_the_worktree_branch(self):
        """gh runs from the caller's cwd, so the branch must be named."""
        project = self._bare_project(origin_head=True)
        started = self._run("start", str(project), "feat/x")
        self.assertEqual(started.returncode, 0, started.stderr)
        worktree = Path(started.stdout.strip())
        self.assertTrue(worktree.is_absolute(), worktree)
        (worktree / "a.txt").write_text("a\n", encoding="utf-8")
        (self.tmp / "body.md").write_text(BODY, encoding="utf-8")
        # Relative to the caller's cwd; gh runs in the worktree, so the script
        # must hand it an absolute path.
        result = self._run("finish", str(worktree), "feat: a", "body.md", "a.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.gh_log.read_text(encoding="utf-8").splitlines()
        # gh reads the base (gh-merge-base) from the checkout it runs in.
        self.assertIn(f"cwd={worktree}", log)
        args = [line[4:] for line in log if line.startswith("arg=")]
        body_arg = args[args.index("--body-file") + 1]
        self.assertEqual(Path(body_arg).read_text(encoding="utf-8"), BODY)
        self.assertIn("--head", args)
        self.assertEqual(args[args.index("--head") + 1], "feat/x")
        # Releasing it to reviewers is the user's step, not the script's.
        self.assertIn("--draft", args)
        self.assertEqual(
            git("-C", str(self.remote), "log", "-1", "--format=%s", "feat/x"), "feat: a"
        )

    def test_a_git_dir_of_the_caller_does_not_redirect_the_commit(self):
        other = self.tmp / "other"
        subprocess.run(["git", "init", "-q", str(other)], check=True, env=self.env)
        project = self._bare_project(origin_head=True)
        self.env["GIT_DIR"] = str(other / ".git")
        started = self._run("start", str(project), "feat/g")
        self.assertEqual(started.returncode, 0, started.stderr)
        worktree = Path(started.stdout.strip())
        (worktree / "a.txt").write_text("a\n", encoding="utf-8")
        (self.tmp / "body.md").write_text(BODY, encoding="utf-8")
        result = self._run("finish", str(worktree), "feat: a", "body.md", "a.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            git("-C", str(self.remote), "log", "-1", "--format=%s", "feat/g"), "feat: a"
        )
        self.assertEqual(git("-C", str(other), "for-each-ref"), "")

    def test_finish_commits_only_the_named_files(self):
        """A file staged in the worktree beforehand must not ride along."""
        project = self._bare_project(origin_head=True)
        started = self._run("start", str(project), "feat/y")
        self.assertEqual(started.returncode, 0, started.stderr)
        worktree = Path(started.stdout.strip())
        (worktree / "a.txt").write_text("a\n", encoding="utf-8")
        (worktree / "unrelated.txt").write_text("secret\n", encoding="utf-8")
        git("-C", str(worktree), "add", "unrelated.txt")
        (self.tmp / "body.md").write_text(BODY, encoding="utf-8")
        result = self._run("finish", str(worktree), "feat: a", "body.md", "a.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        files = git(
            "-C", str(self.remote), "show", "--name-only", "--format=", "feat/y"
        ).split()
        self.assertEqual(files, ["a.txt"])

    def test_finish_accepts_a_body_with_crlf_line_ends(self):
        """A body written on Windows: its blank line reads as `\\r` to awk."""
        project = self._bare_project(origin_head=True)
        started = self._run("start", str(project), "feat/z")
        self.assertEqual(started.returncode, 0, started.stderr)
        worktree = Path(started.stdout.strip())
        (worktree / "a.txt").write_text("a\n", encoding="utf-8")
        (self.tmp / "body.md").write_bytes(BODY.replace("\n", "\r\n").encode())
        result = self._run("finish", str(worktree), "feat: a", "body.md", "a.txt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def _finish_with_hooks(self, branch: str, hook: str, origin_url: str = ""):
        """Run `finish` in a worktree that has a .pre-commit-config.yaml, with
        `hook` as the body of a stub `pre-commit` on PATH."""
        stub = self.bin / "pre-commit"
        stub.write_text(
            '#!/bin/sh\necho "$*" >> "$PC_LOG"\nn=$(wc -l < "$PC_LOG")\n' + hook,
            encoding="utf-8",
        )
        stub.chmod(0o755)
        self.env["PC_LOG"] = str(self.tmp / "pc.log")
        # The test remote is a local path, not netresearch/*: opt in.
        self.env.setdefault("MATERIALIZE_PR_HOOKS", "1")
        project = self._bare_project(origin_head=True)
        started = self._run("start", str(project), branch)
        self.assertEqual(started.returncode, 0, started.stderr)
        worktree = Path(started.stdout.strip())
        if origin_url:
            # The fetch URL names the organisation; pushes still go to the
            # local remote.
            git("-C", str(worktree), "remote", "set-url", "origin", origin_url)
            git(
                "-C",
                str(worktree),
                "remote",
                "set-url",
                "--push",
                "origin",
                str(self.remote),
            )
        (worktree / ".pre-commit-config.yaml").write_text(
            "repos: []\n", encoding="utf-8"
        )
        (worktree / "a.txt").write_text("a\n", encoding="utf-8")
        (self.tmp / "body.md").write_text(BODY, encoding="utf-8")
        result = self._run("finish", str(worktree), "feat: a", "body.md", "a.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = [
            line[4:]
            for line in self.gh_log.read_text(encoding="utf-8").splitlines()
            if line.startswith("arg=")
        ]
        body = Path(args[args.index("--body-file") + 1]).read_text(encoding="utf-8")
        pc_log = self.tmp / "pc.log"
        calls = (
            pc_log.read_text(encoding="utf-8").splitlines() if pc_log.exists() else []
        )
        return worktree, body, calls

    def test_hooks_of_a_netresearch_origin_run_without_the_opt_in(self):
        self.env["MATERIALIZE_PR_HOOKS"] = ""
        _, _, calls = self._finish_with_hooks(
            "feat/hn", "exit 0\n", "https://github.com/netresearch/demo.git"
        )
        self.assertEqual(calls, ["run --files a.txt"])

    def test_hooks_of_a_foreign_origin_do_not_run_without_the_opt_in(self):
        """pre-commit runs the code the target's config names."""
        self.env["MATERIALIZE_PR_HOOKS"] = ""
        _, body, calls = self._finish_with_hooks("feat/h0", "exit 1\n")
        self.assertEqual(calls, [])
        self.assertEqual(body, BODY)

    def test_finish_runs_the_hooks_on_the_named_files(self):
        _, body, calls = self._finish_with_hooks("feat/h1", "exit 0\n")
        self.assertEqual(calls, ["run --files a.txt"])
        self.assertEqual(body, BODY)

    def test_finish_commits_what_the_fixer_hooks_changed(self):
        # First run: a fixer rewrites the file and fails; second run passes.
        hook = '[ "$n" -eq 1 ] && { echo fixed > a.txt; exit 1; }\nexit 0\n'
        _, body, calls = self._finish_with_hooks("feat/h2", hook)
        self.assertEqual(len(calls), 2)
        self.assertEqual(git("-C", str(self.remote), "show", "feat/h2:a.txt"), "fixed")
        self.assertEqual(body, BODY)

    def test_a_failing_hook_goes_into_the_body_and_the_pr_still_opens(self):
        hook = 'echo "SIM114 Combine if branches"\nexit 1\n'
        _, body, calls = self._finish_with_hooks("feat/h3", hook)
        self.assertEqual(len(calls), 2)
        self.assertTrue(body.startswith(BODY), body)
        self.assertIn("\n## Pre-commit hooks\n", body)
        self.assertIn("SIM114 Combine if branches", body)
        self.assertEqual(
            git("-C", str(self.remote), "log", "-1", "--format=%s", "feat/h3"),
            "feat: a",
        )

    def test_exit_statuses_match_the_header(self):
        """The header's Exit line: 2 for refusals, 1 for a missing argument,
        git's own status for a failing git command - never 0."""
        (self.tmp / "bare.md").write_text("body without the line\n", encoding="utf-8")
        # Naming the repo in passing (an issue link) is not the provenance line.
        (self.tmp / "mention.md").write_text(
            "see https://github.com/netresearch/retro-skill/issues/92\n",
            encoding="utf-8",
        )
        # The line itself, but quoted in another section: `## Came from` opens
        # with something else.
        (self.tmp / "elsewhere.md").write_text(
            "## Summary\n\n" + PROVENANCE + "\n## Came from\n\nFinding: B3\n",
            encoding="utf-8",
        )
        cases = [
            (("bogus",), 2, "usage"),
            (("finish", str(self.tmp), "t", "body.md"), 2, "never -A"),
            (("finish", str(self.tmp), "t", "missing.md", "a.txt"), 2, "body file"),
            (("finish", str(self.tmp), "t", "bare.md", "a.txt"), 2, "provenance"),
            (("finish", str(self.tmp), "t", "mention.md", "a.txt"), 2, "provenance"),
            (("finish", str(self.tmp), "t", "elsewhere.md", "a.txt"), 2, "provenance"),
            (("start",), 1, "repo-dir"),
            (("start", str(self.tmp / "no-such-repo"), "feat/x"), 128, "fatal"),
        ]
        for args, status, message in cases:
            with self.subTest(args=args):
                result = self._run(*args)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn(message, result.stderr)
        self.assertFalse(self.gh_log.exists(), "gh must not run on a refusal")


if __name__ == "__main__":
    unittest.main()
