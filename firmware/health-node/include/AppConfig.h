#pragma once

#include <Arduino.h>

#ifndef ENABLE_LOCAL_BUZZER
#define ENABLE_LOCAL_BUZZER 0
#endif

#ifndef ENABLE_LOCAL_ACK_BUTTON
#define ENABLE_LOCAL_ACK_BUTTON 0
#endif

#ifndef ENABLE_BUILTIN_LED
#define ENABLE_BUILTIN_LED 1
#endif

namespace config {

constexpr char kFirmwareVersion[] = "0.3.0";

constexpr uint8_t kI2cSdaPin = D2;       // GPIO4
constexpr uint8_t kI2cSclPin = D1;       // GPIO5
constexpr uint8_t kDs18b20Pin = D5;      // GPIO14, powered 3-wire mode
constexpr uint8_t kBuzzerPin = D6;       // GPIO12, optional through 1 kOhm + 2N2222
constexpr uint8_t kAckButtonPin = D7;    // GPIO13, optional button to GND

constexpr uint32_t kSerialBaud = 115200;
constexpr uint32_t kI2cClockHz = 400000;
// Hardware sensors used here do not require long clock stretching. Keeping the
// per-edge wait short bounds a physically stuck I2C transaction below the
// fall detector's 250 ms maximum sample gap, even for a full MAX30102 burst.
constexpr uint32_t kI2cClockStretchLimitUs = 50;

constexpr uint32_t kImuPeriodMs = 20;          // 50 Hz
constexpr uint32_t kTelemetryPeriodMs = 1000;
constexpr uint32_t kStatusPeriodMs = 30000;
constexpr uint32_t kTemperaturePeriodMs = 2000;
constexpr uint32_t kTemperatureConversionMs = 750;  // DS18B20, 12-bit
constexpr uint32_t kSensorRetryMs = 10000;
constexpr uint32_t kPpgWindowRefreshMs = 1000;
constexpr uint32_t kPpgStaleMs = 5000;
constexpr uint32_t kPpgMaximumSamplingGapMs = 250;

constexpr uint32_t kReconnectBackoffMinMs = 1000;
constexpr uint32_t kReconnectBackoffMaxMs = 30000;
constexpr uint32_t kWifiConnectTimeoutMs = 12000;
constexpr uint16_t kMqttKeepAliveSeconds = 15;
constexpr uint16_t kMqttSocketTimeoutSeconds = 1;
constexpr uint32_t kTcpClientTimeoutMs = 1000;
constexpr size_t kMqttBufferBytes = 1024;
constexpr size_t kEventQueueCapacity = 4;

constexpr uint32_t kButtonDebounceMs = 40;
constexpr uint32_t kBuzzerOnMs = 180;
constexpr uint32_t kBuzzerOffMs = 320;

// Starting values for a controlled demonstration only; calibrate from recorded traces.
constexpr uint32_t kFingerIrThreshold = 50000;
constexpr float kMotionArtifactAccelDeviationG = 0.20F;
constexpr float kMotionArtifactGyroDps = 35.0F;

}  // namespace config
