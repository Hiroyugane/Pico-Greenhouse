# Pi Greenhouse: AI Coding Agent Instructions

## Big-picture architecture (DI-first, async runtime)
- `main.py` is the orchestrator: validates config via `validate_config()`, initialises hardware via `HardwareFactory`, composes providers/services, and spawns `uasyncio` tasks.
- Initialisation order (9 steps): validate config → `HardwareFactory.setup()` (RTC → SPI/SD → GPIO) → `RTCTimeProvider` → `BufferManager` → `EventLogger` → `DHTLogger` → `FanController` ×2 + `GrowlightController` → `LEDButtonHandler` + `ServiceReminder` → spawn async tasks + health-check loop.
- Hardware is created only in `HardwareFactory`, then injected; no module-level hardware init anywhere.
- Time flows through `TimeProvider`/`RTCTimeProvider`; all timestamps and scheduling depend on it (no direct `rtc.ReadTime()` outside provider).
- Storage is centralised in `BufferManager`: writes to SD when available, falls back to `/local/fallback.csv`, buffers in RAM, and migrates fallback before new primary writes to preserve CSV ordering.
- `EventLogger` buffers console+file logs and flushes via `BufferManager` (errors flush immediately); auto-rotates at 50 KB.
- `DHTLogger` writes `/sd/dht_log_YYYY-MM-DD.csv` with date-based rollover and LED blink feedback on GP4; cached `last_temperature` feeds `FanController` thermostat.
- Relay logic uses composition: `RelayController` base → `FanController` (schedule + thermostat with hysteresis) and `GrowlightController` (dawn/sunset, can auto-calc via `sunrise_sunset`). GPIO is inverted (HIGH=off, LOW=on).
- Two fan controllers with independent configs: Fan 1 (GP16, 600 s cycle, 23.8 °C threshold) and Fan 2 (GP18, 500 s cycle, 27.0 °C threshold).
- `GrowlightController` (GP17): configurable dawn/sunset (default 07:00–19:00); supports auto-calculation from `lib/sunrise_sunset_2026.csv` when times are `None`.
- `ServiceReminder` uses `LEDButtonHandler` (GP5 LED + GP9 button) for debounced button interrupts and persistent timestamp storage.
- Menu button (GP9): short press = cycle display menu (future OLED), long press ≥ 3 s = reset service reminder.
- 5 status LEDs: GP4 (DHT read), GP5 (reminder), GP6 (SD), GP7 (fan), GP8 (error); plus GP25 on-board heartbeat.
- Main loop runs periodic health checks: SD hot-swap recovery via `hardware.refresh_sd()`, in-memory buffer flush, and fallback migration.

## Critical workflows
- First run: execute `rtc_set_time.py` on-device via Thonny to sync RTC.
- Normal run: execute `main.py` on-device via Thonny; check `/sd/dht_log_YYYY-MM-DD.csv` and `/sd/system.log`.
- Host simulation: `python main.py` on Windows/CPython; `host_shims/` auto-detected via `sys.implementation.name`; writes to `./sd/` and `./local/`.
- Host tests: `pytest tests/`; MicroPython modules are mocked in `tests/conftest.py`.

## Project-specific conventions
- Avoid module-level hardware initialisation; use dependency injection for testability.
- Long-running logic must be `uasyncio` tasks with `await asyncio.sleep()` (no blocking loops).
- Relay GPIO logic is inverted (HIGH=off, LOW=on) across all relay controllers.
- Prefer `BufferManager.write(relpath, data)` with relative paths (e.g., `dht_log_YYYY-MM-DD.csv`) not absolute SD paths.
- All tunable values live in `DEVICE_CONFIG` inside `config.py`; `validate_config()` checks required keys and value ranges at startup.
- CSV timestamps use ISO-8601 format (`YYYY-MM-DD HH:MM:SS`) from `TimeProvider.now_timestamp()`.

## Integration points & dependencies
- MicroPython-only modules: `machine`, `dht`, `uasyncio`; device drivers in `lib/` (`ds3231.py`, `sdcard.py`).
- Host shims for Windows/CPython live in `host_shims/` (`dht.py`, `machine.py`, `micropython.py`, `os.py`, `uasyncio.py`); auto-loaded when `sys.implementation.name != 'micropython'`.
- Test mocking for MicroPython is wired in `tests/conftest.py`.
- Configuration lives in `config.py` (`DEVICE_CONFIG`), including GPIO pins, schedules, thresholds, and file paths.
- Testing: `pytest` + `pytest-asyncio`; coverage threshold 88 %; config in `pyproject.toml`.
