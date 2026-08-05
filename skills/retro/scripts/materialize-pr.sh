#!/usr/bin/env bash
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
#       plain checkout. Fetches origin, creates ../<branch-dirname> worktree
#       off origin/<default-branch>, prints the worktree path.
#   materialize-pr.sh finish <worktree-dir> <title> <body-file> <file>...
#       Stages ONLY the named files (never -A), commits signed
#       (-S --signoff, message = title), pushes -u, opens the PR with
#       --body-file, prints the PR URL.
#
# Exit: 0 ok; 2 usage/error. Never force-pushes, never merges.
set -euo pipefail

die() { printf 'materialize-pr: %s\n' "$1" >&2; exit 2; }

cmd="${1:-}"; shift || true
case "$cmd" in
start)
    repo="${1:?repo-dir}"; branch="${2:?branch}"
    if [[ -d "$repo/.bare" ]]; then gitdir="$repo/.bare"; else gitdir="$repo"; fi
    git -C "$gitdir" fetch origin --quiet
    default=$(git -C "$gitdir" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
    [[ -n "$default" ]] || default=main
    wt="$repo/../$(basename "${branch//\//-}")"
    wt=$(python3 -c "import os,sys; print(os.path.abspath(sys.argv[1]))" "$wt")
    git -C "$gitdir" worktree add -b "$branch" "$wt" "origin/$default" >/dev/null
    printf '%s\n' "$wt"
    ;;
finish)
    wt="${1:?worktree-dir}"; title="${2:?title}"; body="${3:?body-file}"; shift 3
    [[ $# -ge 1 ]] || die "name at least one file to stage (never -A)"
    [[ -f "$body" ]] || die "body file not found: $body"
    branch=$(git -C "$wt" rev-parse --abbrev-ref HEAD)
    git -C "$wt" add -- "$@"
    git -C "$wt" commit -S --signoff -m "$title"
    git -C "$wt" push -u origin "$branch"
    gh pr create --title "$title" --body-file "$body" \
        --repo "$(git -C "$wt" remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"
    ;;
*)
    die "usage: materialize-pr.sh start <repo-dir> <branch> | finish <worktree-dir> <title> <body-file> <file>..."
    ;;
esac
