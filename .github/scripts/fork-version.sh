#!/usr/bin/env bash
# Resolve already-fetched upstream tags into Actions outputs and a wheel version.
# Usage: fork-version.sh <stable|nightly|auto> [ref=HEAD] [label]
# auto lets local wheel packaging infer the track from the upstream tag.
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
base=$(git describe --tags --abbrev=0 --match 'v[0-9]*' --exclude '*-conda.*' --exclude '*-rc*' "$commit")
if [[ ! "$base" =~ $pattern ]]; then
    echo "$track cannot build on upstream $base" >&2
    exit 1
fi
version=${base#v}
version=${version/-dev/.dev}
if [ -n "$label" ]; then
    version="$version+$label"
fi
printf 'base=%s\nbase-commit=%s\nversion=%s\n' "$base" "$(git rev-parse "$base^{commit}")" "$version"
