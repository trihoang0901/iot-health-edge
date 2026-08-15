#pragma once

#include <DNSServer.h>
#include <ESP8266WebServer.h>

#include "NetworkConfig.h"
#include "NetworkConfigStore.h"

namespace network {

class ProvisioningPortal {
 public:
  bool start(const char* apPassword, const NetworkConfig& currentConfig,
             NetworkConfigStore& store, uint32_t nowMs,
             uint32_t absoluteDeadlineMs = 0);
  void tick(uint32_t nowMs);
  void stop();
  bool active() const;
  uint32_t deadlineMs() const;
  bool takeCandidate(NetworkRecord& candidate);

 private:
  static bool deadlineReached(uint32_t nowMs, uint32_t deadlineMs);
  static uint32_t elapsed(uint32_t nowMs, uint32_t sinceMs);
  static String escapeHtml(const char* value);
  static bool copyField(char* destination, size_t capacity, const String& value);
  static bool validContentLength(const String& value);
  static bool parseUnsignedField(const String& value, uint32_t maximum,
                                 uint32_t& parsed);

  void installRoutes();
  void rotateCsrfNonce();
  void addNoStoreHeaders();
  void handleIndex();
  void handleSave();
  void handleNotFound();
  bool readFormConfig(NetworkConfig& config, String& error);

  DNSServer dns_;
  ESP8266WebServer server_{80};
  NetworkConfigStore* store_ = nullptr;
  NetworkConfig currentConfig_ = {};
  NetworkRecord candidate_ = {};
  char csrfNonce_[33] = {};
  bool routesInstalled_ = false;
  bool active_ = false;
  bool candidateReady_ = false;
  bool hasSaved_ = false;
  uint8_t saveCount_ = 0;
  uint32_t lastSaveMs_ = 0;
  uint32_t candidateReadyAtMs_ = 0;
  uint32_t deadlineMs_ = 0;
};

}  // namespace network
