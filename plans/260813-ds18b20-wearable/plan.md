---
title: DS18B20 wearable surface temperature migration
status: completed
priority: P1
effort: large
branch: codex/ds18b20-wearable
tags: [firmware, ds18b20, wearable, telemetry-v3]
created: 2026-08-13
completed: 2026-08-13
---

# DS18B20 wearable surface temperature migration

**Progress:** 3/3 phases complete (100%)

## Goal

Replace the wrist node's DHT11 with a non-blocking DS18B20 contact sensor and
publish explicitly non-clinical wrist-surface temperature without changing the
meaning of legacy v1 skin-temperature or v2 environmental records.

## Contract

- Firmware `0.3.0` publishes strict `health.telemetry.v3`.
- `wearable.wrist_surface_temp_c` is paired with
  `quality.wrist_surface_temp_valid`.
- Failed or absent DS18B20 publishes `null`/`false` and
  `ds18b20_unavailable`.
- Edge keeps ingesting v1, v2, and v3; database migration is additive.
- No fever/body/core-temperature claim and no temperature alert rule.

## Phases

| Phase | Description | Status |
|---|---|---|
| 01 | Firmware and telemetry contract | Completed |
| 02 | Edge, simulator, and dashboard | Completed |
| 03 | Verification, documentation, and commit | Completed |

## Acceptance criteria

- [x] DS18B20 on D5/GPIO14 uses powered three-wire mode and asynchronous
      conversion; MAX30102, dual-MPU sampling, MQTT, and fall behavior remain
      operational.
- [x] Strict telemetry v3 validation enforces finite/range and null/valid pairs;
      v1/v2 remain accepted unchanged.
- [x] SQLite migration only adds nullable/defaulted wrist fields and preserves
      all historical rows and raw payloads.
- [x] Dashboard shows wrist-surface temperature for v3 without presenting it as
      body/core temperature; legacy v1/v2 values remain semantically separate.
- [x] Simulator normal/fault scenarios emit exact v3 documents and no
      temperature rule opens an alert.
- [x] Native tests, full Python tests, JavaScript syntax, Compose config, and a
      clean PlatformIO build pass; no hardware upload is performed.
- [x] Secret scan passes and verified changes are committed conventionally.

## Out of scope

- Hardware upload or physical calibration.
- Fever diagnosis, clinical thresholds, or medical certification.
- Removing v1/v2 compatibility or deleting historical database columns.
- Reworking MAX30102, Mpu6Axis, fall thresholds, MQTT topics, or API routes.
