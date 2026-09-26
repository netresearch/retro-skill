"""Tests for skills/retro/scripts/mask-secrets.py and the fields it guards (#140).

Every credential-shaped sample is assembled at runtime from a prefix and filler,
so no string in this file looks like a live secret to a scanner.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "retro" / "scripts"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ms = _load("mask_secrets", "mask-secrets.py")
dm = _load("detect_mechanical", "detect-mechanical.py")
scs = _load("scan_cross_session", "scan-cross-session.py")
dss = _load("derive_session_scope", "derive-session-scope.py")

GH = "ghp_" + "Ab1" * 12
PEM_TYPE = "RSA " + "PRIVATE KEY"
PEM_BODY = "MIIE" + "q" * 60 + "\n" + "Zm9v" * 15

# One sample per alternative in ms.ALTERNATIVES; the secret part of each is
# SECRET_PART[name], which must be gone from the masked text.
SAMPLES = {
    "gitlab_pat": "token glpat-" + "x1Y2z3" * 4 + " end",
    "github_token": f"GH_TOKEN={GH} gh pr create",
    "github_fine_grained": "github_pat_" + "11AB" * 6 + "_" + "cd9" * 10,
    "sk_key": "key sk-ant-api03-" + "Q7w" * 12 + "-" + "Zz9" * 5 + "AA",
    "aws_access_key": "aws AKIA" + "IOSFODNN7EXAMPL" + "Q done",
    "slack_token": "slack xoxb-" + "1234-5678-" + "aBcD" * 4,
    "pem_private_key": f"-----BEGIN {PEM_TYPE}-----\n{PEM_BODY}\n-----END {PEM_TYPE}-----",
    "authorization_header": 'curl -H "Authorization: Bearer ' + "tk9" * 10 + '" x',
    "jwt": "jwt eyJ" + "hbGciOiJI" + ".eyJ" + "zdWIiOiIx" + "." + "SflKxwRJ" * 3,
    "url_credentials": "https://oauth2:" + "s3cr" * 5 + "@git.example.org/g/r.git",
    "private_token_header": "curl -H 'PRIVATE-" + "TOKEN: " + "tok3" * 6 + "' x",
    "curl_user": "curl -u sebastian:" + "hunt3r" * 3 + " https://x.example.org",
    "vault_token": "VAULT_TOKEN=hvs." + "CAES" + "Qx7" * 8,
    "npm_token": "npm_" + "Zx8" * 12,
    "google_api_key": "key AIza" + "Sy" + "Kq9" * 11,
    "aws_secret_key": "AWS_SECRET_" + "ACCESS_KEY=" + "Ab1/" * 10,
}
SECRET_PART = {
    "gitlab_pat": "x1Y2z3x1Y2z3",
    "github_token": GH[4:],
    "github_fine_grained": "11AB11AB",
    "sk_key": "Q7wQ7wQ7w",
    "aws_access_key": "IOSFODNN7EXAMPL",
    "slack_token": "aBcDaBcD",
    "pem_private_key": "Zm9vZm9v",
    "authorization_header": "tk9tk9",
    "jwt": "SflKxwRJ",
    "url_credentials": "s3cr",
    "private_token_header": "tok3tok3",
    "curl_user": "hunt3r",
    "vault_token": "Qx7Qx7",
    "npm_token": "Zx8Zx8",
    "google_api_key": "Kq9Kq9",
    "aws_secret_key": "Ab1/Ab1/",
}

NEGATIVES = [
    "ordinary text about a failing test and a retry",
    "commit 4f2a9c0e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39 on main",
    "uuid 123e4567-e89b-12d3-a456-426614174000",
    "task-runner and desk-top and sk-learn-compatible-transformer",
    "git@github.com:octo/repo.git",
    "ssh://git@host.example.org/x.git",
    "https://github.com/o/r/pull/1",
    "Authorization header missing",
    "AKIA is a prefix, AKIAshort is not a key",
    # One look-alike per alternative added for the review's A-F9.
    "PRIVATE-TOKEN header missing",
    'curl -H "PRIVATE-TOKEN: $GITLAB_TOKEN" and {"PRIVATE-TOKEN": token}',
    "curl -u sebastian https://x.example.org",
    "docker run -u 1000:1000 img and git push -u origin a:b",
    "hvs.short is no vault token",
    "npm_config_registry and npm_" + "a" * 20,
    "AIzaShort is no key",
    "AWS_SECRET_ACCESS_KEY=$SECRET",
    "https://example.org:8443/path@x",
]


class AlternativesTest(unittest.TestCase):
    def test_every_alternative_has_exactly_one_sample(self):
        # Adding an alternative without a sample, or dropping one, fails here.
        self.assertEqual(set(SAMPLES), set(ms.ALTERNATIVES))
        self.assertEqual(set(SECRET_PART), set(ms.ALTERNATIVES))

    def test_each_sample_matches_its_own_alternative(self):
        for name, sample in SAMPLES.items():
            with self.subTest(name):
                m = ms.SECRET.search(sample)
                self.assertIsNotNone(m)
                self.assertEqual(m.lastgroup, name)

    def test_each_sample_is_masked(self):
        for name, sample in SAMPLES.items():
            with self.subTest(name):
                self.assertIn(SECRET_PART[name], sample)
                out = ms.mask(sample)
                self.assertNotIn(SECRET_PART[name], out)
                self.assertIn(ms.MARKER, out)
                squeezed = ms.squeeze(sample, 1000)
                self.assertNotIn(SECRET_PART[name], squeezed)

    def test_negatives_are_left_alone(self):
        for text in NEGATIVES:
            with self.subTest(text):
                self.assertIsNone(ms.SECRET.search(text))
                self.assertEqual(ms.mask(text), text)

    def test_context_around_the_masked_value_stays_readable(self):
        self.assertEqual(
            ms.mask(SAMPLES["authorization_header"]),
            'curl -H "Authorization: Bearer [REDACTED]" x',
        )
        self.assertEqual(
            ms.mask(SAMPLES["url_credentials"]),
            "https://[REDACTED]@git.example.org/g/r.git",
        )

    def test_widened_alternatives_mask_the_reviews_forms(self):
        # A-F9: forms of two existing alternatives that shipped in clear.
        # The sample table holds one sample per alternative, so these stand here.
        password = "hunt" + "er2" * 4
        self.assertEqual(
            ms.mask('{"authorization":"Bearer ' + "abcd" * 4 + '1234"}'),
            '{"authorization":"Bearer [REDACTED]"}',
        )
        self.assertEqual(
            ms.mask(f"redis://:{password}@host:6379"), "redis://[REDACTED]@host:6379"
        )
        # An `@` in the password: nothing of it may follow the marker.
        self.assertEqual(
            ms.mask("https://user:p@" + "ss9x@host/"), "https://[REDACTED]@host/"
        )

    def test_pem_body_without_footer_is_masked(self):
        cut = f"-----BEGIN {PEM_TYPE}-----\n{PEM_BODY}"
        self.assertNotIn("Zm9v", ms.squeeze(cut, 1000))


class SqueezeOrderTest(unittest.TestCase):
    def test_token_straddling_the_limit_ships_no_head(self):
        text = "x" * 190 + " " + GH + " tail"
        head = GH[:12]
        # Truncating first leaves a head too short for the pattern to see:
        self.assertIn(head[:9], ms.mask(text[:200]))
        # squeeze masks first, so nothing of the token reaches the output.
        out = ms.squeeze(text, 200)
        self.assertEqual(len(out), 200)
        self.assertNotIn("ghp_", out)
        self.assertNotIn(GH[4:9], out)

    def test_whitespace_is_collapsed(self):
        self.assertEqual(ms.squeeze("  a\n\n b\t c  ", 100), "a b c")


class DetectMechanicalFieldsTest(unittest.TestCase):
    def _transcript(self, events: list[dict]) -> Path:
        tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 -- unlinked in cleanup
            mode="w", suffix=".jsonl", delete=False
        )
        for ev in events:
            tmp.write(json.dumps(ev) + "\n")
        tmp.close()
        path = Path(tmp.name)
        self.addCleanup(path.unlink)
        return path

    @staticmethod
    def _bash(tool_id: str, cmd: str, result: str, is_error: bool) -> list[dict]:
        use = {"type": "tool_use", "id": tool_id, "name": "Bash"}
        use["input"] = {"command": cmd}
        res = {"type": "tool_result", "tool_use_id": tool_id, "content": result}
        res["is_error"] = is_error
        return [
            {"type": "assistant", "message": {"content": [use]}},
            {"type": "user", "message": {"content": [res]}},
        ]

    def test_issue_140_failed_pr_create_prints_no_token(self):
        # The issue's reproduction: the token sits in the command and again in
        # the remote URL the error output echoes.
        cmd = f"GH_TOKEN={GH} gh pr create --title x --body y"
        err = (
            "Exit code 1\nfatal: unable to access "
            f"'https://x-access-token:{GH}@github.com/o/r.git/': 403"
        )
        path = self._transcript(self._bash("t1", cmd, err, True))
        out = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "detect-mechanical.py"),
                "--transcript-file",
                str(path),
                "--signals",
                "A17",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        finding = json.loads(out)["findings"][0]
        self.assertEqual(finding["signal"], "A17")
        self.assertNotIn(GH[4:12], out)
        self.assertNotIn(GH[-8:], out)
        self.assertIn("GH_TOKEN=[REDACTED] gh pr create", finding["command"])
        self.assertIn("https://[REDACTED]@github.com", finding["stderr"])

    def test_every_snippet_signal_masks(self):
        aws = "AKIA" + "IOSFODNN7EXAMPL" + "Q"
        tool_uses = [
            (0, "Bash", {"command": f"GH_TOKEN={GH} git push origin main"}, "", True),
            (1, "Bash", {"command": f"cat x.json | grep {GH} a.json"}, "", False),
            (2, "Bash", {"command": f"cat {GH}.py"}, "", False),
            (
                3,
                "Bash",
                {"command": f"git commit -m 'Generated with Claude {GH}'"},
                "",
                0,
            ),
            (4, "Bash", {"command": "x"}, f"warning: deprecated {GH}", False),
            (
                5,
                "Bash",
                {"command": f"until [ $pending == 0 ]; do sleep 1 {GH}"},
                "",
                0,
            ),
        ]
        findings = (
            dm.signal_tool_errors(tool_uses)
            + dm.signal_main_branch_work(tool_uses)
            + dm.signal_wrong_tool_choice(tool_uses)
            + dm.signal_bot_attribution(tool_uses)
            + dm.signal_outdated_tool(tool_uses)
            + dm.signal_upstream_failure(tool_uses)
            + dm.signal_wait_loop_inefficiency(tool_uses)
            + dm.signal_skipped_verification([(9, f"All tests pass {aws}")], [])
            + dm.signal_user_corrections([(8, f"No, wrong key {aws}")])
        )
        signals = {f["signal"] for f in findings}
        expected = {"A1", "A6", "A11", "A13", "A14", "A15", "A16", "A17", "A20"}
        self.assertEqual(signals, expected)
        self.assertEqual(
            {f["name"] for f in findings if f["signal"] == "A11"},
            {"structured_file_misuse", "cat_instead_of_read"},
        )
        dumped = json.dumps(findings)
        self.assertNotIn(GH[4:12], dumped)
        self.assertNotIn("IOSFODNN", dumped)

    def test_prompt_keys_are_masked_before_lowercasing(self):
        aws = "AKIA" + "IOSFODNN7EXAMPL" + "Q"
        texts = [(i, f"please use key {aws} for step {i % 2}") for i in range(4)]
        findings = dm.signal_prompt_repetition(texts)
        findings += dm.signal_prompt_sequence_repetition(texts, n=2)
        self.assertEqual({f["signal"] for f in findings}, {"A7", "A8"})
        dumped = json.dumps(findings)
        self.assertNotIn("iosfodnn", dumped)
        self.assertIn("[redacted]", dumped)

    def test_permission_prefix_is_masked(self):
        tool_uses = [
            (i * 20, "Bash", {"command": f"GH_TOKEN={GH} gh pr view"}, "", False)
            for i in range(3)
        ]
        findings = dm.signal_permission_reapproval(tool_uses)
        self.assertEqual([f["prefix"] for f in findings], ["GH_TOKEN=[REDACTED] gh"])


class ScanCrossSessionFieldsTest(unittest.TestCase):
    def test_correction_key_masks_before_lowercasing(self):
        key = scs._correction_key("No, use AKIA" + "IOSFODNN7EXAMPL" + "Q instead")
        self.assertNotIn("iosfodnn", key)
        self.assertIn("[redacted]", key)

    def test_failure_key_and_example_are_masked(self):
        call = {
            "name": "Bash",
            "result": f"Exit code 128\nfatal: auth failed for https://u:{GH}@h.example.org/r",
            "is_error": True,
        }
        reason, key, line = scs._failure_key(call, False)
        self.assertIsNone(reason)
        self.assertNotIn(GH[4:9], json.dumps([key, line]))
        # Outside a URL the marker survives normalise(): no digits, no hex
        # run, no slash. (Inside one, PATH_RE folds it into `<path>`.)
        call["result"] = f"Exit code 1\nerror: bad credentials {GH} rejected"
        reason, key, line = scs._failure_key(call, False)
        self.assertIsNone(reason)
        self.assertEqual(key[2], "error: bad credentials [REDACTED] rejected")
        self.assertEqual(line, "error: bad credentials [REDACTED] rejected")


class DeriveSessionScopeFieldsTest(unittest.TestCase):
    def test_unresolved_forge_command_is_masked(self):
        events = DetectMechanicalFieldsTest._bash(
            "t0", f"GH_TOKEN={GH} gh pr edit --add-label x", "", False
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            data = dss.collect_artefacts(path)
        self.assertEqual(
            data["unresolved_forge_commands"],
            ["GH_TOKEN=[REDACTED] gh pr edit --add-label x"],
        )


if __name__ == "__main__":
    unittest.main()
