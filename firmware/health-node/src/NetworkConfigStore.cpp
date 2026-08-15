#include "NetworkConfigStore.h"

#include <LittleFS.h>

namespace network {
namespace {

constexpr const char* kSlotPaths[2] = {"/network-a.bin", "/network-b.bin"};
constexpr const char* kTempPaths[2] = {"/network-a.tmp", "/network-b.tmp"};

bool generationIsNewer(uint32_t candidate, uint32_t reference) {
  return static_cast<int32_t>(candidate - reference) > 0;
}

}  // namespace

bool NetworkConfigStore::begin() {
  LittleFSConfig filesystemConfig(false);
  if (!LittleFS.setConfig(filesystemConfig)) {
    return false;
  }
  mounted_ = LittleFS.begin();
  return mounted_;
}

bool NetworkConfigStore::mounted() const {
  return mounted_;
}

bool NetworkConfigStore::readSlot(uint8_t slot, NetworkRecord& record) const {
  if (!mounted_ || slot >= 2U) {
    return false;
  }
  File file = LittleFS.open(kSlotPaths[slot], "r");
  if (!file || file.size() != sizeof(record)) {
    return false;
  }
  const size_t bytesRead = file.read(reinterpret_cast<uint8_t*>(&record), sizeof(record));
  file.close();
  return bytesRead == sizeof(record) && validateRecord(record);
}

bool NetworkConfigStore::loadCommitted(NetworkRecord& record) {
  NetworkRecord records[2] = {};
  bool readable[2] = {readSlot(0, records[0]), readSlot(1, records[1])};
  const int selected = chooseCommittedRecord(records, readable);
  if (selected < 0) {
    activeCommittedSlot_ = -1;
    return false;
  }
  activeCommittedSlot_ = static_cast<int8_t>(selected);
  record = records[selected];
  return true;
}

uint32_t NetworkConfigStore::nextGeneration() const {
  uint32_t highest = 0;
  bool found = false;
  for (uint8_t slot = 0; slot < 2U; ++slot) {
    NetworkRecord record = {};
    if (!readSlot(slot, record)) {
      continue;
    }
    if (!found || generationIsNewer(record.generation, highest)) {
      highest = record.generation;
      found = true;
    }
  }
  return found ? highest + 1U : 1U;
}

uint8_t NetworkConfigStore::inactiveSlot() const {
  if (activeCommittedSlot_ == 0) {
    return 1U;
  }
  if (activeCommittedSlot_ == 1) {
    return 0U;
  }
  return 0U;
}

bool NetworkConfigStore::writeSlotAtomically(uint8_t slot,
                                             const NetworkRecord& record) const {
  if (!mounted_ || slot >= 2U) {
    return false;
  }

  LittleFS.remove(kTempPaths[slot]);
  File temporary = LittleFS.open(kTempPaths[slot], "w");
  if (!temporary) {
    return false;
  }
  const size_t bytesWritten =
      temporary.write(reinterpret_cast<const uint8_t*>(&record), sizeof(record));
  temporary.flush();
  temporary.close();
  if (bytesWritten != sizeof(record)) {
    LittleFS.remove(kTempPaths[slot]);
    return false;
  }

  NetworkRecord verification = {};
  File verifyFile = LittleFS.open(kTempPaths[slot], "r");
  const bool verified = verifyFile && verifyFile.size() == sizeof(verification) &&
                        verifyFile.read(reinterpret_cast<uint8_t*>(&verification),
                                        sizeof(verification)) == sizeof(verification) &&
                        validateRecord(verification);
  verifyFile.close();
  if (!verified) {
    LittleFS.remove(kTempPaths[slot]);
    return false;
  }

  // This is always the inactive slot (or the candidate slot while promoting),
  // so a power cut cannot remove the other committed record.
  LittleFS.remove(kSlotPaths[slot]);
  if (!LittleFS.rename(kTempPaths[slot], kSlotPaths[slot])) {
    LittleFS.remove(kTempPaths[slot]);
    return false;
  }
  NetworkRecord committedBytes = {};
  return readSlot(slot, committedBytes) &&
         committedBytes.crc32 == record.crc32;
}

bool NetworkConfigStore::writeCandidate(const NetworkConfig& config,
                                        NetworkRecord& record) {
  if (!validateConfig(config)) {
    return false;
  }
  NetworkRecord candidate = {};
  candidate.state = static_cast<uint8_t>(RecordState::kCandidate);
  candidate.generation = nextGeneration();
  candidate.config = config;
  sealRecord(candidate);
  const uint8_t slot = inactiveSlot();
  if (!writeSlotAtomically(slot, candidate)) {
    return false;
  }
  candidateSlot_ = static_cast<int8_t>(slot);
  record = candidate;
  return true;
}

bool NetworkConfigStore::promoteCandidate(NetworkRecord& record) {
  if (candidateSlot_ < 0 ||
      record.state != static_cast<uint8_t>(RecordState::kCandidate) ||
      !validateConfig(record.config)) {
    return false;
  }
  record.state = static_cast<uint8_t>(RecordState::kCommitted);
  sealRecord(record);
  if (!writeSlotAtomically(static_cast<uint8_t>(candidateSlot_), record)) {
    return false;
  }
  activeCommittedSlot_ = candidateSlot_;
  candidateSlot_ = -1;
  return true;
}

bool NetworkConfigStore::writeCommitted(const NetworkConfig& config,
                                        NetworkRecord& record) {
  if (!validateConfig(config)) {
    return false;
  }
  NetworkRecord committed = {};
  committed.state = static_cast<uint8_t>(RecordState::kCommitted);
  committed.generation = nextGeneration();
  committed.config = config;
  sealRecord(committed);
  const uint8_t slot = inactiveSlot();
  if (!writeSlotAtomically(slot, committed)) {
    return false;
  }
  activeCommittedSlot_ = static_cast<int8_t>(slot);
  candidateSlot_ = -1;
  record = committed;
  return true;
}

}  // namespace network
