---
title: DHT11 and Health Node Connectivity Migration
status: completed
progress: 100
priority: P1
effort: medium
branch: none
tags: [iot, esp8266, dht11, mqtt, telemetry-v2, dashboard]
created: 2026-08-12
---

# DHT11 and Health Node Connectivity Migration

## Objective

Replace the DS18B20 surface-temperature path with a DHT11 environmental sensor
that reports ambient temperature and humidity, while restoring the physical
`health-node-01` MQTT connection and preserving ingestion of historical
`health.telemetry.v1` messages.

The completed MVP plan in `../260804-health-edge-mvp/plan.md` remains an
unchanged historical record. This plan is the auditable migration amendment.

## Expected output

- NodeMCU firmware reads DHT11 on D5/GPIO14 and publishes
  `health.telemetry.v2` with `environment.ambient_temp_c` and
  `environment.humidity_pct` plus independent validity flags.
- Edge accepts telemetry v1 and v2, migrates SQLite without deleting v1 rows,
  and exposes both legacy and environmental measurements through the existing
  REST endpoints.
- The Vietnamese dashboard displays ambient temperature and humidity, removes
  the surface/body-temperature implication, and clearly labels cached values
  when the node is offline.
- The local one-click launcher rejects a stale/non-local firmware MQTT broker
  IPv4 before flashing in its local-broker workflow.
- The local ignored `secrets.h` points to the laptop's current broker IPv4 and
  firmware is built/uploaded to the detected CH340 NodeMCU.

## Acceptance criteria

1. DS18B20, OneWire, and DallasTemperature are absent from active firmware and
   DHT11 is sampled no more frequently than once every two seconds.
2. A failed DHT11 read produces JSON `null`, false validity flags, and the
   technical fault `dht11_unavailable`; it never blocks MQTT publication.
3. New firmware publishes `health.telemetry.v2`; v1 payloads remain accepted by
   edge tests and existing SQLite rows remain readable after migration.
4. Environmental values are bounded and paired with validity flags; no DHT11
   value is described as skin, body, or core temperature.
5. The old `surface_temp_demo` rule is not advertised or evaluated. HR, SpO2,
   fall-event behavior, acknowledgement, and Telegram behavior do not regress.
6. The dashboard renders four measurements (HR, SpO2, ambient temperature,
   humidity), supports both environmental chart metrics, and marks latest data
   as stale when `device.online=false`.
7. One-click local startup catches an MQTT host that does not match any current
   non-loopback laptop IPv4 without printing credentials.
8. PlatformIO build and the full Python test suite pass. After upload, serial
   shows `wifi_connected` and `mqtt_connected`, Mosquitto sees a
   `health-node-01-*` client, and `/api/v1/devices` reports fresh `online=true`.
9. Physical DHT11 readings are reported only as an electrical/runtime bring-up;
   no medical accuracy, calibration, diagnosis, or 5G traversal is claimed.

## Scope boundary

- No clinical thresholds or alerts for DHT11 values.
- No claim that ambient temperature represents a person's temperature.
- No Internet exposure, MQTT TLS deployment, remote broker, or 5G performance
  validation in this migration.
- No deletion of historical SQLite data and no destructive credential reset.
- No changes to MAX30102/MPU-6050 algorithms beyond regression-safe integration.

## Constraints and contracts

- Controller: NodeMCU ESP8266; DHT11 DATA remains on D5/GPIO14.
- Topic paths, `health.event.v1`, and `health.status.v1` remain unchanged.
- Telemetry v2 uses an explicit `environment` object; edge keeps strict schema
  validation and forbids unknown fields.
- Secrets remain local and ignored. Diagnostics may report only status, never
  Wi-Fi or MQTT passwords.
- Existing API routes remain stable; response additions are backward-compatible.

## Phases

| Phase | File | Status |
|---|---|---|
| 1 | [Firmware and connectivity](phase-01-firmware-connectivity.md) | Completed |
| 2 | [Edge, schema, simulator, and dashboard](phase-02-edge-dashboard.md) | Completed |
| 3 | [Verification and documentation](phase-03-verification-docs.md) | Completed |

## Completion evidence

- Fresh final Python suite: 139 passed, 0 failed.
- Clean PlatformIO build: RAM 43.1%, flash 29.7%, binary 314,480 bytes.
- Firmware `0.2.0` uploaded on COM10; Serial captured `wifi_connected` and
  `mqtt_connected`.
- Broker observed the health-node client; API returned fresh
  `health.telemetry.v2`, firmware `0.2.0`, and `online=true`.
- Live dashboard showed the four intended measurements and explicit
  `DHT11 không sẵn sàng` states instead of fabricated values.
- Physical DHT11, MAX30102, and MPU-6050 reads remained unavailable during the
  final run. This is an electrical/wiring bring-up follow-up, not a transport
  or schema failure; the firmware reports technical faults and continues MQTT.

## Rollback

- Source rollback: restore the pre-migration firmware and edge files; do not
  remove the new nullable SQLite columns.
- Runtime rollback: flash the last known firmware binary and restart the prior
  edge image. Telemetry v1 data remains intact.
- Network rollback never regenerates passwords; restore only the prior local
  broker host if the network topology intentionally changes.
