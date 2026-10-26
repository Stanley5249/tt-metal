# Stanley5249/tt-metal

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal) builds tt-metal with Tracy for ttsim in a sudo-free pixi environment. Releases ship a ttnn wheel and Tracy tools. This file stays on the fork's two tracks.

## Branches

`stable` is the default branch, based on an upstream release tag. `nightly` uses a selected nightly tag. Their upstream histories can diverge, so keep the tracks independent and preserve published history. The fork has no `main`.

Merge upstream tags with a merge commit, then fast-forward the integration branch to the exact validated candidate. Keep fork-owned changes focused, preferably one commit per change, and fix published changes with follow-ups.

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

Develop on a `feat/*`, `fix/*`, `refactor/*`, or `ci/*` branch from stable and integrate there first. Propagate changes to nightly in two ways:

- Infrastructure paths in `.github/fork-infra` stay identical on both tracks. On a task branch from nightly, run `.github/scripts/fork-infra.sh copy` to take stable's snapshot. Nightly's checks enforce equality with stable.
- Cherry-pick source patches individually and adapt them to nightly's upstream.

The fork's source patches, all maintained here:

| Patch                                             | Upstream files                                               |
| ------------------------------------------------- | ------------------------------------------------------------ |
| build tensors on the host under ttsim             | `ttnn/core/tensor/py_to_tt_tensor.cpp`                       |
| device profiler on ttsim's clock                  | `tt_metal/impl/profiler/`, `tt_metal/**/kernel_profiler.hpp` |
| skip unpaired device markers instead of aborting  | `tt_metal/impl/profiler/profiler.cpp`                        |
| `TT_METAL_SFPI_ROOT` for the kernel JIT           | `tt_metal/jit_build/build.cpp`                               |
| ship tt_transformers' `models/` for vLLM on ttsim | `setup.py`, `models/tt_transformers/tt/model_config.py`      |
| ship the ttsim version pin                        | `setup.py`                                                   |
| bundle the SFPI compiler and licenses             | `setup.py`, `tt_metal/sfpi-licenses/`                        |
| build in pixi                                     | `.gitattributes`, `.gitignore`                               |

## Syncing with upstream

`fork-sync` prepares and fully validates candidates on a schedule or by hand. Stable selects a published release; nightly selects a published nightly tag. SFPI and ttsim follow that tag's pins. Runs with no upstream update skip building and compiler cache access.

When upstream changes files in `.github/workflows/`, GitHub's built-in `GITHUB_TOKEN` cannot push the candidate. Use the manual preparation in step 2 below, then push with your own GitHub identity that can write workflow files (`git push origin HEAD` from the candidate branch). No extra repository secret is needed. The tracer's `TRACER_DISPATCH_TOKEN` is unrelated.

Rerun `fork-sync` with the same track and exact upstream tag after the push. It reuses the remote candidate, skips the already completed push, and runs full validation. If preparation changes the candidate again, push that new commit manually before retrying. Keep upstream workflows disabled as described below, since a push with your own identity can trigger workflows.

1. Review the candidate and exact commit in the Actions summary. Retire source patches when that track's upstream provides equivalent behavior.
2. For conflicts, run `.github/scripts/fork-sync.sh <stable|nightly> <tag>` locally, resolve and commit the merge, then rerun the command. It preserves source edits, aligns submodules, and resumes an existing candidate branch. Commit or stash user edits first. Push the result and restart `fork-sync` for that track and tag to validate on GitHub Actions.
3. After validation and approval, run `git push origin <validated-sha>:refs/heads/<track>`. Check that validation identifies that exact commit. If the target moved and the push fails, prepare and validate a fresh candidate before retrying.
4. Start `fork-release` on the integration branch with `release` enabled. It validates again and drafts a release. Review and publish after approval; nightly releases are prereleases.

For build-only validation, start `fork-release` on the candidate with its matching `track` and `release` disabled. It uses `conda.test` and Contents read permission. Release numbering and write access belong to release preparation and drafting. Keep local work to preparation and `just ci`; full builds and simulator tests run on GitHub Actions.

## Workflows

Fork workflows match `.github/workflows/fork-*.yaml`.

```text
fork-checks    push              checks -- disable-upstream (stable, nightly)
fork-sync      schedule/manual  fork-update [stable, nightly]
                                  prepare -- fork-validate
fork-release   manual           fork-validate (build-only)
                                version -- fork-validate -- release (draft)
                                       +-- notes -----------+
fork-validate  reusable         checks + metadata -- build -- smoke [wh, bh]
fork-notify    published/manual  notify-tracer
```

- `fork-checks` runs `just ci`, which includes `fork-sync-test.py`. On nightly it also runs `fork-infra.sh check`. On stable and nightly it then disables upstream workflows, including newly added ones.
- `fork-update` prepares and pushes candidates with Contents write permission, then explicitly calls validation because token pushes may skip push workflows. Conflicts appear in the Actions summary and preparation log.
- `fork-validate` checks pins and nightly infrastructure, then builds and tests the clean wheel on both simulator architectures, including Tracy and device profiling. Build jobs use Contents read permission and save ccache on failure.
- `fork-select-tag.sh` picks and validates a track's upstream tag. `fork-version.sh` checks the upstream base and derives the wheel version. CI fetches upstream tags from tenstorrent because fork pushes carry none.
- `fork-release` counts drafts when choosing `conda.N`. Release notes use git-cliff and `.github/cliff.toml`; only matching integration branches can draft releases after validation.
- `fork-notify` dispatches `tt-metal-released` to `tt-vllm-tracer`, whose `sync-metal` workflow opens the dependency PR. Only `fork-notify` reads `TRACER_DISPATCH_TOKEN`, scoped to tracer's Contents write permission. Dispatch it with a tag to retry without rebuilding.

Upstream workflows stay in the tree, and `disable-upstream` keeps them off, because their schedules would queue for Tenstorrent's self-hosted runners. Use candidate branches instead of internal PRs, and keep `main` absent, issues off, and Dependabot off to avoid inherited triggers.

## Side effects

Sizes are from one local build. A cold `just build` takes about 32 min locally and 47 min on a runner; with a warm ccache the runner compiles in about 4 min.

| Path                                     | Written by                       | Size   |
| ---------------------------------------- | -------------------------------- | ------ |
| `.pixi/envs/`                            | pixi, recipes, wheel validation  | 2.9 GB |
| `build_Release/`, `build` linking to it  | `just build`                     | 2.3 GB |
| `runtime/`                               | `just build`                     | 0.4 GB |
| `~/.cache/cpm/`                          | `just build`                     | 4.0 GB |
| `~/.cache/ccache/`                       | `just build`                     | 0.6 GB |
| `sim/`                                   | `just fetch-ttsim`               | < 1 MB |
| `generated/`, `~/.cache/tt-metal-cache/` | `just test`, `just trace`        | 2 GB   |
| `dist/`, `build_wheel/`                  | `just wheel`, `just tracy-tools` | 0.4 GB |

The pixi environments have separate roles. `default` runs local builds and tests with editable ttnn, `ci` runs repository checks, and `wheel` validates the packaged wheel without the editable package shadowing it. Removing an inactive environment requires reinstalling it from the lockfile when next used. The wheel environment also needs the wheel installation step used by validation.

Tracy copies captures to `build/profiler/build_wasm/traces/` and points `build/profiler/build_wasm/embed.tracy` at the current capture. Its viewer keeps running after capture, using HTTP port 8080 and WebSocket port 8081 by default. Inspect the `serve_wasm.py` process and use `kill <PID>` to stop only the intended viewer. `pkill -f serve_wasm.py` also stops viewers from other checkouts. Removing capture files does not stop the server.

Other shared caches use these default locations. Environment variables and tool configuration can override them.

| Path                | Written by                     | Contents                               |
| ------------------- | ------------------------------ | -------------------------------------- |
| `~/.cache/rattler/` | pixi installs                  | conda and PyPI packages                |
| `~/.cache/uv/`      | `just wheel`, wheel validation | build dependencies and Python packages |

Tests and Python imports also create `.pytest_cache/` and `__pycache__/` directories. These development caches are disposable.

Sizes are snapshots, not limits. Caches grow with use, and pixi may hard-link installed files to shared package caches, so directory sizes are not additive or a guarantee of reclaimed space. Under WSL, deleting files does not necessarily shrink the virtual disk file on Windows.

Run these commands from the tt-metal repository root. Inspect each process's command and path before stopping it or deleting its build and capture files.

```sh
ps -eo pid,args | rg '[s]erve_wasm.py|[p]ython.*tracy|[n]inja|[c]make --build'
du -sh .pixi/envs/* build_Release runtime generated dist build_wheel 2>/dev/null
du -sh ~/.cache/cpm ~/.cache/ccache ~/.cache/tt-metal-cache ~/.cache/rattler ~/.cache/uv 2>/dev/null
git status --short
```

- **Recorded results**: inspect `generated/` and `build/profiler/build_wasm/traces/` before deleting selected captures. These contain results, not just caches. A new run cannot recover an old capture.
- **Build outputs**: `build` links to `build_Release/`. Removing `build_Release/` and `runtime/` retires the local build and disables execution through editable ttnn until `just build` succeeds again. The tracer's published-wheel environment is independent of this local build.
- **Packaging outputs**: `dist/` and `build_wheel/` can be removed after saving any unpublished assets that are still needed. Recreating packages needs a working local build.
- **Build caches**: removing `~/.cache/cpm/` forces source downloads on later builds. Removing `~/.cache/ccache/` loses reusable compilation results. Keep both when continuing local builds.
- **Kernel cache**: removing `~/.cache/tt-metal-cache/` forces kernel recompilation. This cache is shared with tracer runs and other checkouts.
- **Packages and simulator**: prefer package-manager cache-clean commands for shared rattler and uv caches. Remove `sim/` as a whole, including `.version`, only when a fresh simulator download is wanted. `just fetch-ttsim` restores it.

For example, after stopping captures and saving any needed profiling results, this removes local logs and capture files without deleting the build or environments:

```sh
rm -rf -- generated build/profiler/build_wasm/traces build/profiler/build_wasm/embed.tracy
```

Actions caches pixi environments, ccache, and CPM sources on GitHub, separately from local files. Validation also uploads the wheel, Tracy tools, and smoke-test results as workflow artifacts. Release workflows create draft GitHub releases and upload assets only when release preparation is enabled. Local cache cleanup does not remove remote caches, artifacts, or releases.

## Compared with upstream wheels

Upstream's `.github/workflows/wheels.yaml` builds with cibuildwheel in manylinux. The fork's toolchain and runtime dependencies are defined in `pixi.toml`.

| Aspect                     | Upstream PyPI wheel  | Fork release wheel                 |
| -------------------------- | -------------------- | ---------------------------------- |
| Tracy                      | off                  | on                                 |
| Multihost MPI              | on, bundled          | off                                |
| SFPI compiler              | installed separately | bundled                            |
| tt_transformers' `models/` | requires a checkout  | bundled                            |
| Platform tag               | `manylinux`          | `linux_x86_64`, needs pixi runtime |
| Version                    | upstream tag         | upstream version plus `+conda.N`   |

## Releases

Tags use `<upstream-tag>-conda.N`. The wheel adds `+conda.N` as a PEP 440 local version and writes `-dev` as `.dev`. The [tt-vllm-tracer](https://github.com/Stanley5249/tt-vllm-tracer) project's `pyproject.toml` and `docs/env-vars.md` describe consuming the release wheel.
