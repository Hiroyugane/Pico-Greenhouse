# Hardware test log

> Per [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md).
> Eyes-on verification steps for things `pytest` can't exercise.
> Newest entry on top. Use `[ ]` pending, `[x]` passed, `[!]` failed,
> `[~]` partial/blocked.

## 2026-05-31 · HPA mist-solenoid driver bring-up (PCA9685 ch5 + 12 V valve connector)

**Branch:** `main`
**Why hardware-only:** the ch5 IRLZ44N low-side stage, the 12 V valve
connector, the flyback clamp, and PWM current-hold behaviour need the
rebuilt PCB and a physical 12 V solenoid — `pytest` can't exercise any of
it. Background in
[chat-log.md](../notes/chat-log.md#2026-05-31--hpa-mist-solenoid-pwm-breakout-connector)
and the
[next-revision Schematic entry](../hardware/next-revision.md#--hpa-mist-solenoid-driver--pca9685-ch5--irlz44n-broken-out-as-a-plug-in-12-v-valve-connector).

**Pre-flight:**

1. New PCB with the ch5 IRLZ44N stage populated (150 Ω gate R, 10 kΩ
   gate pull-down, UF4007 across the connector pads) and the 2-pin
   `HPA SOLENOID 12V` connector fitted.
2. PCA9685 present and `pca9685.enabled = True`; firmware with the
   `hpa_solenoid` config section + `lib/hpa_solenoid.py` shipped.
3. A 12 V DC solenoid (or a 12 V coil / lamp dummy load) on hand.
4. A meter on the 12 V rail current. Pico powered cold, Thonny connected.

### Boot-state safety gate (do first)

- [ ] With firmware running but before the first commanded burst (or with
      `hpa_solenoid.enabled = False`), the valve stays **OFF** through
      power-up and reset — the 10 kΩ gate pull-down holds the MOSFET off
      while the PCA9685 initialises. No mist on boot.

### Drive + flyback

- [ ] Command ch5 to 100 % duty: solenoid pulls in / dummy load
      energises; drain pulls to ~0 V. Command 0 %: load de-energises.
- [ ] Scope the drain on de-energise: the inductive kick is clamped near
      12 V + Vf (UF4007 conducting), no high-voltage spike. Record peak:
      __________ V.

### PWM current-hold

- [ ] Pull-in at 100 % then drop to `hold_duty_pct`: the valve stays
      open and the 12 V rail current falls to the hold fraction. Record
      pull-in vs hold current: __________ A / __________ A.
- [ ] Coil temperature after 10 min holding is comfortably below its
      datasheet max (confirms the hold duty is doing its job).

### Connector / polarity

- [ ] `HPA SOLENOID 12V` connector is keyed so a reversed plug is
      mechanically prevented (a reversed plug would forward-bias the
      flyback into a near-short on the 12 V rail).
- [ ] Mist-cycle timing (`burst_ms` / `interval_s`) fires the expected
      on/off pattern over a 10 min observation.

### Notes (post-test)

> Fill in here.

## 2026-05-31 · Hydroponics monitoring bring-up (I²C1 + DS18B20 + pH/EC)

**Branch:** `main`
**Why hardware-only:** the second I²C bus on repurposed GP26/GP27,
the 1-Wire water-temp bus, and the Atlas EZO probe chemistry can't
be exercised by `pytest` — they need the rebuilt PCB (R16/R17
removed, 3V3 pull-ups added, I²C1 + 1-Wire jacks), the physical
probes, and calibration solutions. Background in
[chat-log.md](../notes/chat-log.md#2026-05-31--hydroponics-monitoring-expansion-dwc--hpa-aeroponics)
and the
[next-revision Schematic entry](../hardware/next-revision.md#--hydroponics-monitoring--2nd-ic-bus-ds18b20-phec-wet-system-relays).

**Pre-flight:**

1. New PCB in hand with **R16/R17 deleted** and **GP26/GP27 pull-ups
   to 3V3** fitted. Confirm with a meter: GP26/GP27 idle at ~3.3 V,
   **not** 5 V, before connecting any probe.
2. GP2_CON power pin re-pointed **+5 V → +3V3**; 4.7 kΩ GP2→3V3
   fitted.
3. Firmware with I²C1 init + `water_temp_logger` / `ph_logger` /
   `ec_logger` shipped (lands with the PCB). If not, stop.
4. Atlas EZO-pH + EZO-EC each behind an inline voltage isolator;
   pH 4.0/7.0/10.0 and EC 1413 µS/12880 µS calibration solutions on
   hand.
5. DS18B20 probe(s) wired to the 1-Wire jack. Pico powered cold,
   Thonny REPL connected.

### Pin-safety gate (do first)

- [ ] With probes **unplugged**, measure GP26 and GP27 to GND: both
      ~3.3 V (pull-up to 3V3 confirmed). A 5 V reading means R16/R17
      were not removed — **do not proceed**, the bus will damage the
      Pico.

### I²C1 bus discovery

- [ ] `machine.I2C(1, sda=Pin(26), scl=Pin(27), freq=400000).scan()`
      returns the EZO addresses (0x63 pH, 0x64 EC). Confirm I²C0
      `scan()` is unchanged (no cross-talk between buses).

### DS18B20 water temperature

- [ ] 1-Wire enumeration returns one ROM per fitted probe.
- [ ] Reservoir probe reads within ±1 °C of a reference thermometer
      in the same water. Record: __________ °C.
- [ ] Probe ROM → role map recorded in `DEVICE_CONFIG`
      (`water_temp_logger`).

### Water-level switch (monitor-only, GP22 / REL_CON pin 6)

- [ ] Float wired to **REL_CON pin 6 (GP22) + GND**, not a relay
      module; **GP28/ADC2 left unconnected** (kept free).
- [ ] With the float in the **dry/low** position, `Pin(22, Pin.IN)`
      reads the expected level; moving the float to the **wet/high**
      position flips it. Record which physical state closes the contact
      (NO vs NC): __________.
- [ ] GP22's relay pull-up (moved to 3V3 per item 1b) holds the line
      HIGH with the float open — confirm no extra 10 kΩ was needed.
- [ ] `DEVICE_CONFIG["water_level_monitor"]` `active_low` / `alarm_on`
      set so the *intended* alarm condition (reservoir low) is the one
      that fires — verify by emptying/raising the float, not by trusting
      the datasheet polarity.
- [ ] Chatter test: wiggle the float at the threshold; the software
      debounce (`debounce_ms`) suppresses a storm of toggles — at most
      one alarm edge logged.
- [ ] Alarm surface: low-water condition raises the buzzer/LED and
      writes an `EventLogger` row; restoring level clears the alarm and
      logs the recovery edge.
- [ ] **No actuation:** confirm the level switch firing does **not**
      drive any relay/pump/solenoid (monitor-only by design).

### pH / EC (monitor-only)

- [ ] EZO-pH reads ~7.0 in pH 7.0 buffer after calibration; ~4.0 and
      ~10.0 in the other buffers. Record: __________.
- [ ] EZO-EC reads ~1413 µS and ~12880 µS in the standards. Record:
      __________.
- [ ] Temperature compensation: feed the DS18B20 reading to both EZO
      circuits; readings shift correctly with water temp.
- [ ] **Ground-loop check:** with the air pump + heater running and
      both probes in the reservoir, pH/EC readings stay stable
      (≤0.05 pH, ≤2 % EC jitter). Instability ⇒ isolator missing or
      a second grounded object in the water.

### Mains safety (verify before unattended run)

- [ ] Air pump / heater / HPA-pump circuit trips on the RCD test
      button (or PRCD adapter fitted and tested).
- [ ] Drip loops present on all reservoir-entry cables.

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-26 · Adafruit STEMMA #4026 soil sensor bring-up

**Branch:** `main`
**Why hardware-only:** I²C device discovery, capacitive moisture
range, and probe-temperature correlation all require the physical
sensor plus actual potting mix and tap water. `pytest` cannot
exercise the Seesaw register interface or the moisture plate.
Supersedes the 2026-05-15 analog-replacement checklist further
down this file (NE555 → TLC555 swap was abandoned in favour of
this I²C part). Background in
[chat-log.md](../notes/chat-log.md#2026-05-26--soil-sensor-swap--adafruit-stemma-4026-i2c).

**Pre-flight:**

1. Adafruit STEMMA #4026 in hand. Confirm silkscreen reads
   `STEMMA Soil` (and an ATSAMD10 D-chip is visible) — generic
   capacitive probes do not work with this checklist.
2. Address-select jumpers in default (open) position → address
   0x36.
3. Firmware rewrite of `lib/soil_logger.py` to the Seesaw I²C
   driver has shipped (separate commit, lands with the new PCB).
   If the rewrite has not yet shipped, stop — running the legacy
   ADC-based logger against a missing GP28 probe will just log
   noise.
4. Sensor wired into one of the outward-facing RJ12 / I²C drops:
   3V3, GND, SDA, SCL. New PCB or jumpered onto an existing drop
   for bench validation.
5. Pico powered cold via USB, Thonny REPL connected.

### I²C bus discovery

- [ ] Run an `i2c.scan()` from the REPL. Expect 0x36 to appear
      alongside the existing 0x3C (OLED), 0x44 (SHT31), 0x60
      (MCP4725), 0x68 (DS3231) — and 0x40 once PCA9685 lands.
- [ ] If 0x36 collides with anything else on the bus, jumper one
      of the address-select pads to move the STEMMA to 0x37 / 0x38
      / 0x39 and update `DEVICE_CONFIG["soil_logger"]["i2c_address"]`
      accordingly.

### Capacitive moisture sweep

Use the new REPL helper (the Seesaw-rewrite commit adds it; expect
something like `from lib.soil_logger import print_raw; print_raw()`
returning the Seesaw raw count, **higher = wetter**).

- [ ] **Air (dry reference):** probe held in still air, away from
      hands. Record raw: __________. Expected: 200–400.
- [ ] **Moist soil:** probe inserted into a freshly-watered potting
      mix up to the printed line. Record: __________. Expected:
      700–1100, clearly above the air value.
- [ ] **Tap water:** probe blade submerged to the line, not past.
      Record: __________. Expected: 1200–1600, clearly above the
      moist-soil value.
- [ ] All three readings differ by ≥ 200 raw counts between
      neighbouring states.
- [ ] With the probe stationary, repeated reads vary by ≤ 5 counts.

### Probe temperature sanity

- [ ] Read the Seesaw temperature register at room temp; record:
      __________ °C. Expected: within ±5 °C of the SHT31 reading on
      the same I²C bus (the Seesaw temperature is the chip die, not
      the soil itself — coarse check only).

### STEMMA config + system verification

- [ ] `DEVICE_CONFIG["soil_logger"]["seesaw_dry_raw"]` ← air reading.
- [ ] `DEVICE_CONFIG["soil_logger"]["seesaw_wet_raw"]` ← water reading.
      Validator inequality: `seesaw_wet_raw > seesaw_dry_raw`
      (inverted from the legacy resistive convention).
- [ ] `pytest tests/test_config.py -v` passes after the edit.
- [ ] Reboot into `main.py`. Within `interval_s` a new row appears
      in `/sd/sensors/soil/YYYY/soil_YYYY-MM-DD.csv` with columns
      `Timestamp,SeesawRaw,Percent,ProbeTempC`.
- [ ] Pour water into the pot near the probe; the next row shows
      `Percent` rising toward 100. Withhold water for several
      cycles; `Percent` falls.
- [ ] When `Percent < warn_pct_below`, the warning LED lights via
      `StatusManager`; clearing the condition turns it off.

### Notes (post-test) — STEMMA bring-up

> Fill in here. Record the three calibration raw values, the
> measured probe-temperature offset vs SHT31, and any bus-collision
> jumper changes that were necessary.

## 2026-05-23 · Next-rev post-fab verification (EasyEDA design-review items)

**Branch:** `main`
**Why hardware-only:** Every item below changes a real component
value, footprint, or layout rule on the next PCB. None can be
exercised on the host or by `pytest` — they need scope, multimeter,
and oscilloscope time after the new board lands. See
[chat-log.md](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)
for the full rationale per item.
**Pre-flight:**

1. New PCB fabricated, populated, smoke-tested for shorts before
   power-up.
2. XL4015 buck **reverted from the 6.0 V interim setpoint back to
   5.0 V** (the Schottky swap eliminates the need for the workaround).
3. Bench multimeter, USB scope, hook clips, and the LED-rail visual
   check ready.

### Power input — Schottky swap (D1-D6) and bulk caps

- [ ] Confirm D5 = MBR20100CT (TO-220) is installed on the heater path.
  Measure forward drop across D5 at the heater steady-state current
  (3.4 A single heater, 6.8 A parallel heaters): expect ~0.4–0.5 V.
- [ ] Confirm D1, D2, D3, D4, D6 = **MBRD1045 (D-PAK / TO-252)** are
  installed. Measure forward drop at typical load: expect ~0.3 V per
  diode.
- [ ] Confirm 5 V VSYS bulk cap is **1000 µF / 16 V** (not the earlier
  6.3 V draft). Quick check: read voltage rating off the part body.
- [ ] Verify F1 is now **upstream of D5** in the series order
  (19V_IN → F1 → D5 → bulk cap → HE_MOSFET). Trace continuity from
  19V_IN-2 to F1 input first, then F1 output to D5.
- [ ] With a 5 A or larger heater connected and switched ON, measure
  19.5 V rail at the bulk cap during switch-on transient. Expect rail
  sag < 0.5 V (was effectively undefined before the cap).
- [ ] Measure 12 V rail during fan startup (post-PCA9685): expect
  sag < 0.3 V.
- [ ] VSYS at Pico pin 39 idle: expect 4.6-4.8 V (was 3.05-3.4 V
  pre-Schottky).

### Power input — TVS clamps

- [ ] Confirm SMAJ5.0CA on 5 V, SMAJ15CA on 12 V, SMAJ24CA on 19.5 V
  are installed (all SMA footprint).
- [ ] Verify standoff voltage by measuring rail voltage with TVS in
  place during normal operation: no clamping should engage at
  nominal rail (5 / 12 / 19.5 V).

### Grow light — LM358 swap and gain retune

- [ ] Confirm LM358DR (SOIC-8) is installed in GL_OP-AMP position.
  Measure pin 8 to pin 4 voltage: expect ~12 V (the supply, no
  abs-max violation now).
- [ ] Confirm R4 = 10 kΩ, R5 = 4.7 kΩ.
- [ ] Run firmware DAC sweep (`debug` menu → growlight dim test, or
  manually set `growlight.default_level_pct` through 0, 25, 50, 75,
  100). Measure GL_DIM+ output at the connector at each step:
  - 0 % → ~0 V
  - 25 % → ~2.6 V
  - 50 % → ~5.2 V
  - 75 % → ~7.7 V
  - 100 % → ~10.3 V (firmware clamps to `max_level_pct = 91 %` →
    ~9.4 V at the connector; verify the clamp is active)
- [ ] Sweep continuously and confirm output is **monotonic** with no
  steps, plateaus, or oscillation.

### SD module swap — AZDelivery → Adafruit 4682

> Filed 2026-05-24. See
> [chat-log: module switch](../notes/chat-log.md#2026-05-24--sd-card-module-switch--azdelivery--adafruit-4682)
> and
> [next-revision: SD card module → Adafruit 4682](../hardware/next-revision.md).
> Pre-flight: 4682 populated on the new PCB, freshly-formatted FAT32
> microSD card on hand (8 GB or 32 GB), spare card for hot-swap test.

- [ ] Confirm the SD module silkscreen footprint is the **Adafruit
  4682** pinout: `3V, GND, CLK, SO, SI, CS, DET` on the SPI-side
  header row. DAT2 and D1/D3 pads exposed on the SDIO side (unused
  in firmware).
- [ ] Confirm the SD module power pin connects to the **3V3** net,
  **not** 5 V. Probe pin labelled `3V` on the breakout with no card
  inserted: expect 3.30 ± 0.10 V referenced to GND.
- [ ] Confirm the **100 µF electrolytic + 100 nF ceramic** decoupling
  pair is populated immediately adjacent to the 4682's `3V` pad,
  with leads < 5 mm if through-hole electrolytic, ideally surface-mount.
- [ ] Confirm the external **10 kΩ 0603 from GP13 to 3V3** is
  populated. With no SD card inserted and the Pico in reset (RUN
  held low), measure GP13 with the breakout still powered: expect
  ~3.3 V (pull-up active).
- [ ] **Cold-boot mount test, single attempt.** Power the board from
  cold (no USB held), with a known-good FAT32 card pre-inserted.
  Expected: SD mounts on the first attempt of the boot loop
  (`sd_mount_retries = 3`; ideally completes on retry 1). Repeat
  10× to catch the "first boot fails, second boot works" SDIO-lock
  failure mode the CS pull-up is meant to eliminate. Tolerance: 10
  / 10 first-attempt mounts.
- [ ] **Cold-boot with no card.** Power the board from cold with the
  SD slot empty. With `system.require_sd_startup = True`, expected
  behaviour is the boot path lights `sd_led + error_led` and resets
  after `sd_fail_reset_s = 10` s. Watch the boot log via USB MSC
  after the auto-reset.
- [ ] **Hot-swap recovery, card pulled.** With the system running
  and logging steady-state, pull the SD card. Expected: writes
  fall through to `/local/fallback.csv` (per
  [BufferManager](../../lib/buffer_manager.py)), no crash, no
  watchdog reset. Wait 60 s.
- [ ] **Hot-swap recovery, card re-inserted.** Re-insert the same
  card. Expected: within `sd_recovery_interval_s = 10` s the SD
  recovery loop re-mounts the card, then migrates the fallback
  rows back to `/sd/sensors/...` (per
  [WriteQueueManager](../../lib/write_queue_manager.py)).
- [ ] **Write throughput sanity check.** Run a 10-minute logging
  session at the default `temp_humidity_logger.interval_s = 30`.
  After 10 minutes, expect ~20 rows in the day's CSV file, no
  rows missing or corrupted, no `EventLogger` ERROR entries about
  SD writes.
- [ ] **3V3 rail headroom under SD inrush.** Scope the 3V3 rail at
  the 4682's `3V` pad during a write burst (trigger by inducing a
  rapid logging cadence or pulling a card mid-write). Expect rail
  sag < 0.1 V during the inrush event. If sag > 0.2 V is observed,
  the 100 µF decoupling cap is undersized for this layout — flag
  for the next rev.
- [ ] **DET pin readout (only if DET wired to GP15).** With no card
  inserted, probe GP15: confirm a defined logic level (the 4682's
  4.7 kΩ pull-up plus the DET switch state determines polarity —
  record which state means "absent"). Insert card: confirm logic
  level flips. Cross-check against the firmware's `sd_detect`
  reading via the debug menu or the boot log.
- [ ] **Compare against pre-swap baseline.** Confirm SD cold-mount
  rate, hot-swap recovery, and write throughput are all **at least
  as good** as the AZDelivery-equipped board (last benchmarked
  during the 2026-05-16/18 incident triage). Any regression flags
  a layout or topology issue, not a module issue.

### Senseair S8 — UART RX divider

- [ ] Confirm R11 = 2.2 kΩ and new R_RX_DIV = 3.3 kΩ are installed.
- [ ] With S8 connected and powered, measure DC voltage at Pico GP17
  during S8 idle (TXD high): expect ~3.0 V (not the previous ~5 V).
- [ ] Verify CO2 logging is still functional after the divider — the
  `co2_logger` retry counter should not climb in 24 h normal
  operation.

### I²C bus — pull-ups dropped to 2.2 kΩ

- [ ] Confirm R1 = 2.2 kΩ and R2 = 2.2 kΩ on SDA / SCL.
- [ ] Scope SDA and SCL rise times at the far end of the bus
  (e.g. the outward I²C RJ12 connector). Expect rise time
  < 1 µs at 250 pF bus capacitance.
- [ ] Run `prototypes/i2c_scan.py` (or in-firmware equivalent) and
  confirm all expected devices respond: 0x3C (OLED), 0x44 (SHT31),
  0x60 (MCP4725), 0x68 (DS3231), 0x40 (PCA9685 if populated).
- [ ] 24 h soak: no I²C error counts climbing in the event log.

### R3 correction and button surface

- [ ] Confirm R3 = 10 kΩ (not 10 Ω). Quick continuity check from
  GP14 to GND with the buzzer disconnected: expect ~10 kΩ.
- [ ] Press menu button repeatedly — no firmware glitches or
  spurious resets.

### Heater MOSFET gate driver (MCP1416)

- [ ] Confirm **MCP1416T-E/OT** (SOT-23-5) is installed at the new
  gate-driver footprint between Pico GP3 and the IRLZ44N gate.
- [ ] Confirm MCP1416 V_DD (pin 1) is wired to the 5 V rail and pin 3
  to GND; verify 100 nF decoupling cap is present.
- [ ] Confirm **R6 = 47 Ω** (was 100 Ω) between MCP1416 OUT and
  IRLZ44N gate.
- [ ] Confirm **10 kΩ pull-down** from IRLZ44N gate to source/GND.
- [ ] Power on with Pico held in reset (or before firmware starts):
  measure IRLZ44N V_GS — expect 0 V. Heater must be fully off during
  Pico boot.
- [ ] Drive GP3 HIGH from firmware. Measure IRLZ44N V_GS: expect ~5 V
  (was ~3.3 V with direct drive).
- [ ] Measure HE_MOSFET drain-source voltage with heater current
  flowing: expect ~0.15 V at 6.8 A (R_DS(on) ~0.022 Ω × 6.8 A) —
  improvement over the ~0.4 V seen at 3.3 V V_GS.
- [ ] Scope the gate edge during turn-on / turn-off. Expect clean
  monotonic transition, rise/fall under 1 µs, no ringing > 10 % of
  steady-state.

### Heater MOSFET thermal

- [ ] Confirm clip-on heatsink (SK 104-25 STS or equivalent) is
  mounted on HE_MOSFET.
- [ ] Run heater at full duty for **30 min continuous** in a sealed
  enclosure. Measure heatsink temperature with IR thermometer or
  thermocouple: expect < 70 °C above ambient. If hotter, layout
  pour may be inadequate — investigate copper pour stitch density.

### Power-good LEDs

- [ ] Confirm LEDs light on all four rails (3V3, 5V, 12V, 19.5V) at
  power-up.
- [ ] Visual brightness should be roughly uniform across all four
  (uniform 2 mA target). A LED that is much brighter or dimmer
  than the others suggests a wrong resistor value.

### Test points

- [ ] Confirm 8 labelled test pads (3V3 / 5V / 12V / 19.5V / GND / GND
  / SDA / SCL) are populated and at 2.54 mm pitch.
- [ ] Land a 6-pin pogo-pin debug fixture on the row and verify
  contact to all pads.

### Brownout supervisor

- [ ] Confirm MAX809 (or TPS3839K33) is installed on Pico RUN line
  (pin 30).
- [ ] Bench test: drop the input supply slowly from 5.0 V to 2.5 V
  while observing Pico behaviour. Expect a clean reset cycle when
  the supervisor's threshold is crossed (~3.0 V depending on part),
  not undefined state.

### VBUS / DEBUG_CON backfeed

- [ ] Confirm SS14 Schottky in series on INT_CON-4 (VBUS).
- [ ] Confirm SS14 Schottky in series on DEBUG_CON-2 (5 V).
- [ ] With Pico USB unplugged and 5 V supply on, measure INT_CON-4:
  expect 0 V (no backfeed from internal 5 V).

### Pico footprint label

- [ ] Verify silkscreen now reads `RPI-PICO-V1` (or the matching
  V1-labelled footprint in EasyEDA).

### Power input connectors (XT60 × 3) + F1 fuse

- [ ] Confirm **XT60** connectors installed on **all three** power
  input rails (5 V, 12 V, 19.5 V).
- [ ] Confirm silkscreen labels next to each XT60 read `5V`, `12V`,
  `19.5V` with `+` / `-` polarity marks.
- [ ] Verify board-edge clearance allows full XT60 seating on all
  three connectors (no overhang).
- [ ] Confirm F1 is a **10 A 5×20 mm T-rated (slow-blow)** glass
  cartridge in a through-hole holder, positioned **upstream of D5**
  (`19V_IN → F1 → D5 → bulk cap → HE_MOSFET drain → HE_CON`).
- [ ] Power on with both heaters in parallel switched ON via
  firmware. Heater steady-state current = ~6.8 A. F1 must not nuisance
  trip during the bulk-cap inrush spike at power-on.
- [ ] Short the heater output briefly (controlled test only — use a
  dummy load and current-limited bench supply at 19.5 V): F1 must clear
  in under 2 s at 2× rated current.

### PCB stackup and trace widths

- [ ] Confirm fab order specifies **2 oz copper** on both outer
  layers (verify with the JLCPCB / EasyEDA order screenshot or the
  certificate of conformity).
- [ ] Verify heater current path (F1 → D5 → bulk cap → HE_MOSFET →
  HE_CON) has minimum **3 mm trace width**. Spot-check at the
  narrowest point.
- [ ] Verify 12 V buck output trace has minimum **2.5 mm trace
  width**.
- [ ] Verify default trace clearance is **0.15 mm** on the signal
  nets and **0.3 mm** on the power traces. Quick check: any DRC
  warnings remaining in EasyEDA at the chosen clearance values
  must be reviewed and dismissed deliberately.

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-19 · VSYS rail validation (interim buck bump + next-rev Schottky)

**Branch:** `main`
**Why hardware-only:** VSYS rail behaviour under SD inrush only
reproduces on the real PCB with the XL4015 + 1N4002 input chain; no
host or pytest equivalent. See
[chat-log.md](../notes/chat-log.md#2026-05-19--external-5-v-supply-starves-vsys--1n4002-drop-traced)
for root cause.
**Pre-flight:**

1. Confirm by continuity that **only the Pico** sits downstream of
   the input diodes. If SHT31, OLED, or any other 5 V-rated device
   shares the post-diode rail, **stop** and do the Schottky swap
   below instead of raising the buck.
2. Have a multimeter ready, set to DC volts.

### Interim workaround — raise XL4015 output to ~6.0 V

- [ ] Disconnect Pico from buck. Adjust CV trimpot to **6.0 V**
  no-load. Verify with multimeter at the buck output terminals.
- [ ] Sticker / label the buck: `DO NOT TURN — 6.0 V workaround
  pending Schottky swap`.
- [ ] Reconnect Pico. Measure VSYS (Pico pin 39) at idle:
  expect ~5.0 V. **Must be ≤ 5.5 V (Pico VSYS abs max).**
- [ ] Provoke SD inrush (power-cycle; the SD mount runs early).
  VSYS during inrush should stay above ~4.4 V. A brief dip below
  that means the bulk cap is needed sooner rather than later.
- [ ] Boot reaches main loop. `/boot.log` shows `SD mounted at /sd`.
  No sd+error countdown loop.

### Interim workaround — bulk cap at Pico VSYS

- [ ] Solder a **470 µF–1000 µF** low-ESR electrolytic + **100 nF**
  ceramic between Pico VSYS (pin 39) and GND, leads as short as
  practical.
- [ ] Re-measure VSYS through power-up and SD inrush. The dip during
  inrush should be visibly smaller / shorter than the pre-cap run.

### Next PCB revision — Schottky swap verification

> Run after the next-rev board is fabricated and 1N4002 is replaced
> with SS14 / 1N5817 / MBRS340. Same supply, same Pico.

- [ ] Measure voltage drop across each replacement diode at typical
  load (~50 mA idle) and at SD-inrush peak (~200 mA).
  Expect ~0.25–0.4 V per diode.
- [ ] With XL4015 set to **5.0 V** no-load, measure VSYS at Pico:
  expect ~4.6–4.7 V under load, ~4.7–4.8 V at idle. **Revert the
  buck back to 5.0 V** when this confirms — the 6.0 V interim
  setting must not survive the diode swap.
- [ ] Confirm the second diode in series is either retained for
  OR-ing two sources, or removed as redundant reverse-protection.
  Document which in the schematic notes.
- [ ] Run a full boot cycle: SD mounts, sensors initialize, loop
  reaches steady state. No brown-outs, no WDT resets in the first
  10 minutes of operation.

### Notes (post-test)

> Fill in here.

## 2026-05-19 · Confirm reformat recovers SD + ENODEV diagnostic lands

**Branch:** `main`
**Why hardware-only:** ENODEV from `os.mount` only reproduces on a
card with corrupted FAT; host pytest mocks the error class but cannot
prove the diagnostic + reformat cycle actually recovers the device.
**Pre-flight:**

1. On a host PC, FAT32-format the SD card (Quick format is fine).
   Confirm the card mounts on the PC and is empty.
2. Reinsert into the Pico.
3. Flash latest `main` (post-classifier) to the Pico.

### Reformatted card boots cleanly

- [ ] Power-cycle Pico with freshly-formatted card inserted.
- [ ] No 10 s sd_led+error_led countdown; boot reaches main loop.
- [ ] `/sd/logs/system.log` is created within ~1 minute and contains
  normal startup lines.
- [ ] `/boot.log` shows `SD mounted at /sd` (no ENODEV line).

### Diagnostic line lands on a deliberately bad card

- [ ] Use a card with no FAT filesystem (raw or zeroed). Insert.
- [ ] Power-cycle Pico. Expect reset loop (require_sd_startup).
- [ ] After the first 10 s countdown, read `/boot.log` over USB MSC.
  Expect:
  `SD mount failed at /sd: [Errno 19] ENODEV -- card responds but
  has NO FILESYSTEM (reformat the SD card as FAT32)`
- [ ] On a card with disconnected DAT0 / no card inserted, expect
  instead:
  `... -- raw block read also failed (SPI bus / card unresponsive)`

### Notes (post-test)

> Fill in here.

## 2026-05-19 · Confirm SD detection after reverting mount-time mkdir

**Branch:** `main`
**Why hardware-only:** The reset loop with `/sd/logs` present was
observed on the real Pico after [a4f3acc](a4f3acc) and could not be
reproduced on host. The revert needs eyes-on confirmation that
boot now completes on the same card that was failing.
**Pre-flight:** Flash the latest `main` (post-revert) to the Pico
via `flash-mpremote-nocheck`. Use the same SD card that exhibited
the reset loop, without changing its contents.

### Boot completes with /sd/logs present

- [ ] Power-cycle Pico with card inserted.
- [ ] No 10 s sd_led+error_led countdown, no reset loop.
- [ ] `/sd/logs/system.log` continues to grow with normal entries.

### Boot completes with /sd/logs absent

- [ ] Delete `/sd/logs/` from the card on a host, reinsert.
- [ ] Power-cycle Pico.
- [ ] Boot reaches main loop without reset loop. `/sd/logs/` is
  re-created lazily by `BufferManager._ensure_parent_dir` on the
  first EventLogger write; `/sd/logs/system.log` exists within
  ~1 minute.

### Notes (post-test)

> Fill in here. If the reset loop still happens with `/sd/logs`
> absent, the original symptom was unrelated to the directory and
> we need a /boot.log capture before further code changes.

## 2026-05-19 · SD detected on empty / no-logs cards at boot

**Branch:** `main`
**Why hardware-only:** The reset-loop symptom only manifests on the
real Pico with `require_sd_startup=True` and the actual SD card +
SPI bus. Host tests prove the directory tree is created post-mount;
only the device proves the boot completes without entering the
sd_led+error_led failure state.
**Pre-flight:** Take an SD card the Pico previously booted from and
either (a) delete `/sd/logs/` entirely, or (b) reformat the card
(FAT32, quick) so it has no files. Re-seat the card. Flash latest
`main` to the Pico.

### Empty FAT-formatted card boots cleanly

- [ ] Power-cycle Pico with the empty card inserted.
- [ ] Boot reaches the main loop — no 10 s sd_led+error_led
  countdown, no reset loop.
- [ ] After ~1 minute, `/sd/logs/` exists on the card, contains
  `system.log` with normal startup lines.
- [ ] `/sd/sensors/`, `/sd/ota/pending/`, `/sd/ota/applied/`,
  `/sd/diagnostics/` all exist as empty directories.

### Missing-logs-only card boots cleanly

- [ ] Repeat the above with a card that has `/sd/sensors/` and
  `/sd/ota/` populated from a prior boot but `/sd/logs/` manually
  deleted.
- [ ] Boot completes; `/sd/logs/system.log` is recreated.

### Layout-creation failure stays non-fatal

- [ ] (Optional, advanced) Mount the card read-only on a host,
  delete `/sd/logs`, then re-insert. The Pico mounts, attempts to
  mkdir `/sd/logs`, fails, and continues booting — fallback file
  fills with the lost log lines. `/boot.log` shows
  `SD layout mkdir failed for logs_dir=...`.

### Notes (post-test)

> Fill in here.

## 2026-05-19 · Verify retry-on-OSError under SD bus stalls

**Branch:** `main`
**Why hardware-only:** Whether `verify_max_retries=3` is enough to
recover from real SD bus stalls under a 150 KB payload read can only
be observed on the real Pico + real SD card. Host tests prove the
control flow; only on-device runs prove the timing budget.
**Pre-flight:** Flash latest main to Pico via `flash-mpremote-nocheck`
(includes the retry-aware updater). Delete `/boot.log` on flash for
a clean trail. Build payload with `deploy-update-to-sdcard-nocheck`.

### Confirm verify completes under bus stalls

- [ ] Power-cycle Pico with payload at `G:\ota\pending\`.
- [ ] Apply succeeds (success jingle, all LEDs lit). On failure,
  re-check `/boot.log` for the failure point.
- [ ] `/sd/logs/updates.log` ends with `apply_ok …`.
- [ ] `/boot.log` contains `verify start files=N` and `verify done
  errors=0`. Per-file `verify <rel> ok` lines for all files.

### Confirm retry budget on a deliberately glitchy run

- [ ] If verify still fails: `/boot.log` should now show
  `verify <rel> stat_fail …` or `verify <rel> hash_fail …` instead
  of the misleading `missing` cascade — only the actually-glitched
  file is flagged.
- [ ] Optionally raise `updater.verify_max_retries` to `5` and
  `updater.verify_retry_delay_ms` to `400` in `config.py` and
  retest. Expect more glitchy runs to succeed; if even that doesn't
  help, the SD bus is the problem (cabling, baud, card).

### Notes (post-test)

>

## 2026-05-19 · SD-update verify/apply breadcrumbs to /boot.log

**Branch:** `main`
**Why hardware-only:** New `Updater._breadcrumb()` writes per-file
verify/apply progress crumbs directly to `/boot.log` on internal
flash. Only verifiable on real hardware because the diagnostic value
is "what file did verify die on when the SD log silently stopped" —
host tests cannot reproduce a flaky SD bus.
**Pre-flight:** Flash the new updater + boot_log to Pico via
`flash-mpremote-nocheck` (bypasses SD update so the new breadcrumb
code is live before any SD update is attempted). Delete `/boot.log`
on Pico flash so the new boot starts clean. Build a fresh payload
with `deploy-update-to-sdcard-nocheck`; do not power-cycle yet.

### Capture breadcrumbs on a failing run

- [ ] Power-cycle Pico with the payload in `G:\ota\pending\`.
  Observe the loading-screen LEDs + jingle outcome.
- [ ] Mount Pico internal flash over USB MSC. Read `/boot.log`.
- [ ] `/boot.log` contains `[updater.crumb] verify start files=<N>`
  matching the payload's file count.
- [ ] `/boot.log` lists either `verify <rel> ok` for every file (in
  which case the failure is in apply, not verify) OR exactly one
  non-ok line with the file path that died and the failure kind
  (`hash_fail`, `size_mismatch`, `hash_mismatch`, `missing`,
  `stat_fail`, `not_allowed`).
- [ ] `/boot.log` ends with `[updater.crumb] verify done errors=<n>`
  matching the number of non-ok lines.
- [ ] If verify passed but apply failed, `/boot.log` contains
  `[updater.crumb] apply start files=<N>` followed by per-file
  `apply <rel> ok` lines and an `apply <rel> fail <err>` line at
  the failure point.

### Notes (post-test)

>

## 2026-05-19 · SD-update canonical path + /boot.log mirror

**Branch:** `main`
**Why hardware-only:** Deploy task now writes to `G:\ota\pending` (canonical
`/sd/ota/pending` on Pico). New code path mirrors every `Updater.log()` line
into `/boot.log` on internal flash. Both behaviors only verifiable on a real
Pico + real SD card with the actual USB-MSC readback flow.
**Pre-flight:** SD card mounted as `G:`. Pre-existing `G:\update\` may be
left in place or wiped; either way the canonical path must win. Pico ready
to power-cycle and be re-mounted over USB MSC after the run.

### Deploy

- [ ] Run VS Code task `deploy-update-to-sdcard-nocheck` — completes without
  the `destination parent does not exist` error.
- [ ] After the task, `G:\ota\pending\manifest.json` exists and
  `G:\ota\pending\lib\` contains the compiled `.mpy` set.

### On-Pico verify

- [ ] Power-cycle Pico. Loading-screen LEDs run, fail/success/noop
  jingle plays per the apply outcome.
- [ ] `/sd/logs/updates.log` opens with `payload detected` (no
  trailing `at legacy …` suffix) — confirms canonical path was used.
- [ ] After the boot completes (or after fail jingle), mount Pico
  internal flash over USB MSC. `/boot.log` contains `[updater]`
  lines matching every line that appeared (or *should* have appeared)
  in `/sd/logs/updates.log` — including the `verify_fail` /
  `apply_fail` reason if the apply failed.

### Notes (post-test)

>

## 2026-05-19 · R8 (MISO series resistor) removed from PCB

**Branch:** `main`
**Why hardware-only:** R8 was physically desoldered / bridged on the
board between GP12 and SD_CON pin 3. Only an eyes-on bench run can
confirm the SD link is now stable and that the prior 32× `SD status
changed: FAILED` cluster does not recur. Firmware change in this turn
is documentation only — no code path to unit-test.
**Pre-flight:** Visually inspect that R8 is gone (or replaced with a
0 Ω jumper) and the pads have continuity end-to-end on a multimeter
between Pico GP12 and SD_CON pin 3. Reseat SD card; record make /
model. Wipe `/sd/logs/system.log` so the new run is easy to read.

### Continuity / hardware sanity

- [ ] Multimeter continuity beep between GP12 (Pico pin 16) and
  SD_CON pin 3 with the Pico powered off.
- [ ] R10 on MOSI is still present and intact — only R8 should have
  moved.
- [ ] No solder bridges to neighbouring pads (visual + 10× loupe).

### SD link stability at the current 10 MHz baudrate

- [ ] Boot and let the system run for ≥ 2 h.
- [ ] `grep -c "SD status changed: FAILED" /sd/logs/system.log`
  returns `0` over the 2-h window (previous regime: 32 in ~42 h).
- [ ] `grep -c "Write went to fallback" /sd/logs/system.log` returns
  `0` over the same window (no SPI bit errors forcing fallback).

### Optional: confirm 40 MHz is now safe (separate session)

- [ ] In a separate bench run, temporarily set
  `DEVICE_CONFIG["spi"]["baudrate"] = 40_000_000`, re-flash, run for
  ≥ 2 h, and check both grep counts above are still `0`.
- [ ] If stable, ship a `chore(config): restore SD SPI baudrate to
  40 MHz` commit and update [chat-log.md](../notes/chat-log.md). If
  any FAILED reappears, leave the 10 MHz setting in place and log
  the result.

### Notes (post-test)

> Fill in here. Add `[!]` items with failure mode and a short repro.

## 2026-05-19 · SD reliability + watchdog-feed pass

**Branch:** `main`
**Why hardware-only:** Six interlocking changes touch real SPI timing,
real SD card behavior, and the actual watchdog timer — none of which
the host shim exercises. Verifies the silent-reset rate drops, no
startup log entries get lost across an SD-eject cycle, and the new
reset-cause label is correct on a deliberate WDT trip.
**Pre-flight:** Wipe `/sd/logs/system.log` so the new run is easy to
read in isolation. Confirm `git rev-parse --short HEAD` matches the
fix series (last commit: docs append). Reseat SD card; note its
make/model. Flash the new code via the OTA path or Thonny.

### Silent-reset rate after the fixes

- [ ] Boot the system and let it run for at least 2 hours with no
  manual intervention.
- [ ] `grep -c "System startup" /sd/logs/system.log` returns ≤ 3 over
  the 2-hour window (previous run: 86 startups in ~42 h ≈ 2.05/h, so
  ≤ 3 over 2 h ≈ ≤ 1.5/h = at least 25% reduction; aim is more).
- [ ] No truncated startup patterns (every `System startup` line is
  followed within ~5 s by `TempHumidityLogger Initialized`,
  `Heater controller initialized`, `Fan controllers initialized`).

### Reset cause logging

- [ ] Each `[MAIN] System startup` line now ends with
  `(reset_cause=PWRON_RESET)` or similar.
- [ ] Force a WDT reset by holding a long-press during a known
  blocking operation OR by temporarily setting
  `watchdog_timeout_ms=1000` in config and ensuring at least one
  task overruns. Confirm the *next* boot's startup line reads
  `(reset_cause=WDT_RESET)`.
- [ ] Revert the watchdog timeout to 8000 ms.

### Fallback drain on boot (no more data loss)

- [ ] With SD card inserted and healthy, boot the system; after
  init completes, eject the SD physically.
- [ ] Wait 90 s (verify `[StatusMgr] SD status changed: FAILED`
  appears, plus several `Write went to fallback` rows in the
  console).
- [ ] Reinsert the SD; wait for `[MAIN] SD card re-mounted after
  hot-swap`.
- [ ] Power-cycle the Pico **before** the next health-loop iteration
  (so fallback has rows in it at boot).
- [ ] On the next boot, the new `[STARTUP] Drained N fallback row(s)
  from previous boot` line appears (N > 0) and the migrated rows
  show up in the matching CSV under `/sd/sensors/...`.

### SPI baudrate drop

- [ ] After at least 1 hour of running, count
  `grep -c "SD status changed: FAILED" /sd/logs/system.log` — expect
  noticeably less than the prior 32-in-42-hour rate (≤ 1 per hour).
- [ ] CSV write cadence under `/sd/sensors/th/2026/` matches the
  configured `interval_s` (30 s) — confirms the lower baudrate isn't
  the new bottleneck.

### Notes (post-test)

> Fill in here. Append `[!]` rows with failure mode + console snippet
> for anything that regresses.

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

> **Superseded 2026-05-26** — the analog TLC555 replacement path was
> abandoned in favour of the Adafruit STEMMA #4026 I²C sensor. See
> the 2026-05-26 entry at the top of this file. Steps below are kept
> as a historical record of the analog plan; do not execute.

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

### SD card (SPI1; MOSI via R10, MISO direct after R8 removal)

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
