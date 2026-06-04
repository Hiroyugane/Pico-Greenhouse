
# Pi Greenhouse: Raspberry Pi Pico Environmental Control System

## Overview

**Pi Greenhouse** is a MicroPython-based automated greenhouse/grow-tent controller running on a Raspberry Pi Pico. It senses temperature and humidity (SHT31-D), CO₂ (SenseAir S8-style UART sensor), and soil moisture (ADC); controls fans (schedule + thermostat + CO₂ override), a heater (day/night thermostat), and a grow light (dawn/sunset schedule with optional DAC dimming); logs everything to SD with tiered fallback storage; and drives an OLED menu, status LEDs, and a buzzer. All components are wired through dependency injection and run as concurrent `uasyncio` tasks under a hardware watchdog.

The **same source** runs two ways: on the Pico under MicroPython, and on Windows/CPython for development and testing via the shims in [host_shims/](host_shims/).

## Operating Modes

A single top-level `mode` switch in [config.py](config.py) picks which optional components are constructed at boot:

| Mode | Grow light | Soil logger |
| --- | --- | --- |
| `"plant"` | Dimmable — MCP4725 DAC over the relay master switch | Enabled (GP28 ADC) |
| `"mushroom"` (default) | Relay-only on/off | Not constructed |

Disabled components are skipped entirely — no task, no I/O — so being in the wrong mode only costs the missing feature, not idle RAM.

## Key Features

- **Temperature / Humidity** — SHT31-D on the shared I2C0 bus, CRC-validated reads with retry logic, cached `last_temperature` feeding the fan/heater thermostats
- **CO₂ Monitoring + Vent Override** — `CO2Logger` polls a SenseAir S8-style sensor over UART0; crossing `override_ppm_on` force-runs the exhaust fan until ppm drops below `override_ppm_off`
- **Soil Moisture** *(plant mode)* — `SoilLogger` reads GP28/ADC2, scales raw counts to a calibrated 0–100 %, and raises the warning LED below a threshold
- **Dual + Expandable Fan Roster** — role-keyed `fans` dict dispatched by mode: `thermostat_schedule` (time cycle + temp override), `always_on`, `heater_follower`. Two relay fans ship enabled; three PCA9685 PWM roles ship disabled for the next-rev PWM board
- **Heater Control** — `HeaterController` on an active-HIGH MOSFET (GP3) with separate day/night setpoints that track the grow-light schedule
- **Grow Light** — `GrowlightController` relay master switch with configurable dawn/sunset; optional MCP4725 DAC dimming in plant mode
- **Tiered Storage** — `BufferManager` writes SD → `/local/fallback.csv` → in-memory ring buffer, and migrates fallback rows back to SD when the card returns; async write batching via `WriteQueueManager`
- **Sensor-first SD layout** — `/sd/sensors/<type>/YYYY/<type>_YYYY-MM-DD.csv`, one folder per sensor type, daily rollover
- **System Event Logging** — `EventLogger` with severity levels, buffered flush, and size-based rotation to `/sd/logs/system.log`
- **OLED Display** — SSD1306 menu (temp/hum/CO₂/soil/fan/SD/uptime/stats), short-press cycles menus, long-press runs context actions including a guarded debug-actions sub-menu
- **Status LEDs + Buzzer** — activity / SD / warning / error / reminder LEDs with a power-on self-test (POST) walk; passive buzzer for startup, alert, error, and reminder patterns
- **Service Reminder** — LED-based maintenance reminder with configurable interval, persisted timestamp, and long-press reset
- **Watchdog** — hardware WDT fed by a dedicated async task; a stalled scheduler resets the Pico
- **SD-payload OTA Updater** — drop a SHA-256-verified payload tree under `/sd/ota/pending`; `updater.py` verifies, applies, archives, and resets on next boot
- **SD Hot-swap Recovery** — the health loop detects SD loss, buffers writes, and re-mounts automatically on re-insertion
- **Host Simulation** — runs on Windows/CPython via `host_shims/` with console-logged GPIO for development without hardware

## Architecture

The system follows a **dependency-injection, factory-based** design — [main.py](main.py) is the only place that wires components:

1. **`config.py`** — single `DEVICE_CONFIG` dict holding every pin, interval, threshold, and path. `validate_config()` runs first at boot and is the only check.
2. **Watchdog** — `WDT` is armed early (before other hardware) and fed both by an async task and at long synchronous boundaries via `feed_wdt()`.
3. **`HardwareFactory`** — ordered init: RTC (critical) → SPI/SD mount → GPIO. If `system.require_sd_startup` is set and the card won't mount, the boot path lights sd+error LEDs, holds a visible countdown, then resets.
4. **`run_pending_update()`** — runs *before* the logger so logging code itself can be replaced; ends in `machine.reset()` when an update applies.
5. **`RTCTimeProvider`** — wraps the DS3231; all modules receive timestamps through this provider (no direct RTC calls).
6. **`StatusManager`** — owns the activity/SD/warning/error/heartbeat LEDs and the POST walk; "solid = problem, blink = activity, dark = all good".
7. **`BufferManager` + `WriteQueueManager`** — the single chokepoint for all persistent writes (SD → fallback → RAM), with async drainage and fallback migration.
8. **`EventLogger`** — system log with severity levels, buffered flush through `BufferManager`, and size-based rotation.
9. **Sensor loggers** — `TempHumidityLogger`, `CO2Logger`, `SoilLogger`, each writing through the sensor-first SD path helper.
10. **Actuators** — `HeaterController`, the fan roster (`FanController` / `AlwaysOnFanController` / `HeaterFollowerFanController` over `RelayFanOutput` / `Pca9685FanOutput`), and `GrowlightController` (+ optional `MCP4725`).
11. **UI** — `LEDButtonHandler` + `ServiceReminder` + `OLEDDisplay` + `BuzzerController`.

All long-running logic runs as `uasyncio` tasks with `await asyncio.sleep()` (no blocking loops — a blocking task would trip the watchdog on real hardware).

> **Same code, two runtimes.** [main.py](main.py#L30-L35) detects `sys.implementation.name != "micropython"` and prepends [host_shims/](host_shims/) to `sys.path`, providing `machine`, `micropython`, `os`, `framebuf`, an `sht31` simulator, and a `uasyncio` that aliases standard `asyncio`. Anything new importing MicroPython-only APIs needs a matching shim.

## Hardware — Pico GPIO Map

Pin assignments mirror PCB schematic `SCH_Pico-Greenhouse-PCB_2026-05-14` and the `pins` section of [config.py](config.py). All relay GPIOs are **active-low** (HIGH = off, LOW = on); LEDs and the heater MOSFET are active-high.

| GPIO | Net | Purpose |
| --- | --- | --- |
| GP0 / GP1 | I2C0 (SDA/SCL) | **Shared bus**: SHT31-D `0x44`, DS3231 RTC `0x68`, SSD1306 OLED `0x3C`, MCP4725 DAC `0x60`, I2C breakouts. Pulled to 3V3 via R1/R2 |
| GP2 | GP2_CON | General-purpose breakout (future use) |
| GP3 | Heater MOSFET | IRLZ44N gate via R6 — active HIGH |
| GP4 | Activity LED | Brief blink on I/O actions |
| GP5 | SD LED | Solid = SD missing/failed |
| GP6 | Warning LED | Solid = degraded condition |
| GP7 | Error LED | Solid = fault needs attention |
| GP8 | Reminder LED | Blinks when service is due |
| GP9 | Menu button | Short = cycle menu, long ≥ 3 s = action |
| GP10–GP13 | SPI1 | SD card (SCK/MOSI/MISO/CS); MOSI has series damper R10, MISO is direct |
| GP14 | Buzzer | Passive buzzer (PWM), R3 pulldown |
| GP16 | UART0 TX | → CO₂ sensor (via R9) |
| GP17 | UART0 RX | ← CO₂ sensor (via R11) |
| GP18 | Relay — fan 1 (`exhaust`) | Active-low relay |
| GP19 | Relay — fan 2 (`growroom_walls`) | Active-low relay |
| GP20 | Relay — grow light | Active-low relay |
| GP21 / GP22 | Reserved relays | REL_CON pins 5–6 (future use) |
| GP25 | On-board LED | Heartbeat |
| GP26 / GP27 | Reserved relays | REL_CON pins 7–8 (future use) |
| GP28 | ADC2 | Soil-moisture probe (plant mode) |

> The PCB's `RES_BTN` is wired to the Pico's `3V3_EN` (hardware reset), not a GPIO. The OLED, RTC, SHT31, and DAC all share the single **I2C0** bus — there is no separate I2C1 in this design.

## Quick Start

### 1. First run only — seed the RTC

```bash
# Sets the DS3231 from the Pico's system clock (run in Thonny on-device)
python prototypes/rtc_set_time.py
```

### 2. Normal operation

```bash
# Validates config, inits hardware, spawns all async tasks (run in Thonny on-device)
python main.py
```

### 3. Run on Windows (host simulation)

The shims in [host_shims/](host_shims/) simulate GPIO, SPI, I2C, the SHT31 sensor, and filesystem calls so the full system runs on standard Python 3.

```bash
pip install -r requirements.txt   # one-time
python main.py                    # runs with console-logged GPIO actions
```

Host paths created in the repo: `./sd/` (simulated SD mount) and `./local/` (fallback buffer). Shims are auto-detected via `sys.implementation.name` and never loaded on the Pico.

### 4. Run tests

```bash
pip install -r requirements.txt                                   # pytest, pytest-asyncio, ruff, pre-commit
pytest tests/                                                     # full suite (asyncio_mode=auto)
pytest tests/test_relay.py                                        # single file
pytest tests/ --cov=lib --cov=config --cov-report=term-missing    # coverage; gate is fail_under=88
ruff check . --fix                                                # lint + autofix
```

See [tests/README.md](tests/README.md) for the MicroPython mocking approach. Tests never import `host_shims/`; [tests/conftest.py](tests/conftest.py) installs `MagicMock` stubs for `machine`/`micropython`/`uasyncio` before any `lib/` import.

### 5. Verify data on the SD card

- `/sd/sensors/th/YYYY/th_YYYY-MM-DD.csv` — temperature / humidity (one file per day)
- `/sd/sensors/co2/YYYY/co2_YYYY-MM-DD.csv` — CO₂ ppm
- `/sd/sensors/soil/YYYY/soil_YYYY-MM-DD.csv` — soil moisture (plant mode)
- `/sd/logs/system.log` — system event log

## Configuration

Every tunable parameter lives in `DEVICE_CONFIG` inside [config.py](config.py); `validate_config()` asserts required keys and value ranges at startup. New config keys must be added to the dict, the validator, **and** [tests/test_config.py](tests/test_config.py). `lib/` modules never import `DEVICE_CONFIG` — values flow in through constructors.

### Fan roster (role-keyed, mode-dispatched)

```python
"fans": {
    "exhaust": {            # enabled — relay on GP18
        "mode": "thermostat_schedule",  # time cycle + temperature override
        "output": "relay", "relay_pin_key": "relay_fan_1",
        "interval_s": 600, "on_time_s": 20,
        "max_temp": 23.8, "temp_hysteresis": 0.5, "poll_interval_s": 5,
    },
    "growroom_walls": {...},     # enabled — relay on GP19
    "growroom_center": {...},    # disabled — pca9685 ch0 (next-rev PWM board)
    "heater_distribution": {...},# disabled — heater_follower, pca9685 ch1
    "case": {...},               # disabled — always_on, pca9685 ch2
}
```

`thermostat_schedule` fans run on a time cycle and force on whenever `last_temperature` exceeds `max_temp`, releasing at `max_temp − temp_hysteresis`. The CO₂ logger attaches an `external_override` hook to the `co2_logger.override_fan` role.

### Heater

```python
"heater": {
    "day_min_temp": 22.0, "night_min_temp": 16.0,   # day window must be >= night
    "temp_hysteresis": 0.5,
    "day_offset_min": 0, "night_offset_min": 0,      # offsets from grow-light dawn/sunset
    "max_stale_reads": 3,                            # consecutive sensor failures tolerated
    "poll_interval_s": 30,
}
```

### Grow light

```python
"growlight": {
    "dawn_hour": 7, "dawn_minute": 0,                # ON at 07:00
    "sunset_hour": 19, "sunset_minute": 0,           # OFF at 19:00
    "poll_interval_s": 60,
    "dac_i2c_address": 0x60,                         # MCP4725 (plant mode only)
    "default_level_pct": 80, "max_level_pct": 91,    # ViparSpectra XS1500 safe ceiling
    "min_level_pct": 0, "ramp_duration_s": 300,
}
```

### CO₂ logger

```python
"co2_logger": {
    "interval_s": 30, "warmup_s": 30, "max_retries": 3,
    "override_ppm_on": 2500, "override_ppm_off": 2200,  # on must be > off
    "override_fan": "exhaust",                          # role in the fans dict
    "sensor_type": "co2",
}
```

### Service reminder

```python
"Service_reminder": {
    "days_interval": 7,
    "blink_pattern_ms": [200, 200, 200, 800],
    "blink_after_days": 3,                # days overdue before solid → blink
    "storage_path": "/service_reminder.txt",
    "monitor_interval_s": 3600,
}
# Long-press the menu button (GP9 ≥ 3 s) to reset.
```

Other sections worth knowing: `system` (watchdog, health-check intervals, SD retry, write-queue), `buffer_manager`, `event_logger`, `status_leds` (POST walk order, memory warn/error %), `display` (OLED + debug sub-menu), `buzzer`, `updater` / `updater_feedback` (SD-payload OTA), `pca9685` (disabled until the next-rev board).

## File Structure

```text
Git-codebase/
├── config.py                    # Central DEVICE_CONFIG + validate_config()
├── main.py                      # Orchestrator — DI-based init, spawns async tasks
├── requirements.txt             # Host / dev dependencies
├── pyproject.toml               # pytest + coverage + ruff configuration
├── host_shims/                  # Windows / CPython compatibility shims
│   ├── sht31.py                 #   SHT31 simulation (probe-calibrated readings)
│   ├── machine.py               #   Pin, SPI, I2C, UART, ADC, WDT with console logging
│   ├── micropython.py           #   const() stub
│   ├── framebuf.py              #   Framebuffer stub for the OLED driver
│   ├── os.py                    #   mount / umount / ilistdir / VFS stubs
│   ├── uasyncio.py              #   Maps to asyncio
│   └── _probe_data.py           #   Canned host sensor data
├── lib/                         # Core library modules
│   ├── boot_log.py              #   Tees boot diagnostics to /boot.log
│   ├── hardware_factory.py      #   Ordered HW init (RTC → SPI/SD → GPIO)
│   ├── time_provider.py         #   TimeProvider, RTCTimeProvider
│   ├── status_manager.py        #   LED ownership + POST walk
│   ├── buffer_manager.py        #   Tiered storage: SD → fallback → RAM
│   ├── write_queue_manager.py   #   Async SD write batching
│   ├── event_logger.py          #   System logger with severity + rotation
│   ├── sensor_paths.py          #   Canonical /sd/sensors path builder
│   ├── sht31.py                 #   SHT31-D I2C driver (CRC-validated)
│   ├── temp_humidity_logger.py  #   Temp/humidity logger with date rollover
│   ├── co2_logger.py            #   UART CO₂ logger + fan override flag
│   ├── soil_logger.py           #   ADC soil-moisture logger (plant mode)
│   ├── relay.py                 #   RelayController, FanController, GrowlightController
│   ├── fan_output.py            #   RelayFanOutput, Pca9685FanOutput
│   ├── fan_controllers.py       #   AlwaysOn + HeaterFollower fan policies
│   ├── heater.py                #   HeaterController (day/night thermostat)
│   ├── pca9685.py               #   16-ch PWM driver (next-rev fan board)
│   ├── mcp4725.py               #   DAC driver for grow-light dimming
│   ├── led_button.py            #   LED, LEDButtonHandler, ServiceReminder
│   ├── buzzer.py                #   Passive-buzzer pattern player
│   ├── oled_display.py          #   SSD1306 menu + debug actions sub-menu
│   ├── updater.py               #   SD-payload OTA verify/apply/reset
│   ├── updater_feedback.py      #   LED chase + buzzer ticks during update
│   ├── sd_integration.py        #   mount_sd(), is_mounted() helpers
│   ├── sdcard.py                #   SPI SD-card filesystem driver (vendored)
│   ├── ds3231.py                #   Primary RTC driver (vendored)
│   ├── ds2321_gen.py            #   Alternative DS3231 driver (vendored)
│   ├── ssd1306.py               #   OLED framebuffer driver (vendored)
│   └── picozero/                #   Vendored picozero
├── prototypes/                  # On-device bench scripts (not part of the app)
│   ├── rtc_set_time.py          #   One-time RTC sync
│   ├── sd_test.py               #   SD card health-check state machine
│   ├── i2c_scan.py              #   I2C bus address scan
│   ├── hw_probe.py              #   Hardware probe
│   ├── co2*.py                  #   CO₂ sensor smoke tests
│   ├── led_cycle_test.py        #   LED walk test
│   └── transfer_logs.py         #   Pull logs off the device
├── tools/                       # Host-side utilities
│   ├── build_update_payload.py  #   Build a signed OTA payload tree
│   └── relay_diag.py            #   Relay diagnostics
├── tests/                       # Unit tests (pytest + pytest-asyncio)
│   ├── conftest.py              #   MicroPython mocking setup
│   └── test_*.py                #   One file per lib/ module + config + main
├── docs/                        # Schematic, hardware notes, chat-log, hw-test-log
└── typings/os.pyi               # Type stubs for MicroPython os
```

## CSV Data Format

Sensor data lives under `/sd/sensors/<type>/YYYY/<type>_YYYY-MM-DD.csv`, rolling over at midnight. Temperature / humidity rows:

```csv
Timestamp,Temperature,Humidity
2026-01-29 14:35:42,22.5,65.3
2026-01-29 14:36:12,22.6,65.1
```

## LED Status

Design convention: **solid = problem, blink = activity, dark = all good.** At boot a POST walk lights each LED in `status_leds.walk_order` to verify the row.

| LED | GPIO | Meaning |
| --- | --- | --- |
| Activity | GP4 | Brief blink on sensor reads / I/O |
| SD | GP5 | Solid = SD card missing or failed |
| Warning | GP6 | Solid = degraded (fallback active, low soil, high RAM, RTC invalid) |
| Error | GP7 | Solid = fault needs attention |
| Reminder | GP8 | Blinks when service interval has elapsed (long-press GP9 to reset) |
| Heartbeat | GP25 | On-board LED toggles each health-check tick |

## Development Notes

- **Language**: MicroPython on-device; standard Python 3 for host simulation and tests
- **IDE**: Thonny (for flashing to the Pico) or any editor with the host shims
- **Architecture**: dependency injection + factory pattern; concurrent `uasyncio` tasks under a hardware watchdog
- **Testing**: `pytest` + `pytest-asyncio`, `asyncio_mode=auto`; coverage gate `fail_under=88`
- **Lint/format**: `ruff` (`line-length=120`, selecting `E,F,I`); vendored drivers, `host_shims/`, and `typings/` are excluded from lint and coverage
- **Version**: InDev2.0 (Modular Architecture with Dependency Injection)

## Troubleshooting

| Issue | Solution |
| --- | --- |
| No timestamp data | Run `prototypes/rtc_set_time.py` first to seed the DS3231 |
| Boot resets in a loop with sd+error LEDs lit | SD required but not mounting — check GP10–GP13 wiring / card seating, or set `system.require_sd_startup=False` |
| Sensor read failures | Check SHT31 on I2C0 (GP0/GP1, `0x44`); `max_retries` defaults to 3 |
| Relay not switching | Confirm inverted GPIO logic (HIGH = off, LOW = on) |
| Data missing after SD removal | Check `/local/fallback.csv`; `BufferManager` migrates entries when SD returns |
| CO₂ override never fires | Verify the sensor on UART0 (GP16/GP17) and that `override_fan` names an enabled fan role |
| OLED blank | Check it answers at `0x3C` on I2C0 (`prototypes/i2c_scan.py`); `display.enabled` must be True |
| System log growing large | `EventLogger` auto-rotates past `event_logger.max_size`; old logs renamed with a timestamp |
| Service reminder won't clear | Long-press the menu button (GP9 ≥ 3 s) |

## Planned Enhancements

- **PCA9685 PWM fan board** — flip the three disabled fan roles on for variable-speed control (driver + config already in place; awaiting the next-rev PCB)
- **MCP4725 grow-light dimming** in production — ramped dawn/sunset fades on the ViparSpectra XS1500
- **Soil sensor swap** — move from the analog GP28 probe to the Adafruit STEMMA #4026 (I²C, `0x36`) on the next PCB
- **Adaptive environmental control** — closed-loop adjustments from combined temp/humidity/CO₂/soil signals
- **Custom enclosure** with assembly instructions
- **Preset configurations** — grow templates for vegetables, household plants, flowers, and mycology
