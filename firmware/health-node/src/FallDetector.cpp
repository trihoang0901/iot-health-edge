#include "FallDetector.h"

#include <math.h>

FallDetector::FallDetector(const FallDetectorConfig& config) : config_(config) {}

uint32_t FallDetector::elapsed(uint32_t nowMs, uint32_t sinceMs) {
  return static_cast<uint32_t>(nowMs - sinceMs);
}

void FallDetector::enter(FallPhase next, uint32_t nowMs) {
  phase_ = next;
  phaseSinceMs_ = nowMs;
  if (next != FallPhase::kVerifyStillness) {
    stillSinceMs_ = 0;
  }
}

void FallDetector::resetCandidate(uint32_t nowMs) {
  lowGQualified_ = false;
  lowGSinceMs_ = 0;
  peakAccelG_ = 0.0F;
  enter(FallPhase::kIdle, nowMs);
}

FallUpdate FallDetector::update(const FallSample& sample, uint32_t nowMs) {
  FallUpdate result;

  if (hasLastSample_ && elapsed(nowMs, lastSampleMs_) > config_.maximumSampleGapMs &&
      (phase_ == FallPhase::kLowG || phase_ == FallPhase::kVerifyStillness)) {
    resetCandidate(nowMs);
  }
  lastSampleMs_ = nowMs;
  hasLastSample_ = true;

  if (!sample.valid || !isfinite(sample.accelMagnitudeG) ||
      !isfinite(sample.gyroMagnitudeDps)) {
    if (phase_ == FallPhase::kLowG || phase_ == FallPhase::kVerifyStillness) {
      resetCandidate(nowMs);
    }
    result.phase = phase_;
    result.peakAccelG = peakAccelG_;
    return result;
  }

  if (sample.accelMagnitudeG > peakAccelG_) {
    peakAccelG_ = sample.accelMagnitudeG;
  }

  switch (phase_) {
    case FallPhase::kIdle:
      peakAccelG_ = sample.accelMagnitudeG;
      if (sample.accelMagnitudeG < config_.lowGThreshold) {
        lowGSinceMs_ = nowMs;
        lowGQualified_ = false;
        enter(FallPhase::kLowG, nowMs);
      } else if (sample.accelMagnitudeG >= config_.impactThresholdG) {
        // Impact-first path covers demo falls without an observable low-g interval.
        enter(FallPhase::kVerifyStillness, nowMs);
      }
      break;

    case FallPhase::kLowG:
      // Qualify low-g only from consecutive low-g samples. A single transient
      // followed by ordinary acceleration must not remain armed until impact.
      if (!lowGQualified_) {
        if (sample.accelMagnitudeG >= config_.lowGThreshold) {
          resetCandidate(nowMs);
          break;
        }
        if (elapsed(nowMs, lowGSinceMs_) >= config_.lowGMinimumMs) {
          lowGQualified_ = true;
        }
      }
      if (sample.accelMagnitudeG >= config_.impactThresholdG && lowGQualified_) {
        enter(FallPhase::kVerifyStillness, nowMs);
      } else if (elapsed(nowMs, phaseSinceMs_) > config_.lowGToImpactTimeoutMs) {
        resetCandidate(nowMs);
      }
      break;

    case FallPhase::kVerifyStillness: {
      const bool accelStill =
          fabsf(sample.accelMagnitudeG - 1.0F) <= config_.stillnessAccelBandG;
      const bool gyroStill = sample.gyroMagnitudeDps <= config_.stillnessGyroDps;
      if (accelStill && gyroStill) {
        if (stillSinceMs_ == 0) {
          stillSinceMs_ = nowMs;
        }
        if (elapsed(nowMs, stillSinceMs_) >= config_.stillnessMinimumMs) {
          enter(FallPhase::kAlarm, nowMs);
          result.triggered = true;
        }
      } else {
        stillSinceMs_ = 0;
      }

      if (!result.triggered && elapsed(nowMs, phaseSinceMs_) > config_.verifyTimeoutMs) {
        resetCandidate(nowMs);
      }
      break;
    }

    case FallPhase::kAlarm:
      if (elapsed(nowMs, phaseSinceMs_) >= config_.alarmAutoClearMs) {
        enter(FallPhase::kRefractory, nowMs);
      }
      break;

    case FallPhase::kRefractory:
      if (elapsed(nowMs, phaseSinceMs_) >= config_.refractoryMs) {
        resetCandidate(nowMs);
      }
      break;
  }

  result.phase = phase_;
  result.peakAccelG = peakAccelG_;
  return result;
}

bool FallDetector::acknowledge(uint32_t nowMs) {
  if (phase_ != FallPhase::kAlarm) {
    return false;
  }
  enter(FallPhase::kRefractory, nowMs);
  return true;
}

void FallDetector::reset() {
  phase_ = FallPhase::kIdle;
  phaseSinceMs_ = 0;
  lowGSinceMs_ = 0;
  stillSinceMs_ = 0;
  lastSampleMs_ = 0;
  hasLastSample_ = false;
  lowGQualified_ = false;
  peakAccelG_ = 0.0F;
}

bool FallDetector::alarmActive() const {
  return phase_ == FallPhase::kAlarm;
}

FallPhase FallDetector::phase() const {
  return phase_;
}

const char* FallDetector::publicState() const {
  switch (phase_) {
    case FallPhase::kLowG:
      return "low_g";
    case FallPhase::kVerifyStillness:
      return "verify_stillness";
    case FallPhase::kAlarm:
      return "alarm";
    case FallPhase::kRefractory:
      return "refractory";
    case FallPhase::kIdle:
    default:
      return "idle";
  }
}

float FallDetector::peakAccelG() const {
  return peakAccelG_;
}
