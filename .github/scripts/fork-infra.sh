#!/usr/bin/env bash
# Keep nightly's fork infrastructure, which .github/fork-infra lists, equal to
# stable's. check fails when HEAD differs from the ref; copy brings the ref's
# files to HEAD as one commit.
# Usage: fork-infra.sh <check|copy> [ref], where ref defaults to origin/stable.
set -euo pipefail

usage="usage: fork-infra.sh <check|copy> [ref]"
mode=${1:?$usage}
ref=${2:-origin/stable}
# The ref's list wins, so a path that stable adds reaches nightly too.
# Read the list first, since a failure inside process substitution goes unnoticed.
list=$(git show "$ref:.github/fork-infra")
mapfile -t paths < <(sed -e 's/[[:space:]]*#.*//' -e '/^$/d' <<< "$list")

case "$mode" in
    check)
        if ! git diff --quiet "$ref" HEAD -- "${paths[@]}"; then
            git diff --stat "$ref" HEAD -- "${paths[@]}" >&2
            echo "fork infrastructure differs from $ref; run fork-infra.sh copy" >&2
            exit 1
        fi
        ;;
    copy)
        if [ -n "$(git status --porcelain -- "${paths[@]}")" ]; then
            echo "commit or stash your changes to fork infrastructure first" >&2
            exit 1
        fi
        # restore also deletes files that the ref no longer has.
        git restore --source="$ref" --staged --worktree -- "${paths[@]}"
        if git diff --cached --quiet -- "${paths[@]}"; then
            echo "fork infrastructure already matches $ref"
        else
            git commit -q -m "chore: sync fork infra from stable" -- "${paths[@]}"
            echo "committed fork infrastructure from $ref"
        fi
        ;;
    *)
        echo "$usage" >&2
        exit 1
        ;;
esac
