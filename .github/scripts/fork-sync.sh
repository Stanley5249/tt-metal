#!/usr/bin/env bash
# Prepare an upstream upgrade without rewriting integration or patch branches.
# Usage: fork-sync.sh <stable|nightly> <upstream tag>
# Resolve conflicts and run CI before merging the candidate into its target.
set -euo pipefail

track=${1:?usage: fork-sync.sh <stable|nightly> <upstream tag>}
new=${2:?usage: fork-sync.sh <stable|nightly> <upstream tag>}
case "$track" in
    stable) pattern='^v[0-9]+\.[0-9]+\.[0-9]+$' ;;
    nightly) pattern='^v[0-9]+\.[0-9]+\.[0-9]+-dev[0-9]+$' ;;
    *) echo "expected stable or nightly" >&2; exit 1 ;;
esac
if [[ ! "$new" =~ $pattern ]]; then
    echo "$new is not an upstream $track tag" >&2
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "commit or stash your changes first" >&2
    exit 1
fi
git fetch -q upstream tag "$new"
git fetch -q origin "$track"
old=$(git describe --tags --abbrev=0 --match 'v[0-9]*' --exclude '*-conda.*' "origin/$track")
if ! git merge-base --is-ancestor "$old" "$new"; then
    echo "$new is not a forward upgrade from $old" >&2
    exit 1
fi
candidate="chore/sync-$track-$new"
git switch -c "$candidate" "origin/$track"
git merge --no-ff --no-edit "$new"
echo "Review $candidate, resolve compatibility issues, then merge into $track."
echo "Run the fork workflow on $track before drafting a release."
