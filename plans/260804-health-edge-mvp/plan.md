---
title: Health Edge MVP Implementation Plan
status: completed
progress: 100
priority: P1
effort: high
branch: none
tags: [iot, health-edge, esp8266, mqtt, fastapi, sqlite, docker]
created: 2026-08-04
---

# Health Edge MVP Implementation Plan

## Overview

Build a non-clinical IoT prototype using the available NodeMCU ESP8266, MAX30102, MPU-6050, and DS18B20. The node publishes quality-tagged telemetry over Wi-Fi/MQTT through a 5G phone or router hotspot. A Windows laptop runs the MQTT broker, edge service, SQLite database, alert engine, and Vietnamese dashboard.

## Confirmed requirements

### Expected output

- `firmware/health-node/`: PlatformIO firmware for NodeMCU ESP8266.
- `edge/`: FastAPI service, SQLite persistence, MQTT ingestion, alert logic, and static dashboard.
- `simulator/`: MQTT telemetry simulator for testing without hardware.
- `deploy/`: Docker Compose and authenticated Mosquitto configuration.
- `docs/`: wiring, setup, data contract, operation, and troubleshooting guides.
- `tests/`: automated edge and alert-rule tests.

### Acceptance criteria

1. Firmware samples MAX30102, MPU-6050, and DS18B20 with bounded sensor/I²C
   work. The selected PubSubClient reconnect path is synchronously bounded and
   may interrupt motion sampling for roughly two seconds; PPG/fall candidates
   fail closed after the gap and this non-clinical limitation is documented.
2. Firmware publishes versioned JSON telemetry with device ID, timestamp/uptime, sensor values, quality flags, and fall event state.
3. Firmware reconnects after Wi-Fi or MQTT interruption and reports sensor/network status.
4. Edge service validates telemetry, stores it in SQLite, exposes latest/history/alerts APIs, deduplicates alerts, and supports acknowledgement.
5. Dashboard shows connection state, latest measurements, signal-quality state, active alerts, history, and an explicit non-clinical warning.
6. Simulator can drive normal, low-SpO2, abnormal-heart-rate, invalid-signal, and fall scenarios.
7. Automated tests cover schema validation, threshold rules, invalid data suppression, alert deduplication, acknowledgement, and API responses.
8. Secrets are absent from tracked source; local `.env` and firmware `secrets.h` are ignored.

### Scope boundary

- No diagnosis, treatment, emergency dispatch, or clinical accuracy claim.
- No direct M.2/USB 5G modem integration.
- No camera, RFID, PIR, servo, fan, relay, or mains-voltage control.
- No public Internet exposure or production multi-user authentication in this iteration.
- No final medical thresholds; all thresholds are configurable demo values.

### Non-negotiable constraints

- Hardware controller: NodeMCU ESP8266MOD.
- Sensors: MAX30102 breakout, MPU-6050 breakout, waterproof DS18B20 in 3-wire mode.
- Transport: Wi-Fi/MQTT with username/password. Local mode uses the laptop broker for bring-up; 5G-backhaul mode points the same firmware to an authorized remote broker/edge endpoint.
- Edge host: Windows laptop; Docker path preferred, direct Python path documented.
- Local UI language: Vietnamese.
- All timestamps from the device are uptime-based until the edge assigns an authoritative receive time.

### Touchpoints

This is a new project. There are no existing code contracts to preserve. All files are created below `iot-health-edge/`.

## Architecture

```text
MAX30102 + MPU6050 + DS18B20
              |
              v
       NodeMCU ESP8266
       | optional local indicator/button
       | MQTT over Wi-Fi
              v
      Mosquitto local or remote
              |
              v
   FastAPI edge service -> SQLite
              |
              +-> alert engine
              +-> REST API
              +-> Vietnamese dashboard
```

## Phases

### Phase 1 - Contracts and project skeleton

- [x] Define MQTT topics and telemetry schema.
- [x] Add secret-safe configuration templates.
- [x] Add wiring and system architecture documentation.

### Phase 2 - Firmware

- [x] Implement sensor initialization and quality state.
- [x] Implement bounded sensor sampling and MQTT publishing; document the synchronous reconnect gap.
- [x] Implement demo fall detector and local alarm state.
- [x] Implement reconnect/backoff and status publishing.

### Phase 3 - Edge service and dashboard

- [x] Implement database and telemetry ingestion.
- [x] Implement configurable demo alert rules, deduplication, and acknowledgement.
- [x] Implement REST API and Vietnamese dashboard.
- [x] Add Docker Compose and Mosquitto credentials bootstrap.

### Phase 4 - Verification

- [x] Add simulator scenarios.
- [x] Run unit/API tests.
- [x] Build or statically validate firmware.
- [x] Run independent code review and resolve critical findings.
- [x] Update documentation and completion status.

## Verification Evidence

- Edge/API automated tests: 69/69 passed.
- Coverage: line 85.65%; branch 70.42%.
- PlatformIO `nodemcuv2` build: success.
  - RAM: 43.1% (35,292 / 81,920 bytes).
  - Flash: 30.0% (313,059 / 1,044,464 bytes).
- Native `FallDetector` tests: passed.
- Static and integration checks passed for Docker Compose default/full
  configurations, PowerShell, dashboard JavaScript, documentation links,
  wheel package contents (including dashboard assets), and secrets.
- Simulator dry-runs: all 6 scenarios passed (`normal`, `motion_artifact`, `low_spo2`, `high_hr`, `fall`, and `offline`).
- Final independent firmware re-review: PASS after I²C recovery/fail-closed fixes
  and explicit acceptance of the synchronous MQTT reconnect gap.

## Remaining External Validation

- The Docker daemon was off, so real Mosquitto ACL/authentication and MQTT end-to-end tests, plus Docker image build/start, were not run.
- Physical MAX30102, MPU-6050, DS18B20, and NodeMCU operation on a hotspot were not tested or calibrated.
- Local hotspot traffic versus actual 5G-backhaul traversal has not been demonstrated on physical infrastructure.
- This remains a non-clinical prototype and must not be used for diagnosis, treatment, emergency response, or medical decisions.

## Dependencies

- PlatformIO or Arduino-compatible ESP8266 toolchain.
- Docker Desktop for the preferred edge deployment, or Python plus a local Mosquitto installation.
- Laptop and NodeMCU must be mutually reachable on the hotspot LAN.

## Success criteria

- All automated edge tests pass.
- Firmware compiles when the PlatformIO toolchain and libraries are available.
- Simulator contracts exercise every required scenario and dashboard/API smoke
  tests pass; broker-backed simulator-to-dashboard flow remains in the external
  MQTT validation listed above.
- No secret values exist in repository files.
- Documentation clearly distinguishes 5G backhaul from a directly attached 5G UE and labels the system non-clinical.
- Documentation also distinguishes local hotspot LAN traffic from traffic that demonstrably traverses a 5G backhaul.

## Risks

- Phone hotspots may isolate clients; preflight includes a LAN reachability check.
- When the laptop and NodeMCU are peers on the same hotspot, telemetry may stay on the local WLAN. A remote broker/edge endpoint is required before claiming a 5G backhaul measurement.
- Clone MAX30102 breakout boards vary in regulator/level-shifter design; wiring guide requires module verification.
- MAX30102 optical readings are sensitive to finger pressure, ambient light, and motion.
- ESP8266 RAM constrains TLS and large JSON payloads; the MVP uses a compact schema and isolated authenticated MQTT.

The core MVP must run with the user's listed parts. A buzzer and a separate acknowledgement button are optional compile-time extensions; dashboard acknowledgement is the default. The available 10 kΩ resistor can be tried as a DS18B20 pull-up for a short bench cable, while 4.7 kΩ remains the recommended value if readings are unstable.
