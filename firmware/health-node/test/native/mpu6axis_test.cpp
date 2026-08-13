#include <assert.h>
#include <math.h>
#include <stdint.h>

#include <iostream>

#include "Mpu6Axis.h"

namespace {

bool nearlyEqual(float actual, float expected, float tolerance = 0.0001F) {
  return fabsf(actual - expected) <= tolerance;
}

void testIdentityClassification() {
  assert(Mpu6Axis::classifyIdentity(0x68) == Mpu6AxisKind::kMpu6050);
  assert(Mpu6Axis::classifyIdentity(0x70) ==
         Mpu6AxisKind::kMpu6500Compatible);
  assert(Mpu6Axis::classifyIdentity(0x69) == Mpu6AxisKind::kUnsupported);
  assert(Mpu6Axis::classifyIdentity(0x71) == Mpu6AxisKind::kUnsupported);
  assert(Mpu6Axis::gyroConfigurationVerificationMask(
             Mpu6AxisKind::kMpu6050) == 0x18);
  assert(Mpu6Axis::gyroConfigurationVerificationMask(
             Mpu6AxisKind::kMpu6500Compatible) == 0x1B);
  assert(Mpu6Axis::gyroConfigurationVerificationMask(
             Mpu6AxisKind::kUnsupported) == 0x00);
}

void testSignedBigEndianFrameDecoding() {
  const uint8_t bytes[Mpu6Axis::kMotionFrameBytes] = {
      0x10, 0x00,  // accel X: 4096
      0xF0, 0x00,  // accel Y: -4096
      0x7F, 0xFF,  // accel Z: 32767
      0x80, 0x00,  // temperature: -32768
      0x02, 0x8F,  // gyro X: 655
      0xFD, 0x71,  // gyro Y: -655
      0x00, 0x00,  // gyro Z: 0
  };
  Mpu6AxisRawFrame frame;
  assert(Mpu6Axis::decodeFrame(bytes, sizeof(bytes), frame));
  assert(frame.accelX == 4096);
  assert(frame.accelY == -4096);
  assert(frame.accelZ == 32767);
  assert(frame.temperature == -32768);
  assert(frame.gyroX == 655);
  assert(frame.gyroY == -655);
  assert(frame.gyroZ == 0);
}

void testPartialOrNullFrameFailsClosed() {
  const uint8_t partial[Mpu6Axis::kMotionFrameBytes - 1U] = {};
  Mpu6AxisRawFrame frame;
  frame.accelX = 123;
  assert(!Mpu6Axis::decodeFrame(partial, sizeof(partial), frame));
  assert(frame.accelX == 0);
  frame.accelX = 123;
  assert(!Mpu6Axis::decodeFrame(nullptr, Mpu6Axis::kMotionFrameBytes, frame));
  assert(frame.accelX == 0);
}

void testConfiguredRangeScaling() {
  Mpu6AxisRawFrame frame;
  frame.accelX = 4096;
  frame.accelY = -4096;
  frame.accelZ = 2048;
  frame.gyroX = 655;
  frame.gyroY = -655;
  frame.gyroZ = 131;

  const Mpu6AxisSample sample = Mpu6Axis::scaleFrame(frame);
  assert(nearlyEqual(sample.accelXG, 1.0F));
  assert(nearlyEqual(sample.accelYG, -1.0F));
  assert(nearlyEqual(sample.accelZG, 0.5F));
  assert(nearlyEqual(sample.gyroXDps, 10.0F));
  assert(nearlyEqual(sample.gyroYDps, -10.0F));
  assert(nearlyEqual(sample.gyroZDps, 2.0F));
}

}  // namespace

int main() {
  testIdentityClassification();
  testSignedBigEndianFrameDecoding();
  testPartialOrNullFrameFailsClosed();
  testConfiguredRangeScaling();
  std::cout << "Mpu6Axis tests passed\n";
  return 0;
}
