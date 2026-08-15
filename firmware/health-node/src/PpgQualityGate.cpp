#include "PpgQualityGate.h"

#include <math.h>

namespace {

constexpr uint32_t kMax30102AdcMaximum = 0x3FFFFU;
constexpr uint32_t kClippingMargin = 1024U;
constexpr float kMinimumRelativePulse = 0.003F;
constexpr float kMaximumRrRelativeMad = 0.15F;
constexpr float kMaximumRrCandidateDifferenceBpm = 12.0F;
constexpr float kMinimumHeartRateBpm = 40.0F;
constexpr float kMaximumHeartRateBpm = 220.0F;
constexpr float kMinimumSpo2Pct = 50.0F;
constexpr float kMaximumSpo2Pct = 100.0F;
constexpr size_t kMaximumRrIntervals = 20;

template <typename T>
void insertionSort(T* values, size_t count) {
  for (size_t index = 1; index < count; ++index) {
    const T value = values[index];
    size_t position = index;
    while (position > 0 && values[position - 1] > value) {
      values[position] = values[position - 1];
      --position;
    }
    values[position] = value;
  }
}

}  // namespace

constexpr size_t PpgQualityGate::kRequiredSamples;
constexpr size_t PpgQualityGate::kCandidateWindow;
constexpr size_t PpgQualityGate::kRequiredConsistentWindows;
constexpr float PpgQualityGate::kJumpConfirmationBpm;

float PpgQualityGate::absolute(float value) {
  return value < 0.0F ? -value : value;
}

float PpgQualityGate::clamp01(float value) {
  if (value < 0.0F) {
    return 0.0F;
  }
  if (value > 1.0F) {
    return 1.0F;
  }
  return value;
}

float PpgQualityGate::median(float* values, size_t count) {
  if (count == 0) {
    return 0.0F;
  }
  insertionSort(values, count);
  const size_t middle = count / 2U;
  if ((count & 1U) != 0U) {
    return values[middle];
  }
  return 0.5F * (values[middle - 1U] + values[middle]);
}

uint32_t PpgQualityGate::medianUint32(uint32_t* values, size_t count) {
  if (count == 0) {
    return 0U;
  }
  insertionSort(values, count);
  const size_t middle = count / 2U;
  if ((count & 1U) != 0U) {
    return values[middle];
  }
  return static_cast<uint32_t>((static_cast<uint64_t>(values[middle - 1U]) +
                                static_cast<uint64_t>(values[middle])) /
                               2U);
}

PpgQualityGate::OpticalAssessment PpgQualityGate::assessOptical(
    const PpgGateInput& input) {
  OpticalAssessment assessment;
  if (input.redSamples == nullptr || input.irSamples == nullptr ||
      input.sampleCount < kRequiredSamples || input.sampleRateHz <= 0.0F) {
    return assessment;
  }

  uint32_t irSorted[kRequiredSamples] = {};
  uint32_t redSorted[kRequiredSamples] = {};
  size_t clippedSamples = 0;
  for (size_t index = 0; index < kRequiredSamples; ++index) {
    const uint32_t red = input.redSamples[index];
    const uint32_t ir = input.irSamples[index];
    redSorted[index] = red;
    irSorted[index] = ir;
    if (red == 0U || ir == 0U || red >= kMax30102AdcMaximum - kClippingMargin ||
        ir >= kMax30102AdcMaximum - kClippingMargin) {
      ++clippedSamples;
    }
  }
  assessment.clipping = clippedSamples >= 3U;

  insertionSort(irSorted, kRequiredSamples);
  insertionSort(redSorted, kRequiredSamples);
  const uint32_t irMedian = medianUint32(irSorted, kRequiredSamples);
  const uint32_t redMedian = medianUint32(redSorted, kRequiredSamples);
  const uint32_t irP10 = irSorted[kRequiredSamples / 10U];
  const uint32_t irP90 = irSorted[(kRequiredSamples * 9U) / 10U];
  assessment.relativePulse =
      irMedian > 0U ? static_cast<float>(irP90 - irP10) / static_cast<float>(irMedian)
                    : 0.0F;
  assessment.lowPerfusion = irMedian < 10000U || redMedian < 5000U ||
                             assessment.relativePulse < kMinimumRelativePulse;
  if (assessment.clipping || assessment.lowPerfusion) {
    return assessment;
  }

  const uint32_t peakThreshold =
      irMedian + static_cast<uint32_t>(0.20F * static_cast<float>(irP90 - irP10));
  const size_t minimumPeakGap = static_cast<size_t>(
      input.sampleRateHz * 60.0F / kMaximumHeartRateBpm);
  size_t lastPeak = 0;
  bool havePeak = false;
  float rrIntervals[kMaximumRrIntervals] = {};
  size_t rrCount = 0;

  for (size_t index = 1; index + 1U < kRequiredSamples; ++index) {
    const uint32_t previous = input.irSamples[index - 1U];
    const uint32_t current = input.irSamples[index];
    const uint32_t next = input.irSamples[index + 1U];
    const bool localMaximum = current >= previous && current > next;
    if (!localMaximum || current < peakThreshold) {
      continue;
    }
    if (havePeak && index - lastPeak < minimumPeakGap) {
      if (current > input.irSamples[lastPeak]) {
        lastPeak = index;
      }
      continue;
    }
    if (havePeak && rrCount < kMaximumRrIntervals) {
      rrIntervals[rrCount++] = static_cast<float>(index - lastPeak);
    }
    lastPeak = index;
    havePeak = true;
  }

  if (rrCount < 2U) {
    return assessment;
  }

  float rrForMedian[kMaximumRrIntervals] = {};
  for (size_t index = 0; index < rrCount; ++index) {
    rrForMedian[index] = rrIntervals[index];
  }
  const float rrMedian = median(rrForMedian, rrCount);
  float rrDeviations[kMaximumRrIntervals] = {};
  for (size_t index = 0; index < rrCount; ++index) {
    rrDeviations[index] = absolute(rrIntervals[index] - rrMedian);
  }
  const float rrMad = median(rrDeviations, rrCount);
  assessment.rrRelativeMad = rrMedian > 0.0F ? rrMad / rrMedian : 1.0F;
  assessment.rrHeartRateBpm =
      rrMedian > 0.0F ? 60.0F * input.sampleRateHz / rrMedian : 0.0F;
  assessment.rrStable = assessment.rrRelativeMad <= kMaximumRrRelativeMad &&
                        assessment.rrHeartRateBpm >= kMinimumHeartRateBpm &&
                        assessment.rrHeartRateBpm <= kMaximumHeartRateBpm;
  return assessment;
}

void PpgQualityGate::clearCandidates() {
  candidateCount_ = 0;
  candidateWriteIndex_ = 0;
  for (size_t index = 0; index < kCandidateWindow; ++index) {
    heartRateCandidates_[index] = 0.0F;
    spo2Candidates_[index] = 0.0F;
    spo2CandidateValid_[index] = false;
  }
}

void PpgQualityGate::reset() {
  clearCandidates();
  referenceValid_ = false;
  referenceHeartRateBpm_ = 0.0F;
  jumpPending_ = false;
}

void PpgQualityGate::pushCandidate(float heartRateBpm, float spo2Pct,
                                   bool spo2Valid) {
  heartRateCandidates_[candidateWriteIndex_] = heartRateBpm;
  spo2Candidates_[candidateWriteIndex_] = spo2Pct;
  spo2CandidateValid_[candidateWriteIndex_] = spo2Valid;
  candidateWriteIndex_ = (candidateWriteIndex_ + 1U) % kCandidateWindow;
  if (candidateCount_ < kCandidateWindow) {
    ++candidateCount_;
  }
}

size_t PpgQualityGate::collectHeartRateInliers(float* output,
                                               bool* sourceInlier) const {
  float values[kCandidateWindow] = {};
  for (size_t index = 0; index < candidateCount_; ++index) {
    values[index] = heartRateCandidates_[index];
  }
  const float center = median(values, candidateCount_);

  float deviations[kCandidateWindow] = {};
  for (size_t index = 0; index < candidateCount_; ++index) {
    deviations[index] = absolute(heartRateCandidates_[index] - center);
  }
  const float mad = median(deviations, candidateCount_);
  // Hampel's 3-sigma threshold is 3 * 1.4826 * MAD. A small floor avoids
  // rejecting harmless integer quantization when MAD is zero.
  const float threshold = mad * 4.4478F > 8.0F ? mad * 4.4478F : 8.0F;
  size_t inlierCount = 0;
  for (size_t index = 0; index < candidateCount_; ++index) {
    sourceInlier[index] = absolute(heartRateCandidates_[index] - center) <= threshold;
    if (sourceInlier[index]) {
      output[inlierCount++] = heartRateCandidates_[index];
    }
  }
  return inlierCount;
}

PpgGateResult PpgQualityGate::evaluate(const PpgGateInput& input) {
  PpgGateResult result;
  result.rawHeartRateBpm = input.heartRateCandidateBpm;
  result.rawHeartRateValid = input.heartRateCandidateValid &&
                             isfinite(input.heartRateCandidateBpm) &&
                             input.heartRateCandidateBpm >= kMinimumHeartRateBpm &&
                             input.heartRateCandidateBpm <= kMaximumHeartRateBpm;
  result.rawSpo2Pct = input.spo2CandidatePct;
  result.rawSpo2Valid = input.spo2CandidateValid && isfinite(input.spo2CandidatePct) &&
                        input.spo2CandidatePct >= kMinimumSpo2Pct &&
                        input.spo2CandidatePct <= kMaximumSpo2Pct;

  if (!input.fingerPresent) {
    reset();
    result.rawHeartRateValid = false;
    result.rawSpo2Valid = false;
    result.state = "no_finger";
    return result;
  }
  if (input.sampleLoss) {
    reset();
    result.rawHeartRateValid = false;
    result.rawSpo2Valid = false;
    result.state = "sample_loss";
    return result;
  }
  if (input.sampleCount < kRequiredSamples || input.redSamples == nullptr ||
      input.irSamples == nullptr) {
    clearCandidates();
    result.state = "warming_up";
    result.ppgQuality = clamp01(static_cast<float>(input.sampleCount) /
                                static_cast<float>(kRequiredSamples) * 0.4F);
    return result;
  }
  if (input.motionArtifact || !input.motionCoverageValid) {
    clearCandidates();
    jumpPending_ = false;
    result.state = "motion";
    result.ppgQuality = 0.10F;
    return result;
  }

  const OpticalAssessment optical = assessOptical(input);
  if (optical.clipping) {
    clearCandidates();
    jumpPending_ = false;
    result.state = "clipping";
    result.ppgQuality = 0.05F;
    return result;
  }
  if (optical.lowPerfusion) {
    clearCandidates();
    jumpPending_ = false;
    result.state = "low_perfusion";
    result.ppgQuality = clamp01(optical.relativePulse / kMinimumRelativePulse * 0.30F);
    return result;
  }

  const bool candidateAgreesWithRr =
      result.rawHeartRateValid && optical.rrStable &&
      absolute(result.rawHeartRateBpm - optical.rrHeartRateBpm) <=
          kMaximumRrCandidateDifferenceBpm;
  if (!candidateAgreesWithRr) {
    clearCandidates();
    jumpPending_ = false;
    result.state = "unstable";
    result.ppgQuality = clamp01(0.25F + optical.relativePulse * 5.0F);
    return result;
  }

  const bool isLargeJump =
      referenceValid_ &&
      absolute(result.rawHeartRateBpm - referenceHeartRateBpm_) >
          kJumpConfirmationBpm;
  if (isLargeJump && !jumpPending_) {
    clearCandidates();
    jumpPending_ = true;
  } else if (!isLargeJump && jumpPending_) {
    // The apparent jump disappeared. Do not resurrect a held value: start a
    // fresh confirmation series at the original level.
    clearCandidates();
    jumpPending_ = false;
  }
  pushCandidate(result.rawHeartRateBpm, result.rawSpo2Pct, result.rawSpo2Valid);

  float inliers[kCandidateWindow] = {};
  bool sourceInlier[kCandidateWindow] = {};
  const size_t inlierCount = collectHeartRateInliers(inliers, sourceInlier);
  if (inlierCount < kRequiredConsistentWindows) {
    result.state = referenceValid_ ? "unstable" : "warming_up";
    result.ppgQuality = clamp01(0.35F + optical.relativePulse * 5.0F +
                                static_cast<float>(inlierCount) * 0.10F);
    return result;
  }

  float inlierCopy[kCandidateWindow] = {};
  float minimum = inliers[0];
  float maximum = inliers[0];
  for (size_t index = 0; index < inlierCount; ++index) {
    inlierCopy[index] = inliers[index];
    if (inliers[index] < minimum) {
      minimum = inliers[index];
    }
    if (inliers[index] > maximum) {
      maximum = inliers[index];
    }
  }
  if (maximum - minimum > 12.0F) {
    result.state = "unstable";
    result.ppgQuality = 0.40F;
    return result;
  }

  float spo2Inliers[kCandidateWindow] = {};
  size_t spo2Count = 0;
  for (size_t index = 0; index < candidateCount_; ++index) {
    if (sourceInlier[index] && spo2CandidateValid_[index]) {
      spo2Inliers[spo2Count++] = spo2Candidates_[index];
    }
  }
  if (spo2Count >= kRequiredConsistentWindows) {
    float spo2ForMedian[kCandidateWindow] = {};
    for (size_t index = 0; index < spo2Count; ++index) {
      spo2ForMedian[index] = spo2Inliers[index];
    }
    const float spo2Center = median(spo2ForMedian, spo2Count);
    float spo2Deviations[kCandidateWindow] = {};
    for (size_t index = 0; index < spo2Count; ++index) {
      spo2Deviations[index] = absolute(spo2Inliers[index] - spo2Center);
    }
    const float spo2Mad = median(spo2Deviations, spo2Count);
    const float spo2Threshold =
        spo2Mad * 4.4478F > 2.0F ? spo2Mad * 4.4478F : 2.0F;
    float stableSpo2[kCandidateWindow] = {};
    size_t stableSpo2Count = 0;
    float spo2Minimum = 0.0F;
    float spo2Maximum = 0.0F;
    for (size_t index = 0; index < spo2Count; ++index) {
      if (absolute(spo2Inliers[index] - spo2Center) > spo2Threshold) {
        continue;
      }
      const float value = spo2Inliers[index];
      stableSpo2[stableSpo2Count++] = value;
      if (stableSpo2Count == 1U || value < spo2Minimum) {
        spo2Minimum = value;
      }
      if (stableSpo2Count == 1U || value > spo2Maximum) {
        spo2Maximum = value;
      }
    }
    if (stableSpo2Count < kRequiredConsistentWindows ||
        spo2Maximum - spo2Minimum > 4.0F) {
      result.state = "unstable";
      result.ppgQuality = 0.40F;
      return result;
    }
    result.confirmedSpo2Pct = median(stableSpo2, stableSpo2Count);
    result.confirmedSpo2Valid = true;
  }

  result.confirmedHeartRateBpm = median(inlierCopy, inlierCount);
  result.confirmedHeartRateValid = true;

  referenceHeartRateBpm_ = result.confirmedHeartRateBpm;
  referenceValid_ = true;
  jumpPending_ = false;
  result.state = "valid";
  const float rrScore = clamp01(1.0F - optical.rrRelativeMad / kMaximumRrRelativeMad);
  const float perfusionScore = clamp01(optical.relativePulse / 0.03F);
  result.ppgQuality = clamp01(0.50F + 0.25F * rrScore + 0.25F * perfusionScore);
  return result;
}
