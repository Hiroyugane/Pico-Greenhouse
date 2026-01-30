# Pi Greenhouse: AI Coding Agent Instructions

## Big picture architecture (DI-first, async runtime)
- `main.py` is the orchestrator: validates config, initializes hardware via `HardwareFactory`, then composes providers/services and spawns async tasks.
- Hardware init order matters: RTC (critical) → SPI/SD mount → GPIO pins. Hardware is created only in `HardwareFactory`, then injected.
- Time flows through `TimeProvider`/`RTCTimeProvider`; all timestamps and scheduling depend on it (no direct `rtc.ReadTime()` outside provider).
- Storage is centralized in `BufferManager`: writes to SD when available, falls back to `/local/fallback.csv`, and migrates fallback before new primary writes to preserve CSV ordering.
- `EventLogger` buffers console+file logs and flushes via `BufferManager` (errors flush immediately).
- `DHTLogger` writes `/sd/dht_log_YYYY-MM-DD.csv` with date-based rollover and LED blink feedback; cached `last_temperature` feeds `FanController` thermostat.
- Relay logic uses composition: `RelayController` base, `FanController` (schedule + thermostat), `GrowlightController` (dawn/sunset, can auto-calc via `sunrise_sunset`).
- `ServiceReminder` uses `LEDButtonHandler` for debounced button interrupts and persistent timestamp storage.

## Critical workflows
- First run: execute `rtc_set_time.py` on-device via Thonny to sync RTC.
- Normal run: execute `main.py` on-device via Thonny; check `/sd/dht_log_YYYY-MM-DD.csv` and `/sd/system.log`.
- Host tests: run `pytest tests/`; MicroPython modules are mocked in `tests/conftest.py`.

## Project-specific conventions
- Avoid module-level hardware initialization; use dependency injection for testability.
- Long-running logic must be `uasyncio` tasks with `await asyncio.sleep()` (no blocking loops).
- Relay GPIO logic is inverted (HIGH=off, LOW=on) across controllers.
- Prefer `BufferManager.write(relpath, data)` with relpaths (e.g., `dht_log_YYYY-MM-DD.csv`) not absolute SD paths.

## Integration points & dependencies
- MicroPython-only modules: `machine`, `dht`, `uasyncio`; device drivers in `lib/` (`ds3231.py`, `sdcard.py`).
- Test stubs for MicroPython live in `tests/stubs/` and are wired in `tests/conftest.py`.
- Configuration lives in `config.py` (`DEVICE_CONFIG`), including GPIO pins, schedules, and thresholds.
