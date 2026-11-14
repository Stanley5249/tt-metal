// SPDX-FileCopyrightText: © 2026 Tenstorrent USA, Inc.
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <algorithm>
#include <cstdint>
#include <vector>

namespace tt::tt_metal {

// TT-SIM-PROFILER-SYNC: ttsim's clock advances only when the host reads the device, so its ticks have no fixed rate
// in host time. The profiler samples the clock with the host time at dispatch and profiler-read boundaries, and Tracy
// places simulator markers on host time by interpolating between those samples.
struct SimulatorClockSample {
    int64_t host_time;     // TracyGetCpuTime() units
    uint64_t device_time;  // simulator wall clock ticks
};

// Host time of a simulator tick, interpolated linearly between the samples around it. Samples must be sorted with
// strictly increasing device times and at least one entry. A tick outside the samples takes the nearest sample's host
// time and sets clamped.
inline double simulator_tick_to_host_time(
    const std::vector<SimulatorClockSample>& samples, uint64_t device_time, bool& clamped) {
    const SimulatorClockSample& first = samples.front();
    const SimulatorClockSample& last = samples.back();
    clamped = device_time < first.device_time || device_time > last.device_time;
    if (device_time <= first.device_time) {
        return static_cast<double>(first.host_time);
    }
    if (device_time >= last.device_time) {
        return static_cast<double>(last.host_time);
    }
    const auto after = std::upper_bound(
        samples.begin(), samples.end(), device_time, [](uint64_t time, const SimulatorClockSample& sample) {
            return time < sample.device_time;
        });
    const SimulatorClockSample& before = *(after - 1);
    const double fraction = static_cast<double>(device_time - before.device_time) /
                            static_cast<double>(after->device_time - before.device_time);
    return static_cast<double>(before.host_time) + fraction * static_cast<double>(after->host_time - before.host_time);
}

// Hardware extrapolates with the chip's open sync slope, rather than freezing outside the samples.
inline double hardware_tick_to_host_time(
    const std::vector<SimulatorClockSample>& samples, uint64_t tick, double host_per_tick) {
    const auto& anchor = tick < samples.front().device_time ? samples.front() : samples.back();
    if (tick <= samples.front().device_time || tick >= samples.back().device_time) {
        return anchor.host_time + (static_cast<double>(tick) - anchor.device_time) * host_per_tick;
    }
    bool clamped = false;
    return simulator_tick_to_host_time(samples, tick, clamped);
}

}  // namespace tt::tt_metal
