set minimum-version := "1.58.0"
set unstable
set default-list

# A git-ignored .env can override TT_BUILD_JOBS or any exported variable.
set dotenv-load
set ignore-comments
set shell := ["bash", "-euo", "pipefail", "-c"]
set script-interpreter := ["bash", "-euo", "pipefail"]

# Unity builds of ttnn take several GB per job; a high count can run a
# workstation out of memory.
build_jobs := env("TT_BUILD_JOBS", "10")
cpm_cache := home_directory() / ".cache/cpm"
dist_dir := justfile_directory() / "dist"
wheel_work := justfile_directory() / "build_wheel"

# Fail instead of re-solving when pixi.lock is out of date; run `pixi lock` after a manifest change.
export PIXI_LOCKED := "true"

# Install the pixi environment
[group("setup")]
install:
    pixi install

# Build tt-metal with Tracy; args go to build_metal.sh
[env("CMAKE_BUILD_PARALLEL_LEVEL", build_jobs)]
[group("setup")]
[positional-arguments]
build *args:
    pixi run ./build_metal.sh --enable-ccache --without-distributed \
        --cpm-source-cache "{{ cpm_cache }}" \
        --toolchain-path cmake/x86_64-linux-clang-20-conda-toolchain.cmake "$@"

# UMD reads soc_descriptor.yaml beside TT_METAL_SIMULATOR. This tree owns the
# descriptor, because real hardware reads the same files, and the ttsim package
# ships none. A new symlink in the environment joins them; it never writes
# through a package file, which can be a hard link into pixi's cache.

# Link this tree's SOC descriptor beside the ttsim library; TTSIM_ARCH=bh selects Blackhole
[group("setup")]
[script]
link-ttsim:
    sim=$(pixi run printenv TT_METAL_SIMULATOR)
    case $(basename "$sim") in
        libttsim_wh.so) soc=wormhole_b0_80_arch.yaml ;;
        libttsim_bh.so) soc=blackhole_140_arch.yaml ;;
        *)
            echo "no SOC descriptor for TT_METAL_SIMULATOR=$sim" >&2
            exit 1
            ;;
    esac
    desc="{{ justfile_directory() }}/tt_metal/soc_descriptors/$soc"
    link=$(dirname "$sim")/soc_descriptor.yaml
    # ln -f removes the link first, which a running test could trip on.
    [ "$(readlink "$link")" = "$desc" ] || ln -sf "$desc" "$link"

# Run pytest on ttsim; args go to pytest
[group("test")]
[positional-arguments]
test *args: link-ttsim
    pixi run pytest "$@"

# Profile a Python script on ttsim with Tracy and the device profiler; args go to the script
[group("test")]
[positional-arguments]
trace script *args: link-ttsim
    pixi run python -m tracy -p -r "$@"

# Package the current build as a ttnn wheel in dist/; label becomes the local version, such as conda.1
[arg("label", long, help="PEP 440 local version label")]
[group("release")]
[script]
wheel label="":
    metadata=$(bash .github/scripts/fork-version.sh auto HEAD "{{ label }}")
    version=$(printf '%s\n' "$metadata" | awk -F= '$1 == "version" {print $2}')
    # One wheel in dist/, so a release picks the right one.
    rm -rf "{{ wheel_work }}" "{{ dist_dir }}"/ttnn-*.whl
    mkdir -p "{{ dist_dir }}" "{{ wheel_work }}"
    # setuptools writes into build/, which links to build_Release.
    printf '[build]\nbuild_base = %s\n[egg_info]\negg_base = %s\n' \
        "{{ wheel_work }}/build" "{{ wheel_work }}" > "{{ wheel_work }}/setup.cfg"
    # Package the existing build instead of compiling it again. uv installs
    # tt-metal's build-system requirements in isolation and builds for the
    # environment's Python, which ttnn was compiled against.
    TT_FROM_PRECOMPILED_DIR="$PWD" SETUPTOOLS_SCM_PRETEND_VERSION="$version" \
        DIST_EXTRA_CONFIG="{{ wheel_work }}/setup.cfg" \
        pixi run uv build --wheel --python "$(pixi run which python)" --out-dir "{{ dist_dir }}" .
    ls -l "{{ dist_dir }}"

# Format pixi.toml and the justfile
[group("verify")]
fmt:
    pixi run -e ci tombi format pixi.toml
    just --fmt

# Build and run the host test of the profiler's tear-free wall clock read
[group("verify")]
[script]
split-counter-test:
    out=$(mktemp -d)
    trap 'rm -rf "$out"' EXIT
    pixi run clang++ -std=c++17 -Wall -Werror -I tt_metal/hw/inc \
        .github/scripts/fork-split-counter-test.cpp -o "$out/split-counter-test"
    "$out/split-counter-test"

# Build and run the host test of the ttsim tick-to-host-time map that places device zones in Tracy
[group("verify")]
[script]
simulator-clock-test:
    out=$(mktemp -d)
    trap 'rm -rf "$out"' EXIT
    pixi run clang++ -std=c++17 -Wall -Werror -I tt_metal/impl/profiler \
        .github/scripts/fork-simulator-clock-test.cpp -o "$out/simulator-clock-test"
    "$out/simulator-clock-test"

# Verify formatting, pixi.lock, and the fork workflows without rewriting sources
[group("verify")]
ci:
    pixi lock --check --dry-run
    pixi run -e ci tombi format --check pixi.toml
    pixi run -e ci tombi lint pixi.toml
    just --fmt --check
    pixi run -e ci actionlint .github/workflows/fork-*.yaml
    pixi run -e ci zizmor --offline .github/workflows/fork-*.yaml
    pixi run -e ci shellcheck .github/scripts/fork-*.sh
    pixi run -e ci uv run --no-project python .github/scripts/fork-sync-test.py
    pixi run -e ci uv run --no-project python .github/scripts/fork-release-test.py
    pixi run -e ci uv run --no-project python .github/scripts/fork-models-check-test.py
