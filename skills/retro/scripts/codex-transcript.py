#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Render a Codex rollout JSONL as the Claude-shaped JSONL retro reads.

    python3 codex-transcript.py --transcript-file rollout.jsonl \\
        --match "a phrase the user typed" > session.jsonl

WHY THIS EXISTS. Codex CLI keeps a session as one rollout file,
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, in its own record format.
`detect-mechanical.py` and `collect-review-findings.py` read the Claude Code
format, so a rollout passed to them directly yields no turns and no tool calls.

MEASURED AGAINST real rollouts of Codex CLI 0.39.0 and 0.101.0 (22 sessions,
311 tool calls) and 0.163.0 (`codex exec`, 4 wrapper calls). Each record is
`{"timestamp", "type", "payload"}`; only `response_item`, `event_msg`,
`turn_context` and `session_meta` rows are read.

  · TOOL CALLS are `response_item/function_call` rows. `exec_command` (0.101)
    takes `arguments.cmd`; `shell` (0.39) takes `arguments.command` as an argv
    list, normally `["bash", "-lc", "<script>"]`. Both become `Bash`. Any other
    name (`update_plan`, `write_stdin`, `mcp__…`) is passed through unchanged.
  · RESULTS are `function_call_output` rows paired by `call_id`, so each call
    gets a `tool_use` id and a `tool_result`. `exec_command` writes text with a
    `Process exited with code N` header line and the body after `Output:`;
    `shell` writes a JSON string with `metadata.exit_code`. A non-zero code is
    `is_error`. `Process running with session ID N` is a call that had not
    finished: it gets no result, so it is not counted as a successful one.
  · `apply_patch` as `response_item/custom_tool_call` with the raw patch text
    as `input` becomes `Patch` with the files its headers name, resolved
    against the turn's directory. This shape was reported from Codex
    0.38.0-0.142.5 rollouts in the review of retro-skill#168; none of the
    rollouts measured here contains one.
  · The `functions.exec` runtime, the default of `codex exec` in 0.163.0,
    wraps tools in one `custom_tool_call` named `exec` whose `input` is
    JavaScript. Literal `tools.exec_command({cmd: "..."})` and
    `tools.apply_patch("...")` calls are rendered, the wrapper itself is not;
    a call whose argument is computed is left out and counted on stderr. The
    wrapper's `custom_tool_call_output` is a list of text items, the first a
    `Script completed|failed|terminated` header ending in `Output:`. When the
    wrapper holds exactly one literal call, that call takes the wrapper's
    `call_id` and the output as its result; a failed or terminated script is
    `is_error`. A command's own exit code is not in the output unless the
    script printed it, so a failing command in a completed script is visible
    only through the error text. With several calls the output cannot be
    attributed: the calls stay id-less and the output is not rendered.

HUMAN TURNS. Codex also writes injected text as `role: "user"` messages: the
`<environment_context>` block, `AGENTS.md` instructions, skill text. A user
message counts as human, for the detector and for `--match`, when 0.163.0's
`content_item_kinds` metadata says `user.*`; otherwise when an
`event_msg/user_message` (0.39, 0.101) or an `event_msg/item_completed`
`UserMessage` (0.163) carries the same text; and in a rollout with neither,
when it does not start with a known injected prefix. The others are `isMeta`.

A rollout whose `session_meta.source` names a subagent (a guardian review) is
refused: its user messages embed the main session's history, so `--match`
would find the main session's phrase in the wrong file.

A rollout with tool calls of which none could be rendered is refused, so a
format this adapter does not know reads as an error, not as a quiet session.
No input file is modified.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

TOOL_CALL = re.compile(r"tools\.([A-Za-z_][A-Za-z_0-9]*)\s*\(")
EXIT_CODE = re.compile(r"^Process exited with code (-?\d+)\s*$", re.MULTILINE)
RUNNING = re.compile(r"^Process running with session ID", re.MULTILINE)
#: The first line of a `functions.exec` wrapper's output, per script outcome.
SCRIPT_STATUS = {
    "Script completed": False,
    "Script failed": True,
    "Script terminated": True,
}
#: In a single-quoted JS string: an escape sequence, or a bare double quote.
SINGLE_QUOTED = re.compile(r'\\(.)|"', re.DOTALL)
#: Injected user text in a rollout that carries no human-message record.
INJECTED_PREFIXES = (
    "<environment_context>",
    "<user_instructions>",
    "<skill>",
    "# AGENTS.md instructions",
)
#: Shells whose `-c`/`-lc` script is the command a `shell` call ran.
SHELLS = {"bash", "sh", "zsh", "dash"}


def _load_sibling(filename: str):
    """A sibling script, loaded by path: its name is hyphenated like ours."""
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The patch-header parser and result shape of the opencode adapter: Codex's
#: patch format is the one opencode 1.x adopted.
_opencode = _load_sibling("opencode-transcript.py")


def _skip_literal(source: str, index: int) -> int:
    """Skip a JS string or comment starting at index, or advance one character."""
    char = source[index]
    if char in "\"'`":
        cursor = index + 1
        while cursor < len(source):
            if source[cursor] == "\\":
                cursor += 2
            elif source[cursor] == char:
                return cursor + 1
            else:
                cursor += 1
        return len(source)
    if source.startswith("//", index):
        newline = source.find("\n", index + 2)
        return len(source) if newline < 0 else newline + 1
    if source.startswith("/*", index):
        end = source.find("*/", index + 2)
        return len(source) if end < 0 else end + 2
    return index + 1


def _arguments(source: str, opening: int) -> tuple[str, int] | None:
    depth = 1
    cursor = opening + 1
    while cursor < len(source):
        char = source[cursor]
        if char in "\"'`" or source.startswith(("//", "/*"), cursor):
            cursor = _skip_literal(source, cursor)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : cursor], cursor + 1
        cursor += 1
    return None


def _unquote(token: str) -> str:
    """A JS string literal's value, decoded as JSON; raises ValueError if it is not one."""
    inner = token[1:-1]
    if token[0] == "'":
        # Re-quote for JSON: a bare `"` needs an escape, `\'` loses its own.
        inner = SINGLE_QUOTED.sub(
            lambda m: (
                '\\"'
                if m.group(1) is None
                else ("'" if m.group(1) == "'" else m.group(0))
            ),
            inner,
        )
    return json.loads(f'"{inner}"')


def _js_string(source: str, index: int, terminators: str) -> str | None:
    """The quoted literal at `index`, if it is the whole value.

    The next non-space character must be one of `terminators` or the end of
    `source`; otherwise the literal is an operand (`"a" + "b"`) and the value
    is computed, which this adapter does not evaluate.
    """
    if index >= len(source) or source[index] not in "\"'":
        return None
    end = _skip_literal(source, index)
    token = source[index:end]
    if not token.endswith(source[index]) or len(token) < 2:
        return None
    rest = source[end:].lstrip()
    if rest and rest[0] not in terminators:
        return None
    try:
        return _unquote(token)
    except ValueError:
        return None


def _object_string_property(source: str, key: str) -> str | None:
    """Read one literal property of the outer JS object, not text inside values."""
    cursor = 0
    depth = 0
    while cursor < len(source):
        char = source[cursor]
        if source.startswith(("//", "/*"), cursor):
            cursor = _skip_literal(source, cursor)
            continue
        if char == "{":
            depth += 1
            cursor += 1
            continue
        if char == "}":
            depth -= 1
            cursor += 1
            continue
        if depth == 1:
            candidate = None
            if char in "\"'":
                candidate = _js_string(source, cursor, ":")
                end = _skip_literal(source, cursor)
            elif char.isalpha() or char == "_":
                match = re.match(r"[A-Za-z_][A-Za-z_0-9]*", source[cursor:])
                candidate = match.group() if match else None
                end = cursor + len(candidate) if candidate else cursor + 1
            else:
                cursor += 1
                continue
            after = end
            while after < len(source) and source[after].isspace():
                after += 1
            if candidate == key and after < len(source) and source[after] == ":":
                after += 1
                while after < len(source) and source[after].isspace():
                    after += 1
                return _js_string(source, after, ",}")
            cursor = end
            continue
        if char in "\"'`":
            cursor = _skip_literal(source, cursor)
        else:
            cursor += 1
    return None


def _patch_input(patch: str, directory: str | None) -> dict[str, Any]:
    files = _opencode._patch_files(patch, v2=False)
    return {"file_paths": [_opencode._resolve(p, directory, False) for p in files]}


def _nested_tools(
    source: str, directory: str | None
) -> tuple[list[tuple[str, dict[str, Any]]], int]:
    """Literal tool calls inside a `functions.exec` wrapper, and how many were not."""
    calls: list[tuple[str, dict[str, Any]]] = []
    computed = 0
    cursor = 0
    while cursor < len(source):
        if source[cursor] in "\"'`" or source.startswith(("//", "/*"), cursor):
            cursor = _skip_literal(source, cursor)
            continue
        match = TOOL_CALL.match(source, cursor)
        if not match:
            cursor += 1
            continue
        opening = match.end() - 1
        parsed = _arguments(source, opening)
        if not parsed:
            cursor = match.end()
            continue
        arguments, cursor = parsed
        name = match.group(1)
        if name == "exec_command":
            command = _object_string_property(arguments, "cmd")
            if command is None:
                computed += 1
            else:
                calls.append(("Bash", {"command": command}))
        elif name == "apply_patch":
            patch = _js_string(arguments.strip(), 0, "")
            if patch is None:
                computed += 1
            else:
                calls.append(("Patch", _patch_input(patch, directory)))
    return calls, computed


def _shell_command(argv: Any) -> str | None:
    """The command a `shell` call ran: the script of `bash -lc`, else the argv."""
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return None
    shell = len(argv) == 3 and os.path.basename(argv[0]) in SHELLS
    if shell and argv[1] in ("-c", "-lc"):
        return argv[2]
    return shlex.join(argv)


def _call(payload: dict[str, Any], directory: str | None) -> tuple[str, dict[str, Any]]:
    """A `function_call` or direct `custom_tool_call` in the detector's vocabulary."""
    name = str(payload.get("name") or "tool")
    if payload.get("type") == "custom_tool_call":
        raw = payload.get("input")
        if name == "apply_patch" and isinstance(raw, str):
            return "Patch", _patch_input(raw, directory)
        return name, {}
    try:
        arguments = json.loads(payload.get("arguments") or "{}")
    except (TypeError, ValueError):
        arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    workdir = arguments.get("workdir")
    if isinstance(workdir, str) and workdir:
        directory = workdir
    if name == "exec_command" and isinstance(arguments.get("cmd"), str):
        return "Bash", {"command": arguments["cmd"]}
    if name == "shell":
        command = _shell_command(arguments.get("command"))
        if command is not None:
            return "Bash", {"command": command}
    if name == "apply_patch" and isinstance(arguments.get("input"), str):
        return "Patch", _patch_input(arguments["input"], directory)
    return name, arguments


def _flatten(output: Any) -> str:
    """A call output as text: a list of text items is joined, anything else dumped."""
    if isinstance(output, str):
        return output
    if isinstance(output, list) and all(
        isinstance(item, dict) and isinstance(item.get("text"), str) for item in output
    ):
        return "".join(item["text"] for item in output)
    return json.dumps(output, ensure_ascii=False)


def _wrapper_result(output: Any) -> tuple[str, bool]:
    """A `functions.exec` output as (text after the header, script failed)."""
    text = _flatten(output)
    status, _, rest = text.partition("\n")
    _, marker, body = rest.partition("Output:\n")
    return (body if marker else text), SCRIPT_STATUS.get(status, False)


def _result(output: Any) -> tuple[str, bool] | None:
    """A call output as (text, is_error); None while the call is still running."""
    output = _flatten(output)
    try:
        data = json.loads(output)
    except ValueError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("metadata"), dict):
        code = data["metadata"].get("exit_code")
        text = data.get("output")
        text = text if isinstance(text, str) else output
        return text, isinstance(code, int) and code != 0
    code = EXIT_CODE.search(output)
    if code is None:
        if RUNNING.search(output):
            return None
        return output, False
    _, marker, body = output.partition("\nOutput:\n")
    return (body if marker else output), int(code.group(1)) != 0


def _human_record_texts(rows: list[dict[str, Any]]) -> set[str] | None:
    """Texts Codex recorded as typed by the human; None when it recorded none."""
    texts: set[str] = set()
    found = False
    for row in rows:
        payload = row.get("payload")
        if row.get("type") != "event_msg" or not isinstance(payload, dict):
            continue
        if payload.get("type") == "user_message":
            found = True
            if isinstance(payload.get("message"), str):
                texts.add(payload["message"].strip())
        elif payload.get("type") == "item_completed":
            item = payload.get("item")
            if isinstance(item, dict) and item.get("type") == "UserMessage":
                found = True
                parts = [
                    c.get("text", "")
                    for c in item.get("content") or []
                    if isinstance(c, dict) and isinstance(c.get("text"), str)
                ]
                texts.add("\n".join(parts).strip())
    return texts if found else None


def _is_human(payload: dict[str, Any], text: str, human_texts: set[str] | None) -> bool:
    meta = payload.get("internal_chat_message_metadata_passthrough")
    kinds = meta.get("content_item_kinds") if isinstance(meta, dict) else None
    if isinstance(kinds, list) and kinds:
        return all(isinstance(k, str) and k.startswith("user.") for k in kinds)
    if human_texts is not None:
        return text.strip() in human_texts
    return not text.lstrip().startswith(INJECTED_PREFIXES)


def _message_event(
    payload: dict[str, Any], timestamp: Any, human_texts: set[str] | None
) -> dict[str, Any] | None:
    role = payload.get("role")
    if role not in {"user", "assistant"}:
        return None
    blocks = [
        {"type": "text", "text": item["text"]}
        for item in payload.get("content", [])
        if isinstance(item, dict)
        and item.get("type") in {"input_text", "output_text"}
        and isinstance(item.get("text"), str)
    ]
    if not blocks:
        return None
    text = "\n".join(block["text"] for block in blocks)
    return {
        "type": role,
        "isMeta": role == "user" and not _is_human(payload, text, human_texts),
        "timestamp": timestamp,
        "message": {"role": role, "id": payload.get("id"), "content": blocks},
    }


def _event(role: str, block: dict[str, Any], timestamp: Any, message_id: Any) -> dict:
    return {
        "type": role,
        "timestamp": timestamp,
        "message": {"role": role, "id": message_id, "content": [block]},
    }


def _refuse_subagent(payload: dict[str, Any]) -> None:
    source = payload.get("source")
    if isinstance(source, dict) and "subagent" in source:
        raise ValueError(
            f"this is a subagent rollout (source {json.dumps(source)}); "
            "convert the main session's rollout instead"
        )


def _wrapper_events(
    payload: dict[str, Any], timestamp: Any, directory: str | None
) -> tuple[list[dict[str, Any]], int]:
    """The literal calls of a `functions.exec` wrapper, and the computed count."""
    source = payload.get("input")
    if not isinstance(source, str):
        return [], 1
    nested, computed = _nested_tools(source, directory)
    # The wrapper's single output belongs to its call only when it made exactly
    # one; otherwise the calls stay id-less, which the detector counts where
    # they stand, without a result.
    call_id = payload.get("call_id") if len(nested) == 1 and not computed else None
    events = []
    for name, tool_input in nested:
        use = {"type": "tool_use", "name": name, "input": tool_input}
        if call_id:
            use["id"] = call_id
        events.append(_event("assistant", use, timestamp, payload.get("id")))
    return events, computed


def render(rows: list[dict[str, Any]], token: str | None = None) -> list[str]:
    events: list[dict[str, Any]] = []
    human_texts = _human_record_texts(rows)
    human_seen: list[str] = []
    calls_seen: list[str] = []
    rendered = 0
    computed = 0
    directory: str | None = None
    #: call_id of each wrapper -> whether its one call took that id.
    wrappers: dict[Any, bool] = {}
    for row in rows:
        kind = row.get("type")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        timestamp = row.get("timestamp")
        if kind in ("session_meta", "turn_context"):
            if kind == "session_meta":
                _refuse_subagent(payload)
            cwd = payload.get("cwd")
            directory = cwd if isinstance(cwd, str) and cwd else directory
            continue
        if kind != "response_item":
            continue
        item = payload.get("type")
        if item == "message":
            event = _message_event(payload, timestamp, human_texts)
            if event:
                events.append(event)
                if event["type"] == "user" and not event["isMeta"]:
                    human_seen.extend(b["text"] for b in event["message"]["content"])
        elif item == "custom_tool_call" and payload.get("name") == "exec":
            calls_seen.append("exec")
            nested, skipped = _wrapper_events(payload, timestamp, directory)
            events.extend(nested)
            rendered += len(nested)
            computed += skipped
            wrappers[payload.get("call_id")] = any(
                "id" in e["message"]["content"][0] for e in nested
            )
        elif item in ("function_call", "custom_tool_call"):
            calls_seen.append(str(payload.get("name")))
            name, tool_input = _call(payload, directory)
            use = {
                "type": "tool_use",
                "id": payload.get("call_id") or payload.get("id"),
                "name": name,
                "input": tool_input,
            }
            events.append(_event("assistant", use, timestamp, payload.get("id")))
            rendered += 1
        elif item == "custom_tool_call_output" and payload.get("call_id") in wrappers:
            if wrappers[payload["call_id"]]:
                result = _wrapper_result(payload.get("output"))
                block = _opencode._tool_result(payload["call_id"], *result)
                events.append(_event("user", block, timestamp, None))
        elif item in ("function_call_output", "custom_tool_call_output"):
            result = _result(payload.get("output"))
            if result is not None:
                block = _opencode._tool_result(payload.get("call_id"), *result)
                events.append(_event("user", block, timestamp, None))
    if not events:
        raise ValueError("no Codex response items found")
    if calls_seen and not rendered:
        names = ", ".join(sorted(set(calls_seen)))
        raise ValueError(f"{len(calls_seen)} tool calls ({names}), none rendered")
    if token and not any(token in text for text in human_seen):
        raise ValueError(f"no human user message contains {token!r}")
    if computed:
        print(
            f"codex-transcript: {computed} tool call(s) inside functions.exec "
            "have computed arguments and are not rendered",
            file=sys.stderr,
        )
    return [json.dumps(event, ensure_ascii=False) for event in events]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="codex-transcript",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--transcript-file", required=True, type=Path)
    parser.add_argument("--match", help="literal phrase in a human user message")
    args = parser.parse_args()
    try:
        with args.transcript_file.open(encoding="utf-8") as transcript:
            rows = [json.loads(line) for line in transcript if line.strip()]
        lines = render(rows, args.match)
    except (OSError, ValueError) as error:
        parser.exit(2, f"codex-transcript: {error}\n")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
