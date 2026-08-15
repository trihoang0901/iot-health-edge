#include "NetworkConfig.h"

#include <ctype.h>
#include <string.h>

namespace network {
namespace {

size_t boundedLength(const char* value, size_t capacity) {
  if (value == nullptr) {
    return capacity;
  }
  size_t length = 0;
  while (length < capacity && value[length] != '\0') {
    ++length;
  }
  return length;
}

bool generationIsNewer(uint32_t candidate, uint32_t reference) {
  return static_cast<int32_t>(candidate - reference) > 0;
}

bool hasLocalSuffix(const char* host, size_t length) {
  constexpr char suffix[] = ".local";
  constexpr size_t suffixLength = sizeof(suffix) - 1U;
  if (length < suffixLength) {
    return false;
  }
  for (size_t index = 0; index < suffixLength; ++index) {
    if (tolower(static_cast<unsigned char>(host[length - suffixLength + index])) !=
        suffix[index]) {
      return false;
    }
  }
  return true;
}

bool equalsIgnoreCase(const char* value, const char* expected, size_t length) {
  for (size_t index = 0; index < length; ++index) {
    if (tolower(static_cast<unsigned char>(value[index])) !=
        tolower(static_cast<unsigned char>(expected[index]))) {
      return false;
    }
  }
  return true;
}

bool validDnsName(const char* host, size_t length) {
  if (length == 0U || length > kMaxBrokerHostBytes || host[0] == '.' ||
      host[length - 1U] == '.' || hasLocalSuffix(host, length)) {
    return false;
  }

  size_t labelLength = 0;
  for (size_t index = 0; index < length; ++index) {
    const unsigned char value = static_cast<unsigned char>(host[index]);
    if (value == '.') {
      if (labelLength == 0U || labelLength > 63U || host[index - 1U] == '-') {
        return false;
      }
      labelLength = 0;
      continue;
    }
    if (!(isalnum(value) || value == '-')) {
      return false;
    }
    if (labelLength == 0U && value == '-') {
      return false;
    }
    ++labelLength;
  }
  if (labelLength == 0U || labelLength > 63U || host[length - 1U] == '-') {
    return false;
  }

  return !(length == 9U && equalsIgnoreCase(host, "localhost", 9U));
}

}  // namespace

uint32_t crc32(const uint8_t* data, size_t length) {
  uint32_t value = 0xFFFFFFFFUL;
  for (size_t index = 0; index < length; ++index) {
    value ^= data[index];
    for (uint8_t bit = 0; bit < 8U; ++bit) {
      const uint32_t mask = 0U - (value & 1U);
      value = (value >> 1U) ^ (0xEDB88320UL & mask);
    }
  }
  return ~value;
}

void sealRecord(NetworkRecord& record) {
  record.magic = kNetworkRecordMagic;
  record.schemaVersion = kNetworkSchemaVersion;
  record.config.schemaVersion = kNetworkSchemaVersion;
  record.crc32 = crc32(reinterpret_cast<const uint8_t*>(&record),
                       offsetof(NetworkRecord, crc32));
}

bool parseIpv4(const char* text, uint32_t& address) {
  address = 0;
  const size_t length = boundedLength(text, kIpv4TextBytes);
  if (length == 0U || length >= kIpv4TextBytes) {
    return false;
  }

  uint32_t result = 0;
  size_t position = 0;
  for (uint8_t octetIndex = 0; octetIndex < 4U; ++octetIndex) {
    if (position >= length || !isdigit(static_cast<unsigned char>(text[position]))) {
      return false;
    }
    uint16_t octet = 0;
    uint8_t digits = 0;
    while (position < length && isdigit(static_cast<unsigned char>(text[position]))) {
      octet = static_cast<uint16_t>(octet * 10U + (text[position] - '0'));
      if (octet > 255U || ++digits > 3U) {
        return false;
      }
      ++position;
    }
    result = (result << 8U) | octet;
    if (octetIndex < 3U) {
      if (position >= length || text[position] != '.') {
        return false;
      }
      ++position;
    }
  }
  if (position != length) {
    return false;
  }
  address = result;
  return true;
}

bool isUsableUnicastIpv4(uint32_t address) {
  const uint8_t first = static_cast<uint8_t>(address >> 24U);
  return address != 0U && address != 0xFFFFFFFFUL && first != 0U && first != 127U &&
         first < 224U;
}

bool fallbackMatchesSubnet(uint32_t fallback, uint32_t localAddress,
                           uint32_t subnetMask) {
  if (!isUsableUnicastIpv4(fallback) || !isUsableUnicastIpv4(localAddress) ||
      subnetMask == 0U || fallback == localAddress) {
    return false;
  }
  const uint32_t network = localAddress & subnetMask;
  const uint32_t broadcast = network | ~subnetMask;
  return (fallback & subnetMask) == network && fallback != network &&
         fallback != broadcast;
}

bool isValidBrokerHost(const char* host) {
  const size_t length = boundedLength(host, kMaxBrokerHostBytes + 1U);
  if (length == 0U || length > kMaxBrokerHostBytes || strstr(host, "://") != nullptr ||
      strchr(host, '/') != nullptr || strchr(host, ':') != nullptr) {
    return false;
  }

  uint32_t parsed = 0;
  if (parseIpv4(host, parsed)) {
    // Without a subnet mask a literal ending in .0/.255 is ambiguous. Reject
    // it conservatively here (the launcher applies the same bootstrap rule);
    // resolved addresses are checked again against the DHCP subnet at runtime.
    const uint8_t lastOctet = static_cast<uint8_t>(parsed);
    return isUsableUnicastIpv4(parsed) && lastOctet != 0U &&
           lastOctet != 255U;
  }
  return validDnsName(host, length);
}

bool validateConfig(const NetworkConfig& config) {
  if (config.schemaVersion != kNetworkSchemaVersion || config.brokerPort == 0U ||
      !isValidBrokerHost(config.brokerHost) || config.lastGoodProfile < -1 ||
      config.lastGoodProfile >= static_cast<int8_t>(kMaxWifiProfiles)) {
    return false;
  }

  size_t enabledCount = 0;
  for (size_t index = 0; index < kMaxWifiProfiles; ++index) {
    const WifiProfile& profile = config.profiles[index];
    if (profile.enabled > 1U || profile.priority >= kMaxWifiProfiles ||
        boundedLength(profile.ssid, sizeof(profile.ssid)) >= sizeof(profile.ssid) ||
        boundedLength(profile.password, sizeof(profile.password)) >=
            sizeof(profile.password) ||
        boundedLength(profile.fallbackIpv4, sizeof(profile.fallbackIpv4)) >=
            sizeof(profile.fallbackIpv4)) {
      return false;
    }
    if (profile.enabled == 0U) {
      continue;
    }
    const size_t ssidLength = strlen(profile.ssid);
    const size_t passwordLength = strlen(profile.password);
    if (ssidLength == 0U || ssidLength > kMaxSsidBytes || passwordLength < 8U ||
        passwordLength > kMaxWifiPasswordBytes) {
      return false;
    }
    if (profile.fallbackIpv4[0] != '\0') {
      uint32_t fallback = 0;
      if (!parseIpv4(profile.fallbackIpv4, fallback) || !isUsableUnicastIpv4(fallback)) {
        return false;
      }
    }
    for (size_t previous = 0; previous < index; ++previous) {
      if (config.profiles[previous].enabled != 0U &&
          strcmp(config.profiles[previous].ssid, profile.ssid) == 0) {
        return false;
      }
    }
    ++enabledCount;
  }
  return enabledCount > 0U;
}

bool validateRecord(const NetworkRecord& record) {
  if (record.magic != kNetworkRecordMagic ||
      record.schemaVersion != kNetworkSchemaVersion ||
      (record.state != static_cast<uint8_t>(RecordState::kCandidate) &&
       record.state != static_cast<uint8_t>(RecordState::kCommitted)) ||
      !validateConfig(record.config)) {
    return false;
  }
  return record.crc32 == crc32(reinterpret_cast<const uint8_t*>(&record),
                               offsetof(NetworkRecord, crc32));
}

int chooseCommittedRecord(const NetworkRecord records[2], const bool readable[2]) {
  int selected = -1;
  for (int index = 0; index < 2; ++index) {
    if (!readable[index] || !validateRecord(records[index]) ||
        records[index].state != static_cast<uint8_t>(RecordState::kCommitted)) {
      continue;
    }
    if (selected < 0 ||
        generationIsNewer(records[index].generation, records[selected].generation)) {
      selected = index;
    }
  }
  return selected;
}

}  // namespace network
