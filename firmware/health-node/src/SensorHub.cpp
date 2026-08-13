#include "SensorHub.h"

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <spo2_algorithm.h>

namespace {

constexpr uint8_t kMax30102Address = 0x57;
constexpr uint8_t kFifoOverflowCounterRegister = 0x05;
constexpr uint8_t kFifoOverflowCounterMask = 0x1F;
// SparkFun MAX3010x keeps four slots and uses one slot to distinguish head/tail,
// so four or more samples returned by check() means older samples were overwritten.
constexpr uint16_t kSparkFunFifoStorageSize = 4;

bool isValidAmbientTemperature(float value) {
  return isfinite(value) && value >= 0.0F && value <= 50.0F;
}

bool isValidHumidity(float value) {
  return isfinite(value) && value >= 20.0F && value <= 90.0F;
}

}  // namespace

SensorHub::SensorHub() : dht11_(config::kDht11Pin, DHT11) {}

uint32_t SensorHub::elapsed(uint32_t nowMs, uint32_t sinceMs) {
  return static_cast<uint32_t>(nowMs - sinceMs);
}

float SensorHub::clamp01(float value) {
  if (value < 0.0F) {
    return 0.0F;
  }
  if (value > 1.0F) {
    return 1.0F;
  }
  return value;
}

void SensorHub::setFault(SensorFault fault, bool active) {
  if (active) {
    snapshot_.faultMask |= static_cast<uint8_t>(fault);
  } else {
    snapshot_.faultMask &= ~static_cast<uint8_t>(fault);
  }
}

void SensorHub::recoverI2cBus(uint32_t nowMs) {
  maxReady_ = false;
  maxRetryMs_ = nowMs;
  setFault(kFaultMax30102, true);
  invalidateImu(nowMs);

  // Wire.status() already clocks a stuck SDA line. Reinitializing releases the
  // software bus state; a physically held line remains faulted and is skipped
  // on subsequent ticks instead of entering sensor transactions.
  Wire.begin(config::kI2cSdaPin, config::kI2cSclPin);
  Wire.setClock(config::kI2cClockHz);
  Wire.setClockStretchLimit(config::kI2cClockStretchLimitUs);
}

void SensorHub::begin(uint32_t nowMs) {
  initializeMax30102(nowMs);
  initializeImu(nowMs);
  initializeDht11(nowMs);
}

bool SensorHub::initializeMax30102(uint32_t nowMs) {
  maxRetryMs_ = nowMs;
  maxReady_ = max30102_.begin(Wire, I2C_SPEED_FAST);
  // SparkFun's begin() initializes the shared Wire instance. Reapply the
  // project timing, especially the bounded ESP8266 clock-stretch limit, on
  // both success and failure before any MPU transaction runs.
  Wire.setClock(config::kI2cClockHz);
  Wire.setClockStretchLimit(config::kI2cClockStretchLimitUs);
  setFault(kFaultMax30102, !maxReady_);
  resetPpgWindow();
  invalidatePpg(false);
  lastPpgSampleMs_ = nowMs;
  lastPpgProcessMs_ = nowMs;
  lastPpgTickMs_ = nowMs;

  if (!maxReady_) {
    return false;
  }

  // SparkFun's class is named MAX30105 but also supports MAX30102.
  // 4-sample averaging at 100 sps gives the reference algorithm a stable demo window.
  max30102_.setup(0x3C, 4, 2, 100, 411, 4096);
  max30102_.setPulseAmplitudeRed(0x3C);
  max30102_.setPulseAmplitudeIR(0x3C);
  max30102_.setPulseAmplitudeGreen(0);
  max30102_.clearFIFO();
  return true;
}

bool SensorHub::initializeImu(uint32_t nowMs) {
  mpuRetryMs_ = nowMs;
  mpuReady_ = mpu6Axis_.begin(Wire);
  setFault(kFaultMpu6050, !mpuReady_);
  snapshot_.motionValid = false;
  lastImuSampleMs_ = nowMs;
  return mpuReady_;
}

void SensorHub::initializeDht11(uint32_t nowMs) {
  dht11_.begin();
  snapshot_.ambientTempC.valid = false;
  snapshot_.humidityPct.valid = false;
  setFault(kFaultDht11, true);
  lastEnvironmentReadMs_ = nowMs;
}

void SensorHub::tick(uint32_t nowMs) {
  if (Wire.status() != 0U) {
    recoverI2cBus(nowMs);
    tickDht11(nowMs);
    return;
  }

  if (!maxReady_ && elapsed(nowMs, maxRetryMs_) >= config::kSensorRetryMs) {
    initializeMax30102(nowMs);
  }
  if (!mpuReady_ && elapsed(nowMs, mpuRetryMs_) >= config::kSensorRetryMs) {
    initializeImu(nowMs);
  }
  tickMax30102(nowMs);
  if (Wire.status() != 0U) {
    recoverI2cBus(nowMs);
    tickDht11(nowMs);
    return;
  }
  tickImu(nowMs);
  if (Wire.status() != 0U) {
    recoverI2cBus(nowMs);
  }
  tickDht11(nowMs);
}

void SensorHub::tickMax30102(uint32_t nowMs) {
  if (!maxReady_) {
    return;
  }

  const bool samplingGap =
      elapsed(nowMs, lastPpgTickMs_) > config::kPpgMaximumSamplingGapMs;
  lastPpgTickMs_ = nowMs;
  const uint8_t hardwareOverflow =
      max30102_.readRegister8(kMax30102Address, kFifoOverflowCounterRegister) &
      kFifoOverflowCounterMask;
  if (samplingGap || hardwareOverflow != 0U) {
    max30102_.clearFIFO();
    resetPpgWindow();
    invalidatePpg(fingerPresent_);
    setFault(kFaultPpgOverflow, true);
    lastPpgSampleMs_ = nowMs;
    return;
  }

  const uint16_t fetched = max30102_.check();
  if (fetched >= kSparkFunFifoStorageSize) {
    while (max30102_.available()) {
      max30102_.nextSample();
    }
    resetPpgWindow();
    invalidatePpg(fingerPresent_);
    setFault(kFaultPpgOverflow, true);
    lastPpgSampleMs_ = nowMs;
    return;
  }

  while (max30102_.available()) {
    const uint32_t red = max30102_.getFIFORed();
    const uint32_t ir = max30102_.getFIFOIR();
    max30102_.nextSample();
    addPpgSample(red, ir, nowMs);
  }

  if (elapsed(nowMs, lastPpgSampleMs_) > config::kPpgStaleMs) {
    maxReady_ = false;
    setFault(kFaultMax30102, true);
    invalidatePpg(false);
    maxRetryMs_ = nowMs;
    return;
  }

  if (ppgCount_ == kPpgWindowSamples &&
      elapsed(nowMs, lastPpgProcessMs_) >= config::kPpgWindowRefreshMs) {
    processPpgWindow(nowMs);
  }
}

void SensorHub::addPpgSample(uint32_t red, uint32_t ir, uint32_t nowMs) {
  lastPpgSampleMs_ = nowMs;
  const bool fingerNow = ir >= config::kFingerIrThreshold;

  if (!fingerNow) {
    if (fingerPresent_ || ppgCount_ > 0) {
      resetPpgWindow();
    }
    fingerPresent_ = false;
    invalidatePpg(false);
    return;
  }

  if (!fingerPresent_) {
    resetPpgWindow();
  }
  fingerPresent_ = true;
  snapshot_.fingerPresent = true;

  const bool sampleMotionArtifact =
      snapshot_.motionValid &&
      (fabsf(snapshot_.accelMagnitudeG - 1.0F) > config::kMotionArtifactAccelDeviationG ||
       snapshot_.gyroMagnitudeDps > config::kMotionArtifactGyroDps);

  redRing_[ppgWriteIndex_] = red;
  irRing_[ppgWriteIndex_] = ir;
  motionRing_[ppgWriteIndex_] = sampleMotionArtifact ? 1U : 0U;
  motionValidityRing_[ppgWriteIndex_] = snapshot_.motionValid ? 1U : 0U;
  ppgWriteIndex_ = (ppgWriteIndex_ + 1U) % kPpgWindowSamples;
  if (ppgCount_ < kPpgWindowSamples) {
    ++ppgCount_;
  }

  if (ppgCount_ < kPpgWindowSamples) {
    snapshot_.heartRateBpm.valid = false;
    snapshot_.spo2Pct.valid = false;
    snapshot_.ppgQuality = 0.4F *
                           (static_cast<float>(ppgCount_) /
                            static_cast<float>(kPpgWindowSamples));
  }
}

void SensorHub::processPpgWindow(uint32_t nowMs) {
  lastPpgProcessMs_ = nowMs;
  uint64_t irSum = 0;
  uint32_t irMin = UINT32_MAX;
  uint32_t irMax = 0;
  size_t motionSamples = 0;
  size_t motionValidSamples = 0;

  for (size_t index = 0; index < kPpgWindowSamples; ++index) {
    const size_t ringIndex = (ppgWriteIndex_ + index) % kPpgWindowSamples;
    redWork_[index] = redRing_[ringIndex];
    irWork_[index] = irRing_[ringIndex];
    irSum += irWork_[index];
    if (irWork_[index] < irMin) {
      irMin = irWork_[index];
    }
    if (irWork_[index] > irMax) {
      irMax = irWork_[index];
    }
    motionSamples += motionRing_[ringIndex] != 0U ? 1U : 0U;
    motionValidSamples += motionValidityRing_[ringIndex] != 0U ? 1U : 0U;
  }

  int32_t spo2 = 0;
  int8_t spo2Valid = 0;
  int32_t heartRate = 0;
  int8_t heartRateValid = 0;
  maxim_heart_rate_and_oxygen_saturation(irWork_, static_cast<int32_t>(kPpgWindowSamples),
                                         redWork_, &spo2, &spo2Valid, &heartRate,
                                         &heartRateValid);

  const bool motionArtifact = motionSamples > (kPpgWindowSamples / 10U);
  const bool motionCoverageValid = motionValidSamples == kPpgWindowSamples;
  const bool hrPlausible = heartRate >= 40 && heartRate <= 220;
  const bool spo2Plausible = spo2 >= 50 && spo2 <= 100;
  snapshot_.motionArtifact = motionArtifact;
  snapshot_.heartRateBpm.valid =
      heartRateValid != 0 && hrPlausible && !motionArtifact && motionCoverageValid &&
      snapshot_.motionValid;
  snapshot_.spo2Pct.valid =
      spo2Valid != 0 && spo2Plausible && !motionArtifact && motionCoverageValid &&
      snapshot_.motionValid;
  snapshot_.heartRateBpm.value = static_cast<float>(heartRate);
  snapshot_.spo2Pct.value = static_cast<float>(spo2);

  const float meanIr = static_cast<float>(irSum) / static_cast<float>(kPpgWindowSamples);
  const float relativePulse = meanIr > 0.0F
                                  ? static_cast<float>(irMax - irMin) / meanIr
                                  : 0.0F;
  const float pulsatilityScore = clamp01((relativePulse - 0.001F) / 0.020F);
  const float algorithmScore =
      (snapshot_.heartRateBpm.valid && snapshot_.spo2Pct.valid) ? 1.0F : 0.4F;
  float quality = 0.4F + 0.4F * pulsatilityScore + 0.2F * algorithmScore;
  if (motionArtifact) {
    quality *= 0.35F;
  }
  if (!motionCoverageValid) {
    quality *= 0.35F;
  }
  snapshot_.ppgQuality = clamp01(quality);
  setFault(kFaultPpgOverflow, false);
}

void SensorHub::invalidatePpg(bool fingerPresent) {
  snapshot_.fingerPresent = fingerPresent;
  snapshot_.motionArtifact = false;
  snapshot_.heartRateBpm.valid = false;
  snapshot_.spo2Pct.valid = false;
  snapshot_.ppgQuality = fingerPresent ? snapshot_.ppgQuality : 0.0F;
}

void SensorHub::resetPpgWindow() {
  ppgCount_ = 0;
  ppgWriteIndex_ = 0;
}

void SensorHub::tickImu(uint32_t nowMs) {
  if (!mpuReady_ || elapsed(nowMs, lastImuSampleMs_) < config::kImuPeriodMs) {
    return;
  }
  lastImuSampleMs_ = nowMs;

  Mpu6AxisSample motion;
  const bool ok = mpu6Axis_.readSample(motion);
  if (!ok) {
    invalidateImu(nowMs);
    return;
  }

  snapshot_.accelMagnitudeG =
      sqrtf(motion.accelXG * motion.accelXG + motion.accelYG * motion.accelYG +
            motion.accelZG * motion.accelZG);
  snapshot_.gyroMagnitudeDps =
      sqrtf(motion.gyroXDps * motion.gyroXDps +
            motion.gyroYDps * motion.gyroYDps +
            motion.gyroZDps * motion.gyroZDps);
  snapshot_.motionValid = isfinite(snapshot_.accelMagnitudeG) &&
                          isfinite(snapshot_.gyroMagnitudeDps);
  if (!snapshot_.motionValid) {
    invalidateImu(nowMs);
    return;
  }
  setFault(kFaultMpu6050, !snapshot_.motionValid);

  pendingMotionSample_.accelMagnitudeG = snapshot_.accelMagnitudeG;
  pendingMotionSample_.gyroMagnitudeDps = snapshot_.gyroMagnitudeDps;
  pendingMotionSample_.valid = snapshot_.motionValid;
  motionSamplePending_ = true;
}

void SensorHub::invalidateImu(uint32_t nowMs) {
  mpuReady_ = false;
  mpuRetryMs_ = nowMs;
  snapshot_.motionValid = false;
  setFault(kFaultMpu6050, true);
  resetPpgWindow();
  invalidatePpg(fingerPresent_);

  // Deliver an invalid sample immediately so an in-progress fall candidate is
  // cancelled on this loop rather than surviving until the sample-gap timeout.
  pendingMotionSample_ = FallSample{};
  pendingMotionSample_.valid = false;
  motionSamplePending_ = true;
}

void SensorHub::tickDht11(uint32_t nowMs) {
  if (elapsed(nowMs, lastEnvironmentReadMs_) < config::kEnvironmentPeriodMs) {
    return;
  }
  lastEnvironmentReadMs_ = nowMs;

  // The library reuses the same physical sample for these back-to-back calls.
  // Each field is validated independently so one bad value cannot be published
  // as current, and a failed DHT read never stops the MQTT loop.
  const float ambientTempC = dht11_.readTemperature();
  const float humidityPct = dht11_.readHumidity();
  snapshot_.ambientTempC.valid = isValidAmbientTemperature(ambientTempC);
  snapshot_.humidityPct.valid = isValidHumidity(humidityPct);
  if (snapshot_.ambientTempC.valid) {
    snapshot_.ambientTempC.value = ambientTempC;
  }
  if (snapshot_.humidityPct.valid) {
    snapshot_.humidityPct.value = humidityPct;
  }
  setFault(kFaultDht11,
           !snapshot_.ambientTempC.valid || !snapshot_.humidityPct.valid);
}

bool SensorHub::takeMotionSample(FallSample& sample) {
  if (!motionSamplePending_) {
    return false;
  }
  sample = pendingMotionSample_;
  motionSamplePending_ = false;
  return true;
}

const TelemetrySnapshot& SensorHub::snapshot() const {
  return snapshot_;
}

void SensorHub::setFallState(const char* state) {
  snapshot_.fallState = state != nullptr ? state : "unknown";
}
