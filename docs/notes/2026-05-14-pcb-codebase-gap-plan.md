# PCB ↔ codebase gap plan (2026-05-14)

> Companion to [`chat-log.md`](chat-log.md). Inputs: full netlist extracted
> from [`docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json`](../SCH_Pico-Greenhouse-PCB_2026-05-14.json),
> current state of [`config.py`](../../config.py), [`main.py`](../../main.py),
> and [`lib/`](../../lib/). Output: a per-peripheral TDD-first implementation plan
> shaped so each phase lands as one or two commits per
> [`commit-granularity.md`](../../.claude/rules/ecc/common/commit-granularity.md).

## 1. Method

1. Walked every `LIB`, `W`, and `F` shape in the schematic JSON; built
   union-find over wire-segment endpoints, pin endpoints, and netflag
   anchors. Resulted in **49 named nets** + **23 unnamed pin-to-pin nets**
   (the latter are short hops through series resistors).
2. Cross-checked each named net against `DEVICE_CONFIG["pins"]`, against
   the wiring in `main.py`, and against the drivers in `lib/`.
3. Flagged any net whose endpoints touch the Pico but have **no driver
   class** or **no main.py wiring** — those are the gaps.

## 2. Inventory of PCB hardware vs. firmware coverage

| Pico GPIO / bus      | PCB net           | PCB endpoints                            | Config key                      | Driver in `lib/`             | Wired in `main.py` | Status |
| -------------------- | ----------------- | ---------------------------------------- | ------------------------------- | ---------------------------- | ------------------ | ------ |
| GP0 (I2C0 SDA)       | `I2C0_SDA`        | RTC, OLED, **GL_DAC**, I2C_CON1/2/3, R1  | `rtc_sda`                       | `ds3231`, `ssd1306` (via DI) | ✅                  | ✅ for RTC+OLED; **GL_DAC unused** |
| GP1 (I2C0 SCL)       | `I2C0_SCL`        | RTC, OLED, **GL_DAC**, I2C_CON1/2/3, R2  | `rtc_scl`                       | same                         | ✅                  | same |
| GP2                  | `GP2`             | GP2_CON pin 3                            | `gp2_breakout` / `button_reserved` | none                       | — (input pin alloc only) | OK — explicit breakout, no firmware contract |
| GP3                  | `GP3`             | R6 → HE_MOSFET gate                      | `heater_mosfet`                 | **none**                     | **no**             | **GAP — heater unused** |
| GP4–GP8              | `GP4`–`GP8`       | LED_CON pins 6,5,3,2,1                   | `activity_led`, `sd_led`, `warning_led`, `error_led`, `reminder_led` | `status_manager`, `led_button` | ✅ | ✅ |
| GP9                  | `GP9`             | MEN_BTN pin 2                            | `button_menu`                   | `led_button`                 | ✅                  | ✅ |
| GP10                 | `GP10`            | SD_CON pin 5 (SCK)                       | `spi.sck`                       | `sdcard` + `sd_integration`  | ✅                  | ✅ |
| GP11                 | `GP11`            | R10 → SD_CON pin 4 (MOSI)                | `spi.mosi`                      | same                         | ✅                  | ✅ |
| GP12                 | `GP12`            | R8 → SD_CON pin 3 (MISO)                 | `spi.miso`                      | same                         | ✅                  | ✅ |
| GP13                 | `GP13`            | SD_CON pin 6 (CS)                        | `spi.cs`                        | same                         | ✅                  | ✅ |
| GP14                 | `GP14`            | BUZ_CON pin 3 + R3 pulldown              | `buzzer`                        | `buzzer.BuzzerController`    | ✅                  | ✅ |
| GP15                 | `GP15`            | T/H_CON pin 4 (DHT22 data)               | `dht22`                         | `dht_logger`                 | ✅                  | ✅ |
| GP16 (U1 pin 21)     | unnamed @1035,-550 → R9 → `UART0_TX` | CO2_CON pin 4 (via R9)         | `co2_uart_tx`                   | none yet (UART read code in `tests/co2log.py` only) | **no** | **GAP — CO2 readings not in main loop** |
| GP17 (U1 pin 22)     | `UART0_RX`        | R11 → CO2_CON pin 3                      | `co2_uart_rx`                   | none yet                     | **no**             | **GAP — same** |
| GP18                 | `GP18`            | REL_CON pin 2 (fan_1)                    | `relay_fan_1`                   | `relay.FanController`        | ✅                  | ✅ |
| GP19                 | `GP19`            | REL_CON pin 3 (fan_2)                    | `relay_fan_2`                   | `relay.FanController`        | ✅                  | ✅ |
| GP20                 | `GP20`            | REL_CON pin 4 (growlight master switch)  | `relay_growlight`               | `relay.GrowlightController`  | ✅                  | ✅ on/off only |
| GP21/22/26/27        | `GP21`/`GP22`/`GP26`/`GP27` | REL_CON pins 5–8                | `relay_reserved_1..4`           | **none**                     | **no**             | **GAP (low-priority) — wired but unbound** |
| GP28 (ADC2)          | `ADC_GP28`        | ADC_CON pin 4                            | `adc_input`                     | **none**                     | **no**             | **GAP — purpose TBD** |
| 3V3_EN               | `3V3_EN`          | RES_BTN pin 2                            | n/a (hardware reset)            | n/a                          | n/a                | ✅ (hardware-only) |
| RUN                  | `RUN`             | INT_CON pin 5 (debug)                    | n/a                             | n/a                          | n/a                | ✅ (debug header only) |
| SWCLK / SWDIO        |                   | DEBUG_CON pins 3,4                       | n/a                             | n/a                          | n/a                | ✅ (debug header only) |
| ADC_VREF (Pico pin 35) | `ADC_VREF`      | ADC_CON pin 2                            | n/a                             | n/a                          | n/a                | ✅ (hardware reference) |
| ADC_GND (Pico pin 33)  | `ADC_GND`       | ADC_CON pin 5                            | n/a                             | n/a                          | n/a                | ✅ |

Non-Pico PCB elements with no firmware contract (all expected — listed for completeness):

- `FAN_AMB_CON_1/2` + `FAN_AMB_SW_1/2`: 12V ambient fans on a **manual mechanical switch** (no GPIO control).
- `FAN_CON`: VCC/GND passthrough to the relay-switched fans (already handled via REL_CON).
- `HE_CON`: heater output connector (drain side of HE_MOSFET).
- `GL_OP-AMP` (unity buffer) + `R4`/`R5` (analog conditioning) + `GL_CON`: analog chain from DAC to dimmable grow-light input.
- Three power inputs (`5V_IN`, `12V_IN`, `19.5V_IN`) with reverse-protection diodes `D1`–`D6`, fuse `F1` on the 19.5V rail.
- `C1`–`C6`: decoupling caps.
- `INT_CON`, `DEBUG_CON`: debug/programming headers (RUN, SWD).
- `U2`, `U3`, `U4`: 2-pin helper passives on CO2_CON.2, T/H_CON.2, I2C_CON1.2 respectively (likely pull-ups; verify on the BOM but no firmware impact either way).

## 3. Gap summary

Four firmware-actionable gaps, ranked by user-visible value:

| # | Gap                              | Hardware                                  | Firmware needed                                                                            | Blocker?                          |
| - | -------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------- |
| 1 | **Dimmable grow light**          | MCP4725 DAC → op-amp → GL_CON             | MCP4725 driver + dimming layer over `GrowlightController` (relay = master, DAC = level)    | none                              |
| 2 | **Heater control**               | GP3 → R6 → IRLZ44N → HE_CON               | `HeaterController` (active-HIGH, thermostat fed by `DHTLogger.last_temperature`)           | none                              |
| 3 | **CO2 sensor in main loop**      | GP16/17 ↔ R9/R11 ↔ CO2_CON                | `CO2Logger` (UART0 reader) + tier-through `BufferManager`, OLED menu page for ppm          | none                              |
| 4 | **GP28 ADC reader**              | ADC_CON pin 4                             | `ADCReader` + a sink (logging? OLED page? thermostat 2nd channel?)                          | **purpose unspecified — see Q1**  |
| 5 | Reserved relays GP21/22/26/27    | REL_CON pins 5–8                          | generic relay-output API exposed to a future feature                                       | low priority — leave dormant      |

## 4. Open questions before phase work starts

| ID  | Question                                                                                                            | Why it matters                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Q1  | What does the GP28 ADC actually sense? (soil moisture, light meter, second thermistor, spare?)                       | Determines whether the driver is a simple sampler, a calibrated converter, or a thermostat input. |
| Q2  | Dimming semantics: does the dim level live in `config.py` (static), follow the schedule (ramped at dawn/sunset), or be commanded from the OLED menu (manual)? | Drives whether `GrowlightController` gains a level setter, a ramp method, or a config-only constant. |
| Q3  | Heater thermostat: single setpoint with hysteresis (like the fans, just inverted) or a separate day/night setpoint? | Drives whether `HeaterController` is one config block or two.                  |
| Q4  | CO2: do we want ppm logged to CSV (parallel to DHT), surfaced on OLED, used for fan override (high CO2 → fan on), or all three? | Affects how deep the integration goes in phase 3.                              |
| Q5  | Verify MCP4725 I2C address — is A0 tied to GND (→ 0x60) or VCC (→ 0x61) on this board?                              | Required before the DAC driver can be wired up.                                |
| Q6  | Reserved relays — leave dormant, or surface a generic "extra relay" config to drive any one of them from a future feature? | Determines whether phase 5 happens at all.                                     |

These should be answered before starting phase 1. The picker form can be a single `AskUserQuestion` round at the top of the next session.

## 5. Phased implementation plan

Each phase is sized as a self-contained piece of work that lands as
**2–4 commits** (per `commit-granularity.md`): tests → driver → main.py
wiring → docs (hw-test-log + chat-log). The tree must be green at every
commit.

### Phase 0 — Verify I2C0 fully populated (pre-work, ~30 min)

**Goal:** Confirm the MCP4725 ACKs on the bus and resolve Q5.

- [ ] Flash a host-side or REPL probe that scans I2C0 (`I2C(0).scan()`)
      on the Pico and reports addresses.
- [ ] Expected: `0x3C` (OLED), `0x68` (DS3231), and one of `0x60`/`0x61`
      (MCP4725).
- [ ] Update `docs/test/hw-test-log.md` with the observed address (it's
      already a `[ ]` line — flip to `[x]`).
- [ ] Add the resolved address as `growlight.dac_i2c_address` in
      `config.py` and validator.

**Commits:** 1.

### Phase 1 — MCP4725 grow-light DAC driver + dimmable growlight (~half day)

Depends on Q2 (semantics) and Q5 (address resolved in phase 0).

**Library reuse:** Adopt an existing MicroPython MCP4725 driver. The
file [`docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json`](../SCH_Pico-Greenhouse-PCB_2026-05-14.json)
is the only PCB doc; the driver itself can ship vendored under
[`lib/`](../../lib/) similar to `ds3231.py` and `ssd1306.py`. Search order:

1. `wayoda/micropython-mcp4725` (Apache-2.0, single file, RP2040-compatible)
2. `mcauser/micropython-mcp4725` if the above is missing.
3. Hand-roll only if neither is acceptable — the MCP4725 protocol is
   trivial (3-byte write).

**Step plan (TDD-first):**

1. [ ] `tests/test_mcp4725.py` — exercises the driver against a mock
       I2C bus: writes `0x00`/`0xFFF`/mid-range, asserts byte sequences
       sent. Add a `lib/picozero_excludes` style coverage exclusion if
       the vendored driver doesn't lint clean.
       Commit: `test(mcp4725): cover MCP4725 driver write protocol`.
2. [ ] Vendor (or write) `lib/mcp4725.py`. Ensure it imports cleanly on
       both Pico (`machine.I2C`) and host (the `host_shims/machine.py`
       mock). Adjust the host shim if needed.
       Commit: `feat(mcp4725): add MCP4725 driver for grow-light DAC`.
3. [ ] Extend `GrowlightController`: add `set_level(percent)` and
       `current_level` attribute. Internally: relay ON if level > 0,
       DAC level computed from percent. Default level from new config
       key `growlight.default_level_pct`.
       Tests in `tests/test_relay.py` (or a split-out file) cover:
       - Level 0 → relay OFF, DAC = 0
       - Level 50 → relay ON, DAC ≈ 0x800
       - Level 100 → relay ON, DAC = 0xFFF
       - Schedule transition still fires `on()`/`off()` correctly.
       Commit (test): `test(growlight): cover dimming layer`.
       Commit (impl): `feat(growlight): add DAC-driven dimming`.
4. [ ] Wire into `main.py`: factory-build the MCP4725 from the shared
       `hardware.get_i2c()`, pass it into `GrowlightController` via DI.
       Commit: `feat(main): inject MCP4725 into GrowlightController`.
5. [ ] Add hw-test rows in `docs/test/hw-test-log.md`:
       - [ ] Set level 0 / 25 / 50 / 100 via REPL → measure GL_CON
             with multimeter; expected 0 V / ~0.825 V / ~1.65 V / ~3.3 V
             (or the op-amp's scaled output, document actual).
       - [ ] Schedule transition at dawn — light visibly ramps to
             configured level (if ramp implemented per Q2).
6. [ ] Chat-log decision entry: "MCP4725 driver vendored from
       <upstream>; relay remains master switch, DAC sets brightness".

**Commits in this phase:** 4–6.

### Phase 2 — Heater control (~half day)

Depends on Q3 (single vs. dual setpoint).

1. [ ] `tests/test_heater.py` — covers:
       - `on()` drives gate HIGH (active-HIGH, opposite of relay).
       - `off()` drives gate LOW.
       - Thermostat: temp < `min_temp - hysteresis` → on; temp >
         `min_temp` → off.
       - Reads `dht_logger.last_temperature` (mirror the
         `FanController` pattern).
       - Day/night split if Q3 = dual setpoint.
       Commit: `test(heater): cover HeaterController thermostat`.
2. [ ] `lib/heater.py` — `HeaterController` class. Reuse the
       async-task shape of `FanController`. NOTE: **active-HIGH** —
       do not pass `invert=True` into a `RelayController`; either
       subclass differently or use raw `Pin.OUT` semantics.
       Commit: `feat(heater): add HeaterController`.
3. [ ] Config: add `heater` block (`min_temp`, `temp_hysteresis`,
       `poll_interval_s`, optionally `night_min_temp` etc.). Add to
       validator + `tests/test_config.py`.
       Commit: `feat(config): add heater control block`.
4. [ ] Wire into `main.py`: instantiate, spawn `start_cycle()` task.
       Commit: `feat(main): spawn heater control task`.
5. [ ] hw-test-log rows:
       - [ ] Cold the sensor (ice pack on T/H_CON) → heater LED on the
             multimeter goes HIGH; HE_CON drain measurable.
       - [ ] Warm the sensor past the setpoint → gate LOW within one
             `poll_interval_s` cycle.
       - [ ] No spurious activation at boot (gate LOW before first DHT
             sample arrives).
6. [ ] chat-log decision entry: "Heater driven from GP3 active-HIGH;
       thermostat fed by DHTLogger to share calibration with fans."

**Commits:** 5.

### Phase 3 — CO2 sensor integration (~full day)

Depends on Q4 (logging vs. OLED vs. fan override).

1. [ ] Audit the prototype in [`tests/co2log.py`](../../tests/co2log.py)
       and [`tests/co2test.py`](../../tests/co2test.py); promote the
       working bits into a real driver.
2. [ ] `tests/test_co2_logger.py` — covers UART framing parse, retry
       behavior, timeout fallback, plumbing through `BufferManager`.
3. [ ] `lib/co2_logger.py` — mirrors `DHTLogger` shape (constructor
       takes `time_provider`, `buffer_manager`, `logger`, `write_queue`,
       optional `status_manager`).
4. [ ] Add `co2_logger` config block (interval_s, retry, baudrate
       already in pins, warn/error thresholds).
5. [ ] Wire into `main.py`. Add OLED menu page if Q4 includes display.
6. [ ] hw-test-log rows:
       - [ ] CO2 reading appears in `/sd/co2_log_YYYY-MM-DD.csv` every
             cycle.
       - [ ] Realistic ppm range (400–2000 indoors).
       - [ ] Sensor warm-up phase logged as a warning, not an error.
7. [ ] chat-log decision entry.

**Commits:** 5–6.

### Phase 4 — GP28 ADC reader (size depends on Q1)

If Q1 = "soil moisture" or "light level":

1. [ ] `tests/test_adc_reader.py` covers calibration table + sampling.
2. [ ] `lib/adc_reader.py`.
3. [ ] Config block.
4. [ ] OLED page or CSV log destination.
5. [ ] hw-test-log rows.

If Q1 = "second thermistor for greenhouse-internal temp": fold into the
heater phase instead of a standalone module.

If Q1 = "spare for now": skip this phase, leave `adc_input` in config
as a reserved key, document in chat-log.

**Commits:** 0–5 depending on Q1.

### Phase 5 — Reserved relays (optional, ~hour)

Only do this if Q6 = surface them. The implementation is just a tiny
`SimpleRelay` class + a config map of name→pin. Otherwise leave as-is
and the next person who needs them follows the pattern in `relay.py`.

**Commits:** 0–2.

## 6. Cross-cutting work that does **not** become its own phase

- **Validator updates**: every config key added in phases 1–5 gets a
  matching entry in `validate_config()` and a row in
  `tests/test_config.py`. These ship in the same commit as the config
  key, not separately (per the commit-granularity rule for
  indivisible-unit changes).
- **Watchdog feeding**: any new async task added by phases 1–4 must
  `await` regularly (no long blocking calls), otherwise it bricks the
  Pico under WDT. The MCP4725 write is sync but completes in well under
  1 ms; safe. CO2 UART reads should use `asyncio.sleep_ms` between
  retries.
- **OLED menu**: if Q2/Q4 include OLED surfaces, those edits go through
  `lib/oled_display.py`'s existing menu enum — one menu page per
  peripheral. Touching this file should be its own commit per phase to
  keep the OLED diff readable.
- **Host-shim coverage**: `host_shims/machine.py` already mocks `I2C`,
  `SPI`, `Pin`, `UART`. Confirm `I2C.writeto`/`writeto_mem` work as the
  vendored MCP4725 driver expects; extend the shim if not. Same for
  any new UART idioms in the CO2 driver.

## 7. Ordering

Recommended order (all gated on Q1–Q6 being answered first):

1. Phase 0 (verify I2C inventory) — half hour, no real risk.
2. Phase 2 (heater) — smallest scope, biggest immediate value (the
   greenhouse needs heat before it needs dimming).
3. Phase 1 (DAC dimming) — depends on phase 0; depends on user choice
   for dim semantics.
4. Phase 3 (CO2) — depends on the existing CO2 prototype being healthy.
5. Phase 4 (ADC) — only if Q1 resolves to a concrete use.
6. Phase 5 (reserved relays) — last; trivial.

Total: roughly **2–3 days of focused work** for phases 0–3, plus
whatever Q1 turns out to require.
