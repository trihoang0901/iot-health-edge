#pragma once

#include <DallasTemperature.h>
#include <MAX30105.h>
#include <OneWire.h>

#include "AppConfig.h"
#include "Ds18b20Schedule.h"
#include "Model.h"
#include "Mpu6Axis.h"

class SensorHub {
 public:
  SensorHub();

  void begin(uint32_t nowMs);
  void tick(uint32_t nowMs);

  bool takeMotionSample(FallSample& sample);
  const TelemetrySnapshot& snapshot() const;
  void setFallState(const char* state);

 private:
  static constexpr size_t kPpgWindowSamples = 100;

  static uint32_t elapsed(uint32_t nowMs, uint32_t sinceMs);
  static float clamp01(float value);
  void setFault(SensorFault fault, bool active);
  void recoverI2cBus(uint32_t nowMs);

  bool initializeMax30102(uint32_t nowMs);
  bool initializeImu(uint32_t nowMs);
  bool initializeDs18b20(uint32_t nowMs);
  bool discoverDs18b20Address();
  bool requestDs18b20Conversion(uint32_t nowMs);
  void invalidateDs18b20(uint32_t nowMs);

  void tickMax30102(uint32_t nowMs);
  void addPpgSample(uint32_t red, uint32_t ir, uint32_t nowMs);
  void processPpgWindow(uint32_t nowMs);
  void invalidatePpg(bool fingerPresent);
  void resetPpgWindow();

  void tickImu(uint32_t nowMs);
  void invalidateImu(uint32_t nowMs);
  void tickDs18b20(uint32_t nowMs);

  MAX30105 max30102_;
  Mpu6Axis mpu6Axis_;
  OneWire oneWire_;
  DallasTemperature ds18b20_;
  DeviceAddress ds18b20Address_ = {};

  bool maxReady_ = false;
  bool mpuReady_ = false;
  bool dsReady_ = false;
  uint32_t maxRetryMs_ = 0;
  uint32_t mpuRetryMs_ = 0;

  uint32_t redRing_[kPpgWindowSamples] = {};
  uint32_t irRing_[kPpgWindowSamples] = {};
  uint8_t motionRing_[kPpgWindowSamples] = {};
  uint8_t motionValidityRing_[kPpgWindowSamples] = {};
  uint32_t redWork_[kPpgWindowSamples] = {};
  uint32_t irWork_[kPpgWindowSamples] = {};
  size_t ppgCount_ = 0;
  size_t ppgWriteIndex_ = 0;
  uint32_t lastPpgSampleMs_ = 0;
  uint32_t lastPpgProcessMs_ = 0;
  uint32_t lastPpgTickMs_ = 0;
  bool fingerPresent_ = false;

  uint32_t lastImuSampleMs_ = 0;
  FallSample pendingMotionSample_;
  bool motionSamplePending_ = false;

  Ds18b20Schedule ds18b20Schedule_;

  TelemetrySnapshot snapshot_;
};
