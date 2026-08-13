#include "MqttTransport.h"

#include <Arduino.h>
#include <string.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Missing include/secrets.h. Copy include/secrets.example.h and set local values."
#endif

namespace {

constexpr uint8_t kEventPublishAttempts = 3;
constexpr uint32_t kEventRetryMs = 1000;

void setNullable(JsonObject object, const char* key, const NullableMeasurement& measurement) {
  if (measurement.valid && isfinite(measurement.value)) {
    object[key] = measurement.value;
  } else {
    object[key] = nullptr;
  }
}

}  // namespace

MqttTransport::MqttTransport() : mqtt_(wifiClient_) {}

uint32_t MqttTransport::elapsed(uint32_t nowMs, uint32_t sinceMs) {
  return static_cast<uint32_t>(nowMs - sinceMs);
}

bool MqttTransport::deadlineReached(uint32_t nowMs, uint32_t deadlineMs) {
  return static_cast<int32_t>(nowMs - deadlineMs) >= 0;
}

uint32_t MqttTransport::nextBackoff(uint32_t currentMs) {
  if (currentMs >= config::kReconnectBackoffMaxMs / 2U) {
    return config::kReconnectBackoffMaxMs;
  }
  return currentMs * 2U;
}

void MqttTransport::begin(const char* deviceId, const char* bootId, uint32_t nowMs) {
  snprintf(deviceId_, sizeof(deviceId_), "%s", deviceId);
  snprintf(bootId_, sizeof(bootId_), "%s", bootId);
  snprintf(mqttClientId_, sizeof(mqttClientId_), "%s-%s", deviceId_, bootId_);
  snprintf(telemetryTopic_, sizeof(telemetryTopic_),
           "iot-health/v1/devices/%s/telemetry", deviceId_);
  snprintf(eventTopic_, sizeof(eventTopic_), "iot-health/v1/devices/%s/event", deviceId_);
  snprintf(statusTopic_, sizeof(statusTopic_), "iot-health/v1/devices/%s/status", deviceId_);

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.hostname(deviceId_);

  mqtt_.setServer(MQTT_HOST, MQTT_PORT);
  wifiClient_.setTimeout(config::kTcpClientTimeoutMs);
  mqtt_.setBufferSize(config::kMqttBufferBytes);
  mqtt_.setKeepAlive(config::kMqttKeepAliveSeconds);
  mqtt_.setSocketTimeout(config::kMqttSocketTimeoutSeconds);

  randomSeed(ESP.getCycleCount());
  nextWifiAttemptMs_ = nowMs;
  nextMqttAttemptMs_ = nowMs;
  lastStatusMs_ = nowMs;
  buildLastWill();
}

void MqttTransport::tick(uint32_t nowMs, uint8_t faultMask) {
  if (WiFi.status() != WL_CONNECTED) {
    if (mqtt_.connected()) {
      mqtt_.disconnect();
    }

    if (wifiConnecting_ &&
        elapsed(nowMs, wifiAttemptStartedMs_) >= config::kWifiConnectTimeoutMs) {
      WiFi.disconnect(false);
      wifiConnecting_ = false;
      scheduleWifiRetry(nowMs);
    }

    if (!wifiConnecting_ && deadlineReached(nowMs, nextWifiAttemptMs_)) {
      startWifiAttempt(nowMs);
    }
    return;
  }

  if (wifiConnecting_) {
    wifiConnecting_ = false;
    wifiBackoffMs_ = config::kReconnectBackoffMinMs;
    nextMqttAttemptMs_ = nowMs;
    Serial.print(F("wifi_connected ip="));
    Serial.println(WiFi.localIP());
  }

  if (!mqtt_.connected()) {
    if (deadlineReached(nowMs, nextMqttAttemptMs_)) {
      connectMqtt(nowMs, faultMask);
    }
    return;
  }

  if (!mqtt_.loop()) {
    scheduleMqttRetry(nowMs);
    return;
  }

  serviceEventQueue(nowMs);
  if (elapsed(nowMs, lastStatusMs_) >= config::kStatusPeriodMs) {
    publishStatus(true, "heartbeat", faultMask, true, nowMs);
  }
}

void MqttTransport::startWifiAttempt(uint32_t nowMs) {
  Serial.println(F("wifi_connecting"));
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  wifiConnecting_ = true;
  wifiAttemptStartedMs_ = nowMs;
}

void MqttTransport::scheduleWifiRetry(uint32_t nowMs) {
  const uint32_t jitterMs = static_cast<uint32_t>(random(0, 251));
  nextWifiAttemptMs_ = nowMs + wifiBackoffMs_ + jitterMs;
  wifiBackoffMs_ = nextBackoff(wifiBackoffMs_);
}

void MqttTransport::scheduleMqttRetry(uint32_t nowMs) {
  const uint32_t jitterMs = static_cast<uint32_t>(random(0, 251));
  nextMqttAttemptMs_ = nowMs + mqttBackoffMs_ + jitterMs;
  mqttBackoffMs_ = nextBackoff(mqttBackoffMs_);
}

bool MqttTransport::connectMqtt(uint32_t /*nowMs*/, uint8_t faultMask) {
  buildLastWill();
  const bool connected = mqtt_.connect(mqttClientId_, MQTT_USERNAME, MQTT_PASSWORD, statusTopic_,
                                       0, true, lastWillPayload_, true);
  const uint32_t completedAtMs = millis();
  if (!connected) {
    Serial.printf("mqtt_connect_failed state=%d\n", mqtt_.state());
    // connect() is synchronous, so schedule relative to completion rather than
    // the stale timestamp captured before the bounded TCP/CONNACK wait.
    scheduleMqttRetry(completedAtMs);
    return false;
  }

  mqttBackoffMs_ = config::kReconnectBackoffMinMs;
  nextMqttAttemptMs_ = completedAtMs;
  Serial.println(F("mqtt_connected"));
  publishStatus(true, "connected", faultMask, true, completedAtMs);
  return true;
}

bool MqttTransport::publishTelemetry(const TelemetrySnapshot& snapshot, uint32_t nowMs) {
  if (!mqtt_.connected()) {
    return false;
  }

  document_.clear();
  document_["schema"] = "health.telemetry.v2";
  document_["device_id"] = deviceId_;
  document_["boot_id"] = bootId_;
  document_["seq"] = allocateSequence();
  document_["uptime_ms"] = nowMs;

  JsonObject vitals = document_["vitals"].to<JsonObject>();
  setNullable(vitals, "heart_rate_bpm", snapshot.heartRateBpm);
  setNullable(vitals, "spo2_pct", snapshot.spo2Pct);

  JsonObject environment = document_["environment"].to<JsonObject>();
  setNullable(environment, "ambient_temp_c", snapshot.ambientTempC);
  setNullable(environment, "humidity_pct", snapshot.humidityPct);

  JsonObject motion = document_["motion"].to<JsonObject>();
  if (snapshot.motionValid && isfinite(snapshot.accelMagnitudeG) &&
      isfinite(snapshot.gyroMagnitudeDps)) {
    motion["accel_g"] = snapshot.accelMagnitudeG;
    motion["gyro_dps"] = snapshot.gyroMagnitudeDps;
  } else {
    motion["accel_g"] = nullptr;
    motion["gyro_dps"] = nullptr;
  }
  motion["fall_state"] = snapshot.motionValid ? snapshot.fallState : "unknown";

  JsonObject quality = document_["quality"].to<JsonObject>();
  quality["ppg"] = constrain(snapshot.ppgQuality, 0.0F, 1.0F);
  quality["finger_present"] = snapshot.fingerPresent;
  quality["motion_artifact"] = snapshot.motionArtifact;
  quality["heart_rate_valid"] = snapshot.heartRateBpm.valid;
  quality["spo2_valid"] = snapshot.spo2Pct.valid;
  quality["ambient_temp_valid"] = snapshot.ambientTempC.valid;
  quality["humidity_valid"] = snapshot.humidityPct.valid;
  quality["motion_valid"] = snapshot.motionValid;

  JsonObject system = document_["system"].to<JsonObject>();
  addSystem(system, snapshot.faultMask, true);
  return serializeAndPublish(telemetryTopic_, false);
}

void MqttTransport::enqueueFallEvent(uint32_t detectedAtMs) {
  if (eventCount_ == config::kEventQueueCapacity) {
    eventHead_ = (eventHead_ + 1U) % config::kEventQueueCapacity;
    --eventCount_;
    ++droppedEvents_;
  }

  const size_t tail = (eventHead_ + eventCount_) % config::kEventQueueCapacity;
  PendingEvent& event = eventQueue_[tail];
  event.sequence = allocateSequence();
  event.detectedAtMs = detectedAtMs;
  event.nextAttemptMs = detectedAtMs;
  event.attempts = 0;
  snprintf(event.eventId, sizeof(event.eventId), "%s-%lu", bootId_,
           static_cast<unsigned long>(event.sequence));
  ++eventCount_;
}

void MqttTransport::serviceEventQueue(uint32_t nowMs) {
  if (!mqtt_.connected() || eventCount_ == 0) {
    return;
  }

  PendingEvent& event = eventQueue_[eventHead_];
  if (!deadlineReached(nowMs, event.nextAttemptMs)) {
    return;
  }

  document_.clear();
  document_["schema"] = "health.event.v1";
  document_["device_id"] = deviceId_;
  document_["boot_id"] = bootId_;
  document_["event_id"] = event.eventId;
  document_["seq"] = event.sequence;
  document_["uptime_ms"] = event.detectedAtMs;
  document_["type"] = "fall_suspected_demo";

  if (!serializeAndPublish(eventTopic_, false)) {
    event.nextAttemptMs = nowMs + kEventRetryMs;
    return;
  }

  ++event.attempts;
  if (event.attempts >= kEventPublishAttempts) {
    eventHead_ = (eventHead_ + 1U) % config::kEventQueueCapacity;
    --eventCount_;
  } else {
    event.nextAttemptMs = nowMs + kEventRetryMs;
  }
}

bool MqttTransport::publishStatus(bool isOnline, const char* reason, uint8_t faultMask,
                                  bool retained, uint32_t nowMs) {
  if (!mqtt_.connected()) {
    return false;
  }

  document_.clear();
  document_["schema"] = "health.status.v1";
  document_["device_id"] = deviceId_;
  document_["boot_id"] = bootId_;
  document_["seq"] = allocateSequence();
  document_["uptime_ms"] = nowMs;
  document_["online"] = isOnline;
  document_["reason"] = reason;
  JsonObject system = document_["system"].to<JsonObject>();
  addSystem(system, faultMask, true);

  const bool published = serializeAndPublish(statusTopic_, retained);
  if (published) {
    lastStatusMs_ = nowMs;
  }
  return published;
}

void MqttTransport::buildLastWill() {
  document_.clear();
  document_["schema"] = "health.status.v1";
  document_["device_id"] = deviceId_;
  document_["boot_id"] = bootId_;
  document_["seq"] = sequence_;
  document_["uptime_ms"] = 0;
  document_["online"] = false;
  document_["reason"] = "mqtt_lost";
  JsonObject system = document_["system"].to<JsonObject>();
  addSystem(system, kFaultNone, false);
  serializeJson(document_, lastWillPayload_, sizeof(lastWillPayload_));
}

void MqttTransport::addSystem(JsonObject target, uint8_t faultMask,
                              bool includeRuntimeValues) {
  if (includeRuntimeValues && WiFi.status() == WL_CONNECTED) {
    target["rssi_dbm"] = WiFi.RSSI();
  } else {
    target["rssi_dbm"] = nullptr;
  }
  if (includeRuntimeValues) {
    target["free_heap"] = ESP.getFreeHeap();
  } else {
    target["free_heap"] = nullptr;
  }
  target["fw"] = config::kFirmwareVersion;
  JsonArray faults = target["faults"].to<JsonArray>();
  addFaults(faults, faultMask);
  if (droppedEvents_ > 0U) {
    faults.add("event_queue_overflow");
  }
}

void MqttTransport::addFaults(JsonArray target, uint8_t faultMask) {
  if ((faultMask & kFaultMax30102) != 0U) {
    target.add("max30102_unavailable");
  }
  if ((faultMask & kFaultMpu6050) != 0U) {
    target.add("mpu6050_unavailable");
  }
  if ((faultMask & kFaultDht11) != 0U) {
    target.add("dht11_unavailable");
  }
  if ((faultMask & kFaultPpgOverflow) != 0U) {
    target.add("ppg_sample_loss");
  }
}

bool MqttTransport::serializeAndPublish(const char* topic, bool retained) {
  const size_t requiredLength = measureJson(document_);
  // PubSubClient uses one packet buffer for MQTT headers, topic, and payload.
  constexpr size_t kMqttPacketOverheadBudget = 8;
  if (requiredLength == 0 || requiredLength + 1U > sizeof(payload_) ||
      requiredLength + strlen(topic) + kMqttPacketOverheadBudget >
          config::kMqttBufferBytes) {
    return false;
  }
  const size_t payloadLength = serializeJson(document_, payload_, sizeof(payload_));
  if (payloadLength != requiredLength) {
    return false;
  }
  return mqtt_.publish(topic, reinterpret_cast<const uint8_t*>(payload_),
                       static_cast<unsigned int>(payloadLength), retained);
}

uint32_t MqttTransport::allocateSequence() {
  ++sequence_;
  if (sequence_ == 0) {
    ++sequence_;
  }
  return sequence_;
}

bool MqttTransport::online() {
  return WiFi.status() == WL_CONNECTED && mqtt_.connected();
}

uint32_t MqttTransport::droppedEventCount() const {
  return droppedEvents_;
}
