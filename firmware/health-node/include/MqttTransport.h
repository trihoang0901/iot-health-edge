#pragma once

#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>

#include "AppConfig.h"
#include "CommandContract.h"
#include "Model.h"
#include "NetworkConfig.h"
#include "NetworkConfigStore.h"
#include "NetworkRecoveryController.h"
#include "ProvisioningPortal.h"

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
  static uint32_t packIpv4(const IPAddress& address);
  static IPAddress unpackIpv4(uint32_t address);
  static bool validUuid(const char* value);

  void loadNetworkConfiguration();
  void buildBootstrapConfiguration(network::NetworkConfig& config);
  void configureRecovery(uint32_t nowMs, bool candidateTrial);
  void executeRecoveryAction(const network::RecoveryAction& action, uint32_t nowMs,
                             uint8_t faultMask);
  void startWifiProfile(uint8_t profileIndex);
  void disconnectNetwork();
  void disconnectMqtt();
  void resolveBroker(uint32_t nowMs);
  bool connectMqtt(uint32_t nowMs, uint8_t faultMask, bool useFallback);
  void rollbackCandidate(uint32_t nowMs);
  void acceptPortalCandidate(uint32_t nowMs);
  void maybePersistLastGood(uint32_t nowMs);
  void serviceEventQueue(uint32_t nowMs);

  void prepareCommandSession();
  void handleMqttMessage(char* topic, uint8_t* payload, unsigned int length);
  void serviceProvisioningCommand(uint32_t nowMs, uint8_t faultMask);
  bool commandSeen(const char* commandId) const;
  void rememberCommand(const char* commandId);

  bool publishStatus(bool isOnline, const char* reason, uint8_t faultMask,
                     bool retained, uint32_t nowMs,
                     const char* correlationId = nullptr);
  void buildLastWill();
  void addSystem(JsonObject target, uint8_t faultMask, bool includeRuntimeValues);
  static void addFaults(JsonArray target, uint8_t faultMask);
  bool serializeAndPublish(const char* topic, bool retained);
  uint32_t allocateSequence();
  static network::MqttAttemptResult classifyMqttState(int state);
  static const char* recoveryReasonText(network::RecoveryReason reason);

  WiFiClient wifiClient_;
  PubSubClient mqtt_;
  JsonDocument document_;
  network::NetworkConfigStore configStore_;
  network::NetworkRecoveryController recovery_;
  network::ProvisioningPortal portal_;

  WiFiEventHandler wifiGotIpHandler_;
  WiFiEventHandler wifiDisconnectedHandler_;
  WiFiEventHandler wifiDhcpTimeoutHandler_;

  network::NetworkRecord currentRecord_ = {};
  network::NetworkRecord committedRecord_ = {};
  network::NetworkConfig currentConfig_ = {};
  bool haveCommittedConfig_ = false;
  bool bootstrapCandidateStaged_ = false;
  bool portalCandidateTrial_ = false;
  bool hadSuccessfulConnection_ = false;

  char deviceId_[32] = {};
  char bootId_[24] = {};
  char mqttClientId_[64] = {};
  char telemetryTopic_[96] = {};
  char eventTopic_[96] = {};
  char statusTopic_[96] = {};
  char commandTopic_[112] = {};
  char commandSessionId_[command_contract::kUuidBufferBytes] = {};
  char pendingCommandId_[37] = {};
  char recentCommandIds_[4][37] = {};
  char lastWillPayload_[512] = {};
  char payload_[config::kMqttBufferBytes] = {};

  bool commandSessionPrepared_ = false;
  bool provisioningCommandPending_ = false;
  uint8_t recentCommandPosition_ = 0;
  uint32_t primaryBrokerIpv4_ = 0;
  uint32_t fallbackBrokerIpv4_ = 0;
  uint32_t selectedBrokerIpv4_ = 0;
  uint32_t lastSuccessfulBrokerIpv4_ = 0;
  uint32_t onlineSinceMs_ = 0;
  uint32_t candidatePortalDeadlineMs_ = 0;
  uint32_t lastGoodWriteMs_ = 0;
  bool lastGoodWriteMade_ = false;
  bool gotIpEvent_ = false;
  bool disconnectedEvent_ = false;
  bool dhcpTimeoutEvent_ = false;
  uint32_t eventLocalIpv4_ = 0;

  uint32_t lastStatusMs_ = 0;
  uint32_t sequence_ = 0;

  PendingEvent eventQueue_[config::kEventQueueCapacity];
  size_t eventHead_ = 0;
  size_t eventCount_ = 0;
  uint32_t droppedEvents_ = 0;
};
