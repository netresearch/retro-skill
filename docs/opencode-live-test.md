# Testing the opencode adapter against a real opencode 2.x

`skills/retro/scripts/opencode-transcript.py` reads two opencode schemas. Its unit tests build both from opencode's source schema. This page describes how to check the adapter against sessions that a real opencode 2.x wrote, without touching the opencode data already on the machine.

## Why isolation is mandatory

opencode 2.x migrates its database on first start: it copies every 1.x session into `session_v2` / `session_message` and adds tables to the existing file. Its default database is the same file 1.x uses, `~/.local/share/opencode/opencode.db`. Started without isolation, a 2.x test run migrates the real 1.x database in place.

2.x also runs a shared background server by default. `run --standalone` starts a private one for that call instead.

## Install 2.x without touching the installed 1.x

2.x is not published as `opencode-ai` on npm (that package still carries 1.x), and its GitHub tags have no releases. It ships as `@opencode/cli-<platform>`; the current version is at `https://opencode.ai/update/api/latest/cli/npm`.

```bash
O=/path/to/scratch/oc2; mkdir -p "$O" && cd "$O"
V=2.0.15
curl -fsSL -o cli.tgz "https://registry.npmjs.org/@opencode/cli-linux-x64/-/cli-linux-x64-$V.tgz"
want=$(curl -s "https://registry.npmjs.org/@opencode%2fcli-linux-x64/$V" | python3 -c "import json,sys; print(json.load(sys.stdin)['dist']['integrity'])")
got="sha512-$(openssl dgst -sha512 -binary cli.tgz | base64 -w0)"
[ "$want" = "$got" ] && tar -xzf cli.tgz   # binary: package/bin/opencode
```

## Run it isolated

A wrapper, saved as `$O/oc2.sh` and made executable, that redirects every path opencode uses:

```bash
#!/usr/bin/env bash
set -euo pipefail
O=/path/to/scratch/oc2
export HOME="$O/home"
export XDG_DATA_HOME="$O/home/.local/share" XDG_CONFIG_HOME="$O/home/.config"
export XDG_CACHE_HOME="$O/home/.cache" XDG_STATE_HOME="$O/home/.local/state"
export OPENCODE_DB="$O/home/.local/share/opencode/opencode.db"
mkdir -p "$XDG_DATA_HOME/opencode" "$XDG_CONFIG_HOME/opencode"
exec "$O/package/bin/opencode" "$@"
```

Check the isolation before the first session: `"$O/oc2.sh" debug paths db` must print the path under `$O`.

## Point it at a model

Any OpenAI-compatible endpoint works, for example a local LM Studio or Ollama. `$O/home/.config/opencode/opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "providers": {
    "local": {
      "name": "Local",
      "env": ["LOCAL_API_KEY"],
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": { "baseURL": "http://<host>:<port>/v1" },
      "models": { "<model-id>": { "name": "<model-id>" } }
    }
  }
}
```

A local server accepts any value for `LOCAL_API_KEY`. From WSL, a server running on the Windows host is usually reached at the default gateway (`ip route show default`), not at `localhost`.

## Produce sessions and render them

`--auto` lets the model run its tools without asking. The wrapper isolates only opencode's own data, so a shell command the model runs has your user's access to files, processes and the network. Run the test in a disposable container or VM with no host files mounted.

`RETRO` is the root of this repository's checkout. The model works in `$O/proj`, so the scripts are called by absolute path:

```bash
RETRO=/path/to/retro-skill
cd "$O/proj"
LOCAL_API_KEY=x "$O/oc2.sh" run --standalone --auto --model local/<model-id> \
  "Use your tools. Read app.py, edit it, run it, read it again."
DB="$O/home/.local/share/opencode/opencode.db"
sqlite3 "file:$DB?mode=ro" "select id from session_v2"
python3 "$RETRO/skills/retro/scripts/opencode-transcript.py" --db "$DB" --session <id> > "$O/session.jsonl"
python3 "$RETRO/skills/retro/scripts/detect-mechanical.py" --transcript-file "$O/session.jsonl"
```

`run --session <id> --fork "…"` creates a fork: its copied rows carry ids ending in `_<seq>`, and `session_v2.fork_session_id` names the parent. A prompt that reads a missing file produces a failed tool call (`state.error`, `content: []`).

## Test the migration on a copy

Never point 2.x at the real 1.x database. Copy it consistently with SQLite's backup, the source opened read-only, into a second isolated home `$M` (a copy of the wrapper with `O` replaced by `M`), and let 2.x open the copy:

```bash
M=/path/to/scratch/oc2-migration; mkdir -p "$M/home/.local/share/opencode"
sqlite3 "file:$HOME/.local/share/opencode/opencode.db?mode=ro" ".backup $M/home/.local/share/opencode/opencode.db"
```

After any 2.x start against the copy, every migrated session is in both schemas under one id, so `render()` reads it from V2 while `_render_legacy()` still reads the old rows. Comparing the two per session shows what the migration changed. Compare tool calls by id, not by position, because the migration drops some calls (subagent `task` calls) and shifts later positions. Record the real database's hash, size and mtime before the test and compare them afterwards. The copy holds the user's session contents: delete it when done.
