#!/usr/bin/env python3
"""Render an opencode session as the JSONL shape `detect-mechanical.py` reads.

    python3 opencode-transcript.py --match "<a token from the session>" \\
        [--db ~/.local/share/opencode/opencode.db] [--session <id>] > session.jsonl

WHY THIS EXISTS. `detect-mechanical.py` parses a Claude Code transcript, and an
agent running under opencode keeps its session somewhere else entirely: a SQLite
database, `~/.local/share/opencode/opencode.db`, as JSON in one of two schemas.
Without this, layer A simply cannot run on those sessions — the operator is left
doing the LLM pass by hand, which is the cost this project exists to remove.

TWO SCHEMAS, chosen per session by which table holds its rows:

  · V2 (opencode 2.x): `session_v2` + `session_message`, one row per message,
    ordered by `seq`. The role is the `type` COLUMN — `data` carries no `role` —
    and an assistant's blocks sit in `data.content[]`;
  · legacy (opencode 1.x): `message` + `part`, the role in `message.data` and the
    blocks in `part.data`, one row each.

A session found in both is rendered from V2. opencode 2.x copies every 1.x
session into the V2 tables under the same id and never deletes the legacy rows,
but writes new messages only to V2 — a fresh 2.x database has no `message` or
`part` table at all — so the legacy copy of such a session stops at the upgrade.
A database that has neither table set is refused.

THE SESSION IS FOUND BY CONTENT. `--match` takes any token from the session under
review and greps the stored JSON for it, exactly as `references/workflow.md`
requires of the Claude path: several sessions share one project, so the newest row
is regularly somebody else's. `--session` skips the search when the id is known.

THE LEGACY MAPPING, and the two places it had to be discovered by measuring:

  · a `text` part becomes a `text` block; a `synthetic` one, which opencode
    injected rather than the user typed, is dropped;
  · a `tool` part holds BOTH the call and its result, so it becomes a `tool_use`
    block on the assistant turn AND a `tool_result` block on a user turn
    immediately after — which is where Claude puts it;
  · every `tool_use` NEEDS an `id` and every `tool_result` a matching `tool_use_id`.
    Without them `detect-mechanical.py` raises `KeyError: 'id'` on its first tool
    block, so the id falls back through `callID` to the part's own row id.

THE V2 MAPPING, read from opencode's `packages/schema/src/session-message.ts` at
v2.0.15: a `user` row's `data.text` becomes a `text` block; an `assistant` row's
`text` blocks stay, `reasoning` blocks are dropped as in the legacy path, and a
`tool` block (`id`, `name`, `state.input`) becomes the same `tool_use` +
`tool_result` pair. Its output is `state.content[]` and its error
`state.error.message`; there is no `state.output`. A `streaming` call carries
its input as a partial JSON STRING, which the detector would call `.get` on.
The other row types (`synthetic`, `shell`, `compaction`, `system`, …) are not
rendered.

TOOL NAMES. opencode names its tools `bash` (1.x) or `shell` (2.x), `read`,
`edit`, … and its file tools take `filePath` (1.x) or `path` (2.x); the
detector's signals match Claude's `Bash`, `Read`, `Edit` and `file_path`. Both
are renamed, or every shell and file signal passes over an opencode session
without firing. A migrated session keeps the 1.x names. Relative file paths are
resolved against the session's directory, so a patch that names `src/app.py`
and a read of `/repo/src/app.py` count as the same file.

READ-ONLY. The database is opened with `mode=ro`, so pointing this at a live
database cannot corrupt a session that is still being written.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from urllib.parse import quote

DEFAULT_DB = "~/.local/share/opencode/opencode.db"
#: A block of a very large tool output is worth keeping for the friction signals
#: (an error is at the top, a stack trace at the bottom) and not worth carrying
#: whole: layer A only reads snippets, and a session's outputs run to megabytes.
RESULT_CHARS = 6000

#: opencode's tool names, 1.x and 2.x, as the detector knows them from Claude
#: Code — only those a detector signal reads by name. `patch` has no Claude
#: counterpart: it becomes `Patch`, which the detector's A12 counts as an edit
#: of every file in `file_paths`.
TOOL_NAMES = {
    "bash": "Bash",
    "shell": "Bash",
    "read": "Read",
    "edit": "Edit",
    "write": "Write",
    "apply_patch": "Patch",
    "patch": "Patch",
    "grep": "Grep",
    "glob": "Glob",
    "skill": "Skill",
}
#: opencode's input keys that the detector reads under Claude's name. The file
#: tools take `filePath` in 1.x and `path` in 2.x; `path` is only renamed for
#: them, because on `grep` and `glob` it names a directory.
INPUT_KEYS = {"filePath": "file_path"}
FILE_TOOLS = {"Read", "Edit", "Write"}
#: The header lines of opencode's patch format that name a file.
PATCH_FILE_MARKERS = (
    "*** Add File: ",
    "*** Update File: ",
    "*** Delete File: ",
    "*** Move to: ",
)

#: A 1.x call still running at the upgrade is copied into V2 as this error. The
#: legacy path emits no result for a running call; neither does the V2 one, or
#: every interrupted call of a migrated session reads as a failed command.
MIGRATION_INTERRUPTED = "tool.interrupted"


def _snippet(output: str) -> str:
    """Head and tail of an over-long output: the error is at the top, the trace at the bottom."""
    if len(output) <= RESULT_CHARS:
        return output
    half = RESULT_CHARS // 2
    return output[:half] + "\n…\n" + output[-half:]


def _connect(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise SystemExit(f"opencode-transcript: no database at {path}")
    # The path is percent-encoded: a name carrying its own `?query` would
    # otherwise terminate the URI and override `mode=ro`, which is what the
    # READ-ONLY promise above rests on. `abspath` settles the relative-path
    # ambiguity `file:` URIs have.
    return sqlite3.connect(
        "file:" + quote(os.path.abspath(path)) + "?mode=ro", uri=True
    )


#: Per schema: the tables that identify it, the table with one row per message,
#: and the table whose `data` holds the session's content. V2 is listed first:
#: a session in both schemas is rendered from V2.
SCHEMAS = {
    "v2": ({"session_v2", "session_message"}, "session_message", "session_message"),
    "legacy": ({"message", "part"}, "message", "part"),
}


def _schemas(conn: sqlite3.Connection) -> list[str]:
    """The schemas this database carries, or a refusal when it carries neither."""
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    found = [name for name, (needed, _, _) in SCHEMAS.items() if needed <= tables]
    if not found:
        raise SystemExit(
            "opencode-transcript: no supported schema: expected the tables"
            " session_v2 + session_message (opencode 2.x) or message + part (1.x)"
        )
    return found


def schema_of(conn: sqlite3.Connection, session_id: str) -> str | None:
    """The first schema whose message table holds `session_id`, or None."""
    for name in _schemas(conn):
        query = f"SELECT 1 FROM {SCHEMAS[name][1]} WHERE session_id=? LIMIT 1"
        if conn.execute(query, (session_id,)).fetchone() is not None:
            return name
    return None


def find_session(conn: sqlite3.Connection, token: str) -> str:
    """The session whose content carries `token`, or a refusal naming the ambiguity."""
    # `_` and `%` are LIKE wildcards, so an unescaped token matches more than it
    # says: `foo_bar` also finds `fooXbar`, and the extra session shows up as the
    # ambiguity refusal below rather than as a wrong answer — but a token that is
    # only wildcards matches everything.
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = sorted(
        {
            row
            for name in _schemas(conn)
            for row in conn.execute(
                f"SELECT DISTINCT session_id FROM {SCHEMAS[name][2]}"
                " WHERE data LIKE ? ESCAPE '\\'",
                (f"%{escaped}%",),
            )
        }
    )
    if not rows:
        raise SystemExit(f"opencode-transcript: no session carries {token!r}")
    if len(rows) > 1:
        names = ", ".join(r[0] for r in rows)
        raise SystemExit(
            f"opencode-transcript: {token!r} matches {len(rows)} sessions: {names}"
        )
    return rows[0][0]


def render(conn: sqlite3.Connection, session_id: str) -> list[str]:
    """The session as detector JSONL lines, from whichever schema holds it."""
    schema = schema_of(conn, session_id)
    # A mistyped id otherwise renders nothing and exits 0, which reads as an
    # empty session. Asked of the message tables, not of `session`: those are
    # the rows the adapter goes on to read.
    if schema is None:
        raise SystemExit(f"opencode-transcript: no messages for session {session_id!r}")
    if schema == "v2":
        return _render_v2(conn, session_id)
    return _render_legacy(conn, session_id)


def _event(role: str, content: list[dict], timestamp: int) -> str:
    return json.dumps(
        {
            "type": role,
            "message": {"role": role, "content": content},
            "timestamp": timestamp,
        },
        ensure_ascii=False,
    )


def _events(
    role: str, blocks: list[dict], results: list[dict], timestamp: int
) -> list[str]:
    """One turn's blocks, then its tool results on a user turn — where Claude puts them."""
    lines = [_event(role, blocks, timestamp)] if blocks else []
    if results:
        lines.append(_event("user", results, timestamp))
    return lines


def _text(text: str | None) -> list[dict]:
    return [{"type": "text", "text": text}] if text and text.strip() else []


def _resolve(path: object, directory: str | None) -> object:
    if isinstance(path, str) and directory and not os.path.isabs(path):
        return os.path.normpath(os.path.join(directory, path))
    return path


def _patch_files(text: object) -> list[str]:
    """The files a patch adds, updates, deletes or moves to, in patch order."""
    lines = text.splitlines() if isinstance(text, str) else []
    return [
        line[len(marker) :].strip()
        for line in lines
        for marker in PATCH_FILE_MARKERS
        if line.startswith(marker)
    ]


def _tool_use(tool_id: str, name: str, payload: object, directory: str | None) -> dict:
    name = TOOL_NAMES.get(name, name)
    inputs = payload if isinstance(payload, dict) else {}
    inputs = {INPUT_KEYS.get(key, key): value for key, value in inputs.items()}
    if name in FILE_TOOLS and "file_path" not in inputs and "path" in inputs:
        inputs["file_path"] = inputs.pop("path")
    if "file_path" in inputs:
        inputs["file_path"] = _resolve(inputs["file_path"], directory)
    if name == "Patch":
        files = _patch_files(inputs.get("patchText"))
        inputs["file_paths"] = [_resolve(path, directory) for path in files]
    return {"type": "tool_use", "id": tool_id, "name": name, "input": inputs}


def _tool_result(tool_id: str, output: str, is_error: bool) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": _snippet(output),
        "is_error": is_error,
    }


def _v2_output(state: dict) -> str:
    """A V2 tool result as text: the error message first, then the content items."""
    texts = []
    error = state.get("error")
    if isinstance(error, dict):
        error = error.get("message")
    if error:
        texts.append(str(error))
    for item in state.get("content") or []:
        if item.get("type") == "text":
            texts.append(item.get("text") or "")
        elif item.get("type") == "file":
            texts.append(f"[file {item.get('name') or item.get('uri') or ''}]")
    return "\n".join(text for text in texts if text)


def _v2_tool(block: dict, directory: str | None) -> tuple[dict, dict | None]:
    """A V2 tool block as its `tool_use` and, once the call has finished, its result."""
    state = block.get("state") or {}
    # `streaming` stores the input as a partial JSON string; `_tool_use` drops it.
    name = block.get("name") or "tool"
    use = _tool_use(block.get("id"), name, state.get("input"), directory)
    status = state.get("status")
    error = state.get("error")
    interrupted = isinstance(error, dict) and error.get("type") == MIGRATION_INTERRUPTED
    if status not in ("completed", "error") or interrupted:
        return use, None
    return use, _tool_result(block.get("id"), _v2_output(state), status == "error")


def _v2_assistant(data: dict, directory: str | None) -> tuple[list[dict], list[dict]]:
    blocks: list[dict] = []
    results: list[dict] = []
    for block in data.get("content") or []:
        if block.get("type") == "text":
            blocks.extend(_text(block.get("text")))
        elif block.get("type") == "tool":
            use, result = _v2_tool(block, directory)
            blocks.append(use)
            results.extend([result] if result else [])
    return blocks, results


def _render_v2(conn: sqlite3.Connection, session_id: str) -> list[str]:
    directory = _directory(conn, "session_v2", session_id)
    lines: list[str] = []
    for role, data, timestamp in conn.execute(
        "SELECT type, data, time_created FROM session_message WHERE session_id=? ORDER BY seq",
        (session_id,),
    ):
        data = json.loads(data)
        if role == "user":
            lines.extend(_events("user", _text(data.get("text")), [], timestamp))
        elif role == "assistant":
            blocks, results = _v2_assistant(data, directory)
            lines.extend(_events("assistant", blocks, results, timestamp))
    return lines


def _directory(conn: sqlite3.Connection, table: str, session_id: str) -> str | None:
    """The session's working directory, for resolving relative file paths."""
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone():
        return None
    row = conn.execute(
        f"SELECT directory FROM {table} WHERE id=?", (session_id,)
    ).fetchone()
    return row[0] if row else None


def _legacy_tool(
    row_id: str, part: dict, directory: str | None
) -> tuple[dict, dict | None]:
    """A legacy tool part as its `tool_use` and, once the call has finished, its result."""
    state = part.get("state") or {}
    call = part.get("call") or {}
    name = part.get("tool") or state.get("tool") or call.get("tool") or "tool"
    payload = state.get("input") or call.get("input") or {}
    tool_id = part.get("callID") or part.get("id") or row_id
    use = _tool_use(tool_id, name, payload, directory)
    # `pending` and `running` carry neither output nor error; emitting
    # a result for them files an unfinished call as a successful one.
    if state.get("status") in ("pending", "running"):
        return use, None
    output = state.get("output")
    if output is None:
        output = state.get("error") or ""
    is_error = state.get("status") in ("error", "failed")
    return use, _tool_result(tool_id, str(output), is_error)


def _legacy_blocks(
    role: str, parts: list[tuple[str, dict]], directory: str | None
) -> tuple[list[dict], list[dict]]:
    blocks: list[dict] = []
    results: list[dict] = []
    for row_id, part in parts:
        kind = part.get("type")
        if kind == "text" and not part.get("synthetic"):
            blocks.extend(_text(part.get("text")))
        elif kind == "tool":
            use, result = _legacy_tool(row_id, part, directory)
            if role == "assistant":
                blocks.append(use)
            results.extend([result] if result else [])
    return blocks, results


def _render_legacy(conn: sqlite3.Connection, session_id: str) -> list[str]:
    messages = conn.execute(
        "SELECT id, data, time_created FROM message WHERE session_id=? ORDER BY time_created",
        (session_id,),
    ).fetchall()
    parts: dict[str, list[tuple[str, dict]]] = {}
    for row_id, message_id, data, _ts in conn.execute(
        "SELECT id, message_id, data, time_created FROM part WHERE session_id=? ORDER BY time_created",
        (session_id,),
    ):
        parts.setdefault(message_id, []).append((row_id, json.loads(data)))

    directory = _directory(conn, "session", session_id)
    lines: list[str] = []
    for message_id, data, timestamp in messages:
        role = json.loads(data).get("role")
        if role in ("user", "assistant"):
            parts_of = parts.get(message_id, [])
            blocks, results = _legacy_blocks(role, parts_of, directory)
            lines.extend(_events(role, blocks, results, timestamp))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opencode-transcript", description=__doc__)
    parser.add_argument("--match", help="a token from the session under review")
    parser.add_argument("--session", help="the opencode session id, when it is known")
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args(argv)

    if not args.match and not args.session:
        parser.error("pass --match <token> or --session <id>")

    conn = _connect(os.path.expanduser(args.db))
    session_id = args.session or find_session(conn, args.match or "")
    lines = render(conn, session_id)
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
