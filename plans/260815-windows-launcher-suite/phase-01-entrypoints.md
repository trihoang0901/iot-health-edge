# Phase 01 - Entry points

- [x] Add `IOT-HEALTH-EDGE.ps1` with explicit action dispatch.
- [x] Add thin BAT wrappers for install, software, hardware, stop, status and
  logs.
- [x] Preserve `%~dp0`, exit codes and `--no-pause` behavior.
- [x] Convert `START-IOT-HEALTH-EDGE.bat` into the backward-compatible entry
  point that preserves the no-CH340 software fallback.
