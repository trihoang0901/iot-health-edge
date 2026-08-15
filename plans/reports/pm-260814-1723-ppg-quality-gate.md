---
title: PPG quality gate completion
status: completed
date: 2026-08-14
branch: codex/nt532-mqtt-reliability-mvp
tags: [ppg, firmware, telemetry-v4, dashboard]
---

# PPG Quality Gate Completion

## Summary

| Hạng mục | Kết quả |
|---|---|
| Firmware | `PpgQualityGate`, fw `0.4.0`, telemetry v4 raw/confirmed |
| Backend | SQLite additive migration, normalized measurements, recovery 10 s |
| Dashboard | Confirmed-only; reason tiếng Việt; “Đang xác nhận” |
| Automated tests | `304 passed` |
| Native C++ | Compile `-Werror` + behavior pass |
| PlatformIO | Success; RAM 43,3%; flash 29,8% |
| JS / Compose | Syntax pass / config quiet pass |
| Physical upload | `NOT_VERIFIED` — không thực hiện trong phiên này |

## Acceptance

- [x] Median/Hampel 5 candidate, cần 3 cửa sổ nhất quán.
- [x] RR median/MAD, clipping, low-perfusion, motion, warming/no-finger/sample-loss.
- [x] Jump trên 25 bpm không giữ số cũ và phải xác nhận lại.
- [x] SpO₂ có dispersion gate riêng; sample-loss xóa raw-valid.
- [x] Raw/confirmed/reason đi xuyên firmware → SQLite/API → dashboard.
- [x] Alert chỉ dùng confirmed; invalid không resolve; recovery cần chuỗi liên tục.
- [x] Launcher fail-closed nếu post-upload không thấy v4/fw `0.4.0`.

## Review

Review độc lập phát hiện 3 lỗi correctness; cả 3 đã được sửa và có regression:
SpO₂ false-confirm, raw-valid ở sample-loss, và launcher post-upload exit 0.

## Known limitations

- Chưa upload `0.4.0`; chưa có fresh finger-present HR/SpO₂ hardware pass.
- Chưa có logger/artifact raw Red/IR + IMU để tune LED/ADC trên dữ liệu thật.
- Gate hiện abstain khi chuyển động; không phải motion-compensation cho cổ tay.
- Worktree có thay đổi MQTT credential/Wi-Fi và deliverable có sẵn từ trước;
  chúng được giữ nguyên và không thuộc scope PPG.

## Next

1. Làm kẹp ngón tay, che sáng, giữ lực ép lặp lại.
2. Tạo diagnostic capture riêng, không chứa credential production.
3. Upload `0.4.0`, thu fresh v4 end-to-end và đối chiếu chest strap/ECG tham chiếu.
