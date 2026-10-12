# Stanley5249/tt-metal

This file belongs to the fork only. It lives on `stable` and `nightly` and
never goes upstream.

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal)
builds tt-metal with Tracy for the ttsim simulator, in a pixi environment that
needs no sudo. Its releases ship a ttnn wheel and the Tracy tools.

## Branches

`stable` is the default branch, based on an upstream release tag. `nightly`
carries the same fork on a selected upstream nightly tag. Upstream releases
come from their own line, so `v0.79.0` is not an ancestor of later nightlies,
and neither branch merges into the other. Release tags preserve exact
versions; both branches move forward without rewriting published history. The
fork has no `main`; see Workflows.

```text
upstream releases -- v0.79.0 ---------------------------- v0.80.0
                        \                                    \
stable                   M -- infra change -- source patch -- M
                                   |                |
                              copy |                | cherry-pick
                                   v                v
nightly            M ------- infra snapshot -- source patch ----- M
                  /                                              /
upstream main -- v0.80.0-dev20261002 ----------------- v0.81.0-dev20261011
```

All development starts from `stable` in a `feat/*`, `fix/*`, or `ci/*` branch
and merges there first. Nightly takes it in one of two ways:

- Fork infrastructure, the paths that `.github/fork-infra` lists, has no
  upstream counterpart and stays identical on both branches. Run
  `.github/scripts/fork-infra.sh copy` on a task branch from nightly to take
  stable's copy as one commit. `fork-checks` fails on nightly when the two
  differ.
- Source patches change upstream files, so cherry-pick each onto a task branch
  from nightly, and adapt it there when nightly's upstream has moved.

The source patches, none of them proposed upstream:

| Patch                                             | Upstream files                                                           |
| ------------------------------------------------- | ------------------------------------------------------------------------ |
| build tensors on the host under ttsim             | `ttnn/core/tensor/py_to_tt_tensor.cpp`                                   |
| device profiler on ttsim's clock                  | `tt_metal/impl/profiler/`, `tt_metal/tools/profiler/kernel_profiler.hpp` |
| skip unpaired device markers instead of aborting  | `tt_metal/impl/profiler/profiler.cpp`                                    |
| `TT_METAL_SFPI_ROOT` for the kernel JIT           | `tt_metal/jit_build/build.cpp`                                           |
| ship tt_transformers' `models/` in the ttnn wheel | `setup.py`, `models/tt_transformers/tt/model_config.py`                  |
| ship the ttsim version pin in the ttnn wheel      | `setup.py`                                                               |
| bundle the SFPI kernel compiler in the ttnn wheel | `setup.py`, `tt_metal/sfpi-licenses/`                                    |
| build in a pixi environment                       | `.gitattributes`, `.gitignore`                                           |

The `models/` patch serves vLLM on ttsim rather than Tracy. Older patch
branches, such as `feat/ttsim-profiler`, are frozen records of the first
versions and do not follow later changes.

## Syncing with upstream

Sync nightly on demand or weekly. Upgrade stable only to a selected upstream
release; cherry-pick individual upstream fixes when a full upgrade is not needed.

1. Run `.github/scripts/fork-sync.sh <stable|nightly> <tag>`. It creates a
   `chore/sync-*` candidate and merges the upstream tag without rewriting any
   integration or patch branch. A nightly candidate first takes stable's fork
   infrastructure. The script does not build locally or push anything.
2. Resolve conflicts, review dependencies, submodules, SFPI and ttsim pins,
   and remove fork code that upstream now provides. Push the candidate for
   `fork-checks`, review it, and fast-forward its target branch with
   `git push origin chore/sync-<track>-<tag>:<track>`. A pull request would
   add a second merge commit and could start upstream's new workflows; see
   Workflows. The upstream tag stays on tenstorrent, and the workflows fetch
   it from there.
3. Run `fork-release` by hand on that integration branch for the full build,
   clean-wheel simulator tests and Tracy capture checks. Do not draft a release
   until they pass; `release` drafts one after the same checks pass again.
4. Review the draft and publish it separately, only after approval. Nightly
   drafts are marked as prereleases.

When upstream includes a patch, stop carrying its implementation on each track
once that track reaches the upstream fix. The two tracks may drop it at different
times.

## Workflows

Each fork workflow serves one purpose, and their files match
`.github/workflows/fork-*.yaml`.

```text
fork-checks    push              checks -- disable-upstream (stable, nightly)

fork-release   started by hand   checks ---------+
                                 version --+-----+-- build -- smoke [wh, bh] --+-- release
                                           +-- notes --------------------------+
                                 (notes and release only with `release`)

fork-notify    release published, or started by hand with a tag
                                 notify-tracer
```

- `checks` runs `just ci`, which also lints the fork workflows and the
  `fork-*.sh` scripts, and on nightly compares the fork infrastructure with
  stable's. `fork-release` runs it again, because the push may have run no
  checks.
- `disable-upstream` disables every workflow outside the fork's; see below.
- `version` names the next `conda.N` on the upstream tag, counting drafts. It
  and `build` fetch upstream's tags on the branch's history from tenstorrent,
  because pushes to the fork carry none.
- `build` runs `just build`, `just wheel`, and `just tracy-tools`, with no
  write access, and saves its ccache even when it fails.
- `smoke` installs the wheel in the pixi `wheel` environment, which has no
  editable ttnn, runs one op on both simulator architectures, and verifies Tracy
  capture and device profiler artifacts using the shipped tools.
- `notes` runs git-cliff with `.github/cliff.toml`, and `release` drafts the
  release; it is the only job that writes to this repository.
- `notify-tracer` sends a published release tag to `tt-vllm-tracer`, which tests
  the dependency update and opens a PR to the matching stable or nightly track.
  Drafts never notify tracer. `TRACER_DISPATCH_TOKEN` is an Actions secret scoped
  to tracer's Contents write permission, and only `fork-notify` reads it. Start
  `fork-notify` by hand to retry a notification without rebuilding or
  publishing anything.

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
fork workflows stay the source of truth; this section explains them.

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
| GitHub Actions cache                     | the fork workflows               | the pixi environment, and ccache with CPM per build, restored by upstream tag |

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
