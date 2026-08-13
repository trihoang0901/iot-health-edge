# Phase 02 — Edge, simulator, and dashboard

- [x] Add strict TelemetryV3 parsing while preserving v1/v2 validation.
- [x] Add non-destructive wrist columns and explicit v1/v2/v3 normalization.
- [x] Make simulator emit v3 normal and `ds18b20_fault` scenarios.
- [x] Replace live DHT cards/chart with wrist-surface temperature and preserve
      stale/offline/error semantics.
- [x] Prove temperature never creates a health alert.

Normalized API responses are a superset: unrelated schema fields are `null`
with validity `false`; no legacy value is reinterpreted as a wrist reading.
