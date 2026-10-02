# Stanley5249/tt-metal

This file belongs to the fork only. It lives on `tracy-ttsim` and never goes
upstream.

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal)
builds tt-metal with Tracy for the ttsim simulator, in a pixi environment that
needs no sudo. Its releases ship a ttnn wheel and the Tracy tools.

## Branches

`tracy-ttsim`, the default branch, is an upstream nightly tag, then a merge of
every branch below, then the fork-only commits: this file, `.github/workflows/fork.yaml`,
`.github/scripts/fork-*.sh`, and `.github/cliff.toml`. The fork has no `main`; see Workflows.

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

1. Run `.github/scripts/fork-sync.sh <tag>` with the new upstream nightly tag.
   It rebases every branch that `tracy-ttsim` merges, recreates `tracy-ttsim`
   from the tag with the same merges and the fork-only commits, runs
   `just ci`, and prints a range-diff against `origin/tracy-ttsim`.
2. Push the tag, then the branches with `--force-with-lease`. This rewrites
   their published history, but release tags keep earlier `tracy-ttsim`
   commits. The workflow disables any upstream workflow that the tag adds.
3. Start the workflow by hand to build and smoke-test the result, and with
   `release` to draft a release.
4. Check the pinned actions in `.github/workflows/fork.yaml` against their
   latest releases.

To add a branch, merge it into `tracy-ttsim`, which names it for the next
sync. When upstream merges a change, delete its branch on `origin` and drop
its row here; the next sync leaves it out.

## Workflows

`.github/workflows/fork.yaml` is the fork's only workflow.

```
push to tracy-ttsim   checks ── disable-upstream

started by hand       checks ── version ──┬── build ── smoke [wh, bh] ──┬── release
                                          └── notes ────────────────────┘
                                          (notes and release only with `release`)
```

- `checks` runs `just ci` and lints the workflow and the `fork-*.sh` scripts.
- `disable-upstream` disables every other workflow; see below.
- `version` names the next `conda.N` on the upstream tag, counting drafts.
- `build` runs `just build`, `just wheel`, and `just tracy-tools`, with no
  write access, and saves its ccache even when it fails.
- `smoke` installs the wheel outside the build tree, as tt-vllm-tracer does,
  and runs one op on ttsim with `.github/scripts/fork-smoke.sh`.
- `notes` runs git-cliff with `.github/cliff.toml`, and `release` drafts the
  release; it is the only job that writes to the repository.

Upstream's workflows stay in the tree, unchanged, and are disabled in the
repository's Actions settings; `disable-upstream` catches the ones a sync adds. `tracy-ttsim` is the default branch, so their
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

| Command                          | `local`                       | `runner`                       |
| -------------------------------- | ----------------------------- | ------------------------------ |
| `just build`, empty tree         | 32 min, with a warm CPM cache | 47 min, with empty caches      |
| `just build` after a merge       | 3 min for the patched files   | not measured                   |
| `just wheel`, `just tracy-tools` | 20 s                          | 25 s                           |
| `just trace` on a small op       | about 40 s, compiling kernels | not run                        |
| a whole release run              | not run                       | 51 min, 2 of them freeing disk |

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

## Releases

A release tag names its upstream base and a rebuild count, such as
`v0.80.0-dev20260928-conda.1`, and its wheel carries the same count as a local
version, such as `ttnn-0.80.0.dev20260928+conda.1`. The wheel ships the
`models/` that tt_transformers imports.

[tt-vllm-tracer](https://github.com/Stanley5249/tt-vllm-tracer) installs and
runs a release; its `pyproject.toml` and `docs/env-vars.md` list what the wheel
needs.
