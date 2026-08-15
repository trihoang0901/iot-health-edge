#include "MqttTransport.h"

#include <Arduino.h>
#include <ctype.h>
#include <string.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Missing include/secrets.h. Copy include/secrets.example.h and set local values."
#endif

#if __has_include("provisioning_secret.h")
#include "provisioning_secret.h"
#else
#error "Missing include/provisioning_secret.h. Generate it before the deliberate 0.4.0 flash."
#endif

static_assert(sizeof(PROVISIONING_AP_PASSWORD) - 1U >= 20U,
              "PROVISIONING_AP_PASSWORD must contain at least 20 characters");
static_assert(sizeof(PROVISIONING_AP_PASSWORD) - 1U <= 63U,
              "PROVISIONING_AP_PASSWORD must contain at most 63 characters");
static_assert(sizeof(WIFI_SSID) - 1U <= network::kMaxSsidBytes,
              "WIFI_SSID must contain at most 32 bytes");
static_assert(sizeof(WIFI_PASSWORD) - 1U >= 8U &&
                  sizeof(WIFI_PASSWORD) - 1U <= network::kMaxWifiPasswordBytes,
              "WIFI_PASSWORD must contain 8..63 bytes; open networks are rejected");
static_assert(sizeof(MQTT_HOST) - 1U <= network::kMaxBrokerHostBytes,
              "MQTT_HOST is too long for the runtime network record");

namespace {

constexpr uint8_t kEventPublishAttempts = 3;
constexpr uint32_t kEventRetryMs = 1000;

bool isUsableBrokerAddress(uint32_t address, uint32_t localAddress,
                           uint32_t subnetMask) {
  if (!network::isUsableUnicastIpv4(address)) {
    return false;
  }
  if (!network::isUsableUnicastIpv4(localAddress) || subnetMask == 0U ||
      (address & subnetMask) != (localAddress & subnetMask)) {
    return true;
  }
  const uint32_t subnet = localAddress & subnetMask;
  const uint32_t broadcast = subnet | ~subnetMask;
  return address != subnet && address != broadcast && address != localAddress;
}

void setNullable(JsonObject object, const char* key,
                 const NullableMeasurement& measurement) {
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

uint32_t MqttTransport::packIpv4(const IPAddress& address) {
  return (static_cast<uint32_t>(address[0]) << 24U) |
         (static_cast<uint32_t>(address[1]) << 16U) |
         (static_cast<uint32_t>(address[2]) << 8U) |
         static_cast<uint32_t>(address[3]);
}

IPAddress MqttTransport::unpackIpv4(uint32_t address) {
  return IPAddress(static_cast<uint8_t>(address >> 24U),
                   static_cast<uint8_t>(address >> 16U),
                   static_cast<uint8_t>(address >> 8U),
                   static_cast<uint8_t>(address));
}

bool MqttTransport::validUuid(const char* value) {
  return command_contract::isCanonicalUuid(value);
}

void MqttTransport::buildBootstrapConfiguration(network::NetworkConfig& config) {
  config = network::NetworkConfig();
  snprintf(config.brokerHost, sizeof(config.brokerHost), "%s", MQTT_HOST);
  config.brokerPort = MQTT_PORT;
  config.lastGoodProfile = -1;
  network::WifiProfile& profile = config.profiles[0];
  snprintf(profile.ssid, sizeof(profile.ssid), "%s", WIFI_SSID);
  snprintf(profile.password, sizeof(profile.password), "%s", WIFI_PASSWORD);
  profile.enabled = 1;
  profile.priority = 0;
}

void MqttTransport::loadNetworkConfiguration() {
  const bool storeReady = configStore_.begin();
  if (storeReady && configStore_.loadCommitted(committedRecord_)) {
    currentRecord_ = committedRecord_;
    currentConfig_ = currentRecord_.config;
    haveCommittedConfig_ = true;
    Serial.println(F("network_config_loaded"));
    return;
  }

  buildBootstrapConfiguration(currentConfig_);
  if (!network::validateConfig(currentConfig_)) {
    currentConfig_ = network::NetworkConfig();
    currentConfig_.brokerPort = MQTT_PORT;
    currentConfig_.lastGoodProfile = -1;
    Serial.println(F("network_bootstrap_invalid"));
    return;
  }
  if (storeReady && configStore_.writeCandidate(currentConfig_, currentRecord_)) {
    bootstrapCandidateStaged_ = true;
  }
  Serial.println(F("network_config_bootstrap"));
}

void MqttTransport::configureRecovery(uint32_t nowMs, bool candidateTrial) {
  network::RecoveryProfile profiles[network::kMaxWifiProfiles] = {};
  for (size_t index = 0; index < network::kMaxWifiProfiles; ++index) {
    profiles[index].enabled = currentConfig_.profiles[index].enabled != 0U;
    profiles[index].priority = currentConfig_.profiles[index].priority;
  }
  recovery_.configure(profiles, currentConfig_.lastGoodProfile, nowMs,
                      candidateTrial);
}

void MqttTransport::begin(const char* deviceId, const char* bootId,
                          uint32_t nowMs) {
  snprintf(deviceId_, sizeof(deviceId_), "%s", deviceId);
  snprintf(bootId_, sizeof(bootId_), "%s", bootId);
  snprintf(mqttClientId_, sizeof(mqttClientId_), "%s-%s", deviceId_, bootId_);
  snprintf(telemetryTopic_, sizeof(telemetryTopic_),
           "iot-health/v1/devices/%s/telemetry", deviceId_);
  snprintf(eventTopic_, sizeof(eventTopic_),
           "iot-health/v1/devices/%s/event", deviceId_);
  snprintf(statusTopic_, sizeof(statusTopic_),
           "iot-health/v1/devices/%s/status", deviceId_);
  snprintf(commandTopic_, sizeof(commandTopic_),
           "iot-health/v1/devices/%s/command/%s", deviceId_, bootId_);

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.hostname(deviceId_);
  wifiGotIpHandler_ = WiFi.onStationModeGotIP(
      [this](const WiFiEventStationModeGotIP& event) {
        gotIpEvent_ = true;
        eventLocalIpv4_ = packIpv4(event.ip);
      });
  wifiDisconnectedHandler_ = WiFi.onStationModeDisconnected(
      [this](const WiFiEventStationModeDisconnected&) {
        disconnectedEvent_ = true;
      });
  wifiDhcpTimeoutHandler_ = WiFi.onStationModeDHCPTimeout([this]() {
    dhcpTimeoutEvent_ = true;
  });

  wifiClient_.setTimeout(config::kTcpClientTimeoutMs);
  mqtt_.setBufferSize(config::kMqttBufferBytes);
  mqtt_.setKeepAlive(config::kMqttKeepAliveSeconds);
  mqtt_.setSocketTimeout(config::kMqttSocketTimeoutSeconds);
  mqtt_.setCallback([this](char* topic, uint8_t* payload, unsigned int length) {
    handleMqttMessage(topic, payload, length);
  });

  randomSeed(ESP.getCycleCount());
  loadNetworkConfiguration();
  configureRecovery(nowMs, false);
  lastStatusMs_ = nowMs;
  buildLastWill();
}

void MqttTransport::tick(uint32_t nowMs, uint8_t faultMask) {
  const bool portalWasActive = portal_.active();
  portal_.tick(nowMs);
  if (portalWasActive && !portal_.active()) {
    recovery_.onPortalClosed();
  }
  acceptPortalCandidate(nowMs);

  const bool wifiLinked = WiFi.status() == WL_CONNECTED &&
                          !disconnectedEvent_ && !dhcpTimeoutEvent_;
  const uint32_t localIpv4 =
      gotIpEvent_ ? eventLocalIpv4_ : packIpv4(WiFi.localIP());
  const bool ipv4Valid = wifiLinked && network::isUsableUnicastIpv4(localIpv4);
  const network::RecoveryAction action =
      recovery_.tick(nowMs, wifiLinked, ipv4Valid, localIpv4, mqtt_.connected());
  executeRecoveryAction(action, nowMs, faultMask);

  gotIpEvent_ = false;
  disconnectedEvent_ = false;
  dhcpTimeoutEvent_ = false;

  if (!mqtt_.connected()) {
    return;
  }
  if (!mqtt_.loop()) {
    commandSessionPrepared_ = false;
    provisioningCommandPending_ = false;
    recovery_.onMqttLoopLost(millis());
    return;
  }

  serviceProvisioningCommand(nowMs, faultMask);
  serviceEventQueue(nowMs);
  if (elapsed(nowMs, lastStatusMs_) >= config::kStatusPeriodMs) {
    // A live, non-retained heartbeat is the freshness proof used before the
    // edge sends a boot-specific provisioning command.
    publishStatus(true, "heartbeat", faultMask, false, nowMs);
  }
  maybePersistLastGood(nowMs);
}

void MqttTransport::executeRecoveryAction(
    const network::RecoveryAction& action, uint32_t nowMs, uint8_t faultMask) {
  switch (action.kind) {
    case network::RecoveryActionKind::kNone:
      return;
    case network::RecoveryActionKind::kStartWifi:
      startWifiProfile(action.profileIndex);
      return;
    case network::RecoveryActionKind::kDisconnectNetwork:
      disconnectNetwork();
      return;
    case network::RecoveryActionKind::kDisconnectMqtt:
      disconnectMqtt();
      return;
    case network::RecoveryActionKind::kResolveBroker:
      resolveBroker(nowMs);
      return;
    case network::RecoveryActionKind::kConnectMqttPrimary:
      connectMqtt(nowMs, faultMask, false);
      return;
    case network::RecoveryActionKind::kConnectMqttFallback:
      connectMqtt(nowMs, faultMask, true);
      return;
    case network::RecoveryActionKind::kOpenPortal:
      if (portal_.start(PROVISIONING_AP_PASSWORD, currentConfig_, configStore_, nowMs)) {
        recovery_.onPortalOpened(nowMs, portal_.deadlineMs());
      }
      return;
    case network::RecoveryActionKind::kClosePortal:
      portal_.stop();
      recovery_.onPortalClosed();
      return;
    case network::RecoveryActionKind::kRollbackCandidate:
      rollbackCandidate(nowMs);
      return;
  }
}

void MqttTransport::startWifiProfile(uint8_t profileIndex) {
  if (profileIndex >= network::kMaxWifiProfiles ||
      currentConfig_.profiles[profileIndex].enabled == 0U) {
    return;
  }
  disconnectMqtt();
  WiFi.disconnect(false);
  WiFi.mode(portal_.active() ? WIFI_AP_STA : WIFI_STA);
  const network::WifiProfile& profile = currentConfig_.profiles[profileIndex];
  WiFi.begin(profile.ssid, profile.password);
  Serial.printf("wifi_connecting profile=%u\n", profileIndex);
}

void MqttTransport::disconnectMqtt() {
  if (mqtt_.connected()) {
    mqtt_.disconnect();
  } else {
    wifiClient_.stop();
  }
  commandSessionPrepared_ = false;
  provisioningCommandPending_ = false;
}

void MqttTransport::disconnectNetwork() {
  disconnectMqtt();
  WiFi.disconnect(false);
}

void MqttTransport::resolveBroker(uint32_t nowMs) {
  primaryBrokerIpv4_ = 0;
  fallbackBrokerIpv4_ = 0;
  const uint32_t localAddress = packIpv4(WiFi.localIP());
  const uint32_t subnetMask = packIpv4(WiFi.subnetMask());

  uint32_t literal = 0;
  if (network::parseIpv4(currentConfig_.brokerHost, literal)) {
    if (isUsableBrokerAddress(literal, localAddress, subnetMask)) {
      primaryBrokerIpv4_ = literal;
    }
  } else {
    IPAddress resolved;
    if (WiFi.hostByName(currentConfig_.brokerHost, resolved,
                        config::kDnsResolveTimeoutMs) == 1) {
      const uint32_t packed = packIpv4(resolved);
      if (isUsableBrokerAddress(packed, localAddress, subnetMask)) {
        primaryBrokerIpv4_ = packed;
      }
    }
  }

  const uint8_t profileIndex = recovery_.activeProfile();
  if (profileIndex < network::kMaxWifiProfiles) {
    uint32_t fallback = 0;
    const network::WifiProfile& profile = currentConfig_.profiles[profileIndex];
    const bool fallbackConfigured = profile.fallbackIpv4[0] != '\0';
    const bool fallbackValid =
        fallbackConfigured &&
        network::parseIpv4(profile.fallbackIpv4, fallback) &&
        network::fallbackMatchesSubnet(fallback, localAddress, subnetMask);
    if (fallbackValid) {
      fallbackBrokerIpv4_ = fallback;
    }
    // A candidate is not committed through a profile whose configured
    // fallback contradicts the subnet actually obtained by DHCP. Existing
    // committed configurations remain recoverable: their bad fallback is
    // simply ignored and the primary DNS path can still be used.
    if (portalCandidateTrial_ && fallbackConfigured && !fallbackValid) {
      primaryBrokerIpv4_ = 0;
    }
  }
  recovery_.onDnsResult(primaryBrokerIpv4_ != 0U,
                        fallbackBrokerIpv4_ != 0U, nowMs);
}

network::MqttAttemptResult MqttTransport::classifyMqttState(int state) {
  switch (state) {
    case MQTT_CONNECT_BAD_PROTOCOL:
      return network::MqttAttemptResult::kBadProtocol;
    case MQTT_CONNECT_BAD_CLIENT_ID:
      return network::MqttAttemptResult::kBadClientId;
    case MQTT_CONNECT_UNAVAILABLE:
      return network::MqttAttemptResult::kUnavailable;
    case MQTT_CONNECT_BAD_CREDENTIALS:
      return network::MqttAttemptResult::kBadCredentials;
    case MQTT_CONNECT_UNAUTHORIZED:
      return network::MqttAttemptResult::kUnauthorized;
    default:
      return network::MqttAttemptResult::kTransportFailure;
  }
}

const char* MqttTransport::recoveryReasonText(network::RecoveryReason reason) {
  switch (reason) {
    case network::RecoveryReason::kProvisioning:
      return "recovered_provisioning";
    case network::RecoveryReason::kWifiProfile:
      return "recovered_wifi_profile";
    case network::RecoveryReason::kBrokerIpChange:
      return "recovered_broker_ip_change";
    case network::RecoveryReason::kDnsFallback:
      return "recovered_dns_fallback";
    case network::RecoveryReason::kMqttTransport:
      return "recovered_mqtt_transport";
    case network::RecoveryReason::kNone:
      return "connected";
  }
  return "connected";
}

void MqttTransport::prepareCommandSession() {
  if (commandSessionPrepared_) {
    return;
  }
  uint8_t entropy[16] = {};
  for (size_t offset = 0; offset < sizeof(entropy); offset += sizeof(uint32_t)) {
    const uint32_t randomValue = ESP.random();
    entropy[offset] = static_cast<uint8_t>(randomValue >> 24U);
    entropy[offset + 1U] = static_cast<uint8_t>(randomValue >> 16U);
    entropy[offset + 2U] = static_cast<uint8_t>(randomValue >> 8U);
    entropy[offset + 3U] = static_cast<uint8_t>(randomValue);
  }
  command_contract::formatUuidV4(entropy, commandSessionId_);
  memset(recentCommandIds_, 0, sizeof(recentCommandIds_));
  recentCommandPosition_ = 0;
  provisioningCommandPending_ = false;
  commandSessionPrepared_ = true;
}

bool MqttTransport::connectMqtt(uint32_t /*nowMs*/, uint8_t faultMask,
                                bool useFallback) {
  selectedBrokerIpv4_ = useFallback ? fallbackBrokerIpv4_ : primaryBrokerIpv4_;
  if (!network::isUsableUnicastIpv4(selectedBrokerIpv4_)) {
    recovery_.onMqttResult(network::MqttAttemptResult::kTransportFailure,
                           useFallback, false, millis());
    return false;
  }

  mqtt_.setServer(unpackIpv4(selectedBrokerIpv4_), currentConfig_.brokerPort);
  prepareCommandSession();
  buildLastWill();
  const bool connected = mqtt_.connect(
      mqttClientId_, MQTT_USERNAME, MQTT_PASSWORD, statusTopic_, 0, true,
      lastWillPayload_, true);
  const uint32_t completedAtMs = millis();
  if (!connected) {
    const int state = mqtt_.state();
    Serial.printf("mqtt_connect_failed state=%d\n", state);
    recovery_.onMqttResult(classifyMqttState(state), useFallback, false,
                           completedAtMs);
    return false;
  }
  if (!mqtt_.subscribe(commandTopic_, 1)) {
    disconnectMqtt();
    recovery_.onMqttResult(network::MqttAttemptResult::kTransportFailure,
                           useFallback, false, completedAtMs);
    return false;
  }

  const bool wasPortalCandidate = portalCandidateTrial_;
  if (portalCandidateTrial_) {
    currentRecord_.config.lastGoodProfile =
        static_cast<int8_t>(recovery_.activeProfile());
    currentConfig_.lastGoodProfile = currentRecord_.config.lastGoodProfile;
    if (!configStore_.promoteCandidate(currentRecord_)) {
      disconnectMqtt();
      rollbackCandidate(completedAtMs);
      return false;
    }
    committedRecord_ = currentRecord_;
    haveCommittedConfig_ = true;
    portalCandidateTrial_ = false;
  } else if (bootstrapCandidateStaged_) {
    currentRecord_.config.lastGoodProfile =
        static_cast<int8_t>(recovery_.activeProfile());
    currentConfig_.lastGoodProfile = currentRecord_.config.lastGoodProfile;
    if (configStore_.promoteCandidate(currentRecord_)) {
      committedRecord_ = currentRecord_;
      haveCommittedConfig_ = true;
      bootstrapCandidateStaged_ = false;
    }
  }

  const bool brokerIpChanged = lastSuccessfulBrokerIpv4_ != 0U &&
                               lastSuccessfulBrokerIpv4_ != selectedBrokerIpv4_;
  recovery_.onMqttResult(network::MqttAttemptResult::kConnected, useFallback,
                         brokerIpChanged, completedAtMs);
  lastSuccessfulBrokerIpv4_ = selectedBrokerIpv4_;
  const network::RecoveryReason recovered = recovery_.takeRecoveryReason();
  const char* reason = (!hadSuccessfulConnection_ && !wasPortalCandidate)
                           ? "connected"
                           : recoveryReasonText(recovered);
  hadSuccessfulConnection_ = true;
  onlineSinceMs_ = completedAtMs;
  Serial.println(F("mqtt_connected"));
  publishStatus(true, reason, faultMask, true, completedAtMs);
  return true;
}

void MqttTransport::acceptPortalCandidate(uint32_t nowMs) {
  network::NetworkRecord candidate = {};
  if (!portal_.takeCandidate(candidate)) {
    return;
  }
  candidatePortalDeadlineMs_ = portal_.deadlineMs();
  portal_.stop();
  recovery_.onPortalClosed();
  disconnectNetwork();
  currentRecord_ = candidate;
  currentConfig_ = candidate.config;
  bootstrapCandidateStaged_ = false;
  portalCandidateTrial_ = true;
  configureRecovery(nowMs, true);
}

void MqttTransport::rollbackCandidate(uint32_t nowMs) {
  portalCandidateTrial_ = false;
  bootstrapCandidateStaged_ = false;
  disconnectNetwork();
  if (haveCommittedConfig_) {
    currentRecord_ = committedRecord_;
    currentConfig_ = committedRecord_.config;
  } else {
    // Before the first successful MQTT authentication there is no committed
    // slot to restore. Reconstruct the immutable bootstrap profile so a bad
    // first portal candidate cannot strand the node in an unbounded trial.
    buildBootstrapConfiguration(currentConfig_);
    currentRecord_ = network::NetworkRecord();
    if (network::validateConfig(currentConfig_) && configStore_.mounted() &&
        configStore_.writeCandidate(currentConfig_, currentRecord_)) {
      bootstrapCandidateStaged_ = true;
    } else if (!network::validateConfig(currentConfig_)) {
      currentConfig_ = network::NetworkConfig();
      currentConfig_.brokerPort = MQTT_PORT;
      currentConfig_.lastGoodProfile = -1;
    }
  }
  configureRecovery(nowMs, false);
  if (candidatePortalDeadlineMs_ != 0U &&
      !deadlineReached(nowMs, candidatePortalDeadlineMs_) &&
      portal_.start(PROVISIONING_AP_PASSWORD, currentConfig_, configStore_, nowMs,
                    candidatePortalDeadlineMs_)) {
    recovery_.onPortalOpened(nowMs, candidatePortalDeadlineMs_);
  }
}

void MqttTransport::maybePersistLastGood(uint32_t nowMs) {
  if (!recovery_.online() || !mqtt_.connected() ||
      elapsed(nowMs, onlineSinceMs_) < config::kLastGoodStableMs) {
    return;
  }
  const int8_t active = static_cast<int8_t>(recovery_.activeProfile());
  if (currentConfig_.lastGoodProfile == active ||
      (lastGoodWriteMade_ &&
       elapsed(nowMs, lastGoodWriteMs_) < config::kLastGoodMinimumWriteIntervalMs)) {
    return;
  }

  network::NetworkConfig updated = currentConfig_;
  updated.lastGoodProfile = active;
  network::NetworkRecord written = {};
  if (configStore_.writeCommitted(updated, written)) {
    currentConfig_ = updated;
    currentRecord_ = written;
    committedRecord_ = written;
    haveCommittedConfig_ = true;
    lastGoodWriteMs_ = nowMs;
    lastGoodWriteMade_ = true;
    Serial.println(F("last_good_profile_persisted"));
  }
}

bool MqttTransport::commandSeen(const char* commandId) const {
  for (const auto& recent : recentCommandIds_) {
    if (recent[0] != '\0' && strcmp(recent, commandId) == 0) {
      return true;
    }
  }
  return false;
}

void MqttTransport::rememberCommand(const char* commandId) {
  snprintf(recentCommandIds_[recentCommandPosition_],
           sizeof(recentCommandIds_[recentCommandPosition_]), "%s", commandId);
  recentCommandPosition_ =
      static_cast<uint8_t>((recentCommandPosition_ + 1U) % 4U);
}

void MqttTransport::handleMqttMessage(char* topic, uint8_t* payload,
                                      unsigned int length) {
  if (!commandSessionPrepared_ || portal_.active() ||
      strcmp(topic, commandTopic_) != 0 || payload == nullptr || length == 0U ||
      length > config::kMqttBufferBytes) {
    return;
  }

  JsonDocument command;
  const DeserializationError error = deserializeJson(command, payload, length);
  if (error || !command.is<JsonObjectConst>()) {
    return;
  }
  const JsonObjectConst object = command.as<JsonObjectConst>();
  if (object.size() != 7U || !object["schema"].is<const char*>() ||
      !object["device_id"].is<const char*>() ||
      !object["target_boot_id"].is<const char*>() ||
      !object["command_id"].is<const char*>() ||
      !object["command_session_id"].is<const char*>() ||
      !object["action"].is<const char*>() ||
      !object["expires_uptime_ms"].is<uint32_t>()) {
    return;
  }

  const char* commandId = object["command_id"];
  if (strcmp(object["schema"], "health.command.v1") != 0 ||
      strcmp(object["device_id"], deviceId_) != 0 ||
      strcmp(object["target_boot_id"], bootId_) != 0 ||
      strcmp(object["command_session_id"], commandSessionId_) != 0 ||
      strcmp(object["action"], "open_provisioning") != 0 ||
      !validUuid(commandId) || commandSeen(commandId)) {
    return;
  }

  const uint32_t nowMs = millis();
  const uint32_t expiry = object["expires_uptime_ms"].as<uint32_t>();
  if (!command_contract::expiryIsFresh(nowMs, expiry,
                                       config::kCommandMaximumFutureMs) ||
      provisioningCommandPending_ || !configStore_.mounted()) {
    return;
  }

  rememberCommand(commandId);
  snprintf(pendingCommandId_, sizeof(pendingCommandId_), "%s", commandId);
  provisioningCommandPending_ = true;
}

void MqttTransport::serviceProvisioningCommand(uint32_t nowMs,
                                               uint8_t faultMask) {
  if (!provisioningCommandPending_) {
    return;
  }
  if (!publishStatus(true, "provisioning_started", faultMask, false, nowMs,
                     pendingCommandId_)) {
    return;
  }
  provisioningCommandPending_ = false;
  pendingCommandId_[0] = '\0';
  recovery_.requestPortal();
}

bool MqttTransport::publishTelemetry(const TelemetrySnapshot& snapshot,
                                     uint32_t nowMs) {
  if (!online()) {
    return false;
  }

  document_.clear();
  document_["schema"] = "health.telemetry.v3";
  document_["device_id"] = deviceId_;
  document_["boot_id"] = bootId_;
  document_["seq"] = allocateSequence();
  document_["uptime_ms"] = nowMs;

  JsonObject vitals = document_["vitals"].to<JsonObject>();
  setNullable(vitals, "heart_rate_bpm", snapshot.heartRateBpm);
  setNullable(vitals, "spo2_pct", snapshot.spo2Pct);

  JsonObject wearable = document_["wearable"].to<JsonObject>();
  setNullable(wearable, "wrist_surface_temp_c", snapshot.wristSurfaceTempC);

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
  quality["wrist_surface_temp_valid"] = snapshot.wristSurfaceTempC.valid;
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
  if (!online() || eventCount_ == 0U) {
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

bool MqttTransport::publishStatus(bool isOnline, const char* reason,
                                  uint8_t faultMask, bool retained,
                                  uint32_t nowMs, const char* correlationId) {
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
  if (commandSessionPrepared_) {
    document_["command_session_id"] = commandSessionId_;
  }
  if (correlationId != nullptr && correlationId[0] != '\0') {
    document_["correlation_id"] = correlationId;
  }
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
  if (commandSessionPrepared_) {
    document_["command_session_id"] = commandSessionId_;
  }
  JsonObject system = document_["system"].to<JsonObject>();
  addSystem(system, kFaultNone, false);
  serializeJson(document_, lastWillPayload_, sizeof(lastWillPayload_));
}

void MqttTransport::addSystem(JsonObject target, uint8_t faultMask,
                              bool includeRuntimeValues) {
  const uint32_t localIpv4 = packIpv4(WiFi.localIP());
  if (includeRuntimeValues && WiFi.status() == WL_CONNECTED &&
      network::isUsableUnicastIpv4(localIpv4)) {
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
  if ((faultMask & kFaultDs18b20) != 0U) {
    target.add("ds18b20_unavailable");
  }
  if ((faultMask & kFaultPpgOverflow) != 0U) {
    target.add("ppg_sample_loss");
  }
}

bool MqttTransport::serializeAndPublish(const char* topic, bool retained) {
  const size_t requiredLength = measureJson(document_);
  constexpr size_t kMqttPacketOverheadBudget = 8;
  if (requiredLength == 0U || requiredLength + 1U > sizeof(payload_) ||
      requiredLength + strlen(topic) + kMqttPacketOverheadBudget >
          config::kMqttBufferBytes) {
    return false;
  }
  const size_t payloadLength =
      serializeJson(document_, payload_, sizeof(payload_));
  if (payloadLength != requiredLength) {
    return false;
  }
  return mqtt_.publish(topic, reinterpret_cast<const uint8_t*>(payload_),
                       static_cast<unsigned int>(payloadLength), retained);
}

uint32_t MqttTransport::allocateSequence() {
  ++sequence_;
  if (sequence_ == 0U) {
    ++sequence_;
  }
  return sequence_;
}

bool MqttTransport::online() {
  const uint32_t localIpv4 = packIpv4(WiFi.localIP());
  return WiFi.status() == WL_CONNECTED &&
         network::isUsableUnicastIpv4(localIpv4) && mqtt_.connected();
}

uint32_t MqttTransport::droppedEventCount() const {
  return droppedEvents_;
}
