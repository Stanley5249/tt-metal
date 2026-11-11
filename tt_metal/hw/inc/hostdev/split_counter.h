// SPDX-FileCopyrightText: © 2026 Tenstorrent USA, Inc.
//
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>

namespace kernel_profiler {

// Reads a 64-bit counter that the hardware exposes as two live 32-bit halves, without tearing.
// Reading high then low alone can pair an old high half with a low half that has just wrapped,
// which puts the value 2^32 early. The high half is read again after the low half; if it changed,
// the low half wrapped in between, so the low half is read again and paired with the new high half.
// A second wrap would need 2^32 more counts, so the retried pair is consistent. This needs no latch,
// so it holds on every Tensix generation and on ttsim.
template <typename ReadHigh, typename ReadLow>
inline __attribute__((always_inline)) void read_split_counter(
    ReadHigh read_high, ReadLow read_low, uint32_t& high, uint32_t& low) {
    high = read_high();
    low = read_low();
    const uint32_t high_again = read_high();
    if (high_again != high) {
        high = high_again;
        low = read_low();
    }
}

}  // namespace kernel_profiler
