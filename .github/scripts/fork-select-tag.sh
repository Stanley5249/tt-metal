#!/usr/bin/env bash
# Print a track's upstream tag: the requested one, or the latest published.
# fork-sync.sh and fork-update validate tags here; fork-sync.sh checks ancestry.
# Usage: fork-select-tag.sh <stable|nightly> [tag]
set -euo pipefail

track=${1:?usage: fork-select-tag.sh <stable|nightly> [tag]}
tag=${2:-}
case "$track" in
    stable) pattern='^v[0-9]+\.[0-9]+\.[0-9]+$' ;;
    nightly) pattern='^v[0-9]+\.[0-9]+\.[0-9]+-dev[0-9]+$' ;;
    *) echo "expected stable or nightly" >&2; exit 1 ;;
esac
if [ -z "$tag" ] && [ "$track" = stable ]; then
    tag=$(gh api repos/tenstorrent/tt-metal/releases/latest --jq .tag_name)
elif [ -z "$tag" ]; then
    # Nightlies are daily; the most recent 100 releases cover this window.
    tag=$(gh api 'repos/tenstorrent/tt-metal/releases?per_page=100' \
        --jq '.[] | select(.draft == false) | .tag_name' |
        { grep -E "$pattern" || true; } | sort -V | tail -n 1)
fi
[[ "$tag" =~ $pattern ]] || { echo "${tag:-no tag} is not an upstream $track tag" >&2; exit 1; }
printf '%s\n' "$tag"
