# Phase 1 - Core configuration and Telegram worker

## Tasks

- [x] Add fail-fast Telegram settings and bounded numeric validation in
  `edge/config.py`.
- [x] Add disabled-by-default examples to `.env.example` and pass settings into
  the edge container from `deploy/docker-compose.yml`.
- [x] Implement `edge/notifications.py` with a thread-safe bounded queue,
  dedicated lifecycle-managed worker, plain-text message builder, injectable
  HTTPS sender/sleeper, metrics, bounded retry, and secret-safe errors.
- [x] Cover success, API `ok:false`, malformed JSON, timeout/network failures,
  429 `retry_after`, transient 5xx, permanent 4xx, queue full, Unicode/plain
  text, redaction, and clean shutdown in `tests/test_notifications.py`.
- [x] Cover enabled/disabled settings and numeric bounds in
  `tests/test_config.py`.

## Verification

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_notifications.py -q
& .\.venv\Scripts\python.exe -m compileall edge
```
