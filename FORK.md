# Stanley5249/tt-metal

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal) builds tt-metal with Tracy for ttsim in a sudo-free pixi environment. Releases ship a ttnn wheel and Tracy tools. This file stays on the fork's two tracks.

## Branches

`stable` is the default branch, based on upstream's latest release. `nightly` is based on upstream's latest nightly tag. Their upstream histories diverge, so each track runs its own workflows and scripts from its own ref, and neither track is merged into the other. Preserve published history and published release tags. The fork has no `main`.

Choose the integration method by the kind of change:

| Change                     | Method                                             |
| -------------------------- | -------------------------------------------------- |
| Fork-owned task            | task branch, then fast-forward                     |
| Upstream update            | `fork-sync` merges, validates, promotes, publishes |
| Shared change, other track | cherry-pick and adapt                              |

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

`fork-sync` runs on the track it updates. Its schedule runs on stable, the default branch, and starts a separate run on nightly so nightly uses its own workflow files. Stable selects upstream's `releases/latest`; nightly selects the newest published `vX.Y.Z-devN` release. SFPI and ttsim follow that tag's pins, and the fork never overrides them. `tt_metal/ttsim-release` names the patched ttsim build to download, a [Stanley5249/ttsim](https://github.com/Stanley5249/ttsim) release tagged `<ttsim-version>-steps.N`, whose wall clock gives each simulator step its own time so device profiler timestamps never tie. That repository releases each new upstream ttsim release on its own daily schedule. `fork-sync.sh`, `fork-validate`, and `just fetch-ttsim` refuse a name that is not `<ttsim-version>-steps.N` with N from 1.

One run does the whole update:

1. `fork-sync.sh <track> [tag]` resolves the tag to a commit and stops with result `current` when the track already contains it.
2. When the tag moves `ttsim-version`, `fork-ttsim.py` picks the highest published `steps.N` build of the new pin whose `libttsim_wh.so` and `libttsim_bh.so` are non-empty and carry a sha256 digest. If no build exists yet, the script stops with result `waiting`, before merging or pushing anything, but only while the new pin is upstream ttsim's highest formal release and is less than 48 hours old; the next scheduled run retries. An older pin, a prerelease, an overdue build, a broken build, or an API error fails the run with the fix in the message. An unchanged pin keeps the track's build.
3. The script merges the tag into `chore/sync-<track>-<tag>` with a merge commit, never by rebasing fork patches, and resumes that branch when it already exists on the fork. It then commits the selected build to `ttsim-release`, keeping its repository, and reports result `ready` with the final commit.
4. The workflow pushes the update branch, then `fork-release` numbers the release, validates that exact commit, fast-forwards the track to it, tags it `<upstream-tag>-conda.N`, and publishes the release with the artifacts that the smoke tests used.
5. Review the release and the Actions summary afterwards, and retire source patches when upstream provides equivalent behavior.

The script exits with status 2 on a merge conflict and leaves the merge in progress. Any other failure, such as a fetch or pin check, exits with another status and is not a conflict. To resolve a conflict, commit or stash local edits, run `.github/scripts/fork-sync.sh <track> <tag>` from a full clone with an `upstream` remote and `gh auth login` done, since a ttsim pin change asks the GitHub API for builds. Resolve and commit the merge, rerun the command, push the update branch with `git push origin HEAD`, and rerun `fork-sync` on the track with the same tag. If the track moves during validation, promotion fails and nothing is tagged. The next run resumes the update branch and merges the moved track into it, keeping any manual resolution.

A release tag at the track's tip records the intent to release it. When a sync finds the track current and its tip tagged or drafted but not published, it validates the tip again and finishes that release without moving the track; without a tag or draft it releases nothing. Promotion comes before tagging, so a failure between the two leaves the track moved without a tag. Rerun the failed job in that case, because a new sync would find nothing to finish. Tagging first would instead leave tags on update commits that never reach the track.

Upstream updates change `.github/workflows/`, which `GITHUB_TOKEN` cannot push. The `FORK_SYNC_TOKEN` secret, a fine-grained token for this repository with Contents and Workflows write, pushes the update branch, moves the track, and creates the release tag. Only those steps read it, after the merge code has finished, and they run no repository code; builds and tests use read-only tokens. Pushes with this token trigger push workflows like a person's push, so the tagging job first disables upstream workflows with `GITHUB_TOKEN`.

For build-only validation, start `fork-release` on any branch with `release` disabled. It labels the wheel `conda.test` and uses Contents read permission. To release a fork-owned change without an upstream update, start `fork-release` on stable or nightly with `release` enabled; it tags and publishes the commit it validated and does not move the track. Keep local work to preparation and `just ci`; full builds and simulator tests run on GitHub Actions.

## Workflows

Fork workflows match `.github/workflows/fork-*.yaml`.

```text
fork-checks    push              checks -- disable-upstream (tracks, update branches)
fork-sync      schedule/manual   nightly (schedule only: starts nightly's run)
                                 prepare -- fork-release (ready: promote, release;
                                                          current: resume a started release)
fork-release   manual/reusable   version --+-- fork-validate --+-- ref -- release -- notify
                                           +-- notes ----------+   (promote, tag) (publish)
fork-validate  reusable          checks + metadata -- build -- smoke [wh, bh]
fork-notify    published/manual  notify-tracer
```

- `fork-checks` runs `just ci`, which includes `fork-sync-test.py` and `fork-release-test.py`. On the tracks and `chore/sync-*` branches it then disables upstream workflows, including newly added ones.
- `fork-sync` prepares the update branch from a full clone, because the merge reads upstream objects that the fork will not serve to a partial clone. Conflicts and other errors appear in the Actions summary and preparation log.
- `fork-validate` checks pins, then builds and tests the clean wheel on both simulator architectures, including Tracy, device profiling, and NoC tracing. It infers the track from the upstream base. The build writes `fork-manifest.json` with the commit and the SHA-256 of the wheel and Tracy tools, and smoke tests and the release check the artifacts against it. Build jobs use Contents read permission and save ccache on failure.
- `fork-select-tag.sh` picks and validates a track's upstream tag. `fork-version.sh` checks the upstream base and derives the track and wheel version. CI fetches upstream tags from tenstorrent because fork pushes carry none.
- `fork-release` chooses `conda.N` before building with `fork-release.py plan`, after every tag and release on the base, drafts included, and builds the wheel with that version. A release tag or tagless draft already at the commit is finished under its own number; a published one is only checked and notified again. An unpublished tag or draft for the same base at another commit stops the run until someone publishes or deletes it, so runs never pile up drafts. Its scripts come from the branch it runs on, not from the commit it validates. Release notes use git-cliff and `.github/cliff.toml`; a resumed draft keeps its notes. Only stable and nightly can release. Runs on one branch queue, so two releases never race for a label.
- The `release` job drafts on the existing tag, checks that the tag and draft name the validated commit and that the assets' names, sizes, and digests match the manifest, publishes, and checks the published release again. Stable takes GitHub's latest label only when it is newer than every published stable release; nightly releases are prereleases and never take it. A draft's assets may be replaced; a published release never changes.
- `fork-notify` dispatches `tt-metal-released` to `tt-vllm-tracer`. Its `sync-metal` workflow commits the wheel pin and lockfile for that exact release, validates that commit, and fast-forwards tracer's `main` to it instead of opening a dependency PR. `fork-release` starts `fork-notify` only for the newest release on a channel, because tracer does not refuse an older one; a release that a person publishes triggers it through the release event. Only `fork-notify` reads `TRACER_DISPATCH_TOKEN`, scoped to tracer's Contents write permission. Dispatch it with a tag to retry without rebuilding, or rerun `fork-release`, which notifies again for a release it already published.
- Failures show in each run's Actions summary and in GitHub's own failed-run notifications.

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

Actions caches pixi environments, ccache, and CPM sources on GitHub, separately from local files. Validation also uploads the wheel, Tracy tools, their manifest, and smoke-test results as workflow artifacts. With `release` enabled, including every `fork-sync` run that finds an update, `fork-release` creates a tag, publishes a public GitHub release, and starts `fork-notify`, which updates tracer's `main`. Local cache cleanup does not remove remote caches, artifacts, tags, or releases.

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
