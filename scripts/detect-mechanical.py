#!/usr/bin/env python3
"""
detect-mechanical.py — Schicht A mechanical friction detector for retro-skill.

Reads a Claude Code session transcript (JSONL) and emits a structured list of
mechanical friction candidates. Output is JSON, consumed by the LLM in Schicht B.

Usage:
    python3 detect-mechanical.py --transcript-file <path> [--output-format json]
    python3 detect-mechanical.py --transcript-file <path> --signals A1,A6,A17

Signals implemented (subset of friction-catalog.md):
    A1  Tool errors
    A2  Tool retry clusters
    A3  Tool output verbosity
    A6  User correction phrases
    A7  Prompt repetition (exact)
    A8  Prompt sequence repetition
    A9  Tool sequence repetition
    A10 Skill in reminder vs invoke
    A12 Re-read same file
    A14 Worked on main/master
    A15 Bot attribution in commit
    A16 Outdated tool warnings
    A17 Upstream failure (git push / gh pr checks)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


CORRECTION_PATTERNS = re.compile(
    r"^\s*(no\b|nein\b|stop\b|don't\b|wrong\b|NEIN\b|nicht so\b)",
    re.IGNORECASE | re.MULTILINE,
)
ALL_CAPS_RUN = re.compile(r"[A-ZÄÖÜ]{4,}")
MULTIPLE_EXCLAIM = re.compile(r"!{3,}")
BOT_ATTRIBUTION = re.compile(
    r"(Generated with Claude|Co-Authored-By:\s*Claude|🤖)",
    re.IGNORECASE,
)
OUTDATED_TOOL = re.compile(
    r"\b(deprecated|is now|use\s+\S+\s+instead|no longer supported)\b",
    re.IGNORECASE,
)
GIT_BRANCH_MAIN = re.compile(r"\b(?:main|master)\b")
GIT_CHECKOUT_B = re.compile(r"git\s+checkout\s+-b\b|git\s+switch\s+-c\b|git\s+worktree\s+add\s+-b\b")
LARGE_TOOL_RESULT_BYTES = 5000
DEFAULT_RETRY_WINDOW = 5  # turns
DEFAULT_SEQ_NGRAM = 3


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def extract_user_texts(events: Iterable[dict]) -> list[tuple[int, str]]:
    out = []
    for i, ev in enumerate(events):
        if ev.get("type") != "user":
            continue
        msg = ev.get("message", {})
        content = msg.get("content")
        if isinstance(content, str):
            out.append((i, content))
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    out.append((i, block.get("text", "")))
    return out


def extract_tool_uses(events: Iterable[dict]) -> list[tuple[int, str, dict, str, bool]]:
    """Yield (event_index, tool_name, input, result_text, is_error)."""
    out = []
    tool_uses_pending: dict[str, tuple[int, str, dict]] = {}
    for i, ev in enumerate(events):
        msg = ev.get("message", {})
        content = msg.get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_uses_pending[block["id"]] = (i, block["name"], block.get("input", {}))
            elif block.get("type") == "tool_result":
                use_id = block.get("tool_use_id")
                if use_id in tool_uses_pending:
                    i_use, name, inp = tool_uses_pending.pop(use_id)
                    result = block.get("content", "")
                    if isinstance(result, list):
                        result = " ".join(
                            b.get("text", "") if isinstance(b, dict) else str(b) for b in result
                        )
                    is_error = block.get("is_error", False)
                    out.append((i_use, name, inp, str(result), bool(is_error)))
    return out


def signal_tool_errors(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if is_error or "error" in result.lower()[:200]:
            out.append({
                "signal": "A1",
                "name": "tool_error",
                "turn": i,
                "tool": name,
                "snippet": result[:200],
            })
    return out


def signal_retry_clusters(tool_uses, window: int = DEFAULT_RETRY_WINDOW) -> list[dict]:
    out = []
    by_tool: dict[str, list[int]] = defaultdict(list)
    for i, name, inp, result, is_error in tool_uses:
        by_tool[name].append(i)
    for name, turns in by_tool.items():
        if len(turns) < 3:
            continue
        # Detect 3+ within window
        for j in range(len(turns) - 2):
            if turns[j + 2] - turns[j] <= window * 2:
                out.append({
                    "signal": "A2",
                    "name": "tool_retry_cluster",
                    "tool": name,
                    "turns": turns[j:j + 3],
                })
                break
    return out


def signal_verbose_results(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if len(result) > LARGE_TOOL_RESULT_BYTES:
            out.append({
                "signal": "A3",
                "name": "verbose_tool_output",
                "turn": i,
                "tool": name,
                "bytes": len(result),
            })
    return out


def signal_user_corrections(user_texts) -> list[dict]:
    out = []
    for i, text in user_texts:
        if CORRECTION_PATTERNS.search(text):
            out.append({"signal": "A6", "name": "user_correction", "turn": i, "snippet": text[:200]})
        elif ALL_CAPS_RUN.search(text) and len(text) < 500:
            out.append({"signal": "A6", "name": "all_caps_emphasis", "turn": i, "snippet": text[:200]})
        elif MULTIPLE_EXCLAIM.search(text):
            out.append({"signal": "A6", "name": "exclamation_emphasis", "turn": i, "snippet": text[:200]})
    return out


def signal_prompt_repetition(user_texts) -> list[dict]:
    """Exact (normalized) prompt repetition detector."""
    out = []
    seen: dict[str, list[int]] = defaultdict(list)
    for i, text in user_texts:
        key = re.sub(r"\s+", " ", text.strip().lower())[:200]
        if len(key) < 10:
            continue
        seen[key].append(i)
    for key, turns in seen.items():
        if len(turns) >= 2:
            out.append({
                "signal": "A7",
                "name": "prompt_repetition",
                "turns": turns,
                "snippet": key[:200],
            })
    return out


def signal_prompt_sequence_repetition(user_texts, n: int = DEFAULT_SEQ_NGRAM) -> list[dict]:
    out = []
    if len(user_texts) < n * 2:
        return out
    norm = [re.sub(r"\s+", " ", t[1].strip().lower())[:60] for t in user_texts]
    counter: Counter[tuple[str, ...]] = Counter()
    for i in range(len(norm) - n + 1):
        ngram = tuple(norm[i:i + n])
        if all(len(s) > 5 for s in ngram):
            counter[ngram] += 1
    for ngram, cnt in counter.items():
        if cnt >= 2:
            out.append({
                "signal": "A8",
                "name": "prompt_sequence_repetition",
                "count": cnt,
                "ngram": list(ngram),
            })
    return out


def signal_tool_sequence_repetition(tool_uses, n: int = DEFAULT_SEQ_NGRAM) -> list[dict]:
    out = []
    if len(tool_uses) < n * 2:
        return out
    names = [t[1] for t in tool_uses]
    counter: Counter[tuple[str, ...]] = Counter()
    for i in range(len(names) - n + 1):
        counter[tuple(names[i:i + n])] += 1
    for ngram, cnt in counter.items():
        if cnt >= 2:
            out.append({
                "signal": "A9",
                "name": "tool_sequence_repetition",
                "count": cnt,
                "ngram": list(ngram),
            })
    return out


def signal_skill_reminder_vs_invoke(events) -> list[dict]:
    out = []
    for i, ev in enumerate(events):
        msg = ev.get("message", {}) or {}
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
        else:
            text = str(content)
        matches = re.findall(r"<command-name>([^<]+)</command-name>", text)
        if not matches:
            continue
        # Look at next 3 events for Skill tool invocation
        invoked = False
        for j in range(i + 1, min(i + 4, len(events))):
            content_j = events[j].get("message", {}).get("content", [])
            if isinstance(content_j, list):
                for block in content_j:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
                        invoked = True
                        break
            if invoked:
                break
        if not invoked:
            out.append({
                "signal": "A10",
                "name": "skill_reminder_not_invoked",
                "turn": i,
                "skills_mentioned": matches,
            })
    return out


def signal_reread_same_file(tool_uses) -> list[dict]:
    out = []
    reads: dict[str, list[int]] = defaultdict(list)
    edits: dict[str, list[int]] = defaultdict(list)
    for i, name, inp, result, is_error in tool_uses:
        if name == "Read":
            reads[inp.get("file_path", "")].append(i)
        elif name in ("Edit", "Write", "MultiEdit"):
            edits[inp.get("file_path", "")].append(i)
    for path, read_turns in reads.items():
        if len(read_turns) < 2:
            continue
        # Check if there was an Edit between any two consecutive reads
        edit_turns = sorted(edits.get(path, []))
        suspicious = False
        for a, b in zip(read_turns, read_turns[1:]):
            if not any(a < e < b for e in edit_turns):
                suspicious = True
                break
        if suspicious:
            out.append({
                "signal": "A12",
                "name": "reread_without_edit",
                "path": path,
                "turns": read_turns,
            })
    return out


def signal_main_branch_work(tool_uses) -> list[dict]:
    out = []
    saw_branch = False
    for i, name, inp, result, is_error in tool_uses:
        if name != "Bash":
            continue
        cmd = inp.get("command", "")
        if GIT_CHECKOUT_B.search(cmd):
            saw_branch = True
            continue
        if not saw_branch and re.search(r"\bgit\s+(add|commit|push)\b", cmd) and GIT_BRANCH_MAIN.search(cmd + " " + result):
            out.append({
                "signal": "A14",
                "name": "git_op_without_branch",
                "turn": i,
                "command": cmd[:200],
            })
    return out


def signal_bot_attribution(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if name != "Bash":
            continue
        cmd = inp.get("command", "")
        if "git commit" in cmd and BOT_ATTRIBUTION.search(cmd):
            out.append({
                "signal": "A15",
                "name": "bot_attribution_in_commit",
                "turn": i,
                "snippet": cmd[:300],
            })
    return out


def signal_outdated_tool(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if OUTDATED_TOOL.search(result[:1000]):
            out.append({
                "signal": "A16",
                "name": "outdated_tool_warning",
                "turn": i,
                "tool": name,
                "snippet": result[:300],
            })
    return out


def signal_upstream_failure(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if name != "Bash":
            continue
        cmd = inp.get("command", "")
        if is_error and re.search(r"\bgit\s+push\b|\bgh\s+pr\s+(checks|create|merge)\b|\bglab\s+mr\b", cmd):
            out.append({
                "signal": "A17",
                "name": "upstream_failure",
                "turn": i,
                "command": cmd[:200],
                "stderr": result[:500],
            })
    return out


SIGNAL_FUNCS = {
    "A1": signal_tool_errors,
    "A2": signal_retry_clusters,
    "A3": signal_verbose_results,
    "A6": signal_user_corrections,
    "A7": signal_prompt_repetition,
    "A8": signal_prompt_sequence_repetition,
    "A9": signal_tool_sequence_repetition,
    "A10": signal_skill_reminder_vs_invoke,
    "A12": signal_reread_same_file,
    "A14": signal_main_branch_work,
    "A15": signal_bot_attribution,
    "A16": signal_outdated_tool,
    "A17": signal_upstream_failure,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript-file", required=True, type=Path)
    parser.add_argument("--output-format", choices=["json", "text"], default="json")
    parser.add_argument("--signals", default=",".join(SIGNAL_FUNCS.keys()),
                        help="Comma-separated signal IDs to run (default: all)")
    args = parser.parse_args()

    if not args.transcript_file.exists():
        print(f"Transcript not found: {args.transcript_file}", file=sys.stderr)
        return 2

    events = load_jsonl(args.transcript_file)
    user_texts = extract_user_texts(events)
    tool_uses = extract_tool_uses(events)

    selected = {s.strip() for s in args.signals.split(",") if s.strip()}
    findings = []
    for sid, func in SIGNAL_FUNCS.items():
        if sid not in selected:
            continue
        # Dispatch arg shape
        if func in (signal_user_corrections, signal_prompt_repetition, signal_prompt_sequence_repetition):
            findings.extend(func(user_texts))
        elif func is signal_skill_reminder_vs_invoke:
            findings.extend(func(events))
        else:
            findings.extend(func(tool_uses))

    summary = {
        "transcript": str(args.transcript_file),
        "events_total": len(events),
        "user_messages": len(user_texts),
        "tool_uses": len(tool_uses),
        "findings_total": len(findings),
        "findings": findings,
    }
    if args.output_format == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Transcript: {summary['transcript']}")
        print(f"Events: {summary['events_total']}  User msgs: {summary['user_messages']}  Tool uses: {summary['tool_uses']}")
        print(f"Findings: {summary['findings_total']}")
        for f in findings:
            print(f"  - [{f['signal']}] {f['name']}: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
