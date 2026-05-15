# Hardware test log

> Per [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md).
> Eyes-on verification steps for things `pytest` can't exercise.
> Newest entry on top. Use `[ ]` pending, `[x]` passed, `[!]` failed,
> `[~]` partial/blocked.

## 2026-05-15 · Compiled SD-update payload (.mpy) end-to-end

**Branch:** `main`
**Why hardware-only:** `mpy-cross` output is bytecode-version specific
to the firmware on the Pico, and the updater rewrites flash from SD
and ends in `machine.reset()`. Host tests only confirm the
file/manifest/hash logic; they cannot prove the compiled `.mpy` files
actually import after the flash swap.
**Pre-flight:** Pico already flashed with the matching firmware
version (`flash-mpremote` baseline known-good). Take a Thonny backup
of `/main.py`, `/config.mpy`, `/lib/`. Confirm SD card mounted at
`G:` on host. No prior payload sitting at `G:/update`.

### Payload build and deploy

- [ ] Run `build-mpy` task — succeeds; `build/main.py`,
      `build/config.mpy`, `build/lib/*.mpy` all present.
- [ ] Run `deploy-update-to-sdcard-nocheck` task — succeeds; `G:/update/`
      contains `manifest.json`, `main.py`, `config.mpy`, `lib/*.mpy`
      and no raw `.py` files under `lib/`.
- [ ] Total payload size is meaningfully smaller than the previous
      raw-py payload (record both numbers in Notes below).
- [ ] `manifest.json` entries all end in `.mpy` except `main.py`.

### Apply on device

- [ ] Eject SD, insert into Pico, power-cycle.
- [ ] First boot after insert: updater logs `start` then `apply_ok` to
      `/sd/updates.log`; Pico reboots; comes back up healthy.
- [ ] `/sd/update` is gone; `/sd/applied/<version>/` holds the
      applied tree.
- [ ] `mpremote fs ls /` and `fs ls /lib` show `.mpy` files where
      expected; no orphan raw `.py` siblings except `main.py`.
- [ ] Watchdog does not fire during the apply (boot reaches main
      scheduler).

### Notes (compiled-payload)

> Fill in here. Capture before/after payload size and any
> firmware-version mismatch if `.mpy` files refuse to import.

## 2026-05-15 · SD-payload software updater — implementation eyes-on

**Branch:** `main`
**Why hardware-only:** The updater rewrites flash from SD before
`EventLogger` is up and ends in `machine.reset()`. Host tests cover
the file/manifest/hash logic end-to-end (15/15 passing), but real SD
timing, watchdog feeding during copies, and the post-reset clean-boot
path can only be confirmed on the Pico. The stub is gone; checks below
are now live.
**Pre-flight:** Working `/sd` mount; SD card formatted FAT32; current
`main.py` flashed via Thonny. Pull a known-good backup of `/lib/`,
`/main.py`, `/config.py` off the Pico before testing destructive paths.
Build a payload via VSCode task `build-update-payload` (or
`python tools/build_update_payload.py`) and copy it to the SD card with
`deploy-update-to-sdcard` (or `--copy-to G:/update --no-confirm`).

### Trigger detection

- [ ] With no `/sd/update/` folder: boot proceeds normally; nothing
      appended to `/sd/updates.log`.
- [ ] With `updater.enabled = False` in config and a valid `/sd/update/`
      present: boot proceeds normally; payload is untouched; no reset.
- [ ] With `/sd/update/manifest.json` present and `enabled = True`:
      boot enters the updater (visible via console prints before the
      reset).

### Verification gating

- [ ] Manifest with a corrupted file hash → `verify_fail` line in
      `/sd/updates.log`, `/sd/update/` left in place, no files
      overwritten, boot continues with old code.
- [ ] Manifest naming a path outside whitelist (e.g. `docs/x.md`) →
      same outcome: `verify_fail`, no writes.
- [ ] Manifest with a traversal entry (`../etc/passwd`) → rejected
      before any write.

### Apply + reset

- [ ] Good payload that changes `main.py` (e.g. a startup print): on
      boot, console shows updater activity, files are copied,
      `machine.reset()` fires, post-reset boot prints the new startup
      banner. `/sd/applied/<version>/` exists. `/sd/update/` is gone.
- [ ] Good payload that adds a file under `/lib/`: post-reset boot
      imports it successfully.
- [ ] Good payload that replaces `config.py` with a value change
      (e.g. `fan_1.on_time_s`): observed at runtime after reset.

### Failure / retry

- [ ] Pull SD card mid-apply (carefully, only after first file copy):
      updater logs `apply_fail`; `/sd/update/` still present on
      re-insert; next reboot re-attempts and completes.
- [ ] Watchdog: a full apply of N files completes without a WDT
      reset (i.e. updater feeds `wdt` between files).

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-15 · Growlight `mode` flag

**Branch:** `main`
**Why hardware-only:** The flag controls whether MCP4725 init runs on
the live I2C0 bus and whether GP20 is the only grow-light actuator.
Behavior is observable only by watching the boot log, the relay, and
the lamp on real hardware.
**Pre-flight:** Set `DEVICE_CONFIG["growlight"]["mode"]` to the value
under test (`"relay_only"` or `"dimmed"`) and flash `main.py`. For
`"dimmed"` runs, confirm the MCP4725 is on I2C0 at the configured
address (default `0x60`); for `"relay_only"` runs, the DAC can be
absent.

### relay_only mode

- [ ] Boot log shows `growlight.mode=relay_only — MCP4725 init skipped`
      and no `MCP4725 grow-light DAC at 0x…` line.
- [ ] At dawn (`growlight.dawn_hour:dawn_minute`) the GP20 relay
      energises (audible click, lamp on) without a fade.
- [ ] At sunset the relay de-energises (lamp off) without a fade.
- [ ] Removing the MCP4725 from the bus has no effect on grow-light
      scheduling.

### dimmed mode

- [ ] Boot log shows `MCP4725 grow-light DAC at 0x60` and no relay-only
      skip line.
- [ ] At dawn the lamp ramps from 0% to `growlight.default_level_pct`
      over `growlight.ramp_duration_s` seconds; relay energises at the
      start of the ramp.
- [ ] At sunset the lamp ramps back down and the relay de-energises at
      the end of the ramp.
- [ ] Disconnecting the MCP4725 before boot (with `mode="dimmed"`)
      logs `MCP4725 init failed (falling back to relay-only growlight)`
      and the lamp still switches on/off at the scheduled times via the
      relay.

### Notes (post-test) · growlight mode

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-15 · DHT22 → SHT31-D migration

**Branch:** `main`
**Why hardware-only:** I2C addressing on the shared bus, CRC behaviour
on a real sensor, accuracy vs. the prior DHT22, and downstream
consumers (fan thermostat, heater thermostat, OLED stats, status LEDs)
all depend on `TempHumidityLogger.last_temperature` and can only be
confirmed by watching readings on real hardware.
**Pre-flight:** Replace the DHT22 module on T/H_CON with a SHT31-D
breakout. Wire VCC = 3V3, GND, SDA = GP0, SCL = GP1, ADDR = GND
(0x44). Confirm the existing I2C pull-ups (R1/R2) are populated.
GP15 is now unused — leave the old DHT22 data wire disconnected.
Flash latest `main.py` after pulling the rename.

### Bus / addressing

- [ ] `prototypes/i2c_scan.py` (or equivalent REPL scan) lists `0x44`
      alongside `0x68` (RTC), `0x3C` (OLED), and `0x60` (MCP4725).
- [ ] If the SHT31 ADDR pin is wired to VCC, set
      `DEVICE_CONFIG["sht31"]["i2c_address"] = 0x45` and re-verify the
      scan shows the new address.

### Boot + steady state

- [ ] On cold boot, `system.log` shows
      `TempHumidityLogger Initialized: /sd/th_log_YYYY-MM-DD.csv`
      and no I2C / CRC errors during the first minute.
- [ ] `/sd/th_log_YYYY-MM-DD.csv` exists with a
      `Timestamp,Temperature,Humidity` header and gains a row every
      `temp_humidity_logger.interval_s` (default 30 s).
- [ ] Temperature and humidity readings on the OLED `temp` / `humidity`
      pages look plausible for the room (within ±1 °C / ±3 %RH of a
      reference thermometer).
- [ ] Activity LED (GP4) blinks once per successful read.

### Failure modes

- [ ] Unplug the SHT31 SDA line for 10 s — `system.log` records
      `TempHumidityLogger` warnings, the warning LED comes solid after
      `status_leds.th_warn_threshold` consecutive failures, then the
      error LED comes solid after `th_error_threshold`.
- [ ] Reconnect — both LEDs clear and CSV logging resumes within one
      cycle. Old `dht_log_*.csv` files remain untouched.
- [ ] Heater + fan thermostats follow the SHT31 temperature: warming a
      hot-air gun toward the sensor pushes `fan_1` / `fan_2` past
      `max_temp` and the heater past `day_min_temp` as expected.

### Notes (post-test)

> Fill in.

## 2026-05-14 · Phase 4 — Soil moisture (GP28 ADC)

**Branch:** `main`
**Why hardware-only:** ADC range, probe-to-soil contact resistance, and
real-world dry/wet endpoints differ per sensor and per soil pot;
only an eyes-on calibration pass produces useful `adc_dry_raw` /
`adc_wet_raw` defaults. CSV logging cadence and the warning-LED hook
also need confirmation against the live status manager.
**Pre-flight:** Flash latest `main.py`. Wire the soil probe to
`ADC_CON.4` (GP28). Have a small jar of saturated soil and an empty/dry
medium handy for calibration.

### Calibration via REPL

- [ ] In Thonny's REPL, run `from lib.soil_logger import print_raw` then
      `print_raw()` with the probe held in air. Record the value as
      `adc_dry_raw` (expected somewhere in the 700–900 range, but per-
      sensor).
- [ ] Insert the probe into saturated soil, run `print_raw()` again.
      Record the value as `adc_wet_raw` (expected 250–450 range).
- [ ] Update `config.py`'s `soil_logger.adc_dry_raw` and
      `adc_wet_raw` with the measured values; reboot.

### Logging

- [ ] On a fresh boot, `/sd/soil_log_YYYY-MM-DD.csv` exists with a
      `Timestamp,Raw,Percent` header within the first
      `soil_logger.interval_s` (default 60 s).
- [ ] Each cycle appends a plausible row: raw value in calibrated
      range, percent in 0–100.
- [ ] Pull the SD card briefly — soil rows should route through the
      fallback file and migrate back to `/sd/soil_log_*.csv` when the
      card returns.

### Warning LED + OLED page

- [ ] With the probe in dry soil (or air), the warning LED (GP6) turns
      solid ON within one `interval_s` cycle and EventLogger emits a
      `WARN` line `soil moisture low: N% (< 20%)`.
- [ ] Wet the soil — within one cycle the warning clears, LED turns
      off, and an `INFO` line `soil moisture recovered: N%` lands.
- [ ] Cycle the OLED to the `SOIL` page (after `CO2`). Verify the page
      shows `Moist: N%`, `Raw: NNN`, and the `Warn<20%` indicator.
      The `LOW!` row should appear only when percent is below the
      threshold.

## 2026-05-14 · Phase 3 — CO2 logger + fan override

**Branch:** `main`
**Why hardware-only:** SenseAir-style UART framing, 9600 baud line
levels through R9/R11 series resistors, real sensor response time vs.
`max_retries`/`retry_delay_ms` budget, and the high-ppm → fan-2 force-on
behavior all need eyes-on confirmation.
**Pre-flight:** Flash latest `main.py`. Confirm CO2 sensor is wired via
CO2_CON (GP16 TX → R9 → sensor RX, sensor TX → R11 → GP17 RX). Power
the sensor from the same 5 V supply as the rest of the board so the
common ground is stable.

### CO2 logging

- [ ] On a fresh boot, `/sd/co2_log_YYYY-MM-DD.csv` exists with a
      `Timestamp,PPM` header within the first ~30 s.
- [ ] Each poll cycle (default 30 s) appends one row with a plausible
      indoor reading (400–2000 ppm).
- [ ] During the `warmup_s` window (first 30 s), any missed reads
      surface as `DEBUG` lines only — no `WARN`/`ERR`.
- [ ] After the warmup window, intentionally disconnecting the sensor
      data line produces a `WARN` per poll cycle but the system loop
      stays alive (watchdog is still being fed).
- [ ] Reconnecting the sensor resumes logging within one
      `interval_s` cycle.

### CO2 override → fan_2

- [ ] Exhale steadily into the sensor inlet until ppm crosses
      `override_ppm_on` (default 1000). Within one `fan_2.poll_interval_s`
      cycle the fan relay closes (audible click) and the EventLogger
      reports `EXTERNAL OVERRIDE ON` against `Fan_2`.
- [ ] Stop exhaling and ventilate the room. As ppm drops below
      `override_ppm_off` (default 800), the override releases and
      `Fan_2` returns to schedule/thermostat control.
- [ ] Confirm that during an override, the thermostat path still
      wins: if you also warm the DHT22 to above `fan_2.max_temp`, the
      thermostat ON message logs and the fan stays on regardless of
      ppm direction.
- [ ] Pull the SD card briefly — CO2 rows should route through the
      fallback file and migrate back to `/sd/co2_log_*.csv` when the
      card returns (BufferManager path).

## 2026-05-14 · Phase 0/1/2 — heater + grow-light dimming

**Branch:** `main`
**Why hardware-only:** Active-HIGH MOSFET drive, MCP4725 I2C ACK at the
assumed address (0x60 vs 0x61), op-amp output range, and the dimming
fade behavior cannot be exercised by `pytest`. Heater fail-safe
on stale DHT reads also needs eyes-on confirmation.
**Pre-flight:** Flash latest `main.py`. Confirm growlight is wired
through REL_CON pin 4 → GL_CON, MCP4725 sits on the shared I2C0 bus,
heater wiring goes GP3 → R6 → IRLZ44N gate → HE_CON drain.

### Phase 0 · MCP4725 address probe

- [ ] Run `prototypes/i2c_scan.py` via Thonny on a clean boot.
      Expected scan results: `0x3C` (OLED), one of `0x60`/`0x61`
      (MCP4725), `0x68` (DS3231). Anything else gets noted below.
- [ ] If the MCP4725 reports at `0x61` instead of `0x60`, update
      `growlight.dac_i2c_address` in [config.py](../../config.py)
      and re-flash.

### Phase 2 · Heater (GP3 active-HIGH)

- [ ] Boot Pico with T/H_CON warm (room temp). Gate sits LOW
      (multimeter on R6 gate side ≈ 0 V). No spurious activation
      before the first DHT cycle completes.
- [ ] Apply ice pack to T/H_CON until DHT logs temperature below
      `heater.day_min_temp - hysteresis` (default 21.5 °C during the
      day window) → gate goes HIGH within one `heater.poll_interval_s`
      cycle (30 s). HE_CON drain should switch.
- [ ] Warm sensor back above setpoint → gate returns LOW.
- [ ] Unplug T/H_CON during a heating cycle. After
      `heater.max_stale_reads` (default 3) consecutive failed reads,
      gate falls LOW (fail-safe). EventLogger shows a `WARN` line.
- [ ] At night window (after 20:00 by default), setpoint drops to
      `night_min_temp` (16 °C). Confirm heater behavior follows.

### Phase 1 · Grow-light dimming (MCP4725 → op-amp → GL_CON)

- [ ] At boot, GL_CON measures 0 V (relay open, DAC at 0).
- [ ] During the day window, GL_CON tracks `default_level_pct` (80%).
      Op-amp output should sit around 80% of the buffer's swing.
- [ ] Force-set level 0 / 25 / 50 / 100 from the REPL:
      `growlight.set_level(50)`. Measure GL_CON; expected DAC raw
      output is 0 V / ~0.825 V / ~1.65 V / ~3.30 V (clamped to
      `max_level_pct=91` so 100% reads ~3.00 V at the DAC pin).
- [ ] At schedule dawn the lamp comes on at default level. At sunset
      it goes off (relay opens, DAC returns to 0).
- [ ] Pull I2C0 SDA briefly during a level change. Logger captures the
      DAC write error, controller does not crash, system continues.

## 2026-05-14 · PCB pin remap connection test

**Branch:** `main`
**Why hardware-only:** GPIO assignments changed across nearly every peripheral
to match the new printed PCB (`docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json`).
`pytest` only checks config shape — wiring continuity, LED roles, relay polarity,
UART direction and SD/I2C bus integrity must be observed on the physical board.
**Pre-flight:** Flash the latest `main.py` to the Pico; insert a freshly-formatted
SD card; connect the LED_CON, REL_CON, BUZ_CON, MEN_BTN, OLED_CON, RTC_CON,
T/H_CON, CO2_CON, ADC_CON and at least one I2C_CON breakout per the new PCB.

### Boot + I2C0 bus

- [ ] Pico boots, POST LED walk fires in order **GP4(Activity) → GP5(SD) → GP6(Warn) → GP7(Err) → GP8(Service)** — confirms LED channel remap.
- [ ] On-board GP25 heartbeat blinks once per ~2 s.
- [ ] OLED (SSD1306 @ 0x3C) shows the default menu within 5 s.
- [ ] RTC time displayed is within ±2 s of wall clock (no "RTC invalid" warning LED).
- [ ] `I2C_CON1/2/3` breakouts read back the expected bus traffic on a logic analyzer (GP0=SDA, GP1=SCL).
- [ ] MCP4725 grow-light DAC (new, at 0x60) ACKs on the bus — even if no driver is wired yet.

### SD card (SPI1 via R8/R10 series resistors)

- [ ] `system.log` shows successful SD mount within the first health-check cycle.
- [ ] DHT log file appears at `/sd/dht_log_YYYY-MM-DD.csv` and grows every 30 s.
- [ ] Hot-pull the card → SD LED (GP5) goes solid; re-insert → LED clears, fallback rows migrate (check `migrations` metric in log).

### Status LEDs (LED_CON role swap)

- [ ] Force DHT failure (unplug T/H_CON) → after threshold, **GP6 Warn** then **GP7 Err** light up.
- [ ] Service-reminder due → **GP8** blinks the configured pattern.
- [ ] During an SD write → **GP4** Activity LED pulses briefly.
- [ ] Hot-pull the SD card → **GP5** SD LED goes solid (also covered in the SD section above).

### Menu button (GP9) + reset

- [ ] Short press MEN_BTN → OLED cycles to next menu page.
- [ ] Long press (≥3 s) → service reminder resets / context action fires.
- [ ] Press RES_BTN → Pico hard-resets (3V3_EN line, not a GPIO). System comes back cleanly.

### Buzzer (GP14, was GP20)

- [ ] Startup melody plays on boot.
- [ ] Trigger an error condition → error pattern audible.

### Relays (REL_CON, GP18/19/20 = fan_1/fan_2/growlight)

- [ ] REL_CON pin 2 (GP18) clicks on the fan_1 cycle schedule.
- [ ] REL_CON pin 3 (GP19) clicks on the fan_2 cycle schedule.
- [ ] REL_CON pin 4 (GP20) toggles at the configured dawn/sunset times.
- [ ] Reserved relays on GP21/22/26/27 stay HIGH (off) — no spurious activity.
- [ ] Verify polarity: relays are wired active-low; LOW on GPIO = load energized.

### CO2 UART (GP16/GP17 = UART0, was GP2/GP3 on UART1)

- [ ] CO2_CON wired to a CO2 sensor → first valid reading arrives within the sensor's warm-up window.
- [ ] Confirm baud 9600 8N1 on the line with a scope or USB-UART probe.

### DHT22 (GP15, unchanged)

- [ ] T/H readings appear in `dht_log_*.csv` every 30 s with realistic values.

### Heater MOSFET (GP3, new)

- [ ] No driver yet — verify the gate sits LOW at boot (multimeter on R6 / MOSFET gate). Heater must NOT energize spuriously.

### ADC input (GP28, new)

- [ ] Apply a known voltage to ADC_CON pin 4 → confirm Pico ADC reads it (use a prototype script or REPL `machine.ADC(28).read_u16()`).

### Notes (post-test)

> Fill in here after running through the list. Capture any `[!]` with the
> failure mode and a one-line repro so the next session can pick it up.
