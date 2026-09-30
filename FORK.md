# Stanley5249/tt-metal

This file belongs to the fork only. It lives on `tracy-ttsim` and never goes
upstream.

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal)
builds tt-metal with Tracy for the ttsim simulator, in a pixi environment that
needs no sudo. Its releases ship a ttnn wheel and the Tracy tools.

## Branches

`tracy-ttsim`, the default branch, is an upstream nightly tag, then a merge of
every branch below, then the fork-only commits: this file, the `fork-*`
workflows, and `.github/cliff.toml` with its script. The fork has no `main`;
see Workflows.

Every other branch is a change that could go upstream. Each starts from the
same upstream tag, fits one of the PR categories that `CONTRIBUTING.md` lists,
and has a commit message that drafts the PR description.

| Branch                    | Change                                            | Category | Upstream     |
| ------------------------- | ------------------------------------------------- | -------- | ------------ |
| `feat/ttsim-host-tensors` | build tensors on the host under ttsim             | Feature  | not proposed |
| `feat/ttsim-profiler`     | device profiler on ttsim's clock                  | Feature  | not proposed |
| `fix/device-marker-order` | skip unpaired device markers instead of aborting  | Bug fix  | not proposed |
| `feat/sfpi-root-override` | `TT_METAL_SFPI_ROOT` for the kernel JIT           | Feature  | not proposed |
| `feat/wheel-models`       | ship tt_transformers' `models/` in the ttnn wheel | Feature  | not proposed |
| `feat/pixi`               | pixi workspace and conda clang toolchain          | Feature  | not proposed |
| `feat/justfile`           | build, ttsim, and release recipes                 | Feature  | not proposed |

`feat/wheel-models` serves vLLM on ttsim rather than Tracy, and
`feat/justfile` builds on `feat/pixi`.

## Syncing with upstream

Sync on demand, when a fix or a ttsim release needs a newer upstream tag.

1. Push the new upstream nightly tag to the fork; the release workflow reads
   it with `git describe`.
2. Rebase each branch onto that tag.
3. Recreate `tracy-ttsim` from that tag, merge every branch into it, then
   cherry-pick the fork-only commits: everything above the last merge on the
   old `tracy-ttsim`.
4. Force-push the branches. Release tags keep earlier `tracy-ttsim` commits.
5. Check the pinned actions in `.github/workflows/fork-*.yaml` against their
   latest releases.

When upstream merges a change, delete its branch and drop its row here.

## Workflows

`fork-checks` runs `just ci` on each push to `tracy-ttsim`. `fork-release`,
started by hand on `tracy-ttsim` with a label such as `conda.1`, builds on a
GitHub-hosted runner and drafts a release with the wheel, the Tracy tools, and
notes that git-cliff writes from `.github/cliff.toml`.

Upstream's workflows stay in the tree, unchanged, and do not fire here:
scheduled runs and issues are off on forks, the fork opens no pull requests,
and their push triggers listen on `main`, which the fork does not have. Do not
recreate `main` or open pull requests inside the fork. For the same reason,
the fork has no Dependabot.

## Releases

A release tag names its upstream base and a rebuild count, such as
`v0.80.0-dev20260928-conda.1`, and its wheel carries the same count as a local
version, such as `ttnn-0.80.0.dev20260928+conda.1`.
