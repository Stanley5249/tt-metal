# Stanley5249/tt-metal

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal) builds tt-metal with Tracy for ttsim in a sudo-free pixi environment. Releases ship a ttnn wheel and Tracy tools. This file stays on the fork's two tracks.

## Branches

`stable` is the default branch, based on upstream's latest release. `nightly` is based on upstream's latest nightly tag. Their upstream histories diverge, so each track runs its own workflows and scripts from its own ref, and neither track is merged into the other. Preserve published history and published release tags. The fork has no `main`.

Choose the integration method by the kind of change:

| Change                     | Method                                  |
| -------------------------- | --------------------------------------- |
| Fork-owned task            | task branch, then fast-forward          |
| Upstream update            | `fork-sync` merges, validates, promotes |
| Shared change, other track | cherry-pick and adapt                   |

Keep fork-owned changes focused, preferably one commit per change. Unpublished fork-owned task commits may be rebased onto the latest target before integration. Fix published changes with follow-ups. A track moves only by fast-forward, and `fork-sync` moves it only to the commit that passed validation.

```text
upstream releases -- v0.79.0 ----------------------- v0.80.0
                        \                               \
stable                   M -- fork change -- fix ------- M
                                              |
                                              | cherry-pick
                                              v
nightly            M ----------------------- fix ------------ M
                  /                                          /
upstream main -- v0.80.0-dev20261002 ------------- v0.81.0-dev20261011
```

Start fork-owned work on a task branch from either track. Stable also serves as the base for experiments. When a change applies to the other track, cherry-pick it onto a task branch from that track and adapt it. Nothing forces the tracks' fork files to match, so review drift with `git diff stable nightly -- FORK.md justfile pixi.toml .github/scripts .github/workflows/fork-*.yaml` when porting.

The fork's source patches, all maintained here:

| Patch                                             | Upstream files                                               |
| ------------------------------------------------- | ------------------------------------------------------------ |
| build tensors on the host under ttsim             | `ttnn/core/tensor/py_to_tt_tensor.cpp`                       |
| device profiler on ttsim's clock                  | `tt_metal/impl/profiler/`, `tt_metal/**/kernel_profiler.hpp` |
| skip unpaired device markers instead of aborting  | `tt_metal/impl/profiler/profiler.cpp`                        |
| `TT_METAL_SFPI_ROOT` for the kernel JIT           | `tt_metal/jit_build/build.cpp`                               |
| ship tt_transformers' `models/` for vLLM on ttsim | `setup.py`, `models/tt_transformers/tt/model_config.py`      |
| ship the ttsim version pin and release            | `setup.py`                                                   |
| bundle the SFPI compiler and licenses             | `setup.py`, `tt_metal/sfpi-licenses/`                        |
| build in pixi                                     | `.gitattributes`, `.gitignore`                               |

## Syncing with upstream

`fork-sync` runs on the track it updates. Its schedule runs on stable, the default branch, and starts a separate run on nightly so nightly uses its own workflow files. Stable selects upstream's `releases/latest`; nightly selects the newest published `vX.Y.Z-devN` release. SFPI and ttsim follow that tag's pins. `tt_metal/ttsim-release` names the patched ttsim build to download, a [Stanley5249/ttsim](https://github.com/Stanley5249/ttsim) release tagged `<ttsim-version>-steps.N`, whose wall clock gives each simulator step its own time so device profiler timestamps never tie. When an upstream update moves `ttsim-version`, release the matching build there first and update `ttsim-release` on that track, or `just fetch-ttsim` refuses the mismatch.

One run does the whole update:

1. `fork-sync.sh <track> [tag]` resolves the tag to a commit and stops when the track already contains it. Otherwise it merges that commit into `chore/sync-<track>-<tag>` with a merge commit, never by rebasing fork patches, and resumes that branch when it already exists on the fork.
2. The workflow pushes the update branch, then `fork-release` numbers the release, validates that exact commit, fast-forwards the track to it, and drafts `<upstream-tag>-conda.N` with the artifacts that the smoke tests used.
3. Review the draft and the Actions summary, retire source patches when upstream provides equivalent behavior, and publish the draft by hand. Nightly drafts are prereleases.

The script exits with status 2 on a merge conflict and leaves the merge in progress. Any other failure, such as a fetch or pin check, exits with another status and is not a conflict. To resolve a conflict, commit or stash local edits, run `.github/scripts/fork-sync.sh <track> <tag>` from a full clone with an `upstream` remote, resolve and commit the merge, rerun the command, push the update branch with `git push origin HEAD`, and rerun `fork-sync` on the track with the same tag. If the track moves during validation, promotion fails and nothing is drafted. The next run resumes the update branch and merges the moved track into it, keeping any manual resolution. If only the draft fails after promotion, rerun that failed job, which drafts from the same artifacts; a new sync run would find the track up to date.

Upstream updates change `.github/workflows/`, which `GITHUB_TOKEN` cannot push. The `FORK_SYNC_TOKEN` secret, a fine-grained token for this repository with Contents and Workflows write, pushes the update branch and moves the track. Only those two steps read it, after the merge code has finished; builds and tests use read-only tokens. Pushes with this token trigger push workflows like a person's push.

For build-only validation, start `fork-release` on any branch with `release` disabled. It labels the wheel `conda.test` and uses Contents read permission. To release a fork-owned change without an upstream update, start `fork-release` on stable or nightly with `release` enabled; it drafts from the commit it validated and does not move the track. Keep local work to preparation and `just ci`; full builds and simulator tests run on GitHub Actions.

## Workflows

Fork workflows match `.github/workflows/fork-*.yaml`.

```text
fork-checks    push              checks -- disable-upstream (tracks, update branches)
fork-sync      schedule/manual   nightly (schedule only: starts nightly's run)
                                 prepare -- fork-release (when updated: promote, release)
fork-release   manual/reusable   version --+-- fork-validate --+-- promote -- release (draft)
                                           +-- notes ----------+
fork-validate  reusable          checks + metadata -- build -- smoke [wh, bh]
fork-notify    published/manual  notify-tracer
```

- `fork-checks` runs `just ci`, which includes `fork-sync-test.py`. On the tracks and `chore/sync-*` branches it then disables upstream workflows, including newly added ones.
- `fork-sync` prepares the update branch from a full clone, because the merge reads upstream objects that the fork will not serve to a partial clone. Conflicts and other errors appear in the Actions summary and preparation log.
- `fork-validate` checks pins, then builds and tests the clean wheel on both simulator architectures, including Tracy, device profiling, and NoC tracing. It infers the track from the upstream base. Build jobs use Contents read permission and save ccache on failure.
- `fork-select-tag.sh` picks and validates a track's upstream tag. `fork-version.sh` checks the upstream base and derives the track and wheel version. CI fetches upstream tags from tenstorrent because fork pushes carry none.
- `fork-release` chooses `conda.N` before building, counting drafts, and builds the wheel with that version. Its scripts come from the branch it runs on, not from the commit it validates. Release notes use git-cliff and `.github/cliff.toml`. Only stable and nightly can draft releases, and the draft summary lists the assets' SHA-256 digests. Runs on one branch queue, so two drafts never race for a label.
- `fork-notify` dispatches `tt-metal-released` to `tt-vllm-tracer`, whose `sync-metal` workflow opens the dependency PR. Only `fork-notify` reads `TRACER_DISPATCH_TOKEN`, scoped to tracer's Contents write permission. Dispatch it with a tag to retry without rebuilding.

Upstream workflows stay in the tree, and `disable-upstream` keeps them off, because their schedules would queue for Tenstorrent's self-hosted runners. A sync can add new ones, which start active until the next push to a track or update branch disables them. Use update branches instead of internal PRs, and keep `main` absent, issues off, and Dependabot off to avoid inherited triggers.

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
