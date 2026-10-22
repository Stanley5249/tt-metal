#!/usr/bin/env bash
# Prepare a candidate; GitHub Actions validates it before manual promotion.
# Usage: fork-sync.sh <stable|nightly> <upstream tag>
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
# A submodule at an older recorded commit is safe to align. Its own edits are not.
if [ -n "$(git status --porcelain --ignore-submodules=all)" ]; then
    echo "commit or stash your changes first" >&2
    exit 1
fi
# shellcheck disable=SC2016 # Each submodule's shell expands the status command.
git submodule foreach --quiet --recursive 'test -z "$(git status --porcelain --ignore-submodules=all)"' || {
    echo "commit or stash your submodule changes first" >&2
    exit 1
}
git fetch -q --no-tags upstream tag "$new"
git fetch -q --no-tags origin "stable:refs/remotes/origin/stable" "$track:refs/remotes/origin/$track"
# Fork clones carry only fork release tags. Discover upstream bases first.
bash .github/scripts/fork-upstream-tags.sh "origin/$track"
old=$(git describe --tags --abbrev=0 --match 'v[0-9]*' --exclude '*-conda.*' --exclude '*-rc*' "origin/$track")
if ! git merge-base --is-ancestor "$old" "$new"; then
    echo "$new is not a forward upgrade from $old" >&2
    exit 1
fi
if git merge-base --is-ancestor "$new" "origin/$track"; then
    echo "$track already contains $new"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "changed=false" >> "$GITHUB_OUTPUT"
    fi
    exit 0
fi
candidate="chore/sync-$track-$new"
# Reuse a complete candidate, but preserve any work that needs manual resolution.
if git ls-remote --exit-code --heads origin "$candidate" > /dev/null; then
    git fetch -q --no-tags origin "$candidate:refs/remotes/origin/$candidate"
    start="origin/$candidate"
else
    status=$?
    if [ "$status" -ne 2 ]; then
        echo "could not inspect remote candidate" >&2
        exit "$status"
    fi
    start="origin/$track"
fi
if git show-ref --verify --quiet "refs/heads/$candidate"; then
    git switch "$candidate"
else
    git switch -c "$candidate" "$start"
fi
if [ "$start" = "origin/$candidate" ]; then
    if git merge-base --is-ancestor HEAD "$start"; then
        git merge --ff-only "$start"
    elif ! git merge-base --is-ancestor "$start" HEAD; then
        echo "$candidate diverged from its remote; reconcile it manually" >&2
        exit 1
    fi
fi
if ! git merge-base --is-ancestor "origin/$track" HEAD; then
    echo "$candidate is behind $track; review or replace the candidate manually" >&2
    exit 1
fi
if [ "$track" = nightly ]; then
    bash <(git show origin/stable:.github/scripts/fork-infra.sh) copy origin/stable
fi
if ! git merge --no-ff --no-edit --no-stat "$new"; then
    echo "Resolve conflicts on $candidate, then rerun this command:" >&2
    git diff --name-only --diff-filter=U >&2
    exit 1
fi
# SFPI and ttsim always follow the selected upstream tag.
git diff --exit-code "$new" HEAD -- tt_metal/sfpi-version tt_metal/ttsim-version
git submodule sync --recursive
git submodule update --init --recursive
sha=$(git rev-parse HEAD)
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
        echo "changed=true"
        echo "candidate=$candidate"
        echo "sha=$sha"
    } >> "$GITHUB_OUTPUT"
fi
printf 'Candidate: %s\nCommit: %s\nUpstream: %s -> %s\n' "$candidate" "$sha" "$old" "$new"
echo "Validate this exact commit before fast-forwarding $track."
