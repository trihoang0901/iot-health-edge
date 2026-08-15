#include <assert.h>
#include <stdint.h>
#include <string.h>

#include <iostream>

#include "NetworkConfig.h"

namespace {

network::NetworkConfig validConfig() {
  network::NetworkConfig config;
  strcpy(config.brokerHost, "edge.example.test");
  config.brokerPort = 1883;
  config.lastGoodProfile = 0;
  strcpy(config.profiles[0].ssid, "closed-network");
  strcpy(config.profiles[0].password, "not-a-real-password");
  strcpy(config.profiles[0].fallbackIpv4, "192.168.10.10");
  config.profiles[0].enabled = 1;
  config.profiles[0].priority = 0;
  return config;
}

network::NetworkRecord record(network::RecordState state, uint32_t generation) {
  network::NetworkRecord result;
  result.state = static_cast<uint8_t>(state);
  result.generation = generation;
  result.config = validConfig();
  network::sealRecord(result);
  return result;
}

void testCrcRejectsPartialOrCorruptWrite() {
  network::NetworkRecord good = record(network::RecordState::kCommitted, 7U);
  assert(network::validateRecord(good));
  good.config.profiles[0].ssid[0] ^= 1;
  assert(!network::validateRecord(good));
}

void testBootIgnoresNewerCandidateAndKeepsCommitted() {
  network::NetworkRecord records[2] = {
      record(network::RecordState::kCommitted, 10U),
      record(network::RecordState::kCandidate, 11U),
  };
  const bool readable[2] = {true, true};
  assert(network::chooseCommittedRecord(records, readable) == 0);

  records[1] = record(network::RecordState::kCommitted, 12U);
  assert(network::chooseCommittedRecord(records, readable) == 1);
}

void testInterruptedPromotionFallsBackToOldCommitted() {
  network::NetworkRecord records[2] = {
      record(network::RecordState::kCommitted, 100U),
      record(network::RecordState::kCommitted, 101U),
  };
  records[1].crc32 ^= 0x1U;  // Simulates loss during replacement/promotion.
  const bool readable[2] = {true, true};
  assert(network::chooseCommittedRecord(records, readable) == 0);
}

void testConfigRejectsOpenDuplicateAndUnsafeBroker() {
  network::NetworkConfig config = validConfig();
  assert(network::validateConfig(config));

  config.profiles[0].password[0] = '\0';
  assert(!network::validateConfig(config));
  config = validConfig();
  config.profiles[1] = config.profiles[0];
  config.profiles[1].priority = 1;
  assert(!network::validateConfig(config));

  config = validConfig();
  strcpy(config.brokerHost, "http://192.168.10.10");
  assert(!network::validateConfig(config));
  strcpy(config.brokerHost, "127.0.0.1");
  assert(!network::validateConfig(config));
  strcpy(config.brokerHost, "LOCALHOST");
  assert(!network::validateConfig(config));
  strcpy(config.brokerHost, "broker.local");
  assert(!network::validateConfig(config));
  strcpy(config.brokerHost, "192.168.10.0");
  assert(!network::validateConfig(config));
  strcpy(config.brokerHost, "192.168.10.255");
  assert(!network::validateConfig(config));
}

void testIpv4AndFallbackSubnetPolicy() {
  uint32_t local = 0;
  uint32_t mask = 0;
  uint32_t sameSubnet = 0;
  uint32_t otherSubnet = 0;
  assert(network::parseIpv4("192.168.10.20", local));
  assert(network::parseIpv4("255.255.255.0", mask));
  assert(network::parseIpv4("192.168.10.8", sameSubnet));
  assert(network::parseIpv4("192.168.11.8", otherSubnet));
  assert(network::fallbackMatchesSubnet(sameSubnet, local, mask));
  assert(!network::fallbackMatchesSubnet(otherSubnet, local, mask));
  assert(!network::fallbackMatchesSubnet(local, local, mask));
  assert(!network::parseIpv4("192.168.1.999", otherSubnet));
}

}  // namespace

int main() {
  testCrcRejectsPartialOrCorruptWrite();
  testBootIgnoresNewerCandidateAndKeepsCommitted();
  testInterruptedPromotionFallsBackToOldCommitted();
  testConfigRejectsOpenDuplicateAndUnsafeBroker();
  testIpv4AndFallbackSubnetPolicy();
  std::cout << "NetworkConfig tests passed\n";
  return 0;
}
