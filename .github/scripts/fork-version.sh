#!/usr/bin/env bash
# Resolve the upstream base recorded in pixi.toml into Actions outputs and a wheel
# version. git describe cannot name the base: upstream's commit dates are out of
# order, so it can prefer an older tag over the one that was merged.
# Usage: fork-version.sh <stable|nightly|auto> [ref=HEAD] [label]
# auto infers the track from the upstream tag; a named track must match it.
set -euo pipefail

track=${1:?usage: fork-version.sh <stable|nightly|auto> [ref] [label]}
ref=${2:-HEAD}
label=${3:-}
case "$track" in
    stable) pattern='^v[0-9]+\.[0-9]+\.[0-9]+$' ;;
    nightly) pattern='^v[0-9]+\.[0-9]+\.[0-9]+-dev[0-9]+$' ;;
    auto) pattern='^v[0-9]+\.[0-9]+\.[0-9]+(-dev[0-9]+)?$' ;;
    *) echo "expected stable, nightly or auto" >&2; exit 1 ;;
esac
if [ -n "$label" ] && [[ ! "$label" =~ ^[a-zA-Z0-9]+([._-][a-zA-Z0-9]+)*$ ]]; then
    echo "expected an alphanumeric local version label with dot, underscore or hyphen separators" >&2
    exit 1
fi
commit=$(git rev-parse --verify --end-of-options "$ref^{commit}")
recorded=$(git show "$commit:pixi.toml" | sed -n '0,/^version = /s/^version = "\(.*\)"$/\1/p')
if [ -z "$recorded" ]; then
    echo "$ref records no upstream version in pixi.toml" >&2
    exit 1
fi
base=v${recorded/.dev/-dev}
if [[ ! "$base" =~ $pattern ]]; then
    echo "$track cannot build on upstream $base" >&2
    exit 1
fi
# Fork clones carry only fork release tags.
if ! git rev-parse -q --verify "refs/tags/$base" > /dev/null; then
    upstream=$(git remote get-url upstream 2>/dev/null || printf '%s' https://github.com/tenstorrent/tt-metal.git)
    git fetch -q --no-tags "$upstream" tag "$base"
fi
if ! git merge-base --is-ancestor "$base" "$commit"; then
    echo "pixi.toml names $base, which $ref does not contain" >&2
    exit 1
fi
track=stable
if [[ "$base" == *-dev* ]]; then
    track=nightly
fi
version=${base#v}
version=${version/-dev/.dev}
if [ -n "$label" ]; then
    version="$version+$label"
fi
printf 'base=%s\nbase-commit=%s\ntrack=%s\nversion=%s\n' "$base" "$(git rev-parse "$base^{commit}")" "$track" "$version"
