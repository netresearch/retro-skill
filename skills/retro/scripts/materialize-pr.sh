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
#       `samples` (check-eval-samples.py). Then stages and commits
#       ONLY the named files (never -A; other staged changes stay out of the
#       commit), signed (-S --signoff, message = title), pushes -u, opens the PR for that branch (--head) with
#       --body-file as a draft (--draft), prints the PR URL.
#
# Exit: 0 ok; 2 unknown command, no file named, body file not found, body
# without the provenance line or an eval refused; 1 a missing positional
# argument; a failing git or gh command ends the script with that command's
# status. Never force-pushes, never merges.
set -euo pipefail

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
    # The pathspec limits the commit to the named files: anything else that
    # was already staged in the worktree stays out of it.
    git -C "$wt" commit -S --signoff -m "$title" -- "$@"
    git -C "$wt" push -u origin "$branch"
    # From the worktree, and with --head: gh otherwise takes the head branch
    # and its gh-merge-base (the PR's base) from the caller's checkout.
    repo_slug=$(git -C "$wt" remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
    body=$(cd "$(dirname "$body")" && pwd)/$(basename "$body")
    # A draft: leaving draft summons reviewers, and that is the user's call.
    (cd "$wt" && gh pr create --draft --title "$title" --body-file "$body" --head "$branch" --repo "$repo_slug")
    ;;
*)
    die "usage: materialize-pr.sh start <repo-dir> <branch> | finish <worktree-dir> <title> <body-file> <file>..."
    ;;
esac
