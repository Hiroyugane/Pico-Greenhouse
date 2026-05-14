# Hardware test log

> Per [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md).
> Eyes-on verification steps for things `pytest` can't exercise.
> Newest entry on top. Use `[ ]` pending, `[x]` passed, `[!]` failed,
> `[~]` partial/blocked.

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
