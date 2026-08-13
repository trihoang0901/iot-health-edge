# Phase 1 - Firmware and connectivity

- [x] Replace DallasTemperature/OneWire dependencies with the pinned DHT sensor
      dependency.
- [x] Replace DS18B20 state and fault handling with recoverable DHT11 reads at a
      two-second minimum interval.
- [x] Publish telemetry v2 environmental values and bump firmware version.
- [x] Update only the broker host in ignored `secrets.h`; preserve credentials.
- [x] Add a secret-safe local-IP/MQTT-host preflight to the one-click launcher.
- [x] Build and upload through the detected CH340 port.

Verification gate: firmware compiles with warnings enabled and serial reaches
`mqtt_connected` without DHT11 availability blocking transport.
