# Prompt: Debug Device Logs

Use this prompt to have an AI analyze logs pulled from the Pi Greenhouse device.

---

## Context

The Pi Greenhouse generates two types of log files on the SD card:

1. **System log** (`/sd/system.log`) — Event log with severity levels:

   ```text
   [2026-03-01 14:23:45] [INFO] [MAIN] System startup
   [2026-03-01 14:23:46] [WARN] [DHTLogger] Sensor read attempt 1/3 failed: timeout
   [2026-03-01 14:23:47] [ERR] [FanController] Failed to turn ON: pin error
   [2026-03-01 14:23:48] [DEBUG] [FanController] cycle tick | temp=23.5 state=ON elapsed_s=45
   ```

2. **DHT data log** (`/sd/dht_log_YYYY-MM-DD.csv`) — Sensor data:

   ```csv
   timestamp,temperature,humidity
   2026-03-01 14:23:45,23.5,65.2
   2026-03-01 14:24:15,23.7,64.8
   ```

## Task

Analyze the attached log files and identify:

1. **Errors and warnings** — List all `[ERR]` and `[WARN]` entries with timestamps and affected modules.
2. **Patterns** — Are errors recurring? At what frequency? Correlated with time of day?
3. **SD card issues** — Look for `[BufferMgr]`, `[SD]`, fallback-related warnings, or gaps in data.
4. **Sensor health** — DHT read failures, out-of-range values, missing readings (gaps in CSV timestamps).
5. **Temperature anomalies** — Unusual temperature spikes/drops, thermostat triggers.
6. **Startup/shutdown** — Count system restarts (`[STARTUP]`), identify unclean shutdowns.

## Known failure modes

| Symptom | Likely cause |
| --------- | ------------- |
| `SD card mount failed after retries` | SD card loose, dirty contacts, or dead card |
| `Sensor read attempt N/3 failed: timeout` | DHT22 wiring issue or sensor failure |
| `Failed to turn ON/OFF: pin error` | Relay wiring or GPIO conflict |
| `RTC time appears invalid` | RTC battery dead or first-time setup needed |
| `Buffer has N entries (SD may be unavailable)` | SD card removed or failing; data buffered in RAM |
| `Log rotated -> system_*.log` | Normal — log exceeded 50KB and was rotated |
| Gaps in DHT CSV timestamps | System restart or sensor failure during that period |

## Module tags reference

| Tag | Module | What it controls |
| ----- | -------- | ----------------- |
| `MAIN` | `main.py` | System orchestration, health checks |
| `DHTLogger` | `lib/dht_logger.py` | Temperature/humidity sensor |
| `FanController` | `lib/relay.py` | Fan relay cycling |
| `GrowlightController` | `lib/relay.py` | Grow light scheduling |
| `BufferMgr` | `lib/buffer_manager.py` | SD/fallback storage |
| `EventLogger` | `lib/event_logger.py` | Log system itself |
| `HWFactory` | `lib/hardware_factory.py` | Hardware initialization |
| `StatusMgr` | `lib/status_manager.py` | Status LEDs |
| `Buzzer` | `lib/buzzer.py` | Audio alerts |
| `LEDButton` | `lib/led_button.py` | LED + button handler |

## Output format

Provide a structured summary:

```markdown
### Summary
- Time range: {first timestamp} to {last timestamp}
- System uptime: continuous / {N} restarts detected
- Error count: {N} errors, {N} warnings

### Critical issues
1. {description + affected module + timestamps}

### Recommendations
1. {actionable fix}
```
