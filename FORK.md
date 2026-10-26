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

Develop on a `feat/*`, `fix/*`, `refactor/*`, or `ci/*` branch from stable and
integrate there first. Propagate changes to nightly in two ways:

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
Stable selects a published release; nightly selects a published nightly tag.
SFPI and ttsim follow that tag's pins.
Runs with no upstream update skip building and compiler cache access.

When upstream changes files in `.github/workflows/`, GitHub's built-in
`GITHUB_TOKEN` cannot push the candidate. Configure the repository Actions
secret `FORK_SYNC_TOKEN` with a fine-grained personal access token restricted
to `Stanley5249/tt-metal`, granting **Contents: read and write** and
**Workflows: read and write**. Metadata read access is implicit. Set an
expiration and rotate the secret before it expires. Do not reuse the tracer's
`TRACER_DISPATCH_TOKEN`, which belongs to another repository.

Only the candidate push reads `FORK_SYNC_TOKEN`; preparation and validation
keep their built-in tokens. Without it, updates that do not change workflows
still work, while workflow changes fail with a setup message before pushing.
Unlike built-in-token pushes, personal-token pushes can trigger push workflows;
keep upstream workflows disabled as described below. The explicit validation
still runs, and integration branches are never promoted automatically.

1. Review the candidate and exact commit in the Actions summary. Retire source
   patches when that track's upstream provides equivalent behavior.
2. For conflicts, run `.github/scripts/fork-sync.sh <stable|nightly> <tag>`
   locally, resolve and commit the merge, then rerun the command. It preserves
   source edits, aligns submodules, and resumes an existing candidate branch.
   Commit or stash user edits first. Push the result and restart `fork-sync`
   for that track and tag to validate on GitHub Actions.
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

- `fork-checks` runs `just ci`, which includes `fork-sync-test.py`. On nightly
  it also runs `fork-infra.sh check`. On stable and nightly it then disables
  upstream workflows, including newly added ones.
- `fork-update` prepares and pushes candidates with Contents write permission,
  then explicitly calls validation because token pushes may skip push workflows.
  Conflicts appear in the Actions summary and preparation log.
- `fork-validate` checks pins and nightly infrastructure, then builds and tests
  the clean wheel on both simulator architectures, including Tracy and device
  profiling. Build jobs use Contents read permission and save ccache on failure.
- `fork-select-tag.sh` picks and validates a track's upstream tag.
  `fork-version.sh` checks the upstream base and derives the wheel version. CI
  fetches upstream tags from tenstorrent because fork pushes carry none.
- `fork-release` counts drafts when choosing `conda.N`. Release notes use
  git-cliff and `.github/cliff.toml`; only matching integration branches can
  draft releases after validation.
- `fork-notify` dispatches `tt-metal-released` to `tt-vllm-tracer`, whose
  `sync-metal` workflow opens the dependency PR. Only `fork-notify` reads
  `TRACER_DISPATCH_TOKEN`, scoped to tracer's Contents write permission.
  Dispatch it with a tag to retry without rebuilding.

Upstream workflows stay in the tree, and `disable-upstream` keeps them off,
because their schedules would queue for Tenstorrent's self-hosted runners. Use
candidate branches instead of internal PRs, and keep `main` absent, issues off,
and Dependabot off to avoid inherited triggers.

## Side effects

Sizes are from one local build. A cold `just build` takes about 32 min locally
and 47 min on a runner; with a warm ccache the runner compiles in about 4 min.

| Path                                     | Written by                       | Size   |
| ---------------------------------------- | -------------------------------- | ------ |
| `.pixi/envs/`                            | any recipe                       | 2.9 GB |
| `build_Release/`, `build` linking to it  | `just build`                     | 2.3 GB |
| `runtime/`                               | `just build`                     | 0.4 GB |
| `~/.cache/cpm/`                          | `just build`                     | 4.0 GB |
| `~/.cache/ccache/`                       | `just build`                     | 0.6 GB |
| `sim/`                                   | `just fetch-ttsim`               | < 1 MB |
| `generated/`, `~/.cache/tt-metal-cache/` | `just test`, `just trace`        | 2 GB   |
| `dist/`, `build_wheel/`                  | `just wheel`, `just tracy-tools` | 0.4 GB |

Tracy captures go to `build/profiler/build_wasm/traces/`. The viewer serves on
ports 8080 and 8081 until `pkill -f serve_wasm.py`. Actions caches the pixi
environments and ccache with CPM sources.

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

Tags use `<upstream-tag>-conda.N`. The wheel adds `+conda.N` as a PEP 440 local
version and writes `-dev` as `.dev`. The
[tt-vllm-tracer](https://github.com/Stanley5249/tt-vllm-tracer) project's
`pyproject.toml` and `docs/env-vars.md` describe consuming the release wheel.
