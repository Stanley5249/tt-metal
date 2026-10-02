#!/usr/bin/env bash
# Rebuild the fork on a new upstream nightly tag, locally; FORK.md has the
# steps around it. Pushing stays by hand, since it rewrites published history.
#
# Usage: fork-sync.sh <upstream tag>
#
# The branches are the ones that origin/tracy-ttsim merges, in the same order.
# A branch that another one builds on, such as feat/pixi under feat/justfile,
# moves with it through --update-refs.
set -euo pipefail

new=$1
git fetch -q upstream tag "$new"
git fetch -q --prune origin
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "commit or stash your changes first" >&2
    exit 1
fi

old=$(git describe --tags --abbrev=0 --match 'v[0-9]*-dev[0-9]*' --exclude 'v*-*-*' origin/tracy-ttsim)
# A branch deleted from origin, because upstream merged it, drops out.
mapfile -t branches < <(git log --reverse --merges --first-parent --format=%s "$old..origin/tracy-ttsim" |
    sed -n "s/^Merge branch '\(.*\)' into tracy-ttsim$/\1/p" |
    while read -r b; do git show-ref -q --verify "refs/remotes/origin/$b" && echo "$b"; done)
echo "$old -> $new: ${branches[*]}"

for b in "${branches[@]}"; do
    if [ "$(git rev-parse "$b")" != "$(git rev-parse "origin/$b")" ]; then
        echo "$b differs from origin/$b" >&2
        exit 1
    fi
done

for b in "${branches[@]}"; do
    for c in "${branches[@]}"; do
        if [ "$b" != "$c" ] && git merge-base --is-ancestor "$b" "$c"; then
            continue 2
        fi
    done
    git rebase -q --update-refs --onto "$new" "$old" "$b"
done

# Commits on tracy-ttsim that no branch has: this file, the workflow, FORK.md.
mapfile -t fork_only < <(git rev-list --reverse --no-merges origin/tracy-ttsim \
    --not "$old" "${branches[@]/#/origin/}")
git switch -q -C tracy-ttsim "$new"
for b in "${branches[@]}"; do
    git merge -q --no-ff --no-edit "$b"
done
git cherry-pick "${fork_only[@]}"

pixi run just ci
git range-diff -s "$old..origin/tracy-ttsim" "$new..tracy-ttsim" | grep -v ' = ' || true
echo "Review the range-diff above, then push as FORK.md says."
