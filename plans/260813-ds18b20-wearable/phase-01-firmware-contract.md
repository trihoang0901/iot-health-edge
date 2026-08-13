# Phase 01 — Firmware and telemetry contract

- [x] Replace DHT dependency and model with DS18B20/OneWire on D5.
- [x] Implement rollover-safe asynchronous request/read/retry state machine.
- [x] Reject absent devices, wrong family, Dallas sentinels, non-finite and
      out-of-prototype-range values without publishing cached data.
- [x] Publish telemetry v3 wrist fields and DS18B20 fault; bump firmware and
      launcher gate to `0.3.0`.
- [x] Add targeted firmware contract/scheduler regression tests.

No `delay()` or synchronous conversion wait is allowed. Existing MAX30102 FIFO
recovery and dual-MPU logic must stay functionally unchanged.
