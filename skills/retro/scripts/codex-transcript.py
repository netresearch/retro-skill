#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""Render a Codex rollout JSONL as the Claude-shaped JSONL retro reads.

Usage:
    python3 codex-transcript.py --transcript-file rollout.jsonl \
        --match "a phrase the user typed" > session.jsonl

Codex records user/assistant messages as ``response_item/message`` and tool
calls as ``response_item/custom_tool_call``. In the functions.exec runtime, one
record is a JavaScript wrapper around several actual tools. Counting that
wrapper as one repeated ``exec`` command produces false retry and repetition
findings. This adapter unwraps literal ``tools.exec_command(...)`` and
``tools.apply_patch(...)`` calls, and does not count the wrapper itself.

JavaScript-computed arguments and batched tool results cannot be attributed
reliably without executing the transcript. Such calls are omitted from the
mechanical tool stream; read the original rollout for error and review context.
No input file is modified.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

TOOL_CALL = re.compile(r"tools\.([A-Za-z_][A-Za-z_0-9]*)\s*\(")
PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+)$", re.MULTILINE)


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


def _js_string(source: str, index: int) -> str | None:
    if index >= len(source) or source[index] not in "\"'":
        return None
    end = _skip_literal(source, index)
    token = source[index:end]
    if not token.endswith(source[index]) or len(token) < 2:
        return None
    try:
        value = json.loads(token) if token[0] == '"' else ast.literal_eval(token)
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, str) else None


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
                candidate = _js_string(source, cursor)
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
                return _js_string(source, after)
            cursor = end
            continue
        if char in "\"'`":
            cursor = _skip_literal(source, cursor)
        else:
            cursor += 1
    return None


def _nested_tools(source: str) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
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
            if command is not None:
                calls.append(("Bash", {"command": command}))
        elif name == "apply_patch":
            patch = _js_string(arguments, len(arguments) - len(arguments.lstrip()))
            if patch is not None:
                paths = [item.strip() for item in PATCH_FILE.findall(patch)]
                calls.append(("Patch", {"file_paths": paths}))
    return calls


def _message_event(payload: dict[str, Any]) -> dict[str, Any] | None:
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
    synthetic = role == "user" and text.startswith(
        ("<skill>", "# AGENTS.md instructions")
    )
    return {
        "type": role,
        "isMeta": synthetic,
        "message": {"id": payload.get("id"), "content": blocks},
    }


def render(rows: list[dict[str, Any]], token: str | None = None) -> list[str]:
    events: list[dict[str, Any]] = []
    human_texts: list[str] = []
    for row in rows:
        if row.get("type") != "response_item":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "message":
            event = _message_event(payload)
            if event:
                events.append(event)
                if event["type"] == "user" and not event["isMeta"]:
                    human_texts.extend(
                        item["text"] for item in event["message"]["content"]
                    )
        elif (
            payload.get("type") == "custom_tool_call" and payload.get("name") == "exec"
        ):
            source = payload.get("input")
            if not isinstance(source, str):
                continue
            for name, tool_input in _nested_tools(source):
                # No id: the detector counts this call without inventing a
                # result. All calls in one wrapper share the message id.
                events.append(
                    {
                        "type": "assistant",
                        "message": {
                            "id": payload.get("id"),
                            "content": [
                                {"type": "tool_use", "name": name, "input": tool_input}
                            ],
                        },
                    }
                )
    if not events:
        raise ValueError("no Codex response items found")
    if token and not any(token in text for text in human_texts):
        raise ValueError(f"no user message contains {token!r}")
    return [json.dumps(event, ensure_ascii=False) for event in events]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript-file", required=True, type=Path)
    parser.add_argument("--match", help="literal phrase in a human user message")
    args = parser.parse_args()
    try:
        with args.transcript_file.open(encoding="utf-8") as transcript:
            rows = [json.loads(line) for line in transcript if line.strip()]
        lines = render(rows, args.match)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"codex-transcript: {error}\n")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
