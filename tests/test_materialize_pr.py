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

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "retro" / "scripts" / "materialize-pr.sh"

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
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
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
        body = self.tmp / "body.md"
        body.write_text("body\n", encoding="utf-8")
        result = self._run("finish", str(worktree), "feat: a", str(body), "a.txt")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = [
            line[4:]
            for line in self.gh_log.read_text(encoding="utf-8").splitlines()
            if line.startswith("arg=")
        ]
        self.assertIn("--head", args)
        self.assertEqual(args[args.index("--head") + 1], "feat/x")
        self.assertEqual(
            git("-C", str(self.remote), "log", "-1", "--format=%s", "feat/x"), "feat: a"
        )


if __name__ == "__main__":
    unittest.main()
