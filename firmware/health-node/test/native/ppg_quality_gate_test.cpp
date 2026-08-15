#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

#include <iostream>

#include "PpgQualityGate.h"

namespace {

constexpr size_t kSamples = PpgQualityGate::kRequiredSamples;
constexpr float kSampleRateHz = 25.0F;
constexpr float kPi = 3.14159265358979323846F;

void makeSignal(float bpm, uint32_t* red, uint32_t* ir,
                float irAmplitude = 6000.0F) {
  const float frequencyHz = bpm / 60.0F;
  for (size_t index = 0; index < kSamples; ++index) {
    const float phase = 2.0F * kPi * frequencyHz *
                        static_cast<float>(index) / kSampleRateHz;
    ir[index] = static_cast<uint32_t>(100000.0F + irAmplitude * sinf(phase));
    red[index] = static_cast<uint32_t>(80000.0F + 0.6F * irAmplitude * sinf(phase - 0.15F));
  }
}

PpgGateInput inputFor(const uint32_t* red, const uint32_t* ir, float bpm,
                      float spo2 = 97.0F) {
  PpgGateInput input;
  input.redSamples = red;
  input.irSamples = ir;
  input.sampleCount = kSamples;
  input.sampleRateHz = kSampleRateHz;
  input.fingerPresent = true;
  input.motionCoverageValid = true;
  input.heartRateCandidateBpm = bpm;
  input.heartRateCandidateValid = true;
  input.spo2CandidatePct = spo2;
  input.spo2CandidateValid = true;
  return input;
}

void testWarmingUpRequiresThreeConsistentWindows() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  makeSignal(72.0F, red, ir);
  PpgQualityGate gate;
  PpgGateInput input = inputFor(red, ir, 72.0F);

  PpgGateResult result = gate.evaluate(input);
  assert(strcmp(result.state, "warming_up") == 0);
  assert(!result.confirmedHeartRateValid);
  result = gate.evaluate(input);
  assert(strcmp(result.state, "warming_up") == 0);
  assert(!result.confirmedHeartRateValid);
  result = gate.evaluate(input);
  assert(strcmp(result.state, "valid") == 0);
  assert(result.confirmedHeartRateValid);
  assert(result.confirmedHeartRateBpm >= 70.0F &&
         result.confirmedHeartRateBpm <= 74.0F);
  assert(result.confirmedSpo2Valid);
}

void testIncompleteWindowIsWarmingUp() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  makeSignal(72.0F, red, ir);
  PpgQualityGate gate;
  PpgGateInput input = inputFor(red, ir, 72.0F);
  input.sampleCount = 50;
  const PpgGateResult result = gate.evaluate(input);
  assert(strcmp(result.state, "warming_up") == 0);
  assert(!result.confirmedHeartRateValid);
}

void testSingleSpikeIsNotHeldOrConfirmed() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  PpgQualityGate gate;
  makeSignal(72.0F, red, ir);
  const PpgGateInput stable = inputFor(red, ir, 72.0F);
  gate.evaluate(stable);
  gate.evaluate(stable);
  assert(gate.evaluate(stable).confirmedHeartRateValid);

  makeSignal(180.0F, red, ir);
  const PpgGateResult spike = gate.evaluate(inputFor(red, ir, 180.0F));
  assert(strcmp(spike.state, "unstable") == 0);
  assert(spike.rawHeartRateValid);
  assert(!spike.confirmedHeartRateValid);
}

void testRawCandidateMustAgreeWithRrMedian() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  makeSignal(72.0F, red, ir);
  PpgQualityGate gate;
  const PpgGateResult result = gate.evaluate(inputFor(red, ir, 150.0F));
  assert(strcmp(result.state, "unstable") == 0);
  assert(result.rawHeartRateValid);
  assert(!result.confirmedHeartRateValid);
}

void testLargeJumpNeedsThreeNewWindows() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  PpgQualityGate gate;
  makeSignal(72.0F, red, ir);
  const PpgGateInput stable = inputFor(red, ir, 72.0F);
  gate.evaluate(stable);
  gate.evaluate(stable);
  assert(gate.evaluate(stable).confirmedHeartRateValid);

  makeSignal(105.0F, red, ir);
  const PpgGateInput jump = inputFor(red, ir, 105.0F);
  assert(!gate.evaluate(jump).confirmedHeartRateValid);
  assert(!gate.evaluate(jump).confirmedHeartRateValid);
  const PpgGateResult accepted = gate.evaluate(jump);
  assert(strcmp(accepted.state, "valid") == 0);
  assert(accepted.confirmedHeartRateValid);
  assert(accepted.confirmedHeartRateBpm >= 103.0F &&
         accepted.confirmedHeartRateBpm <= 107.0F);
}

void testUnstableSpo2CannotConfirmEitherVital() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  makeSignal(72.0F, red, ir);
  PpgQualityGate gate;

  assert(!gate.evaluate(inputFor(red, ir, 72.0F, 50.0F)).confirmedSpo2Valid);
  assert(!gate.evaluate(inputFor(red, ir, 72.0F, 100.0F)).confirmedSpo2Valid);
  const PpgGateResult result = gate.evaluate(inputFor(red, ir, 72.0F, 50.0F));
  assert(strcmp(result.state, "unstable") == 0);
  assert(!result.confirmedHeartRateValid);
  assert(!result.confirmedSpo2Valid);
}

void testClippingFailsClosed() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  makeSignal(72.0F, red, ir);
  for (size_t index = 0; index < 4; ++index) {
    ir[index] = 0x3FFFFU;
  }
  PpgQualityGate gate;
  const PpgGateResult result = gate.evaluate(inputFor(red, ir, 72.0F));
  assert(strcmp(result.state, "clipping") == 0);
  assert(!result.confirmedHeartRateValid);
}

void testLowPerfusionFailsClosed() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  makeSignal(72.0F, red, ir, 100.0F);
  PpgQualityGate gate;
  const PpgGateResult result = gate.evaluate(inputFor(red, ir, 72.0F));
  assert(strcmp(result.state, "low_perfusion") == 0);
  assert(!result.confirmedHeartRateValid);
}

void testMotionFailsClosed() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  makeSignal(72.0F, red, ir);
  PpgQualityGate gate;
  PpgGateInput input = inputFor(red, ir, 72.0F);
  input.motionArtifact = true;
  const PpgGateResult result = gate.evaluate(input);
  assert(strcmp(result.state, "motion") == 0);
  assert(!result.confirmedHeartRateValid);
}

void testNoFingerAndSampleLossAreExplicit() {
  uint32_t red[kSamples] = {};
  uint32_t ir[kSamples] = {};
  makeSignal(72.0F, red, ir);
  PpgQualityGate gate;
  PpgGateInput input = inputFor(red, ir, 72.0F);
  input.fingerPresent = false;
  PpgGateResult result = gate.evaluate(input);
  assert(strcmp(result.state, "no_finger") == 0);
  assert(!result.rawHeartRateValid);
  input.fingerPresent = true;
  input.sampleLoss = true;
  result = gate.evaluate(input);
  assert(strcmp(result.state, "sample_loss") == 0);
  assert(!result.rawHeartRateValid);
  assert(!result.rawSpo2Valid);
  assert(!result.confirmedHeartRateValid);
}

}  // namespace

int main() {
  testWarmingUpRequiresThreeConsistentWindows();
  testIncompleteWindowIsWarmingUp();
  testSingleSpikeIsNotHeldOrConfirmed();
  testRawCandidateMustAgreeWithRrMedian();
  testLargeJumpNeedsThreeNewWindows();
  testUnstableSpo2CannotConfirmEitherVital();
  testClippingFailsClosed();
  testLowPerfusionFailsClosed();
  testMotionFailsClosed();
  testNoFingerAndSampleLossAreExplicit();
  std::cout << "PpgQualityGate tests passed\n";
  return 0;
}
