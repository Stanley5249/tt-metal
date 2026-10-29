#!/usr/bin/env bash
# Merge an upstream tag into an update branch for one track. fork-sync pushes
# and validates the branch, then fast-forwards the track to it. Locally, rerun
# after resolving conflicts and push the branch. Exit status 2 means a merge
# conflict; any other failure is a fetch, check, or setup error.
set -euo pipefail

usage="usage: fork-sync.sh <stable|nightly> [upstream tag]"
track=${1:?$usage}
new=$(bash .github/scripts/fork-select-tag.sh "$track" "${2:-}")
# Actions reads these outputs; a local run has no GITHUB_OUTPUT.
emit() {
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        printf '%s\n' "$@" >> "$GITHUB_OUTPUT"
    fi
}
candidate="chore/sync-$track-$new"
emit "tag=$new" "candidate=$candidate"
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
upstream_sha=$(git rev-parse "$new^{commit}")
git fetch -q --no-tags origin "$track:refs/remotes/origin/$track"
# Fork clones carry only fork release tags. Discover upstream bases first.
bash .github/scripts/fork-upstream-tags.sh "origin/$track"
metadata=$(bash .github/scripts/fork-version.sh "$track" "origin/$track")
old=$(printf '%s\n' "$metadata" | awk -F= '$1 == "base" {print $2}')
if ! git merge-base --is-ancestor "$old" "$upstream_sha"; then
    echo "$new is not a forward upgrade from $old" >&2
    exit 1
fi
if git merge-base --is-ancestor "$upstream_sha" "origin/$track"; then
    echo "$track already contains $new"
    emit changed=false
    exit 0
fi
# Resume a pushed update branch, which may hold a manual conflict resolution.
if git ls-remote --exit-code --heads origin "$candidate" > /dev/null; then
    git fetch -q --no-tags origin "$candidate:refs/remotes/origin/$candidate"
    start="origin/$candidate"
else
    status=$?
    if [ "$status" -ne 2 ]; then
        echo "could not inspect remote update branch" >&2
        exit "$status"
    fi
    start="origin/$track"
fi
if git show-ref --verify --quiet "refs/heads/$candidate"; then
    git switch -q "$candidate"
else
    git switch -q -c "$candidate" "$start"
fi
# A local branch may be ahead of its remote, which --ff-only accepts.
if [ "$start" = "origin/$candidate" ] && ! git merge -q --ff-only "$start"; then
    echo "$candidate diverged from its remote; reconcile it manually" >&2
    exit 1
fi
# Merge, and tell a conflict, which leaves the merge in progress, from errors.
merge() {
    if git merge --no-ff --no-stat -m "$1" "$2"; then
        return
    fi
    conflicts=$(git diff --name-only --diff-filter=U)
    if [ -z "$conflicts" ]; then
        echo "merging $2 failed without conflicts; see the error above" >&2
        exit 1
    fi
    echo "Resolve conflicts on $candidate, commit the merge, then rerun this command:" >&2
    printf '%s\n' "$conflicts" >&2
    exit 2
}
# The track moved after the branch was made, such as during validation. Merge
# it in, which keeps any manual resolution on the branch.
if ! git merge-base --is-ancestor "origin/$track" HEAD; then
    merge "Merge $track into $candidate" "origin/$track"
fi
if ! git merge-base --is-ancestor "$upstream_sha" HEAD; then
    merge "Merge upstream $new into $track" "$upstream_sha"
fi
# SFPI and ttsim always follow the selected upstream tag.
git diff --exit-code "$upstream_sha" HEAD -- tt_metal/sfpi-version tt_metal/ttsim-version
# just fetch-ttsim refuses a ttsim-release that does not build the pinned ttsim,
# so stop before validation spends a build on it.
read -r _ ttsim_release < tt_metal/ttsim-release
ttsim=$(tr -d '[:space:]' < tt_metal/ttsim-version)
if [[ "$ttsim_release" != "$ttsim"-* ]]; then
    echo "tt_metal/ttsim-release names $ttsim_release, not a build of ttsim $ttsim; release one in Stanley5249/ttsim, commit the new name on $candidate, and rerun" >&2
    exit 1
fi
git submodule sync --recursive
git submodule update --init --recursive
sha=$(git rev-parse HEAD)
emit changed=true "previous=$old" "sha=$sha"
printf 'Update branch: %s\nCommit: %s\nUpstream: %s -> %s (%s)\n' "$candidate" "$sha" "$old" "$new" "$upstream_sha"
