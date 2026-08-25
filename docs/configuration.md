# Configuration reference

Every tunable value in Pi Greenhouse lives in one dict — `DEVICE_CONFIG` in
[`config.py`](../config.py). This page maps the dict: what each section
controls and which keys matter. The inline comments in `config.py` carry the
*why* behind individual values (measurements, field incidents, rejected
alternatives) and are the authority when the two disagree.

## The three rules

1. **One dict, one validator.** `validate_config()` runs before anything is
   constructed and is the only check. A new key is not finished until it exists
   in the dict, in the validator, and in
   [`tests/test_config.py`](../tests/test_config.py) — in the same commit.
2. **No reaching into config from `lib/`.** [`main.py`](../main.py) reads the
   dict and passes plain values into constructors. No module under `lib/`
   imports `DEVICE_CONFIG`, which is what lets tests instantiate components with
   literals. `HardwareFactory` is the one exception: it takes the relevant
   section dicts as arguments, still without importing the config itself.
3. **Anything an operator might retune belongs here.** Pins, intervals,
   thresholds, timeouts, buffer sizes, paths, feature toggles. A literal that
   deliberately stays inline carries a `# fixed: <reason>` comment; a magic
   number without one is a defect.

## Top-level map

| Section | Controls |
| --- | --- |
| [`mode`](#mode) | Which optional components exist at boot |
| [`pins`](#pins) | Every GPIO, UART and bus assignment |
| [`spi`](#spi--sd_detect) | SD card SPI bus |
| [`sd_detect`](#spi--sd_detect) | Card-detect line polarity and pull |
| [`files`, `paths`](#files--paths) | Log and sensor-tree locations |
| [`sht31`](#sensors) | Temp/humidity sensor address |
| [`temp_humidity_logger`](#sensors) | T/H poll cadence and retries |
| [`co2_logger`](#sensors) | CO₂ poll, frame integrity, staleness |
| [`soil_logger`](#sensors) | Soil probe calibration + root-zone limits (plant mode) |
| [`fans`](#fans--pca9685) | Fans *outside* the regulation engine |
| [`pca9685`](#fans--pca9685) | PWM driver address, frequency, inversion |
| [`regulation`](#regulation) | The whole control pipeline |
| [`display`](#display) | OLED pages, timeouts, debug sub-menu |
| [`status_leds`](#status-leds--buzzer) | LED behaviour, POST walk, memory thresholds |
| [`buzzer`](#status-leds--buzzer) | Tone patterns |
| [`Service_reminder`](#service-reminder) | Maintenance interval and persistence |
| [`buffer_manager`](#storage) | Tiered-storage limits |
| [`event_logger`](#storage) | System log level, rotation, retention |
| [`updater`, `updater_feedback`](#updater) | SD-payload OTA |
| [`diagnostics`, `memory`](#diagnostics--memory) | Instrumentation and GC tuning |
| [`system`](#system) | Watchdog, health loop, I²C, SD retries, write queue |
| [`output_pins`](#output-pins) | Boot-time output states |

## mode

```python
"mode": "mushroom",   # or "plant"
```

Picks which optional components are constructed. `"plant"` builds the
`SoilLogger` and its STEMMA probe; `"mushroom"` skips both entirely — no object,
no task, no I/O. The active `regulation.profile`'s `category` must match this
mode, and `validate_config()` enforces it.

Grow-light dimming is **not** controlled by the mode. It is decided by
`regulation.regulators.growlight.dimmable`, because the MCP4725 costs nothing
when fitted and does nothing for mushrooms either way.

## pins

Mirrors PCB schematic `SCH_Pico-Greenhouse-PCB_2026-05-14`. Relay lines are
active-low; LEDs and the heater MOSFET are active-high. See the GPIO table in
[`readme.md`](../readme.md#hardware) for the wiring view; `config.py` carries
the per-pin connector references.

Notable keys: `heater_mosfet` (GP3, active HIGH — the one non-relay switch),
`relay_cooler` / `relay_humidifier` / `relay_growlight` (GP18/19/20),
`relay_reserved_1` (GP21, wired but unclaimed), `sd_detect` (GP15),
`co2_uart_tx` / `co2_uart_rx` / `co2_baudrate`. GP28/ADC2 carries no key: the
soil probe moved to I²C and the pin is free.

`relay_reserved_2..4` (GP22/26/27) exist in the dict but have no net on the
connector — they are driven HIGH at boot and otherwise unused.

## spi & sd_detect

`spi` configures SPI1 to the SD card: `baudrate` (10 MHz — bandwidth is not the
bottleneck, CSV rows are ~30 bytes), the four pins, and `mount_point`.

`sd_detect` reads the Adafruit 4682 card-detect switch. `present_when_low` is
field-observed as `False` on this board (GP15 HIGH = card seated) and stays
configurable because it is board-specific. With `enabled: False` the line is
ignored and hot-swap recovery falls back to polling the bus.

## files & paths

`paths.sensor_root` anchors the sensor tree; the final path per reading is
`<sensor_root>/<type>/YYYY/<type>_YYYY-MM-DD.csv`. Adding a sensor means adding
a `sensor_type` string, not touching the path code. `paths` also holds the
logs, OTA pending/applied and diagnostics directories.

## Sensors

**`sht31`** — I²C address (`0x44`, or `0x45` with ADDR tied high).

**`temp_humidity_logger`** — `interval_s`, `max_retries`, `retry_delay_s`,
`sensor_type`. The cached `last_temperature` / `last_humidity` are what the
regulation engine consumes; the engine never reads the sensor itself.

**`co2_logger`** — `interval_s`, `warmup_s`, `max_retries`, plus three layers
of defence against a sensor that fails in humid air:

| Key | Effect |
| --- | --- |
| `verify_checksum` | Reject frames failing the Modbus RTU header + CRC16 check. This is the primary filter — a range check cannot catch a framing error that lands on a plausible value |
| `plausible_min_ppm` / `plausible_max_ppm` | Backstop window for structurally valid but absurd readings. The ceiling is a *fruiting* figure; raise it before automating colonization |
| `stale_after_s` | Age past which the cached reading stops being offered to the engine. Without it the engine regulates forever on a dead sensor's last value |

`override_ppm_on` / `override_ppm_off` drive only the advisory flag on the CO₂
OLED page. Actual venting is the engine's job through the CO₂ deviation
dimension.

**`soil_logger`** *(plant mode)* — an Adafruit STEMMA #4026 capacitive probe on
I²C0 at `i2c_address` (0x36). `raw_dry` and `raw_wet` are raw seesaw counts (what
the `print_raw()` REPL helper prints); **wet must be higher than dry** — the
capacitive probe reads higher when wetter, the opposite of the analog probe it
replaced. The shipped 200/2000 are placeholders: calibrate in air and in
saturated substrate before potting. `warn_pct_below` raises the warning LED, and
`root_temp_min_c` / `root_temp_max_c` bound the root-zone temperature the same
probe reports (logged and alarmed only, never regulated).

## fans & pca9685

`fans` holds only fans **outside** the regulation pipeline — currently just the
always-on case fan on PCA9685 ch3. The regulated fans (exhaust, circulation
pair, heater follower) are engine actuators configured under
`regulation.regulators.*.adapter`; adding them here would claim the channel
twice.

Each entry needs `enabled`, `mode` (`always_on` is the only policy left),
`output` (`relay` or `pca9685`), the channel or `relay_pin_key`, `duty_pct` and
`refresh_interval_s`.

`pca9685` configures the shared PWM driver:

| Key | Notes |
| --- | --- |
| `i2c_address` | `0x40` with all address straps low |
| `freq_hz` | 24–1526 Hz, shared by all 16 channels. Currently 60 Hz as an audible-noise trial: the chip cannot reach the ~25 kHz that makes fan PWM inaudible, so the only choice is *which* audible tone, and 60 Hz drones below the ear's most sensitive band instead of whining inside it. Costs low-duty torque smoothness — revert to 1000 if a fan will not start at its configured floor |
| `invert` | Whether the gate stage inverts duty. Applies to every channel |

If the chip is absent, every PCA9685-backed output becomes inert and cooling
stops — there is no relay fallback now that the roster is all-PWM.

## regulation

The largest section, and the one worth reading `config.py` for directly. The
model itself is specified in
[`docs/prompts/regulation-matrix.md`](prompts/regulation-matrix.md).

### Engine-level keys

| Key | Meaning |
| --- | --- |
| `enabled` | `False` leaves only the case fan and the sensor loggers running |
| `tick_s` | Evaluation cadence (30 s) |
| `profile` | Active species profile; its `category` must match the top-level `mode` |
| `band_edges` | Severity band boundaries, strictly ascending, last = 50 → perfect / ideal / organic / minor / major / emergency / shutdown |
| `day_start_min`, `day_end_min`, `transition_min` | Time-of-day blend. `b = 1` full day, `b = 0` full night, linear ramp of `transition_min` on each edge |
| `external_sensor` | Optional second SHT31 that gates exhaust *effectiveness* only. Disabled → constant multiplier of 1.0 |
| `fresh_air_exchange` | Timed exhaust/circulation floor for when the CO₂ reading is unavailable |
| `escalation` | Which deviation directions may escalate to the forced vectors |
| `latch` | Entry, release and minimum-hold rules for the safe-state latch |
| `profiles` | Species anchor sets |
| `regulators` | Per-actuator surfaces, adapters and forced values |
| `conflicts` | Ordered override rules applied at global band ≥ 30 |

### profiles

Each profile has a `category` (`mushroom` or `plant`) and, for `day` and
`night`, three anchors per dimension:

```python
"temp":     {"at_0": …, "at_50": …, "at_100": …},   # °C
"humidity": {"at_0": …, "at_50": …, "at_100": …},   # %RH
"co2":      {"at_0": …, "at_50": …, "at_100": …},   # ppm
```

`at_50` is ideal (deviation 50). The two outer anchors set how fast deviation
grows on each side — asymmetric spacing is how "strict below, tolerant above"
is expressed. Tune these first: they define what the whole engine is aiming at.

Two traps live here, both learned the hard way:

- **Deviation saturates at the outer anchor**, and a saturated dimension pins
  global severity at 50 — the latch edge. An `at_100` that the chamber reaches
  routinely will latch the system on a normal condition. The humidity ceiling
  is deliberately set just past physically reachable for exactly this reason,
  and *tightly* — loosening it further would halve the exhaust and circulation
  response at the condition they exist to correct.
- **The ideal is a calibration, not a preference.** Moving `at_50` moves the
  humidifier ramp, the conflict rule's threshold and the adapter switch points
  with it. Change them together or the tent cannot reach its own setpoint.

### regulators

Seven slots, in a load-bearing order (`heater`, `heater_follower`, `cooler`,
`humidifier`, `exhaust`, `circulation`, `growlight`). Each has:

| Key | Meaning |
| --- | --- |
| `driven` | `surface` (2D hinge function), `follower` (derived from the heater command), or `tod` (time-of-day blend — the grow light) |
| `dims` | `[x, y]` deviation inputs for a surface-driven regulator |
| `surface` | Parameter set built by `_surface(**overrides)` — neutral defaults make an untouched surface a pass-through |
| `co2_gain`, `co2_break` | Additive CO₂ term: `gain * relu(co2_dev − break)`. Only on the exhaust and circulation — this is CO₂'s *only* path to any actuator |
| `external` | Whether the external-effectiveness multiplier applies (exhaust only) |
| `adapter` | Device-quirk layer: `relay`, `pwm`, `pwm_pair`, `growlight` or the heater's time-proportioning window |
| `slew_normal`, `slew_fast` | Max per-tick delta of the organic output, below / within band 20–39 |
| `floor` | Minimum command once the regulator's band reaches 20 — floors only push toward stronger actuation |
| `emergency_value`, `safe_state` | Forced values, written *after* the slew limiter. `None` means "free": leave the regulator on its organic output |
| `emergency_by_cause`, `safe_state_by_cause` | Per-cause overrides keyed `<dim>_<high\|low>` |

The surface parameter list is frozen into an `array('f')` addressed by position,
so **appending is safe and reordering is not**.

Three things repeatedly go wrong here and are worth stating plainly:

- **A surface and its adapter's thresholds are one calibration.** The surface
  decides how command maps to deviation; `on_above` / `off_below` pick the two
  points on that curve where a relay actually switches. Re-derive both together.
- **A relay never sees a surface-level deadband.** It only ever observes the two
  switch points, so a deadband around ideal just means the contact never closes.
  Hysteresis belongs in the adapter.
- **A floor can swallow a whole ramp.** The additive CO₂ term is bounded by
  `gain * (100 − break)`; if that ceiling sits below the regulator's `floor`,
  the CO₂ reading moves nothing at all and nothing warns you.

`emergency_value: None` matters more than it looks. Pinning the cooler to 0
during a heat emergency turns the air conditioner off in the one situation it
exists for, and leaves the latch with no way to release.

### escalation and latch

Severity is `|d − 50|` and saturates the moment a reading passes an outer
anchor. A freshly set-up tent legitimately starts far from ideal, so ungated
escalation latched the system into the safe-state vector on the first tick —
with the actuators that would fix it forced off.

`escalation` therefore gates *which directions may escalate*. Only the hazardous
high side of temperature and humidity does; too cold, too dry, and any CO₂ level
are correctable conditions the surfaces handle. Floors, conflict rules and the
surfaces all still see the full ungated severity.

`latch` needs the condition to persist `enter_ticks` ticks before firing, and
releases only when every severity is ≤ `release_max` for `release_ticks`
consecutive ticks *and* `min_s` has elapsed.

### conflicts

An ordered list, evaluated at global band ≥ 30, later rules winning:

```python
{
    "when": [["humidity", "above", 0], ["temp", "above", 30]],
    "force":  {"humidifier": 0.0},
    "prefer": {"exhaust": 60.0, "cooler": 100.0},
}
```

`when` terms are AND-combined and read as *(dimension, side of 50, severity
threshold)*. `force` sets exact values; `prefer` applies `max()`. The shipped
rule is the mold-risk guard: above the temperature gate, stop adding water once
humidity reaches ideal.

## display

`enabled`, `width`, `height`, `i2c_address`, `refresh_interval_s`,
`stats_window_s`, `max_history`, `menu_timeout_s` (return to the default page)
and `display_timeout_s` (blank the panel to extend its life).

`max_render_errors` is a safety valve: after that many consecutive I²C
failures the OLED self-disables at runtime, so a dying panel cannot keep
hammering the shared bus or starve the watchdog.

`display.debug` configures the debug sub-menu — `confirm_timeout_s` for the
second-long-press confirmation on destructive actions, plus the durations and
levels used by the heater, grow-light and relay smoke tests.

## Status LEDs & buzzer

`status_leds` sets `activity_blink_ms`, `heartbeat_interval_ms`,
`sd_fault_blink_ms`, the T/H failure counts that escalate to warning and error,
the RTC plausible-year window, and `mem_warning_pct` / `mem_error_pct`.

`walk_order` is the *physical* left-to-right order of the LED row, so the
power-on self-test sweeps smoothly across the case instead of jumping in GPIO
order. Set `post_enabled: False` to skip the walk.

`buzzer` holds the tone patterns as `(freq_hz, duration_ms, pause_ms)` triples:
`startup_melody`, `error_pattern`, `alert_pattern`, `reminder_pattern`.

## Service reminder

`days_interval`, `blink_after_days` (how long overdue before the LED switches
from solid to blinking), `blink_pattern_ms`, `monitor_interval_s`, and
`storage_path` for the persisted last-serviced timestamp. Long-press the menu
button to reset.

## Storage

`buffer_manager` — `sd_mount_point`, `fallback_path`, `max_buffer_entries` (the
in-memory ring buffer cap) and `max_fallback_size_kb` (past which the oldest
fallback rows are pruned).

`event_logger` — `logfile`, `log_level`, `debug_enabled` / `debug_to_file`, the
per-severity flush thresholds, and rotation:

| Key | Notes |
| --- | --- |
| `max_size` | Rotate the active log past this size. Kept small on purpose: rotation is an atomic `os.rename`, so the active file stays tiny and rotation never blocks the watchdog feed |
| `debug_max_size` | Lower threshold used when `debug_to_file` is on, because debug output fills far faster |
| `log_retention_days` | Keep archives from the most recent N distinct dates and delete the rest after each rotation — bounds the file count in `/sd/logs` |

## Updater

`updater` drives the SD-payload OTA path:

| Key | Notes |
| --- | --- |
| `update_dir`, `applied_dir`, `log_path` | Payload in, archive out, history |
| `allowed_paths` | Whitelist. Anything outside it fails verification |
| `enforce_mpy_abi` | Refuse payloads whose declared `.mpy` ABI the running firmware cannot import. SHA-256 proves integrity, not compatibility — a mismatched payload applies cleanly and then fails every import on the next boot |
| `prune_stale` | After a successful apply, delete `.py`/`.mpy` files under the allowed roots that the payload did not ship. Without it flash is strictly additive and a leftover `lib/<mod>.mpy` shadows its frozen twin forever. The sweep only deletes where the frozen `fw_info.FROZEN_MODULES` record proves the firmware carries a replacement |
| `max_retries`, `retry_delay_ms`, `verify_max_retries`, `verify_retry_delay_ms` | Per-file resilience against SD glitches |
| `legacy_update_dirs` | Extra locations checked when the canonical directory holds no manifest |

`updater_feedback` makes an update visible without a serial console: an LED
chase across `status_leds.walk_order`, a buzzer chirp per file, and distinct
success / failure / no-op jingles before the post-apply reset.

## Diagnostics & memory

`diagnostics.mem_trend_log` writes one greppable INFO line per health cycle
(pre/post-GC heap, reclaimed churn, task count, buffer and queue depth) to
`system.log` *without* enabling debug-to-file — so a headless unit records the
slow climb toward `mem_warning_pct` for offline diagnosis.

`diagnostics.metrics_log` appends a row per cycle to
`/sd/sensors/metrics/YYYY/metrics_YYYY-MM-DD.csv`: heap, task and queue depth,
write failures, plus the engine's tick timing, severity, band, latch and
emergency flags, the three deviations and all seven commanded values. Both cost
heap — check headroom before enabling them for a long soak.

`memory.gc_threshold_b` calls `gc.threshold()` at boot so MicroPython collects
proactively instead of only on OOM, which curbs the allocation peaks behind
cold-boot framebuffer failures. `-1` restores the default. No-op on CPython.

## system

| Key | Notes |
| --- | --- |
| `watchdog_timeout_ms`, `watchdog_feed_interval_ms` | RP2040 maximum is ~8388 ms; the feed interval must stay well under the timeout |
| `require_sd_startup`, `sd_fail_reset_s` | Whether a cold-boot mount failure is fatal, and how long the LEDs hold before the reset |
| `boot_log_path`, `boot_log_max_kb` | Internal-flash mirror of boot diagnostics, readable over USB after a reset — the copy that survives an unwritable card |
| `health_check_interval_s`, `sd_recovery_interval_s` | Normal and fast health-loop cadence |
| `i2c_freq` | 100 kHz. Raised rise times with 7+ devices on 10 kΩ pull-ups made the 1 KB OLED framebuffer render time out at 400 kHz; raise it back only after the pull-ups are reworked |
| `i2c_use_soft`, `i2c_timeout_us`, `i2c_recover_on_error`, `i2c_recover_clocks` | `SoftI2C` with a bounded per-transfer timeout, plus SCL pulsing to clock a wedged slave off the bus and one retry |
| `sd_power_up_ms`, `sd_mount_retries`, `sd_retry_delay_ms` | Cold-boot SD patience; cheap cards may need more than a second |
| `write_queue_max_size`, `queue_drain_interval_ms`, `queue_batch_size` | Async SD write batching |
| `fallback_migrate_batch_max` | Caps the synchronous SD work one health-loop pass does, so a large backlog cannot exceed the watchdog timeout |
| `button_debounce_ms`, `button_poll_ms`, `long_press_ms` | Operator input timing |
| `rtc_sync_interval_s`, `rtc_min_year`, `rtc_max_year` | RTC sync cadence and the plausibility window behind the `rtc_invalid` warning |

## Output pins

`output_pins` sets the boot-time level of every output. Relay lines default
`True` (HIGH = off, including the reserved channels, so their active-low inputs
never float into a half-powered state); LEDs default `False`.

## Adding a new configurable value

1. Add the key to the right section of `DEVICE_CONFIG`, with units in the name
   (`interval_s`, `timeout_ms`, `threshold_c`, `pin`).
2. Add a `validate_config()` check asserting presence, type and a sane range.
3. Add a row to `tests/test_config.py` covering the happy path and at least one
   failure the validator catches.
4. Consume it through a constructor argument in `main.py` — never by importing
   `DEVICE_CONFIG` inside `lib/`.

Steps 1–3 ship as one commit, before the commit that consumes the value.
