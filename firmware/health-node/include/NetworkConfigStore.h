#pragma once

#include <stdint.h>

#include "NetworkConfig.h"

namespace network {

class NetworkConfigStore {
 public:
  bool begin();
  bool mounted() const;
  bool loadCommitted(NetworkRecord& record);
  bool writeCandidate(const NetworkConfig& config, NetworkRecord& record);
  bool promoteCandidate(NetworkRecord& record);
  bool writeCommitted(const NetworkConfig& config, NetworkRecord& record);

 private:
  bool readSlot(uint8_t slot, NetworkRecord& record) const;
  bool writeSlotAtomically(uint8_t slot, const NetworkRecord& record) const;
  uint32_t nextGeneration() const;
  uint8_t inactiveSlot() const;

  bool mounted_ = false;
  int8_t activeCommittedSlot_ = -1;
  int8_t candidateSlot_ = -1;
};

}  // namespace network
