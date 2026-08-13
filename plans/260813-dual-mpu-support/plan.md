---
title: Dual MPU6050 and MPU6500-compatible IMU support
status: completed
priority: P1
effort: medium
branch: none
tags: [firmware, imu, mpu6050, mpu6500]
created: 2026-08-13
completed: 2026-08-13
---

# Dual MPU6050 / MPU6500-compatible IMU support

**Progress:** 6/6 acceptance criteria complete (100%)
**Scope:** NodeMCU firmware motion sensor path and active documentation

## Goal

Support both a genuine MPU6050 (`WHO_AM_I=0x68`) and the installed
MPU6500-compatible module (`WHO_AM_I=0x70`) without weakening I2C error
handling or changing the MQTT/API telemetry contract.

## Implementation

- Add a project-owned `Mpu6Axis` driver that probes address `0x68`, accepts
  only IDs `0x68` and `0x70`, and rejects unknown devices.
- Configure both variants for ±8 g, ±500 dps, and approximately 20–21 Hz
  filtering. Configure `ACCEL_CONFIG2` only for ID `0x70`.
- Read the 14-byte motion frame from register `0x3B`; require a successful
  register transaction and the complete frame before publishing a sample.
- Integrate the driver into `SensorHub` while retaining 50 Hz sampling, I2C
  recovery, retry behavior, fall thresholds, telemetry fields, and the legacy
  compatibility fault name `mpu6050_unavailable`.
- Remove the unused Adafruit MPU6050 dependency and bump firmware to `0.2.1`.

## Acceptance criteria

- [x] ID `0x68` and `0x70` initialize; any other ID fails closed.
- [x] NACK or a partial 14-byte frame makes motion invalid and sets the existing
  MPU fault instead of publishing stale/fabricated values.
- [x] Host tests cover identity classification, signed big-endian frame decoding,
  and ±8 g / ±500 dps scaling.
- [x] Native fall tests, full Python tests, and a clean NodeMCU PlatformIO build
  pass without new warnings from project-owned code.
- [x] After uploading to COM10, the node reconnects with firmware `0.2.1`, sequence
  numbers advance, `motion_valid=true`, acceleration and gyro are finite,
  stationary acceleration is plausibly near 1 g, and
  `mpu6050_unavailable` is absent.
- [x] MQTT schema remains `health.telemetry.v2`; edge/API/database contracts do not
  change. MAX30102 and DHT11 behavior remains fail-closed and independent.

## Verification summary

- Native C++: 11/11 cases passed with `-Wall -Wextra -Werror`.
- Python: 142/142 tests passed; Compose configuration and documentation links
  passed independent QA.
- PlatformIO clean build: RAM 43.0%, flash 29.3%; no new project-owned warning.
- COM10: firmware `0.2.1`, Serial Wi-Fi/MQTT connected, broker client connected.
- Ten fresh samples in one boot advanced `seq 30` to `40`; all motion samples
  were valid, acceleration was `0.934–0.945 g`, gyro was `1.47–3.37 dps`, and
  the MPU fault was absent.

## Out of scope

- Clinical or safety certification, calibration, and falls involving a person.
- Renaming the public fault key or changing telemetry/database schemas.
- DMP, fusion/orientation output, temperature from the IMU, and SPI support.
- Repairing or validating the currently disconnected MAX30102/DHT11 modules.
