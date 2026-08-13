#pragma once

#include <stdint.h>

#include "Model.h"

enum class FallPhase : uint8_t {
  kIdle,
  kLowG,
  kVerifyStillness,
  kAlarm,
  kRefractory,
};
struct FallDetectorConfig {
  float lowGThreshold = 0.50F;
  uint32_t lowGMinimumMs = 150;
  float impactThresholdG = 2.50F;
  uint32_t lowGToImpactTimeoutMs = 1000;
  float stillnessAccelBandG = 0.15F;
  float stillnessGyroDps = 25.0F;
  uint32_t stillnessMinimumMs = 1500;
  uint32_t verifyTimeoutMs = 3500;
  uint32_t alarmAutoClearMs = 30000;
  uint32_t refractoryMs = 10000;
  uint32_t maximumSampleGapMs = 250;
};

struct FallUpdate {
  bool triggered = false;
  float peakAccelG = 0.0F;
  FallPhase phase = FallPhase::kIdle;
};

class FallDetector {
 public:
  explicit FallDetector(const FallDetectorConfig& config = FallDetectorConfig());

  FallUpdate update(const FallSample& sample, uint32_t nowMs);
  bool acknowledge(uint32_t nowMs);
  void reset();

  bool alarmActive() const;
  FallPhase phase() const;
  const char* publicState() const;
  float peakAccelG() const;

 private:
  static uint32_t elapsed(uint32_t nowMs, uint32_t sinceMs);
  void enter(FallPhase next, uint32_t nowMs);
  void resetCandidate(uint32_t nowMs);

  FallDetectorConfig config_;
  FallPhase phase_ = FallPhase::kIdle;
  uint32_t phaseSinceMs_ = 0;
  uint32_t lowGSinceMs_ = 0;
  uint32_t stillSinceMs_ = 0;
  uint32_t lastSampleMs_ = 0;
  bool hasLastSample_ = false;
  bool lowGQualified_ = false;
  float peakAccelG_ = 0.0F;
};
