"""Check that the installed wheel ships the tt_transformers modules and model
parameters that tt-vllm-tracer imports.

fork-validate's smoke job runs it as a file after installing the wheel, so the
checkout's models/ folder cannot answer for the wheel. It finds the modules
without running them, because model_config imports packages such as
safetensors that the wheel environment lacks.

Stable ships the implementation under models/tt_transformers. Since
v0.82.0-dev20261101 nightly ships it under models/ttt_compat and keeps
models/tt_transformers as an import alias with no files of its own, so the
check follows the old names to the files that implement them.
"""

import argparse
import importlib
import importlib.machinery
import importlib.util
import sys
import sysconfig
from pathlib import Path

PACKAGE = "models.tt_transformers"
MODULES = ("tt.generator", "tt.generator_vllm", "tt.model_config")
# model_config resolves model parameters beside its own tt/ folder.
PARAMS = "model_params/Llama-3.2-1B-Instruct/config.json"


def origin(name):
    """Return the file that implements module `name`, or None when it is missing."""
    parent, _, leaf = name.rpartition(".")
    try:
        # Finding `name` imports its parents, and an alias parent imports the real
        # package; the module itself does not run.
        if importlib.util.find_spec(name) is None:
            return None
    except ModuleNotFoundError:
        return None
    # The alias's spec has no origin, so search the real package's folders.
    spec = importlib.machinery.PathFinder.find_spec(leaf, sys.modules[parent].__path__)
    return Path(spec.origin).resolve() if spec and spec.origin else None


def check(sites):
    """Return an error for each module or parameter file missing from `sites`."""
    errors = []
    for module in MODULES:
        name = f"{PACKAGE}.{module}"
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--site",
        type=Path,
        action="append",
        help="folder the modules must come from; by default the environment's site-packages",
    )
    args = parser.parse_args()
    sites = args.site or [Path(sysconfig.get_path(key)) for key in ("purelib", "platlib")]
    errors = check([site.resolve() for site in sites])
    for error in errors:
        print(error, file=sys.stderr)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
