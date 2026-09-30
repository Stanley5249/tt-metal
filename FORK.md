# Stanley5249/tt-metal

This file belongs to the fork only. It lives on `docs/fork` and never goes
upstream.

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal)
builds tt-metal with Tracy for the ttsim simulator, in a pixi environment that
needs no sudo. Its releases ship a ttnn wheel and the Tracy tools.

## Branches

`main` mirrors upstream `main` and takes no commits. Every other branch starts
from an upstream nightly tag, and `tracy-ttsim`, the default branch, merges
them all.

Each change that could go upstream sits on its own branch, in one of the
upstream PR categories that `CONTRIBUTING.md` lists, and its commit message is
the draft PR description.

| Branch                    | Change                                            | Category | Upstream     |
| ------------------------- | ------------------------------------------------- | -------- | ------------ |
| `feat/ttsim-host-tensors` | build tensors on the host under ttsim             | Feature  | not proposed |
| `feat/ttsim-profiler`     | device profiler on ttsim's clock                  | Feature  | not proposed |
| `fix/device-marker-order` | skip unpaired device markers instead of aborting  | Bug fix  | not proposed |
| `feat/sfpi-root-override` | `TT_METAL_SFPI_ROOT` for the kernel JIT           | Feature  | not proposed |
| `feat/wheel-models`       | ship tt_transformers' `models/` in the ttnn wheel | Feature  | not proposed |
| `feat/pixi`               | pixi workspace and conda clang toolchain          | Feature  | not proposed |
| `feat/justfile`           | build, ttsim, and release recipes                 | Feature  | not proposed |
| `ci/fork`                 | the fork's own workflows                          | none     | fork only    |
| `docs/fork`               | this file                                         | none     | fork only    |

`feat/wheel-models` serves vLLM on ttsim rather than Tracy, and
`feat/justfile` builds on `feat/pixi`.

## Syncing with upstream

1. Rebase each branch onto the new upstream nightly tag.
2. Recreate `tracy-ttsim` from that tag and merge every branch into it.
3. Force-push the branches. Release tags keep earlier `tracy-ttsim` commits.

When upstream merges a change, delete its branch and drop its row here.

## Releases

A release tag names its upstream base and a rebuild count, such as
`v0.80.0-dev20260928-conda.1`, and its wheel carries the same count as a local
version, such as `ttnn-0.80.0.dev20260928+conda.1`.
