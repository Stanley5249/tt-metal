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
tracy_asset := "tracy-tools-linux_x86_64.tar.gz"
ttsim_repo := "tenstorrent/ttsim"

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

# Download the ttsim library that tt_metal/ttsim-version pins into sim/
[arg("arch", long, pattern="wh|bh|", help="wh: Wormhole, bh: Blackhole; by default the arch already in sim/, else wh")]
[group("setup")]
[script]
fetch-ttsim arch="":
    tag=$(tr -d '[:space:]' < tt_metal/ttsim-version)
    # test and trace call this without an arch, so they keep the one in sim/.
    arch={{ arch }}
    if [ -z "$arch" ]; then
        arch=$(cut -d' ' -f2 sim/.version 2>/dev/null || true)
        arch=${arch:-wh}
    fi
    case $arch in
        wh) soc=wormhole_b0_80_arch.yaml ;;
        bh) soc=blackhole_140_arch.yaml ;;
    esac
    # .version names the release and arch in sim/, so a rerun downloads nothing.
    if [ "$(cat sim/.version 2>/dev/null)" = "$tag $arch" ]; then
        exit 0
    fi
    # GitHub records a sha256 digest for each release asset, which upstream's
    # tt-llk/tests/run_ttsim_regression.sh also checks against.
    asset=libttsim_$arch.so
    # A GH_TOKEN lifts the API's anonymous rate limit, which CI runners share.
    hash=$(curl -fsSL ${GH_TOKEN:+-H "Authorization: Bearer $GH_TOKEN"} \
        "https://api.github.com/repos/{{ ttsim_repo }}/releases/tags/$tag" |
        ASSET=$asset python3 -c '
    import json, os, sys
    for a in json.load(sys.stdin)["assets"]:
        if a["name"] == os.environ["ASSET"]:
            print(a["digest"].removeprefix("sha256:"))
    ')
    if [ -z "$hash" ]; then
        echo "no sha256 digest for $asset in ttsim $tag" >&2
        exit 1
    fi
    mkdir -p sim
    # Verify before replacing, so a bad download never reaches TT_METAL_SIMULATOR.
    curl -fsSL -o sim/libttsim.so.part "https://github.com/{{ ttsim_repo }}/releases/download/$tag/$asset"
    echo "$hash  sim/libttsim.so.part" | sha256sum -c --quiet -
    mv sim/libttsim.so.part sim/libttsim.so
    cp "tt_metal/soc_descriptors/$soc" sim/soc_descriptor.yaml
    echo "$tag $arch" > sim/.version

# Run pytest on ttsim; args go to pytest
[group("test")]
[positional-arguments]
test *args: fetch-ttsim
    pixi run pytest "$@"

# Profile a Python script on ttsim with Tracy and the device profiler; args go to the script
[group("test")]
[positional-arguments]
trace script *args: fetch-ttsim
    pixi run python -m tracy -p -r "$@"

# Package the current build as a ttnn wheel in dist/; label becomes the local version, such as conda.1
[arg("label", long, help="PEP 440 local version label")]
[group("release")]
[script]
wheel label="":
    # The upstream tag, such as v0.80.0-dev20260928, becomes 0.80.0.dev20260928.
    # --exclude skips tags with a suffix, such as a fork's v0.80.0-dev20260928-conda.1.
    tag=$(git describe --tags --abbrev=0 --match 'v[0-9]*-dev[0-9]*' --exclude 'v*-*-*')
    version="${tag#v}"
    version="${version/-dev/.dev}"
    if [ -n "{{ label }}" ]; then
        version="$version+{{ label }}"
    fi
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

# Package the Tracy tools and WASM viewer from the current build in dist/
[group("release")]
[script]
tracy-tools:
    mkdir -p "{{ dist_dir }}"
    # Paths stay as in the source tree, where tt-metal's tracy module looks
    # for them under TT_METAL_HOME.
    wasm=build/profiler/build_wasm
    tar -czf "{{ dist_dir }}/{{ tracy_asset }}" \
        build/tools/profiler/bin \
        "$wasm/index.html" "$wasm/favicon.svg" "$wasm/tracy-profiler.js" "$wasm/tracy-profiler.wasm"
    ls -l "{{ dist_dir }}/{{ tracy_asset }}"

# Format pixi.toml and the justfile
[group("verify")]
fmt:
    pixi run tombi format pixi.toml
    just --fmt

# Verify formatting and pixi.lock without rewriting sources
[group("verify")]
ci:
    pixi lock --check --dry-run
    pixi run tombi format --check pixi.toml
    pixi run tombi lint pixi.toml
    just --fmt --check
