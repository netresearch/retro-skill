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
A `running` or `streaming` call gets no result, and neither does a
`tool.interrupted` error, which is how 2.x copies a 1.x call that was still
running at the upgrade. The other row types (`synthetic`, `shell`,
`compaction`, `system`, …) are not rendered.

TOOL NAMES. opencode names its tools `bash` (1.x) or `shell` (2.x), `read`,
`edit`, … and its file tools take `filePath` (1.x) or `path` (2.x); the
detector's signals match Claude's `Bash`, `Read`, `Edit` and `file_path`. Both
are renamed, or every shell and file signal passes over an opencode session
without firing. A migrated session keeps the 1.x names. `patch` (2.x) and
`apply_patch` (1.x) become `Patch`, with the files the patch headers name in
`file_paths`; the detector's A12 counts it as an edit of each. Relative file
paths are resolved against the session's directory, so a patch that names
`src/app.py` and a read of `/repo/src/app.py` count as the same file; 2.x
expands `~` and `~/…` to a home directory the database does not record, so
those stay as they are. A 2.x session can be moved or forked; each row is
resolved against the directory it ran in, taken from the `location-switched`
rows and, for a fork's copied rows, the parent's.

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
#: The header lines of opencode's patch format that name a file. No trailing
#: space: 1.x's parser accepts `*** Update File:app.py` and trims the rest.
#: 2.x's `patch` trims a line before matching a hunk header, except inside an
#: Update hunk, where an indented line is context (`packages/util/src/patch.ts`
#: at v2.0.15); 1.x's `apply_patch` always matches the raw line. Neither
#: version accepts an indented `*** Move to:`.
PATCH_UPDATE_MARKER = "*** Update File:"
PATCH_HUNK_MARKERS = ("*** Add File:", PATCH_UPDATE_MARKER, "*** Delete File:")
PATCH_MOVE_MARKER = "*** Move to:"

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


def _resolve(path: object, directory: str | None, expands_home: bool) -> object:
    # opencode 2.x expands `~` and `~/…` to the session user's home, which the
    # database does not record, so those stay as they are. 1.x resolves them
    # against the directory like any other relative path.
    if not isinstance(path, str) or not directory or os.path.isabs(path):
        return path
    if expands_home and (path == "~" or path.startswith("~/")):
        return path
    return os.path.normpath(os.path.join(directory, path))


def _patch_files(text: object, trims_hunk_headers: bool) -> list[str]:
    """The files a patch adds, updates, deletes or moves to, in patch order."""
    files, in_update = [], False
    for line in text.splitlines() if isinstance(text, str) else []:
        header = line.strip() if trims_hunk_headers and not in_update else line
        marker = next((m for m in PATCH_HUNK_MARKERS if header.startswith(m)), None)
        if marker:
            in_update = marker == PATCH_UPDATE_MARKER
            files.append(header[len(marker) :].strip())
        elif line.startswith(PATCH_MOVE_MARKER):
            files.append(line[len(PATCH_MOVE_MARKER) :].strip())
    return [path for path in files if path]


def _tool_use(
    tool_id: str,
    name: str,
    payload: object,
    directory: str | None,
    expands_home: bool = False,
) -> dict:
    trims_hunk_headers = name == "patch"
    name = TOOL_NAMES.get(name, name)
    inputs = payload if isinstance(payload, dict) else {}
    inputs = {INPUT_KEYS.get(key, key): value for key, value in inputs.items()}
    if name in FILE_TOOLS and "file_path" not in inputs and "path" in inputs:
        inputs["file_path"] = inputs.pop("path")
    if "file_path" in inputs:
        inputs["file_path"] = _resolve(inputs["file_path"], directory, expands_home)
    if name == "Patch":
        files = _patch_files(inputs.get("patchText"), trims_hunk_headers)
        inputs["file_paths"] = [_resolve(p, directory, expands_home) for p in files]
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
    use = _tool_use(
        block.get("id"), name, state.get("input"), directory, expands_home=True
    )
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


def _location(data: dict, *keys: str) -> str | None:
    """The directory of a `location-switched` row, at `data[keys…].location`."""
    for key in keys:
        data = data.get(key) or {}
    return (data.get("location") or {}).get("directory")


def _timeline(conn: sqlite3.Connection, session_id: str) -> dict:
    """What decides a V2 session's directory at a given `seq`.

    A move rewrites `session_v2.directory` and appends a `location-switched`
    row naming the previous location, so the current directory holds only
    after the last move. A fork starts in its parent's directory at fork time
    and copies the parent's rows with their `seq`, under ids ending `_<seq>` —
    moves included, so the fork's own copies say where most copied rows ran.
    """
    # `SELECT *`: a database from before forks has no `fork_session_id`.
    cursor = conn.execute("SELECT * FROM session_v2 WHERE id=?", (session_id,))
    session = cursor.fetchone()
    names = [column[0] for column in cursor.description]
    info = dict(zip(names, session)) if session else {}
    switches, copied, seqs = [], set(), set()
    for row_id, kind, seq, data, created in conn.execute(
        "SELECT id, type, seq, data, time_created FROM session_message"
        " WHERE session_id=? ORDER BY seq",
        (session_id,),
    ):
        seqs.add(seq)
        if kind == "location-switched":
            previous = _location(json.loads(data), "previous")
            switches.append((seq, previous, created))
        if row_id.endswith(f"_{seq}"):
            copied.add(seq)
    return {
        "directory": info.get("directory"),
        "created": info.get("time_created"),
        "parent": info.get("fork_session_id"),
        "switches": switches,
        "copied": copied,
        # The fork boundary: the last row the fork copied.
        "boundary": max(copied, default=None),
        "seqs": seqs,
    }


def _directory_at(
    conn: sqlite3.Connection,
    session_id: str,
    seq: int,
    timelines: dict,
    visiting: frozenset = frozenset(),
) -> tuple[str | None, int | None]:
    """The directory the row at `seq` ran in, and when the move that says so ran.

    A row's directory is the previous location of the next move after it, or
    the session's directory when none follows (then the time is None). A
    fork's copied row with no copied move after it ran where the parent was at
    the fork boundary. The parent is asked only while it still holds the
    boundary row, and its answer counts only when a move row made before the
    fork gives it. A revert deletes rows from a boundary on without restoring
    the directory, so neither the parent's directory nor a move made after a
    revert need name where the copied rows ran; a move made after the fork adds
    nothing the fork's own directory — the parent's at fork time — does not
    already say.
    """
    timeline = _cached_timeline(conn, session_id, timelines)
    later = [switch for switch in timeline["switches"] if switch[0] > seq]
    copied_move_follows = any(switch[0] in timeline["copied"] for switch in later)
    if seq in timeline["copied"] and not copied_move_follows:
        answer = _parent_answer(conn, session_id, timelines, visiting)
        if answer:
            return answer
    if later:
        return later[0][1], later[0][2]
    return timeline["directory"], None


def _parent_answer(
    conn: sqlite3.Connection, session_id: str, timelines: dict, visiting: frozenset
) -> tuple[str | None, int] | None:
    """Where a fork's parent was at the fork boundary, if a move made before
    the fork says so; None when the parent cannot answer."""
    timeline = timelines[session_id]
    parent, boundary = timeline["parent"], timeline["boundary"]
    if not parent or parent in visiting:
        return None
    if boundary not in _cached_timeline(conn, parent, timelines)["seqs"]:
        return None
    found, when = _directory_at(
        conn, parent, boundary, timelines, visiting | {session_id}
    )
    # Both times are wall-clock epoch milliseconds. A fork time of 0 is
    # opencode's default for an event that carried none: unknown.
    forked = timeline["created"]
    if when is not None and (not forked or when <= forked):
        return found, when
    return None


def _cached_timeline(
    conn: sqlite3.Connection, session_id: str, timelines: dict
) -> dict:
    if session_id not in timelines:
        timelines[session_id] = _timeline(conn, session_id)
    return timelines[session_id]


def _render_v2(conn: sqlite3.Connection, session_id: str) -> list[str]:
    timelines: dict = {}
    lines: list[str] = []
    for role, data, timestamp, seq in conn.execute(
        "SELECT type, data, time_created, seq FROM session_message WHERE session_id=? ORDER BY seq",
        (session_id,),
    ).fetchall():
        data = json.loads(data)
        if role == "user":
            lines.extend(_events("user", _text(data.get("text")), [], timestamp))
        elif role == "assistant":
            directory, _ = _directory_at(conn, session_id, seq, timelines)
            blocks, results = _v2_assistant(data, directory)
            lines.extend(_events("assistant", blocks, results, timestamp))
    return lines


def _legacy_directory(conn: sqlite3.Connection, session_id: str) -> str | None:
    """A 1.x session's working directory, for resolving relative file paths."""
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session'"
    ).fetchone():
        return None
    row = conn.execute(
        "SELECT directory FROM session WHERE id=?", (session_id,)
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

    directory = _legacy_directory(conn, session_id)
    lines: list[str] = []
    for message_id, data, timestamp in messages:
        role = json.loads(data).get("role")
        if role in ("user", "assistant"):
            parts_of = parts.get(message_id, [])
            blocks, results = _legacy_blocks(role, parts_of, directory)
            lines.extend(_events(role, blocks, results, timestamp))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opencode-transcript",
        description=__doc__,
        # The docstring's lists and usage block keep their line breaks.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
