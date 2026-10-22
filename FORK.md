# Stanley5249/tt-metal

This fork of [tenstorrent/tt-metal](https://github.com/tenstorrent/tt-metal)
builds tt-metal with Tracy for ttsim in a sudo-free pixi environment. Releases
ship a ttnn wheel and Tracy tools. This file stays on the fork's two tracks.

## Branches

`stable` is the default branch, based on an upstream release tag. `nightly`
uses a selected nightly tag. Their upstream histories can diverge, so keep the
tracks independent and preserve published history. The fork has no `main`.

Merge upstream tags with a merge commit, then fast-forward the integration
branch to the exact validated candidate. Keep fork-owned changes focused,
preferably one commit per change, and fix published changes with follow-ups.

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

Develop on a `feat/*`, `fix/*`, or `ci/*` branch from stable and integrate there
first. Propagate changes to nightly in two ways:

- Infrastructure paths in `.github/fork-infra` stay identical on both tracks.
  On a task branch from nightly, run `.github/scripts/fork-infra.sh copy` to
  take stable's snapshot. Nightly's checks enforce equality with stable.
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

`fork-sync` prepares and fully validates candidates on a schedule or by hand.
Its workflow owns the schedule and inputs. Stable selects a published release;
nightly selects a published nightly tag. SFPI and ttsim follow that tag's pins.
Runs with no upstream update skip building and compiler cache access.

1. Review the candidate and exact commit in the Actions summary. Retire source
   patches when that track's upstream provides equivalent behavior.
2. For conflicts, run `.github/scripts/fork-sync.sh <stable|nightly> <tag>`
   locally, resolve and commit the merge, then rerun the command. It preserves
   source edits, aligns submodules, and reuses complete candidates. Commit or
   stash user edits first. Push the result and restart `fork-sync` for that
   track and tag to validate on GitHub Actions.
3. After validation and approval, run
   `git push origin <validated-sha>:refs/heads/<track>`. Check that validation
   identifies that exact commit. If the target moved and the push fails,
   prepare and validate a fresh candidate before retrying.
4. Start `fork-release` on the integration branch with `release` enabled. It
   validates again and drafts a release. Review and publish after approval;
   nightly releases are prereleases.

For build-only validation, start `fork-release` on the candidate with its
matching `track` and `release` disabled. It uses `conda.test` and Contents read
permission. Release numbering and write access belong to release preparation
and drafting. Keep local work to preparation and `just ci`; full builds and
simulator tests run on GitHub Actions.

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

- `fork-checks` runs `just ci`, including lightweight Git tests. After
  integration checks it disables upstream workflows, including newly added ones.
- `fork-update` prepares and pushes candidates with Contents write permission,
  then explicitly calls validation because token pushes may skip push workflows.
  Conflicts appear in the Actions summary and preparation log.
- `fork-validate` checks pins and nightly infrastructure, then builds and tests
  the clean wheel on both simulator architectures, including Tracy and device
  profiling. Build jobs use Contents read permission and save ccache on failure.
- `.github/scripts/fork-version.sh` owns upstream base validation and wheel
  version conversion for sync, validation, release, and local packaging. CI
  fetches upstream tags from tenstorrent because fork pushes carry none.
- `fork-release` counts drafts when choosing `conda.N`. Release notes use
  git-cliff and `.github/cliff.toml`; only matching integration branches can
  draft releases after validation.
- `fork-notify` sends published tags to `tt-vllm-tracer`; its `sync-metal`
  workflow owns dependency PRs. Only `fork-notify` reads `TRACER_DISPATCH_TOKEN`,
  scoped to tracer's Contents write permission.
  Dispatch with a tag to retry notification without rebuilding.

Keep upstream workflows in the tree but disabled in Actions. Use candidate
branches instead of internal PRs, and keep `main` absent, issues off, and
Dependabot off to avoid inherited triggers. Upstream schedules otherwise
queue for Tenstorrent's self-hosted runners on this fork.

## Side effects

The `justfile` and workflows own commands and cache settings. Use Actions logs
for current timings rather than fixed machine-specific measurements.

- Environments and builds write `.pixi/envs/`, `build_Release/`, its `build`
  symlink, and `runtime/`. Packaging writes `dist/` and `build_wheel/`.
- Downloads and caches use `sim/`, `~/.cache/cpm/`, and `~/.cache/ccache/`.
  Tests and traces write `generated/` and `~/.cache/tt-metal-cache/`.
- Tracy captures live under `build/profiler/build_wasm/traces/`. The viewer
  serves on ports 8080 and 8081 until stopped with `pkill -f serve_wasm.py`.
- Actions saves pixi environments, ccache with CPM sources, and test artifacts.

## Compared with upstream wheels

Upstream's `.github/workflows/wheels.yaml` builds with cibuildwheel in manylinux.
The fork's toolchain and runtime dependencies are defined in `pixi.toml`.

| Aspect                     | Upstream PyPI wheel  | Fork release wheel                 |
| -------------------------- | -------------------- | ---------------------------------- |
| Tracy                      | off                  | on                                 |
| Multihost MPI              | on, bundled          | off                                |
| SFPI compiler              | installed separately | bundled                            |
| tt_transformers' `models/` | requires a checkout  | bundled                            |
| Platform tag               | `manylinux`          | `linux_x86_64`, needs pixi runtime |
| Version                    | upstream tag         | upstream version plus `+conda.N`   |

## Releases

Tags use `<upstream-tag>-conda.N`; wheels use the same rebuild count as a
PEP 440 local version. `fork-version.sh` owns the conversion. The
[tt-vllm-tracer](https://github.com/Stanley5249/tt-vllm-tracer) project's
`pyproject.toml` and `docs/env-vars.md` describe consuming the release wheel.
