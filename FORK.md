# Stanley5249/tt-metal

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal) builds tt-metal with Tracy for ttsim in a sudo-free pixi environment. Releases ship a ttnn wheel that bundles the Tracy tools and viewer, and, until tt-vllm-tracer moves off it, the same tools as a tarball. This file stays on the fork's two tracks.

## Branches

`stable` is the default branch, based on upstream's latest release. `nightly` is based on upstream's latest nightly tag. Their upstream histories diverge, so each track runs its own workflows and scripts from its own ref, and neither track is merged into the other. Preserve published history and published release tags. The fork has no `main`.

Choose the integration method by the kind of change:

| Change                     | Method                                             |
| -------------------------- | -------------------------------------------------- |
| Fork-owned task            | task branch, then fast-forward                     |
| Upstream update            | `fork-sync` merges and fast-forwards without builds |
| Shared change, other track | cherry-pick and adapt                              |

Keep fork-owned changes focused, preferably one commit per change. Unpublished fork-owned task commits may be rebased onto the latest target before integration. Fix published changes with follow-ups. A track moves only by fast-forward, and routine syncs do not guarantee build validation.

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

| Patch                                             | Upstream files                                                                                                                        |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| build tensors on the host under ttsim             | `ttnn/core/tensor/py_to_tt_tensor.cpp`                                                                                                |
| read the wall clock without tearing               | `tt_metal/hw/inc/api/debug/kernel_profiler.hpp`, `tt_metal/hw/inc/hostdev/split_counter.h`                                            |
| skip zero-length profiler NoC writes              | `tt_metal/hw/inc/api/debug/kernel_profiler.hpp`                                                                                       |
| nominal AICLK for simulator ticks                 | `tt_metal/impl/profiler/profiler_analysis.*`, `profiler.cpp`                                                                          |
| wait for each ttsim core's profiler flush         | `tt_metal/impl/profiler/tt_metal_profiler.cpp`                                                                                        |
| place ttsim device zones on host time in Tracy    | `tt_metal/impl/profiler/`, `tt_metal/llrt/llrt.cpp`, `tt_metal/impl/program/slow_dispatch.cpp`, `tt_metal/impl/host_api/tt_metal.cpp` |
| place hardware device zones per chip and per read | `tt_metal/impl/profiler/`, `tools/tracy/process_ops_logs.py`                                                                          |
| discard device markers without reading them       | `tt_metal/impl/profiler/`, `ttnn/cpp/ttnn-nanobind/device.cpp`, `ttnn/ttnn/`                                                         |
| `TT_METAL_SFPI_ROOT` for the kernel JIT           | `tt_metal/jit_build/build.cpp`                                                                                                        |
| ship tt_transformers' `models/` for vLLM on ttsim | `setup.py`, `models/ttt_compat/tt/model_config.py`                                                                               |
| ship the ttsim version pin                        | `setup.py`                                                                                                                            |
| bundle the SFPI compiler and licenses             | `setup.py`, `tt_metal/sfpi-licenses/`                                                                                                 |
| bundle the Tracy tools, viewer, and licenses      | `setup.py`                                                                                                                            |
| build in pixi                                     | `.gitattributes`, `.gitignore`                                                                                                        |

ttsim's clock advances only when the host reads the device, so its ticks have no fixed rate in host time. The device profiler samples the simulator clock of every profiled device with Tracy's host clock around each program launch, around each wait for programs to finish, and after each profiler read, and places ttsim markers in Tracy by interpolating between those samples. Every device is sampled at each point, because chips that share one simulator clock run while the host works on any of them. Each sample costs about three register reads per device, so a workload spanning N devices pays for about N² reads per program, and reads of a remote chip clock the simulator too; this is small next to the polling of a ttsim run. Profiler CSV files, ops reports, and NoC traces keep raw ticks. Search for `TT-SIM-PROFILER-SYNC` to find every hook.

On hardware, every profiled chip runs its own worker-to-host sync when the mesh opens and closes, instead of mapping other chips' worker markers through an Ethernet-to-Ethernet fit, because a chip's worker and Ethernet counters need not share an epoch. AICLK drops under sustained load, such as a vLLM server's warmup, and the device counter runs on it, so one open fit drifts by hundreds of ms over minutes. Mid-run profiler reads and `DiscardDeviceProfiler` therefore take a fresh anchor per chip: the fastest of eight tear-free host reads of a worker wall clock register. Tracy interpolates between anchors and uses the open sync slope outside them. A remote chip's register reads return its worker counter plus a constant offset, so that offset is measured right after the open sync and subtracted from later reads. A midpoint anchor has uncertainty up to half its logged read latency, about 4 µs over PCIe and up to a few hundred µs over Ethernet, and interpolation cannot recover clock-rate changes between anchors. Mid-run reads and discards reject an active Metal trace capture; the final read when a mesh closes does not. Sampling launches no kernel and writes no profiler buffer, and accumulate mode, which skips the open sync, keeps the old placement. With the device-to-device fit gone, multi-chip NoC traces keep each chip's raw counter and are not on one timebase.

The ttsim flush wait is a workaround: BRISC reports a program done before its profiler flush, and ttsim runs the flush only while the host reads the device, so the profiler read polls each core first. It runs only at profiler reads. A firmware zone's end and the flush zones that follow DONE are therefore placed by interpolation over whatever host work comes next, such as the next op's compile. Retire the wait if upstream ttsim or tt-metal flushes before reporting done.

## Syncing with upstream

`fork-sync` runs on the track it updates. Stable syncs weekly on Monday at 05:23 Taiwan time. A Thursday 12:23 schedule starts nightly's own workflow. Manual runs accept an optional exact upstream `tag`. Stable selects upstream's latest release; nightly selects the newest published `vX.Y.Z-devN` release.

`fork-sync.sh` merges upstream into `chore/sync-<track>-<tag>`, preserves fork commits, and records the upstream base in `pixi.toml`. SFPI and ttsim follow upstream's pins. A changed ttsim pin selects the highest published patched `steps.N` build with nonempty assets and SHA-256 digests, and updates `pixi.toml` and `pixi.lock` together. An unchanged pin keeps its existing build. The script waits for a newly published ttsim build for up to 48 hours; a later scheduled or manual sync retries. Conflicts and invalid pins fail without advancing the track.

The merge job has no write token because `pixi lock` can execute merged code. A separate job imports its git bundle, checks the candidate commit, disables inherited workflows, and atomically pushes the candidate and track with fast-forward checks. `FORK_SYNC_TOKEN` needs Contents and Workflows write. If the track moves incompatibly, the push fails safely. Routine sync does not build, smoke-test, tag, publish, resume releases, or notify tracer. A synced track may be broken until someone requests a release.

For conflicts, run `.github/scripts/fork-sync.sh <track> <tag>` in a clean full clone with an upstream remote, pixi, and authenticated gh. Resolve and commit the merge, rerun the script, push the candidate, and rerun `fork-sync` with the same tag. Existing candidate branches retain manual resolutions. Keep commit-based patches: merge history already preserves fork changes across two divergent tracks; patch files would add extraction, ordering, and reapplication work.

Releases are manual and use the exact commit captured when the run starts:

```sh
gh workflow run fork-release.yaml -R Stanley5249/tt-metal --ref stable -f release=true
gh workflow run fork-release.yaml -R Stanley5249/tt-metal --ref nightly -f release=true
```

Use `-f release=false` on a task branch for build-only validation with `conda.test`. Rerun failed release jobs to finish an existing tag or draft without allocating another version. Sync never recovers unfinished releases automatically. Published releases remain unchanged. Keep local work to `just ci`; full builds and simulator smoke tests run on GitHub Actions.

## Workflows

Fork workflows match `.github/workflows/fork-*.yaml`.

```text
fork-checks    push              lightweight checks, disable inherited workflows
fork-sync      weekly/manual     prepare -- push candidate and track (no build)
fork-release   manual            version -- validate + notes -- tag -- publish -- notify
fork-validate  reusable          checks + metadata -- build -- smoke [wh, bh]
fork-notify    published/manual  notify-tracer
```

`fork-checks` runs `just ci`, including sync, release, and installed-model checks. Track and candidate pushes disable inherited workflows even when checks fail. Fork workflows use no local composite actions; upstream actions stay in the tree for merge compatibility but are not used by fork workflows.

`fork-validate` checks upstream SFPI/ttsim pins, builds the wheel and Tracy tools, and tests the installed wheel on Wormhole and Blackhole simulators. Regression tests cover models packaging, Tracy capture/viewer, device profiling, NoC tracing, and simulator timestamps. `fork-manifest.json` ties the commit to artifact SHA-256 digests. Smoke tests and publication verify the same artifacts. Build jobs use read-only tokens and save ccache on failure.

`fork-select-tag.sh` validates upstream tags. `fork-version.sh` checks the upstream base recorded by `pixi.toml` and derives the wheel version. `fork-release.py` allocates `<upstream-tag>-conda.N` after existing tags and drafts, resumes a release at the same commit, and rejects unfinished releases at another commit. Manual releases queue per track. Stable releases take GitHub's latest label only when newest; nightly releases are prereleases. Publication checks tag identity, asset names, sizes, and manifest digests before and after publishing. A published release never changes.

Only successful publication of the newest channel release starts `fork-notify`. The existing `tt-metal-released` dispatch carries `repository`, `release`, and `track` to tracer. Tracer requires an immutable release, pins its exact wheel and lockfile, validates, and advances its branch. Only `fork-notify` reads `TRACER_DISPATCH_TOKEN`. Retry notification without rebuilding with `gh workflow run fork-notify.yaml -R Stanley5249/tt-metal --ref stable -f tag=<published-tag>` (use nightly for nightly).

## Side effects

Sizes are from one local build. A cold `just build` takes about 32 min locally and 47 min on a runner; with a warm ccache the runner compiles in about 4 min.

| Path                                     | Written by                       | Size   |
| ---------------------------------------- | -------------------------------- | ------ |
| `.pixi/envs/`                            | pixi, recipes, wheel validation  | 2.9 GB |
| `build_Release/`, `build` linking to it  | `just build`                     | 2.3 GB |
| `runtime/`                               | `just build`                     | 0.4 GB |
| `~/.cache/cpm/`                          | `just build`                     | 4.0 GB |
| `~/.cache/ccache/`                       | `just build`                     | 0.6 GB |
| `generated/`, `~/.cache/tt-metal-cache/` | `just test`, `just trace`        | 2 GB   |
| `dist/`, `build_wheel/`                  | `just wheel`, `just tracy-tools` | 0.4 GB |

`just link-ttsim`, which `just test` and `just trace` run first, writes one path outside the table's sizes: the symlink `.pixi/envs/<environment>/lib/ttsim/<arch>/soc_descriptor.yaml`, which points at this tree's descriptor, because UMD reads it beside the library and real hardware reads the same files. `TTSIM_ARCH=bh` selects Blackhole; the default is Wormhole. ttsim runs here on those two architectures only: the Stanley5249/ttsim package has no Quasar library, and `.github/actions/setup-ttsim` belongs to upstream's disabled workflows.

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
- **Packages**: prefer package-manager cache-clean commands for shared rattler and uv caches.

For example, after stopping captures and saving any needed profiling results, this removes local logs and capture files without deleting the build or environments:

```sh
rm -rf -- generated build/profiler/build_wasm/traces build/profiler/build_wasm/embed.tracy
```

Actions caches pixi environments, ccache, and CPM sources on GitHub, separately from local files. Validation also uploads the wheel, Tracy tools, their manifest, and smoke-test results as workflow artifacts. Only with manual `release` enabled, `fork-release` creates a tag, publishes a public GitHub release, and starts `fork-notify`, which updates tracer's `main`. Local cache cleanup does not remove remote caches, artifacts, tags, or releases.

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

## Releases

Tags use `<upstream-tag>-conda.N`. The wheel adds `+conda.N` as a PEP 440 local version and writes `-dev` as `.dev`. The [tt-vllm-tracer](https://github.com/Stanley5249/tt-vllm-tracer) project's `pyproject.toml` and `docs/env-vars.md` describe consuming the release wheel.
