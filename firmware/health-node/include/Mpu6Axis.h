#pragma once

#include <stddef.h>
#include <stdint.h>

class TwoWire;

enum class Mpu6AxisKind : uint8_t {
  kUnsupported = 0x00,
  kMpu6050 = 0x68,
  kMpu6500Compatible = 0x70,
};

struct Mpu6AxisRawFrame {
  int16_t accelX = 0;
  int16_t accelY = 0;
  int16_t accelZ = 0;
  int16_t temperature = 0;
  int16_t gyroX = 0;
  int16_t gyroY = 0;
  int16_t gyroZ = 0;
};

struct Mpu6AxisSample {
  float accelXG = 0.0F;
  float accelYG = 0.0F;
  float accelZG = 0.0F;
  float gyroXDps = 0.0F;
  float gyroYDps = 0.0F;
  float gyroZDps = 0.0F;
};

class Mpu6Axis {
 public:
  static constexpr uint8_t kAddress = 0x68;
  static constexpr size_t kMotionFrameBytes = 14;

  bool begin(TwoWire& wire);
  bool readSample(Mpu6AxisSample& sample);

  bool ready() const;
  Mpu6AxisKind kind() const;

  static Mpu6AxisKind classifyIdentity(uint8_t identity);
  static uint8_t gyroConfigurationVerificationMask(Mpu6AxisKind kind);
  static bool decodeFrame(const uint8_t* bytes, size_t length,
                          Mpu6AxisRawFrame& frame);
  static Mpu6AxisSample scaleFrame(const Mpu6AxisRawFrame& frame);

 private:
  static constexpr float kAccelScaleLsbPerG = 4096.0F;
  static constexpr float kGyroScaleLsbPerDps = 65.5F;

  bool configure();
  bool writeRegister(uint8_t registerAddress, uint8_t value);
  bool writeAndVerifyRegister(uint8_t registerAddress, uint8_t value,
                              uint8_t verificationMask);
  bool readRegisters(uint8_t registerAddress, uint8_t* destination,
                     size_t length);

  TwoWire* wire_ = nullptr;
  Mpu6AxisKind kind_ = Mpu6AxisKind::kUnsupported;
  bool ready_ = false;
};
