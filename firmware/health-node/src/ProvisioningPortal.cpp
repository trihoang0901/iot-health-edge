#include "ProvisioningPortal.h"

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <stdlib.h>
#include <string.h>

#include "AppConfig.h"

namespace network {
namespace {

constexpr byte kDnsPort = 53;
constexpr uint32_t kSaveRateLimitMs = 2000;
constexpr uint8_t kMaxSavesPerWindow = 5;
constexpr size_t kMaximumPostBytes = 4096;
constexpr uint32_t kResponseHandoffMs = 250;
constexpr uint32_t kSaveDeadlineGuardMs = 750;

}  // namespace

bool ProvisioningPortal::deadlineReached(uint32_t nowMs, uint32_t deadlineMs) {
  return static_cast<int32_t>(nowMs - deadlineMs) >= 0;
}

uint32_t ProvisioningPortal::elapsed(uint32_t nowMs, uint32_t sinceMs) {
  return static_cast<uint32_t>(nowMs - sinceMs);
}

String ProvisioningPortal::escapeHtml(const char* value) {
  String escaped;
  if (value == nullptr) {
    return escaped;
  }
  escaped.reserve(strlen(value) + 16U);
  for (const char* cursor = value; *cursor != '\0'; ++cursor) {
    switch (*cursor) {
      case '&':
        escaped += F("&amp;");
        break;
      case '<':
        escaped += F("&lt;");
        break;
      case '>':
        escaped += F("&gt;");
        break;
      case '"':
        escaped += F("&quot;");
        break;
      case '\'':
        escaped += F("&#39;");
        break;
      default:
        escaped += *cursor;
        break;
    }
  }
  return escaped;
}

bool ProvisioningPortal::copyField(char* destination, size_t capacity,
                                   const String& value) {
  if (capacity == 0U || value.length() >= capacity) {
    return false;
  }
  memcpy(destination, value.c_str(), value.length() + 1U);
  return true;
}

bool ProvisioningPortal::validContentLength(const String& value) {
  if (value.length() == 0U || value.length() > 5U) {
    return false;
  }
  size_t parsed = 0;
  for (size_t index = 0; index < value.length(); ++index) {
    if (value[index] < '0' || value[index] > '9') {
      return false;
    }
    parsed = parsed * 10U + static_cast<size_t>(value[index] - '0');
    if (parsed > kMaximumPostBytes) {
      return false;
    }
  }
  return parsed > 0U;
}

bool ProvisioningPortal::parseUnsignedField(const String& value,
                                            uint32_t maximum,
                                            uint32_t& parsed) {
  if (value.length() == 0U || value.length() > 10U) {
    return false;
  }
  uint32_t result = 0;
  for (size_t index = 0; index < value.length(); ++index) {
    if (value[index] < '0' || value[index] > '9') {
      return false;
    }
    const uint32_t digit = static_cast<uint32_t>(value[index] - '0');
    if (digit > maximum || result > (maximum - digit) / 10U) {
      return false;
    }
    result = result * 10U + digit;
  }
  parsed = result;
  return true;
}

void ProvisioningPortal::rotateCsrfNonce() {
  snprintf(csrfNonce_, sizeof(csrfNonce_), "%08lx%08lx%08lx%08lx",
           static_cast<unsigned long>(ESP.random()),
           static_cast<unsigned long>(ESP.random()),
           static_cast<unsigned long>(ESP.random()),
           static_cast<unsigned long>(ESP.random()));
}

void ProvisioningPortal::addNoStoreHeaders() {
  server_.sendHeader(F("Cache-Control"), F("no-store, max-age=0"), true);
  server_.sendHeader(F("Pragma"), F("no-cache"));
  server_.sendHeader(F("X-Content-Type-Options"), F("nosniff"));
  server_.sendHeader(F("X-Frame-Options"), F("DENY"));
}

void ProvisioningPortal::installRoutes() {
  if (routesInstalled_) {
    return;
  }
  server_.collectHeaders("Content-Length");
  server_.on("/", HTTP_GET, [this]() { handleIndex(); });
  server_.on("/save", HTTP_POST, [this]() { handleSave(); });
  server_.onNotFound([this]() { handleNotFound(); });
  routesInstalled_ = true;
}

bool ProvisioningPortal::start(const char* apPassword,
                               const NetworkConfig& currentConfig,
                               NetworkConfigStore& store, uint32_t nowMs,
                               uint32_t absoluteDeadlineMs) {
  if (active_ || apPassword == nullptr || strlen(apPassword) < 20U ||
      strlen(apPassword) > 63U || !store.mounted()) {
    return false;
  }

  installRoutes();
  currentConfig_ = currentConfig;
  store_ = &store;
  candidateReady_ = false;
  candidateReadyAtMs_ = 0;
  hasSaved_ = false;
  saveCount_ = 0;
  lastSaveMs_ = 0;
  rotateCsrfNonce();
  deadlineMs_ = absoluteDeadlineMs != 0U
                    ? absoluteDeadlineMs
                    : nowMs + config::kProvisioningPortalDurationMs;
  if (deadlineReached(nowMs, deadlineMs_)) {
    return false;
  }

  char apName[32] = {};
  snprintf(apName, sizeof(apName), "HealthNode-Setup-%06lx",
           static_cast<unsigned long>(ESP.getChipId() & 0xFFFFFFUL));
  WiFi.mode(WIFI_AP_STA);
  if (!WiFi.softAP(apName, apPassword)) {
    WiFi.mode(WIFI_STA);
    return false;
  }
  dns_.setErrorReplyCode(DNSReplyCode::NoError);
  if (!dns_.start(kDnsPort, "*", WiFi.softAPIP())) {
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    return false;
  }
  server_.begin();
  active_ = true;
  Serial.println(F("provisioning_portal_started"));
  return true;
}

void ProvisioningPortal::tick(uint32_t nowMs) {
  if (!active_) {
    return;
  }
  if (deadlineReached(nowMs, deadlineMs_)) {
    stop();
    return;
  }
  dns_.processNextRequest();
  server_.handleClient();
}

void ProvisioningPortal::stop() {
  if (!active_) {
    return;
  }
  server_.stop();
  dns_.stop();
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  active_ = false;
  Serial.println(F("provisioning_portal_stopped"));
}

bool ProvisioningPortal::active() const {
  return active_;
}

uint32_t ProvisioningPortal::deadlineMs() const {
  return deadlineMs_;
}

bool ProvisioningPortal::takeCandidate(NetworkRecord& candidate) {
  const uint32_t nowMs = millis();
  if (!candidateReady_ || deadlineReached(nowMs, deadlineMs_) ||
      !deadlineReached(nowMs, candidateReadyAtMs_)) {
    return false;
  }
  candidateReady_ = false;
  candidate = candidate_;
  return true;
}

void ProvisioningPortal::handleIndex() {
  if (!active_) {
    server_.send(503, F("text/plain"), F("portal_closed"));
    return;
  }

  String html;
  html.reserve(3900);
  html += F("<!doctype html><html lang='vi'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Health Node Wi-Fi</title><style>body{font-family:sans-serif;"
            "max-width:44rem;margin:2rem auto;padding:0 1rem}fieldset{margin:1rem 0}"
            "label{display:block;margin:.45rem 0}input{width:100%;box-sizing:border-box}"
            "input[type=checkbox]{width:auto}</style><h1>Cau hinh mang</h1>"
            "<p>Mat khau da luu khong duoc hien thi. De trong de giu nguyen.</p>"
            "<form method='post' action='/save'>");
  html += F("<input type='hidden' name='csrf' value='");
  html += csrfNonce_;
  html += F("'><label>Broker hostname/IP<input required name='broker_host' value='");
  html += escapeHtml(currentConfig_.brokerHost);
  html += F("'></label><label>Broker port<input required type='number' min='1' "
            "max='65535' name='broker_port' value='");
  html += currentConfig_.brokerPort;
  html += F("'></label>");

  for (size_t index = 0; index < kMaxWifiProfiles; ++index) {
    const WifiProfile& profile = currentConfig_.profiles[index];
    html += F("<fieldset><legend>Wi-Fi ");
    html += static_cast<unsigned int>(index + 1U);
    html += F("</legend><label><input type='checkbox' name='enabled_");
    html += static_cast<unsigned int>(index);
    html += '\'';
    if (profile.enabled != 0U) {
      html += F(" checked");
    }
    html += F("> Bat profile</label><label>SSID<input name='ssid_");
    html += static_cast<unsigned int>(index);
    html += F("' maxlength='32' value='");
    html += escapeHtml(profile.ssid);
    html += F("'></label><label>Mat khau<input type='password' autocomplete='new-password' "
              "name='password_");
    html += static_cast<unsigned int>(index);
    html += F("' maxlength='63' value=''></label><label>Uu tien 0..2<input type='number' "
              "min='0' max='2' name='priority_");
    html += static_cast<unsigned int>(index);
    html += F("' value='");
    html += profile.priority;
    html += F("'></label><label>Fallback IPv4<input name='fallback_");
    html += static_cast<unsigned int>(index);
    html += F("' maxlength='15' value='");
    html += escapeHtml(profile.fallbackIpv4);
    html += F("'></label><label><input type='checkbox' name='delete_");
    html += static_cast<unsigned int>(index);
    html += F("'> Xoa profile</label></fieldset>");
  }
  html += F("<button type='submit'>Luu va thu ket noi</button></form></html>");
  addNoStoreHeaders();
  server_.send(200, F("text/html; charset=utf-8"), html);
}

bool ProvisioningPortal::readFormConfig(NetworkConfig& config, String& error) {
  config = currentConfig_;
  const String brokerHost = server_.arg(F("broker_host"));
  uint32_t brokerPort = 0;
  if (!copyField(config.brokerHost, sizeof(config.brokerHost), brokerHost) ||
      !parseUnsignedField(server_.arg(F("broker_port")), 65535U, brokerPort) ||
      brokerPort == 0U) {
    error = F("broker_invalid");
    return false;
  }
  config.brokerPort = static_cast<uint16_t>(brokerPort);

  size_t aggregateLength = brokerHost.length();
  for (size_t index = 0; index < kMaxWifiProfiles; ++index) {
    char field[20] = {};
    snprintf(field, sizeof(field), "delete_%u", static_cast<unsigned int>(index));
    if (server_.hasArg(field)) {
      config.profiles[index] = WifiProfile();
      continue;
    }

    WifiProfile& profile = config.profiles[index];
    snprintf(field, sizeof(field), "enabled_%u", static_cast<unsigned int>(index));
    profile.enabled = server_.hasArg(field) ? 1U : 0U;
    snprintf(field, sizeof(field), "ssid_%u", static_cast<unsigned int>(index));
    const String ssid = server_.arg(field);
    snprintf(field, sizeof(field), "password_%u", static_cast<unsigned int>(index));
    const String password = server_.arg(field);
    snprintf(field, sizeof(field), "priority_%u", static_cast<unsigned int>(index));
    uint32_t priority = 0;
    const String priorityText = server_.arg(field);
    snprintf(field, sizeof(field), "fallback_%u", static_cast<unsigned int>(index));
    const String fallback = server_.arg(field);
    aggregateLength += ssid.length() + password.length() + fallback.length();

    if (!copyField(profile.ssid, sizeof(profile.ssid), ssid) ||
        !copyField(profile.fallbackIpv4, sizeof(profile.fallbackIpv4), fallback) ||
        !parseUnsignedField(priorityText, kMaxWifiProfiles - 1U, priority)) {
      error = F("profile_invalid");
      return false;
    }
    profile.priority = static_cast<uint8_t>(priority);
    if (password.length() > 0U &&
        !copyField(profile.password, sizeof(profile.password), password)) {
      error = F("password_invalid");
      return false;
    }
  }

  if (aggregateLength > kMaximumPostBytes || !validateConfig(config)) {
    error = F("config_invalid");
    return false;
  }
  return true;
}

void ProvisioningPortal::handleSave() {
  const uint32_t nowMs = millis();
  addNoStoreHeaders();
  if (!active_ || deadlineReached(nowMs, deadlineMs_)) {
    server_.send(410, F("text/plain"), F("portal_expired"));
    return;
  }
  if (static_cast<uint32_t>(deadlineMs_ - nowMs) <= kSaveDeadlineGuardMs) {
    server_.send(410, F("text/plain"), F("portal_expiring"));
    return;
  }
  if (!validContentLength(server_.header(F("Content-Length")))) {
    server_.send(413, F("text/plain"), F("body_too_large_or_missing"));
    return;
  }
  if (!server_.hasArg(F("csrf")) || server_.arg(F("csrf")) != csrfNonce_) {
    server_.send(403, F("text/plain"), F("csrf_invalid"));
    return;
  }
  rotateCsrfNonce();  // A matching nonce is single-use even when validation fails.
  if (saveCount_ >= kMaxSavesPerWindow ||
      (hasSaved_ && elapsed(nowMs, lastSaveMs_) < kSaveRateLimitMs)) {
    server_.send(429, F("text/plain"), F("save_rate_limited"));
    return;
  }
  hasSaved_ = true;
  lastSaveMs_ = nowMs;
  ++saveCount_;

  NetworkConfig config = {};
  String error;
  if (!readFormConfig(config, error)) {
    server_.send(400, F("text/plain"), error);
    return;
  }
  if (store_ == nullptr || !store_->writeCandidate(config, candidate_)) {
    server_.send(503, F("text/plain"), F("config_store_failed"));
    return;
  }

  currentConfig_ = config;
  candidateReady_ = true;
  server_.send(200, F("text/html; charset=utf-8"),
               F("<!doctype html><meta charset='utf-8'><p>Da luu. Node dang thu ket noi; "
                 "cau hinh cu se duoc giu neu thu that bai.</p>"));
  // Keep AP/server alive briefly after send() returns so the TCP response can
  // leave the ESP before the main loop switches back to STA for the trial.
  // This handoff does not change the portal's absolute hard deadline.
  candidateReadyAtMs_ = millis() + kResponseHandoffMs;
}

void ProvisioningPortal::handleNotFound() {
  addNoStoreHeaders();
  server_.sendHeader(F("Location"), F("http://192.168.4.1/"), true);
  server_.send(302, F("text/plain"), "");
}

}  // namespace network
