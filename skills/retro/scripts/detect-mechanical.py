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
import itertools
import json
import re
import shlex
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Line-start correction openers (EN + DE). Anchored so a mid-sentence "no" /
# "nicht" inside ordinary prose does not trip the signal.
CORRECTION_PATTERNS = re.compile(
    r"^\s*(no\b|nope\b|nah\b|stop\b|don't\b|wrong\b|"
    r"nein\b|n[oö]\b|nicht\b|nicht so\b|falsch\b|quatsch\b|unsinn\b|"
    r"doch nicht\b|warum\b|wieso\b|weshalb\b|manno?\b|mann\b)",
    re.IGNORECASE | re.MULTILINE,
)
# Strong correction phrases that signal friction wherever they appear in the
# message, not only at line start — German-speaking users correct mid-sentence
# far more than the anchored EN openers catch. Curated to stay low-false-positive.
STRONG_CORRECTION_PHRASES = re.compile(
    r"(so nicht\b|nicht schon wieder\b|schon wieder\b|wieder drin\b|"
    r"raus damit\b|endlich mal\b|mal merken\b|was soll das\b|"
    r"das ist (?:so )?nicht\b|stimmt (?:so )?nicht\b|"
    r"mach(?:'s| es| das)?(?: doch)? selber\b|"
    r"sei (?:bitte )?(?:mal )?(?:genau|vorsichtig|gr[uü]ndlich)\b|"
    r"nicht analog\b)",
    re.IGNORECASE,
)
ALL_CAPS_RUN = re.compile(r"[A-ZÄÖÜ]{4,}")
MULTIPLE_EXCLAIM = re.compile(r"!{3,}")
BOT_ATTRIBUTION = re.compile(
    r"(Generated with Claude|Co-Authored-By:\s*Claude|🤖)",
    re.IGNORECASE,
)
# `(?<!HEAD )is now`: git prints "HEAD is now at <sha>" on every checkout/worktree
# add, which is a position report, not a deprecation — it fired seven times in one
# session before the lookbehind.
OUTDATED_TOOL = re.compile(
    r"\b(deprecated|(?<!HEAD )is now|use\s+\S+\s+instead|no longer supported)\b",
    re.IGNORECASE,
)
#: Slash commands the client handles itself; no Skill call can ever follow them.
BUILTIN_SLASH_COMMANDS = frozenset(
    {
        "/clear",
        "/compact",
        "/config",
        "/cost",
        "/doctor",
        "/exit",
        "/help",
        "/init",
        "/login",
        "/logout",
        "/memory",
        "/model",
        "/quit",
        "/status",
    }
)
#: A `<command-name>` block whose text body is this long carries the skill content
#: inline (the client expanded the slash command), so the skill IS in effect without
#: a Skill tool call.
INLINE_SKILL_MIN_CHARS = 1500
GIT_BRANCH_MAIN = re.compile(r"\b(?:main|master)\b")
# Each alternative skips the flags that come before its branch-creating one via
# its own negative lookahead (`(?!-b\b)` / `(?!-c\b)`), so the `*` cannot eat the
# flag it is looking for: `git checkout -q -b feat` creates a branch just as
# `git checkout -b feat`
# does, but without this the switch went unrecognised and the tracked branch
# stayed on whatever was checked out before it.
GIT_CHECKOUT_B = re.compile(
    r"git\s+checkout\s+(?:(?!-b\b)-\S+\s+)*-b\b"
    r"|git\s+switch\s+(?:(?!-c\b)-\S+\s+)*-c\b"
    r"|git\s+worktree\s+add\s+(?:(?!-b\b)-\S+\s+)*-b\b"
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
# `On branch` is followed by a space, the other two by an optional quote. The
# missing `\s+` meant the `git status` header — the most common way a branch
# appears in output — never set the tracked branch at all.
GIT_ON_BRANCH_OUT = re.compile(
    r"(?:On branch\s+|Switched to(?: a new)? branch '?|Already on '?)(?P<br>[\w./-]+)"
)
GIT_COMMIT = re.compile(r"\bgit\s+commit\b")
# `(?![\w-])` requires main/master as a full token so "main-menu" / "master2"
# (where `\b` would otherwise match the "main"/"master" prefix) do not fire.
# `[^\n;&|]*` stops at a shell command separator so the match stays inside the
# `git push` invocation itself: `git push | tail && git log origin/main..HEAD`
# mentions main in a *later, read-only* command, and spanning into it flagged
# an ordinary feature-branch push as work on main.
GIT_PUSH_TO_MAIN = re.compile(
    r"\bgit\s+push\b[^\n;&|]*\b(?:HEAD:)?(?:main|master)(?![\w-])"
)

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
A19_MIN_COUNT = 8  # one command shape this often is a script, not a habit
C6_MIN_VIOLATIONS = 3  # a written rule tripped this often needs a gate
# Signal -> phrases that indicate a matching rule already exists in the
# always-loaded instructions.
C6_RULE_KEYWORDS = {
    "A11": ["structured file", "jq", "yq", "dasel", "never grep"],
    "A14": ["feature branch", "never work on main"],
    "A15": ["bot attribution", "co-authored-by", "generated with"],
    "A13": ["without pasted command output", "verification", "evidence before"],
}

# A11: tool-misuse patterns — shlex tokenization to handle quoted regex/sed bodies
# (e.g. `sed -i 's|a|b|g' file.json`) and to distinguish piped from terminal cat.
A11_STRUCTURED_EXT_RE = re.compile(
    r"\.(?:json|jsonl|ya?ml|toml|xml|csv)$", re.IGNORECASE
)
A11_STRUCTURED_TOOLS = {"grep", "egrep", "fgrep", "sed", "awk", "gawk"}
A11_CAT_TOOLS = {"cat", "head", "tail"}
A11_PIPELINE_OPS = {"|", "||", "&&", ";", ">", ">>", "<"}
# The Read tool addresses files in the project; it has no last-N-lines mode and
# is not the way to poll a background task's output, a log, or a scratch file.
# The harness gate that enforces "Read instead of cat/head/tail" says so
# explicitly, so flagging those paths reports as friction what the rule permits
# — and, worse, feeds C6, which reads repeated A11 hits as proof that the prose
# rule failed and escalates to "propose a mechanical gate". A false positive
# must not be able to manufacture that escalation.
A11_CAT_EXEMPT_PATH_RE = re.compile(
    r"(?:"
    r"(?:^|/)(?:tmp|var/log|var/tmp|logs?)/"  # a scratch or log directory
    r"|/tasks/"  # a background task's output
    r"|\.(?:log|out|output)$"  # an output file by extension
    r")"
)

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


# Turns that carry the "user" role but were not typed by a human: harness
# task/system notifications, scheduled-wakeup re-fired prompts (each firing
# repeats the same /loop or continuation prompt verbatim), slash-command
# expansions, and teammate messages. Counting them as user input floods A6
# (user corrections) and A7 (prompt repetition) with self-inflicted noise in
# loop-heavy sessions.
_SYNTHETIC_USER_MARKERS = (
    "<task-notification>",
    "[SYSTEM NOTIFICATION",
    "<system-reminder>",
    "<command-message>",
    "<teammate-message",
    "<agent-message",
    # Compaction-continuation banner: quotes the session's own emphatic
    # content back as a "user" turn — 3 false A6 and 1 false A7 from three
    # banners in one measured session. Fallback for transcripts predating the
    # isCompactSummary flag handled in extract_user_texts.
    "This session is being continued from a previous conversation",
)


def _is_synthetic_user_text(text: str) -> bool:
    head = text.lstrip()[:400]
    return any(marker in head for marker in _SYNTHETIC_USER_MARKERS)


def extract_user_texts(events: Iterable[dict]) -> list[tuple[int, str]]:
    events = list(events)
    out = []
    # Prompts the assistant scheduled itself (ScheduleWakeup) come back as
    # verbatim user turns on every firing. Map prompt -> earliest scheduling
    # event index: only occurrences AFTER that index are re-firings — a human
    # may well have typed the same text originally (the /loop pattern).
    wakeup_prompts: dict[str, int] = {}
    for j, ev in enumerate(events):
        if ev.get("type") != "assistant":
            continue
        content = (ev.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == "ScheduleWakeup"
            ):
                prompt = (block.get("input") or {}).get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    wakeup_prompts.setdefault(prompt.strip(), j)
    for i, ev in enumerate(events):
        if ev.get("type") != "user":
            continue
        # The harness stamps synthetic user turns (slash-command expansions,
        # scheduled-wakeup re-firings, meta notifications) with isMeta: true —
        # the authoritative discriminator where present. The marker/prompt
        # checks below remain as fallback for transcripts predating the flag.
        if ev.get("isMeta"):
            continue
        # Compaction summaries carry the user role but are harness-authored
        # recaps of earlier turns; isCompactSummary is authoritative where
        # present (the banner marker above covers older transcripts).
        if ev.get("isCompactSummary"):
            continue
        msg = ev.get("message", {})
        content = msg.get("content")
        texts = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
        # A slash-command expansion delivers the static command template as a
        # sibling text block of the <command-message> marker — if any block
        # in the message is synthetic, the whole message is.
        if any(_is_synthetic_user_text(t) for t in texts):
            continue
        for text in texts:
            scheduled_at = wakeup_prompts.get(text.strip())
            if scheduled_at is not None and i > scheduled_at:
                continue
            out.append((i, text))
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


# --- command shape -----------------------------------------------------------
# Grouping by tool NAME is blind in a Bash-dominated session: every shell call
# collapses to "Bash", so 61 identical `gh pr view` probes look like one busy
# tool. The catalog has always promised "same tool + similar args"; this is the
# args half. A shape keeps the program and its subcommands and drops every
# value, so `gh pr view 120 --repo x --json state` and `gh pr view 7 --json url`
# share the shape `gh pr view`.

_SHELL_NOISE = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "for",
    "do",
    "done",
    "while",
    "until",
    "case",
    "esac",
    "function",
    "return",
    "exit",
    "local",
    "export",
    "set",
    "echo",
    "printf",
    "cd",
    "true",
    "false",
    "test",
    "[",
    "[[",
    "]]",
    "exec",
    "source",
    ".",
    "read",
    "shift",
    "eval",
    "continue",
    "break",
}
# A program name, to reject the shell syntax that survives segmentation: a
# comment (`# note`), a case arm (`*)`), a brace (`{ echo`, `}`), arithmetic
# (`(m+1))`). Those were reported as commands nobody ran.
_PROGRAM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.+-]*$")
# Wrappers do not identify the work — the command they wrap does. Skipping the
# whole segment on seeing one hides the probe entirely: `timeout 300 gh api ...`
# counted as "timeout", `sudo gh pr view` as nothing at all.
_WRAPPERS = {"env", "sudo", "command", "time", "timeout", "nohup", "nice", "stdbuf"}
# Only these git subcommands leave the machine; git status/log/diff are local.
_REMOTE_GIT = {"fetch", "pull", "push", "clone", "ls-remote", "remote", "submodule"}


def is_remote_shape(shape: str) -> bool:
    """True when the shape leaves the machine — a round trip worth counting."""
    parts = shape.split()
    prog = parts[0]
    if prog == "git":
        return len(parts) > 1 and parts[1] in _REMOTE_GIT
    return prog in _REMOTE_PREFIX


_VALUEISH = re.compile(r"""^(-|/|\.|~|\$|\d|['"])""")


def split_segments(cmd: str) -> list[str]:
    """Split one shell string on separators that sit OUTSIDE quotes.

    A regex split treats every `|`, `;` and newline as a separator, including
    the ones inside a quoted argument. That turns the pipes of a jq program
    (`--jq '[.[]|select(.x)] | length'`) and the newlines of an inline script
    (`python3 -c "import yaml\\nprint(x)"`) into statement boundaries, and the
    first word of each fragment is then reported as a command that was never
    run — `select(.x)]`, `length'`, `import yaml`.

    Shell rules decide what still separates inside quotes: nothing does inside
    single quotes, and inside double quotes only command substitution (`$(`
    and a backtick) opens a new command.
    """
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    cmd = cmd or ""

    def flush() -> None:
        segments.append("".join(buf))
        buf.clear()

    while i < len(cmd):
        ch = cmd[i]
        if quote:
            if quote == '"':
                if ch == "\\" and i + 1 < len(cmd):
                    buf.append(ch)
                    buf.append(cmd[i + 1])
                    i += 2
                    continue
                # Command substitution is the one thing that still starts a
                # command inside double quotes.
                if cmd.startswith("$(", i) or ch == "`":
                    flush()
                    i += 2 if ch == "$" else 1
                    continue
                # Closing the substitution returns to the command that wrapped
                # it, which has to be examined on its own: without this,
                # `FOO="$(git rev-parse HEAD)" gh pr view 1` reported only the
                # inner `git rev-parse` and lost `gh pr view` entirely.
                if ch == ")":
                    flush()
                    i += 1
                    continue
            if ch == quote:
                quote = None
                # After a substitution flushed, the closing quote would open the
                # next segment and be tokenised as its program. It carries no
                # information there, so drop it; elsewhere it is kept, because a
                # leading quote is what marks a token as a value rather than a
                # subcommand.
                if not buf:
                    i += 1
                    continue
            buf.append(ch)
            i += 1
            continue

        if ch in "'\"":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in ";\n`":
            flush()
            i += 1
            continue
        if cmd.startswith("&&", i) or cmd.startswith("||", i):
            flush()
            i += 2
            continue
        if ch == "|":
            flush()
            i += 1
            continue
        if cmd.startswith("$(", i):
            flush()
            i += 2
            continue
        if ch == ")":
            flush()
            i += 1
            continue
        buf.append(ch)
        i += 1

    flush()
    return segments


HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?.*?^\1$", re.DOTALL | re.MULTILINE)


ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
# Wrapper options that take a separate value. Dropping the flag but leaving its
# argument hides the program behind it: `sudo -u root git push` peeled to
# `root git push`, whose first token is not git, so the operation vanished.
# `--flag=value` needs no entry here — it is one token.
_WRAPPER_VALUE_FLAGS = {
    "sudo": {
        "-u",
        "--user",
        "-g",
        "--group",
        "-p",
        "--prompt",
        "-h",
        "--host",
        "-r",
        "--role",
        "-t",
        "--type",
        "-C",
        "--close-from",
    },
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "stdbuf": {"-i", "--input", "-o", "--output", "-e", "--error"},
}


def _drop_wrapper_args(toks: list[str], wrapper: str) -> None:
    """Consume a wrapper's own flags, values included, in place."""
    takes_value = _WRAPPER_VALUE_FLAGS.get(wrapper, set())
    while toks:
        tok = toks[0]
        if tok.startswith("-"):
            toks.pop(0)
            if tok in takes_value and toks and not toks[0].startswith("-"):
                toks.pop(0)
            continue
        if re.match(r"^\d+[smhd]?$", tok):  # `timeout 60`
            toks.pop(0)
            continue
        return


def peel_to_program(toks: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and wrapper commands, in place order.

    `env FOO=1 sudo -u x timeout 60 git push` is a git operation; the wrappers
    and their own flags say nothing about the work. Shared by command_shapes()
    and git_segments() so the two cannot drift — a copy of this loop in the
    latter is what made `sudo git push origin main` stop counting.
    """
    peeled = True
    while peeled and toks:
        peeled = False
        while toks and ASSIGNMENT.match(toks[0]):
            toks.pop(0)
            peeled = True
        if toks and toks[0].split("/")[-1] in _WRAPPERS:
            wrapper = toks.pop(0).split("/")[-1]
            peeled = True
            _drop_wrapper_args(toks, wrapper)
    return toks


def git_segments(cmd: str) -> list[str]:
    """The statements in `cmd` that actually invoke git.

    Matching a pattern like `git push … main` against the raw command string
    also matches the *words* `git push` wherever they appear as data — in a
    replacement string, a documentation example, a script being written. That
    is how editing this file made A14 report "worked on main" seven times for
    commands that ran no git at all. Segmenting first (quote-aware) and keeping
    only the segments whose program is git leaves the pattern nothing to
    misread.
    """
    segments = []
    for seg in split_segments(HEREDOC.sub(" ", cmd or "")):
        toks = peel_to_program(seg.strip().split())
        if toks and toks[0].split("/")[-1] == "git":
            segments.append(" ".join(toks))
    return segments


# Local text plumbing. Repeating these is a pipeline, not a probe worth
# wrapping in a script; wrong-tool use is A11's job, verbosity is A3's.
_PLUMBING = {
    "head",
    "tail",
    "cat",
    "grep",
    "sed",
    "awk",
    "wc",
    "sort",
    "uniq",
    "cut",
    "tr",
    "xargs",
    "find",
    "ls",
    "mkdir",
    "rm",
    "cp",
    "mv",
    "chmod",
    "touch",
    "basename",
    "dirname",
    "sha256sum",
    "base64",
    "diff",
    "tee",
    "jq",
    "yq",
}
# Anything that leaves the machine: each call is a round trip and a token cost.
_REMOTE_PREFIX = (
    "gh",
    "glab",
    "curl",
    "wget",
    "git",
    "docker",
    "ssh",
    "uvx",
    "npm",
    "composer",
)


def command_shapes(cmd: str) -> list[str]:
    """Every distinct program+subcommand shape invoked in one shell string."""
    cmd = HEREDOC.sub(" ", cmd or "")
    shapes: list[str] = []
    for seg in split_segments(cmd):
        toks = peel_to_program(seg.strip().split())
        if not toks:
            continue
        prog = toks[0].split("/")[-1]
        # A bare "/" or a trailing slash leaves prog empty; an empty shape would
        # crash every consumer that splits it.
        if not prog or prog in _SHELL_NOISE or _VALUEISH.match(prog):
            continue
        if not _PROGRAM_NAME.match(prog):
            continue
        # git subcommands are single-level: everything after `git push` is an
        # argument, so `git push origin` and `git push` must not split apart.
        # gh/glab/docker nest two deep (`gh pr view`, `docker compose up`).
        depth = 1 if prog == "git" else 2
        parts = [prog]
        for t in toks[1 : 1 + depth]:
            if _VALUEISH.match(t) or "=" in t:
                break
            if not re.match(r"^[a-z][a-z0-9:_-]*$", t):
                break
            parts.append(t)
        shape = " ".join(parts)
        if shape not in shapes:
            shapes.append(shape)
    return shapes


def shape_of(name: str, inp: dict) -> list[str]:
    """Shapes for any tool use. Non-Bash tools are already one shape each."""
    if name == "Bash":
        return command_shapes((inp or {}).get("command", ""))
    return [name]


def shape_histogram(tool_uses) -> dict[str, list[int]]:
    hist: dict[str, list[int]] = defaultdict(list)
    for i, name, inp, _result, _err in tool_uses:
        for sh in shape_of(name, inp):
            hist[sh].append(i)
    return hist


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
    # Grouped by command shape: "Bash three times" says nothing, "gh pr view
    # three times in five turns" is the finding.
    by_tool = shape_histogram(tool_uses)
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
        if CORRECTION_PATTERNS.search(text) or STRONG_CORRECTION_PHRASES.search(text):
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
        # Built-ins are handled by the client; an expanded slash command arrives with
        # its full instructions inline — neither is a skill that failed to trigger.
        if all(m.strip() in BUILTIN_SLASH_COMMANDS for m in matches):
            continue
        if len(text) >= INLINE_SKILL_MIN_CHARS:
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
        for a, b in itertools.pairwise(read_turns):
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
    mentions "main", no longer trips this signal. A commit *on* main is the
    violation; a push only counts when it targets the main branch — pushing a
    tag or another ref while standing on main (e.g. `git push origin v1.2.3`
    during a release) is legitimate and does not fire.
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
        # Take the LAST branch reported in the output, not the first: a block
        # like `git checkout main && git checkout -b feat` echoes two switches,
        # and the final one is the branch the next command runs on.
        branch_lines = list(GIT_ON_BRANCH_OUT.finditer(result))
        if branch_lines:
            on_main = branch_lines[-1].group("br") in ("main", "master")

        # A commit while on main is the violation; a push only counts when it
        # targets the main branch (a bare push of a tag/other ref is fine).
        # Both are matched against the segments that really invoke git, so the
        # words `git push … main` sitting in data do not count as either.
        git_segs = git_segments(cmd)
        committed_on_main = (
            any(GIT_COMMIT.search(seg) for seg in git_segs) and on_main is True
        )
        if committed_on_main or any(GIT_PUSH_TO_MAIN.search(seg) for seg in git_segs):
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
        # A bare ratio is not a proposal: it says "a lot happened" without
        # naming what to mechanize. Carry the dominant command shapes so the
        # finding points at something that can become a script.
        hist = shape_histogram(tool_uses)
        top = sorted(
            (
                (sh, len(t))
                for sh, t in hist.items()
                if len(t) >= 3 and sh.split()[0] not in _PLUMBING
            ),
            key=lambda kv: -kv[1],
        )[:10]
        return [
            {
                "signal": "A4",
                "name": "tool_call_inefficiency_ratio",
                "top_shapes": [{"shape": sh, "count": c} for sh, c in top],
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
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _split_statements(tokens: list[str]) -> list[list[str]]:
    """Split a token list into statements at `;`, `&&`, `||` — keeping pipes.

    A pipeline is one statement: `cat f | wc -l` is legitimate use of cat and
    must stay intact so the caller can see the `|` and skip it.
    """
    statements: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in (";", "&&", "||", "&"):
            if current:
                statements.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        statements.append(current)
    return statements


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
        #
        # Per sub-command, not per Bash call: `head -50 file.py; echo done` is
        # the misuse even though the call also runs something else, while
        # bailing on the whole call whenever any operator appears misses it.
        # A sub-command that pipes or redirects is legitimate use and is
        # skipped — that is what `cat f | wc -l` is for.
        for sub in _split_statements(tokens):
            if not sub or sub[0] not in A11_CAT_TOOLS:
                continue
            if any(tok in A11_PIPELINE_OPS for tok in sub):
                continue
            head = sub[0]
            file_args = [t for t in sub[1:] if not t.startswith("-")]
            if file_args and not all(
                A11_CAT_EXEMPT_PATH_RE.search(t) for t in file_args
            ):
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
                # One finding per Bash call: a call with two such reads is one
                # habit, and counting it twice inflates the C6 tally that
                # decides whether prose has failed.
                break
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
        gaps = [b - a for a, b in itertools.pairwise(turns)]
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


def signal_repeated_probe(tool_uses, min_count: int = A19_MIN_COUNT) -> list[dict]:
    """A19: one command shape invoked many times — a script waiting to happen.

    Read-only probes are the expensive case: each one costs a round trip and
    tokens, and the same derived answer is recomputed from scratch every time.
    The finding names the shape and the count so the proposal can be concrete
    ("wrap these in a script") instead of "you used many tools".
    """
    out = []
    hist = shape_histogram(tool_uses)
    for shape, turns in sorted(hist.items(), key=lambda kv: -len(kv[1])):
        if len(turns) < min_count:
            continue
        prog = shape.split()[0]
        if prog in _PLUMBING:
            continue  # pipeline noise, not a probe
        remote = is_remote_shape(shape)
        span = turns[-1] - turns[0]
        out.append(
            {
                "signal": "A19",
                "name": "repeated_command_shape",
                "shape": shape,
                "count": len(turns),
                "first_turn": turns[0],
                "last_turn": turns[-1],
                "span_turns": span,
                "remote": remote,
                "hint": (
                    f"`{shape}` ran {len(turns)}x across {span} turns — a single "
                    "script that returns the whole answer (and the next valid "
                    "action) removes the repetition. Route to harness-artefact "
                    "or a skill script, not to prose."
                ),
            }
        )
    return out


def signal_wait_loop_inefficiency(tool_uses) -> list[dict]:
    """A20: polling that waits for everything instead of the first actionable event.

    `until [ pending == 0 ]` learns nothing until the slowest job finishes, long
    after the first failure was visible and fixable — and the user is left
    asking for status. A loop that exits on the first actionable state is the
    fix; this surfaces the ones that do not.
    """
    out = []
    for i, name, inp, _result, _err in tool_uses:
        if name != "Bash":
            continue
        cmd = (inp or {}).get("command", "") or ""
        if not re.search(r"\b(until|while)\b", cmd) or "sleep" not in cmd:
            continue
        # "waits for everything" = the loop exits only when a backlog counter
        # reaches zero. The counter and the comparison are usually far apart —
        # the count is computed inside a nested $( ... --jq ... ) — so proximity
        # matching misses almost all of them; presence of both is the signal.
        counts_backlog = re.search(r"\b(pending|in_progress|queued|running)\b", cmd)
        compares_zero = re.search(r"(==|=|-eq)\s*[\"']?0[\"']?", cmd)
        terminal = bool(counts_backlog and compares_zero)
        out.append(
            {
                "signal": "A20",
                "name": "wait_loop_terminal_condition" if terminal else "wait_loop",
                "turn": i,
                "waits_for_everything": terminal,
                "snippet": cmd[:180],
                "hint": (
                    "Loop waits for every check to settle. Return on the first "
                    "actionable event instead (a failure, a thread needing an "
                    "answer, the required checks concluding) and report progress "
                    "while waiting."
                )
                if terminal
                else "Polling loop — check whether it can exit on the first actionable state.",
            }
        )
    return out


def signal_rule_exists_but_violated(findings, rules_text: str) -> list[dict]:
    """C6: a written rule was violated repeatedly anyway — mechanize it.

    When a rule already exists in the always-loaded instructions and the session
    still trips it N times, another sentence will not help: the same prose has
    already failed. The answer is a hook or a check that makes the violation
    impossible, which is a harness-artefact, not a skill-update.
    """
    if not rules_text:
        return []
    out = []
    by_sig: dict[str, int] = defaultdict(int)
    for f in findings:
        by_sig[f.get("signal", "")] += 1
    for sig, keywords in C6_RULE_KEYWORDS.items():
        n = by_sig.get(sig, 0)
        if n < C6_MIN_VIOLATIONS:
            continue
        if not any(k.lower() in rules_text.lower() for k in keywords):
            continue
        out.append(
            {
                "signal": "C6",
                "name": "written_rule_violated_repeatedly",
                "violated_signal": sig,
                "occurrences": n,
                "hint": (
                    f"{sig} fired {n}x while a matching rule is already present in "
                    "the always-loaded instructions. Prose has demonstrably not "
                    "worked — propose a mechanical gate (PreToolUse hook, "
                    "checkpoint, CI check), not another rule."
                ),
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
    "A19": signal_repeated_probe,
    "A20": signal_wait_loop_inefficiency,
    "C6": signal_rule_exists_but_violated,
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
        elif func is signal_rule_exists_but_violated:
            continue  # runs last, needs the other findings
        else:
            findings.extend(func(tool_uses))

    if "C6" in selected:
        # C6 counts how often OTHER signals fired. Selecting it alone would
        # silently report "no violations" — an empty result that reads like a
        # clean bill of health. Compute its dependencies regardless of the
        # --signals filter, without adding them to the reported findings.
        dep_findings = list(findings)
        for dep in C6_RULE_KEYWORDS:
            if dep in selected:
                continue
            fn = SIGNAL_FUNCS.get(dep)
            if fn is None:
                continue
            dep_findings.extend(
                fn(assistant_texts, tool_uses)
                if fn is signal_skipped_verification
                else fn(tool_uses)
            )
        findings_for_c6 = dep_findings
        rules = ""
        for cand in (Path.home() / ".claude" / "CLAUDE.md",):
            try:
                rules = cand.read_text(encoding="utf-8")
            except OSError:
                pass
        findings.extend(signal_rule_exists_but_violated(findings_for_c6, rules))

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
