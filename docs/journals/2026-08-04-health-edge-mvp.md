---
title: Health Edge MVP Implementation Journal
date: 2026-08-04
status: completed
tags: [iot, health-edge, esp8266, mqtt, fastapi, sqlite, docker]
---

# Health Edge MVP - Implementation Journal

## Outcome

Completed the code and documentation baseline for a non-clinical health-monitoring prototype: ESP8266 firmware, versioned MQTT contracts, FastAPI/SQLite edge ingestion and demo alert rules, a Vietnamese dashboard, simulator scenarios, Docker packaging, and operator guides.

## Key Decisions

- Treat the phone/router 5G connection as backhaul, not as a directly attached 5G sensor modem. Local hotspot peer traffic is not evidence that telemetry traversed 5G.
- Use versioned MQTT topics and schemas, explicit quality flags, and `null` for invalid measurements.
- Keep normal sensor work bounded, cap I2C clock stretching, detect lost PPG
  samples, and fail closed after a sampling gap. PubSubClient reconnect remains
  synchronous and is explicitly accepted as a roughly two-second non-clinical
  MVP gap rather than described as fully nonblocking.
- Centralize MQTT ingestion at the edge and use SQLite transactions, deduplication, acknowledgement, threshold holds, and hysteresis for demo alerts.
- Keep the local dashboard bound to loopback by default; make the full Mosquitto profile optional and preserve persistent data through named volumes.

## Safeguards

- The UI and documentation label the system as non-clinical and exclude diagnosis, treatment, emergency dispatch, and clinical-accuracy claims.
- Credentials use ignored local files and templates; authenticated Mosquitto ACLs separate device publishing from edge consumption.
- Invalid or poor-quality sensor values are suppressed from alert evaluation, and acknowledgements do not erase alert history.
- Optional local alarm hardware remains disabled unless explicitly configured; dashboard acknowledgement is the default.

## Verification Evidence

- Pytest: 69/69 tests passed; line coverage 85.65%; branch coverage 70.42%.
- PlatformIO `nodemcuv2` build: success; RAM 43.1% (35,292 / 81,920 bytes); flash 30.0% (313,059 / 1,044,464 bytes).
- Native `FallDetector` tests passed.
- Docker Compose default/full configuration, PowerShell, dashboard JavaScript,
  documentation-link, wheel-content, and secret checks passed.
- All 6 simulator dry-runs passed: `normal`, `motion_artifact`, `low_spo2`, `high_hr`, `fall`, and `offline`.
- Final independent firmware re-review passed.

## Remaining Limitations

- The Docker daemon was off. Real Mosquitto ACL/authentication and MQTT end-to-end behavior, along with Docker image build/start, remain unverified.
- The physical MAX30102, MPU-6050, DS18B20, NodeMCU, and hotspot path were not tested or calibrated.
- Synchronous MQTT reconnect can interrupt motion/fall sampling for roughly two
  seconds per backed-off attempt; an event occurring entirely inside that gap
  can be missed.
- No physical test has yet distinguished local hotspot LAN traffic from telemetry that demonstrably traverses a 5G backhaul.
- The prototype is not a medical device and must not be used for medical decisions or emergency response.

## Next Operator Steps

1. Start Docker Desktop, initialize local credentials with the actual device ID, then build and start the full Compose profile.
2. Run authenticated Mosquitto ACL and MQTT end-to-end tests first with the simulator, then with the NodeMCU.
3. Wire the physical sensors, verify power and I2C addressing, confirm the DS18B20 pull-up, and collect calibration/quality traces.
4. Test laptop-to-NodeMCU reachability on the intended hotspot and document whether traffic remains local or traverses a remote 5G-backed endpoint.
5. Re-run the verification checklist after hardware validation and retain the non-clinical limitation in every demonstration.
