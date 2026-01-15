# Pi Greenhouse: AI Coding Agent Instructions

## Project Overview
**Pi Greenhouse** is a Raspberry Pi Pico-based environmental monitoring and control system for greenhouse automation. It combines temperature/humidity logging via DHT22 sensors with automated fan control via relay modules, storing timestamped data to an SD card.

## Architecture & Hardware Integration

### Core Hardware Components
- **Raspberry Pi Pico**: Microcontroller running MicroPython
- **DHT22 Sensor**: Temperature/humidity measurement on GPIO 15
- **DS3231 RTC Module**: Real-time clock for accurate timestamps via I2C (SDA=GPIO0, SCL=GPIO1)
- **SD Card Module**: SPI-based data storage (SCK=GPIO10, MOSI=GPIO11, MISO=GPIO12, CS=GPIO13)
- **Relay Module**: Fan control switch on GPIO 16 (HIGH=relay off, LOW=relay on)
- **Status LED**: GPIO 25 for operation feedback

### GPIO Pin Mapping (Critical Reference)
```
GPIO0/1: RTC (I2C)
GPIO10-13: SD Card (SPI)
GPIO15: DHT22 data
GPIO16: Relay (fan control)
GPIO25: Status LED
```

## Development Workflows

### Setup & Execution Order
1. **First Run Only**: Execute `rtc_set_time.py` to sync RTC with Pi Pico's system time (uses Zeller's Congruence for weekday calculation, converts to BCD format)
2. **Normal Operation**: Run `main.py` which starts concurrent tasks for sensor logging and fan control
3. **Verification**: Check SD card (`/sd/dht_log.csv`) for timestamped readings after unplugging device

### Development Environment
- **IDE**: Thonny (explicitly required for flashing and execution)
- **MicroPython**: Device runtime (not standard Python 3)
- **Testing Strategy**: Physical verification on hardware (check CSV output after runs)

## Code Patterns & Conventions

### Async/Concurrent Architecture
Uses `uasyncio` for concurrent task execution. All long-running operations (logging, fan control) are coroutines spawned in `main()`:
```python
asyncio.create_task(logger.log_data())
asyncio.create_task(fan_control(pin_no=16))
```
**Pattern**: Never block the event loop; use `await asyncio.sleep()` for delays.

### DHTLogger Class Design
- **CSV Header**: `'Timestamp,Temperature,Humidity\n'` (auto-created if file missing)
- **File Path Convention**: Stores data on SD card mount point (`'/sd/dht_log.csv'`)
- **Error Handling**: Wraps sensor reads in try/except for `OSError` (DHT read failures)
- **Status Indication**: LED pulse (on 1s, off for interval) indicates active logging

### Relay Control Pattern
- **Timing Model**: `on_time=20s` (fan runs), `period=1800s` (30min total cycle)
- **Logic**: GPIO is inverted (HIGH=off, LOW=on) — standard relay module behavior
- **Blocking Avoidance**: Uses async sleep for cycle timing

## Integration Points & Data Flow

```
RTC (I2C) → Timestamp String → DHTLogger.log_data()
DHT22 → Raw Temp/Humidity → CSV write to SD card
Fan Thermostat Logic → Relay GPIO → Physical fan
```

**Critical Dependencies**:
- `ds3231` module: Custom library for RTC communication (time format varies: `'DIN-1355-1+time'` vs `'timestamp'`)
- `sdcard` module: SD card driver for SPI interface
- `dht`, `machine`, `uasyncio`: MicroPython core libraries

## RTC Time Format Modes

The `ds3231.ReadTime()` method supports multiple output modes:
- **String Formats**: `'DIN-1355-1'` (DD.MM.YYYY), `'DIN-1355-1+time'` (DD.MM.YYYY HH:MM:SS), `'ISO-8601'`, `'time'`, `'weekday'`, `'timestamp'`
- **Tuple Formats**: `'localtime'`, `'datetime'`, `'weekday'`
- **Numeric Mode** (default/1): Returns raw tuple `(second, minute, hour, weekday, day, month, year)`
- **Current Usage**: `main.py` uses `ReadTime(1)` for numeric format; conversion may be needed for CSV output

## Project-Specific Notes

- **Language**: MicroPython (not standard Python — no f-string formatting in some contexts, limited memory)
- **Versioning**: Currently `InDev1.0` (development state)
- **Author**: Dennis Hiro (2024-06-08)
- **Data Persistence**: All logging persists to physical SD card; no cloud sync
- **Multilingual Comments**: Code contains German comments (relay states, debug messages) — preserve when editing
- **Known Issues**: Check `fan_control()` loop completion; ensure relay timing logic is fully implemented

## Common Tasks for Agents

1. **Adding a new sensor**: Create async method in new task, mount appropriate I2C/SPI interface
2. **Tuning fan timing**: Modify `on_time` and `period` parameters in `fan_control()` call (default: 20s on, 1800s total cycle)
3. **Changing logging interval**: Update `DHTLogger` instantiation `interval` parameter (seconds, default 30s in main.py)
4. **Debugging sensor failures**: Check GPIO wiring against pin map, verify I2C/SPI initialization
5. **SD card issues**: Ensure `/sd` mount succeeds; check `os.mount()` before file operations
6. **Timestamp formatting**: When modifying CSV logging, consider switching from `ReadTime(1)` to `ReadTime('timestamp')` for ISO-8601 format

## Key File Reference

- [main.py](main.py): Entry point with `DHTLogger` class and async tasks (logger, fan control)
- [rtc_set_time.py](rtc_set_time.py): One-time setup script using Zeller's Congruence & BCD conversion
- [lib/ds3231.py](lib/ds3231.py): RTC driver with multiple time format modes (8 supported formats)
- [lib/sdcard.py](lib/sdcard.py): SPI-based SD card filesystem driver (310 lines, third-party library)
