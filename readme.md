
# Pi Greenhouse: Raspberry Pi Pico Environmental Control System

**Pi Greenhouse** runs a grow tent or mushroom fruiting chamber closed-loop on a Raspberry Pi Pico. Every 30 seconds it reads temperature, humidity and CO₂, normalises them against the active species profile, and turns the result into commands for seven actuators — heater, heater-follower fan, cooler, humidifier, exhaust, circulation pair and grow light. Everything it measures is logged to SD with tiered fallback, shown on an OLED, and the unit can be updated in the field from the same card.

The **same source** runs in two places: on the Pico under MicroPython, and on Windows or Linux CPython through the shims in [host_shims/](host_shims/) — so the whole system boots and runs on a laptop with no hardware attached.

## At a glance

| | |
| --- | --- |
| **Target** | Raspberry Pi Pico (RP2040), custom MicroPython with frozen application modules |
| **Sensing** | SHT31-D temp/humidity (I²C0), SenseAir S8-style CO₂ (UART0), analog soil probe (plant mode) |
| **Actuation** | 3 mains relays, 1 heater MOSFET, 5 PWM fan channels (PCA9685), 0–10 V lamp dimmer (MCP4725) |
| **Control** | one config-driven regulation engine, 30 s tick, allocation-free hot path |
| **Storage** | SD card → `/local/fallback.csv` → in-memory ring buffer, with automatic migration back |
| **Operator UI** | SSD1306 OLED (11 pages, one button), 5 status LEDs, passive buzzer |
| **Updates** | SD-payload OTA (SHA-256 + `.mpy` ABI checked), custom firmware build + verify tooling |
| **Host dev** | full system runs on CPython; pytest suite with an 88 % coverage gate |

## How it works

### One engine owns every regulated actuator

The [RegulationEngine](lib/regulation_engine.py) replaces what used to be a pile of independent controllers (a fan thermostat, a heater day/night cycle, a CO₂ vent override, a grow-light scheduler). It runs a five-stage pipeline every `regulation.tick_s`:

1. **Normalize** — each dimension's physical reading is mapped through three per-phase anchors (`at_0`, `at_50`, `at_100`) to a deviation `d ∈ 0..100`, where 50 is ideal. Severity is `|d − 50|`. Day and night anchors are blended by a time-of-day factor from the RTC, so setpoints ramp instead of stepping at dawn.
2. **2D hinge surfaces** — each regulator evaluates a pure function of two deviations (e.g. the heater sees temp × humidity) built from a rotated plane, eight hinges, two boost axes and clamps. CO₂ enters additively on the exhaust and circulation regulators — no surface takes CO₂ as an axis.
3. **Band classify** — severity is bucketed by `band_edges` into perfect / ideal / organic / minor / major / emergency / shutdown.
4. **Arbitrate** — slew-limit the organic output, apply per-regulator floors, apply ordered conflict rules (the shipped one cuts the humidifier in a hot-and-humid tent to head off bacterial blotch), then emergency and latch vectors. Forced values are written *after* the slew limiter, so a safety cut lands in one tick.
5. **Actuator adapters** — device quirks live only [here](lib/regulation_adapters.py): relay hysteresis and compressor anti-short-cycle, heater time-proportioning over a 600 s window, PWM duty, the pair scaler for centre/wall fans, and the grow light's relay-plus-DAC pairing.

The engine never reads a sensor directly — it consumes the loggers' cached values. The per-tick path is allocation-free (frozen `array('f')` parameters, preallocated buffers), and the surface math is pinned by golden-vector CSVs under [tests/golden/](tests/golden/).

Full specification: [docs/prompts/regulation-matrix.md](docs/prompts/regulation-matrix.md).

Two behaviours are worth knowing before you tune anything:

- **Escalation is gated by direction.** Only the hazardous high side of temperature and humidity may escalate to the emergency and latch vectors; too cold, too dry and any CO₂ level are conditions the surfaces correct on their own. Ungated escalation used to latch a freshly set-up tent on its first tick, with the very actuators that would fix it forced off.
- **The chamber keeps breathing when CO₂ goes blind.** The S8 is specified to 95 %RH non-condensing and fails exactly when a fruiting tent is running correctly. With no usable reading the CO₂ dimension is neutralised, so `regulation.fresh_air_exchange` applies a timed floor to the exhaust and circulation instead.

### The profile is the setpoint

`regulation.profile` picks a species profile — `cubensis`, `oyster`, `lions_mane` for mushrooms; `seedling`, `cannabis`, `bellpepper` for plants. Each holds day and night anchors for all three dimensions, and its `category` must match the top-level `mode` (validated at boot). Retuning what "ideal" means is an edit to three numbers per dimension, not a code change.

The top-level `mode` switch decides which optional components are constructed:

| Mode | Soil logger | Regulation profiles allowed |
| --- | --- | --- |
| `"mushroom"` (default) | not constructed | `category: mushroom` |
| `"plant"` | enabled (GP28 ADC) | `category: plant` |

Grow-light dimming is **not** tied to the mode — `regulation.regulators.growlight.dimmable` decides, because the MCP4725 is harmless when fitted and pointless for mushrooms either way. Disabled components are skipped entirely: no task, no I/O, no idle RAM.

### Same code, two runtimes

[main.py](main.py#L31-L36) detects `sys.implementation.name != "micropython"` and prepends [host_shims/](host_shims/) to `sys.path`, providing `machine`, `micropython`, `os`, `framebuf`, an `sht31` simulator and a `uasyncio` that aliases standard `asyncio`. Anything new that imports a MicroPython-only API needs a matching shim, or it will only ever work on-device.

Tests take a third path: [tests/conftest.py](tests/conftest.py) installs `MagicMock` stubs *before* any `lib/` import and never touches the shims.

### Every persistent write goes through one chokepoint

`TempHumidityLogger`, `CO2Logger`, `SoilLogger`, `MetricsLogger` and `EventLogger` all write through [BufferManager](lib/buffer_manager.py), which tries the SD card, falls back to `/local/fallback.csv`, and falls back again to an in-memory ring buffer. When the card comes back the health loop migrates the fallback rows onto it in bounded batches. [WriteQueueManager](lib/write_queue_manager.py) batches the actual SD writes off the hot path. Direct file I/O anywhere else bypasses all of that and is a bug.

### Boot order is enforced

[main.py](main.py) is the only place components are wired; everything downstream takes its dependencies as constructor arguments. The order is deliberate:

1. **Config validation** — `validate_config()` is the only check, and it runs before anything is constructed.
2. **Early OTA (device only)** — the watchdog is armed and a pending SD update is applied *before* the heavy application imports, while the heap is still nearly empty. A successful apply ends in `machine.reset()`, so the old code never finishes booting.
3. **[HardwareFactory](lib/hardware_factory.py)** — RTC (critical) → SPI/SD mount → GPIO. If `system.require_sd_startup` is set and the card will not mount, the boot path lights the SD and error LEDs, holds a visible countdown, and resets.
4. **`RTCTimeProvider`** — every timestamp in the system comes from here; no module calls the RTC directly.
5. **`StatusManager`** — owns the LED row and the power-on self-test walk.
6. **Buffer / queue / event logger**, then the sensor loggers, then the regulation stack, then the UI.

All long-running work is a `uasyncio` task. The watchdog is fed by its own task, so a stalled scheduler resets the Pico — which also means a blocking call inside any task will reset real hardware even when host tests pass happily.

## Hardware

Pin assignments mirror PCB schematic `SCH_Pico-Greenhouse-PCB_2026-05-14` and the `pins` section of [config.py](config.py). Relay GPIOs are **active-low** (HIGH = off, LOW = on); LEDs and the heater MOSFET are active-high.

| GPIO | Purpose |
| --- | --- |
| GP0 / GP1 | **I²C0, shared**: SHT31-D `0x44`, DS3231 RTC `0x68`, SSD1306 OLED `0x3C`, PCA9685 `0x40`, MCP4725 `0x60`, breakout headers. Pulled to 3V3 via R1/R2 |
| GP2 | General-purpose breakout header |
| GP3 | Heater MOSFET gate (IRLZ44N via R6) — **active HIGH** |
| GP4 – GP8 | Status LEDs: activity, SD, warning, error, service reminder |
| GP9 | Menu button — short press cycles pages, long press (≥ 3 s) runs the page action |
| GP10 – GP13 | SPI1 to the SD card (SCK / MOSI / MISO / CS); MOSI and MISO carry series dampers |
| GP14 | Passive buzzer (PWM) |
| GP15 | SD card-detect (Adafruit 4682 CD switch; HIGH = card seated) |
| GP16 / GP17 | UART0 TX/RX to the CO₂ sensor, 9600 baud |
| GP18 | Relay 1 — **cooler** |
| GP19 | Relay 2 — **humidifier** |
| GP20 | Relay 3 — **grow light** |
| GP21 | Relay 4 — spare (wired, no controller) |
| GP22 / GP26 / GP27 | Reserved relay lines (no net on the connector) |
| GP25 | On-board LED — heartbeat |
| GP28 | ADC2 — soil-moisture probe (plant mode) |

Fans do not use GPIO: all five run from the PCA9685 on I²C0 — ch0 circulation centre, ch1 circulation walls, ch2 heater follower, ch3 case, ch4 exhaust. The channel map is bench-confirmed; do not renumber it without re-running the bring-up.

The PCB's `RES_BTN` is wired to the Pico's `3V3_EN` (hardware reset), not a GPIO. There is no I²C1 in this design — every I²C device shares bus 0.

Hardware reference: [docs/hardware/pcb-design-rules.md](docs/hardware/pcb-design-rules.md), the queued changes in [docs/hardware/next-revision.md](docs/hardware/next-revision.md), and the printable enclosure legend [docs/hardware/case-legend.pdf](docs/hardware/case-legend.pdf).

## Quick start

### Run it on your machine

The shims simulate GPIO, SPI, I²C, UART, the SHT31 and the filesystem, so the full system runs on standard Python 3.

```bash
pip install -r requirements.txt
python main.py
```

It creates `./sd/` (simulated card) and `./local/` (fallback buffer) in the repo. Shims are auto-detected and never loaded on the Pico.

### Run the tests

```bash
pytest tests/
```

```bash
pytest tests/ --cov=lib --cov=config --cov-report=term-missing
```

```bash
ruff check . --fix
```

Coverage below 88 % fails. See [tests/README.md](tests/README.md) for the MicroPython mocking approach.

### Run it on a Pico

1. Flash the firmware — stock MicroPython works, the custom frozen build is recommended (see [Keeping a unit up to date](#keeping-a-unit-up-to-date)).
2. Seed the RTC once, on-device: `prototypes/rtc_set_time.py`.
3. Copy `main.py`, `config.py` and `lib/` to the board (`tools/deploy_device.py` does this over `mpremote`, with `--prune` to clear stale files that would shadow frozen modules).
4. Reset. The LED walk at boot confirms the row is alive; the OLED banner confirms the display is.

## Operating the unit

**Button (GP9)** — short press cycles OLED pages; long press (≥ 3 s) runs the current page's action. The debug page's action opens a sub-menu where short press picks an action and long press runs it; destructive actions ask for a second long press.

**OLED pages** — `temp`, `humidity`, `service`, `sd`, `alerts`, `system`, `relays`, `reg`, `co2`, `soil`, `debug`. The `reg` page shows the engine's live state: deviation triple, band, and the commanded value for each actuator. The display sleeps after `display.display_timeout_s` to spare the panel.

**Status LEDs** — the convention is *solid = problem, blink = activity, dark = all good*.

| LED | GPIO | Meaning |
| --- | --- | --- |
| Activity | GP4 | Brief blink on sensor reads and I/O |
| SD | GP5 | Dark = mounted · solid = no card in the slot · blinking = card present but mount failed |
| Warning | GP6 | Solid = a degraded condition is active |
| Error | GP7 | Solid = a fault needs attention |
| Reminder | GP8 | Blinks when the service interval has elapsed (long-press GP9 to reset) |
| Heartbeat | GP25 | Toggles each health-check tick — proves the loop is alive |

**Alert keys** — the `alerts` page names the active condition. Errors: `sd_required`, `th_dead`, `mem_error`, `logged_error`. Warnings: `th_intermittent`, `fallback_active`, `buffer_backlog`, `mem_warn`, `rtc_invalid`, `co2_stale`, and `soil_low` in plant mode. The printed case legend lists these for someone standing at the tent with no terminal; it is regenerated from [tools/gen_case_legend.py](tools/gen_case_legend.py) whenever an operator-visible surface changes.

## Data on the SD card

```text
/sd/sensors/th/YYYY/th_YYYY-MM-DD.csv           temperature + humidity
/sd/sensors/co2/YYYY/co2_YYYY-MM-DD.csv         CO₂ ppm
/sd/sensors/soil/YYYY/soil_YYYY-MM-DD.csv       soil moisture (plant mode)
/sd/sensors/metrics/YYYY/metrics_YYYY-MM-DD.csv health + regulation metrics
/sd/logs/system.log                             system event log
/sd/logs/updates.log                            OTA history
/boot.log                                       last boot's diagnostics (internal flash)
```

Sensor files roll over at midnight. Temperature/humidity rows look like this:

```csv
Timestamp,Temperature,Humidity
2026-01-29 14:35:42,22.5,65.3
2026-01-29 14:36:12,22.6,65.1
```

The **metrics CSV** is written by the health loop when `diagnostics.metrics_log` is on: free/allocated heap and used percentage, task count, write-queue and buffer depth, fallback writes and write failures, plus the engine's `tick_us` / `tick_max_us` timing, global severity, band, latch and emergency flags, the three deviations, and the commanded value for all seven actuators. It charts like any other sensor log, which is what makes a soak run legible after the fact. `diagnostics.mem_trend_log` adds one greppable pre/post-GC heap line per cycle to `system.log` without turning on debug logging.

## Keeping a unit up to date

**Application updates (no reflash).** Build a payload with `tools/build_update_payload.py`, drop the tree under `/sd/ota/pending`, and reset. The updater verifies every file by SHA-256 before writing any, refuses payloads whose `.mpy` ABI the running firmware cannot import, writes with per-file retries, sweeps files the payload did not ship (so a stale `lib/*.mpy` cannot keep shadowing its frozen twin), archives the payload to `/sd/ota/applied/<version>/`, and resets. LEDs chase and the buzzer ticks throughout, so an update is visible without a serial console.

**Firmware.** The application modules are frozen into a custom `.uf2`, which reclaimed roughly a third of the heap. Building, flashing, verifying that the image really froze what the manifest asked for, and the `.mpy` ABI rules that keep OTA payloads importable are all in [docs/hardware/firmware-build-runbook.md](docs/hardware/firmware-build-runbook.md). Two rules that bite: a package cannot span frozen and filesystem copies, and a leftover file in `/lib` silently wins over its frozen twin.

Every boot logs one identity line — firmware version, app version, `.mpy` ABI, and where that identity came from — to both `system.log` and `/boot.log`. It is the only record of the outgoing firmware once a new image is written.

## Configuration

Every tunable value lives in the single `DEVICE_CONFIG` dict in [config.py](config.py), and `validate_config()` checks it at boot. A new key is not done until it exists in the dict, in the validator, and in [tests/test_config.py](tests/test_config.py). `lib/` modules never import `DEVICE_CONFIG` — values reach them through constructors, which is what keeps them testable in isolation.

**→ [docs/configuration.md](docs/configuration.md)** documents every section: pins, regulation (profiles, regulators, surfaces, adapters, escalation, latch, conflicts), loggers, storage, display, LEDs, buzzer, updater, diagnostics and system timing.

## Repository layout

```text
config.py        DEVICE_CONFIG + validate_config() — the only knobs
main.py          orchestrator: DI wiring, boot order, async tasks, health loop
lib/             application modules (+ vendored SD, RTC, OLED drivers)
host_shims/      CPython stand-ins for MicroPython APIs
tests/           pytest suite, incl. golden vectors for the surface math
tools/           host-side: firmware build, OTA payload, deploy, case legend
prototypes/      on-device bench scripts and the surface-tuning explorer
docs/            configuration, conventions, hardware, task prompts
```

**→ [docs/repository-layout.md](docs/repository-layout.md)** for the annotated file-by-file tree.

## Development

- **Language** — MicroPython on-device, standard Python 3 on the host. No f-strings or dict churn in the regulation tick path.
- **Style** — `ruff`, line length 120, rules `E,F,I`. Vendored drivers, `host_shims/` and `typings/` are excluded from lint and coverage on purpose.
- **Tests** — `pytest` + `pytest-asyncio` with `asyncio_mode=auto`; coverage gate `fail_under=88`; `pre-commit run --all-files` runs lint and the suite.
- **Conventions** — architecture, naming, GPIO, logging and error-handling rules are in [docs/conventions.md](docs/conventions.md).
- **Retuning a surface** is a deliberate act: regenerate the golden vectors with [prototypes/plot_regulation_surfaces.py](prototypes/plot_regulation_surfaces.py), and remember that a surface and its adapter's thresholds are one calibration, not two knobs.

## Troubleshooting

| Symptom | Where to look |
| --- | --- |
| No timestamps in the logs | Seed the DS3231 once with `prototypes/rtc_set_time.py` |
| Boot loops with the SD and error LEDs lit | SD required but not mounting — check GP10–GP13 wiring and card seating, or set `system.require_sd_startup=False` |
| Sensor reads failing | SHT31 at `0x44` on I²C0 (`prototypes/i2c_scan.py`); `max_retries` defaults to 3 |
| A relay never switches | Relay GPIOs are inverted (HIGH = off). Confirm with the `relays` OLED page or `tools/relay_diag.py` |
| Data missing after pulling the card | Check `/local/fallback.csv` — rows migrate back when the card returns |
| An actuator sits at a constant value | Check the `reg` OLED page for a latch. Release needs every severity ≤ `latch.release_max` for `release_ticks` ticks *and* `latch.min_s` elapsed |
| CO₂ never moves the fans | The reading may be stale (`co2_stale` alert) — the fresh-air-exchange floor takes over. Otherwise check UART0 wiring and that the CO₂ term clears the regulator's floor |
| OLED blank | It must answer at `0x3C`; after `display.max_render_errors` consecutive I²C failures it self-disables to protect the shared bus |
| `system.log` growing without bound | It rotates past `event_logger.max_size` and keeps `log_retention_days` of archives |
| OTA refused with `mpy_abi mismatch` | The `.mpy` files were built by a different `mpy-cross` than the running firmware — see [the runbook](docs/hardware/firmware-build-runbook.md#5-the-mpy-abi-invariant-do-not-get-this-wrong) |
| OTA applied but a `lib/` module didn't change | That module is frozen into the firmware. Rebuild and reflash, or move it out of the freeze set |

## Roadmap

- **Adaptive tuning** — close the loop on the regulation surfaces themselves from logged outcomes, rather than hand-exporting them from the tuning explorer.
- **Soil sensor swap** — replace the analog GP28 probe with the Adafruit STEMMA #4026 (I²C) on the next PCB.
- **Hydroponics monitoring** — a second I²C bus for Atlas EZO pH/EC probes, monitor-only to start.
- **More species profiles** — colonization-phase mushroom profiles (which legitimately run several thousand ppm CO₂) and vegetable presets.
- **Enclosure** — a documented case with assembly instructions to go with the printed legend.
