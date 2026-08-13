# Phase 3 - Verification and documentation

## Tasks

- [x] Document BotFather setup, obtaining a chat ID without exposing it,
  `.env` configuration, Docker restart, a safe test procedure, and disable/
  troubleshooting steps.
- [x] Document Telegram as optional third-party egress, best-effort delivery,
  in-memory queue loss limits, and a non-clinical/non-emergency channel.
- [x] Update the Windows quickstart and checklist while preserving the one-click
  launcher workflow.
- [x] Run the complete Python test suite and compile checks.
- [x] Validate Docker Compose with Telegram disabled and with placeholder-free
  dummy test values, without printing resolved secrets.
- [x] Run a secret-pattern scan that excludes `.env` and local secret files.
- [x] Confirm firmware, MQTT schemas, REST responses, database schema, and
  dashboard assets were not changed.

## Result

- 115/115 Python tests passed and `compileall` succeeded.
- Compose validation succeeded for the current environment and `.env.example`.
- No concrete token-, private-key-, or cloud-key-shaped credential was found in
  tracked project text after excluding local secret and generated directories.
- Documentation link validation reported no broken local link.
- The protected firmware/schema/database/simulator/dashboard scope contains no
  Telegram integration reference; public data contracts remain unchanged.

## Verification

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m compileall edge tests
docker compose --env-file .\.env -f .\deploy\docker-compose.yml --profile full config --quiet
rg -n --hidden -g "!.env" -g "!secrets.h" "[0-9]{8,10}:[A-Za-z0-9_-]{30,}" .
```
