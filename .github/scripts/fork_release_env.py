"""Print the environment table for a fork release's notes.

fork-release.yaml runs it in the pixi environment after the build and passes
the output to git-cliff as RELEASE_ENVIRONMENT; .github/cliff.toml places it::

    pixi run python .github/scripts/fork_release_env.py \\
        --tag v0.80.0-dev20260928-conda.1 --base v0.80.0-dev20260928

The table reads the checkout, pixi.lock's default environment, and the wheel
in dist/, so it matches a release only from that release's build.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
FORK = "https://github.com/Stanley5249/tt-metal"
TENSTORRENT = "https://github.com/tenstorrent"


def output(*command: str, cwd: Path = ROOT) -> str:
    """Return a command's stripped stdout, raising if it fails."""
    result = subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE, text=True)
    return result.stdout.strip()


def locked(*names: str) -> list[str]:
    """Return the locked versions of packages in the default environment."""
    packages = json.loads(output("pixi", "list", "--environment", "default", "--json"))
    versions = {package["name"]: package["version"] for package in packages}
    return [versions[name] for name in names]


def submodule(path: str) -> str:
    """Link a submodule's commit."""
    repo = ROOT / path
    url = output("git", "remote", "get-url", "origin", cwd=repo).removesuffix(".git")
    sha = output("git", "rev-parse", "HEAD", cwd=repo)
    return f"[`{sha[:7]}`]({url}/commit/{sha})"


def pinned(path: str, key: str) -> str:
    """Return a shell-style `key='value'` pin, or a bare version file's content."""
    text = (ROOT / path).read_text()
    match = re.search(rf"^{key}='([^']+)'", text, re.MULTILINE)
    return match[1] if match else text.strip()


def wheel() -> str:
    """Return the file name of the one wheel in dist/."""
    wheels = sorted((ROOT / "dist").glob("ttnn-*.whl"))
    if len(wheels) != 1:
        sys.exit(f"need one ttnn wheel in dist/, found {len(wheels)}")
    return wheels[0].name


def main() -> None:
    """Print the table and what a consumer needs."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--tag", required=True, help="the fork release tag")
    parser.add_argument("--base", required=True, help="the upstream tag it builds on")
    args = parser.parse_args()

    python, clang, libstdcxx, glibc = locked("python", "clang", "libstdcxx-devel_linux-64", "sysroot_linux-64")
    whl = wheel()
    ttsim = pinned("tt_metal/ttsim-version", "ttsim_version")
    sfpi = pinned("tt_metal/sfpi-version", "sfpi_version")
    rows = {
        "tt-metal": f"[{args.base}]({TENSTORRENT}/tt-metal/releases/tag/{args.base})"
        f" with the fork's branches; [FORK.md]({FORK}/blob/{args.tag}/FORK.md) lists them",
        "Tracy": "on; tt-metal's fork " + submodule("tt_metal/third_party/tracy"),
        "Wheel": f"[`{whl}`]({FORK}/releases/download/{args.tag}/{quote(whl)})",
        "Python": f"{python} (conda-forge)",
        "ttsim": f"[{ttsim}]({TENSTORRENT}/ttsim/releases/tag/{ttsim}), as upstream pins it",
        "SFPI": f"[{sfpi}]({TENSTORRENT}/sfpi/releases/tag/{sfpi}), not bundled",
        "Toolchain": f"clang {clang}, libstdc++ {libstdcxx} headers, glibc {glibc} sysroot",
    }
    table = "\n".join(
        ["| Item | Version |", "| --- | --- |"] + [f"| {item} | {version} |" for item, version in rows.items()]
    )
    print(f"""{table}

The wheel needs x86_64 Linux with glibc {glibc} or newer, Python 3.12, and
libnuma, libhwloc, and libmpc at runtime; this repo's pixi.toml provides them.""")


if __name__ == "__main__":
    main()
