#include "LocalControls.h"

#include <Arduino.h>

#include "AppConfig.h"

uint32_t LocalControls::elapsed(uint32_t nowMs, uint32_t sinceMs) {
  return static_cast<uint32_t>(nowMs - sinceMs);
}
void LocalControls::begin(uint32_t nowMs) {
#if ENABLE_LOCAL_BUZZER
  digitalWrite(config::kBuzzerPin, LOW);
  pinMode(config::kBuzzerPin, OUTPUT);
#endif

#if ENABLE_LOCAL_ACK_BUTTON
  pinMode(config::kAckButtonPin, INPUT_PULLUP);
  rawButtonPressed_ = digitalRead(config::kAckButtonPin) == LOW;
  stableButtonPressed_ = rawButtonPressed_;
  rawButtonChangedMs_ = nowMs;
#else
  (void)nowMs;
#endif

#if ENABLE_BUILTIN_LED
  digitalWrite(LED_BUILTIN, HIGH);  // NodeMCU built-in LED is active-low.
  pinMode(LED_BUILTIN, OUTPUT);
#endif
}

void LocalControls::tick(uint32_t nowMs, bool alarmActive, bool networkOnline) {
  updateButton(nowMs);

  bool buzzerOn = false;
  bool ledOn = false;
  if (alarmActive) {
    const uint32_t patternMs = config::kBuzzerOnMs + config::kBuzzerOffMs;
    const bool alertPulse = (nowMs % patternMs) < config::kBuzzerOnMs;
    buzzerOn = alertPulse;
    ledOn = alertPulse;
  } else if (networkOnline) {
    ledOn = (nowMs % 2000U) < 50U;
  } else {
    ledOn = (nowMs % 1000U) < 100U;
  }
  writeIndicators(buzzerOn, ledOn);
}

void LocalControls::updateButton(uint32_t nowMs) {
#if ENABLE_LOCAL_ACK_BUTTON
  const bool pressed = digitalRead(config::kAckButtonPin) == LOW;
  if (pressed != rawButtonPressed_) {
    rawButtonPressed_ = pressed;
    rawButtonChangedMs_ = nowMs;
  }

  if (rawButtonPressed_ != stableButtonPressed_ &&
      elapsed(nowMs, rawButtonChangedMs_) >= config::kButtonDebounceMs) {
    stableButtonPressed_ = rawButtonPressed_;
    if (stableButtonPressed_) {
      acknowledgementPending_ = true;
    }
  }
#else
  (void)nowMs;
#endif
}

void LocalControls::writeIndicators(bool buzzerOn, bool ledOn) {
#if ENABLE_LOCAL_BUZZER
  digitalWrite(config::kBuzzerPin, buzzerOn ? HIGH : LOW);
#else
  (void)buzzerOn;
#endif

#if ENABLE_BUILTIN_LED
  digitalWrite(LED_BUILTIN, ledOn ? LOW : HIGH);
#else
  (void)ledOn;
#endif
}

bool LocalControls::takeAcknowledgement() {
  const bool pending = acknowledgementPending_;
  acknowledgementPending_ = false;
  return pending;
}
