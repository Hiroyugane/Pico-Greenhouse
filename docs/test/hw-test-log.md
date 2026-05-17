# Hardware test log

> Per [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md).
> Eyes-on verification steps for things `pytest` can't exercise.
> Newest entry on top. Use `[ ]` pending, `[x]` passed, `[!]` failed,
> `[~]` partial/blocked.

## 2026-05-17 · OLED SYSTEM screen shows build version

**Branch:** `main`
**Why hardware-only:** Verifies that `lib/build_info.py` actually
ships in the payload, gets imported on-device, and the new row 1
literal `Ver:<hash>` fits the 16-char OLED row without truncation
artifacts the host shim can't simulate (real SSD1306 + real font).
Also confirms the combined `YYYY-MM-DD HH:MM` on row 0 reads cleanly
from the live RTC, not just from a mocked `now_timestamp()`.
**Pre-flight:** Run `python tools/build_update_payload.py
--copy-to G:/ota/pending --no-confirm` so the working tree
contains a freshly-stamped `lib/build_info.py`. Flash via Thonny
(or let the updater run from `/sd/update/`). Note the local
`git rev-parse --short HEAD` value before booting.

### SYSTEM screen renders new layout

- [ ] After boot, short-press the menu button until SYSTEM is
  reached (sixth screen).
- [ ] Row 0 reads `YYYY-MM-DD HH:MM` (16 chars exactly), matching
  the RTC date and time.
- [ ] Row 1 reads `Ver:<hash>` where `<hash>` equals the
  7-character output of `git rev-parse --short HEAD` captured
  during pre-flight.
- [ ] Rows 2–4 still show `Up: …`, `Buf:…`, `RAM: …%` as before
  (no regressions).
- [ ] No text wraps to row 5 / no garbled characters at the right
  edge of any row.

### Notes (post-test)

> Fill in here.

## 2026-05-17 · Updater same-version short-circuit (noop jingle)

**Branch:** `main`
**Why hardware-only:** The noop short-circuit hashes every manifest
file against the live flash. Host pytest covers the logic but only
real MicroPython + a mounted SD card prove that (a) the hash path
on `_FLASH_ROOT = "/"` reads the bytes the Pico will actually
execute, (b) the new `noop` log entry lands in
`/sd/logs/updates.log`, and (c) the operator hears the new
two-blip 880 Hz chime instead of the failure descend.
**Pre-flight:** Pico flashed via `flash-mpremote` from the
current commit. SD card with payload built from the SAME commit
via `deploy-update-to-sdcard` (so `/sd/update/manifest.json`
exists and every file's SHA-256 matches what's on flash). `/sd/`
otherwise empty under `ota/`.

### Same-content payload short-circuits cleanly

- [ ] Power on. `[updater]` lines now print on USB serial: one
  `start` and one `noop`, both with the new
  `2026-05-17T<HH:MM:SS>` (or whatever the RTC says) timestamp.
- [ ] Buzzer plays the new two-blip 880 Hz noop chime — distinct
  from the success 3-note rising arpeggio and the failure 2-note
  descending tone.
- [ ] Every other LED in the chase row (positions 0, 2, 4) lights
  during the chime, not all five (success) or just the first one
  (failure).
- [ ] Pico does **not** reset — boot continues directly into
  normal operation, OLED comes up, sensors start logging.
- [ ] After boot: `/sd/update/` is gone. `/sd/ota/applied/<version>/`
  contains the payload (manifest + files).
- [ ] `/sd/logs/updates.log` last two lines: `start ...` then
  `noop <version> already up to date; files=<N>`.

### Real update (modified source) still applies + resets

- [ ] Touch a comment in `main.py`, rebuild payload via
  `deploy-update-to-sdcard` (gets new version string), insert SD,
  reboot. Success jingle plays (3-note rising), Pico resets,
  `/sd/logs/updates.log` ends with `apply_ok`. Confirms the
  short-circuit only fires on byte-identical content, not on
  every reboot.

### Diagnostic stdout fallback visible on USB

- [ ] Pull the SD card mid-boot AFTER the manifest is read but
  BEFORE finalize (tricky timing — easier: pre-fill
  `/sd/logs/updates.log` to ~50 KB so rotation can mask a write
  fault, then trigger any update). USB serial should still show
  `[updater] ...\tverify_fail\t...` even if the SD log doesn't
  capture it.

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-16 · Fan-control refactor (FanOutput + fans dict, pre-PCB)

**Branch:** `main`
**Why hardware-only:** Existing `exhaust` and `growroom_walls` fans
moved from the old `fan_1` / `fan_2` config keys to a role-keyed
`fans` dict, with the wiring loop in `main.py` rewritten to dispatch
on `mode` and `output`. Behavior on current PCB is intended to be
identical — these checks confirm that.
**Pre-flight:** Current-rev PCB (no PCA9685 yet). `pca9685.enabled
= False` (default). Both relay fans wired to GP18 / GP19 via
REL_CON. RTC + SD healthy. CO2 sensor connected if you want to
verify the override path.

### Boot sanity

- [ ] Boot the device. Console logs `[STARTUP] Configuration
  validated` (no `co2_logger.override_fan` complaint about
  `exhaust`).
- [ ] `system.log` shows `Fan controllers initialized` and a
  `Step 7a fans` debug line listing `['exhaust', 'growroom_walls']`
  (the three pca9685 fans skipped with `fan disabled in config`
  debug lines).
- [ ] No `Fan ... uses pca9685 but driver unavailable` warning
  (the three pca9685 fans are `enabled: false`, so the wiring loop
  skips them before reaching the pca9685 check).

### Relay behavior unchanged

- [ ] Force `exhaust` thermostat by warming the SHT31 above
  `max_temp` (23.8 °C). REL_CON pin 2 (GP18) clicks ON within
  `poll_interval_s` (5 s). Log entry: `FanController exhaust
  THERMOSTAT ON at ...`.
- [ ] Cool back below the hysteresis threshold (23.3 °C). Same fan
  clicks back to schedule control inside one poll. Log entry:
  `THERMOSTAT RESUME SCHEDULE`.
- [ ] Repeat for `growroom_walls` (REL_CON pin 3 / GP19,
  max_temp 27.0 °C).

### CO2 override (only if sensor connected)

- [ ] Breathe on / cover the CO2 sensor until ppm > 1000. The
  `exhaust` fan force-on event lands in `system.log` as
  `EXTERNAL OVERRIDE ON`. REL_CON pin 2 stays closed for the full
  override window even when the thermostat is idle.
- [ ] When ppm drops below 800, log shows `EXTERNAL OVERRIDE
  RELEASE` and the fan returns to schedule control. Verify on
  REL_CON pin 2.

### Future PCA9685 turn-on (defer until new PCB)

- [ ] Wire PCA9685 to I2C0 at 0x40 alongside RTC/OLED/MCP4725.
- [ ] Flip `DEVICE_CONFIG["pca9685"]["enabled"] = True`.
- [ ] Flip per-fan `enabled` to True for `growroom_center`,
  `heater_distribution`, `case`.
- [ ] Flip `exhaust` / `growroom_walls` `output` from `"relay"` to
  `"pca9685"` and add `pca9685_ch` entries.
- [ ] Confirm: each fan responds to its assigned channel at
  configured duty; case fan holds 60 % from boot; heater
  distribution kicks on the heater MOSFET and stays on for
  `post_run_s` (60 s default) after the heater drops.

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-16 · OLED debug actions sub-menu

**Branch:** `main`
**Why hardware-only:** Each action drives a real relay, MOSFET gate,
or DAC and is observed by ear (relay click), thermometer (heater
gate), or eye (growlight on/off, dim ramp). Wipe also affects the
mounted SD card.
**Pre-flight:** SD card mounted with at least one fallback row in
`/local/fallback.csv` (let the device run with the card briefly
ejected and reinserted to populate). System.log file present at
`/sd/logs/system.log`. Heater MOSFET wired to GP3. Growlight relay
on GP20; MCP4725 at 0x60 if the dim-sweep action is to be tested.
RTC + I2C0 healthy (POST passes).

### Navigation into the debug sub-menu

- [ ] Short-press the menu button until the OLED shows the `DEBUG`
  header with `Hold to enter` / `[HOLD]=open` hint.
- [ ] Long-press (≥3 s). Display switches to `> Wipe logs` with
  `1/N` page indicator and `[HOLD]=run` hint.
- [ ] Short-press cycles through every entry: `Wipe logs`, `Cycle
  relays`, `Heater 5s`, `Light pulse`, and `Dim sweep` (only if
  MCP4725 is wired). Page indicator updates each press.
- [ ] Stop pressing for `menu_timeout_s` (default 30 s); display
  returns to the temperature menu and the debug sub-menu state is
  cleared (next entry restarts at action index 0).

### Wipe logs — two-step confirm

- [ ] Long-press while on `Wipe logs`. Display shows `CONFIRM?` and
  `TAP=cancel`; the `[HOLD]` hint reads `[HOLD]=YES`.
- [ ] Short-press; confirm clears, status line shows `cancelled`,
  fallback.csv and system.log untouched.
- [ ] Long-press again, long-press a second time within ~8 s. Status
  briefly shows `RUNNING...`, then `done`, reminder LED plays the
  feedback blink pattern.
- [ ] After wipe: `/sd/logs/system.log` is gone (or recreated empty
  by the next EventLogger flush), `/local/fallback.csv` is gone, and
  any in-memory buffered sensor entries are dropped. Sensor CSVs
  under `/sd/sensors/**` are untouched.

### Cycle relays — audible click on each output

- [ ] Long-press `Cycle relays`. Listen: relay 1 clicks ON, ~1 s
  later clicks OFF; relay 2 clicks ON, then OFF; growlight relay
  clicks ON, then OFF. Each fan scheduler resumes its normal state
  on its next poll (≤ poll_interval_s).
- [ ] Reminder LED plays the feedback blink at completion; OLED
  status shows `done`.

### Heater 5 s

- [ ] Long-press `Heater 5s`. Heater MOSFET gate goes HIGH for
  5 s; heating element warms perceptibly (or measure with a probe).
- [ ] After 5 s, gate returns LOW; OLED status shows `done`.

### Growlight tests

- [ ] Long-press `Light pulse`. Growlight relay closes for 2 s, then
  opens. If MCP4725 is wired, brightness is `default_level_pct`
  during the pulse.
- [ ] (DAC builds only) Long-press `Dim sweep`. Growlight ramps
  through 0 → 25 → 50 → 75 → 100 → 0 % with ~1 s dwell at each
  step. Final state: relay open, DAC at 0.

### Resilience

- [ ] During any action (e.g. heater 5 s), press the button. Display
  shows `RUNNING...` and ignores the press; no second action starts.
- [ ] During an action, leave the system idle past
  `menu_timeout_s`. The display does NOT exit debug mode mid-action;
  it only exits once the action has finished.

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-16 · Updater legacy update_dir fallback applies

**Branch:** `main`
**Why hardware-only:** Update payload detection runs against the
mounted SD on a real Pico — host pytest covers the path-selection
logic but not the actual boot-time mount + apply + reset sequence on
a card with the legacy `/sd/update/` layout.
**Pre-flight:** SD card has a valid payload (manifest.json + files)
at `/sd/update/` from a previous `tools/build_update_payload.py
--copy-to G:/update` run. `/sd/ota/pending/` is empty or absent.
Pico flashed with this commit's `lib/updater.py` and `config.py`.

### Legacy payload at /sd/update is detected and applied

- [ ] Insert SD with legacy `/sd/update/manifest.json` present;
  power-cycle the Pico.
- [ ] LED loading-chase + buzzer ticks run (updater_feedback) during
  verify/apply — confirms the payload was detected, not skipped.
- [ ] Pico resets and the success jingle plays.
- [ ] After reboot, pull the card: `/sd/update/` is gone,
  `/sd/ota/applied/<version>/` contains the manifest + files.
- [ ] `/sd/logs/updates.log` last line for that version contains
  `payload detected at legacy /sd/update` followed by `apply_ok`.

### Canonical wins over legacy when both are present

- [ ] Build a second payload, copy it to `G:/ota/pending/`. Leave the
  old legacy directory in place with its own manifest (different
  version string).
- [ ] Power-cycle. The canonical payload should be the one that
  applies; `/sd/logs/updates.log` should NOT say `at legacy`.
- [ ] `/sd/update/` still present after reboot; `/sd/ota/pending/`
  consumed into `/sd/ota/applied/<canonical-version>/`.

### Empty list disables fallback

- [ ] Edit `config.py` on the Pico: set
  `updater.legacy_update_dirs = []`. Reboot.
- [ ] With payload only at `/sd/update/`, Pico boots normally (no
  jingle, no reset). `/sd/update/` untouched.

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-15 · /boot.log captures SD diagnostics without USB serial

**Branch:** `main`
**Why hardware-only:** `lib/boot_log.py` writes to the Pico's
internal flash; the only way to read it back is to mount the Pico as
USB MSC (or open Thonny's file browser) after a boot. Pytest covers
the write logic but not the over-USB retrieval path.
**Pre-flight:** Pico flashed with the latest `lib/`, `main.py`,
`config.py`. Defaults in play (`boot_log_path=/boot.log`,
`boot_log_max_kb=10`).

### /boot.log appears and contains SD-diagnostic lines

- [ ] Power-cycle the Pico with NO SD inserted (hard-fail loop).
  After a few reset cycles, unplug from power, plug into a host as
  USB MSC, open `boot.log` at the device root.
- [ ] File contains `[HardwareFactory] SD mount attempt 1/3...`,
  the `reset SPI/mount and retry` lines, `All mount_sd attempts
  failed; trying is_mounted fallback`, and the final `[SD] Mount
  failed at /sd: <reason>` line (the actual error string).
- [ ] File size ≤ 10 KB.

### /boot.log truncates per boot

- [ ] Read `/boot.log` after one failed boot (e.g. 6 lines).
- [ ] Power-cycle without SD again. Read `/boot.log` after the new
  boot — the file is again ~6 lines (NOT 12). First write per boot
  truncates.

### Notes (post-test) — boot_log

> Fill in here.

## 2026-05-15 · Boot SD mount recovery + hard-fail behavior

**Branch:** `main`
**Why hardware-only:** the cold-boot SD mount path is exactly what
pytest cannot exercise — `sdcard.SDCard()` over real SPI to a real
FAT32 card with a real power-up sequence. The SPI-reinit-between-retries
fix only proves itself on the bench, and the new sd+error LED hold +
`machine.reset()` countdown is observable only on hardware.
**Pre-flight:** Pico booted standalone (USB power, no Thonny), SD
card inserted before power-on, `system.require_sd_startup=True`
(default), `system.sd_fail_reset_s=10` (default).

### Cold-boot mount succeeds on a normal card

- [ ] Power-cycle with a healthy card seated. Console prints
  `[HardwareFactory] SD mounted` on attempt 1 (or, at worst, attempt
  2 with a `reinit SPI and retry` line in between).
- [ ] After POST walk, the sd_led (GP5) is **off** and stays off.

### Cold-boot mount recovers via SPI reinit on a flaky card

- [ ] Reseat the SD connector loosely (or use the known-slow card)
  and power-cycle. Watch console: first mount attempt fails, a
  `reinit SPI and retry` line appears, then a later attempt succeeds.
- [ ] sd_led off after POST.

### Hard-fail path: SD missing at boot

- [ ] Power-cycle with no SD inserted. After ~1-2s of setup, sd_led
  (GP5) **and** error_led (GP7) light SOLID. Console prints
  `[STARTUP ERROR] SD card required but not mounted. Resetting in 10s...`.
- [ ] The two LEDs stay lit for ~10s, then the Pico resets (POST
  walk re-runs from the top). No watchdog reset before the countdown
  expires.

### Hard-fail path: SD missing with require_sd_startup=False

- [ ] Edit `config.py` to set `system.require_sd_startup=False`,
  reflash, power-cycle without SD. System boots all the way through
  POST and into the menu loop. sd_led is solid (SD missing) but
  error_led is OFF (no hard-fail).
- [ ] Insert SD, long-press the menu button → SD remount succeeds,
  sd_led goes dark, normal operation resumes.

### Notes (post-test) — SD mount recovery

> Fill in here.

## 2026-05-15 · SD card layout refactor — verify writes land in new tree

**Branch:** `main`
**Why hardware-only:** real FAT32 on the SD card may behave differently
from the host shim — in particular, recursive `mkdir` on missing
intermediate dirs (`sensors/co2/2026/`) and the Updater's log-rotation
rename across `/sd/logs/` are only fully exercised against the real
VFS. Pytest covers the path math; only the device proves the writes
hit the card.
**Pre-flight:** boot the Pico with a freshly inserted SD card that
**does not** already have a `sensors/`, `logs/`, `ota/`, or
`diagnostics/` directory. RTC must be set so daily-rotated filenames
have correct dates.

### Sensor CSVs land under `sensors/<type>/YYYY/`

- [ ] After ~2 minutes uptime,
  `/sd/sensors/th/<YYYY>/th_<YYYY-MM-DD>.csv` exists and has a
  `Timestamp,Temperature,Humidity` header followed by readings.
- [ ] After ~2 minutes uptime,
  `/sd/sensors/co2/<YYYY>/co2_<YYYY-MM-DD>.csv` exists with rows
  (sensor connected) or no file (sensor absent — verify no traceback
  in console).
- [ ] In **plant** mode, `/sd/sensors/soil/<YYYY>/soil_<YYYY-MM-DD>.csv`
  exists. In **mushroom** mode, the `soil/` folder is absent.
- [ ] The legacy root files (`/sd/th_log_*.csv`, `/sd/co2_log_*.csv`,
  `/sd/soil_log_*.csv`) are **not** modified or recreated.

### System + updates logs land under /sd/logs/

- [ ] `/sd/logs/system.log` exists and grows after a deliberate
  warning (e.g. unplug SD briefly to trigger fallback path).
- [ ] After a manual size-rotation trigger (artificially seed a
  large `/sd/logs/system.log`), a `system_<ts>.log` appears in the
  same dir and `system.log` restarts at 0 bytes.
- [ ] OTA payload drop into `/sd/ota/pending/` is detected at next
  boot, applied, and renamed under `/sd/ota/applied/<version>/`.
- [ ] `/sd/logs/updates.log` records each attempt; after seeding a
  pre-existing >50 KB file, the next OTA event rotates it to
  `updates_<ts>.log`.

### hw_probe diagnostics land under /sd/diagnostics/

- [ ] `prototypes/hw_probe.py` writes its JSON to
  `/sd/diagnostics/hw_probe_<ts>.json`. Old top-level
  `/sd/hw_probe_*.json` files are untouched.

### Notes (post-test) — SD layout refactor

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-15 · Relay diagnostic tool — investigate random boot behavior

**Branch:** `main`
**Why hardware-only:** the symptom is "relay behavior seems random,
especially when restarting" — only a physical bench run can verify
which relays click on at boot, whether any latch oddly, and whether
the all-on phase triggers a brownout. `pytest` can't observe the
relay coils or the module's power rail.
**Pre-flight:** Pico powered, full relay board connected through
REL_CON, 5V supply to the relay module verified. No actuators (fans,
grow light) need to be plugged into the relay outputs — listening
for the click and watching the indicator LEDs is sufficient.

### Pre-bring-up: upload script

- [x] `tools/relay_diag.py` uploaded to Pico via Thonny.
- [x] Run it standalone (not via `main.py`).

### Phase 1 — float-state probe

- [x] **GP27 reads raw=0** — floats LOW persistently. All other six
  GPIOs read raw=1. GP27 is the cause of `reserved_4` (REL_CON 8)
  clicking on at every reset.
- [x] Observations recorded per-pin below in Notes.

### Phase 2 — drive all HIGH

- [x] All relay module indicator LEDs go dark immediately after the
  phase-2 banner prints. Confirms that once MicroPython drives the
  pins, every channel is held off correctly.

### Phase 3 — per-relay sweep

- [x] GP18 fan_1     — clean single click on/off.
- [x] GP19 fan_2     — clean.
- [x] GP20 growlight — clean.
- [x] GP21 reserved_1 — clean.
- [x] GP22 reserved_2 — clean.
- [x] GP26 reserved_3 — clean.
- [x] GP27 reserved_4 — clean.

### Phase 4 — all-on stress

- [x] All 7 LEDs energize together. No Pico reset, no USB
  re-enumeration, no spurious extra clicks. Power rail holds under
  full coil load.

### Phase 5 — settle

- [x] All relays off at end. Tree clean.

### Notes (post-test)

The runtime path (Phases 2–5) is healthy — when MicroPython is
actively driving the pins, every relay behaves correctly. **All
remaining issues are in the un-driven windows: hardware reset
transient and REPL idle.**

- `[!]` **GP27 / REL_CON 8 / `reserved_4`** — Phase 1 shows
  persistent `raw=0`. The line floats LOW out of reset, fires the
  relay every restart. Cannot be fixed in firmware (window is
  pre-MicroPython). Needs external pull-up — tracked in
  [`pcb-revision-changes.md`](../notes/pcb-revision-changes.md).
- `[!]` **GP26 / REL_CON 7 / `reserved_3`** — user observed it
  activating during 3V3_EN reset, but Phase 1 reports raw=1.
  Interpretation: the line dips low transiently during the boot
  window and latches the relay, then drifts back high before
  MicroPython runs the probe. Same fix as GP27.
- `[!]` **REL_CON 8 channel (the unwired 8th)** — user observed it
  enabling on 3V3_EN reset despite (intended) 3V3 tie. Either the
  3V3 strap is not actually connected or the module variant on the
  bench is active-HIGH on that channel. Needs metering on next
  bench session; entry in `pcb-revision-changes.md` to either pull
  it up explicitly or wire it to a GPIO.
- `[~]` **REPL idle dim-LED on all 7 channels** — classic
  high-impedance floating-input signature. The Pico's GPIOs are
  inputs (high-Z) whenever MicroPython hasn't taken ownership; the
  relay module's IN line sits in the ~0.8–2.0V band, half-lights
  the indicator LED but is above the coil threshold. External
  pull-ups eliminate this entirely.
- `[x]` **Runtime path** — Phases 2–5 fully passed. No
  neighbour-activity (no channel transition disturbing another),
  no brownout under all-on stress. Confirms the firmware-side
  inverted-relay handling in [`lib/relay.py`](../../lib/relay.py)
  and [`config.py:296-304`](../../config.py#L296-L304) is correct.
- **Action items:** see
  [`docs/notes/pcb-revision-changes.md`](../notes/pcb-revision-changes.md)
  for the two PCB-revision entries opened from this session.

## 2026-05-15 · Capacitive soil sensor replacement bring-up

**Branch:** `main`
**Why hardware-only:** verifying a real moisture probe requires
physically moving the probe through air → soil → water and reading
GP28; `pytest` cannot exercise the ADC, the 555 oscillator, or the
sensor's capacitive plate.
**Pre-flight:** Replacement TLC555/7555-class capacitive sensor in
hand (NE555 units do not start at 3V3 — see chat-log entry of this
date). 6.8 k + 10 k divider from the previous attempt **removed**.
Pico powered cold via USB; Thonny REPL connected; multimeter on
hand. Confirm the silkscreen chip marking before powering up — if it
reads `NE555` / `LM555` / plain `555`, stop and source a different
unit.

### Wiring verification (before first power-up)

- [ ] Sensor VCC → Pico pin 36 (3V3 OUT). **Not** pin 35 (ADC_VREF);
      ADC_VREF cannot source a sensor's load and corrupts every ADC
      channel.
- [ ] Sensor GND → any Pico GND (pin 33 / 38 / 23 / etc.).
- [ ] Sensor AOUT → Pico pin 34 (GP28 / ADC2) directly. No divider.
- [ ] DMM between VCC and GND at the sensor header reads
      3.30 V ± 0.05 V after the Pico boots.
- [ ] DMM between AOUT and GND at the sensor header reads roughly
      2.0–2.5 V with the probe held in dry air. If it reads ~0 V,
      stop — the new sensor is also bad or wired wrong.

### `print_raw()` calibration sweep

Run each step from the Thonny REPL with
`from lib.soil_logger import print_raw; print_raw()`. Wait ~5 s
between moves so the RC filter on the sensor settles.

- [ ] **Air (dry reference):** probe held in still air, away from
      hands. Record raw value: __________. Expected: 700–900 range.
- [ ] **Moist soil:** probe inserted into a freshly watered potting
      mix up to the printed fill line. Record: __________. Expected:
      400–600 range, clearly below the air value.
- [ ] **Tap water:** white PCB blade submerged to (but not past) the
      printed line. Record: __________. Expected: 300–450 range,
      clearly below the moist-soil value.
- [ ] All three readings differ by ≥ 100 raw counts between
      neighbouring states (otherwise calibration won't be useful).
- [ ] With the probe stationary in any one state, repeated
      `print_raw()` calls vary by ≤ 5 counts (no floating-pin jitter).

### Config + system verification

- [ ] Update [config.py:151-152](../../config.py#L151-L152):
      `adc_dry_raw` ← air reading, `adc_wet_raw` ← water reading.
- [ ] `pytest tests/test_config.py -v` passes after the edit (validator
      still happy with the new values).
- [ ] Reboot the Pico into `main.py`. Within 60 s a new row appears
      in `/sd/soil_log_YYYY-MM-DD.csv` (or the BufferManager fallback)
      with a plausible `Raw,Percent` pair.
- [ ] Pour water into the pot near the probe; the next logged row
      shows `Percent` rising toward 100. Withhold water for several
      cycles; `Percent` falls.
- [ ] When `Percent < warn_pct_below` (default 20), the warning LED
      lights via `StatusManager`; clearing the condition turns it off.

### Notes (post-test) — soil sensor replacement

> Fill in here. Record the three calibration raw values, any
> per-state jitter observed, and the sensor model + chip marking of
> the unit that finally worked.

## 2026-05-15 · Reserved relay GPIOs parked HIGH + REL_CON 3V3 fault

**Branch:** `main`
**Why hardware-only:** the floating GPIO symptom is an analog
voltage on the relay board's input pins; `pytest` can prove the
config plumbing but only a multimeter (or watching the relay LEDs)
confirms the inputs sit at a clean 3V3 instead of the prior
half-powered state. The REL_CON 3V3 supply complaint is pure
hardware — no software fix exists.
**Pre-flight:** Pico powered cold via USB; relay board connected to
REL_CON; multimeter ready; nothing wired to the four reserved
channels (REL_CON pins 5–8).

### Reserved relay channels (GP21, GP22, GP26, GP27)

- [ ] On boot, measure GP21/GP22/GP26/GP27 to GND with a multimeter:
      each should read a clean ≈3.3 V (HIGH, relay off). No
      intermediate "half-power" reading (>0.4 V, <2.7 V) anywhere.
- [ ] Relay-board LEDs (if present) for those four channels stay
      OFF — no flicker, no dim glow.
- [ ] Touch each of the four GPIO pads with a finger; the reading
      and relay state must not change (proves the pins are driven,
      not floating).

### REL_CON 3V3 supply

- [!] REL_CON 3V3 pin reads 0 V — relay board appears unpowered on
      the logic side. Check:
  - [ ] Continuity from REL_CON 3V3 pin → Pico 3V3(OUT) pin 36.
  - [ ] Series resistor / trace between REL_CON 3V3 and the Pico
        rail (visual + DMM continuity).
  - [ ] Relay board's JD-VCC ↔ VCC jumper position (opto-isolator
        common). If using external relay-coil supply, JD-VCC
        jumper must be **removed** and JD-VCC fed externally; if
        powering coils from Pico 3V3 (not recommended past 1
        relay), jumper must be **installed**.
  - [ ] No shorted decoupling cap on the relay board's VCC pin.

### Notes (post-test) — reserved relays + 3V3 fault

> Fill in here after bench-checking. Record DMM readings per channel.

## 2026-05-15 · SD-update loading screen LEDs + buzzer jingles

**Branch:** `main`
**Why hardware-only:** the loading animation and end-state jingles are
purely sensory — `pytest` proves the feedback hooks fire at the right
points, but only eyes/ears verify the chase is visible, the ticks are
audible, and the success/fail tones are distinguishable.
**Pre-flight:** Pico powered cold; a valid signed payload staged under
`/sd/update/` with `manifest.json` (use `tools/build_update_payload.py`);
`updater.enabled=True` and `updater_feedback.enabled=True` in
`config.py`. Have a deliberately corrupt manifest on hand for the
failure run.

### Successful update

- [ ] Cold-boot with the valid payload present. While verify + apply
      runs, the LED row sweeps left↔right in a cylon chase across
      activity → sd → reminder → warning → error, with a short chirp
      audible on each per-file step.
- [ ] On `apply_ok`, all five status LEDs light briefly while the
      buzzer plays a rising 3-note arpeggio (≈ C6 → E6 → G6), then the
      Pico reboots into the new code.

### Failed verify

- [ ] Cold-boot with a payload whose `manifest.json` has a sha256 that
      doesn't match its file. The chase runs through the verify phase,
      stops, and the buzzer plays a descending 2-note fail tone
      (≈ 400 Hz → 250 Hz). The Pico does **not** reboot; normal boot
      proceeds and the next health-check log line shows the failure.

### Disabled feedback

- [ ] Set `updater_feedback.enabled = False`, redeploy, cold-boot with
      a valid payload. The update still applies and the Pico reboots,
      but the LED row stays dark and the buzzer is silent during the
      whole update window.

### Notes (post-test) — updater feedback

> Fill in here.

## 2026-05-15 · POST LED walk follows physical row order

**Branch:** `main`
**Why hardware-only:** the walk order is purely a visual matter — the
sequence the operator sees on the LED_CON row at boot. `pytest`
verifies the configured order maps to the right LED instances, but
not that the physical sweep looks like a left-to-right scan.
**Pre-flight:** Pico powered cold, all five status LEDs visible in
the row, `config.py` at defaults (`status_leds.walk_order =
["activity", "sd", "reminder", "warning", "error"]`).

### Default order

- [ ] Cold-boot the Pico. The status LEDs light one at a time, left
      to right, in order: green (activity) → blue (sd) → white
      (reminder) → yellow (warning) → red (error), then the on-board
      heartbeat LED pulses last.
- [ ] After the walk, all status LEDs flash on together, then go
      dark.

### Reordered walk

- [ ] Set `status_leds.walk_order = ["error", "warning", "reminder",
      "sd", "activity"]` in `config.py`, redeploy, cold-boot. The
      walk now runs right-to-left across the row; heartbeat still
      pulses last.

### Notes (post-test) — POST walk

> Fill in here.

## 2026-05-15 · OLED warmup delays now configurable

**Branch:** `main`
**Why hardware-only:** the warmup sequence (`vram_clear_delay_s`,
`invert_delay_s`, `startup_banner_s`) exists to mask SSD1306 power-on
garbage pixels and to show the "Pi Greenhouse / Ready!" banner.
Host pytest can't tell whether shorter delays leave visible artifacts
or whether the banner is readable.
**Pre-flight:** Pico powered cold, OLED visible, `config.py` at
defaults (banner 2.0 s, vram delay 0.05 s, invert delay 0.1 s).

### Default delays (regression check)

- [ ] Cold-boot the Pico. Banner "Pi Greenhouse / Ready!" appears
      and stays visible for ~2 s before the first menu renders.
- [ ] No garbage pixels persist past the boot sequence.

### Tuned-down delays

- [ ] Set `display.startup_banner_s = 0.5` in `config.py`, redeploy,
      cold-boot. Banner flashes briefly, menu still renders cleanly.
- [ ] Set all three delays to `0`, redeploy, cold-boot. Note in
      Notes whether garbage pixels are visible (this is the failure
      mode the delays were originally added to mask).

### Notes (post-test)

> Fill in.

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
