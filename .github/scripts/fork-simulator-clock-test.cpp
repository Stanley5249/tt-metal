// Host test of tt::tt_metal::simulator_tick_to_host_time, which places ttsim device markers on host time in Tracy.
// Run with `just simulator-clock-test`.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>

#include "simulator_clock.hpp"

namespace {

using tt::tt_metal::simulator_tick_to_host_time;
using tt::tt_metal::SimulatorClockSample;

int failures = 0;

void check(
    const char* name,
    const std::vector<SimulatorClockSample>& samples,
    uint64_t tick,
    double expected,
    bool expected_clamped) {
    bool clamped = !expected_clamped;
    const double host = simulator_tick_to_host_time(samples, tick, clamped);
    if (std::fabs(host - expected) > 1e-6 || clamped != expected_clamped) {
        std::printf(
            "FAIL %s: tick %llu gave host %f clamped %d, want %f clamped %d\n",
            name,
            static_cast<unsigned long long>(tick),
            host,
            clamped,
            expected,
            expected_clamped);
        failures++;
    }
}

}  // namespace

int main() {
    // A program polled for 100 ticks over 1000 host units, then a compile of 5000 host units with 3 ticks, then
    // another program of 50 ticks over 1000 host units.
    const std::vector<SimulatorClockSample> samples = {
        {1000, 10},
        {2000, 110},
        {7000, 113},
        {8000, 163},
    };

    check("first sample", samples, 10, 1000, false);
    check("between first samples", samples, 60, 1500, false);
    check("sample inside", samples, 110, 2000, false);
    check("frozen segment", samples, 112, 2000 + 5000.0 * 2 / 3, false);
    check("second program", samples, 138, 7500, false);
    check("last sample", samples, 163, 8000, false);
    check("before samples", samples, 3, 1000, true);
    check("after samples", samples, 500, 8000, true);

    const std::vector<SimulatorClockSample> one = {{42, 7}};
    check("one sample, at it", one, 7, 42, false);
    check("one sample, before it", one, 6, 42, true);
    check("one sample, after it", one, 8, 42, true);

    // The map is monotone: increasing ticks never map to earlier host times, so sorted markers stay sorted.
    double previous = 0;
    for (uint64_t tick = 0; tick < 200; tick++) {
        bool clamped = false;
        const double host = simulator_tick_to_host_time(samples, tick, clamped);
        if (host < previous) {
            std::printf("FAIL monotone: tick %llu went back in host time\n", static_cast<unsigned long long>(tick));
            failures++;
        }
        previous = host;
    }

    if (failures != 0) {
        return 1;
    }
    std::printf("simulator clock: all checks passed\n");
    return 0;
}
