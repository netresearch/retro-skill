#!/usr/bin/env bash
# find-installed-skills.sh — discover installed Claude Code skills
#
# Scans known skill locations and emits a JSON array of
# {name, path, description, repo_url} objects. Used by retro-skill for
# Schicht-B classification when destination is skill-update or new-skill.
#
# Usage:
#     bash find-installed-skills.sh
#     bash find-installed-skills.sh --project /path/to/project

set -euo pipefail

# Hard dependency on jq: every value is JSON-escaped via `jq -Rs .`. Without jq
# the output would be malformed JSON which downstream consumers cannot handle.
if ! command -v jq >/dev/null 2>&1; then
  echo "[]"
  exit 0
fi

PROJECT_DIR=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --project)
      PROJECT_DIR="${2:-}"
      [ -n "$PROJECT_DIR" ] || { echo "find-installed-skills.sh: --project requires a path" >&2; exit 2; }
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--project <path>] [<path>]"
      exit 0
      ;;
    *)
      PROJECT_DIR="$1"
      shift
      ;;
  esac
done

if [ -n "$PROJECT_DIR" ] && [ ! -d "$PROJECT_DIR" ]; then
  echo "find-installed-skills.sh: project path does not exist: $PROJECT_DIR" >&2
  PROJECT_DIR=""
fi

CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"

SEARCH_PATHS=()
[ -n "$PROJECT_DIR" ] && [ -d "$PROJECT_DIR/.claude/skills" ] && SEARCH_PATHS+=("$PROJECT_DIR/.claude/skills")
[ -d "$CLAUDE_HOME/skills" ] && SEARCH_PATHS+=("$CLAUDE_HOME/skills")
# Plugin cache layout: <marketplace>/<plugin>/<version>/skills/
for d in "$CLAUDE_HOME"/plugins/cache/*/*/*/skills; do
  [ -d "$d" ] && SEARCH_PATHS+=("$d")
done
# Older / alternative cache layout: <marketplace>/<plugin>/skills/
for d in "$CLAUDE_HOME"/plugins/cache/*/*/skills; do
  [ -d "$d" ] && SEARCH_PATHS+=("$d")
done

if [ ${#SEARCH_PATHS[@]} -eq 0 ]; then
  echo "[]"
  exit 0
fi

extract_description() {
  local skill_md="$1"
  # Read description field from YAML frontmatter
  awk '
    /^---$/ { state++; next }
    state==1 && /^description:/ {
      sub(/^description:[[:space:]]*"?/, "")
      sub(/"?[[:space:]]*$/, "")
      print
      exit
    }
  ' "$skill_md"
}

find_plugin_root() {
  # Walk up from skill_root looking for .claude-plugin/, composer.json, or .git
  local dir="$1"
  while [ -n "$dir" ] && [ "$dir" != "/" ]; do
    if [ -d "$dir/.claude-plugin" ] || [ -f "$dir/composer.json" ] || [ -e "$dir/.git" ]; then
      echo "$dir"
      return
    fi
    dir=$(dirname "$dir")
  done
}

extract_repo_url() {
  local skill_root="$1"
  local plugin_root="$2"
  local resolved_root
  resolved_root=$(readlink -f "$skill_root" 2>/dev/null || echo "$skill_root")
  # Find real plugin root by walking up from resolved location
  local real_plugin_root
  real_plugin_root=$(find_plugin_root "$resolved_root")
  [ -z "$real_plugin_root" ] && real_plugin_root="$plugin_root"

  # 1. plugin.json
  if [ -f "$real_plugin_root/.claude-plugin/plugin.json" ]; then
    local url
    url=$(jq -r '.repository // empty' "$real_plugin_root/.claude-plugin/plugin.json" 2>/dev/null || true)
    [ -n "$url" ] && [ "$url" != "null" ] && echo "$url" && return
  fi
  # 2. composer.json
  if [ -f "$real_plugin_root/composer.json" ]; then
    local url
    url=$(jq -r '.support.source // .homepage // empty' "$real_plugin_root/composer.json" 2>/dev/null || true)
    [ -n "$url" ] && [ "$url" != "null" ] && echo "$url" && return
  fi
  # 3. git remote (resolved skill root)
  if [ -d "$resolved_root/.git" ] || [ -f "$resolved_root/.git" ]; then
    local url
    url=$(git -C "$resolved_root" config --get remote.origin.url 2>/dev/null || true)
    [ -n "$url" ] && echo "$url" && return
  fi
  # 4. git remote (real plugin root)
  if [ -d "$real_plugin_root/.git" ] || [ -f "$real_plugin_root/.git" ]; then
    local url
    url=$(git -C "$real_plugin_root" config --get remote.origin.url 2>/dev/null || true)
    [ -n "$url" ] && echo "$url" && return
  fi
  echo ""
}

first=true
printf '['

for base in "${SEARCH_PATHS[@]}"; do
  for skill_dir in "$base"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_dir="${skill_dir%/}"
    name=$(basename "$skill_dir")
    skill_md="$skill_dir/SKILL.md"
    [ -f "$skill_md" ] || continue

    # plugin_root is two levels up if base is .../plugins/cache/*/skills, otherwise skill_dir
    plugin_root="$skill_dir"
    case "$base" in
      */plugins/cache/*) plugin_root=$(dirname "$base") ;;
    esac

    description=$(extract_description "$skill_md")
    repo_url=$(extract_repo_url "$skill_dir" "$plugin_root")

    # Trim trailing newlines/whitespace
    name="${name%$'\n'}"
    description="${description%$'\n'}"
    repo_url="${repo_url%$'\n'}"

    $first || printf ','
    first=false
    printf '\n  {"name":%s,"path":%s,"description":%s,"repo_url":%s}' \
      "$(printf '%s' "$name" | jq -Rs .)" \
      "$(printf '%s' "$skill_dir" | jq -Rs .)" \
      "$(printf '%s' "$description" | jq -Rs .)" \
      "$(printf '%s' "$repo_url" | jq -Rs .)"
  done
done

printf '\n]\n'
