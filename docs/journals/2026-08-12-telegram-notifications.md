---
title: Telegram Notifications Implementation Journal
date: 2026-08-12
status: completed
tags: [telegram, notifications, fastapi, mqtt, security, non-clinical]
---

# Telegram Notifications - Implementation Journal

## Outcome

Added optional Vietnamese Telegram notifications for new threshold alerts and
new fall events. Delivery runs outside MQTT ingestion in a bounded background
worker, is disabled by default, and preserves the existing REST, MQTT, SQLite,
firmware, simulator, and dashboard contracts.

## Key Decisions

- Use the Python standard library and a fixed Telegram Bot API host instead of
  adding an SDK dependency or a configurable outbound URL.
- Enqueue notifications without blocking ingestion. Threshold alerts notify
  only when opened or reopened; fall events notify once per accepted event ID.
- Keep delivery best-effort with a bounded in-memory queue, finite retries,
  clamped Telegram `retry_after`, bounded response reads, and explicit request
  and shutdown timeouts.
- Treat Telegram as an optional third-party egress channel. Local `.env`
  settings enable it explicitly; credentials are excluded from messages,
  application representations, normalized errors, tests, and documentation.
- Keep messages concise and explicitly state that the prototype is not a
  medical or emergency-response system.

## Review Findings Resolved

- Network failures now consistently classify `OSError`, `TimeoutError`,
  `HTTPException`, and incomplete HTTP reads as retryable without retaining raw
  exception text.
- A full notification queue is verified not to reject or roll back a valid
  alert accepted by ingestion.
- Runtime cleanup now uses nested `finally` blocks so MQTT, ingestion, and the
  notifier all receive a stop attempt even when an earlier cleanup step fails.

## Verification Evidence

- Full Python suite: 115 tests passed with no failures, skips, or warnings.
- Python compilation completed successfully for `edge` and `tests`.
- Docker Compose full-profile configuration passed with the current local
  environment and with `.env.example`; resolved secrets were not printed.
- Independent specification review passed 100/100, code-quality re-review
  passed 9.9/10, and adversarial Stage 3 review passed 9.8/10 with no must-fix
  finding.
- Automated tests force Telegram and MQTT transport off unless a test provides
  a local fake; no real Telegram request or user credential was used.

## Accepted Limits

- Pending notifications can be lost when the queue is full or the process
  crashes or restarts because this iteration has no durable outbox.
- A rare duplicate is possible if Telegram accepts a request immediately before
  the client times out and retries.
- Notifier delivery health is logged and counted internally but is intentionally
  not added to the existing public health response.
- Real phone delivery remains an operator verification step after the user
  privately configures a bot token and chat ID.

## Next Operator Steps

1. Create a bot with BotFather, start a private chat with it, and obtain the
   target chat ID using the documented credential-safe procedure.
2. Set `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` in
   the local `.env`; never paste those values into chat, logs, or source files.
3. Restart the stack and run one simulator alert scenario, then confirm the
   message on the phone and disable Telegram again if third-party egress is not
   desired.
