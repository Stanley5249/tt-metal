#!/usr/bin/env bash
# Fetch tenstorrent's version tags on HEAD's history, so git describe can name
# the upstream base. Pushes to the fork carry no upstream tags, and fetching
# only tags on local commits downloads just the tag objects.
set -euo pipefail

upstream=$(git remote get-url upstream 2>/dev/null || printf '%s' https://github.com/tenstorrent/tt-metal.git)
history=${1:-HEAD}
# Annotated tags use a peeled `^{}` line; lightweight tags point to a commit.
# Only releases and nightlies can be a base; release candidates are excluded.
# Read the remote first, since a failure inside process substitution goes unnoticed.
remote_tags=$(git ls-remote --tags "$upstream" 'v*')
mapfile -t refspecs < <(
    awk -F'\t' '
        NR == FNR { history[$1]; next }
        $2 ~ /^refs\/tags\/v[0-9]+\.[0-9]+\.[0-9]+(-dev[0-9]+)?(\^\{\})?$/ && $1 in history {
            sub(/\^\{\}$/, "", $2)
            refs[$2]
        }
        END { for (ref in refs) print ref ":" ref }
    ' <(git rev-list "$history") - <<< "$remote_tags"
)
if [ "${#refspecs[@]}" -eq 0 ]; then
    echo "no upstream tag on HEAD's history" >&2
    exit 1
fi
git fetch -q --no-tags "$upstream" "${refspecs[@]}"
echo "fetched ${#refspecs[@]} upstream tags"
