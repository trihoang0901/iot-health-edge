#include <Arduino.h>
#include <Wire.h>

#include "AppConfig.h"
#include "FallDetector.h"
#include "LocalControls.h"
#include "MqttTransport.h"
#include "SensorHub.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Missing include/secrets.h. Copy include/secrets.example.h and set local values."
#endif

namespace {

SensorHub sensorHub;
FallDetector fallDetector;
MqttTransport transport;
LocalControls localControls;

char deviceId[32] = {};
char bootId[24] = {};
uint32_t lastTelemetryMs = 0;

uint32_t elapsed(uint32_t nowMs, uint32_t sinceMs) {
  return static_cast<uint32_t>(nowMs - sinceMs);
}

void buildIdentity() {
  const uint32_t bootEntropyHigh = ESP.random();
  const uint32_t bootEntropyLow = ESP.random();
  static_assert(sizeof(DEVICE_ID) <= sizeof(deviceId),
                "DEVICE_ID must be at most 31 characters");
  snprintf(deviceId, sizeof(deviceId), "%s", DEVICE_ID);
  snprintf(bootId, sizeof(bootId), "%08lx%08lx",
           static_cast<unsigned long>(bootEntropyHigh),
           static_cast<unsigned long>(bootEntropyLow));
}

}  // namespace

void setup() {
  Serial.begin(config::kSerialBaud);
  Serial.println();
  Serial.println(F("IoT Health Edge - non-clinical demonstration firmware"));

  const uint32_t nowMs = millis();
  buildIdentity();
  localControls.begin(nowMs);

  Wire.begin(config::kI2cSdaPin, config::kI2cSclPin);
  Wire.setClock(config::kI2cClockHz);
  Wire.setClockStretchLimit(config::kI2cClockStretchLimitUs);

  sensorHub.begin(nowMs);
  transport.begin(deviceId, bootId, nowMs);
  lastTelemetryMs = nowMs;

  Serial.printf("device_id=%s boot_id=%s fw=%s\n", deviceId, bootId,
                config::kFirmwareVersion);
}

void loop() {
  const uint32_t nowMs = millis();

  sensorHub.tick(nowMs);
  FallSample motionSample;
  if (sensorHub.takeMotionSample(motionSample)) {
    const FallUpdate update = fallDetector.update(motionSample, nowMs);
    if (update.triggered) {
      transport.enqueueFallEvent(nowMs);
    }
  }

  if (localControls.takeAcknowledgement()) {
    fallDetector.acknowledge(nowMs);
  }
  sensorHub.setFallState(fallDetector.publicState());

  transport.tick(nowMs, sensorHub.snapshot().faultMask);
  localControls.tick(nowMs, fallDetector.alarmActive(), transport.online());

  if (elapsed(nowMs, lastTelemetryMs) >= config::kTelemetryPeriodMs) {
    lastTelemetryMs = nowMs;
    transport.publishTelemetry(sensorHub.snapshot(), nowMs);
  }

  // ESP8266 services its Wi-Fi stack here. TCP/DNS plus MQTT CONNACK can pause
  // this loop for roughly two seconds; SensorHub fails closed after that gap.
  yield();
}
