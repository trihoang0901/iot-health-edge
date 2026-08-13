#pragma once

#include <stdint.h>

enum class Ds18b20ScheduleState : uint8_t {
  kUnavailable,
  kIdle,
  kWaiting,
};

class Ds18b20Schedule {
 public:
  static constexpr uint32_t kConversionMs = 750;
  static constexpr uint32_t kCycleMs = 2000;
  static constexpr uint32_t kRetryMs = 10000;

  void beginConversion(uint32_t requestedAtMs) {
    state_ = Ds18b20ScheduleState::kWaiting;
    referenceMs_ = requestedAtMs;
  }

  void acceptMeasurement() {
    state_ = Ds18b20ScheduleState::kIdle;
    // Keep the request timestamp so kCycleMs is start-to-start cadence;
    // conversion time must not be added to the configured sampling period.
    measurementValid_ = true;
  }

  void invalidate(uint32_t failedAtMs) {
    state_ = Ds18b20ScheduleState::kUnavailable;
    referenceMs_ = failedAtMs;
    measurementValid_ = false;
  }

  bool conversionDue(uint32_t nowMs) const {
    return state_ == Ds18b20ScheduleState::kWaiting &&
           elapsed(nowMs, referenceMs_) >= kConversionMs;
  }

  bool cycleDue(uint32_t nowMs) const {
    return state_ == Ds18b20ScheduleState::kIdle &&
           elapsed(nowMs, referenceMs_) >= kCycleMs;
  }

  bool retryDue(uint32_t nowMs) const {
    return state_ == Ds18b20ScheduleState::kUnavailable &&
           elapsed(nowMs, referenceMs_) >= kRetryMs;
  }

  Ds18b20ScheduleState state() const { return state_; }
  bool measurementValid() const { return measurementValid_; }

 private:
  static uint32_t elapsed(uint32_t nowMs, uint32_t sinceMs) {
    return static_cast<uint32_t>(nowMs - sinceMs);
  }

  Ds18b20ScheduleState state_ = Ds18b20ScheduleState::kUnavailable;
  uint32_t referenceMs_ = 0;
  bool measurementValid_ = false;
};
