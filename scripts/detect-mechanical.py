#!/usr/bin/env python3
"""
detect-mechanical.py — Schicht A mechanical friction detector for retro-skill.

Reads a Claude Code session transcript (JSONL) and emits a structured list of
mechanical friction candidates. Output is JSON, consumed by the LLM in Schicht B.

Usage:
    python3 detect-mechanical.py --transcript-file <path> [--output-format json]
    python3 detect-mechanical.py --transcript-file <path> --signals A1,A6,A17

Signals implemented (Schicht A — full catalog):
    A1  Tool errors
    A2  Tool retry clusters
    A3  Tool output verbosity
    A4  Tool call count vs task (inefficiency ratio)
    A5  Sequential calls that could be parallel
    A6  User correction phrases
    A7  Prompt repetition (exact)
    A8  Prompt sequence repetition
    A9  Tool sequence repetition
    A10 Skill in reminder vs invoke
    A11 Wrong tool choice (grep/sed on structured files)
    A12 Re-read same file
    A13 Skipped verification (claim without prior test/build)
    A14 Worked on main/master
    A15 Bot attribution in commit
    A16 Outdated tool warnings
    A17 Upstream failure (git push / gh pr checks)
    A18 Permission re-approval (same prompt ≥3× spread over session)
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
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
GIT_CHECKOUT_B = re.compile(
    r"git\s+checkout\s+-b\b|git\s+switch\s+-c\b|git\s+worktree\s+add\s+-b\b"
)
# A14 branch-state tracking: a checkout/switch to a named branch, a worktree
# added on an existing branch, or a branch reported in command output. Used to
# decide whether a commit/push is actually happening on main — replacing the old
# "the word 'main' appears anywhere in the command or output" heuristic, which
# fired on every worktree commit and on commit messages mentioning "main".
# `(?:-[^\s;&|]+\s+)*` skips optional flags (e.g. `-f`, `--quiet`) that may
# precede the branch name/path before the capture group.
GIT_SWITCH_TO = re.compile(
    r"\bgit\s+(?:checkout|switch)\s+(?:-[^\s;&|]+\s+)*(?P<br>[^\s;&|]+)"
)
GIT_WORKTREE_ADD_BRANCH = re.compile(
    r"\bgit\s+worktree\s+add\s+(?:-[^\s;&|]+\s+)*\S+\s+(?P<br>[^\s;&|-][^\s;&|]*)"
)
GIT_ON_BRANCH_OUT = re.compile(
    r"(?:On branch|Switched to(?: a new)? branch '?)(?P<br>[\w./-]+)"
)
GIT_COMMIT_OR_PUSH = re.compile(r"\bgit\s+(?:commit|push)\b")
GIT_PUSH_TO_MAIN = re.compile(r"\bgit\s+push\b[^\n]*\b(?:HEAD:)?(?:main|master)\b")

# A1: textual error markers, used as a fallback only when the harness `is_error`
# flag is absent. The previous bare `"error" in result` substring test fired on
# benign output ("0 errors", "no errors found", code that mentions error
# handling), producing the bulk of A1 false positives. Require a real error
# marker AND exclude success phrasing that merely contains the word "error".
A1_ERROR_MARKER = re.compile(
    r"(?:^|\n)\s*(?:error|fatal|panic)\b[:\s]"
    r"|command not found"
    r"|no such file or directory"
    r"|:\s*error:"
    r"|\bexit code [1-9]"
    r"|\bnon-zero exit\b"
    r"|Traceback \(most recent call last\)",
    re.IGNORECASE,
)
A1_BENIGN = re.compile(
    r"\b(?:0|no|zero|without|found 0)\s+errors?\b"
    r"|\berrors?\s*[:=]\s*0\b"
    r"|\berror[- ]free\b"
    r"|all checks passed"
    r"|created successfully"
    r"|\bgood\b.*\bsignature\b",
    re.IGNORECASE,
)
LARGE_TOOL_RESULT_BYTES = 5000
DEFAULT_RETRY_WINDOW = 5  # turns
DEFAULT_SEQ_NGRAM = 3

# A4: efficiency ratio
A4_RATIO_THRESHOLD = 5.0  # tool_uses / user_messages
A4_MIN_TOOL_USES = 20  # skip tiny sessions

# A5: read-only / independent tools that benefit from batching
A5_PARALLELIZABLE_TOOLS = {"Read", "Glob", "Grep", "Bash"}
A5_MIN_SERIAL_RUN = 3  # >=3 calls in separate assistant turns

# A11: tool-misuse patterns — shlex tokenization to handle quoted regex/sed bodies
# (e.g. `sed -i 's|a|b|g' file.json`) and to distinguish piped from terminal cat.
A11_STRUCTURED_EXT_RE = re.compile(
    r"\.(?:json|jsonl|ya?ml|toml|xml|csv)$", re.IGNORECASE
)
A11_STRUCTURED_TOOLS = {"grep", "egrep", "fgrep", "sed", "awk", "gawk"}
A11_CAT_TOOLS = {"cat", "head", "tail"}
A11_PIPELINE_OPS = {"|", "||", "&&", ";", ">", ">>", "<"}

# A13: verification-skip claims — tightened to phrases that are unambiguously
# success assertions, not incidental status notes ("done", "fixed in v2", etc.).
A13_CLAIM_PATTERNS = re.compile(
    r"\b("
    r"tests?\s+pass(?:es|ed|ing)?"  # "tests pass" / "test passed"
    r"|all\s+tests?\s+(?:pass|green)"  # "all tests pass" / "all tests green"
    r"|build\s+(?:passes|works|succeeds|succeeded)"
    r"|(?:the\s+)?bug\s+is\s+fixed"  # "the bug is fixed"
    r"|behoben"  # DE: "fixed"
    r"|tests?\s+laufen(?:\s+(?:jetzt|wieder|durch))?"
    r"|läuft\s+jetzt(?:\s+wieder)?"  # DE: "läuft jetzt"
    r"|funktioniert\s+jetzt(?:\s+wieder)?"  # DE: "funktioniert jetzt"
    r")\b",
    re.IGNORECASE,
)
A13_VERIFICATION_CMD = re.compile(
    r"\b("
    r"pytest|unittest|jest|vitest|phpunit|composer\s+(?:test|ci:test)"
    r"|npm\s+(?:test|run\s+test)|yarn\s+test|pnpm\s+(?:test|run\s+test)|bun\s+test"
    r"|go\s+test|cargo\s+test|mvn\s+test|gradle\s+test"
    r"|make\s+(?:test|check|lint)|tox|nox"
    r"|ruff|flake8|mypy|pyright|eslint|tsc|phpstan|psalm|rector|golangci-lint"
    r"|npm\s+run\s+build|yarn\s+build|pnpm\s+build|cargo\s+build|go\s+build|tsc\s+--build"
    r")\b",
)
A13_LOOKBACK_BASH_CMDS = (
    10  # examine the most recent N Bash invocations prior to the claim
)

# A18: allowlist candidate — same Bash command-prefix appearing ≥3× spread out
# (not a retry burst). Restricted to Bash; non-Bash tools like Read/Glob/Grep
# are already permission-scoped by name and would generate noisy false positives.
A18_MIN_OCCURRENCES = 3
A18_BASH_PREFIX_TOKENS = 2  # e.g. "git status", "gh pr"


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


def extract_assistant_texts(events: Iterable[dict]) -> list[tuple[int, str]]:
    """Return (event_index, text) for assistant-authored text blocks only."""
    out = []
    for i, ev in enumerate(events):
        if ev.get("type") != "assistant":
            continue
        content = (ev.get("message") or {}).get("content")
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
                tool_uses_pending[block["id"]] = (
                    i,
                    block["name"],
                    block.get("input", {}),
                )
            elif block.get("type") == "tool_result":
                use_id = block.get("tool_use_id")
                if use_id in tool_uses_pending:
                    i_use, name, inp = tool_uses_pending.pop(use_id)
                    result = block.get("content", "")
                    if isinstance(result, list):
                        result = " ".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in result
                        )
                    is_error = block.get("is_error", False)
                    out.append((i_use, name, inp, str(result), bool(is_error)))
    return out


def signal_tool_errors(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        head = result[:200]
        # Trust the harness is_error flag unconditionally (an authoritative
        # failure). Only the text-based fallback is gated by A1_BENIGN, so
        # success output that merely contains the word "error" ("0 errors",
        # "all checks passed") is not flagged.
        if is_error or (A1_ERROR_MARKER.search(head) and not A1_BENIGN.search(head)):
            out.append(
                {
                    "signal": "A1",
                    "name": "tool_error",
                    "turn": i,
                    "tool": name,
                    "snippet": result[:200],
                }
            )
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
                out.append(
                    {
                        "signal": "A2",
                        "name": "tool_retry_cluster",
                        "tool": name,
                        "turns": turns[j : j + 3],
                    }
                )
                break
    return out


def signal_verbose_results(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if len(result) > LARGE_TOOL_RESULT_BYTES:
            out.append(
                {
                    "signal": "A3",
                    "name": "verbose_tool_output",
                    "turn": i,
                    "tool": name,
                    "bytes": len(result),
                }
            )
    return out


def signal_user_corrections(user_texts) -> list[dict]:
    out = []
    for i, text in user_texts:
        if CORRECTION_PATTERNS.search(text):
            out.append(
                {
                    "signal": "A6",
                    "name": "user_correction",
                    "turn": i,
                    "snippet": text[:200],
                }
            )
        elif ALL_CAPS_RUN.search(text) and len(text) < 500:
            out.append(
                {
                    "signal": "A6",
                    "name": "all_caps_emphasis",
                    "turn": i,
                    "snippet": text[:200],
                }
            )
        elif MULTIPLE_EXCLAIM.search(text):
            out.append(
                {
                    "signal": "A6",
                    "name": "exclamation_emphasis",
                    "turn": i,
                    "snippet": text[:200],
                }
            )
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
            out.append(
                {
                    "signal": "A7",
                    "name": "prompt_repetition",
                    "turns": turns,
                    "snippet": key[:200],
                }
            )
    return out


def signal_prompt_sequence_repetition(
    user_texts, n: int = DEFAULT_SEQ_NGRAM
) -> list[dict]:
    out = []
    if len(user_texts) < n * 2:
        return out
    norm = [re.sub(r"\s+", " ", t[1].strip().lower())[:60] for t in user_texts]
    counter: Counter[tuple[str, ...]] = Counter()
    for i in range(len(norm) - n + 1):
        ngram = tuple(norm[i : i + n])
        if all(len(s) > 5 for s in ngram):
            counter[ngram] += 1
    for ngram, cnt in counter.items():
        if cnt >= 2:
            out.append(
                {
                    "signal": "A8",
                    "name": "prompt_sequence_repetition",
                    "count": cnt,
                    "ngram": list(ngram),
                }
            )
    return out


def signal_tool_sequence_repetition(
    tool_uses, n: int = DEFAULT_SEQ_NGRAM
) -> list[dict]:
    out = []
    if len(tool_uses) < n * 2:
        return out
    names = [t[1] for t in tool_uses]
    counter: Counter[tuple[str, ...]] = Counter()
    for i in range(len(names) - n + 1):
        counter[tuple(names[i : i + n])] += 1
    for ngram, cnt in counter.items():
        if cnt >= 2:
            out.append(
                {
                    "signal": "A9",
                    "name": "tool_sequence_repetition",
                    "count": cnt,
                    "ngram": list(ngram),
                }
            )
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
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                        and block.get("name") == "Skill"
                    ):
                        invoked = True
                        break
            if invoked:
                break
        if not invoked:
            out.append(
                {
                    "signal": "A10",
                    "name": "skill_reminder_not_invoked",
                    "turn": i,
                    "skills_mentioned": matches,
                }
            )
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
            out.append(
                {
                    "signal": "A12",
                    "name": "reread_without_edit",
                    "path": path,
                    "turns": read_turns,
                }
            )
    return out


def signal_main_branch_work(tool_uses) -> list[dict]:
    """Flag commits/pushes that are positively on main/master.

    Tracks the active branch from explicit checkouts/switches, worktree
    additions, and branch names echoed in command output. Only fires when we
    *know* the operation is on main (or a push explicitly targets main) — a
    worktree checked out on a feature branch, or a commit message that merely
    mentions "main", no longer trips this signal.
    """
    out = []
    on_main = None  # None = unknown; only flag when positively known to be on main
    for i, name, inp, result, is_error in tool_uses:
        if name != "Bash":
            continue
        cmd = inp.get("command", "")

        if GIT_CHECKOUT_B.search(cmd):  # checkout -b / switch -c / worktree add -b
            on_main = False
        else:
            m = GIT_SWITCH_TO.search(cmd)
            mw = GIT_WORKTREE_ADD_BRANCH.search(cmd)
            if m and not m.group("br").startswith("-"):
                on_main = m.group("br") in ("main", "master")
            elif mw:
                on_main = mw.group("br") in ("main", "master")
        mob = GIT_ON_BRANCH_OUT.search(result)
        if mob:
            on_main = mob.group("br") in ("main", "master")

        if GIT_COMMIT_OR_PUSH.search(cmd) and (
            on_main is True or GIT_PUSH_TO_MAIN.search(cmd)
        ):
            out.append(
                {
                    "signal": "A14",
                    "name": "git_op_without_branch",
                    "turn": i,
                    "command": cmd[:200],
                }
            )
    return out


def signal_bot_attribution(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if name != "Bash":
            continue
        cmd = inp.get("command", "")
        if "git commit" in cmd and BOT_ATTRIBUTION.search(cmd):
            out.append(
                {
                    "signal": "A15",
                    "name": "bot_attribution_in_commit",
                    "turn": i,
                    "snippet": cmd[:300],
                }
            )
    return out


def signal_outdated_tool(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if OUTDATED_TOOL.search(result[:1000]):
            out.append(
                {
                    "signal": "A16",
                    "name": "outdated_tool_warning",
                    "turn": i,
                    "tool": name,
                    "snippet": result[:300],
                }
            )
    return out


def signal_upstream_failure(tool_uses) -> list[dict]:
    out = []
    for i, name, inp, result, is_error in tool_uses:
        if name != "Bash":
            continue
        cmd = inp.get("command", "")
        if is_error and re.search(
            r"\bgit\s+push\b|\bgh\s+pr\s+(checks|create|merge)\b|\bglab\s+mr\b", cmd
        ):
            out.append(
                {
                    "signal": "A17",
                    "name": "upstream_failure",
                    "turn": i,
                    "command": cmd[:200],
                    "stderr": result[:500],
                }
            )
    return out


def signal_tool_count_vs_task(tool_uses, user_texts) -> list[dict]:
    """A4: total tool-call/user-message ratio above threshold on a non-trivial session.

    Denominator counts distinct user *events*, not text blocks — a single user
    event with multiple text blocks must not skew the ratio downward.
    """
    n_tools = len(tool_uses)
    n_msgs = len({i for i, _ in user_texts}) or 1
    ratio = n_tools / n_msgs
    if n_tools >= A4_MIN_TOOL_USES and ratio >= A4_RATIO_THRESHOLD:
        return [
            {
                "signal": "A4",
                "name": "tool_call_inefficiency_ratio",
                "tool_uses": n_tools,
                "user_messages": n_msgs,
                "ratio": round(ratio, 2),
                "threshold": A4_RATIO_THRESHOLD,
            }
        ]
    return []


def signal_sequential_parallelizable(tool_uses) -> list[dict]:
    """A5: ≥N parallelizable tools (Read/Glob/Grep/Bash) in *separate* assistant
    messages, back-to-back, without an interleaving non-parallelizable call.

    Two tool_use blocks emitted from the same assistant message share the same
    event index in the 5-tuple, so a parallel batch inside one assistant
    message is naturally not counted as a multi-message run.
    """
    out = []
    run: list[tuple[int, str]] = []  # (event_index, name)

    def flush(run):
        if len(run) < A5_MIN_SERIAL_RUN:
            return
        distinct_msgs = {ev for ev, _ in run}
        if len(distinct_msgs) >= A5_MIN_SERIAL_RUN:
            out.append(
                {
                    "signal": "A5",
                    "name": "sequential_parallelizable",
                    "tools": [n for _, n in run],
                    "assistant_messages": sorted(distinct_msgs),
                }
            )

    for ev_idx, name, _inp, _result, _err in tool_uses:
        if name in A5_PARALLELIZABLE_TOOLS:
            run.append((ev_idx, name))
        else:
            flush(run)
            run = []
    flush(run)
    return out


def _tokenize_bash(cmd: str) -> list[str] | None:
    """shlex-tokenize a Bash command. Returns None on unbalanced quotes etc."""
    try:
        return shlex.split(cmd, posix=True, comments=False)
    except ValueError:
        return None


def _split_pipeline_segments(tokens: list[str]) -> list[list[str]]:
    """Split a token list into pipeline segments at | || && ; operators."""
    segments: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in ("|", "||", "&&", ";"):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def signal_wrong_tool_choice(tool_uses) -> list[dict]:
    """A11: Bash invoking grep/sed/awk on structured files, or cat/head/tail
    *terminally* on a single file (Read would fit).

    Uses shlex so quoted regex/sed bodies like `sed -i 's|a|b|g' file.json`
    tokenize correctly, and so piped pipelines like `cat file | wc -l`
    aren't misread as a cat-instead-of-read pattern.
    """
    out = []
    for i, name, inp, _result, _err in tool_uses:
        if name != "Bash":
            continue
        cmd = inp.get("command", "")
        if not cmd:
            continue
        tokens = _tokenize_bash(cmd)
        if not tokens:
            continue

        # Misuse 1: grep/sed/awk acting on a structured-file argument.
        fired_structured = False
        for segment in _split_pipeline_segments(tokens):
            if not segment:
                continue
            tool = segment[0]
            if tool not in A11_STRUCTURED_TOOLS:
                continue
            for tok in segment[1:]:
                if tok.startswith("-"):
                    continue
                if A11_STRUCTURED_EXT_RE.search(tok):
                    out.append(
                        {
                            "signal": "A11",
                            "name": "structured_file_misuse",
                            "turn": i,
                            "tool_invoked": tool,
                            "file": tok,
                            "hint": "use data-tools (jq / yq / dasel) instead of grep/sed/awk on structured formats",
                            "snippet": cmd[:200],
                        }
                    )
                    fired_structured = True
                    break
            if fired_structured:
                break
        if fired_structured:
            continue

        # Misuse 2: cat/head/tail used as the terminal command (no pipe/redirect).
        if any(tok in A11_PIPELINE_OPS for tok in tokens):
            continue
        head = tokens[0]
        if head in A11_CAT_TOOLS:
            file_args = [t for t in tokens[1:] if not t.startswith("-")]
            if file_args:
                out.append(
                    {
                        "signal": "A11",
                        "name": "cat_instead_of_read",
                        "turn": i,
                        "tool_invoked": head,
                        "hint": "use the Read tool (line-numbered output, ranged reads) instead of cat/head/tail",
                        "snippet": cmd[:200],
                    }
                )
    return out


def signal_skipped_verification(assistant_texts, tool_uses) -> list[dict]:
    """A13: assistant claims success without any prior test/build/lint Bash
    call within the last `A13_LOOKBACK_BASH_CMDS` Bash invocations.

    Counting Bash calls (rather than estimating events-per-turn) makes the
    lookback robust regardless of how many tool_use blocks a turn contains.
    `tool_uses` is already chronological from `extract_tool_uses`, so no sort
    is needed.
    """
    out = []
    bash_commands_chronological: list[tuple[int, str]] = [
        (i, inp.get("command", ""))
        for i, name, inp, _r, _e in tool_uses
        if name == "Bash"
    ]

    def had_verification_before(turn: int) -> bool:
        recent = [(i, c) for i, c in bash_commands_chronological if i < turn][
            -A13_LOOKBACK_BASH_CMDS:
        ]
        return any(A13_VERIFICATION_CMD.search(c) for _, c in recent)

    for i, text in assistant_texts:
        m = A13_CLAIM_PATTERNS.search(text)
        if not m:
            continue
        if had_verification_before(i):
            continue
        out.append(
            {
                "signal": "A13",
                "name": "claim_without_verification",
                "turn": i,
                "claim": m.group(0),
                "snippet": text[:200],
            }
        )
    return out


def signal_permission_reapproval(
    tool_uses, window: int = DEFAULT_RETRY_WINDOW
) -> list[dict]:
    """A18: same Bash command-prefix appears ≥3× *spread* over the session.

    Distinct from A2 (retry burst): A18 fires only when the run is dispersed,
    i.e. median gap between occurrences exceeds the retry window — these are
    candidates for an allowlist entry, not a misunderstanding.

    Restricted to Bash. Non-Bash tools (Read/Glob/Grep/etc.) are already
    permission-scoped by tool name, so repeated invocations don't represent
    re-approval friction.
    """
    out = []
    grouped: dict[str, list[int]] = defaultdict(list)
    for i, name, inp, _r, _e in tool_uses:
        if name != "Bash":
            continue
        cmd = (inp.get("command") or "").strip()
        prefix = " ".join(cmd.split()[:A18_BASH_PREFIX_TOKENS])
        if not prefix:
            continue
        grouped[prefix].append(i)
    for prefix, turns in grouped.items():
        if len(turns) < A18_MIN_OCCURRENCES:
            continue
        gaps = [b - a for a, b in zip(turns, turns[1:])]
        if not gaps:
            continue
        gaps_sorted = sorted(gaps)
        median = gaps_sorted[len(gaps_sorted) // 2]
        if median <= window * 2:
            # Looks like a retry burst — leave it to A2.
            continue
        out.append(
            {
                "signal": "A18",
                "name": "permission_reapproval_candidate",
                "prefix": prefix,
                "occurrences": len(turns),
                "median_gap_turns": median,
            }
        )
    return out


SIGNAL_FUNCS = {
    "A1": signal_tool_errors,
    "A2": signal_retry_clusters,
    "A3": signal_verbose_results,
    "A4": signal_tool_count_vs_task,
    "A5": signal_sequential_parallelizable,
    "A6": signal_user_corrections,
    "A7": signal_prompt_repetition,
    "A8": signal_prompt_sequence_repetition,
    "A9": signal_tool_sequence_repetition,
    "A10": signal_skill_reminder_vs_invoke,
    "A11": signal_wrong_tool_choice,
    "A12": signal_reread_same_file,
    "A13": signal_skipped_verification,
    "A14": signal_main_branch_work,
    "A15": signal_bot_attribution,
    "A16": signal_outdated_tool,
    "A17": signal_upstream_failure,
    "A18": signal_permission_reapproval,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript-file", required=True, type=Path)
    parser.add_argument("--output-format", choices=["json", "text"], default="json")
    parser.add_argument(
        "--signals",
        default=",".join(SIGNAL_FUNCS.keys()),
        help="Comma-separated signal IDs to run (default: all)",
    )
    args = parser.parse_args()

    if not args.transcript_file.exists():
        print(f"Transcript not found: {args.transcript_file}", file=sys.stderr)
        return 2

    events = load_jsonl(args.transcript_file)
    user_texts = extract_user_texts(events)
    assistant_texts = extract_assistant_texts(events)
    tool_uses = extract_tool_uses(events)

    selected = {s.strip() for s in args.signals.split(",") if s.strip()}
    findings = []
    for sid, func in SIGNAL_FUNCS.items():
        if sid not in selected:
            continue
        # Dispatch arg shape
        if func in (
            signal_user_corrections,
            signal_prompt_repetition,
            signal_prompt_sequence_repetition,
        ):
            findings.extend(func(user_texts))
        elif func is signal_skill_reminder_vs_invoke:
            findings.extend(func(events))
        elif func is signal_tool_count_vs_task:
            findings.extend(func(tool_uses, user_texts))
        elif func is signal_skipped_verification:
            findings.extend(func(assistant_texts, tool_uses))
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
        print(
            f"Events: {summary['events_total']}  User msgs: {summary['user_messages']}  Tool uses: {summary['tool_uses']}"
        )
        print(f"Findings: {summary['findings_total']}")
        for f in findings:
            print(f"  - [{f['signal']}] {f['name']}: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
