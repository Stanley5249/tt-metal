#!/usr/bin/env bash
# Install a release's ttnn wheel the way tt-vllm-tracer does, outside the build
# tree, and run one op on ttsim. The fork workflow runs it once per arch.
#
# Usage: fork-smoke.sh <wh|bh> <dir with ttnn-*.whl>
# Run it under pixi exec with python 3.12, libhwloc, libnuma, mpc, and uv.
# The eval of sfpi-info.sh below sets the sfpi_* variables.
# shellcheck disable=SC2154
set -euo pipefail

arch=$1
wheel=$(echo "$(realpath "$2")"/ttnn-*.whl)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

uv venv -q --python "$(command -v python)" "$work/venv"
# The wheel lists no torch; tests and tt-vllm-tracer bring the CPU build.
uv pip install -q --python "$work/venv/bin/python" "$wheel" \
    torch --index https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match
root=$("$work/venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/ttnn/

# The SFPI kernel compiler that the wheel's tt-metal pins, through tt-metal's
# own helper, which reads sfpi-version next to itself.
cp "$root/tt_metal/tt-llk/tests/sfpi-info.sh" "$root/tt_metal/sfpi-version" "$work/"
eval "$(bash "$work/sfpi-info.sh" SHELL txz)"
curl -fsSL -o "$work/$sfpi_filename" "$sfpi_url/$sfpi_filename"
echo "$sfpi_hash  $work/$sfpi_filename" | sha256sum -c --quiet -
mkdir "$work/sfpi"
tar -xJf "$work/$sfpi_filename" -C "$work/sfpi" --strip-components=1

# The ttsim release that the wheel pins, checked against its release digest.
case $arch in
    wh) soc=wormhole_b0_80_arch.yaml ;;
    bh) soc=blackhole_140_arch.yaml ;;
esac
tag=$(tr -d '[:space:]' < "$root/tt_metal/ttsim-version")
asset=libttsim_$arch.so
hash=$(gh release view "$tag" -R tenstorrent/ttsim --json assets \
    -q ".assets[] | select(.name == \"$asset\") | .digest | ltrimstr(\"sha256:\")")
mkdir "$work/sim"
gh release download "$tag" -R tenstorrent/ttsim -p "$asset" -O "$work/sim/libttsim.so"
echo "$hash  $work/sim/libttsim.so" | sha256sum -c --quiet -
cp "$root/tt_metal/soc_descriptors/$soc" "$work/sim/soc_descriptor.yaml"

# tt-vllm-tracer's pixi activation, minus what only tracing needs.
export LD_LIBRARY_PATH=$CONDA_PREFIX/lib
export TT_METAL_RUNTIME_ROOT=$root
export TT_METAL_SFPI_ROOT=$work/sfpi
export TT_METAL_SIMULATOR=$work/sim/libttsim.so
export TT_METAL_SLOW_DISPATCH_MODE=1
export TT_METAL_DISABLE_SFPLOADMACRO=1
export TT_METAL_LOGS_PATH=$work/logs
cd "$work"
"$work/venv/bin/python" - <<'EOF'
import torch
import ttnn

device = ttnn.open_device(device_id=0)
try:
    a = torch.rand(32, 32, dtype=torch.bfloat16)
    t = ttnn.from_torch(a, layout=ttnn.TILE_LAYOUT, device=device)
    out = ttnn.to_torch(ttnn.add(t, t))
finally:
    ttnn.close_device(device)
torch.testing.assert_close(out, a + a)
print("ttnn.add matches torch on ttsim")
EOF
