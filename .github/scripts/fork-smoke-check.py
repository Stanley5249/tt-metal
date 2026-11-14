"""Check the device profiler logs that fork-smoke.py leaves under tracy.

Every FW and KERNEL zone must pair its start with an end on each core, RISC,
and run, and no two markers on one RISC may share a timestamp: the host merges
equal markers and pairs tied zones by marker id. With --noc, the NoC trace must
hold reads and multicast writes, and every NoC event must fall inside its
KERNEL zone. With --expect-quick-push, at least one RISC must have flushed its
buffer mid-kernel, which repeats its FW and KERNEL start markers for the host
to drop. With --tracy, the capture must place device zones on host time: no
KERNEL zone may overlap the host pause that fork-smoke.py marks, and some must
end before it and start after it.
With --log, tracy's console output must hold no warning that the profiler
dropped markers or gave up waiting for a flush.
"""

import argparse
import collections
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("logs", type=Path, help="tracy's .logs folder")
parser.add_argument("--noc", action="store_true", help="check the NoC trace too")
parser.add_argument("--expect-quick-push", action="store_true", help="require a mid-kernel flush")
parser.add_argument("--tracy", type=Path, help="check device zone placement in this .tracy capture")
parser.add_argument("--log", type=Path, help="tracy's console output, checked for profiler warnings")
args = parser.parse_args()

errors = []
with open(args.logs / "profile_log_device.csv", newline="") as f:
    next(f)  # ARCH line
    rows = list(csv.DictReader(f, skipinitialspace=True))

zones = collections.Counter()
kernels = collections.defaultdict(dict)
quick_pushes = set()
timestamps = collections.Counter()
for row in rows:
    key = (row["core_x"], row["core_y"], row["RISC processor type"], row["run host ID"], row["trace id counter"])
    name = row["zone name"]
    timestamps[key[:3], row["time[cycles since reset]"]] += 1
    if name.endswith(("-FW", "-KERNEL")):
        zones[key, name, row["type"]] += 1
        if name.endswith("-KERNEL"):
            kernels[key][row["type"]] = int(row["time[cycles since reset]"])
    elif name == "PROFILER-NOC-QUICK-PUSH":
        quick_pushes.add(key)

pairs = {(key, name) for key, name, _ in zones}
for key, name in sorted(pairs):
    starts, ends = zones[key, name, "ZONE_START"], zones[key, name, "ZONE_END"]
    if starts != 1 or ends != 1:
        errors.append(f"{name} on core {key[:2]} {key[2]} run {key[3]}: {starts} starts, {ends} ends")
if not pairs:
    errors.append("no FW or KERNEL zones")
print(f"{len(pairs)} FW and KERNEL zones, {len(quick_pushes)} RISCs flushed mid-kernel")

ties = sum(1 for count in timestamps.values() if count > 1)
if ties:
    errors.append(f"{ties} timestamps repeat on one core and RISC")

if args.expect_quick_push and not quick_pushes:
    errors.append("no PROFILER-NOC-QUICK-PUSH zone, so the mid-kernel flush went untested")

if args.noc:
    traces = sorted(args.logs.glob("noc_trace_dev*_ID*.json"))
    types = collections.Counter(e.get("type") for t in traces for e in json.loads(t.read_text()) if "type" in e)
    print(f"{len(traces)} NoC trace files: {dict(types)}")
    for needed in ("READ", "WRITE_MULTICAST"):
        if not types[needed]:
            errors.append(f"no {needed} event in the NoC traces")
    outside = 0
    for row in rows:
        if row["type"] != "TS_DATA":
            continue
        key = (row["core_x"], row["core_y"], row["RISC processor type"], row["run host ID"], row["trace id counter"])
        kernel = kernels.get(key, {})
        if not kernel.get("ZONE_START", 0) <= int(row["time[cycles since reset]"]) <= kernel.get("ZONE_END", -1):
            outside += 1
    if outside:
        errors.append(f"{outside} NoC events fall outside their KERNEL zone")


def tracy_rows(option, columns):
    """Export the capture with the tracy-csvexport under TT_METAL_HOME, one tuple per row.

    The exporter does not quote fields, and names can hold commas, so each row splits from the right.
    """
    exporter = Path(os.environ["TT_METAL_HOME"]) / "build/tools/profiler/bin/tracy-csvexport"
    out = subprocess.run([exporter, option, args.tracy], check=True, capture_output=True, text=True).stdout
    return [line.rsplit(",", columns - 1) for line in out.splitlines()[1:] if line.count(",") >= columns - 1]


if args.tracy:
    messages = {name: int(time) for name, time in tracy_rows("-m", 2) if time.isdigit()}
    pause_start = messages.get("fork-smoke: host pause start")
    pause_end = messages.get("fork-smoke: host pause end")
    kernels_on_host = [
        (int(start), int(length)) for name, _, start, length in tracy_rows("-g", 4) if name.endswith("-KERNEL")
    ]
    print(f"{len(kernels_on_host)} device KERNEL zones in the .tracy")
    if pause_start is None or pause_end is None:
        errors.append("no host pause messages in the .tracy")
    elif not kernels_on_host:
        errors.append("no device KERNEL zones in the .tracy")
    else:
        overlapping = sum(start < pause_end and start + length > pause_start for start, length in kernels_on_host)
        if overlapping:
            errors.append(f"{overlapping} KERNEL zones overlap the host pause, when ttsim ran no ticks")
        # The first add finishes before the pause and the held one runs after it, so device zones sit on both
        # sides; zones anchored at the profiler dump would all come after it.
        if not any(start + length <= pause_start for start, length in kernels_on_host):
            errors.append("no KERNEL zone ends before the host pause")
        if not any(start >= pause_end for start, _ in kernels_on_host):
            errors.append("no KERNEL zone starts after the host pause")
        if any(start < 0 for start, _ in kernels_on_host):
            errors.append("KERNEL zones start before the capture")

if args.log:
    for line in args.log.read_text(errors="replace").splitlines():
        if "markers were dropped" in line or "Device profiling never finished" in line:
            errors.append(f"profiler warning: {line.strip()}")

for error in errors:
    print(f"error: {error}", file=sys.stderr)
sys.exit(1 if errors else 0)
