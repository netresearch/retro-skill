# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH

"""
transcript-results.py — tool results that Claude Code's Code Mode stores elsewhere.

Not a command. detect-mechanical.py, scan-cross-session.py and
derive-session-scope.py load it by path and pass every event they read through
`fill_nested_result()`.

A call made from a Code Mode script (the REPL tool) is stored as an event with
`isVirtual: true`. When it succeeds, its `tool_result` block has empty
`content`, and what it printed stands in the event's `toolUseResult`: an object
with `stdout` and `stderr` for a shell command, a string for an MCP tool.
Measured on 2026-11-25 in transcripts of Claude Code 2.1.330: every such event
held one result block. A failed call keeps its text in `content`.
"""

from __future__ import annotations

from typing import Any

# The notice Claude Code puts into a result whose command runs on: the readers
# take it as "the output is not here".
BACKGROUND_NOTICE = "Command running in background"


def _printed(stored: Any) -> str:
    """What the call printed, as far as `toolUseResult` states it as text."""
    if isinstance(stored, str):
        return stored
    if not isinstance(stored, dict) or stored.get("isImage"):
        return ""
    parts = [stored.get("stdout"), stored.get("stderr")]
    if stored.get("backgroundTaskId"):
        parts.append(BACKGROUND_NOTICE)
    return "\n".join(p for p in parts if isinstance(p, str) and p)


def fill_nested_result(event: dict[str, Any]) -> dict[str, Any]:
    """The event, with the text of a Code Mode call put into its result block.

    The block gets `nested: true`: the script read this text, the model did not
    unless the script returned it.
    """
    message = event.get("message")
    if event.get("isVirtual") is not True or not isinstance(message, dict):
        return event
    content = message.get("content")
    results = [
        block
        for block in (content if isinstance(content, list) else [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    if len(results) != 1 or results[0].get("content"):
        return event
    text = _printed(event.get("toolUseResult"))
    if text:
        results[0]["content"] = text
        results[0]["nested"] = True
    return event
