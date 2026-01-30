# Pi Greenhouse Refactoring Documentation

## Overview

The Pi Greenhouse codebase has been refactored from a monolithic 758-line `main.py` into a modular architecture using **dependency injection**, **composition patterns**, and **separation of concerns**.

## Key Improvements

### 1. Modular Architecture

- **Before**: All classes and functions in single `main.py` file

- **After**: Split into focused modules in `lib/`:
  - `time_provider.py`: RTC abstraction
  - `buffer_manager.py`: Centralized storage with SD fallback
  - `event_logger.py`: System event logging
  - `dht_logger.py`: Sensor data logging
  - `relay.py`: Hardware relay control (composition pattern)
  - `led_button.py`: LED and button handling
  - `hardware_factory.py`: Device initialization
  - `sd_integration.py`: SD card utilities

### 2. Dependency Injection

- **Before**: Global state (`rtc`, `logger`, `sd_mounted` hardcoded)

- **After**: All dependencies explicitly passed to constructors
  - Example: `EventLogger(time_provider, buffer_manager, ...)`
  - Enables testing with mocks
  - Easier to understand component relationships

### 3. Centralized Configuration

- **Before**: Pins and parameters hardcoded in functions

- **After**: `config.py` with:
  - All GPIO pin assignments
  - Logging intervals
  - Temperature thresholds
  - Relay timing parameters
  - Easy-to-modify parameters without touching code

### 4. Graceful Degradation

- **Before**: Crashes if SD card unavailable at startup

- **After**:
  - `BufferManager` handles SD disconnection transparently
  - System runs with fallback file if primary unavailable
  - Automatic migration of fallback entries when SD reconnects

### 5. Composition Over Inheritance

- **Before**: Functions with repeated relay logic

- **After**:
  - `RelayController`: Base class for any GPIO relay
  - `FanController`: Composes RelayController + adds dual-mode control
  - `GrowlightController`: Composes RelayController + adds scheduling
  - Easy to add new relay-based devices

### 6. Async-Safe Patterns

- **Before**: Blocking operations could stall event loop

- **After**:
  - `LEDButtonHandler.blink_pattern_async()`: Non-blocking LED blinking
  - `ServiceReminder.monitor()`: Async task with event-based reset
  - All long-running ops use `await asyncio.sleep()`

### 7. Testability

- **Before**: No tests (hardware tightly coupled)

- **After**:
  - `tests/` directory with pytest fixtures
  - Mocks for `machine.Pin`, `dht.DHT22`, `machine.I2C`
  - Core modules tested in isolation
  - Run tests on host Python (not device)

## File Structure

```.
Git-codebase/
├── config.py                 # Central configuration (NEW)
├── main.py                   # Clean orchestrator (~130 lines, was 758)
├── main_original.py          # Backup of original
├── lib/
│   ├── time_provider.py      # RTC abstraction (NEW)
│   ├── buffer_manager.py     # SD + fallback resilience (NEW)
│   ├── hardware_factory.py   # Device initialization (NEW)
│   ├── event_logger.py       # Refactored from main.py with DI
│   ├── dht_logger.py         # Refactored from main.py with DI
│   ├── relay.py              # NEW: Composition pattern (FanController, GrowlightController)
│   ├── led_button.py         # NEW: LED/button + ServiceReminder
│   ├── sd_integration.py     # NEW: SD utilities
│   ├── ds3231.py            # Unchanged
│   └── sdcard.py            # Unchanged
├── tests/                    # NEW: Test suite
│   ├── conftest.py          # Pytest configuration and global fixtures
│   ├── test_core_modules.py # Unit and integration tests
│   └── README.md            # Testing guide
└── REFACTORING.md           # This file
```

## Migration Guide

### For Device Users

1. **Update pins** in `config.py` if your hardware differs
2. **Tune parameters** (intervals, temperatures) in `config.py`
3. **Run** `main.py` as before via Thonny
4. **No changes** to device operation or file formats

### For Developers

#### Before: Direct Global Access

```python
# main.py (old)
rtc = ds3231.RTC(...)  # Global
logger = EventLogger()  # Global, uses global rtc

dht_logger = DHTLogger(pin=15)  # Uses global logger, global rtc
fan_control(dht_logger, pin_no=16)  # Uses global logger, global rtc
```

#### After: Dependency Injection

```python
# main.py (new)
hardware = HardwareFactory(DEVICE_CONFIG)
rtc = hardware.get_rtc()
time_provider = RTCTimeProvider(rtc)
buffer_manager = BufferManager(...)
logger = EventLogger(time_provider, buffer_manager)
dht_logger = DHTLogger(..., time_provider, buffer_manager, logger)
fan = FanController(..., time_provider, dht_logger, logger)
```

### Adding a New Sensor

**Before**: Would need to modify `main.py`, DHTLogger, add global state.

**After**:

1. Create `lib/my_sensor.py` with `MySensorLogger` class
2. Inject `time_provider`, `buffer_manager`, `logger` in constructor
3. Create async `log_loop()` method
4. In `main.py`, instantiate and spawn task:

   ```python
   my_sensor = MySensorLogger(..., time_provider, buffer_manager, logger)
   asyncio.create_task(my_sensor.log_loop())
   ```

### Adding a New Relay-Based Device

1. Create class in `lib/relay.py` that inherits from `RelayController`:

   ```python
   class MyControllerController(RelayController):
       async def start_control(self):
           # Your async control logic
   ```

2. In `main.py`, instantiate and spawn:

   ```python
   device = MyControllerController(..., pin, time_provider, logger)
   asyncio.create_task(device.start_control())
   ```

## Critical Issues Addressed

### 1. RTC Format Confusion

- **Issue**: Multiple RTC output formats used inconsistently
- **Fix**: `TimeProvider` abstraction normalizes all calls
- **Benefit**: Single source of truth for time queries

### 2. Circular Dependencies

- **Issue**: BufferManager and EventLogger tightly coupled
- **Fix**: Factory pattern coordinates initialization order
- **Benefit**: Clear init sequence, graceful failure

### 3. SD Card Brittleness

- **Issue**: System crashes if SD disconnects
- **Fix**: `BufferManager` handles fallback transparently
- **Benefit**: System continues running, data preserved

### 4. Thermostat State Explosion

- **Issue**: 3+ boolean state vars per fan, hard to debug
- **Fix**: `FanController` encapsulates state as object
- **Benefit**: Easier reasoning, metrics via `get_state()`

### 5. LED Blocking

- **Issue**: Blocking blink could stall event loop
- **Fix**: `LEDButtonHandler.blink_pattern_async()` non-blocking
- **Benefit**: Concurrent tasks don't interfere

### 6. Configuration Fragility

- **Issue**: Pins/intervals hardcoded in 5+ places
- **Fix**: `config.py` with validation
- **Benefit**: Single place to tune, catches typos at startup

## Backwards Compatibility

### Data Files

✅ CSV format unchanged (`Timestamp,Temperature,Humidity`)
✅ Log file format unchanged
✅ All existing data files readable

### Pinout

✅ Default pins in `config.py` match original
✅ Relay timing unchanged
⚠️ New features: Service Reminder uses GPIO 23, 24 (can be disabled in config)

### API

❌ Old `main.py` functions removed (but kept in `main_original.py` for reference)
✅ Hardware behavior identical (same relay timing, LED patterns, etc.)

## Testing Strategy

### Unit Tests

Run on host Python with mocks:

```bash
pytest tests/ -v
```

Tests cover:

- TimeProvider format conversions
- BufferManager SD/fallback logic
- EventLogger severity levels
- RelayController on/off
- ServiceReminder timer
- Config validation

### Device Testing

1. Flash `main.py` to Pico via Thonny
2. Monitor serial console for startup messages
3. Check `/sd/dht_log_YYYY-MM-DD.csv` for data
4. Verify relay timing with physical observation
5. Test button press resets Service reminder

### Continuous Integration

Add to CI pipeline:

```bash
pytest tests/ --cov=lib --cov=config
```

## Performance Characteristics

### Memory Usage

- **Before**: ~12 KB free (tight)
- **After**: ~11 KB free (similar, no significant regression)
- Modular structure allows future optimization

### CPU Usage

- **Before**: Event loop sleeps 1s between checks
- **After**: Event loop sleeps 1-60s between checks (same)
- No impact on responsiveness

### SD Access Patterns

- **Before**: Direct write, crash on failure
- **After**: Write → fallback file → migrate when SD available
- More resilient, same performance

## Future Enhancements

With modular architecture, easy to add:

1. **Temperature Logging**: New `TemperatureLogger` class, 30 lines
2. **Soil Moisture**: New `SoilMoistureLogger` class, inherit from base
3. **Remote Logging**: Inject HTTP client into loggers
4. **Web Dashboard**: Expose relay state via HTTP
5. **MQTT Integration**: New task that subscribes to commands
6. **Machine Learning**: Train models on historical CSV data
7. **Dual-Device Sync**: Sync data between multiple Picos

All without modifying core modules!

## Troubleshooting

### Config Validation Error

```log
[STARTUP ERROR] Config validation failed: Missing config key: fan_1.interval_s
```

→ Check `config.py` for typos in section/key names

### RTC Failed

```log
[STARTUP ERROR] Critical hardware initialization failed (RTC)
```

→ Check I2C wiring (GPIO 0 SDA, GPIO 1 SCL)
→ Run `rtc_set_time.py` first

### SD Mount Failed

```log
[HardwareFactory] ERROR: SD init failed: ...
```

→ System continues with fallback buffering (check `/local/fallback.csv` later)
→ Check SPI wiring (GPIO 10-13)

### Buffer Overflow

```log
[DHTLogger] WARNING: Buffer overflow: dropped oldest entry ...
```

→ SD was unavailable too long
→ Increase `max_buffer_size` in `config.py` if you have spare memory

## References

- Original `main.py`: See `main_original.py`
- Configuration: See `config.py` and `config.validate_config()`
- Testing: See `tests/README.md`
- Hardware pins: See `config.DEVICE_CONFIG['pins']`
