#pragma once

#include <stdint.h>

class LocalControls {
 public:
  void begin(uint32_t nowMs);
  void tick(uint32_t nowMs, bool alarmActive, bool networkOnline);
  bool takeAcknowledgement();

 private:
  static uint32_t elapsed(uint32_t nowMs, uint32_t sinceMs);
  void updateButton(uint32_t nowMs);
  void writeIndicators(bool buzzerOn, bool ledOn);

  bool rawButtonPressed_ = false;
  bool stableButtonPressed_ = false;
  bool acknowledgementPending_ = false;
  uint32_t rawButtonChangedMs_ = 0;
};
