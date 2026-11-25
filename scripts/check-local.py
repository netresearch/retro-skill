#!/usr/bin/env -S uv run --script
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML==6.0.4"]
# ///

"""Run the checks CI runs on a pull request, as far as they run locally.

1. The test command of .github/workflows/lint.yml, read from that file and run
   the way ci-python.yml runs it, on the first Python version of its matrix
   (--all-pythons: on every version).
2. Every pre-commit hook over every tracked file. With --files, pre-commit
   skips validate-skill when none of its trigger files is listed. The fixer
   hooks (trailing-whitespace, end-of-file-fixer, ruff-format) rewrite files.
3. Untracked files fail the run: pre-commit does not see them.

Every step runs even when an earlier one failed; the exit code is 1 when any
did. Not covered: the hooks run at the revisions pinned in
.pre-commit-config.yaml, while CI calls the reusable workflows at @main. The
plugin version format, composer schema, checkpoint schema, harness, template
drift, security, eval-sample, SonarCloud and DCO checks run in CI only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_lint(repo: Path) -> tuple[str, list[str]]:
    """The test command and the Python versions lint.yml gives ci-python.yml."""
    import yaml

    path = repo / ".github" / "workflows" / "lint.yml"
    try:
        inputs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["test"][
            "with"
        ]
        command, versions = (
            inputs["test-command"],
            json.loads(inputs["python-versions"]),
        )
    except (KeyError, TypeError) as error:
        raise SystemExit(f"{path}: no test-command or python-versions: {error}")
    if not command.strip() or not versions:
        raise SystemExit(f"{path}: empty test-command or python-versions")
    return command, versions


def clean_env() -> dict[str, str]:
    """The environment without the virtualenv `uv run --script` put in it.

    The steps start `uv run --python X`, which would otherwise find this
    script's environment.
    """
    env = dict(os.environ)
    venv = env.pop("VIRTUAL_ENV", None)
    if venv:
        own = str(Path(venv) / "bin")
        env["PATH"] = os.pathsep.join(
            p for p in env.get("PATH", "").split(os.pathsep) if p != own
        )
    return env


def run_test_command(command: str, version: str, repo: Path) -> bool:
    env = clean_env() | {
        "PYTHON_VERSION": version,
        "UV_PYTHON": version,
        "TEST_COMMAND": command,
    }
    # ci-python.yml: `run: eval "$TEST_COMMAND"` in GitHub's default bash -e.
    done = subprocess.run(
        ["bash", "-e", "-c", 'eval "$TEST_COMMAND"'], cwd=repo, env=env, check=False
    )
    return done.returncode == 0


def run_pre_commit(repo: Path) -> bool:
    command = ["pre-commit", "run", "--all-files"]
    try:
        return (
            subprocess.run(command, cwd=repo, env=clean_env(), check=False).returncode
            == 0
        )
    except FileNotFoundError:
        print("pre-commit is not installed", flush=True)
        return False


def no_untracked(repo: Path) -> bool:
    listed = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if listed:
        print(f"git add these first, or no hook checks them:\n{listed}", flush=True)
    return not listed


def main(argv: list[str] | None = None, repo: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--all-pythons", action="store_true", help="every Python version of the matrix"
    )
    args = parser.parse_args(argv)
    command, versions = read_lint(repo)
    results = []
    for version in versions if args.all_pythons else versions[:1]:
        passed = run_test_command(command, version, repo)
        results.append((f"lint.yml test command, Python {version}", passed))
    results.append(("pre-commit run --all-files", run_pre_commit(repo)))
    results.append(("no untracked files", no_untracked(repo)))
    print()
    for name, passed in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    return 0 if all(passed for _, passed in results) else 1


if __name__ == "__main__":
    sys.exit(main())
