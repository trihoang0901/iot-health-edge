#include "CommandContract.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

namespace command_contract {

bool isCanonicalUuid(const char* value) {
  if (value == nullptr || strlen(value) != kUuidTextLength) {
    return false;
  }
  for (size_t index = 0; index < kUuidTextLength; ++index) {
    const bool separator = index == 8U || index == 13U || index == 18U || index == 23U;
    if (separator) {
      if (value[index] != '-') {
        return false;
      }
    } else if (!isxdigit(static_cast<unsigned char>(value[index]))) {
      return false;
    }
  }
  return true;
}

void formatUuidV4(const uint8_t entropy[16], char output[kUuidBufferBytes]) {
  uint8_t bytes[16] = {};
  if (entropy != nullptr) {
    memcpy(bytes, entropy, sizeof(bytes));
  }
  bytes[6] = static_cast<uint8_t>((bytes[6] & 0x0FU) | 0x40U);
  bytes[8] = static_cast<uint8_t>((bytes[8] & 0x3FU) | 0x80U);
  snprintf(output, kUuidBufferBytes,
           "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-"
           "%02x%02x%02x%02x%02x%02x",
           bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5],
           bytes[6], bytes[7], bytes[8], bytes[9], bytes[10], bytes[11],
           bytes[12], bytes[13], bytes[14], bytes[15]);
}

bool expiryIsFresh(uint32_t nowMs, uint32_t expiryMs,
                   uint32_t maximumFutureMs) {
  const int32_t remaining = static_cast<int32_t>(expiryMs - nowMs);
  return remaining >= 0 && static_cast<uint32_t>(remaining) <= maximumFutureMs;
}

}  // namespace command_contract
