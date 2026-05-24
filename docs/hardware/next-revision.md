# Next hardware revision — queued changes

> Canonical, append-only checklist of every change planned for the
> next PCB / enclosure / wiring revision. Read this before opening
> the schematic editor. Per
> [.claude/rules/ecc/common/hardware-revision-notes.md](../../.claude/rules/ecc/common/hardware-revision-notes.md).
>
> Sections follow the EasyEDA workflow: **Schematic** (nets,
> components, BOM) → **PCB layout** (footprints, routing,
> silkscreen, test points) → **PCB ordering** (fabrication
> settings) → **Mechanical / enclosure** → **Wiring / harness**.
>
> Newest item on top within each section. Each item links to the
> `docs/notes/chat-log.md` entry where the root cause / decision
> was captured, so the full rationale is one click away.
>
> Use `[ ]` queued, `[x]` shipped on the new revision, `[~]` deferred
> with a reason in the entry body.

## Schematic — nets, components, BOM

### [x] MCP1416 gate driver for HE_MOSFET (IRLZ44N)

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Current PCB drives IRLZ44N gate directly from Pico GP3 (3.3 V).
  At V_GS = 3.3 V, R_DS(on) is ~0.05–0.08 Ω (linear region, not
  saturated) → ~2 W dissipation at 3.4 A heater current. At 6.8 A
  (parallel-heater option a) the gate-drive shortfall becomes a
  thermal cliff.
- **Add MCP1416T-E/OT** (SOT-23-5, 1.5 A peak, V_DD 4.5–18 V, ~$0.40).
  Drives the MOSFET gate from 0 → 5 V (or 12 V), pushing IRLZ44N
  fully into saturation: R_DS(on) drops to ~0.022 Ω at V_GS = 5 V →
  conduction loss halves (~1 W at 6.8 A vs ~2.5 W direct-drive).
- **Wiring:** Pico GP3 → MCP1416 IN (pin 2) → MCP1416 OUT (pin 5) →
  **R6 = 47 Ω** (was 100 Ω; lower value for faster switching now that
  the driver can source the current) → IRLZ44N gate. **Power MCP1416
  from 5 V** (pin 1 to 5 V, pin 3 to GND, 100 nF decoupling).
- **Add 10 kΩ gate pull-down** from IRLZ44N gate to source/GND so the
  MOSFET stays OFF during Pico boot / reset (otherwise the gate
  floats while GP3 is high-Z and could partially turn on the heater).
- **Side benefit:** GP3 only sources logic-level current (~µA) instead
  of trying to charge a ~2 nF gate through 100 Ω — switching edges
  become clean, EMI improves, no overshoot.
- **PWM-readiness:** the MCP1416 also makes future heater PWM viable
  (see "Heater channel count" entry below) — direct-drive at 3.3 V
  through 100 Ω can't switch fast enough for audio-frequency PWM.

**Comment after implementation**: nc pin seems to ne not-connected? needs review

### [x] Power input connectors → XT60 across all three rails

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Current PCB mixes connectors on the three input rails (5 V Phoenix
  block, 12 V JST B2B-XH, 19.5 V XT60). The 12 V JST B2B-XH is rated
  ~3 A — well under the 12 V buck's 9 A capacity and a fire risk if
  multi-fan load lands on that rail.
- **Standardise on XT60 for all three input rails** (5 V, 12 V, 19.5 V).
  XT60 is rated 30 A continuous, 60 A burst — massive headroom for
  all three rails. Single connector SKU = one cable family in the
  field, one mating-tool requirement, simpler harness build.
- Silkscreen voltage labels and board-edge clearance for all three
  XT60s are tracked under "External power connectors and silkscreen
  polish" in the PCB layout section.

### [ ] 5 V VSYS bulk cap voltage rating upgrade

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Earlier entry pinned the 5 V VSYS bulk cap as **1000 µF / 6.3 V**.
  At 5 V nominal that's **79 % voltage derating** — tight for
  long-life electrolytics, especially with TVS transients reaching
  the clamp voltage before settling.
- **Bump to 1000 µF / 16 V** (or 1000 µF / 10 V minimum). Standard
  value, identical footprint family, ~$0.10 cost delta. Voltage
  derating drops to 31 % (16 V part) — comfortable margin for
  10 000+ h life at 65 °C.
- Same principle applied to the 12 V and 19.5 V bulk caps already
  queued (220 µF / 25 V on 12 V = 48 % derating, 470 µF / 35 V on
  19.5 V = 56 % derating). Both fine as specified.

### [ ] F1 fuse — 10 A 5×20 mm slow-blow (parallel-heater ready)

**Filed:** 2026-05-23 · supersedes earlier "5 A fast-blow" placeholder ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Parallel-heater case (two 100 W / 24 V heaters at 19.6 V) draws
  6.8 A steady-state. Single-heater case draws 3.4 A. Fuse must
  cover both without nuisance trips.
- **F1 = 10 A T (slow-blow), 5×20 mm glass cartridge** in
  through-hole fuse holder. Standard part: **Littelfuse 0234010.MXP**
  (or equivalent 5×20 mm T-rated 10 A).
- T rating tolerates the brief inrush spike on bulk-cap charging
  without nuisance trips, while clearing on a hard short (10 A ×
  I²t for the heater traces at 2 oz / 3 mm is well within trace
  fusing limits).
- **Position:** upstream of D5 per "F1 fuse position" entry above.
  Sequence: `19V_IN → F1 → D5 → bulk cap → HE_MOSFET drain`.

### [ ] MCP6002 op-amp → LM358N + footprint to DIP-8 socket + grow-light gain retune

**Filed:** 2026-05-23 · updated 2026-05-24 (footprint changed from
SOIC-8 to DIP-8 socket to use the LM358N already in stock) ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[chat-log: DIP-8 footprint decision](../notes/chat-log.md#2026-05-24--lm358-footprint-switch-to-dip-8-socket) ·
[memory: project-grow-light-opamp-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_grow_light_opamp_revision.md)

- **Critical — current part is operating above absolute maximum.**
  MCP6002T-I/SN abs-max V_DD-V_SS = **7.0 V**; the schematic powers it
  from the **12 V rail** (pin 8 to 12 V net). Chip degrades silently
  and will fail; explains any flaky grow-light dim behaviour.
- **PCB footprint change:** swap the SOIC-8 land pattern for a
  **DIP-8 socket** footprint (2.54 mm pitch, 7.62 mm row spacing).
  The DIP socket lets the chip be inserted (and swapped if it fails)
  without rework. Costs ~3× the SOIC-8 board area but eliminates a
  procurement step — see "use on-hand stock" below.
- **Use the LM358N (DIP-8) already in stock** (10 pcs on hand per
  [inventory.md](inventory.md), order 3071191067167331). V_CC max
  32 V, pin-compatible with the dual op-amp layout the MCP6002 used.
  Not rail-to-rail at the top, which is a feature here: at 12 V
  supply the output swings to ~10.5 V max, a natural ceiling below
  the 10 V dim-spec damage threshold. **DIP-8 sockets are also
  already in stock** (66-pc socket kit, order 3071191067207331).
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

### [ ] Bulk capacitance on 12 V and 19.5 V rails

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-power-input-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)

- Current PCB has **only 100 nF ceramics** on each rail — no
  electrolytics. Heater switching (3.4 A on the 19.5 V rail) and fan
  inrush (12 V rail, once PCA9685 + MOSFETs land) hammer the rails
  with no bulk capacitance to absorb transients.
- **Add per rail, close to the load:**
  - **19.5 V near D5 / HE_MOSFET:** 470 µF / 35 V low-ESR electrolytic
    in parallel with 100 nF ceramic
  - **12 V near D4:** 220 µF / 25 V low-ESR electrolytic in parallel
    with 100 nF ceramic
  - 5 V VSYS owned by the dedicated entry above (1000 µF / 16 V).
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
  - **19.5 V input:** SMAJ24CA (working voltage 24 V, clamp ~39 V)
- Bidirectional `CA` parts — protects against either polarity, useful
  on the Phoenix terminal block where reversed wiring is plausible.
- **Placement:** just downstream of input connector and series
  Schottky, before the bulk capacitor. ~$0.15 each.

### [ ] Schottky plan — single +rail diode per input; **delete D2 / D3 / D6** (GND-return diodes)

**Filed:** 2026-05-23 · updated 2026-05-24 (topology corrected: drop
GND-return diodes) ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[chat-log: topology correction](../notes/chat-log.md#2026-05-24--input-diode-topology-correction-drop-gnd-return-diodes) ·
[memory: project-power-input-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)

- **Topology correction (2026-05-24):** the current PCB has **one
  1N4002 on each line of every input** — D1 on +5 V / D2 on 5 V GND
  return, D4 on +12 V / D3 on 12 V GND return, D5 on +19.5 V /
  D6 on 19.5 V GND return. Earlier next-rev plan listed all six for
  Schottky replacement; netlist review confirms the **GND-return
  diodes (D2, D3, D6) earn nothing the +rail diode doesn't already
  provide** — a single Schottky on the positive line blocks
  reverse-polarity current the same way, with half the forward drop
  and half the part count.
- **Critical — D5 is currently a fire risk.** D5 is a 1N4002 (1 A
  rated, DO-41) on the 19.5 V → heater path. Heater is 24 V / 100 W →
  5.76 Ω → at 19.6 V draws ~3.4 A. D5 is being run at **3.4× its
  continuous rating**; package dissipation exceeds DO-41 limits.
- **Final diode set on the next revision (3 parts, 2 SKUs):**
  - **D5 → MBR20100CT** (TO-220, 20 A / 100 V) — heater path. Massive
    headroom, very low V_f, large package for the ~1 W dissipation
    at 3.4 A.
  - **D1 (+5 V) and D4 (+12 V) → MBRD1045** (D-PAK / TO-252,
    10 A / 45 V, ~$0.45). Single SKU for both +rail Schottkys. 10 A
    headroom matches rail capacities (5 V/5 A, 12 V/9 A) with safety
    margin; large D-PAK tab assists thermal dissipation.
  - **D2, D3, D6 → deleted.** Connector negative pins tie **directly
    to system GND** (copper trace, no diode). Saves three parts,
    ~0.8 V of return-path drop per rail, three through-hole footprints.
- **Reverse-polarity behaviour after the change:** plug a rail in
  backwards → +line Schottky reverse-biases → no current flows → fails
  safe. Identical protection to the old D+ + D− scheme.
- **Why MBRD1045 over SS54:** SS54 (5 A SMA) was an earlier draft for
  BOM cost, but the 5 V buck is rated 5 A and 12 V buck 9 A — running
  a 5 A SMA part at its limit eats reliability margin. MBRD1045
  doubles current headroom for ~$0.30 extra; single SKU = simpler
  ordering, larger thermal pad, no penalty on V_f.
- V_f drops from ~1.6 V (two 1N4002 in the current loop) to ~0.3 V
  (one Schottky on +line, direct GND return) at every rail —
  eliminates the VSYS-starvation root cause permanently and frees
  ~1.3 V of headroom that the bench workaround currently steals from
  the XL4015 setpoint.
- **Separate SKU on VBUS / DEBUG_CON: SS14** (SMA, 1 A) — listed
  under the "VBUS + DEBUG_CON 5 V backfeed protection" entry below.
  Different package, ~10 mA peak current, no benefit upgrading.
  Three Schottky SKUs total on the board (MBR20100CT, MBRD1045,
  SS14).
- **Post-fab cleanup:** revert the interim XL4015 buck setpoint from
  6.0 V back to 5.0 V once the swap is verified per
  [hw-test-log "VSYS rail validation"](../test/hw-test-log.md).
  Footprint-constrained fallback parts if MBR20100CT / MBRD1045
  cannot be sourced: SS14 (SMA, 1 A), 1N5817 (DO-41, 1 A), MBRS340
  (SMA, 3 A) — V_f benefit holds in all cases.

### [ ] F1 fuse position — upstream of D5

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Current netlist order is **19V_IN → D5 → F1 → HE_CON**. A shorted
  D5 dumps all 19.5 V before F1 can react.
- **Correct order:** `19V_IN → F1 → D5 → bulk cap → HE_MOSFET drain
  → HE_CON`. Fuse goes first, then series diode, then load chain.
- **Fuse spec:** see "F1 fuse — 10 A 5×20 mm slow-blow" entry above
  for the chosen part. Same fuse covers both single-heater and
  parallel-heater operation.

### [ ] Heater channel count — single-MOSFET, parallel heaters, PWM-later

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- **Decision: single MOSFET channel (option a).** Two 100 W / 24 V
  heaters wired in parallel on the one HE_MOSFET output, controlled
  by Pico GP3 through the MCP1416 gate driver. Heaters always run
  together — the goal is to spread heat over more surface area, not
  selective control.
- Total current = 6.8 A on the 19.5 V rail. Handled by:
  - F1 = 10 A 5×20 mm T-rated (entry above)
  - D5 = MBR20100CT 20 A (Schottky entry above)
  - IRLZ44N with MCP1416 gate driver at 5 V V_GS → R_DS(on) ~0.022 Ω
    → ~1 W package dissipation, manageable with the TO-220 thermal
    pour + clip-on heatsink (TO-220 thermal entry in the PCB layout
    section)
  - 3 mm heater-path trace on 2 oz copper (see "Power trace widths"
    in PCB layout and "PCB fab order — 2 oz copper" in PCB ordering)
  - 16 AWG harness from F1 to HE_CON
- **Heater PWM is planned for a later firmware revision.** The
  MCP1416 gate driver (entry above) makes audio-frequency PWM
  electrically viable on GP3 — the current direct-3.3 V drive cannot
  switch the gate fast enough for clean PWM at any useful frequency.
  Schematic / PCB land the gate driver now; firmware adds PWM duty
  control when the control loop wants finer modulation than on/off.
- **Why not option b (dual channel):** graceful degradation isn't
  worth a second MOSFET + driver + fuse + GPIO on a heater stage
  the operator runs in tandem anyway. Revisit if a use case for
  selective control ever appears.

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
  pin of INT_CON and on the 5 V pin of DEBUG_CON. SS14 sits in its
  own SKU (D1–D4/D6 are MBRD1045 D-PAK) — different package because
  these are signal-header low-current paths, not rail-protection
  diodes.
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
  - 19.5 V rail: 8.2 kΩ (2.2 mA)
- Different resistor values per rail are intentional — uniform
  current is more useful than a uniform BOM line at this scale.

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
- (The 10 kΩ pull-up originally noted on GP12 in this batch belongs
  electrically with the SD section — GP12 is SD-MISO. Moved to the
  [SD module entry](#--sd-card-module--adafruit-4682-3-v-micro-sd-spisdio-bypass).)

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
- **Add one more outward-facing RJ12 connector** for an additional
  I²C drop on the enclosure wall. Bus topology (one I²C bus vs two)
  stays flexible — the requirement is a second exposed jack so future
  I²C peripherals don't need bus stubs through the case.
- Silkscreen rename for the existing port (`I2C con_1` → `SHT31`)
  tracked under "I²C address map on silkscreen" in the PCB layout
  section.

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

### [ ] SD card module → **Adafruit 4682** (3 V Micro SD SPI/SDIO Bypass)

**Filed:** 2026-05-22 · updated 2026-05-24 (full module swap delta) ·
[chat-log: original footprint note](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes) ·
[chat-log: SD-MISO pull-up correction](../notes/chat-log.md#2026-05-24--sd-miso-pull-up-correction-supersedes-the-cs-draft) ·
[chat-log: module switch + 74LVC125 correction](../notes/chat-log.md#2026-05-24--sd-card-module-switch--azdelivery--adafruit-4682) ·
[memory: project-sd-card-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_sd_card_revision.md)

**Chosen part:** [Adafruit 4682 "Micro SD SPI or SDIO Card Breakout
Board — 3V ONLY!"](https://www.adafruit.com/product/4682) — the 3 V
bypass variant of the older Adafruit 254. Replaces the current
AZDelivery generic SPI Reader module on the next PCB.

Verbatim spec (Adafruit product + pinouts pages, 2026-05-24 fetch):

- "For use with 3V power and logic microcontollers only!"
- "does not have level shifters" — no 74LVC125 / no LDO regulator.
- Pinout SPI mode: `3V, GND, CLK, SO, SI, CS, DET` (+ SDIO-only
  `D1, DAT2, D3` available on the SDIO-side pads).
- "Pull ups are provided on all SPI logic pins" (value not published).
- "DET — Detect whether a microSD card is inserted" with a 4.7 kΩ
  pull-up resistor on board.
- Dimensions: 25.4 × 22.8 × 3.5 mm, 2.5 g.

**Footprint / connector change:**

- Replace the current AZDelivery-shaped land pattern with a header
  matching the 4682's pinout. Single-row, 7-pin in SPI mode (8 pins
  if DAT2 is exposed for the SDIO upgrade path). Spacing per the
  4682 mechanical drawing.
- Mounting hole(s) per the 4682 mechanical drawing — confirm on the
  bench part before committing layout.

**Power rail change (current PCB → next rev):**

- AZDelivery module accepts 5 V through an onboard AMS1117-3.3 LDO.
  4682 has **no regulator** and requires 3.3 V directly.
- **Move the SD module power net from `5V` to `3V3`.** This adds the
  SD module's ~50–100 mA (peaks to ~200 mA on inrush) to the Pico
  RT6150 buck-boost 3V3 rail. With Pico, SHT31, DS3231, SSD1306 ×2,
  MCP4725, and future PCA9685 also on 3V3, the 800 mA reg budget is
  still comfortable but worth a bench re-measurement once PCA9685
  lands.
- **Add 100 µF electrolytic + 100 nF ceramic decoupling pair at the
  4682's `3V` pad**, leads as short as practical. The
  [VSYS 1000 µF bulk cap](#--5-v-vsys-bulk-cap-voltage-rating-upgrade)
  helps the 5 V rail upstream but no longer decouples SD inrush from
  the 3V3 node where it now lives.

**Onboard pull-ups + Pico-side MISO pull-up:**

- 4682 has onboard pull-ups on every SPI logic line (value
  unpublished). Both ends of each pin are the same electrical node
  because there's no level shifter — the prior version of this entry
  described a 74LVC125 + "card-side" pull-ups, which is the
  **Adafruit 254**, not the 4682. Corrected
  [in the 2026-05-24 chat-log](../notes/chat-log.md#2026-05-24--sd-card-module-switch--azdelivery--adafruit-4682).
- **Add an external 10 kΩ 0603 from GP12 (MISO) to 3V3.** Not on the
  current PCB. Reason: MISO is tri-stated by the card outside response
  windows — CS high, no card inserted, or during the 80+ dummy clocks
  the host sends before CMD0. With MISO floating, the Pico's SPI
  peripheral latches garbage (0x00 / 0xFF / noise depending on board
  capacitance) and the init state machine in `lib/sdcard.py` either
  reads a false response or misses the real one. A 10 kΩ pull-up
  establishes a defined idle-high state — matches the SPI mode
  convention ("no response yet" reads as 0xFF, which is what the
  timeout logic expects). Coexists cleanly with R8 (33 Ω MISO damper):
  R8 sits in series for edge damping, the 10 kΩ is a shunt to 3V3 on
  the Pico side. Parallel with the unspecified onboard pull-up the
  combined value stays well inside SD spec (≤ 100 kΩ on DAT lines).
  One resistor, ~$0.01 BOM, eliminates a real SPI-init failure mode.
- **No external pull-ups on CS / MOSI / SCK.** R8 = 33 Ω MISO damper
  and R10 = 33 Ω MOSI damper stay per the
  [R8 entry](#--r8-stays--fix-the-firmware-comment-not-the-schematic).

**Card-detect (DET) wiring — new capability:**

- Wire **DET → GP15** (free per
  [config.py:55-98](../../config.py#L55-L98); adjacent to the SPI
  block GP10–GP13, keeps the SD signal cluster compact). Firmware
  reads DET to distinguish "no card present" from "card present but
  mount failed" — neither distinguishable today on the AZDelivery
  module.
- New `DEVICE_CONFIG["pins"]["sd_detect"]` entry, matching
  `validate_config()` row, and a `tests/test_config.py` row per
  [configurability.md](../../../.claude/rules/ecc/common/configurability.md).
  `HardwareFactory` and the
  [SD recovery loop](../../main.py) consume it to short-circuit
  retries when the card is absent.
- DET polarity (open = no card vs. inserted = pulled low, or
  vice-versa) confirmed on a bench unit before firmware wiring.
  Mechanical detect schemes differ between socket vendors.
- **Hot-swap recovery code must be refactored once DET is live.**
  The current loop at
  [main.py:942-981](../../main.py#L942-L981) polls
  `refresh_sd()` (block-level `readblocks` over SPI) every
  health-check interval whenever `is_primary_available()` is false
  *or* `buffered > 0`. That's the only mechanism available today —
  the AZDelivery module can't report card presence at all, so the
  firmware has to probe the bus to find out. Once GP15 reads DET,
  the loop should:
  1. Skip `refresh_sd()` entirely when DET reads "no card" — save
     the SPI traffic, the CPU cycles, and the misleading
     `logger.warning("SD card not accessible, retrying soon")`
     entries that today fire even when the operator has
     deliberately pulled the card.
  2. Trigger an immediate remount attempt on the DET edge from
     "absent → present" instead of waiting up to
     `sd_recovery_interval_s = 10 s` for the next health-check tick.
  3. Surface three distinct states to `StatusManager` —
     `no_card_inserted` (DET says absent), `mounted` (DET says
     present + `is_primary_available() == True`), and
     `mount_failed` (DET says present + mount failed) — instead of
     today's binary `sd_status` flag. The `sd_problem_led`
     behaviour and the boot-time `require_sd_startup` reset path
     should both branch on the new states so a missing card lights
     a different indicator than a bus fault.

  Treat this as a firmware-only follow-up that lands **after** the
  new PCB lands and DET polarity is confirmed on the bench — not
  part of the hardware change itself. The refactor ships as its
  own commit per
  [commit-granularity.md](../../../.claude/rules/ecc/common/commit-granularity.md),
  separate from the `sd_detect` config + factory wiring commits.

**Firmware / config implications (next-rev firmware sweep):**

- SPI pin assignments unchanged: GP10/11/12/13 stay as
  SCK/MOSI/MISO/CS per
  [config.py:108-115](../../config.py#L108-L115). The 4682's CS pin
  maps 1:1.
- Timing constants stay as-is until bench measurement:
  `sd_power_up_ms = 1500`, `sd_mount_retries = 3`,
  `sd_retry_delay_ms = 1000`, `spi.baudrate = 10_000_000`. The
  4682's cold-start envelope should be **at least as fast** as the
  AZDelivery (no LDO ramp, no buffer init), so the existing values
  are conservative. Don't pre-tune speculatively — measure first.
- The `spi.baudrate = 10 MHz` cap (versus the RP2040 ceiling of
  ~40 MHz) is from the
  [2026-05-16 R8 incident](../notes/chat-log.md#2026-05-16-18--sd-bit-error-incident) — the module swap does not unblock raising it; that
  would need a separate signal-integrity pass on the rebuilt board.
- `lib/sdcard.py` driver is unchanged — SPI-mode SD protocol is
  identical between breakouts.

**Verification:** post-fab eyes-on checklist in
[hw-test-log.md "SD module swap"](../test/hw-test-log.md).

**Inventory:** see
[inventory.md → SD card storage](inventory.md) for the new line
item (Adafruit 4682 to order; AZDelivery module not currently
catalogued).

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
  spec accordingly — tracked under the "Relay connector cleanup"
  entry above; spacing / clearance / silkscreen polish for the
  mains-only relay connector picked up at the PCB layout stage.
- Planned fan roster: exhaust, growroom walls, growroom center,
  heater distribution, case.
- Steps 1–4 of the suggested build order in the memory entry are
  firmware-side and can land before the PCB arrives.

## PCB layout — footprints, routing, silkscreen, test points

### [ ] Power trace widths and default clearance

**Filed:** 2026-05-23 · split from earlier combined "PCB stackup" entry ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- **Heater current path (19.5 V rail, F1 → D5 → bulk cap → HE_MOSFET
  drain → HE_CON):** **3 mm minimum trace width** on 2 oz copper
  (handles 6.8 A parallel-heater case at <30 °C rise per IPC-2221).
  Pour copper rather than narrow traces where possible.
- **12 V buck output trace (D4 → 12 V rail):** **2.5 mm minimum** on
  2 oz copper (handles 9 A buck capacity at <30 °C rise).
- **Default clearance: 0.15 mm** (was 0.2 mm). Frees layout real
  estate for the bulk caps + TVS + new gate driver footprints near
  the input area. Safe for all sub-50 V nets on this board.
- **Power traces keep 0.3 mm clearance** to the adjacent net for
  fault-current robustness (one wider trace among the dense signal
  net).
- All trace-width math above assumes the 2 oz copper outer layers
  set in the [PCB fab order entry](#--pcb-fab-order--2-oz-copper-outer-layers)
  under PCB ordering.

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

### [ ] Test-point row near input area

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- **Eight labelled THT pads** in a 2.54 mm-pitch row near the input
  regulators: `3V3 / 5V / 12V / 19.5V / GND / GND / SDA / SCL`.
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
- **Rename silkscreen label `I2C con_1` → `SHT31`** on the existing
  RJ12 port — it carries exactly one sensor, so the device name is
  more informative than the generic bus label. (Connector swap and
  the second outward bus are queued under "I²C / RJ12 connector
  layout" in the Schematic section.)
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

### [ ] External power connectors and silkscreen polish

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- **XT60 board-edge clearance:** the original 19.5 V XT60 body
  overhangs / doesn't seat because the board edge is too close. Now
  that all three rails are XT60 (see Schematic section), move each
  XT60 inboard or extend the board edge in that area, and re-check
  clearance for all three after layout. (Interacts with the
  board-size shrink below in this section.)
- **Silkscreen voltage labels next to each XT60:** `5V`, `12V`,
  `19.5V`, plus `+` / `-` polarity marks on all three. XT60 is keyed
  but polarity-label redundancy catches reversed crimps during
  harness assembly.
- **Rename silkscreen label "VCC" → "5V"** — ambiguous given the mix
  of 3V3 / 5V / 12V / 19.5V rails on the board.
- **Label voltage direction on the ambient fan switch** (and on the
  new case fan switch) — which switch position selects which rail.

### [ ] Board size reduction, footprint clearances, enclosure simplification

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Shrink overall board size — current revision is larger than the
  components warrant.
- Reduce enclosure shell from a 4-wall structure to **only 2
  connecting walls** so the smaller PCB sits in a lighter housing.
  (Enclosure-side change tracked here alongside the board shrink
  that motivates it; see Mechanical / enclosure section if a
  standalone enclosure entry is later split out.)
- **Ambient fan switch mounting holes:** current hole spacing is
  wrong for the actual switch — re-measure and fix.
- **External fan connector** is physically larger than the footprint
  it sits on — widen the footprint or move it.

## PCB ordering — fabrication settings

### [ ] PCB fab order — 2 oz copper outer layers

**Filed:** 2026-05-23 · split from earlier combined "PCB stackup" entry ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- **Fab order: 2 oz copper on both outer layers** (up from default
  1 oz). Roughly doubles current-carrying capacity per mm of trace
  width and improves the TO-220 thermal pour effectiveness. Cost
  delta on JLCPCB / EasyEDA is small at production quantities.
- The trace-width and clearance design rules in the
  [Power trace widths](#--power-trace-widths-and-default-clearance)
  entry under PCB layout assume this 2 oz stackup — order them
  together.

## Mechanical / enclosure

> No standalone entries currently queued. Star-ground topology and
> TO-220 thermal management are board-level routing changes and
> moved to **PCB layout**; the enclosure-shell simplification and
> ambient-fan-switch mounting-hole fix ride along with the
> [Board size reduction](#--board-size-reduction-footprint-clearances-enclosure-simplification)
> entry under PCB layout since the board shrink motivates them.
> Future enclosure-only items (lid, gland fittings, vent cutouts)
> belong here.

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
