"""Compile and run the C++ host tests that a channel keeps beside its profiler source.

They test fork math, so they run in seconds without a build, but they need the
channel's source and its default environment's clang. The fork branch has
neither.
"""

import subprocess
from pathlib import Path

import pytest
from sync import activated

ROOT = Path(__file__).parents[2]
TESTS = ("tt_metal/impl/profiler/split_counter_test.cpp", "tt_metal/impl/profiler/simulator_clock_test.cpp")


@pytest.mark.skipif(not (ROOT / "pixi.toml").is_file(), reason="needs a channel's source and pixi environment")
@pytest.mark.parametrize("source", TESTS)
def test_host(source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    binary = tmp_path / "test"
    # The environment's clang, started directly with its activation.
    env = activated("default")
    command = ["clang++", "-std=c++17", "-Wall", "-Werror", "-I", "tt_metal/hw/inc", source, "-o", str(binary)]
    subprocess.run(command, env=env, check=True)
    subprocess.run([binary], check=True)
