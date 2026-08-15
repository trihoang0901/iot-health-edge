#include <assert.h>
#include <stdint.h>

#include <iostream>

#include "NetworkRecoveryController.h"

namespace {

network::RecoveryTimings timings() {
  network::RecoveryTimings value;
  value.wifiAttemptMs = 8;
  value.backoffMinMs = 10;
  value.backoffMaxMs = 40;
  value.autoPortalAfterMs = 45;
  value.portalDurationMs = 30;
  value.candidateTrialMs = 40;
  return value;
}

network::RecoveryProfile singleProfile() {
  network::RecoveryProfile profile;
  profile.enabled = true;
  profile.priority = 0;
  return profile;
}

void connectPrimary(network::NetworkRecoveryController& controller,
                    uint32_t startMs, uint32_t address) {
  assert(controller.tick(startMs, false, false, 0, false).kind ==
         network::RecoveryActionKind::kStartWifi);
  assert(controller.tick(startMs + 1U, true, true, address, false).kind ==
         network::RecoveryActionKind::kResolveBroker);
  controller.onDnsResult(true, false, startMs + 1U);
  assert(controller.tick(startMs + 2U, true, true, address, false).kind ==
         network::RecoveryActionKind::kConnectMqttPrimary);
  controller.onMqttResult(network::MqttAttemptResult::kConnected, false, false,
                          startMs + 3U);
  assert(controller.online());
}

void testLastGoodFirstAndMissingIpTimesOut() {
  network::NetworkRecoveryController controller(timings());
  network::RecoveryProfile profiles[network::kMaxWifiProfiles] = {};
  profiles[0] = singleProfile();
  profiles[0].priority = 0;
  profiles[2] = singleProfile();
  profiles[2].priority = 2;
  controller.configure(profiles, 2, 0, false);

  network::RecoveryAction action = controller.tick(0, false, false, 0, false);
  assert(action.kind == network::RecoveryActionKind::kStartWifi);
  assert(action.profileIndex == 2);
  assert(controller.tick(7, true, false, 0, false).kind ==
         network::RecoveryActionKind::kNone);
  assert(controller.tick(8, true, false, 0, false).kind ==
         network::RecoveryActionKind::kDisconnectNetwork);
  action = controller.tick(9, false, false, 0, false);
  assert(action.kind == network::RecoveryActionKind::kStartWifi);
  assert(action.profileIndex == 0);
}

void testFullSweepBackoffAndRollover() {
  network::NetworkRecoveryController controller(timings());
  network::RecoveryProfile profiles[network::kMaxWifiProfiles] = {};
  profiles[0] = singleProfile();
  controller.configure(profiles, -1, 0, false);
  assert(controller.tick(0, false, false, 0, false).kind ==
         network::RecoveryActionKind::kStartWifi);
  assert(controller.tick(8, false, false, 0, false).kind ==
         network::RecoveryActionKind::kDisconnectNetwork);
  // jitter=(8 xor 10)%251=2, so the first full-sweep retry is at t=20.
  assert(controller.tick(19, false, false, 0, false).kind ==
         network::RecoveryActionKind::kNone);
  assert(controller.tick(20, false, false, 0, false).kind ==
         network::RecoveryActionKind::kStartWifi);

  constexpr uint32_t nearWrap = UINT32_MAX - 4U;
  controller.configure(profiles, -1, nearWrap, false);
  assert(controller.tick(nearWrap, false, false, 0, false).kind ==
         network::RecoveryActionKind::kStartWifi);
  assert(controller.tick(2U, false, false, 0, false).kind ==
         network::RecoveryActionKind::kNone);
  assert(controller.tick(3U, false, false, 0, false).kind ==
         network::RecoveryActionKind::kDisconnectNetwork);
}

void testDhcpAddressChangeForcesMqttReresolve() {
  network::NetworkRecoveryController controller(timings());
  network::RecoveryProfile profiles[network::kMaxWifiProfiles] = {};
  profiles[0] = singleProfile();
  controller.configure(profiles, 0, 0, false);
  connectPrimary(controller, 0, 0xC0A8010AUL);

  assert(controller.tick(4, true, true, 0xC0A8010BUL, true).kind ==
         network::RecoveryActionKind::kDisconnectMqtt);
  assert(controller.tick(5, true, true, 0xC0A8010BUL, false).kind ==
         network::RecoveryActionKind::kResolveBroker);
}

void testAuthFailureDoesNotRoamOrOpenPortal() {
  network::NetworkRecoveryController controller(timings());
  network::RecoveryProfile profiles[network::kMaxWifiProfiles] = {};
  profiles[0] = singleProfile();
  profiles[1] = singleProfile();
  profiles[1].priority = 1;
  controller.configure(profiles, 0, 0, false);
  assert(controller.tick(0, false, false, 0, false).profileIndex == 0);
  assert(controller.tick(1, true, true, 0x0A000002UL, false).kind ==
         network::RecoveryActionKind::kResolveBroker);
  controller.onDnsResult(true, true, 1);
  assert(controller.tick(2, true, true, 0x0A000002UL, false).kind ==
         network::RecoveryActionKind::kConnectMqttPrimary);
  controller.onMqttResult(network::MqttAttemptResult::kUnauthorized, false, false, 3);
  assert(controller.tick(50, true, true, 0x0A000002UL, false).kind ==
         network::RecoveryActionKind::kNone);
  const network::RecoveryAction retry =
      controller.tick(51, true, true, 0x0A000002UL, false);
  assert(retry.kind == network::RecoveryActionKind::kConnectMqttPrimary);
  assert(retry.profileIndex == 0);
}

void testPhysicalLinkLossPreemptsMqttAuthBackoff() {
  network::NetworkRecoveryController controller(timings());
  network::RecoveryProfile profiles[network::kMaxWifiProfiles] = {};
  profiles[0] = singleProfile();
  profiles[1] = singleProfile();
  profiles[1].priority = 1;
  controller.configure(profiles, 0, 0, false);
  assert(controller.tick(0, false, false, 0, false).profileIndex == 0);
  assert(controller.tick(1, true, true, 0x0A000002UL, false).kind ==
         network::RecoveryActionKind::kResolveBroker);
  controller.onDnsResult(true, false, 1);
  assert(controller.tick(2, true, true, 0x0A000002UL, false).kind ==
         network::RecoveryActionKind::kConnectMqttPrimary);
  controller.onMqttResult(network::MqttAttemptResult::kUnauthorized, false,
                          false, 3);

  const network::RecoveryAction lost =
      controller.tick(4, false, false, 0, false);
  assert(lost.kind == network::RecoveryActionKind::kDisconnectNetwork);
  const network::RecoveryAction next =
      controller.tick(5, false, false, 0, false);
  assert(next.kind == network::RecoveryActionKind::kStartWifi);
  assert(next.profileIndex == 1);
}

void testFallbackPortalAndCandidateDeadlines() {
  network::NetworkRecoveryController controller(timings());
  network::RecoveryProfile profiles[network::kMaxWifiProfiles] = {};
  profiles[0] = singleProfile();
  controller.configure(profiles, 0, 0, false);
  assert(controller.tick(45, false, false, 0, false).kind ==
         network::RecoveryActionKind::kOpenPortal);
  controller.onPortalOpened(45);
  assert(controller.portalDeadlineMs() == 75U);
  assert(controller.tick(74, false, false, 0, false).kind ==
         network::RecoveryActionKind::kNone);
  assert(controller.tick(75, false, false, 0, false).kind ==
         network::RecoveryActionKind::kClosePortal);
  controller.onPortalClosed();

  controller.configure(profiles, 0, 100, true);
  assert(controller.tick(140, false, false, 0, false).kind ==
         network::RecoveryActionKind::kRollbackCandidate);
}

void testDnsFallbackAndRecoveryReasonPriority() {
  network::NetworkRecoveryController controller(timings());
  network::RecoveryProfile profiles[network::kMaxWifiProfiles] = {};
  profiles[0] = singleProfile();
  controller.configure(profiles, 0, 0, false);
  assert(controller.tick(0, false, false, 0, false).kind ==
         network::RecoveryActionKind::kStartWifi);
  assert(controller.tick(1, true, true, 0xC0A80A14UL, false).kind ==
         network::RecoveryActionKind::kResolveBroker);
  controller.onDnsResult(false, true, 1);
  assert(controller.tick(2, true, true, 0xC0A80A14UL, false).kind ==
         network::RecoveryActionKind::kConnectMqttFallback);
  controller.onMqttResult(network::MqttAttemptResult::kConnected, true, false, 3);
  assert(controller.takeRecoveryReason() ==
         network::RecoveryReason::kDnsFallback);

  controller.onMqttLoopLost(4);
  // backoff=10 and jitter=(4 xor 10)=14, so the retry deadline is t=28;
  // the following tick performs the requested re-resolution.
  assert(controller.tick(27, true, true, 0xC0A80A14UL, false).kind ==
         network::RecoveryActionKind::kNone);
  assert(controller.tick(28, true, true, 0xC0A80A14UL, false).kind ==
         network::RecoveryActionKind::kNone);
  assert(controller.tick(29, true, true, 0xC0A80A14UL, false).kind ==
         network::RecoveryActionKind::kResolveBroker);
  controller.onDnsResult(false, true, 29);
  assert(controller.tick(30, true, true, 0xC0A80A14UL, false).kind ==
         network::RecoveryActionKind::kConnectMqttFallback);
  controller.onMqttResult(network::MqttAttemptResult::kConnected, true, false, 31);
  assert(controller.takeRecoveryReason() ==
         network::RecoveryReason::kDnsFallback);
}

}  // namespace

int main() {
  testLastGoodFirstAndMissingIpTimesOut();
  testFullSweepBackoffAndRollover();
  testDhcpAddressChangeForcesMqttReresolve();
  testAuthFailureDoesNotRoamOrOpenPortal();
  testPhysicalLinkLossPreemptsMqttAuthBackoff();
  testFallbackPortalAndCandidateDeadlines();
  testDnsFallbackAndRecoveryReasonPriority();
  std::cout << "NetworkRecoveryController tests passed\n";
  return 0;
}
