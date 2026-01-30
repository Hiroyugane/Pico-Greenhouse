
# Pi Greenhouse: Raspberry Pi Pico Environmental Monitoring System

## Overview

**Pi Greenhouse** is a MicroPython-based automated greenhouse control system running on Raspberry Pi Pico. It monitors temperature/humidity via DHT22 sensors, logs timestamped data to SD card, and automatically controls a fan relay and grow lights based on schedules.

## Key Features

- **Real-time Environmental Monitoring**: DHT22 sensor reads temperature and humidity every 30 seconds
- **Persistent Data Logging**: All readings stored as CSV on SD card with RTC timestamps
- **Automated Fan Control**: Relay-based fan cycling (configurable on/off timing)
- **Scheduled Grow Lights**: Time-based light control with dawn/sunset automation
- **System Event Logging**: Comprehensive logging to both console and SD card
- **Hardware Status Feedback**: LED pulse patterns indicate operational state

## Hardware Requirements

| Component | GPIO Pin | Purpose |
| --- | --- | --- |
| DHT22 Sensor | GPIO 15 | Temperature/humidity measurement |
| DS3231 RTC | GPIO 0/1 (I2C) | Real-time clock for timestamps |
| SD Card Module | GPIO 10-13 (SPI) | Data persistence |
| Relay Module (Fan) | GPIO 16 | Fan control (HIGH=off, LOW=on) |
| Relay Module (Light) | GPIO 17 | Grow light control |
| Status LED | GPIO 25 | Operation feedback |

## Quick Start

### 1. Initial Setup (First Run Only)

```bash
# Set RTC module time from Pi Pico's system clock
# Uses Zeller's Congruence for weekday calculation
python rtc_set_time.py  # Run in Thonny
```

### 2. Normal Operation

```bash
# Start all monitoring and control tasks
python main.py  # Run in Thonny
```

### 2b. Run on Windows (Host Simulation)

You can run the system on a Windows PC without GPIO hardware. The project includes
host shims that print GPIO actions to the console and write logs to local folders.

```bash
# Run on Windows (standard Python 3)
python main.py
```

Host paths created in the repo:

- `./sd/` — simulated SD mount (CSV + logs)
- `./local/` — fallback buffer file

Note: The host shims live in `host_shims/` and are only loaded on Windows/CPython.
They are not used on the Pico.

### 3. Verify Data

Unplug device and check SD card:

- `/sd/dht_log.csv` – Temperature/humidity readings
- `/sd/system.log` – Event log with timestamps

## Configuration Parameters

### DHTLogger (Temperature Logging)

```python
DHTLogger(pin=15, interval=30, filename='/sd/dht_log.csv')
# interval: seconds between readings (default: 30s)
```

### Fan Control

```python
fan_control(pin_no=16, on_time=20, period=1800)
# on_time: fan runs for 20 seconds
# period: 30-minute cycle (1800 seconds)
```

### Grow Light Control

```python
growlight_control(pin_no=17, dawn_time=(6, 0), sunset_time=(22, 0))
# Light ON: 6:00 AM → 10:00 PM
```

## File Structure

- `main.py` – Core system with `DHTLogger`, `EventLogger`, async task runners
- `rtc_set_time.py` – One-time RTC initialization script
- `lib/ds3231.py` – RTC driver (supports 8 time format modes)
- `lib/sdcard.py` – SPI-based SD card filesystem driver

## CSV Data Format

```cs
Timestamp,Temperature,Humidity
08.06.2024 15:30:07,22.5,65.3
```

Note: Timestamp is raw RTC tuple; convert for human-readable format

## LED Status Codes

- **1 pulse (0.1s)** – Reading started
- **2 pulses (0.1s)** – Sensor read successful
- **3 pulses (0.15s)** – Sensor read failed
- **3 rapid pulses (0.5s)** – Unexpected error

## Development Notes

- **Language**: MicroPython (not standard Python 3)
- **IDE**: Thonny (required for flashing to Pico)
- **Architecture**: Concurrent async tasks via `uasyncio`
- **Version**: InDev1.0

## Troubleshooting

| Issue | Solution |
| --- | --- |
| No timestamp data | Run `rtc_set_time.py` first to sync RTC |
| SD card not mounting | Verify GPIO 10-13 connections, check baudrate |
| Sensor read failures | Check DHT22 wiring on GPIO 15, allow retries |
| Relay not switching | Confirm GPIO levels (HIGH=off, LOW=on) |
