"""Check the installed wheel's models, then run one ttnn op on ttsim against torch.

release.py runs this file in the pixi wheel environment after it installs the
wheel, from a folder outside the checkout, so `import ttnn` and `import models`
find the wheel instead of the checkout's folders.

The models check finds tt_transformers' modules without running them, because
model_config imports packages such as safetensors that the wheel environment
lacks. Stable ships them under models/tt_transformers. Since
v0.82.0-dev20261101 main ships them under models/ttt_compat and keeps
models/tt_transformers as an import alias with no files of its own, so the
check follows the old names to the files that implement them.
"""

import importlib.machinery
import importlib.util
import sys
import sysconfig
from pathlib import Path

# tt-scope imports these tt_transformers modules.
MODELS = "models.tt_transformers"
MODULES = ("tt.generator", "tt.generator_vllm", "tt.model_config")
# model_config resolves model parameters beside its own tt/ folder.
PARAMS = "model_params/Llama-3.2-1B-Instruct/config.json"


def origin(name: str) -> Path | None:
    """Return the file that implements module name, or None when it is missing."""
    parent, _, leaf = name.rpartition(".")
    try:
        # Finding name imports its parents, and an alias parent imports the real
        # package; the module itself does not run.
        if importlib.util.find_spec(name) is None:
            return None
    except ModuleNotFoundError:
        return None
    # The alias's spec has no origin, so search the real package's folders.
    spec = importlib.machinery.PathFinder.find_spec(leaf, sys.modules[parent].__path__)
    return Path(spec.origin).resolve() if spec and spec.origin else None


def check_models() -> list[str]:
    """Return an error for each module or parameter file missing from site-packages."""
    sites = [Path(sysconfig.get_path(key)).resolve() for key in ("purelib", "platlib")]
    errors = []
    for module in MODULES:
        name = f"{MODELS}.{module}"
        path = origin(name)
        if path is None:
            errors.append(f"{name} is missing")
        elif not any(path.is_relative_to(site) for site in sites):
            errors.append(f"{name} comes from {path}, not the installed wheel")
        elif module == "tt.model_config" and not (path.parents[1] / PARAMS).is_file():
            errors.append(f"{path.parents[1] / PARAMS} is missing")
        else:
            print(f"{name}: {path}")
    return errors


def run_op() -> None:
    """Add a tile to itself on device 0 and compare it with torch."""
    # Imported here, so the models check runs first. tt-scope imports
    # tt_transformers through models.common, which needs every package the
    # wheel ships beside ttnn.
    import models.common.utility_functions  # noqa: F401, PLC0415 -- the import is the check
    import torch  # noqa: PLC0415 -- after the models check
    import ttnn  # noqa: PLC0415 -- after the models check

    device = ttnn.open_device(device_id=0)
    try:
        a = torch.rand(32, 32, dtype=torch.bfloat16)
        t = ttnn.from_torch(a, layout=ttnn.TILE_LAYOUT, device=device)
        out = ttnn.to_torch(ttnn.add(t, t))
    finally:
        ttnn.close_device(device)
    torch.testing.assert_close(out, a + a)
    print("ttnn.add matches torch on ttsim")


if __name__ == "__main__":
    errors = check_models()
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        sys.exit(1)
    run_op()
