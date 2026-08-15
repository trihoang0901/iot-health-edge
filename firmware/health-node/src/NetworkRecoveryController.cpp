#include "NetworkRecoveryController.h"

namespace network {

NetworkRecoveryController::NetworkRecoveryController(const RecoveryTimings& timings)
    : timings_(timings),
      wifiBackoffMs_(timings.backoffMinMs),
      mqttBackoffMs_(timings.backoffMinMs) {}

bool NetworkRecoveryController::deadlineReached(uint32_t nowMs, uint32_t deadlineMs) {
  return static_cast<int32_t>(nowMs - deadlineMs) >= 0;
}

uint32_t NetworkRecoveryController::elapsed(uint32_t nowMs, uint32_t sinceMs) {
  return static_cast<uint32_t>(nowMs - sinceMs);
}

uint32_t NetworkRecoveryController::nextBackoff(uint32_t value) const {
  if (value >= timings_.backoffMaxMs / 2U) {
    return timings_.backoffMaxMs;
  }
  return value * 2U;
}

void NetworkRecoveryController::rebuildOrder(
    const RecoveryProfile profiles[kMaxWifiProfiles], int8_t lastGoodProfile) {
  orderCount_ = 0;
  if (lastGoodProfile >= 0 && lastGoodProfile < static_cast<int8_t>(kMaxWifiProfiles) &&
      profiles[lastGoodProfile].enabled) {
    order_[orderCount_++] = static_cast<uint8_t>(lastGoodProfile);
  }
  for (uint8_t priority = 0; priority < kMaxWifiProfiles; ++priority) {
    for (uint8_t index = 0; index < kMaxWifiProfiles; ++index) {
      if (!profiles[index].enabled || profiles[index].priority != priority ||
          index == static_cast<uint8_t>(lastGoodProfile)) {
        continue;
      }
      order_[orderCount_++] = index;
    }
  }
}

void NetworkRecoveryController::configure(
    const RecoveryProfile profiles[kMaxWifiProfiles], int8_t lastGoodProfile,
    uint32_t nowMs, bool candidateTrial) {
  rebuildOrder(profiles, lastGoodProfile);
  orderPosition_ = 0;
  activeProfile_ = orderCount_ > 0U ? order_[0] : 0U;
  phase_ = Phase::kWaitingWifi;
  phaseStartedMs_ = nowMs;
  nextActionMs_ = nowMs;
  offlineSinceMs_ = nowMs;
  candidateStartedMs_ = nowMs;
  candidateTrial_ = candidateTrial;
  fallbackAvailable_ = false;
  retryResolve_ = false;
  portalSuppressed_ = false;
  pendingTransportRecovery_ = everOnline_;
  onlineLocalIpv4_ = 0;
  wifiBackoffMs_ = timings_.backoffMinMs;
  mqttBackoffMs_ = timings_.backoffMinMs;
}

void NetworkRecoveryController::advanceProfile(uint32_t nowMs) {
  fallbackAvailable_ = false;
  retryResolve_ = false;
  ++orderPosition_;
  if (orderPosition_ >= orderCount_) {
    orderPosition_ = 0;
    const uint32_t jitterMs = (nowMs ^ wifiBackoffMs_) % 251U;
    nextActionMs_ = nowMs + wifiBackoffMs_ + jitterMs;
    wifiBackoffMs_ = nextBackoff(wifiBackoffMs_);
  } else {
    nextActionMs_ = nowMs;
  }
  if (orderCount_ > 0U) {
    activeProfile_ = order_[orderPosition_];
  }
  phase_ = Phase::kWaitingWifi;
  phaseStartedMs_ = nowMs;
}

void NetworkRecoveryController::markNetworkPathFailure(uint32_t nowMs) {
  portalSuppressed_ = false;
  advanceProfile(nowMs);
}

void NetworkRecoveryController::scheduleMqttRetry(uint32_t nowMs,
                                                   bool resolveAgain) {
  const uint32_t jitterMs = (nowMs ^ mqttBackoffMs_) % 251U;
  nextActionMs_ = nowMs + mqttBackoffMs_ + jitterMs;
  mqttBackoffMs_ = nextBackoff(mqttBackoffMs_);
  retryResolve_ = resolveAgain;
  phase_ = Phase::kRetryMqtt;
}

RecoveryAction NetworkRecoveryController::tick(uint32_t nowMs, bool wifiLinked,
                                                bool ipv4Valid, uint32_t localIpv4,
                                                bool mqttConnected) {
  if (portalRequested_ && !portalActive_) {
    portalRequested_ = false;
    return {RecoveryActionKind::kOpenPortal, activeProfile_};
  }
  if (portalActive_ && deadlineReached(nowMs, portalDeadlineMs_)) {
    return {RecoveryActionKind::kClosePortal, activeProfile_};
  }
  if (candidateTrial_ && phase_ != Phase::kOnline &&
      elapsed(nowMs, candidateStartedMs_) >= timings_.candidateTrialMs) {
    candidateTrial_ = false;
    return {RecoveryActionKind::kRollbackCandidate, activeProfile_};
  }
  if (phase_ != Phase::kOnline && !candidateTrial_ && !portalActive_ &&
      !autoPortalOpened_ && !portalSuppressed_ &&
      elapsed(nowMs, offlineSinceMs_) >= timings_.autoPortalAfterMs) {
    autoPortalOpened_ = true;
    return {RecoveryActionKind::kOpenPortal, activeProfile_};
  }

  if (phase_ == Phase::kOnline) {
    if (!wifiLinked || !ipv4Valid) {
      pendingTransportRecovery_ = true;
      offlineSinceMs_ = nowMs;
      orderPosition_ = 0;
      nextActionMs_ = nowMs;
      phase_ = Phase::kWaitingWifi;
      onlineLocalIpv4_ = 0;
      return {RecoveryActionKind::kDisconnectNetwork, activeProfile_};
    }
    if (localIpv4 != onlineLocalIpv4_) {
      pendingTransportRecovery_ = true;
      onlineLocalIpv4_ = localIpv4;
      phase_ = Phase::kNeedResolve;
      return {RecoveryActionKind::kDisconnectMqtt, activeProfile_};
    }
    if (!mqttConnected) {
      pendingTransportRecovery_ = true;
      scheduleMqttRetry(nowMs, true);
    }
    return {};
  }

  if (portalActive_) {
    return {};
  }
  if (orderCount_ == 0U) {
    return {};
  }

  // Once association/DHCP has succeeded, every later phase relies on that
  // exact network path. A lost link or missing IPv4 must pre-empt even a long
  // MQTT auth/config backoff instead of waiting up to 30 seconds for TCP to
  // fail. Authentication errors still stay on the same profile while the link
  // itself remains valid.
  if (phase_ != Phase::kWaitingWifi && phase_ != Phase::kWifiConnecting &&
      (!wifiLinked || !ipv4Valid)) {
    pendingTransportRecovery_ = everOnline_;
    offlineSinceMs_ = nowMs;
    onlineLocalIpv4_ = 0;
    markNetworkPathFailure(nowMs);
    return {RecoveryActionKind::kDisconnectNetwork, activeProfile_};
  }

  switch (phase_) {
    case Phase::kWaitingWifi:
      if (deadlineReached(nowMs, nextActionMs_)) {
        phase_ = Phase::kWifiConnecting;
        phaseStartedMs_ = nowMs;
        activeProfile_ = order_[orderPosition_];
        return {RecoveryActionKind::kStartWifi, activeProfile_};
      }
      break;
    case Phase::kWifiConnecting:
      if (wifiLinked && ipv4Valid) {
        onlineLocalIpv4_ = localIpv4;
        wifiBackoffMs_ = timings_.backoffMinMs;
        mqttBackoffMs_ = timings_.backoffMinMs;
        phase_ = Phase::kAwaitingResolve;
        return {RecoveryActionKind::kResolveBroker, activeProfile_};
      }
      if (elapsed(nowMs, phaseStartedMs_) >= timings_.wifiAttemptMs) {
        advanceProfile(nowMs);
        return {RecoveryActionKind::kDisconnectNetwork, activeProfile_};
      }
      break;
    case Phase::kNeedResolve:
      phase_ = Phase::kAwaitingResolve;
      return {RecoveryActionKind::kResolveBroker, activeProfile_};
    case Phase::kAwaitingResolve:
    case Phase::kAwaitingMqtt:
      break;
    case Phase::kNeedMqttPrimary:
      phase_ = Phase::kAwaitingMqtt;
      return {RecoveryActionKind::kConnectMqttPrimary, activeProfile_};
    case Phase::kNeedMqttFallback:
      phase_ = Phase::kAwaitingMqtt;
      return {RecoveryActionKind::kConnectMqttFallback, activeProfile_};
    case Phase::kRetryMqtt:
      if (deadlineReached(nowMs, nextActionMs_)) {
        phase_ = retryResolve_ ? Phase::kNeedResolve
                               : (fallbackAvailable_ ? Phase::kNeedMqttFallback
                                                     : Phase::kNeedMqttPrimary);
      }
      break;
    case Phase::kOnline:
      break;
  }
  return {};
}

void NetworkRecoveryController::onDnsResult(bool primaryResolved,
                                             bool fallbackAvailable,
                                             uint32_t nowMs) {
  fallbackAvailable_ = fallbackAvailable;
  if (primaryResolved) {
    phase_ = Phase::kNeedMqttPrimary;
  } else if (fallbackAvailable_) {
    phase_ = Phase::kNeedMqttFallback;
  } else {
    markNetworkPathFailure(nowMs);
  }
}

void NetworkRecoveryController::onMqttResult(MqttAttemptResult result,
                                              bool usedFallback,
                                              bool brokerIpChanged,
                                              uint32_t nowMs) {
  if (result == MqttAttemptResult::kConnected) {
    if (candidateTrial_) {
      readyReason_ = RecoveryReason::kProvisioning;
    } else if (everOnline_ && lastOnlineProfile_ >= 0 &&
               activeProfile_ != static_cast<uint8_t>(lastOnlineProfile_)) {
      readyReason_ = RecoveryReason::kWifiProfile;
    } else if (brokerIpChanged) {
      readyReason_ = RecoveryReason::kBrokerIpChange;
    } else if (usedFallback) {
      readyReason_ = RecoveryReason::kDnsFallback;
    } else if (everOnline_ && pendingTransportRecovery_) {
      readyReason_ = RecoveryReason::kMqttTransport;
    } else {
      readyReason_ = RecoveryReason::kNone;
    }
    candidateTrial_ = false;
    everOnline_ = true;
    pendingTransportRecovery_ = false;
    lastOnlineProfile_ = static_cast<int8_t>(activeProfile_);
    mqttBackoffMs_ = timings_.backoffMinMs;
    portalSuppressed_ = false;
    phase_ = Phase::kOnline;
    phaseStartedMs_ = nowMs;
    return;
  }

  if (result == MqttAttemptResult::kTransportFailure) {
    pendingTransportRecovery_ = everOnline_;
    portalSuppressed_ = false;
    if (!usedFallback && fallbackAvailable_) {
      phase_ = Phase::kNeedMqttFallback;
    } else {
      markNetworkPathFailure(nowMs);
    }
    return;
  }

  // A CONNACK proves that the selected network path reached an MQTT broker.
  // Do not roam or open provisioning for protocol/auth/configuration failures.
  portalSuppressed_ = true;
  fallbackAvailable_ = usedFallback;
  scheduleMqttRetry(nowMs, false);
}

void NetworkRecoveryController::onMqttLoopLost(uint32_t nowMs) {
  if (phase_ != Phase::kOnline) {
    return;
  }
  pendingTransportRecovery_ = true;
  offlineSinceMs_ = nowMs;
  portalSuppressed_ = false;
  scheduleMqttRetry(nowMs, true);
}

void NetworkRecoveryController::requestPortal() {
  if (!portalActive_) {
    portalRequested_ = true;
  }
}

void NetworkRecoveryController::onPortalOpened(uint32_t nowMs,
                                               uint32_t absoluteDeadlineMs) {
  portalActive_ = true;
  portalRequested_ = false;
  portalDeadlineMs_ = absoluteDeadlineMs != 0U
                          ? absoluteDeadlineMs
                          : nowMs + timings_.portalDurationMs;
}

void NetworkRecoveryController::onPortalClosed() {
  portalActive_ = false;
  portalRequested_ = false;
}

uint8_t NetworkRecoveryController::activeProfile() const {
  return activeProfile_;
}

bool NetworkRecoveryController::online() const {
  return phase_ == Phase::kOnline;
}

bool NetworkRecoveryController::candidateTrial() const {
  return candidateTrial_;
}

RecoveryReason NetworkRecoveryController::takeRecoveryReason() {
  const RecoveryReason result = readyReason_;
  readyReason_ = RecoveryReason::kNone;
  return result;
}

uint32_t NetworkRecoveryController::portalDeadlineMs() const {
  return portalDeadlineMs_;
}

}  // namespace network
