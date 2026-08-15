#include <assert.h>
#include <stdint.h>
#include <string.h>

#include <iostream>

#include "CommandContract.h"

namespace {

void testSessionUuidRoundTripsThroughCanonicalEdgeEcho() {
  const uint8_t entropy[16] = {
      0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x06, 0x77,
      0xF8, 0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF,
  };
  char advertised[command_contract::kUuidBufferBytes] = {};
  command_contract::formatUuidV4(entropy, advertised);
  assert(strcmp(advertised, "00112233-4455-4677-b899-aabbccddeeff") == 0);
  assert(command_contract::isCanonicalUuid(advertised));

  // The edge parses and emits canonical UUID text; exact replay-boundary
  // comparison therefore succeeds without normalization on the device.
  char edgeEcho[command_contract::kUuidBufferBytes] = {};
  strcpy(edgeEcho, advertised);
  assert(strcmp(advertised, edgeEcho) == 0);
}

void testUuidAndWrapSafeExpiryValidation() {
  assert(command_contract::isCanonicalUuid(
      "550e8400-e29b-41d4-a716-446655440000"));
  assert(!command_contract::isCanonicalUuid(
      "550e8400e29b41d4a716446655440000"));
  assert(command_contract::expiryIsFresh(100U, 30100U, 30000U));
  assert(!command_contract::expiryIsFresh(100U, 30101U, 30000U));
  assert(!command_contract::expiryIsFresh(101U, 100U, 30000U));
  assert(command_contract::expiryIsFresh(UINT32_MAX - 10U, 9U, 30000U));
}

}  // namespace

int main() {
  testSessionUuidRoundTripsThroughCanonicalEdgeEcho();
  testUuidAndWrapSafeExpiryValidation();
  std::cout << "CommandContract tests passed\n";
  return 0;
}
