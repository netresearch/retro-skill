#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# materialize-pr.sh — the repeatable halves of a promote materialization.
#
# A destination-shaped promote batch repeats the same sequence per proposal:
# fresh worktree off origin/main, (agent edits), signed commit, push, PR.
# Hand-typing it ~30x per campaign is where mistakes creep in (stale base,
# missed -S/--signoff, body heredoc quoting). This wraps the mechanical halves;
# the edits between `start` and `finish` stay with the agent.
#
# Usage:
#   materialize-pr.sh start  <repo-dir> <branch>
#       repo-dir: the project dir holding .bare (bare-worktree layout) or a
#       plain checkout. Fetches origin, creates a worktree named after the
#       branch (slashes become dashes) off origin/<default-branch> - inside
#       repo-dir for the bare layout, beside it for a plain checkout - and
#       prints the worktree path. The default branch falls back to main when
#       origin/HEAD is not set.
#   materialize-pr.sh finish <worktree-dir> <title> <body-file> <file>...
#       Refuses first when the first non-empty line under `## Came from` is
#       not the provenance line of the PR body template (patch-workflow.md) -
#       the line elsewhere, or an issue link to the repo, does not count - or
#       when a named evals.json adds or tightens an eval that carries no
#       `samples` (check-eval-samples.py). Then stages ONLY the named files
#       (never -A). When the worktree has a .pre-commit-config.yaml, runs the
#       target repository's pre-commit hooks on those files - by itself
#       only for a netresearch/* origin, elsewhere with MATERIALIZE_PR_HOOKS=1
#       (MATERIALIZE_PR_HOOKS=0 turns it off) - (pre-commit, or
#       `uv tool run pre-commit` when it is not installed) and keeps what
#       the fixer hooks changed; a hook that still fails does not stop the
#       PR, its output is appended to the PR body under "## Pre-commit
#       hooks". Then commits ONLY the named files (other staged changes stay
#       out of the commit), signed (-S --signoff, message = title), pushes
#       -u, opens the PR for that branch (--head) with --body-file as a
#       draft (--draft), prints the PR URL.
#
# Exit: 0 ok; 2 unknown command, no file named, body file not found, body
# without the provenance line or an eval refused; 1 a missing positional
# argument; a failing git or gh command ends the script with that command's
# status. Never force-pushes, never merges.
set -euo pipefail

# A git hook exports these; they outrank `git -C`.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY

die() { printf 'materialize-pr: %s\n' "$1" >&2; exit 2; }

cmd="${1:-}"; shift || true
case "$cmd" in
start)
    repo="${1:?repo-dir}"; branch="${2:?branch}"
    if [[ -d "$repo/.bare" ]]; then gitdir="$repo/.bare"; else gitdir="$repo"; fi
    git -C "$gitdir" fetch origin --quiet
    # `|| true`: without origin/HEAD symbolic-ref exits non-zero, and under
    # `set -e` that would abort here before the main fallback below.
    default=$(git -C "$gitdir" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)
    default=${default#origin/}
    [[ -n "$default" ]] || default=main
    name=$(basename "${branch//\//-}")
    # Bare layout: worktrees live inside the project dir, next to .bare.
    if [[ -d "$repo/.bare" ]]; then wt="$repo/$name"; else wt="$repo/../$name"; fi
    wt=$(uv run --no-project --python '>=3.11' python -c "import os,sys; print(os.path.abspath(sys.argv[1]))" "$wt")
    git -C "$gitdir" worktree add -b "$branch" "$wt" "origin/$default" >/dev/null
    printf '%s\n' "$wt"
    ;;
finish)
    wt="${1:?worktree-dir}"; title="${2:?title}"; body="${3:?body-file}"; shift 3
    [[ $# -ge 1 ]] || die "name at least one file to stage (never -A)"
    [[ -f "$body" ]] || die "body file not found: $body"
    # A maintainer of the target repo cannot tell what `/retro` is; the PR
    # has to name the tool that opened it. Only the first non-empty line under
    # `## Came from` counts: the prefix elsewhere (a quoted example) does not.
    # CR is stripped first: awk counts a lone `\r` as a field, so a body
    # written with CRLF line ends would read its blank line as the first one.
    provenance=$(awk '{sub(/\r$/, "")} /^## Came from[[:space:]]*$/ {f = 1; next} f && NF {print; exit}' "$body")
    [[ "$provenance" == 'Opened by a [netresearch/retro-skill](https://github.com/netresearch/retro-skill)'* ]] \
        || die "body file lacks the provenance line naming netresearch/retro-skill as the first line under '## Came from' (patch-workflow.md, PR body template)"
    branch=$(git -C "$wt" rev-parse --abbrev-ref HEAD)
    # An eval retro adds or tightens must carry samples, or the fleet's eval
    # gate has nothing to grade it against (retro-skill#92). Runs before any
    # git write, so a refusal leaves the worktree untouched.
    uv run "$(dirname "$0")/check-eval-samples.py" --repo "$wt" -- "$@" \
        || die "eval(s) added or tightened without samples - see above"
    git -C "$wt" add -- "$@"
    # The target repository's own hooks, so a contributor sees a lint failure
    # in the PR body instead of first in CI. Fixer hooks (ruff --fix,
    # ruff-format, whitespace) rewrite files on the first run; the second run
    # reports what they could not fix. A failure never stops the PR: the
    # retro run is a contribution, and a barrier here would lose it.
    # pre-commit fetches and runs the code the config names, so it runs by
    # itself only for a target of our own organisation; for any other
    # target MATERIALIZE_PR_HOOKS=1 is the user's explicit opt-in.
    # owner/repo from the last two path segments, so scp-style, ssh:// and
    # https URLs and SSH host aliases all give the same slug.
    repo_slug=$(git -C "$wt" remote get-url origin | sed -E 's#/+$##; s#\.git$##; s#^.*[:/]([^/:]+/[^/:]+)$#\1#')
    run_hooks=${MATERIALIZE_PR_HOOKS:-}
    if [[ -z "$run_hooks" ]]; then
        if [[ "$repo_slug" == netresearch/* ]]; then run_hooks=1; else run_hooks=0; fi
    fi
    if [[ -f "$wt/.pre-commit-config.yaml" && "$run_hooks" != 1 ]]; then
        printf 'materialize-pr: pre-commit hooks not run for %s; set MATERIALIZE_PR_HOOKS=1 to run them\n' "$repo_slug" >&2
    fi
    if [[ -f "$wt/.pre-commit-config.yaml" && "$run_hooks" == 1 ]]; then
        if command -v pre-commit >/dev/null 2>&1; then
            precommit=(pre-commit)
        else
            precommit=(uv tool run pre-commit)
        fi
        if ! (cd "$wt" && "${precommit[@]}" run --files "$@") >/dev/null 2>&1 \
            && ! hook_output=$(cd "$wt" && "${precommit[@]}" run --files "$@" 2>&1); then
            printf 'materialize-pr: pre-commit hooks still fail; their output goes into the PR body\n' >&2
            # In the worktree's git dir: never committed, removed with the worktree.
            report="$(git -C "$wt" rev-parse --absolute-git-dir)/retro-pr-body.md"
            {
                cat "$body"
                printf '\n## Pre-commit hooks\n\n'
                # shellcheck disable=SC2016 # literal backticks: Markdown code span
                printf '`pre-commit run --files` still fails after the fixer hooks ran; CI is likely to fail the same way. Last 150 lines of its output:\n\n'
                printf '````text\n'
                printf '%s\n' "$hook_output" | tail -n 150
                printf '````\n'
            } > "$report"
            body="$report"
        fi
    fi
    # The pathspec limits the commit to the named files: anything else that
    # was already staged in the worktree stays out of it.
    git -C "$wt" commit -S --signoff -m "$title" -- "$@"
    git -C "$wt" push -u origin "$branch"
    # From the worktree, and with --head: gh otherwise takes the head branch
    # and its gh-merge-base (the PR's base) from the caller's checkout.
    body=$(cd "$(dirname "$body")" && pwd)/$(basename "$body")
    # A draft: leaving draft summons reviewers, and that is the user's call.
    (cd "$wt" && gh pr create --draft --title "$title" --body-file "$body" --head "$branch" --repo "$repo_slug")
    ;;
*)
    die "usage: materialize-pr.sh start <repo-dir> <branch> | finish <worktree-dir> <title> <body-file> <file>..."
    ;;
esac
