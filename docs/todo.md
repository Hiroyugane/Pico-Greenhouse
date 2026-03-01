# Todo

## Completed

- [x] Refactor logging — add DEBUG severity level with structured `key=value` fields for AI-parseable diagnostics
- [x] AI agents — comprehensive Copilot instructions, prompt library, conventions doc
- [x] GitHub Actions CI pipeline (lint → test → host-sim-smoke)
- [x] Inject `EventLogger` into `BufferManager`, `LEDButtonHandler`, `ServiceReminder`
- [x] Migrate `print()` calls to structured logger with fallback

## Backlog

- [ ] CO2 sensor integration (UART on GP0/GP1, new `CO2Logger` + `CO2Controller`)
- [ ] OLED display module (I2C on GP2/GP3, status dashboard)
- [ ] OTA update mechanism (Wi-Fi Pico W variant)
- [ ] Device-side integration tests (run on Pico via Thonny)
- [ ] Performance benchmarks (startup time, memory usage, 24h soak test)
