---
title: Telegram Alert Notifications
status: completed
progress: 100
priority: P1
effort: medium
branch: none
tags: [telegram, notifications, fastapi, mqtt, non-clinical]
created: 2026-08-12
---

# Telegram Alert Notifications

## Expected output

The edge service can optionally send Vietnamese Telegram messages from a bounded
background worker. Configuration is local through `.env`; Telegram is disabled
by default and no credential is stored in source.

## Acceptance criteria

1. `TELEGRAM_ENABLED=true` requires a non-empty bot token and chat ID; disabled
   mode requires neither and starts no notification worker.
2. A threshold rule sends once when a new alert opens, not on later touches,
   acknowledgement, or resolution; reopening after resolution sends again.
3. Every new fall `event_id` sends once, including a new event while a fall
   alert is already active; a retransmitted duplicate does not send.
4. Enqueue is non-blocking and bounded. A full queue or Telegram failure never
   rejects an otherwise valid MQTT message or stops ingestion/dashboard work.
5. Telegram delivery uses plain UTF-8 text, a finite request timeout, bounded
   attempts, `retry_after` for HTTP 429, bounded backoff for network/5xx errors,
   and no retry for other permanent 4xx responses.
6. Logs and metrics never contain the bot token, chat ID, token-bearing URL,
   request body, or raw Telegram response body.
7. Messages contain only the alert summary, device, optional reference value,
   edge timestamp, and an explicit non-clinical/non-emergency warning.
8. Existing REST, MQTT, firmware, simulator, database, and dashboard contracts
   remain unchanged; the complete automated test suite passes.

## Scope boundary

- Telegram only; no Slack and no inbound bot commands.
- No durable SQLite outbox or delivery guarantee across a crash/restart.
- No messages for acknowledgement or resolution.
- No real Telegram request in automated tests and no user credential in chat.
- No diagnosis, treatment, emergency dispatch, or medical-accuracy claim.

## Non-negotiable constraints

- Use the Python standard library for HTTPS; do not add an SDK dependency.
- Use a standard thread-safe bounded queue and a dedicated daemon worker.
- Keep Telegram optional and disabled by default.
- Never run outbound HTTP inside the MQTT callback, SQLite write lock, or
  ingestion worker beyond the non-blocking enqueue operation.
- Preserve all public API and MQTT schemas.

## Touchpoints

- New: `edge/notifications.py`, `tests/test_notifications.py`.
- Extend: `edge/config.py`, `edge/service.py`, `edge/app.py`.
- Configure: `.env.example`, `deploy/docker-compose.yml`.
- Test: `tests/test_config.py`, `tests/test_ingestion.py`, `tests/test_api.py` as
  needed without real network access.
- Document: `README.md`, `docs/windows-quickstart.md`,
  `docs/network-and-security.md`, `docs/troubleshooting.md`,
  `docs/test-checklist.md`.

## Phases

| Phase | File | Status |
|---|---|---|
| 1 | [Core configuration and Telegram worker](phase-01-core.md) | completed |
| 2 | [Alert integration and lifecycle](phase-02-integration.md) | completed |
| 3 | [Verification and documentation](phase-03-verification-docs.md) | completed |

## Risks accepted for this iteration

- The in-memory queue can lose pending messages on process crash/restart or
  discard them when full; Telegram is best-effort and not an emergency channel.
- Telegram may accept a message just before a client timeout, so a retry can
  rarely produce a duplicate.
- Sending alert summaries to Telegram is third-party data egress; content is
  deliberately minimized and must be enabled explicitly by the user.

## Completion evidence

- Full Python suite: 115 tests passed; Python compilation completed.
- Docker Compose full-profile configuration passed with the current `.env` and
  the disabled-by-default `.env.example`, without resolved output.
- Documentation links passed with no broken local target. The concrete-token,
  private-key, and cloud-key scan found no credential-shaped value; two dynamic
  Telegram API URL constructions were reviewed as expected code/documentation,
  not embedded credentials.
- Firmware, MQTT schemas, REST responses, database schema, simulator, and
  dashboard assets remain outside the Telegram integration surface.
- Specification review passed 100/100, code-quality re-review passed 9.9/10,
  and adversarial Stage 3 review passed 9.8/10 with no must-fix finding.
- Real phone delivery remains intentionally unverified until the operator adds
  the bot token and chat ID privately and performs the documented test.
