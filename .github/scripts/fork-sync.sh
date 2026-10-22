#!/usr/bin/env bash
# Prepare a candidate; GitHub Actions validates it before manual promotion.
set -euo pipefail

usage="usage: fork-sync.sh <stable|nightly> <upstream tag>"
track=${1:?$usage}
new=$(bash .github/scripts/fork-select-tag.sh "$track" "${2:?$usage}")
# Actions reads these outputs; a local run has no GITHUB_OUTPUT.
emit() {
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        printf '%s\n' "$@" >> "$GITHUB_OUTPUT"
    fi
}
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
metadata=$(bash .github/scripts/fork-version.sh "$track" "origin/$track")
old=$(printf '%s\n' "$metadata" | awk -F= '$1 == "base" {print $2}')
if ! git merge-base --is-ancestor "$old" "$new"; then
    echo "$new is not a forward upgrade from $old" >&2
    exit 1
fi
if git merge-base --is-ancestor "$new" "origin/$track"; then
    echo "$track already contains $new"
    emit changed=false
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
# A local candidate may be ahead of its remote, which --ff-only accepts.
if [ "$start" = "origin/$candidate" ] && ! git merge -q --ff-only "$start"; then
    echo "$candidate diverged from its remote; reconcile it manually" >&2
    exit 1
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
emit changed=true "previous=$old" "candidate=$candidate" "sha=$sha"
printf 'Candidate: %s\nCommit: %s\nUpstream: %s -> %s\n' "$candidate" "$sha" "$old" "$new"
echo "Validate this exact commit before fast-forwarding $track."
