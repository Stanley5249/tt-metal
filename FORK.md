# Stanley5249/tt-metal

This file belongs to the fork only. It lives on `stable` and `nightly` and
never goes upstream.

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal)
builds tt-metal with Tracy for the ttsim simulator, in a pixi environment that
needs no sudo. Its releases ship a ttnn wheel and the Tracy tools.

## Branches

`stable` is the default development branch, based on an upstream release tag.
`nightly` tests the fork's patches against selected upstream nightly tags.
Release tags preserve exact versions; integration branches move forward without
rewriting published history. The fork has no `main`; see Workflows.

New `feat/*` and `fix/*` branches start from their target integration branch.
Merge normal development into `stable`, then cherry-pick relevant commits onto
a task branch for `nightly`. Do not merge the whole nightly branch into stable.
The existing branches below preserve the original upstream-facing patches;
porting them does not rebase or rewrite those branches.

| Branch                    | Change                                            | Category | Upstream     |
| ------------------------- | ------------------------------------------------- | -------- | ------------ |
| `feat/ttsim-host-tensors` | build tensors on the host under ttsim             | Feature  | not proposed |
| `feat/ttsim-profiler`     | device profiler on ttsim's clock                  | Feature  | not proposed |
| `fix/device-marker-order` | skip unpaired device markers instead of aborting  | Bug fix  | not proposed |
| `feat/sfpi-root-override` | `TT_METAL_SFPI_ROOT` for the kernel JIT           | Feature  | not proposed |
| `feat/wheel-models`       | ship tt_transformers' `models/` in the ttnn wheel | Feature  | not proposed |
| `feat/pixi`               | pixi workspace and conda clang toolchain          | Feature  | not proposed |
| `feat/justfile`           | build, ttsim, and release recipes                 | Feature  | not proposed |
| `fix/wheel-ttsim-version` | ship the ttsim version pin in the ttnn wheel      | Bug fix  | not proposed |
| `feat/wheel-sfpi`         | bundle the SFPI kernel compiler in the ttnn wheel | Feature  | not proposed |

`feat/wheel-models` serves vLLM on ttsim rather than Tracy, and
`feat/justfile` builds on `feat/pixi`.

## Syncing with upstream

Sync nightly on demand or weekly. Upgrade stable only to a selected upstream
release; cherry-pick individual upstream fixes when a full upgrade is not needed.

1. Run `.github/scripts/fork-sync.sh <stable|nightly> <tag>`. It creates a
   `chore/sync-*` candidate and merges the upstream tag without rewriting any
   integration or patch branch. It does not build locally or push anything.
2. Resolve conflicts, review dependencies, submodules, SFPI and ttsim pins,
   and remove fork code that upstream now provides. Push the candidate for
   fast CI checks, then review and merge it into its target branch.
3. Run the fork workflow by hand on that integration branch for the full build,
   clean-wheel simulator tests and Tracy capture checks. Do not draft a release
   until they pass; `release` drafts one after the same checks pass again.
4. Review the draft and publish it separately, only after approval. Nightly
   drafts are marked as prereleases.

When upstream includes a patch, stop carrying its implementation on each track
once that track reaches the upstream fix. The two tracks may drop it at different
times.

## Workflows

`.github/workflows/fork.yaml` is the fork's only workflow.

```
push to stable/nightly   checks ── disable-upstream

started by hand       checks ───────┐
                      version ──┬───┴── build ── smoke [wh, bh] ──┬── release
                                └── notes ────────────────────────┘
                                (notes and release only with `release`)
```

- `checks` runs `just ci` and lints the workflow and the `fork-*.sh` scripts.
- `disable-upstream` disables every other workflow; see below.
- `version` names the next `conda.N` on the upstream tag, counting drafts.
- `build` runs `just build`, `just wheel`, and `just tracy-tools`, with no
  write access, and saves its ccache even when it fails.
- `smoke` installs the wheel in the pixi `wheel` environment, which has no
  editable ttnn, runs one op on both simulator architectures, and verifies Tracy
  capture and device profiler artifacts using the shipped tools.
- `notes` runs git-cliff with `.github/cliff.toml`, and `release` drafts the
  release; it is the only job that writes to the repository.

Upstream's workflows stay in the tree, unchanged, and are disabled in the
repository's Actions settings; `disable-upstream` catches the ones a sync adds.
The integration branch is the default branch, so their
schedules would fire here and queue for Tenstorrent's self-hosted runners
until GitHub drops them. Other events start none of them: issues are off on
forks, the fork opens no pull requests, and most push triggers listen on
`main`, which the fork does not have. Do not recreate `main` or open pull
requests inside the fork. For the same reason, the fork has no Dependabot.

## Side effects

What the `just` recipes write and how long they take. The `justfile` and the
fork workflow stay the source of truth; this section explains them.

Times start without a build tree, on two machines. `local` is an Intel Core
Ultra 9 185H under WSL 2 with 26 GB given to WSL and `TT_BUILD_JOBS=10`.
`runner` is GitHub's `ubuntu-latest` with 4 vCPU, 16 GB, and the jobs that
the build job sets.

| Command                          | `local`                       | `runner`                                        |
| -------------------------------- | ----------------------------- | ----------------------------------------------- |
| `just build`, empty tree         | 32 min, with a warm CPM cache | 47 min, with empty caches                       |
| `just build` after a merge       | 3 min for the patched files   | not measured                                    |
| `just wheel`, `just tracy-tools` | not measured with SFPI        | 45 s                                            |
| `just trace` on a small op       | about 40 s, compiling kernels | not run                                         |
| a whole run, empty caches        | not run                       | 51 min, with a 2 min disk cleanup since dropped |
| a whole run, warm ccache         | not run                       | 10 min                                          |

Sizes are from `local`.

| Path or resource                         | Written by                       | Notes                                                                         |
| ---------------------------------------- | -------------------------------- | ----------------------------------------------------------------------------- |
| `.pixi/envs/`                            | `just install`, any recipe       | the pixi environment, 2.9 GB                                                  |
| `build_Release/`, `build` linking to it  | `just build`                     | 2.3 GB                                                                        |
| `runtime/`                               | `just build`                     | the SFPI kernel compiler, 0.4 GB                                              |
| `~/.cache/cpm/`                          | `just build`                     | CPM's source cache, 4.0 GB                                                    |
| `~/.cache/ccache/`                       | `just build`                     | 0.6 GB                                                                        |
| `sim/`                                   | `just fetch-ttsim`               | the ttsim library, its SOC descriptor, and a `.version` stamp; under 1 MB     |
| `generated/`, `~/.cache/tt-metal-cache/` | `just test`, `just trace`        | tt-metal's logs and JIT-compiled kernels, 2 GB together                       |
| `build/profiler/build_wasm/traces/`      | `just trace`                     | each capture's `.tracy`, small                                                |
| `dist/`, `build_wheel/`                  | `just wheel`, `just tracy-tools` | the release assets and the wheel's build files, 0.4 GB                        |
| `localhost:8080`, `:8081`                | `just trace`                     | tt-metal's WASM viewer server for this tree, until `pkill -f serve_wasm.py`   |
| GitHub Actions cache                     | the fork workflow                | the pixi environment, and ccache with CPM per build, restored by upstream tag |

## Compared with upstream wheels

Upstream publishes ttnn to PyPI from `.github/workflows/wheels.yaml`, which
builds with cibuildwheel in a manylinux image. A fork release differs in:

| Aspect                     | Upstream PyPI wheel                     | Fork release wheel                         |
| -------------------------- | --------------------------------------- | ------------------------------------------ |
| Tracy                      | off                                     | on                                         |
| Multihost MPI              | on, with MPI bundled                    | off                                        |
| SFPI kernel compiler       | installed separately                    | bundled                                    |
| tt_transformers' `models/` | not shipped; models run from a checkout | bundled                                    |
| Toolchain                  | the manylinux image's clang             | conda-forge clang 20                       |
| Platform tag               | `manylinux_2_34`, with auditwheel       | `linux_x86_64`, needing the pixi `runtime` |
| Version                    | the release tag, such as `0.79.0`       | the upstream tag plus `+conda.N`           |

## Releases

A release tag names its upstream base and a rebuild count: stable uses
`v0.79.0-conda.1`, while nightly uses `v0.80.0-dev20260928-conda.1`.
Wheels use the same count as a local version, such as `0.79.0+conda.1` or
`0.80.0.dev20260928+conda.1`. The wheel ships the
`models/` that tt_transformers imports and the SFPI kernel compiler.

[tt-vllm-tracer](https://github.com/Stanley5249/tt-vllm-tracer) installs and
runs a release; its `pyproject.toml` and `docs/env-vars.md` list what the wheel
needs.
