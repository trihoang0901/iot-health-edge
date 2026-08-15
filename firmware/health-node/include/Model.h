#pragma once

#include <stdint.h>

enum SensorFault : uint8_t {
  kFaultNone = 0,
  kFaultMax30102 = 1U << 0,
  kFaultMpu6050 = 1U << 1,
  kFaultDs18b20 = 1U << 2,
  kFaultPpgOverflow = 1U << 3,
};

struct NullableMeasurement {
  float value = 0.0F;
  bool valid = false;
};

struct TelemetrySnapshot {
  NullableMeasurement heartRateRawBpm;
  NullableMeasurement spo2RawPct;
  NullableMeasurement heartRateBpm;
  NullableMeasurement spo2Pct;
  NullableMeasurement wristSurfaceTempC;

  float accelMagnitudeG = 0.0F;
  float gyroMagnitudeDps = 0.0F;
  bool motionValid = false;

  float ppgQuality = 0.0F;
  bool fingerPresent = false;
  bool motionArtifact = false;
  const char* ppgState = "no_finger";
  const char* fallState = "idle";

  uint8_t faultMask = kFaultNone;
};

struct FallSample {
  float accelMagnitudeG = 0.0F;
  float gyroMagnitudeDps = 0.0F;
  bool valid = false;
};
