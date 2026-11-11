// Host test of kernel_profiler::read_split_counter, the tear-free wall clock read that every
// profiler timestamp uses. Scripted register values put the low-half wrap at each point a
// device read could see it. Run with `just split-counter-test`.

#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#include "hostdev/split_counter.h"

namespace {

// Replays a scripted sequence of register values and records which half each read touched.
struct Script {
    std::vector<uint32_t> highs;
    std::vector<uint32_t> lows;
    size_t next_high = 0;
    size_t next_low = 0;
    std::string reads;

    uint32_t high() {
        reads += 'H';
        return highs.at(next_high++);
    }
    uint32_t low() {
        reads += 'L';
        return lows.at(next_low++);
    }
};

int failures = 0;

void check(const char* name, Script script, uint64_t expected, const std::string& expected_reads) {
    uint32_t high = 0;
    uint32_t low = 0;
    kernel_profiler::read_split_counter([&] { return script.high(); }, [&] { return script.low(); }, high, low);
    const uint64_t value = (static_cast<uint64_t>(high) << 32) | low;
    if (value != expected || script.reads != expected_reads) {
        std::printf(
            "FAIL %s: value 0x%llx, expected 0x%llx; reads %s, expected %s\n",
            name,
            static_cast<unsigned long long>(value),
            static_cast<unsigned long long>(expected),
            script.reads.c_str(),
            expected_reads.c_str());
        failures++;
    } else {
        std::printf("ok   %s\n", name);
    }
}

}  // namespace

int main() {
    // The counter does not wrap during the read: one high, one low, one high.
    check("no wrap", Script{{7, 7}, {0x1234}}, 0x0000'0007'0000'1234ULL, "HLH");
    // The low half wraps after the first high read: the first low already belongs to high 8, and
    // pairing it with high 7 would put the value 2^32 early, so the low half is read again.
    check("wrap between high and low", Script{{7, 8}, {0x0000'0003, 0x0000'0005}}, 0x0000'0008'0000'0005ULL, "HLHL");
    // The low half wraps after the low read: high 7 and low 0xFFFFFFF0 are a consistent pair, but
    // the second high differs, so the read retries and returns a later consistent pair.
    check("wrap between low and high", Script{{7, 8}, {0xFFFF'FFF0, 0x0000'0002}}, 0x0000'0008'0000'0002ULL, "HLHL");
    // A wrap of the high half itself, at 2^64, still pairs the retried halves.
    check("high half wraps", Script{{0xFFFF'FFFF, 0}, {0xFFFF'FFFF, 1}}, 0x0000'0000'0000'0001ULL, "HLHL");
    return failures == 0 ? 0 : 1;
}
