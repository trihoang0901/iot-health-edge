#include <assert.h>
#include <stdint.h>

#include <iostream>

#include "Ds18b20Schedule.h"

namespace {

void testConversionDeadlineAndCycleCadence() {
  Ds18b20Schedule schedule;
  schedule.beginConversion(1000U);
  assert(!schedule.conversionDue(1749U));
  assert(schedule.conversionDue(1750U));

  schedule.acceptMeasurement();
  assert(schedule.measurementValid());
  assert(!schedule.cycleDue(2999U));
  assert(schedule.cycleDue(3000U));
}

void testRetryDeadline() {
  Ds18b20Schedule schedule;
  schedule.invalidate(500U);
  assert(!schedule.retryDue(10499U));
  assert(schedule.retryDue(10500U));
}

void testUnsignedMillisRollover() {
  Ds18b20Schedule schedule;
  constexpr uint32_t requestedAt = UINT32_MAX - 249U;
  schedule.beginConversion(requestedAt);
  assert(!schedule.conversionDue(499U));
  assert(schedule.conversionDue(500U));

  constexpr uint32_t failedAt = UINT32_MAX - 99U;
  schedule.invalidate(failedAt);
  assert(!schedule.retryDue(9899U));
  assert(schedule.retryDue(9900U));
}

void testInvalidationCancelsPendingConversionAndCycle() {
  Ds18b20Schedule schedule;
  schedule.beginConversion(0U);
  schedule.acceptMeasurement();
  assert(schedule.measurementValid());
  schedule.beginConversion(2750U);
  schedule.invalidate(2800U);
  assert(schedule.state() == Ds18b20ScheduleState::kUnavailable);
  assert(!schedule.measurementValid());
  assert(!schedule.conversionDue(10000U));
  assert(!schedule.cycleDue(10000U));
  assert(!schedule.retryDue(12799U));
  assert(schedule.retryDue(12800U));
}

}  // namespace

int main() {
  testConversionDeadlineAndCycleCadence();
  testRetryDeadline();
  testUnsignedMillisRollover();
  testInvalidationCancelsPendingConversionAndCycle();
  std::cout << "Ds18b20Schedule tests passed\n";
  return 0;
}
