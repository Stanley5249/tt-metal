# Stanley5249/tt-metal

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal) builds tt-metal with Tracy for ttsim in a sudo-free pixi environment. Releases ship one ttnn wheel that bundles the Tracy tools and viewer, and a `tt-metal` conda metapackage that names the native libraries the wheel loads.

## Branches

| Branch | Holds | Takes upstream from |
| --- | --- | --- |
| `stable` | default branch: upstream release, patches, pins, and fork | `v0.Y.Z` tags of upstream `stable` |
| `main` | the same on upstream's nightly line | `v0.Y.Z-devN` tags of upstream `main` |
| `fork` | orphan branch with only the fork-owned files | nothing |

Each channel merges the upstream tag of its own line, and the `fork` branch. The fork-owned files are `AGENTS.md`, the `justfile`, `.oxfmtrc.json`, `fork/`, `.github/zizmor.yml`, and `.github/workflows/fork-*.yaml`, so an infra commit has one SHA on both channels. `pixi.toml`, `pixi.lock`, and the source patches stay on each channel, because their content differs. `just check` on a channel fails when a fork-owned path differs from the fork commit that the channel merged last.

```text
upstream stable --v0.82.0----------------------------v0.82.1
                       \ merge                          \
stable          --M--s--F--b--o[v0.82.0-conda.1]------M--F--b--o[v0.82.1-conda.1]
                        ^                                 ^
fork            i1--i2--+-----------i3----------------i4--+
                        v
main            --M--s'-F--b--o[v0.83.0-dev20261121-conda.2]
upstream main   --v0.83.0-dev20261121
M upstream merge, F fork merge, s/s' fix and its cherry-pick -x, b pin commit, o release
```

Choose the integration method by the kind of change:

| Change               | Method                                                                    |
| -------------------- | ------------------------------------------------------------------------- |
| fork-owned file      | commit on `fork`, then `git merge fork` on the checked-out channel        |
| upstream update      | `pixi run --script fork/scripts/sync.py merge` on the checked-out channel |
| source fix, both     | commit on one channel, `git cherry-pick -x` onto the other                |
| source fix, one only | commit on that channel, and note it in the patch table                    |

Edit fork-owned files in a worktree of the `fork` branch, such as `git worktree add .agents/worktrees/fork fork`. It holds a few files and builds nothing, so it needs no pixi environment; run `just ci` there. A channel takes a fork change at its next sync, or by `git merge fork` when it needs the change sooner. Never merge a channel into `fork`, and never cherry-pick onto it.

One checkout serves both channels. Switching is `git switch --recurse-submodules main`, then `just install && just build`: the submodules differ, one `build_Release/` is reconfigured and relinked, and ccache serves most objects.

## History

- Read a channel with `git log --first-parent stable`. It shows upstream merges, fork merges, fixes, and pin commits. Read the infra with `git log fork`.
- Merge subjects are fixed: `Merge upstream <tag> into <channel>` and `Merge fork into <channel>`, both written by `sync.py`.
- Squash topic work before it lands, with `git commit --fixup` and `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash`. Fix pushed commits with follow-ups.
- Preserve published history and published release tags.
- The first fork commits name their source, such as `Moved from stable@c8db27d008e`, because blame stops at the orphan root. `git log c8db27d008e -- .github/scripts/fork-release.py` still finds the older history.

## Patches

The fork's source patches, all maintained here. Search a channel for the key to find a patch.

| Patch | Key | Upstream files |
| --- | --- | --- |
| build tensors on the host under ttsim | `is_simulator` | `ttnn/core/tensor/py_to_tt_tensor.cpp` |
| read the wall clock without tearing | `read_wall_clock` | `tt_metal/hw/inc/api/debug/kernel_profiler.hpp`, `hostdev/split_counter.h` |
| skip zero-length profiler NoC writes | `noc_at_len_be=0` | `tt_metal/hw/inc/api/debug/kernel_profiler.hpp` |
| nominal AICLK for simulator ticks | `profiler_aiclk_mhz` | `tt_metal/impl/profiler/profiler_analysis.*`, `profiler.cpp` |
| wait for each ttsim core's profiler flush | `TT-SIM-PROFILER-SYNC` | `tt_metal/impl/profiler/tt_metal_profiler.cpp` |
| place ttsim device zones on host time in Tracy | `TT-SIM-PROFILER-SYNC` | `tt_metal/impl/profiler/`, `llrt/llrt.cpp`, `impl/program/slow_dispatch.cpp`, `impl/host_api/tt_metal.cpp` |
| place hardware device zones per chip and per read | `remote_clock_offset` | `tt_metal/impl/profiler/` |
| discard device markers without reading them | `DiscardMeshDeviceProfilerResults` | `tt_metal/impl/profiler/`, `ttnn/cpp/ttnn-nanobind/device.cpp`, `ttnn/ttnn/` |
| ship tt_transformers' `models/` for vLLM on ttsim | `model_params` | `setup.py`, `models/ttt_compat/tt/model_config.py` |
| bundle the SFPI compiler and licenses | `BUNDLE_SFPI` | `setup.py`, `tt_metal/sfpi-licenses/` |
| bundle the Tracy tools, viewer, and licenses | `tracy_licenses` | `setup.py` |
| build in pixi | `pixi` | `.gitattributes`, `.gitignore` |

`tt_metal/impl/profiler/split_counter_test.cpp` and `simulator_clock_test.cpp` are host tests of the clock math, which `just test` compiles and runs on a channel. `tools/tracy/` matches upstream. tt-metal's own ops report step fails on an eager op whose device markers were discarded, so a workflow that discards markers builds its report another way, as tt-scope does.

Review the patches of the checked-out channel, or compare both channels' patches, with the base that `pixi.toml` records:

```sh
base=v$(pixi workspace version get | sed 's/\.dev/-dev/')
git diff "$base" HEAD -- . ':!tt_metal/sfpi-licenses' ':!fork' ':!pixi.*'
git range-diff v0.82.0..stable v0.83.0-dev20261121..main -- . ':!tt_metal/sfpi-licenses' ':!fork' ':!pixi.*'
```

ttsim's clock advances only when the host reads the device, so its ticks have no fixed rate in host time. The device profiler samples the simulator clock of every profiled device with Tracy's host clock around each program launch, around each wait for programs to finish, and after each profiler read, and places ttsim markers in Tracy by interpolating between those samples. Every device is sampled at each point, because chips that share one simulator clock run while the host works on any of them. Each sample costs about three register reads per device, so a workload spanning N devices pays for about N² reads per program, and reads of a remote chip clock the simulator too; this is small next to the polling of a ttsim run. Profiler CSV files, ops reports, and NoC traces keep raw ticks.

On hardware, every profiled chip runs its own worker-to-host sync when the mesh opens and closes, instead of mapping other chips' worker markers through an Ethernet-to-Ethernet fit, because a chip's worker and Ethernet counters need not share an epoch. AICLK drops under sustained load, such as a vLLM server's warmup, and the device counter runs on it, so one open fit drifts by hundreds of ms over minutes. Mid-run profiler reads and `DiscardDeviceProfiler` therefore take a fresh anchor per chip: the fastest of eight tear-free host reads of a worker wall clock register. Tracy interpolates between anchors and uses the open sync slope outside them. A remote chip's register reads return its worker counter plus a constant offset, so that offset is measured right after the open sync and subtracted from later reads. A midpoint anchor has uncertainty up to half its logged read latency, about 4 µs over PCIe and up to a few hundred µs over Ethernet, and interpolation cannot recover clock-rate changes between anchors. Mid-run reads and discards reject an active Metal trace capture; the final read when a mesh closes does not. Sampling launches no kernel and writes no profiler buffer, and accumulate mode, which skips the open sync, keeps the old placement. With the device-to-device fit gone, multi-chip NoC traces keep each chip's raw counter and are not on one timebase.

The ttsim flush wait is a workaround: BRISC reports a program done before its profiler flush, and ttsim runs the flush only while the host reads the device, so a profiler read or discard polls each core first; a discard that finds a core still flushing fails rather than leak its markers into the next read. It runs only at profiler reads and discards. A firmware zone's end and the flush zones that follow DONE are therefore placed by interpolation over whatever host work comes next, such as the next op's compile. Retire the wait if upstream ttsim or tt-metal flushes before reporting done.

## Syncing with upstream

Sync runs locally on the checked-out channel; it builds nothing and pushes nothing:

```sh
git switch --recurse-submodules main && git pull --ff-only
pixi run --script fork/scripts/sync.py -- merge [--tag v0.83.0-dev20261130]
just install && just build && just ci
git push origin main
```

Stable takes upstream's newest published `vX.Y.Z` release, and main the newest `vX.Y.Z-devN`; `--tag` names one, which must be a forward upgrade from the base that `pixi.toml` records. sync.py refuses uncommitted changes, but accepts a submodule at an older recorded commit, which the merge aligns. It merges the tag, checks that `tt_metal/sfpi-version` and `tt_metal/ttsim-version` match upstream, updates the submodules, records the new base in `pixi.toml`, and merges `fork`. A merge conflict exits with status 2: resolve it, commit the merge, and run sync.py again.

A changed ttsim version needs the fork's patched build of it. sync.py decides before merging: it takes the highest published `steps.N` build of Stanley5249/ttsim whose conda package is non-empty with a SHA-256 digest, pins it in `pixi.toml`, and runs `pixi lock`. For 48 hours after upstream publishes the version it waits for the build and merges nothing; later it fails and names the release workflow to run. An unchanged version keeps its build, even when a newer `steps.N` exists.

Upstream's workflows stay in the tree for merge compatibility but must never run here. Before a push or a new tag, sync.py and release.py stop while an inherited workflow is active or unregistered on GitHub. Disable an active one with `gh workflow disable <path> -R Stanley5249/tt-metal`. GitHub registers a workflow only once a run evaluates it, so for a new path push a separate branch with a no-op stub at that path that runs on pushes to that branch only, disable the registered workflow, delete the branch, then retry.

## Releases

Tags use `<upstream-tag>-conda.N`. The wheel adds `+conda.N` as a PEP 440 local version and writes `-dev` as `.dev`. Stable releases take GitHub's latest label only when newest; main's releases are prereleases. Published releases are immutable. The [tt-scope](https://github.com/Stanley5249/tt-scope) project's `pyproject.toml` and `docs/side-effects.md` describe consuming the release.

A release runs locally or on GitHub Actions with the same scripts. Locally:

```sh
just build
pixi run --script fork/scripts/release.py prepare   # dist/<tag>/: wheel, conda package, manifest, notes.md
$EDITOR dist/<tag>/notes.md
git push origin HEAD
pixi run --script fork/scripts/release.py publish
```

On Actions, `gh workflow run fork-release.yaml -R Stanley5249/tt-metal`, with `--ref main` for main, runs the same two commands in a read-only job and a write job. The scripts have no CI branches: CI sets `TT_BUILD_JOBS` and `CCACHE_MAXSIZE`, and the build's defaults suit a workstation. The dispatch is the approval, and the notes are published as generated. Replace published notes with `gh release edit <tag> -R Stanley5249/tt-metal --notes-file <file>`.

`release.py prepare` packages the last `just build`, so build first. It reads GitHub's tags and releases and writes nothing remote. It numbers the release after every existing tag on the base, and stops when HEAD is already released or a draft is left on the base, instead of resuming either. It checks upstream's SFPI and ttsim pins, packages the wheel and, with `rattler-build`, the metapackage, and checks that the wheel ships tracy-capture, tracy-csvexport, the viewer's static files, the SFPI tools, and the license texts. rattler-build installs the metapackage in a fresh environment and runs the recipe's tests. The script then installs the wheel in the `wheel` environment and runs `fork/scripts/smoke.py` on the Wormhole simulator, from a folder outside the checkout so that the checkout's `models/` cannot answer for the wheel's: it checks the tt_transformers modules that tt-scope imports and runs one add, without the profiler. Profiler capture tests belong to tt-scope, because a profiler bug found there costs one new `-conda.N`, while capture tests here would slow every release. The notes list HEAD's conventional commits since the upstream base that no earlier fork release listed. `fork-manifest.json` ties the assets to the commit. `release.py publish` finds the folder whose manifest names HEAD, requires HEAD on the channel's remote branch, checks the numbering again with write access, creates a draft at HEAD with `notes.md` as it stands, compares GitHub's asset names, sizes, and digests with the manifest, and publishes it, which creates the tag. Neither command regenerates the notes. A failed publish leaves the draft, and the next run names it: delete it with `gh release delete <tag> -R Stanley5249/tt-metal`, then run `release.py publish` again.

Each release also carries `tt-metal-<version>-0.conda`, a `noarch` conda metapackage with the wheel's version. It ships no files: its run dependencies are the native libraries that the wheel loads from the environment, such as libhwloc, libnuma, the SFPI compiler's mpc and zstd, and a libstdc++ at least as new as GCC 13's, so a consumer pins it beside the wheel instead of listing them. `fork/conda/recipe.yaml` holds the list and repeats `feature.runtime` in `pixi.toml`; change both together. The consumer still points `TT_METAL_HOME` and `TT_METAL_RUNTIME_ROOT` at the installed `ttnn` and puts the environment's `lib/` on `LD_LIBRARY_PATH`. pixi caches a conda package by name, version, and build, so a local rebuild with the same version installs the cached one until that cache entry is removed.

## Workflows

`.github/workflows/fork-checks.yaml` checks pushes to the channels and `fork`; `fork-release.yaml` runs `release.py prepare` in a read-only job and `publish` in a write job, on a manual dispatch. The workflow files list each job's triggers, steps, and tools.

Versions follow tt-scope's [versions in CI](https://github.com/Stanley5249/tt-scope/blob/main/docs/architecture.md#versions-in-ci): workflows install the latest pixi and follow action version tags, which `.github/zizmor.yml` allows. The command-line tools that recipes call come from `PATH`: install them with `pixi global install just ruff pyrefly uv bun gh git-cliff rattler-build actionlint zizmor`. Fork scripts carry a PEP 723 header and run with `pixi run --script`; uv is left only for building the wheel and installing it into the `wheel` environment, which pixi cannot do.

fork-release's prepare job restores ccache and the CPM cache, keyed per run and restored by channel, then stable, and saves them even when the build fails. A warm ccache cuts the build from most of an hour to minutes; the workflow sets `TT_BUILD_JOBS` for the runner's memory.

## Side effects

A cold `just build` takes about half an hour locally; `du -sh` on these paths shows their sizes.

| Path                                    | Written by                            |
| --------------------------------------- | ------------------------------------- |
| `.pixi/envs/`                           | `just install`, `release.py prepare`  |
| `build_Release/`, `build` linking to it | `just build`                          |
| `runtime/`                              | `just build`                          |
| `~/.cache/cpm/`                         | `just build`                          |
| `~/.cache/ccache/`                      | `just build`                          |
| `~/.cache/tt-metal-cache/`              | tests, captures, `release.py prepare` |
| `dist/<tag>/`, `build_wheel/`           | `release.py prepare`                  |
| `build_conda/`                          | `release.py prepare`                  |

`just install` and `release.py prepare` also write one symlink per simulator in their environment, `.pixi/envs/<environment>/lib/ttsim/<arch>/soc_descriptor.yaml`, which points at this tree's descriptor, because UMD reads it beside the library and real hardware reads the same files. `TTSIM_ARCH=bh` selects Blackhole; the default is Wormhole. ttsim runs here on those two architectures only: the Stanley5249/ttsim package has no Quasar library.

The `default` environment runs local builds and tests with editable ttnn, and `wheel` runs the packaged wheel without the editable package shadowing it. `release.py prepare` installs the wheel into `wheel` and writes `dist/<tag>/` from scratch, but stops when `notes.md` is already there, so reviewed notes survive.

Tracy copies captures to `build/profiler/build_wasm/traces/` and points `build/profiler/build_wasm/embed.tracy` at the current capture. Its viewer keeps running after a capture, using HTTP port 8080 and WebSocket port 8081 by default. For other viewers, inspect the `serve_wasm.py` process and use `kill <PID>`; `pkill -f serve_wasm.py` also stops viewers from other checkouts. Removing capture files does not stop the server.

Other shared caches: `~/.cache/rattler/` holds pixi's conda and PyPI packages, and `~/.cache/uv/` the wheel build's dependencies and the scripts' environments. Sizes are snapshots, not limits, and pixi may hard-link installed files to shared package caches, so sizes are not additive. Under WSL, deleting files does not necessarily shrink the virtual disk.

```sh
ps -eo pid,args | rg '[s]erve_wasm.py|[p]ython.*tracy|[n]inja|[c]make --build'
du -sh .pixi/envs/* build_Release runtime generated dist build_wheel 2>/dev/null
du -sh ~/.cache/cpm ~/.cache/ccache ~/.cache/tt-metal-cache ~/.cache/rattler ~/.cache/uv 2>/dev/null
```

- Recorded results: `generated/` and `build/profiler/build_wasm/traces/` hold captures, not only caches.
- Build outputs: removing `build_Release/` and `runtime/` retires the local build and editable ttnn until `just build` succeeds again.
- Build caches: removing `~/.cache/cpm/` forces source downloads, and removing `~/.cache/ccache/` loses reusable objects.
- Remote state: Actions keeps caches and artifacts, and only `publish` creates tags and releases. Local cleanup removes none of them.

## Compared with upstream wheels

Upstream's `.github/workflows/wheels.yaml` builds with cibuildwheel in manylinux. The fork's toolchain and runtime dependencies are defined in `pixi.toml`.

| Aspect                     | Upstream PyPI wheel  | Fork release wheel                 |
| -------------------------- | -------------------- | ---------------------------------- |
| Tracy                      | off                  | on                                 |
| Multihost MPI              | on, bundled          | off                                |
| SFPI compiler              | installed separately | bundled                            |
| Tracy tools and viewer     | not included         | bundled                            |
| tt_transformers' `models/` | requires a checkout  | bundled                            |
| Platform tag               | `manylinux`          | `linux_x86_64`, needs pixi runtime |
| Version                    | upstream tag         | upstream version plus `+conda.N`   |
