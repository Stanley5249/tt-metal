#!/usr/bin/env bash
# Select a published upstream tag; fork-sync.sh validates the tag and ancestry.
set -euo pipefail

case "${1:?usage: fork-select-tag.sh <stable|nightly>}" in
    stable)
        tag=$(gh api repos/tenstorrent/tt-metal/releases/latest --jq .tag_name)
        pattern='^v[0-9]+\.[0-9]+\.[0-9]+$'
        ;;
    nightly)
        # Nightlies are daily; the most recent 100 releases cover this window.
        tag=$(gh api 'repos/tenstorrent/tt-metal/releases?per_page=100' \
            --jq '.[] | select(.draft == false) | .tag_name' |
            awk '/^v[0-9]+\.[0-9]+\.[0-9]+-dev[0-9]+$/' | sort -V | tail -n 1)
        pattern='^v[0-9]+\.[0-9]+\.[0-9]+-dev[0-9]+$'
        ;;
    *) echo "expected stable or nightly" >&2; exit 1 ;;
esac
[[ "$tag" =~ $pattern ]] || { echo "no published upstream tag for this track" >&2; exit 1; }
printf '%s\n' "$tag"
