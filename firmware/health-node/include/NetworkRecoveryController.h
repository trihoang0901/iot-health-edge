#pragma once

#include <stddef.h>
#include <stdint.h>

#include "NetworkConfig.h"

namespace network {

struct RecoveryTimings {
  uint32_t wifiAttemptMs = 8000;
  uint32_t backoffMinMs = 1000;
  uint32_t backoffMaxMs = 30000;
  uint32_t autoPortalAfterMs = 45000;
  uint32_t portalDurationMs = 300000;
  uint32_t candidateTrialMs = 45000;
};

struct RecoveryProfile {
  bool enabled = false;
  uint8_t priority = 0;
};

enum class RecoveryActionKind : uint8_t {
  kNone,
  kStartWifi,
  kDisconnectNetwork,
  kDisconnectMqtt,
  kResolveBroker,
  kConnectMqttPrimary,
  kConnectMqttFallback,
  kOpenPortal,
  kClosePortal,
  kRollbackCandidate,
};

struct RecoveryAction {
  RecoveryActionKind kind = RecoveryActionKind::kNone;
  uint8_t profileIndex = 0;
};

enum class MqttAttemptResult : uint8_t {
  kConnected,
  kTransportFailure,
  kUnavailable,
  kBadProtocol,
  kBadClientId,
  kBadCredentials,
  kUnauthorized,
};

enum class RecoveryReason : uint8_t {
  kNone,
  kProvisioning,
  kWifiProfile,
  kBrokerIpChange,
  kDnsFallback,
  kMqttTransport,
};

class NetworkRecoveryController {
 public:
  explicit NetworkRecoveryController(const RecoveryTimings& timings = RecoveryTimings());

  void configure(const RecoveryProfile profiles[kMaxWifiProfiles], int8_t lastGoodProfile,
                 uint32_t nowMs, bool candidateTrial = false);
  RecoveryAction tick(uint32_t nowMs, bool wifiLinked, bool ipv4Valid,
                      uint32_t localIpv4, bool mqttConnected);

  void onDnsResult(bool primaryResolved, bool fallbackAvailable, uint32_t nowMs);
  void onMqttResult(MqttAttemptResult result, bool usedFallback,
                    bool brokerIpChanged, uint32_t nowMs);
  void onMqttLoopLost(uint32_t nowMs);
  void requestPortal();
  void onPortalOpened(uint32_t nowMs, uint32_t absoluteDeadlineMs = 0);
  void onPortalClosed();

  uint8_t activeProfile() const;
  bool online() const;
  bool candidateTrial() const;
  RecoveryReason takeRecoveryReason();
  uint32_t portalDeadlineMs() const;

 private:
  enum class Phase : uint8_t {
    kWaitingWifi,
    kWifiConnecting,
    kNeedResolve,
    kAwaitingResolve,
    kNeedMqttPrimary,
    kNeedMqttFallback,
    kAwaitingMqtt,
    kRetryMqtt,
    kOnline,
  };

  static bool deadlineReached(uint32_t nowMs, uint32_t deadlineMs);
  static uint32_t elapsed(uint32_t nowMs, uint32_t sinceMs);
  uint32_t nextBackoff(uint32_t value) const;
  void rebuildOrder(const RecoveryProfile profiles[kMaxWifiProfiles],
                    int8_t lastGoodProfile);
  void advanceProfile(uint32_t nowMs);
  void markNetworkPathFailure(uint32_t nowMs);
  void scheduleMqttRetry(uint32_t nowMs, bool resolveAgain);

  RecoveryTimings timings_;
  Phase phase_ = Phase::kWaitingWifi;
  uint8_t order_[kMaxWifiProfiles] = {};
  uint8_t orderCount_ = 0;
  uint8_t orderPosition_ = 0;
  uint8_t activeProfile_ = 0;
  int8_t lastOnlineProfile_ = -1;
  bool fallbackAvailable_ = false;
  bool retryResolve_ = false;
  bool candidateTrial_ = false;
  bool everOnline_ = false;
  bool portalRequested_ = false;
  bool portalActive_ = false;
  bool autoPortalOpened_ = false;
  bool portalSuppressed_ = false;
  bool pendingTransportRecovery_ = false;
  uint32_t phaseStartedMs_ = 0;
  uint32_t nextActionMs_ = 0;
  uint32_t offlineSinceMs_ = 0;
  uint32_t candidateStartedMs_ = 0;
  uint32_t portalDeadlineMs_ = 0;
  uint32_t wifiBackoffMs_ = 1000;
  uint32_t mqttBackoffMs_ = 1000;
  uint32_t onlineLocalIpv4_ = 0;
  RecoveryReason readyReason_ = RecoveryReason::kNone;
};

}  // namespace network
