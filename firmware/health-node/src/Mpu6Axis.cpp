#include "Mpu6Axis.h"

#if defined(ARDUINO)
#include <Arduino.h>
#include <Wire.h>
#endif

namespace {

constexpr uint8_t kSampleRateDividerRegister = 0x19;
constexpr uint8_t kConfigurationRegister = 0x1A;
constexpr uint8_t kGyroConfigurationRegister = 0x1B;
constexpr uint8_t kAccelConfigurationRegister = 0x1C;
constexpr uint8_t kAccelConfiguration2Register = 0x1D;
constexpr uint8_t kMotionFrameRegister = 0x3B;
constexpr uint8_t kPowerManagement1Register = 0x6B;
constexpr uint8_t kPowerManagement2Register = 0x6C;
constexpr uint8_t kWhoAmIRegister = 0x75;

constexpr uint8_t kDeviceReset = 0x80;
constexpr uint8_t kClockSourcePllXGyro = 0x01;
constexpr uint8_t kSampleRateDivider = 0x04;
constexpr uint8_t kDlpfApproximately20Hz = 0x04;
constexpr uint8_t kGyroRange500Dps = 0x08;
constexpr uint8_t kAccelRange8G = 0x10;

constexpr uint8_t kPowerManagement1VerificationMask = 0x47;
constexpr uint8_t kPowerManagement2VerificationMask = 0x3F;
constexpr uint8_t kFullRegisterMask = 0xFF;
constexpr uint8_t kDlpfVerificationMask = 0x07;
constexpr uint8_t kMpu6050GyroVerificationMask = 0x18;
constexpr uint8_t kMpu6500GyroVerificationMask = 0x1B;
constexpr uint8_t kAccelFullScaleVerificationMask = 0x18;
constexpr uint8_t kAccelDlpfVerificationMask = 0x0F;

int16_t decodeSignedBigEndian(uint8_t high, uint8_t low) {
  const uint16_t value =
      (static_cast<uint16_t>(high) << 8U) | static_cast<uint16_t>(low);
  return static_cast<int16_t>(value);
}

}  // namespace

Mpu6AxisKind Mpu6Axis::classifyIdentity(uint8_t identity) {
  if (identity == static_cast<uint8_t>(Mpu6AxisKind::kMpu6050)) {
    return Mpu6AxisKind::kMpu6050;
  }
  if (identity == static_cast<uint8_t>(Mpu6AxisKind::kMpu6500Compatible)) {
    return Mpu6AxisKind::kMpu6500Compatible;
  }
  return Mpu6AxisKind::kUnsupported;
}

uint8_t Mpu6Axis::gyroConfigurationVerificationMask(Mpu6AxisKind kind) {
  if (kind == Mpu6AxisKind::kMpu6500Compatible) {
    // MPU6500 FCHOICE_B[1:0] must remain zero so CONFIG.DLPF_CFG is active.
    return kMpu6500GyroVerificationMask;
  }
  if (kind == Mpu6AxisKind::kMpu6050) {
    // The corresponding low bits are reserved on MPU6050.
    return kMpu6050GyroVerificationMask;
  }
  return 0U;
}

bool Mpu6Axis::decodeFrame(const uint8_t* bytes, size_t length,
                           Mpu6AxisRawFrame& frame) {
  frame = Mpu6AxisRawFrame{};
  if (bytes == nullptr || length != kMotionFrameBytes) {
    return false;
  }

  frame.accelX = decodeSignedBigEndian(bytes[0], bytes[1]);
  frame.accelY = decodeSignedBigEndian(bytes[2], bytes[3]);
  frame.accelZ = decodeSignedBigEndian(bytes[4], bytes[5]);
  frame.temperature = decodeSignedBigEndian(bytes[6], bytes[7]);
  frame.gyroX = decodeSignedBigEndian(bytes[8], bytes[9]);
  frame.gyroY = decodeSignedBigEndian(bytes[10], bytes[11]);
  frame.gyroZ = decodeSignedBigEndian(bytes[12], bytes[13]);
  return true;
}

Mpu6AxisSample Mpu6Axis::scaleFrame(const Mpu6AxisRawFrame& frame) {
  Mpu6AxisSample sample;
  sample.accelXG = static_cast<float>(frame.accelX) / kAccelScaleLsbPerG;
  sample.accelYG = static_cast<float>(frame.accelY) / kAccelScaleLsbPerG;
  sample.accelZG = static_cast<float>(frame.accelZ) / kAccelScaleLsbPerG;
  sample.gyroXDps = static_cast<float>(frame.gyroX) / kGyroScaleLsbPerDps;
  sample.gyroYDps = static_cast<float>(frame.gyroY) / kGyroScaleLsbPerDps;
  sample.gyroZDps = static_cast<float>(frame.gyroZ) / kGyroScaleLsbPerDps;
  return sample;
}

bool Mpu6Axis::ready() const {
  return ready_;
}

Mpu6AxisKind Mpu6Axis::kind() const {
  return kind_;
}

#if defined(ARDUINO)

bool Mpu6Axis::begin(TwoWire& wire) {
  wire_ = &wire;
  ready_ = false;
  kind_ = Mpu6AxisKind::kUnsupported;

  uint8_t identity = 0;
  if (!readRegisters(kWhoAmIRegister, &identity, 1U)) {
    return false;
  }
  kind_ = classifyIdentity(identity);
  if (kind_ == Mpu6AxisKind::kUnsupported || !configure()) {
    kind_ = Mpu6AxisKind::kUnsupported;
    return false;
  }

  ready_ = true;
  return true;
}

bool Mpu6Axis::configure() {
  if (!writeRegister(kPowerManagement1Register, kDeviceReset)) {
    return false;
  }
  delay(100);

  // A reset may expose a different device or a floating-bus value. Require the
  // same supported identity again before writing configuration registers.
  uint8_t identityAfterReset = 0;
  if (!readRegisters(kWhoAmIRegister, &identityAfterReset, 1U) ||
      classifyIdentity(identityAfterReset) != kind_) {
    return false;
  }

  if (!writeAndVerifyRegister(kPowerManagement1Register,
                              kClockSourcePllXGyro,
                              kPowerManagement1VerificationMask) ||
      !writeAndVerifyRegister(kPowerManagement2Register, 0x00,
                              kPowerManagement2VerificationMask) ||
      !writeAndVerifyRegister(kSampleRateDividerRegister, kSampleRateDivider,
                              kFullRegisterMask) ||
      !writeAndVerifyRegister(kConfigurationRegister,
                              kDlpfApproximately20Hz,
                              kDlpfVerificationMask) ||
      !writeAndVerifyRegister(kGyroConfigurationRegister, kGyroRange500Dps,
                              gyroConfigurationVerificationMask(kind_)) ||
      !writeAndVerifyRegister(kAccelConfigurationRegister, kAccelRange8G,
                              kAccelFullScaleVerificationMask)) {
    return false;
  }

  // MPU6500-compatible parts have a separate accelerometer DLPF register.
  // Register 0x1D is reserved on MPU6050 and is therefore never touched there.
  if (kind_ == Mpu6AxisKind::kMpu6500Compatible &&
      !writeAndVerifyRegister(kAccelConfiguration2Register,
                              kDlpfApproximately20Hz,
                              kAccelDlpfVerificationMask)) {
    return false;
  }
  delay(10);
  return true;
}

bool Mpu6Axis::readSample(Mpu6AxisSample& sample) {
  sample = Mpu6AxisSample{};
  if (!ready_ || wire_ == nullptr) {
    return false;
  }

  uint8_t bytes[kMotionFrameBytes] = {};
  if (!readRegisters(kMotionFrameRegister, bytes, sizeof(bytes))) {
    ready_ = false;
    return false;
  }

  Mpu6AxisRawFrame rawFrame;
  if (!decodeFrame(bytes, sizeof(bytes), rawFrame)) {
    ready_ = false;
    return false;
  }
  sample = scaleFrame(rawFrame);
  return true;
}

bool Mpu6Axis::writeRegister(uint8_t registerAddress, uint8_t value) {
  if (wire_ == nullptr) {
    return false;
  }
  wire_->beginTransmission(kAddress);
  wire_->write(registerAddress);
  wire_->write(value);
  return wire_->endTransmission(true) == 0U;
}

bool Mpu6Axis::writeAndVerifyRegister(uint8_t registerAddress, uint8_t value,
                                      uint8_t verificationMask) {
  if (!writeRegister(registerAddress, value)) {
    return false;
  }
  uint8_t actual = 0;
  return readRegisters(registerAddress, &actual, 1U) &&
         (actual & verificationMask) == (value & verificationMask);
}

bool Mpu6Axis::readRegisters(uint8_t registerAddress, uint8_t* destination,
                             size_t length) {
  if (wire_ == nullptr || destination == nullptr || length == 0U ||
      length > UINT8_MAX) {
    return false;
  }

  wire_->beginTransmission(kAddress);
  wire_->write(registerAddress);
  if (wire_->endTransmission(false) != 0U) {
    return false;
  }

  const size_t received = wire_->requestFrom(kAddress, length, true);
  if (received != length) {
    while (wire_->available() > 0) {
      wire_->read();
    }
    return false;
  }

  for (size_t index = 0; index < length; ++index) {
    if (wire_->available() <= 0) {
      return false;
    }
    destination[index] = static_cast<uint8_t>(wire_->read());
  }
  return wire_->available() == 0;
}

#endif
