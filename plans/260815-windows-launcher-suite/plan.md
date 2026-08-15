---
title: Windows launcher suite
description: Safe install and lifecycle launchers for the IoT Health Edge Windows workflow
status: completed
priority: P1
effort: medium
branch: codex/nt532-mqtt-reliability-mvp
tags: [windows, launcher, powershell, docker, platformio]
created: 2026-08-15
---

# Windows launcher suite

## Goal

Tach launcher Windows thanh bo lenh cai dat va van hanh ro rang, giu nguyen
workflow nap firmware fail-closed va cung cap duong khoi dong software khong
the tac dong toi NodeMCU.

## Acceptance criteria

- Co mot loi PowerShell dung chung va cac wrapper BAT cho install, software,
  hardware, stop, status va logs.
- Tat ca wrapper chay dung khi duoc goi tu working directory bat ky, bao toan
  exit code va ho tro `--no-pause`.
- Software start khong doc `secrets.h`, khong do CH340/PlatformIO, khong auth
  probe firmware va khong upload.
- Hardware start giu thu tu Compose, readiness, credential probe, upload va
  fresh telemetry v4/firmware 0.4.0 gate.
- Install khong ghi de `.env`, secret hay Mosquitto credential hien huu.
- Stop khong xoa Docker volume; logs khong dung inspect/config va khong doc
  `.env`.
- Contract tests, full pytest va Docker Compose config deu dat.

## Scope boundary

- Khong tu cai Docker Desktop, Python hoac driver CH340.
- Khong tao, hien thi, ghi de hoac dua secret vao log.
- Khong chay hardware launcher trong validation tu dong.
- Khong sua artifact/evidence lich su hoac thu muc `new-clone/` khong duoc Git
  theo doi.

## Phases

| Phase | Description | Status |
| --- | --- | --- |
| 01 | Shared PowerShell entrypoint and BAT wrappers | completed |
| 02 | Safe action behavior and backward compatibility | completed |
| 03 | Contract tests and verification fingerprint | completed |
| 04 | Documentation and validation | completed |

Progress: **16/16 tasks (100%)**.
