# Phase 2 - Edge, schema, simulator, and dashboard

- [x] Add strict `health.telemetry.v2` validation while retaining v1 parsing.
- [x] Add a non-destructive SQLite migration for schema version, ambient
      temperature, humidity, and validity fields.
- [x] Preserve existing REST routes and return normalized legacy/environmental
      data.
- [x] Remove the surface-temperature demo rule without affecting HR, SpO2,
      fall, acknowledgement, or notification behavior.
- [x] Update the simulator to emit telemetry v2 environmental values and a DHT
      failure scenario.
- [x] Update the Vietnamese dashboard to display ambient temperature/humidity,
      chart both metrics, and distinguish stale cached data from live data.
- [x] Add schema, migration, ingestion, API, simulator, and static UI tests.

Verification gate: all Python tests pass and v1/v2 payloads coexist in one
database without loss.
