# Recipes of the Stanley5249/tt-metal fork. They live on the fork branch with
# the other fork-owned files, and each channel merges that branch. A channel
# has pixi.toml and the tt-metal source; the fork branch has neither, so the
# recipes that need them only work on a channel. fork/README.md explains the
# branches.
#
# The formatters and linters touch only fork-owned files and pixi.toml, never
# upstream's: .oxfmtrc.json lists them for oxfmt, and ruff and pyrefly read fork/.

set minimum-version := "1.58.0"

# A git-ignored .env can override TT_BUILD_JOBS or any exported variable.
set dotenv-load
set unstable
set default-list

# quote(args) quotes each argument, instead of joining them into one.
set lists
set lazy
set ignore-comments

[unix]
set shell := ["bash", "-euo", "pipefail", "-c"]

channel := path_exists(justfile_directory() / "pixi.toml")

# Install the pixi environment and link the SOC descriptors beside ttsim
[group("setup")]
install:
    pixi install --locked
    pixi run --script fork/scripts/sync.py link-ttsim

# The defaults suit a 30 GB workstation; CI sets TT_BUILD_JOBS, CCACHE_MAXSIZE,
# and the cache folders instead. Unity builds of ttnn take several GB per job.
# ccache checks the compiler by content, because pixi install re-links clang
# when the other channel's lock installs, which the default mtime check misses.

# Build tt-metal with Tracy
[env("CCACHE_COMPILERCHECK", "content")]
[env("CMAKE_BUILD_PARALLEL_LEVEL", env("TT_BUILD_JOBS", "10"))]
[group("setup")]
build:
    pixi run --locked -e default ./build_metal.sh --enable-ccache --without-distributed \
        --cpm-source-cache {{ quote(env("CPM_SOURCE_CACHE", home_directory() / ".cache/cpm")) }} \
        --toolchain-path fork/cmake/x86_64-linux-clang-20-conda-toolchain.cmake

# Format Python, TOML, Markdown, YAML, JSON, and the justfile
[group("verify")]
[parallel]
fmt: _fmt-ruff _fmt-oxfmt _fmt-just

# Format, then apply automatic lint fixes
[group("verify")]
fix: fmt
    ruff check --fix fork

# pyrefly reads fork/pyrefly.toml, and runs inside a pixi exec environment that
# has the scripts' dependencies, because it takes the interpreter from PATH.

# Typecheck the fork's Python
[group("verify")]
[working-directory("fork")]
typecheck:
    pixi exec -s pyrefly -s "pydantic>=2" -s pytest pyrefly check --summary=none

# Lint Python and the fork workflows
[group("verify")]
[parallel]
lint: _lint-ruff _lint-actionlint _lint-zizmor

_lint-ruff:
    ruff check -q fork

_lint-actionlint:
    actionlint .github/workflows/fork-*.yaml

_lint-zizmor:
    zizmor -q --offline .github/workflows/fork-*.yaml

# Verify formatting, types, and lint, and on a channel pixi.lock and the fork-owned paths
[group("verify")]
[parallel]
check: _fmt-check typecheck lint _check-lock _check-infra

[parallel]
_fmt-check: (_fmt-ruff "--check") (_fmt-oxfmt "--check") (_fmt-just "--check")

_fmt-ruff flag="":
    ruff format -q {{ flag }} fork

# Use the latest oxfmt release because formatting needs no project dependencies.
_fmt-oxfmt flag="":
    bunx oxfmt@latest {{ flag }}

_fmt-just flag="":
    just --fmt {{ flag }}

_check-lock:
    {{ if channel == "true" { "pixi lock --check" } else { "" } }}

_check-infra:
    {{ if channel == "true" { "pixi run --script fork/scripts/sync.py check-infra" } else { "" } }}

# Run the script tests, and on a channel the C++ host tests; args go to pytest
[group("verify")]
test *args:
    pixi exec -s pytest -s "pydantic>=2" pytest -q fork/tests {{ quote(args) }}

# Run every source-preserving gate
[group("verify")]
[parallel]
ci: check test

# Build, package, and smoke-test HEAD on ttsim into dist/<tag>/ with notes.md to review; writes nothing remote
[group("release")]
release: build
    pixi run --script fork/scripts/release.py prepare

# Publish the release that `just release` prepared for HEAD, with its reviewed notes
[confirm("Publish the release prepared for HEAD on GitHub? (y/n)")]
[group("release")]
publish:
    pixi run --script fork/scripts/release.py publish
