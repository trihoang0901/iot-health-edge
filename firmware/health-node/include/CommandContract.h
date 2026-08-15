#pragma once

#include <stddef.h>
#include <stdint.h>

namespace command_contract {

constexpr size_t kUuidTextLength = 36;
constexpr size_t kUuidBufferBytes = kUuidTextLength + 1U;

bool isCanonicalUuid(const char* value);
void formatUuidV4(const uint8_t entropy[16], char output[kUuidBufferBytes]);
bool expiryIsFresh(uint32_t nowMs, uint32_t expiryMs, uint32_t maximumFutureMs);

}  // namespace command_contract
