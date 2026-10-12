#!/usr/bin/env bash
# Fetch tenstorrent's version tags on HEAD's history, so git describe can name
# the upstream base. Pushes to the fork carry no upstream tags, and fetching
# only tags on local commits downloads just the tag objects.
set -euo pipefail

upstream=https://github.com/tenstorrent/tt-metal.git
# Annotated tags list their commit on a peeled `^{}` line. Only releases and
# nightlies can be a base; a release candidate can share a release's commit.
mapfile -t refspecs < <(
    awk -F'\t' '
        NR == FNR { history[$1]; next }
        $2 ~ /^refs\/tags\/v[0-9]+\.[0-9]+\.[0-9]+(-dev[0-9]+)?\^\{\}$/ && $1 in history {
            sub(/\^\{\}$/, "", $2)
            print $2 ":" $2
        }
    ' <(git rev-list HEAD) <(git ls-remote --tags "$upstream" 'v*')
)
if [ "${#refspecs[@]}" -eq 0 ]; then
    echo "no upstream tag on HEAD's history" >&2
    exit 1
fi
git fetch -q --no-tags "$upstream" "${refspecs[@]}"
echo "fetched ${#refspecs[@]} upstream tags"
