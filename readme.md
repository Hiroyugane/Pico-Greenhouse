
# Pi Greenhouse: Raspberry Pi Pico Environmental Monitoring System

## Overview

**Pi Greenhouse** is a MicroPython-based automated greenhouse control system running on Raspberry Pi Pico. It monitors temperature and humidity via a DHT22 sensor, logs timestamped data to SD card with automatic fallback storage, and controls two fan relays (schedule + thermostat) and a grow light relay (dawn/sunset scheduling). All components use dependency injection and run as concurrent `uasyncio` tasks.

## Key Features

- **Real-time Environmental Monitoring** — DHT22 sensor reads temperature and humidity every 30 seconds (configurable)
- **Date-based CSV Logging** — Readings stored as `/sd/dht_log_YYYY-MM-DD.csv` with automatic daily rollover
- **Tiered Storage** — `BufferManager` writes to SD card, falls back to `/local/fallback.csv`, and buffers in RAM; migrates fallback data when SD becomes available
- **Dual Fan Control** — Two independent `FanController` relays with time-based cycling *and* thermostat override (temperature threshold + hysteresis)
- **Scheduled Grow Lights** — `GrowlightController` with configurable dawn/sunset times and optional auto-calculation from sunrise/sunset data
- **System Event Logging** — `EventLogger` with severity levels (`info`/`warning`/`error`), console + SD output, and log rotation at 50 KB
- **Service Reminder** — LED-based maintenance reminder with configurable interval and button reset
- **Multi-function Button** — Short press cycles display menu; long press (≥ 3 s) triggers context action (e.g. reset reminder)
- **5 Status LEDs** — Dedicated indicators for DHT feedback, service reminder, SD status, fan status, and errors
- **SD Hot-swap Recovery** — Main loop detects SD removal, buffers writes, and re-mounts automatically on re-insertion
- **Host Simulation** — Runs on Windows/CPython via `host_shims/` for development and testing without hardware

## Architecture

The system follows a **dependency-injection, factory-based** design:

1. `config.py` — Single `DEVICE_CONFIG` dict with all pins, intervals, thresholds, and file paths. `validate_config()` runs at startup.
2. `HardwareFactory` — Ordered hardware init: RTC (critical) → SPI/SD mount → GPIO pins. Created once, then injected.
3. `RTCTimeProvider` — Wraps the DS3231 RTC; all modules receive timestamps through this provider (no direct RTC calls).
4. `BufferManager` — Centralized write layer: SD → fallback CSV → in-memory buffer. Handles migration and flush.
5. `EventLogger` — System log with severity levels, buffered flush through `BufferManager`, and size-based rotation.
6. `DHTLogger` — Sensor reads with retry logic, date-based CSV rollover, LED blink feedback, and cached `last_temperature` for fan thermostat.
7. `FanController` / `GrowlightController` — Composition over `RelayController` base; relay GPIO is inverted (HIGH = off, LOW = on).
8. `LEDButtonHandler` + `ServiceReminder` — Debounced button interrupts with short/long press discrimination and persistent timestamp storage.

All long-running logic runs as `uasyncio` tasks with `await asyncio.sleep()` (no blocking loops).

## Hardware Requirements

| Component | GPIO Pin | Purpose |
| --- | --- | --- |
| DHT22 Sensor | GP15 | Temperature / humidity measurement |
| DS3231 RTC | GP0/GP1 (I2C0) | Real-time clock for timestamps |
| SD Card Module | GP10–GP13 (SPI1) | Data persistence |
| Relay — Fan 1 | GP16 | Primary fan (HIGH=off, LOW=on) |
| Relay — Grow Light | GP17 | Grow light (HIGH=off, LOW=on) |
| Relay — Fan 2 | GP18 | Secondary fan (HIGH=off, LOW=on) |
| Status LED (DHT) | GP4 | DHT read feedback |
| Reminder LED | GP5 | Service reminder blink |
| SD LED | GP6 | SD card status |
| Fan LED | GP7 | Fan status |
| Error LED | GP8 | System / error indicator |
| Menu Button | GP9 | Short = cycle menu, long ≥ 3 s = action |
| Reserved Button | GP14 | Future use |
| On-board LED | GP25 | Heartbeat |
| CO2 Sensor (UART) | GP2/GP3 (TX/RX) | SenseAir S8 (future, pins reserved) |

> **Note:** I2C1 bus (GP2–GP3) is shared between the RTC and the planned OLED display (SSD1306 at `0x3C`; RTC at `0x68`).

## Quick Start

### 1. Initial Setup (First Run Only)

```bash
# Set RTC module time from Pi Pico's system clock
# Uses Zeller's Congruence for weekday calculation
python rtc_set_time.py  # Run in Thonny on-device
```

### 2. Normal Operation

```bash
# Start all monitoring and control tasks
python main.py  # Run in Thonny on-device
```

### 3. Run on Windows (Host Simulation)

The project includes host shims (`host_shims/`) that simulate GPIO, SPI, I2C, DHT, and filesystem calls so you can run the full system on a standard Python 3 install.

```bash
pip install -r requirements.txt   # one-time
python main.py                    # runs with console-logged GPIO actions
```

Host paths created in the repo:

- `./sd/` — simulated SD mount (CSV data + system log)
- `./local/` — fallback buffer file

The shims are auto-detected via `sys.implementation.name` and are never loaded on the Pico.

### 4. Run Tests

```bash
pip install -r requirements.txt   # includes pytest + pytest-asyncio
pytest tests/                     # run full test suite
```

See [tests/README.md](tests/README.md) for details on the test structure and MicroPython mocking.

### 5. Verify Data

On the Pico, unplug the device and check the SD card:

- `/sd/dht_log_YYYY-MM-DD.csv` — Temperature / humidity readings (one file per day)
- `/sd/system.log` — Event log with timestamps

## Configuration

All tunable parameters live in `DEVICE_CONFIG` inside [config.py](config.py). The `validate_config()` function checks for required keys and value ranges at startup.

### DHTLogger

```python
DHTLogger(
    pin=15,                   # DHT22 data pin
    time_provider=...,        # RTCTimeProvider instance
    buffer_manager=...,       # BufferManager instance
    logger=...,               # EventLogger instance
    interval=30,              # seconds between readings (config: dht_logger.interval_s)
    filename='dht_log',       # base name → dht_log_YYYY-MM-DD.csv
    max_retries=3,            # sensor read retries before giving up
    status_led_pin=4,         # LED for blink feedback
)
```

### Fan Control (× 2)

```python
FanController(
    pin=16,                   # relay GPIO (inverted: HIGH=off, LOW=on)
    time_provider=...,
    dht_logger=...,           # reads cached last_temperature
    logger=...,
    interval_s=600,           # cycle interval — Fan 1: 600 s, Fan 2: 500 s
    on_time_s=20,             # relay ON duration per cycle
    max_temp=23.8,            # thermostat threshold — Fan 1: 23.8 °C, Fan 2: 27.0 °C
    temp_hysteresis=0.5,      # °C band around threshold
    name='Fan_1',
)
```

When `last_temperature` exceeds `max_temp`, the fan stays on continuously until the temperature drops below `max_temp - temp_hysteresis`.

### Grow Light Control

```python
GrowlightController(
    pin=17,                   # relay GPIO
    time_provider=...,
    logger=...,
    dawn_hour=7,              # Light ON at 07:00
    dawn_minute=0,
    sunset_hour=19,           # Light OFF at 19:00
    sunset_minute=0,
    name='Growlight',
)
# Supports auto-calculation from sunrise/sunset data when dawn/sunset are None
```

### Service Reminder

```python
ServiceReminder(
    time_provider=...,
    led_handler=...,          # LEDButtonHandler on GP5 (LED) + GP9 (button)
    days_interval=7,          # remind every 7 days
    blink_pattern_ms=[2000, 2000, 2000, 2000],
)
# Long-press the menu button (GP9 ≥ 3 s) to reset the reminder
```

## File Structure

```.
Git-codebase/
├── config.py                    # Central DEVICE_CONFIG + validate_config()
├── main.py                      # Orchestrator — DI-based init, spawns async tasks
├── rtc_set_time.py              # One-time RTC sync script (run in Thonny)
├── sd_test.py                   # SD card health-check state machine
├── requirements.txt             # Python / host dependencies
├── pyproject.toml               # pytest + coverage configuration
├── host_shims/                  # Windows / CPython compatibility shims
│   ├── dht.py                   #   DHT22 simulation (random readings)
│   ├── machine.py               #   Pin, SPI, I2C with console logging
│   ├── micropython.py           #   const() stub
│   ├── os.py                    #   mount / umount / ilistdir / VFS stubs
│   └── uasyncio.py              #   Maps to asyncio
├── lib/                         # Core library modules
│   ├── buffer_manager.py        #   Tiered storage: SD → fallback → RAM
│   ├── dht_logger.py            #   DHT22 logger with DI + date rollover
│   ├── ds3231.py                #   Primary RTC driver (8 time format modes)
│   ├── ds2321_gen.py            #   Alternative DS3231 driver (Peter Hinch)
│   ├── event_logger.py          #   System logger with severity + rotation
│   ├── hardware_factory.py      #   Factory for ordered HW init
│   ├── led_button.py            #   LED, LEDButtonHandler, ServiceReminder
│   ├── relay.py                 #   RelayController, FanController, GrowlightController
│   ├── sd_integration.py        #   mount_sd(), is_mounted() helpers
│   ├── sdcard.py                #   SPI-based SD card filesystem driver
│   ├── sunrise_sunset_2026.csv  #   Pre-computed sunrise / sunset (Cologne)
│   └── time_provider.py         #   TimeProvider, RTCTimeProvider, sunrise_sunset()
├── tests/                       # Unit tests (pytest + pytest-asyncio)
│   ├── conftest.py              #   MicroPython mocking setup
│   ├── README.md                #   Testing guide
│   ├── test_buffer_manager.py
│   ├── test_config.py
│   ├── test_dht_logger.py
│   ├── test_event_logger.py
│   ├── test_hardware_factory.py
│   ├── test_led_button.py
│   ├── test_main.py
│   ├── test_relay.py
│   ├── test_rtc_set_time.py
│   ├── test_sd_integration.py
│   ├── test_sd_test.py
│   └── test_time_provider.py
└── typings/
    └── os.pyi                   # Type stubs for MicroPython os
```

## CSV Data Format

```csv
Timestamp,Temperature,Humidity
2026-01-29 14:35:42,22.5,65.3
2026-01-29 14:36:12,22.6,65.1
```

Files are named `dht_log_YYYY-MM-DD.csv` and roll over at midnight.

## LED Status Codes

### DHT Read Feedback (GP4)

| Pattern | Meaning |
| --- | --- |
| 1 pulse (100 ms) | Reading started |
| 2 pulses (100 ms each) | Sensor read successful |
| 3 pulses (150 ms each) | Sensor read failed |
| 3 pulses (500 ms each) | Unexpected error |

### Service Reminder (GP5)

Blinks with the configured pattern (default: `[2000, 2000, 2000, 2000]` ms) when the maintenance interval has elapsed. Long-press the menu button (GP9 ≥ 3 s) to reset.

## Development Notes

- **Language**: MicroPython on-device; standard Python 3 for host simulation and tests
- **IDE**: Thonny (for flashing to Pico) or any editor with host shims
- **Architecture**: Dependency injection + factory pattern; concurrent `uasyncio` tasks
- **Testing**: `pytest` + `pytest-asyncio`; coverage threshold 88 %
- **Version**: InDev2.0 (Modular Architecture with Dependency Injection)

## Troubleshooting

| Issue | Solution |
| --- | --- |
| No timestamp data | Run `rtc_set_time.py` first to sync the DS3231 RTC |
| SD card not mounting | Verify GP10–GP13 wiring; check SPI baudrate in config |
| Sensor read failures | Check DHT22 wiring on GP15; `max_retries` defaults to 3 |
| Relay not switching | Confirm inverted GPIO logic (HIGH = off, LOW = on) |
| Data missing after SD removal | Check `/local/fallback.csv`; `BufferManager` migrates entries when SD returns |
| System log growing large | `EventLogger` auto-rotates at 50 KB; old logs renamed with timestamp |
| Service reminder won't clear | Long-press menu button (GP9 ≥ 3 s) to reset |

## Planned Enhancements

- **Sensor Upgrades**
  - Replace DHT22 with SHT31-D for improved accuracy
  - CO2-based exhaust fan automation (SenseAir S8 UART pins reserved)

- **User Interface**
  - OLED display driver (SSD1306) on shared I2C1 bus with real-time info screen
    - Temp / Humidity / CO₂ / Fan Status / SD Status / Uptime / Time & Date / Errors
  - Button-driven menu cycling (short press on GP9)

- **Control System Improvements**
  - PWM-based fan speed control (variable instead of on/off)
  - Variable MarsHydro grow light intensity control
  - Adaptive environmental adjustments via mathematical algorithms

- **Hardware & Integration**
  - Custom enclosure design with assembly instructions
  - Optional: upgrade to self-charging RTC module for improved reliability

- **Preset Configurations**
  - Growing scenario templates: Vegetables, Household Plants, Flowers, Mycology
