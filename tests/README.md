# Pi Greenhouse Testing Guide

## Overview

Unit and integration tests for the Pi Greenhouse system, running on **host Python** (not on the Pico device) using `MagicMock` for MicroPython-specific modules (`machine`, `dht`, `uasyncio`).

## Quick Start

```bash
pip install -r requirements.txt
pytest tests/ -v
pytest tests/ --cov=lib --cov=config --cov-report=term-missing
```

## Test Files

| File | Module Under Test | Tests |
| --- | --- | --- |
| `test_time_provider.py` | `lib/time_provider.py` | Base & RTC TimeProvider, sunrise/sunset interpolation, error fallbacks |
| `test_buffer_manager.py` | `lib/buffer_manager.py` | Primary/fallback/in-memory writes, flush, migration, rename, metrics |
| `test_event_logger.py` | `lib/event_logger.py` | INFO/WARN/ERR logging, flush thresholds, log rotation, timestamps |
| `test_relay.py` | `lib/relay.py` | RelayController toggle/state, FanController thermostat+schedule, GrowlightController dawn/sunset |
| `test_dht_logger.py` | `lib/dht_logger.py` | Sensor read/retry/range, date rollover, CSV creation, async log loop |
| `test_led_button.py` | `lib/led_button.py` | LED on/off/blink, button debounce, ServiceReminder persistence+monitor |
| `test_hardware_factory.py` | `lib/hardware_factory.py` | RTC/SPI/SD init, pin setup, refresh, error accumulation |
| `test_sd_integration.py` | `lib/sd_integration.py` | mount_sd host/device, is_mounted checks |
| `test_config.py` | `config.py` | Config structure, validate_config edge cases |
| `test_main.py` | `main.py` | Startup sequence, task spawning, health-check loop, hot-swap recovery |

## Configuration

- **`pyproject.toml`** at project root configures pytest (`asyncio_mode = "auto"`) and coverage (`fail_under = 85`).
- **`conftest.py`** patches `sys.modules` for `machine`, `dht`, `micropython`, `uasyncio` using structured `MagicMock` objects with realistic Pin constants (`OUT`, `IN`, `PULL_UP`, `IRQ_FALLING`).
- **Fixtures** provide pre-wired instances: `time_provider`, `buffer_manager(tmp_path)`, `event_logger`, `fan_controller`, `growlight_controller`, `led_handler`, etc.
- **Async tests** use `pytest-asyncio` auto mode — just write `async def test_*()` methods.

## Architecture

```.
tests/
├── conftest.py              # MagicMock module patches + shared fixtures
├── test_time_provider.py    # TimeProvider, RTCTimeProvider, sunrise_sunset
├── test_buffer_manager.py   # BufferManager with tmp_path filesystem isolation
├── test_event_logger.py     # EventLogger flush/rotation/error paths
├── test_relay.py            # RelayController, FanController, GrowlightController
├── test_dht_logger.py       # DHTLogger sensor, rollover, log_loop
├── test_led_button.py       # LED, LEDButtonHandler, ServiceReminder
├── test_hardware_factory.py # HardwareFactory setup/init/refresh
├── test_sd_integration.py   # SD mount/is_mounted
├── test_config.py           # Config validation
├── test_main.py             # Main orchestration
└── README.md                # This file
```

## Coverage

Run with coverage report:

```bash
pytest tests/ --cov=lib --cov=config --cov-report=term-missing
```

Generate HTML report:

```bash
pytest tests/ --cov=lib --cov=config --cov-report=html
open htmlcov/index.html
```

1. **Fallback Testing**: Remove SD card during operation and verify `/local/fallback.csv` captures data

## Expected Initialization Sequence (from main.py)

1. Validate configuration (config.py)
2. Initialize hardware via HardwareFactory (RTC, SPI, SD, GPIO)
3. Create TimeProvider (wraps RTC for consistent timestamps)
4. Create BufferManager (SD + fallback resilience)
5. Create EventLogger (system event tracking with persistence)
6. Create DHTLogger (temperature/humidity sensor)
7. Create relay controllers: FanController × 2, GrowlightController
8. Create LED/button handler and CleaningReminder task
9. Spawn all async tasks (fan cycles, growlight scheduler, sensor logging, reminder monitoring)
10. Enter main event loop with periodic health checks

**Note**: Recommended improvement is to move EventLogger creation before step 2 (hardware init) so hardware failures can be logged persistently. See REFACTORING.md for details.

## Continuous Integration (CI)

To run tests in CI/CD pipeline:

```bash
pytest tests/ --cov=lib --cov=config --cov-report=xml -v
```

CI should run on every commit to catch regressions.

## Debugging Tests

### Print Debug Output

```bash
pytest tests/ -v -s  # -s shows print() statements
```

### Run Single Test with Debugger

```bash
pytest tests/test_core_modules.py::TestTimeProvider::test_time_provider_now_timestamp -v -s --pdb
```

### Check Mock Calls

```python
def test_mock_was_called(self, mock_rtc):
    """Verify mock was called."""
    from lib.time_provider import RTCTimeProvider
    provider = RTCTimeProvider(mock_rtc)
    provider.now_timestamp()
    
    mock_rtc.ReadTime.assert_called()  # Verify ReadTime was called
    print(mock_rtc.ReadTime.call_count)  # How many times?
    print(mock_rtc.ReadTime.call_args)   # With what arguments?
```

## Known Limitations

1. **Async Tests**: CleaningReminder, DHTLogger, and FanController have async methods not fully tested (would need pytest-asyncio fixtures)
2. **File I/O**: File operations are partially mocked; real SD behavior may differ
3. **MicroPython Specifics**: Some MicroPython-only features (e.g., memory constraints, interrupt handlers) aren't tested
4. **GPIO Interrupts**: Button interrupt handlers are mocked; real debouncing untested
5. **Hardware Timing**: Relay timing and temperature thresholds use mock data, not real sensor values

## Future Improvements

- [ ] Add pytest-asyncio fixtures for async task testing (`log_loop()`, `start_cycle()`, `monitor()`)
- [ ] Create integration test fixtures that simulate real SD card behavior
- [ ] Add device-side tests (run on Pico via Thonny with serial capture)
- [ ] Add performance benchmarks (startup time, memory usage)
- [ ] Test memory usage under sustained load (24+ hour runs)
- [ ] Add end-to-end tests combining multiple components
- [ ] Stress test relay cycling with high-frequency switching
