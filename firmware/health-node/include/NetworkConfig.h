#pragma once

#include <stddef.h>
#include <stdint.h>

namespace network {

constexpr uint16_t kNetworkSchemaVersion = 1;
constexpr size_t kMaxWifiProfiles = 3;
constexpr size_t kMaxSsidBytes = 32;
constexpr size_t kMaxWifiPasswordBytes = 63;
constexpr size_t kMaxBrokerHostBytes = 95;
constexpr size_t kIpv4TextBytes = 16;
constexpr uint32_t kNetworkRecordMagic = 0x484E4554UL;  // "HNET"

enum class RecordState : uint8_t {
  kCandidate = 1,
  kCommitted = 2,
};

#pragma pack(push, 1)
struct WifiProfile {
  char ssid[kMaxSsidBytes + 1] = {};
  char password[kMaxWifiPasswordBytes + 1] = {};
  char fallbackIpv4[kIpv4TextBytes] = {};
  uint8_t enabled = 0;
  uint8_t priority = 0;
};

struct NetworkConfig {
  uint16_t schemaVersion = kNetworkSchemaVersion;
  uint16_t brokerPort = 1883;
  int8_t lastGoodProfile = -1;
  uint8_t reserved[3] = {};
  char brokerHost[kMaxBrokerHostBytes + 1] = {};
  WifiProfile profiles[kMaxWifiProfiles] = {};
};

struct NetworkRecord {
  uint32_t magic = kNetworkRecordMagic;
  uint16_t schemaVersion = kNetworkSchemaVersion;
  uint8_t state = static_cast<uint8_t>(RecordState::kCandidate);
  uint8_t reserved = 0;
  uint32_t generation = 0;
  NetworkConfig config;
  uint32_t crc32 = 0;
};
#pragma pack(pop)

uint32_t crc32(const uint8_t* data, size_t length);
void sealRecord(NetworkRecord& record);
bool validateRecord(const NetworkRecord& record);
bool validateConfig(const NetworkConfig& config);
int chooseCommittedRecord(const NetworkRecord records[2], const bool readable[2]);

bool parseIpv4(const char* text, uint32_t& address);
bool isUsableUnicastIpv4(uint32_t address);
bool fallbackMatchesSubnet(uint32_t fallback, uint32_t localAddress,
                           uint32_t subnetMask);
bool isValidBrokerHost(const char* host);

}  // namespace network
