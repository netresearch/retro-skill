"""Unit tests for skills/retro/scripts/validate-evals.py.

Each test builds its own tiny synthetic ``evals/`` directory in a temp dir (no
shared fixture) and asserts the validator accepts well-formed scenarios and
rejects malformed ones.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


def load_validator():
    """Import skills/retro/scripts/validate-evals.py despite its hyphenated filename."""
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "skills" / "retro" / "scripts" / "validate-evals.py"
    spec = importlib.util.spec_from_file_location("validate_evals", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()


VALID = """---
id: {id}
skill_under_test: retro
mode: sweep
trigger: "a friction happened"
expected:
  - classify correctly
  - propose a bounded edit
negative_expected:
  - invent a broad rule
---
Prose rationale.
"""


def write_scenario(directory: Path, scenario_id: str, body: str | None = None) -> None:
    content = body if body is not None else VALID.format(id=scenario_id)
    (directory / f"{scenario_id}.md").write_text(content, encoding="utf-8")


class ValidateEvalsTest(unittest.TestCase):
    def _dir(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_accepts_well_formed_corpus(self):
        directory = self._dir()
        for i in range(5):
            write_scenario(directory, f"scenario-{i}")
        self.assertEqual(validator.validate(directory, min_scenarios=5), [])

    def test_readme_is_ignored(self):
        directory = self._dir()
        for i in range(5):
            write_scenario(directory, f"scenario-{i}")
        (directory / "README.md").write_text("# not a scenario", encoding="utf-8")
        self.assertEqual(validator.validate(directory, min_scenarios=5), [])

    def test_json_layout_is_named_instead_of_counted_as_empty(self):
        directory = self._dir()
        (directory / "evals.json").write_text(
            '{"skill_name": "other", "evals": [{"id": 1}]}', encoding="utf-8"
        )
        problems = validator.validate(directory, min_scenarios=5)
        self.assertEqual(len(problems), 1)
        self.assertIn("holds JSON evals", problems[0])
        self.assertIn("repo-scoped", problems[0])
        self.assertNotIn("too few scenarios", problems[0])

    def test_unrelated_json_is_not_mistaken_for_an_eval_corpus(self):
        directory = self._dir()
        (directory / "package.json").write_text(
            '{"name": "some-repo", "version": "1.0.0"}', encoding="utf-8"
        )
        problems = validator.validate(directory, min_scenarios=5)
        self.assertEqual(problems, ["too few scenarios: found 0, need >= 5"])

    def test_json_layout_is_recognised_under_any_filename(self):
        directory = self._dir()
        (directory / "comprehensive-evals.json").write_text(
            '[{"name": "a", "prompt": "b"}]', encoding="utf-8"
        )
        problems = validator.validate(directory, min_scenarios=5)
        self.assertEqual(len(problems), 1)
        self.assertIn("holds JSON evals", problems[0])

    def test_markdown_scenarios_win_over_a_stray_json_file(self):
        directory = self._dir()
        for i in range(5):
            write_scenario(directory, f"scenario-{i}")
        (directory / "config.json").write_text("{}", encoding="utf-8")
        self.assertEqual(validator.validate(directory, min_scenarios=5), [])

    def test_too_few_scenarios(self):
        directory = self._dir()
        for i in range(3):
            write_scenario(directory, f"scenario-{i}")
        errors = validator.validate(directory, min_scenarios=5)
        self.assertTrue(any("too few" in e for e in errors), errors)

    def test_missing_negative_expected(self):
        directory = self._dir()
        for i in range(4):
            write_scenario(directory, f"scenario-{i}")
        body = (
            "---\n"
            "id: bad\n"
            "skill_under_test: retro\n"
            'trigger: "x"\n'
            "expected:\n"
            "  - do the thing\n"
            "---\n"
            "no negatives.\n"
        )
        write_scenario(directory, "bad", body)
        errors = validator.validate(directory, min_scenarios=5)
        self.assertTrue(any("negative_expected" in e for e in errors), errors)

    def test_filename_id_mismatch(self):
        directory = self._dir()
        for i in range(4):
            write_scenario(directory, f"scenario-{i}")
        write_scenario(directory, "wrongname", VALID.format(id="different-id"))
        errors = validator.validate(directory, min_scenarios=5)
        self.assertTrue(any("does not match filename" in e for e in errors), errors)

    def test_missing_frontmatter(self):
        directory = self._dir()
        for i in range(4):
            write_scenario(directory, f"scenario-{i}")
        write_scenario(directory, "plain", "# just markdown, no frontmatter\n")
        errors = validator.validate(directory, min_scenarios=5)
        self.assertTrue(any("frontmatter" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
