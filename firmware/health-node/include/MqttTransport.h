#pragma once

#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>

#include "AppConfig.h"
#include "Model.h"

class MqttTransport {
 public:
  MqttTransport();

  void begin(const char* deviceId, const char* bootId, uint32_t nowMs);
  void tick(uint32_t nowMs, uint8_t faultMask);

  bool publishTelemetry(const TelemetrySnapshot& snapshot, uint32_t nowMs);
  void enqueueFallEvent(uint32_t detectedAtMs);
  bool online();
  uint32_t droppedEventCount() const;

 private:
  struct PendingEvent {
    char eventId[48] = {};
    uint32_t sequence = 0;
    uint32_t detectedAtMs = 0;
    uint32_t nextAttemptMs = 0;
    uint8_t attempts = 0;
  };

  static uint32_t elapsed(uint32_t nowMs, uint32_t sinceMs);
  static bool deadlineReached(uint32_t nowMs, uint32_t deadlineMs);
  static uint32_t nextBackoff(uint32_t currentMs);

  void startWifiAttempt(uint32_t nowMs);
  void scheduleWifiRetry(uint32_t nowMs);
  void scheduleMqttRetry(uint32_t nowMs);
  bool connectMqtt(uint32_t nowMs, uint8_t faultMask);
  void serviceEventQueue(uint32_t nowMs);

  bool publishStatus(bool isOnline, const char* reason, uint8_t faultMask, bool retained,
                     uint32_t nowMs);
  void buildLastWill();
  void addSystem(JsonObject target, uint8_t faultMask, bool includeRuntimeValues);
  static void addFaults(JsonArray target, uint8_t faultMask);
  bool serializeAndPublish(const char* topic, bool retained);
  uint32_t allocateSequence();

  WiFiClient wifiClient_;
  PubSubClient mqtt_;
  JsonDocument document_;

  char deviceId_[32] = {};
  char bootId_[24] = {};
  char mqttClientId_[64] = {};
  char telemetryTopic_[96] = {};
  char eventTopic_[96] = {};
  char statusTopic_[96] = {};
  char lastWillPayload_[384] = {};
  char payload_[config::kMqttBufferBytes] = {};

  bool wifiConnecting_ = false;
  uint32_t wifiAttemptStartedMs_ = 0;
  uint32_t nextWifiAttemptMs_ = 0;
  uint32_t nextMqttAttemptMs_ = 0;
  uint32_t wifiBackoffMs_ = config::kReconnectBackoffMinMs;
  uint32_t mqttBackoffMs_ = config::kReconnectBackoffMinMs;
  uint32_t lastStatusMs_ = 0;
  uint32_t sequence_ = 0;

  PendingEvent eventQueue_[config::kEventQueueCapacity];
  size_t eventHead_ = 0;
  size_t eventCount_ = 0;
  uint32_t droppedEvents_ = 0;
};
