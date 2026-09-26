"""Unit tests for skills/retro/scripts/check-eval-samples.py.

Both directions are asserted throughout: an eval added or tightened without
``samples`` is rejected, and the same eval WITH samples is accepted, so a
checker that refused everything would fail these tests. The last two cases
drive ``materialize-pr.sh finish`` itself, which is where the refusal is a
control rather than a lint.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "retro" / "scripts"


def load_checker():
    """Import check-eval-samples.py despite its hyphenated filename."""
    src = SCRIPTS / "check-eval-samples.py"
    spec = importlib.util.spec_from_file_location("check_eval_samples", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load_checker()

ASSERTIONS = [{"type": "content", "pattern": "git worktree add"}]
SAMPLES = {"passing": "run git worktree add", "failing": ["run git checkout"]}


def eval_record(name: str, *, samples: bool = False, pattern: str | None = None):
    record = {
        "eval_name": name,
        "prompt": "how do I isolate a branch?",
        "assertions": [{"type": "content", "pattern": pattern or "git worktree add"}],
    }
    if samples:
        record["samples"] = dict(SAMPLES)
    return record


class CheckEvalSamplesTest(unittest.TestCase):
    def _repo(self, base_evals: list[dict] | None) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        for key, value in (("user.email", "t@example.com"), ("user.name", "T")):
            subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
        (repo / "evals").mkdir()
        if base_evals is not None:
            self._write(repo, base_evals)
        else:
            (repo / "README.md").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "base", "--no-gpg-sign"],
            check=True,
        )
        return repo

    @staticmethod
    def _write(repo: Path, evals: list[dict]) -> None:
        payload = {"skill_name": "demo", "evals": evals}
        (repo / "evals" / "evals.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def _check(self, repo: Path) -> list[str]:
        return checker.check_file(repo, "HEAD", "evals/evals.json")

    # --- new eval, both directions ---

    def test_new_eval_without_samples_is_rejected(self):
        repo = self._repo([eval_record("existing", samples=True)])
        self._write(repo, [eval_record("existing", samples=True), eval_record("added")])
        problems = self._check(repo)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("eval_name=added", problems[0])
        self.assertIn("new eval", problems[0])

    def test_new_eval_with_samples_is_accepted(self):
        repo = self._repo([eval_record("existing", samples=True)])
        self._write(
            repo,
            [eval_record("existing", samples=True), eval_record("added", samples=True)],
        )
        self.assertEqual(self._check(repo), [])

    # --- tightened eval, both directions ---

    def test_tightened_assertions_without_samples_are_rejected(self):
        repo = self._repo([eval_record("existing")])
        self._write(repo, [eval_record("existing", pattern="git worktree add -b")])
        problems = self._check(repo)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("tightened assertions", problems[0])

    def test_tightened_assertions_with_samples_are_accepted(self):
        repo = self._repo([eval_record("existing")])
        self._write(
            repo,
            [eval_record("existing", pattern="git worktree add -b", samples=True)],
        )
        self.assertEqual(self._check(repo), [])

    # --- what must stay untouched ---

    def test_existing_eval_without_samples_is_left_alone(self):
        """The 485 evals that carry no samples must keep passing untouched."""
        repo = self._repo([eval_record("existing"), eval_record("other")])
        self._write(repo, [eval_record("existing"), eval_record("other")])
        self.assertEqual(self._check(repo), [])

    def test_new_file_of_untouched_evals_is_still_checked(self):
        repo = self._repo(None)
        self._write(repo, [eval_record("first")])
        problems = self._check(repo)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("new eval", problems[0])

    def test_expectations_only_eval_is_not_asked_for_samples(self):
        """No pattern means nothing for the grader to grep - and validate-evals.sh
        rejects samples no assertion backs, so demanding them would be wrong."""
        repo = self._repo(None)
        self._write(
            repo,
            [
                {
                    "eval_name": "judged",
                    "prompt": "p",
                    "expectations": ["the answer names the worktree command"],
                }
            ],
        )
        self.assertEqual(self._check(repo), [])

    def test_value_only_assertion_counts_as_pattern_bearing(self):
        """`value` is a pattern key, because the gate this mirrors treats it as
        one: validate-evals.sh builds the list the samples requirement reads
        from `a.get("pattern") or a.get("value")`. Dropping `value` here would
        let a value-only eval past this check and straight into a CI failure
        the local run said was fine."""
        repo = self._repo(None)
        self._write(
            repo,
            [
                {
                    "eval_name": "value_only",
                    "prompt": "p",
                    "assertions": [
                        {"type": "content", "value": "bun install"},
                        {"type": "must_not", "value": "npm install"},
                    ],
                }
            ],
        )
        problems = self._check(repo)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("value_only", problems[0])

    def test_legacy_array_container_is_understood(self):
        repo = self._repo(None)
        (repo / "evals" / "evals.json").write_text(
            json.dumps([{"name": "a", "prompt": "p", "assertions": ASSERTIONS}]) + "\n",
            encoding="utf-8",
        )
        problems = self._check(repo)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("name=a", problems[0])

    def test_non_eval_json_is_skipped(self):
        repo = self._repo(None)
        (repo / "package.json").write_text('{"name": "x"}\n', encoding="utf-8")
        self.assertEqual(checker.check_file(repo, "HEAD", "package.json"), [])

    def test_missing_file_is_skipped(self):
        repo = self._repo(None)
        self.assertEqual(checker.check_file(repo, "HEAD", "nope.json"), [])

    def test_option_like_revision_is_not_read_as_a_git_flag(self):
        """A revision starting with '-' is data, not an option.

        Without ``--end-of-options`` git reads ``--output=<file>`` as its own
        diff option and writes that file - an argument injection, since the
        revision reaches this script as an agent-composed CLI argument.
        """
        repo = self._repo(None)
        self._write(repo, [eval_record("added")])
        target = repo / "pwned"
        base = f"--output={target}"
        self.assertIsNone(checker._base_text(repo, base, "evals.json"))
        written = list(repo.glob("pwned*"))
        self.assertEqual(written, [], f"git wrote {written} from an injected option")

    def test_option_shaped_revision_never_reaches_git(self):
        """The allowlist refuses before the subprocess, not after it."""
        repo = self._repo(None)
        calls = []

        def explode(*args, **kwargs):
            calls.append(args)
            raise AssertionError("git must not be invoked for a rejected revision")

        original = checker.subprocess.run
        checker.subprocess.run = explode
        self.addCleanup(setattr, checker.subprocess, "run", original)
        self.assertIsNone(checker._base_text(repo, "--output=/tmp/x", "evals.json"))
        self.assertIsNone(checker._base_text(repo, "HEAD", "-evals.json"))
        self.assertEqual(calls, [])

    def test_git_dir_in_the_environment_does_not_redirect_the_read(self):
        """A git hook exports GIT_DIR; `-C <repo>` must still read <repo>."""
        repo = self._repo([eval_record("base")])
        other = self._repo(None)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(other / ".git")}):
            text = checker._base_text(repo, "HEAD", "evals/evals.json")
        self.assertIsNotNone(text)
        self.assertIn('"base"', text)

    def test_git_is_called_with_end_of_options(self):
        """Second half of the same guard: whatever passes the allowlist is still
        handed to git behind --end-of-options."""
        repo = self._repo(None)
        seen = []

        def record(argv, **kwargs):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 1, "", "")

        original = checker.subprocess.run
        checker.subprocess.run = record
        self.addCleanup(setattr, checker.subprocess, "run", original)
        checker._base_text(repo, "HEAD", "evals/evals.json")
        self.assertEqual(len(seen), 1, seen)
        self.assertIn("--end-of-options", seen[0])
        self.assertLess(
            seen[0].index("--end-of-options"),
            seen[0].index("HEAD:evals/evals.json"),
        )

    # --- wiring: the refusal must happen on materialize-pr.sh's path ---

    def _finish(self, repo: Path):
        body = repo / "body.md"
        body.write_text("body\n", encoding="utf-8")
        return subprocess.run(
            [
                "bash",
                str(SCRIPTS / "materialize-pr.sh"),
                "finish",
                str(repo),
                "feat: add an eval",
                str(body),
                "evals/evals.json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_finish_refuses_a_new_eval_without_samples(self):
        repo = self._repo(None)
        self._write(repo, [eval_record("added")])
        result = self._finish(repo)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("without samples", result.stderr)
        staged = subprocess.run(
            ["git", "-C", str(repo), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(staged.stdout.strip(), "", "refusal must stage nothing")

    def test_finish_gets_past_the_check_when_samples_are_present(self):
        """Proves the guard is not a blanket refusal: with samples the run
        reaches the git/gh steps and fails there instead (no remote here)."""
        repo = self._repo(None)
        self._write(repo, [eval_record("added", samples=True)])
        result = self._finish(repo)
        self.assertNotIn("without samples", result.stderr)


if __name__ == "__main__":
    unittest.main()
