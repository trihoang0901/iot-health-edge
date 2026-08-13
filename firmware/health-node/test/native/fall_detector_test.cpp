#include <assert.h>
#include <stdint.h>

#include <iostream>

#include "FallDetector.h"

namespace {

FallSample motion(float accelG, float gyroDps = 0.0F) {
  FallSample sample;
  sample.accelMagnitudeG = accelG;
  sample.gyroMagnitudeDps = gyroDps;
  sample.valid = true;
  return sample;
}

bool holdStill(FallDetector& detector, uint32_t startMs, uint32_t durationMs) {
  bool triggered = false;
  for (uint32_t offset = 0; offset <= durationMs; offset += 20U) {
    triggered = detector.update(motion(1.0F), startMs + offset).triggered || triggered;
  }
  return triggered;
}

void testNormalMotionDoesNotTrigger() {
  FallDetector detector;
  for (uint32_t nowMs = 0; nowMs < 10000; nowMs += 20U) {
    const float accel = (nowMs % 400U == 0U) ? 1.6F : 1.0F;
    assert(!detector.update(motion(accel, 15.0F), nowMs).triggered);
  }
  assert(detector.phase() == FallPhase::kIdle);
}

void testShortLowGDoesNotBypassMinimum() {
  FallDetector detector;
  detector.update(motion(0.2F), 100);
  detector.update(motion(3.0F), 180);
  assert(!holdStill(detector, 200, 2000));
  assert(!detector.alarmActive());
}

void testTransientLowGDoesNotRemainArmed() {
  FallDetector detector;
  detector.update(motion(0.2F), 100);
  detector.update(motion(1.0F), 180);
  assert(detector.phase() == FallPhase::kIdle);
  detector.update(motion(1.0F), 260);
  assert(!holdStill(detector, 280, 2000));
  assert(!detector.alarmActive());
}

void testQualifiedLowGImpactStillnessTriggersOnce() {
  FallDetector detector;
  detector.update(motion(0.2F), 100);
  detector.update(motion(0.2F), 260);
  detector.update(motion(3.0F), 280);
  assert(holdStill(detector, 300, 1700));
  assert(detector.alarmActive());
  assert(!detector.update(motion(1.0F), 2020).triggered);
}

void testImpactFirstPathTriggers() {
  FallDetector detector;
  detector.update(motion(3.1F), 100);
  assert(holdStill(detector, 120, 1700));
  assert(detector.alarmActive());
  assert(detector.acknowledge(1900));
  assert(detector.phase() == FallPhase::kRefractory);
  assert(!detector.acknowledge(1920));
}

void testContinuedMotionCancelsCandidate() {
  FallDetector detector;
  detector.update(motion(3.1F), 100);
  for (uint32_t nowMs = 120; nowMs < 4000; nowMs += 20U) {
    assert(!detector.update(motion(1.35F, 60.0F), nowMs).triggered);
  }
  assert(!detector.alarmActive());
  assert(detector.phase() == FallPhase::kIdle);
}

void testSampleGapCancelsCandidate() {
  FallDetector detector;
  detector.update(motion(3.1F), 100);
  detector.update(motion(1.0F), 120);
  detector.update(motion(1.0F), 500);
  assert(detector.phase() == FallPhase::kIdle);
}

}  // namespace

int main() {
  testNormalMotionDoesNotTrigger();
  testShortLowGDoesNotBypassMinimum();
  testTransientLowGDoesNotRemainArmed();
  testQualifiedLowGImpactStillnessTriggersOnce();
  testImpactFirstPathTriggers();
  testContinuedMotionCancelsCandidate();
  testSampleGapCancelsCandidate();
  std::cout << "FallDetector tests passed\n";
  return 0;
}
