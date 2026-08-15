#pragma once

#include <stddef.h>
#include <stdint.h>

struct PpgGateInput {
  const uint32_t* redSamples = nullptr;
  const uint32_t* irSamples = nullptr;
  size_t sampleCount = 0;
  float sampleRateHz = 25.0F;

  bool fingerPresent = false;
  bool motionArtifact = false;
  bool motionCoverageValid = false;
  bool sampleLoss = false;

  float heartRateCandidateBpm = 0.0F;
  bool heartRateCandidateValid = false;
  float spo2CandidatePct = 0.0F;
  bool spo2CandidateValid = false;
};

struct PpgGateResult {
  float rawHeartRateBpm = 0.0F;
  bool rawHeartRateValid = false;
  float rawSpo2Pct = 0.0F;
  bool rawSpo2Valid = false;

  float confirmedHeartRateBpm = 0.0F;
  bool confirmedHeartRateValid = false;
  float confirmedSpo2Pct = 0.0F;
  bool confirmedSpo2Valid = false;

  float ppgQuality = 0.0F;
  const char* state = "warming_up";
};

// Stateful confidence gate for MAX30102 candidate measurements. The class is
// intentionally independent from Arduino so its fail-closed behavior can be
// exercised by native tests.
class PpgQualityGate {
 public:
  static constexpr size_t kRequiredSamples = 100;
  static constexpr size_t kCandidateWindow = 5;
  static constexpr size_t kRequiredConsistentWindows = 3;
  static constexpr float kJumpConfirmationBpm = 25.0F;

  PpgGateResult evaluate(const PpgGateInput& input);
  void reset();

 private:
  struct OpticalAssessment {
    bool clipping = false;
    bool lowPerfusion = false;
    bool rrStable = false;
    float rrHeartRateBpm = 0.0F;
    float rrRelativeMad = 1.0F;
    float relativePulse = 0.0F;
  };

  static float absolute(float value);
  static float clamp01(float value);
  static float median(float* values, size_t count);
  static uint32_t medianUint32(uint32_t* values, size_t count);
  static OpticalAssessment assessOptical(const PpgGateInput& input);

  void clearCandidates();
  void pushCandidate(float heartRateBpm, float spo2Pct, bool spo2Valid);
  size_t collectHeartRateInliers(float* output, bool* sourceInlier) const;

  float heartRateCandidates_[kCandidateWindow] = {};
  float spo2Candidates_[kCandidateWindow] = {};
  bool spo2CandidateValid_[kCandidateWindow] = {};
  size_t candidateCount_ = 0;
  size_t candidateWriteIndex_ = 0;

  bool referenceValid_ = false;
  float referenceHeartRateBpm_ = 0.0F;
  bool jumpPending_ = false;
};
