# Next hardware revision — queued changes

> Canonical, append-only checklist of every change planned for the
> next PCB / enclosure / wiring revision. Read this before opening
> the schematic editor. Per
> [.claude/rules/ecc/common/hardware-revision-notes.md](../../.claude/rules/ecc/common/hardware-revision-notes.md).
>
> Newest item on top. Each item links to the `docs/notes/chat-log.md`
> entry where the root cause / decision was captured, so the full
> rationale is one click away.
>
> Use `[ ]` queued, `[x]` shipped on the new revision, `[~]` deferred
> with a reason in the entry body.

## Electrical / PCB

### [ ] MCP6002 op-amp → LM358 + grow-light gain retune

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-grow-light-opamp-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_grow_light_opamp_revision.md)

- **Critical — current part is operating above absolute maximum.**
  MCP6002T-I/SN abs-max V_DD-V_SS = **7.0 V**; the schematic powers it
  from the **12 V rail** (pin 8 to 12 V net). Chip degrades silently
  and will fail; explains any flaky grow-light dim behaviour.
- Replace with **LM358DR** (SOIC-8, pin-compatible, V_CC max 32 V).
  Not rail-to-rail at the top, but that turns out to be useful — at
  12 V supply the output swings to ~10.5 V max, a natural ceiling
  below the 10 V dim-spec damage threshold.
- **Retune feedback divider** for clean 0–10 V output from the 0–3.3 V
  DAC: **R4 = 10 kΩ, R5 = 4.7 kΩ** → gain = 1 + 10/4.7 = 3.13 →
  V_out_max = 3.3 × 3.13 = **10.3 V**. Firmware clips to 10 V via
  `growlight.max_level_pct` (already 91 %, which equates to ~9.4 V at
  the new gain — well within spec).
- Verify with [hw-test-log](../test/hw-test-log.md) post-fab: sweep
  DAC 0 → 0xFFF, measure GL_DIM+ output, confirm monotonic + clean
  ramp.

### [ ] Senseair S8 UART RX level protection

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-co2-uart-protection](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_co2_uart_protection.md)

- Senseair S8 UART TXD is **5 V TTL** referenced to V+. Pico GPIO
  abs-max is **3.3 V + 0.5 V = 3.8 V**. Current R11 = 100 Ω in series
  is signal damping, not voltage protection — Pico clamp diodes
  shoulder the over-voltage today, which works but degrades the input
  pin over weeks of continuous operation.
- **Fix — resistor divider on the RX line (Pico GP17):**
  - Change R11 from 100 Ω to **2.2 kΩ** (series, S8 TX → Pico RX)
  - Add new **R_RX_DIV = 3.3 kΩ** from Pico RX to GND
  - Divider output: 5 × 3.3/(2.2+3.3) = **3.0 V** ✓
  - Loaded impedance ~1.3 kΩ — fine for 9600 baud over 1 m cable
- R9 (Pico TX → S8 RX, 100 Ω) **unchanged.** 3.3 V drive easily
  crosses the S8 input threshold (~V+ × 0.3 = 1.5 V).

### [ ] Bulk capacitance on 12 V and 19 V rails

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-power-input-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)

- Current PCB has **only 100 nF ceramics** on each rail — no
  electrolytics. Heater switching (3.4 A on the 19 V rail) and fan
  inrush (12 V rail, once PCA9685 + MOSFETs land) hammer the rails
  with no bulk capacitance to absorb transients.
- **Add per rail, close to the load:**
  - **19 V near D5 / HE_MOSFET:** 470 µF / 35 V low-ESR electrolytic
    in parallel with 100 nF ceramic
  - **12 V near D4:** 220 µF / 25 V low-ESR electrolytic in parallel
    with 100 nF ceramic
  - **5 V VSYS (already queued):** 1000 µF / 6.3 V in parallel with
    100 nF ceramic
- **Why both electrolytic AND ceramic at each spot:** electrolytics
  have low impedance at low frequencies (handles amps of sag during
  inrush) but ESR/ESL rise sharply above ~100 kHz. The 100 nF ceramic
  shunts MHz switching-edge noise to GND. Standard pairing — covers
  the full frequency band.

### [ ] TVS clamp diodes on all three power inputs

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-power-input-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)

- Three TVS diodes, same SMA-family footprint, three values:
  - **5 V input:** SMAJ5.0CA (working voltage 5 V, clamp ~9 V)
  - **12 V input:** SMAJ15CA (working voltage 15 V, clamp ~24 V)
  - **19 V input:** SMAJ24CA (working voltage 24 V, clamp ~39 V)
- Bidirectional `CA` parts — protects against either polarity, useful
  on the Phoenix terminal block where reversed wiring is plausible.
- **Placement:** just downstream of input connector and series
  Schottky, before the bulk capacitor. ~$0.15 each.

### [ ] Schottky diode plan — MBR20100CT for D5, SS54 elsewhere

**Filed:** 2026-05-23 · supersedes per-diode notes in earlier entry ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-power-input-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)

- **Critical — D5 is currently a fire risk.** D5 is a 1N4002 (1 A
  rated, DO-41) on the 19 V → heater path. Heater is 24 V / 100 W →
  5.76 Ω → at 19.6 V draws ~3.4 A. D5 is being run at **3.4× its
  continuous rating**; package dissipation exceeds DO-41 limits.
- **Two SKUs total:**
  - **D5 → MBR20100CT** (TO-220, 20 A / 100 V) — heater path. Massive
    headroom, very low V_f.
  - **D1, D2, D3, D4, D6 → SS54** (SMA, 5 A / 40 V, ~$0.10) — covers
    every other input-protection diode with 5 A safety margin and
    SMA footprint to keep the board-shrink goal viable.
- V_f drops from ~0.8 V (1N4002) to ~0.3 V (Schottky) at every
  diode, eliminating the VSYS-starvation root cause permanently.
- If single-SKU is strongly preferred: 6× MBR20100CT works
  electrically but costs ~$3.84 and eats six TO-220 footprints.

### [ ] F1 fuse position — upstream of D5, sized for parallel-heater option

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Current netlist order is **19V_IN → D5 → F1 → HE_CON**. A shorted
  D5 dumps all 19 V before F1 can react.
- **Correct order:** `19V_IN → F1 → D5 → bulk cap → HE_MOSFET drain
  → HE_CON`. Fuse goes first, then series diode, then load chain.
- **Fuse rating depends on heater plan** (open decision below):
  - **Single 100 W / 24 V heater (current):** F1 = 5 A fast-blow
    keeps ~50 % headroom over 3.4 A steady-state. No change.
  - **Two parallel 100 W heaters on one channel (option a):** total
    draw = 6.8 A → bump F1 to **7.5 A T-rated slow-blow** and bump
    harness to 16 AWG minimum.
  - **Two heaters on two MOSFETs / separate fuses (option b):**
    keep F1 = 5 A on the shared rail, add a second 5 A fuse on the
    second channel.

### [ ] Heater channel count — single vs. dual MOSFET decision

**Filed:** 2026-05-23 · DEFERRED — pick at schematic-design time ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- **Single channel (option a):** keep the current one-MOSFET layout,
  one control GPIO (GP3). For two heaters in parallel, upsize fuse +
  wire (see fuse entry above), keep IRLZ44N (handles 6.8 A on
  heatsink). Simplest schematic delta, no firmware change.
- **Dual channel (option b — RECOMMENDED for weeks-of-uptime):**
  add a second IRLZ44N + gate resistor + flyback Schottky + fuse on
  an unused GPIO (GP21 is the closest reserved relay channel — or
  pick from GP15/GP22/GP26/GP27 reserved). Each channel sees ~3.4 A,
  within today's envelope. Firmware adds a `heater_2` config block
  mirroring `heater`. Graceful degradation if one heater fails.
- Either choice keeps the **MBR20100CT** on the high-current path
  and the **copper-pour-plus-clip-on-heatsink** thermal plan.

### [ ] R3 corrected to 10 kΩ pull-down on GP14 buzzer line

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Current BOM lists R3 as **"10"** (10 Ω) — too low for a GPIO
  pull-down. If GP14 ever drives high (buzzer PWM start, glitch), 10 Ω
  to GND draws 330 mA → instant pin damage.
- **Replace R3 = 10 Ω with R3 = 10 kΩ.** Standard pull-down value;
  draws 330 µA worst-case if firmware ever drives the pin against the
  pull-down. Same body as R1/R2 already on the BOM.
- Likely a schematic transcription error (R1, R2, R7 are 10 kΩ on
  identical footprint) — verify in EasyEDA before re-fabbing.

### [ ] I²C pull-ups R1/R2 → 2.2 kΩ for 400 kHz fast-mode rise time

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-i2c-bus-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_i2c_bus_revision.md)

- `config.py.system.i2c_freq = 400000` (fast mode). Bus carries
  Pico + DS3231 RTC + SSD1306 + MCP4725 DAC + SHT31 + (future)
  PCA9685 + three external RJ12 / JST drops → bus capacitance
  ~250 pF.
- I²C fast mode requires rise time < 300 ns. With R1/R2 = 10 kΩ:
  τ = R·C = 10 k × 250 pF = 2.5 µs — **~8× too slow**, likely root
  cause of any intermittent I²C bus glitches.
- **Drop R1, R2 from 10 kΩ → 2.2 kΩ.** Rise time falls to ~550 ns →
  within spec at the device end after RC settling.
- Also a candidate suspect for any "MCP4725 doesn't respond" or
  "OLED tears" symptoms seen on the current PCB.

### [ ] Brownout supervisor on Pico RUN line

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- RP2040 internal POR threshold is ~2.0 V. A slow rail droop that
  doesn't cross 2.0 V can latch the MCU in undefined state — won't
  reset, won't recover.
- Add a **MAX809LEUR+T** (or **TPS3839K33**) on RUN (Pico pin 30).
  ~3.0 V reset threshold, ~$0.30, SOT-23-3.
- Effect: rail droop below 3.0 V forces a clean reset; firmware
  watchdog catches the rest. Improves stability across the
  weeks-of-uptime envelope.

### [ ] VBUS + DEBUG_CON 5 V backfeed protection

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- **INT_CON-4 = VBUS** (straight off Pico USB connector). Anything
  plugged into INT_CON can back-feed the USB host or sink VBUS.
- **DEBUG_CON-2 = 5 V** (off the post-Schottky 5 V rail). SWD
  programmers / probes can back-feed the rail.
- **Fix:** add an **SS14** (SMA, 1 A, ~$0.06) in series on the VBUS
  pin of INT_CON and on the 5 V pin of DEBUG_CON. SS14 is from the
  same family as SS54 chosen for D1–D4/D6 — keeps the SKU count flat.
- Alternative: drop those power pins from the headers entirely if
  no current design needs them.

### [ ] Power-good LEDs — 2 mA current target across all rails

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Add a 3 mm or 0805 LED + series resistor on each rail near the
  input area, for immediate visual confirmation during bring-up and
  field service.
- **Uniform 2 mA target** (long LED life over weeks of always-on
  operation, with typical 2 V Vf):
  - 3V3 rail: 680 Ω (1.9 mA)
  - 5 V rail: 1.5 kΩ (2.0 mA)
  - 12 V rail: 4.7 kΩ (2.1 mA)
  - 19 V rail: 8.2 kΩ (2.1 mA)
- Different resistor values per rail are intentional — uniform
  current is more useful than a uniform BOM line at this scale.

### [ ] Test-point row near input area

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- **Eight labelled THT pads** in a 2.54 mm-pitch row near the input
  regulators: `3V3 / 5V / 12V / 19V / GND / GND / SDA / SCL`.
- 1.5 mm round pads with via hole → accepts hook clips and a 6/8-pin
  pogo-pin debug fixture later.
- Silkscreen label next to each pad. Two GND pads (one near positive
  rail group, one near signal group) saves probe reach.
- Free during fab. Consider adding SWD pads (`SWCLK / SWDIO`) too if
  layout allows, even though they're already on DEBUG_CON.

### [ ] I²C address map on silkscreen

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-i2c-bus-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_i2c_bus_revision.md)

- Print the 7-bit hex address next to each I²C device's footprint:
  - SHT31 → `(0x44)`
  - DS3231 RTC → `(0x68)`
  - MCP4725 DAC → `(0x60)`
  - SSD1306 OLED → `(0x3C)`
  - PCA9685 (future) → `(0x40)`
- Also consolidate the full address list in a comment block at the
  top of `config.py` so future agents can see conflicts at a glance.

### [ ] Pico V1 footprint label correction

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- BOM row 37 lists footprint as `RPI-PICO-V2 COPY`. The board uses
  the **original Pico (V1, RP2040)** — V2 was simply the
  best-fitting footprint at design time.
- Rename the footprint label to **`RPI-PICO-V1`** to align
  documentation with reality. No layout change; pinout identical.

### [ ] R8 stays — fix the firmware comment, not the schematic

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- `config.py:36-40` claims R8 was "removed" after the 2026-05-16/18
  SD bit-error incident. The current PCB still has R8 = 33 Ω on the
  MISO line, and the field fix turned out to be VSYS voltage, not
  R8 itself.
- **Decision: keep R8 = 33 Ω.** Functions as SPI signal damper for
  the 10 MHz baud over the SD ribbon — useful, not harmful.
- **Firmware-side correction:** update the comment in `config.py`
  to say R8 stays. Filed as a non-PCB cleanup to ship with the
  next-rev planning sweep.

### [ ] Button connector rework — menu_btn debounced, reset_btn direct

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Combine `reset_btn` and `menu_btn` into a **single 3-pin connector,
  two-split layout** (one shared ground, two signal pins).
- **Menu button:** 10 kΩ pull-up to 3V3 on its signal line + a
  debounce capacitor on that line. The menu button is non-functional
  on the current board; missing pull-up / debounce is the suspected
  cause.
- **Reset button:** direct contact only — no pull-up, no series
  resistor, no capacitor. Supersedes the earlier draft of a 10 kΩ
  pull-up and 1 kΩ series resistor on GP9.
- **Drop** the capacitor previously sketched between **3V3_EN and
  GND** — not needed.
- Add a separate **10 kΩ pull-up on GP12 to 3V3** (not button-related,
  but caught in the same pass).

### [ ] Relay connector cleanup — flip, pull-ups, GND fix, mains-only

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- **Flip the relay connector orientation** — current orientation is
  wrong for the harness.
- Add a **10 kΩ pull-up on each relay IN line** to the relay module's
  VCC, so inputs sit at the inactive (HIGH) level during Pico boot
  and reset (active-low relays).
- The "3V3" pin on the current relay connector goes nowhere (dead).
  **Tie it to GND** so the connector pinout is meaningful.
- After fans move to PCA9685 + IRLZ44N (see fan entry below), the
  remaining relays carry **only 230 V mains loads** (grow light,
  heater). Update connector spec / spacing for mains creepage and
  clearance.

### [ ] I²C / RJ12 connector layout — rename, add second outward bus

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Replace the existing **DHT21 connector with an I²C-friendly RJ12
  connector** so the SHT31 plugs in directly (current rev still has
  the DHT21-style port).
- **Rename silkscreen label "I2C con_1" → "SHT31"** — the port
  carries exactly one sensor and the label should say so.
- **Add one more outward-facing RJ12 connector** for an additional
  I²C drop on the enclosure wall. Bus topology (one I²C bus vs two)
  stays flexible — the requirement is a second exposed jack so future
  I²C peripherals don't need bus stubs through the case.

### [ ] ADC / soil-moisture interface

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Soil-moisture sensor outputs 0–5 V analog. Pico ADC is 0–3.3 V max.
  Add a **10 kΩ (top) + 15 kΩ (bottom)** voltage divider between the
  sensor output and the ADC pin: 5 V full-scale → ~3.0 V at the Pico
  (under abs max, with margin).
- **Route 3V3 to the ADC connector** alongside GND and the ADC signal
  so 3V3-powered analog peripherals can be powered from the same jack.

### [ ] Case fan voltage selector + ambient fan Pico control

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Add a **second 2-pole voltage selector switch** for the case fan,
  mirroring the existing ambient fan voltage switch (so each fan can
  be tied to a different rail without re-wiring).
- Make the **ambient fan Pico-controllable** — currently it's
  hardwired and bypasses the Pico. Route it through the new
  PCA9685 + IRLZ44N stage so it joins the rest of the fan control
  surface (see fan entry further below).

### [ ] SD card module → Adafruit Micro SD breakout footprint

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Change the SD connector footprint to match the **Adafruit Micro SD
  breakout** — more reliable on hot-swap than the current module.
- **[~] Deferred — pending bench verification:** remove the 10 kΩ
  resistor currently on the SD card line. Keep in place by default;
  only drop after the Adafruit module proves it isn't needed.

### [ ] External power connectors and silkscreen polish

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- **XT60 board-edge clearance:** the connector body overhangs / doesn't
  seat because the board edge is too close. Move the XT60 inboard or
  extend the board edge in that area. (Interacts with the board-size
  shrink in the mechanical section — re-check after layout.)
- **Banana plug connectors for 12 V and 19 V rails.** 5 V stays on the
  current connector style (no banana plug — avoids extra probe surface
  on a rail with little abs-max margin).
- **Silkscreen polarity marks (+/-) on the 19 V terminals.**
- **Rename silkscreen label "VCC" → "5V"** — ambiguous given the mix
  of 3V3 / 5V / 12V / 19V rails on the board.
- **Label voltage direction on the ambient fan switch** (and on the
  new case fan switch) — which switch position selects which rail.

### [ ] Replace 1N4002 input diodes with Schottky (+ bulk cap at VSYS)

**Filed:** 2026-05-19 · updated 2026-05-22 ·
[chat-log: root cause](../notes/chat-log.md#2026-05-19--external-5-v-supply-starves-vsys--1n4002-drop-traced) ·
[chat-log: chosen part](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes) ·
[memory: project-power-input-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)

- Chosen part: **MBR20100CT** (TO-220, 20 A / 100 V). Massive
  headroom — uses an on-hand part, costs nothing in BOM at this rail.
- Footprint-constrained alternatives if TO-220 doesn't fit: **SS14**
  (SMA 1 A), **1N5817** (DO-41 1 A), **MBRS340** (3 A SMA). Forward
  drop falls from ~0.8 V (1N4002) to ~0.3 V per diode in all cases.
- Evaluate whether the second series diode is needed. If both are
  reverse-polarity protection, drop to a single Schottky.
- Add **1000 µF low-ESR electrolytic + 100 nF ceramic** at Pico VSYS
  pin 39, leads as short as practical, to absorb SD inrush.
- After fab: re-verify per
  [hw-test-log "VSYS rail validation"](../test/hw-test-log.md)
  and revert the interim XL4015 setpoint from 6.0 V back to 5.0 V.

### [ ] Move fans from 2× relays to PCA9685 + IRLZ44N MOSFETs

**Filed:** 2026-05-16 · updated 2026-05-22 ·
[chat-log: 2026-05-22 planning](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes) ·
[memory: project-fan-hardware-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_fan_hardware_revision.md)

- Replace 2-relay fan control with a **PCA9685** 16-ch PWM driver
  on I2C0 (shared with SHT31), each channel driving an **IRLZ44N**
  MOSFET. Frees the two relay GPIOs, scales to 5+ fans, unlocks
  variable speed.
- **Per-fan stage:** PCA9685 channel → series gate resistor (low
  value, ~150 Ω) → IRLZ44N gate. Fan between rail and drain
  (low-side switching); source to GND. **1N4007 (or UF4007) flyback
  diode antiparallel across each fan** to clamp inductive kick on
  spin-down.
- **Socket the PCA9685** (DIP socket, not soldered direct) so the
  chip can be swapped for variant boards or after failure.
- After fans move off relays, **the remaining relays carry only
  230 V mains loads** (grow light, heater). Update relay connector
  spec / spacing / silkscreen accordingly — tracked under the
  "Relay connector cleanup" entry above.
- Planned fan roster: exhaust, growroom walls, growroom center,
  heater distribution, case.
- Steps 1–4 of the suggested build order in the memory entry are
  firmware-side and can land before the PCB arrives.

## Mechanical / enclosure

### [ ] Star-ground topology for heater current return

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-power-input-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)

- Common GND plane stays, but **route HE_MOSFET source pad with a
  wide, short trace directly to the 19V_IN GND pin.** Logic ground
  merges at the input node, not at the MOSFET source.
- Effect: heater switching current (3.4 A or 6.8 A depending on
  channel choice) loops through dedicated copper, not through the
  I²C / RTC / Pico ground return paths. Avoids ground bounce that
  could glitch the bus or reset the MCU.
- Layout-only change; no schematic delta. Mark the keep-out / star
  point in EasyEDA before pour.

### [ ] TO-220 thermal management — copper pour + clip-on heatsink

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-thermal-management](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_thermal_management.md)

- Apply to **every TO-220 power part** carrying significant load.
  Current scope: HE_MOSFET (IRLZ44N, heater). Future scope: any
  TO-220 in the PCA9685 + MOSFET fan stage that isn't socketed.
- **Copper pour:** ≥ 1 sq inch (≈ 25 × 25 mm) of bare copper on
  **both top and bottom layers** under the TO-220 tab pad. Don't
  cover with soldermask — bare copper convects slightly better.
  Stitch top to bottom with **6–10 thermal vias** (0.3 mm drill,
  0.6 mm pad), unsealed (no tenting).
- **Clip-on heatsink:** add **Fischer SK 104-25 STS** (or
  equivalent TO-220 clip-on, ~$0.50) to the BOM and mount on the
  tab. Belt-and-suspenders for sealed-enclosure scenarios.
- Effect: junction-to-ambient thermal resistance falls from ~62 °C/W
  (bare TO-220) to ~20–30 °C/W (pour + heatsink). At 2 W IRLZ44N
  dissipation that's 40–60 °C above ambient — safely in spec.

### [ ] Board size reduction, footprint clearances, enclosure simplification

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Shrink overall board size — current revision is larger than the
  components warrant.
- Reduce enclosure shell from a 4-wall structure to **only 2
  connecting walls** so the smaller PCB sits in a lighter housing.
- **Ambient fan switch mounting holes:** current hole spacing is
  wrong for the actual switch — re-measure and fix.
- **External fan connector** is physically larger than the footprint
  it sits on — widen the footprint or move it.
- The **XT60 board-edge clearance** issue is also tracked under
  "External power connectors and silkscreen polish" in the
  Electrical / PCB section.

## Wiring / harness

### [ ] Sensor cable & external connector moisture protection

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- The PCB and enclosure sit **outside** the greenhouse — no
  conformal coat needed on the board.
- **Greenhouse-side exposure** applies to: RJ12 sensor cables
  (SHT31, CO2, soil ADC), the two ambient fans, the case fan
  (rated for in-case use), and the grow-light DAC cable.
- Use cables and end-fittings rated for high humidity:
  - **RJ12 plugs:** standard nylon plugs are fine inside the case
    but seal the cable-side plug with a small dab of dielectric
    grease where it enters the greenhouse atmosphere.
  - **Fan power leads:** silicone-insulated wire if any fan
    body is mounted inside the high-humidity zone.
  - **Sensor breakouts (SHT31 board, S8 board, etc):** house in
    their own vented-but-shielded sensor enclosures with a
    small desiccant sachet at install time.
- No enclosure-side IP rating required on the main PCB housing.
