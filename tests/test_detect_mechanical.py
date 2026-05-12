"""Smoke tests for scripts/detect-mechanical.py.

Builds tiny synthetic JSONL transcripts and asserts the detector fires the
expected signal. Not exhaustive — one synthetic case per implemented signal.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def load_detect_module():
    """Import scripts/detect-mechanical.py despite its hyphenated filename."""
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "scripts" / "detect-mechanical.py"
    spec = importlib.util.spec_from_file_location("detect_mechanical", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect = load_detect_module()


def write_jsonl(events: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for ev in events:
        tmp.write(json.dumps(ev) + "\n")
    tmp.close()
    return Path(tmp.name)


def user_msg(text: str) -> dict:
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def tool_use_pair(tool_id: str, name: str, input_: dict, result_text: str, is_error: bool = False) -> list[dict]:
    return [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": input_}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": result_text, "is_error": is_error}]}},
    ]


class TestSchichtA(unittest.TestCase):
    def assert_signal(self, events: list[dict], expected_signal: str):
        path = write_jsonl(events)
        try:
            events_loaded = detect.load_jsonl(path)
            user_texts = detect.extract_user_texts(events_loaded)
            tool_uses = detect.extract_tool_uses(events_loaded)
            findings = []
            for sid, func in detect.SIGNAL_FUNCS.items():
                if func in (detect.signal_user_corrections, detect.signal_prompt_repetition, detect.signal_prompt_sequence_repetition):
                    findings.extend(func(user_texts))
                elif func is detect.signal_skill_reminder_vs_invoke:
                    findings.extend(func(events_loaded))
                else:
                    findings.extend(func(tool_uses))
            signals = {f["signal"] for f in findings}
            self.assertIn(expected_signal, signals, f"expected {expected_signal} in {signals}")
        finally:
            path.unlink(missing_ok=True)

    def test_A1_tool_error(self):
        evs = tool_use_pair("u1", "Bash", {"command": "exit 1"}, "Exit code 1\nerror", is_error=True)
        self.assert_signal(evs, "A1")

    def test_A2_retry_cluster(self):
        evs = []
        for i in range(3):
            evs.extend(tool_use_pair(f"u{i}", "Bash", {"command": "echo hi"}, "hi"))
        self.assert_signal(evs, "A2")

    def test_A3_verbose_output(self):
        big = "x" * 10000
        evs = tool_use_pair("u1", "Bash", {"command": "cat huge"}, big)
        self.assert_signal(evs, "A3")

    def test_A6_user_correction(self):
        evs = [user_msg("no, that's wrong")]
        self.assert_signal(evs, "A6")

    def test_A7_prompt_repetition(self):
        evs = [user_msg("please run the tests now"), user_msg("please run the tests now")]
        self.assert_signal(evs, "A7")

    def test_A16_outdated_tool(self):
        evs = tool_use_pair("u1", "Bash", {"command": "npm i"}, "npm WARN deprecated: use yarn instead")
        self.assert_signal(evs, "A16")

    def test_A17_upstream_failure(self):
        evs = tool_use_pair("u1", "Bash", {"command": "git push origin main"}, "remote: rejected", is_error=True)
        self.assert_signal(evs, "A17")


class TestHelpers(unittest.TestCase):
    def test_extract_user_texts_handles_string_content(self):
        events = [{"type": "user", "message": {"content": "hello"}}]
        result = detect.extract_user_texts(events)
        self.assertEqual(result, [(0, "hello")])

    def test_extract_tool_uses_returns_5tuple_with_is_error(self):
        events = tool_use_pair("u1", "Read", {"file_path": "/x"}, "ok", is_error=False)
        result = detect.extract_tool_uses(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 5)
        i, name, inp, res, is_error = result[0]
        self.assertEqual(name, "Read")
        self.assertFalse(is_error)


if __name__ == "__main__":
    unittest.main()
