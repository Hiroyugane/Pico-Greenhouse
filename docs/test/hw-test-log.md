# Hardware test log

> Per [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md).
> Eyes-on verification steps for things `pytest` can't exercise.
> Newest entry on top. Use `[ ]` pending, `[x]` passed, `[!]` failed,
> `[~]` partial/blocked.

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
