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

### [ ] Hydroponics monitoring — 2nd I²C bus, DS18B20, pH/EC, wet-system relays

**Filed:** 2026-05-31 ·
[chat-log entry](../notes/chat-log.md#2026-05-31--hydroponics-monitoring-expansion-dwc--hpa-aeroponics) ·
[memory: project-hydro-automation-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_hydro_automation_revision.md)

Future-proofs the board for an automated **DWC reservoir now** and
**HPA aeroponics later**. Scope is deliberately small: closed-loop on
**water temperature only** (manual top-off, no chiller), **pH/EC
monitor-only** (no dosing), all wet-system pumps/heater on **230 V
relays**. No new MCU, no GPIO expander — rides repurposed pins and the
spare PCA9685 channels already on the board.

**1 — Second I²C bus (I²C1) on GP26/GP27.** The as-built 2026-05-31
board has no unrouted GPIO; RP2040 maps I²C1 only to (GP18,GP19) or
(GP26,GP27) here. Use **GP26 = I²C1 SDA, GP27 = I²C1 SCL** (REL_CON1
pins 7 & 8 — the two never-loaded "reserved" relays).

- **Delete R17 (GP26→+5 V) and R16 (GP27→+5 V).** These are the relay
  inactive-state pull-ups to +5 V; left in place, I²C idle would put
  5 V on the Pico pins → abs-max violation.
- **Add two I²C pull-ups to 3V3** on GP26 (SDA) and GP27 (SCL),
  2.2 kΩ (mirror R11/R13 on I²C0); 4.7 kΩ acceptable for the shorter
  in-case I²C1 run.
- **Break GP26/GP27 out to a dedicated I²C1 connector** (RJ12 or
  4-pin JST: `3V3 / GND / SDA / SCL`), not REL_CON1 pins 7-8. REL_CON1
  drops to 5 functional channels (GP18,19,20,21,22).
- Firmware: `machine.I2C(1, sda=Pin(26), scl=Pin(27), freq=400000)`.

**1b — Move the surviving relay pull-ups (R18–R22) from +5 V to 3V3.**
R16/R17 above are deleted, but R18–R22 (GP18/19/20/21/22 relay lines)
keep their 10 kΩ pull-ups — **re-reference them from +5 V to 3V3**.

- **Why:** the pull-up only has to hold an active-low relay input at
  its *inactive* HIGH during Pico boot/reset Hi-Z. The Pico's own
  driven-high is 3.3 V, so a 3V3 pull-up matches the level the GPIO
  drives anyway and is already proven to hold these relays off.
- **5 V is electrically wrong here, even though it "works" today:**
  during boot Hi-Z the GPIO ESD clamp shoulders ~0.14 mA at ~3.6–
  3.8 V (the same slow pin-degradation mechanism fixed on the
  [CO2 UART RX](#x-senseair-s8-uart-rx-level-protection)); when the
  pin is driven HIGH (relay off) ~0.17 mA per line backfeeds 5 V into
  the 3.3 V output stage. Lower urgency than the R16/R17 I²C fault,
  but the correct and consistent choice with no downside.
- **Keep R18–R22 = 10 kΩ; only the rail changes** (+5 V → 3V3). After
  this, every Pico-facing pin on the relay header + GP2_CON is a clean
  3.3 V domain.

**2 — DS18B20 water-temperature 1-Wire bus on GP2.** Repurpose
GP2_CON (currently `GND / +5V / GP2`).

- **Change GP2_CON power pin from +5 V to +3V3** so the open-drain
  1-Wire data line never exceeds 3.3 V (DS18B20 runs 3.0–5.5 V).
- **Add 4.7 kΩ pull-up from GP2 to 3V3.**
- One bus carries **multiple DS18B20** (reservoir + root-zone probes),
  each addressed by its 64-bit ROM. Foundational — **both pH and EC
  need water temp for compensation.**

**3 — pH/EC monitoring on I²C1 (Atlas EZO + isolators).**

- **Atlas EZO-pH** (default 0x63) and **EZO-EC** (default 0x64) in
  I²C mode, off-board modules. ~50 € each (DE).
- **One Atlas inline voltage isolator per probe** (galvanic DC/DC +
  digital isolator) — mandatory to break the reservoir ground loop;
  un-isolated twin probes in one tank interfere. ~25 € each. Fallback
  if budget forces it: isolate pH only, accept some EC coupling
  (documented in chat-log, not recommended).
- PCB only needs the I²C1 connector + 3V3/GND from item 1; the EZO
  modules + isolators live in the dry enclosure above the reservoir.
- New silkscreen address rows `(0x63)` pH, `(0x64)` EC under the
  [I²C address-map entry](#--ic-address-map-on-silkscreen) — note
  these are on **I²C1**, a separate bus from the 0x36/0x3C/0x40/0x44/
  0x60/0x68 group on I²C0.

**4 — Wet-system actuators on spare mains relays (no new GPIO).**

- **Air pump** (DWC dissolved-O₂), **reservoir heater** (230 V
  aquarium type), and **HPA pump** (230 V, self-regulating via its own
  pressure switch + accumulator) → spare relay channels GP18 / GP19 /
  GP21 / GP22 on the mains-rated REL_CON1 (see
  [Relay connector cleanup](#x-relay-connector-cleanup--pull-ups-gnd-fix-mains-rated-header)).
- **No new PCA9685 + MOSFET DC stages required.** PWM5–15 stay in
  reserve; an HPA burst solenoid is added there (12/24 V DC →
  PCA9685 ch + IRLZ44N + UF4007 flyback) only if true HPA mist-burst
  timing is later wanted. A 230 V burst solenoid would instead take a
  relay channel.
- **No chiller** (impractical at 20 L); water temp is monitor + alarm
  via the existing buzzer/LED surface plus the relay heater.

**5 — Water-level switch (monitor + alarm only, no top-off loop) on GP28.**
A single simple float/level switch — a dry-contact (reed or tilt) SPST
that **closes the circuit when the water crosses the sensor level** —
gives the controller a low-water (and/or high-water) alarm without
reinstating any automatic top-off. Top-off stays **manual**; this only
makes the reservoir running dry *visible* (buzzer/LED + logged event)
instead of silent between daily checks. Refines, does not reverse, the
"no float-switch loop" decision (which deleted the solenoid/top-off-pump
*actuation*, not a passive sense input).

- **Pin: GP28** — freed by the
  [soil-sensor STEMMA swap](#x-soil-moisture-sensor--adafruit-stemma-4026-i2c)
  (that entry deletes `adc_input: 28`). Used here as a plain digital
  input, not ADC. Depends on the STEMMA swap shipping on the same
  revision; if GP28 is kept analog for any reason, fall back to a spare
  mains-relay channel reused as an input (lower preference — those are
  earmarked for wet-system actuators).
- **Add a 10 kΩ pull-up from GP28 to 3V3** so the line is a defined
  HIGH when the float contact is open and pulled LOW when the float
  closes to GND. Don't rely on the Pico's internal pull-up alone over a
  metres-long wet-zone cable.
- **Add a series ~1 kΩ + 100 nF to GND at the pin** (RC ≈ 100 µs) to
  debounce float chatter at the threshold and shunt ESD/transients off
  the long cable; firmware adds a software debounce on top.
- **New 2-pin connector** (`GP28 / GND`, e.g. 2-pin JST) for the
  switch. Dry-contact, low-voltage — no relay, no mains, no MOSFET.
- Float must be **plastic-bodied** (no second grounded metal object in
  the reservoir, per the wet-zone single-point-ground note); switch
  polarity (which physical state closes the contact) is handled in
  firmware, so either a normally-open "closes when low" or a
  normally-closed float works.

**Config / firmware (queued, lands with the new PCB):**

- `DEVICE_CONFIG["pins"]`: add `i2c1_sda: 26`, `i2c1_scl: 27`,
  `onewire_water: 2`, `water_level: 28`; document GP26/GP27 leaving
  the relay block and GP28 being reclaimed from the dropped ADC soil
  probe.
- New section `water_level_monitor` (`enabled`, `active_low`,
  `alarm_on` = `"low"`/`"high"`/`"both"`, `debounce_ms`, internal
  `pull` fallback) with a `validate_config()` row + `tests/test_config.py`
  row per
  [configurability.md](../../../.claude/rules/ecc/common/configurability.md);
  new `lib/water_level_monitor.py` reads the debounced pin, raises the
  existing buzzer/LED alarm, and logs an `EventLogger` row on each edge.
  **Monitor-only — never drives a pump/solenoid.**
- New sections `water_temp_logger` (1-Wire, per-probe ROM map),
  `ph_logger` (`i2c_bus: 1`, `i2c_address: 0x63`),
  `ec_logger` (`i2c_bus: 1`, `i2c_address: 0x64`), each with
  `validate_config()` rows + `tests/test_config.py` rows per
  [configurability.md](../../../.claude/rules/ecc/common/configurability.md).
- New loggers `lib/water_temp_logger.py`, `lib/ph_logger.py`,
  `lib/ec_logger.py`; I²C1 + 1-Wire init in `hardware_factory`;
  CSV trees under `sensor_root` (`water_temp`, `ph`, `ec`).
- Accepted risk: HPA mist timing lives in firmware only; WDT reset
  drops mist during boot. User accepts (>10 d uptime, daily checks) —
  no hardware dead-man fallback fitted.

**Verification:** post-fab checklist in
[hw-test-log "Hydroponics monitoring bring-up"](../test/hw-test-log.md).

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

### [x] 5 V VSYS bulk cap voltage rating upgrade

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

### [x] F1 fuse — 10 A 5×20 mm slow-blow (parallel-heater ready)

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

### [x] MCP6002 op-amp → LM358N (DIP-8) + grow-light gain retune

**Filed:** 2026-05-23 · updated 2026-05-24 (chose DIP-8 LM358N to use
the part already in stock) ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[chat-log: DIP-8 footprint decision](../notes/chat-log.md#2026-05-24--lm358-footprint-switch-to-dip-8-socket) ·
[memory: project-grow-light-opamp-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_grow_light_opamp_revision.md)

- **Critical — current part is operating above absolute maximum.**
  MCP6002T-I/SN abs-max V_DD-V_SS = **7.0 V**; the schematic powers it
  from the **12 V rail** (pin 8 to 12 V net). Chip degrades silently
  and will fail; explains any flaky grow-light dim behaviour.
- **Use the LM358N (DIP-8) already in stock** (10 pcs on hand per
  [inventory.md](inventory.md), order 3071191067167331). V_CC max
  32 V, pin-compatible with the dual op-amp layout the MCP6002 used.
  Not rail-to-rail at the top, which is a feature here: at 12 V
  supply the output swings to ~10.5 V max, a natural ceiling below
  the 10 V dim-spec damage threshold. **DIP-8 sockets are also
  already in stock** (66-pc socket kit, order 3071191067207331) so
  the chip can be inserted and swapped without rework.
- **Retune feedback divider** for clean 0–10 V output from the 0–3.3 V
  DAC: **R4 = 10 kΩ, R5 = 4.7 kΩ** → gain = 1 + 10/4.7 = 3.13 →
  V_out_max = 3.3 × 3.13 = **10.3 V**. Firmware clips to 10 V via
  `growlight.max_level_pct` (already 91 %, which equates to ~9.4 V at
  the new gain — well within spec).
- PCB footprint change (SOIC-8 land pattern → DIP-8 socket) tracked
  under "MCP6002 → LM358N — DIP-8 socket footprint" in the PCB
  layout section.
- Verify with [hw-test-log](../test/hw-test-log.md) post-fab: sweep
  DAC 0 → 0xFFF, measure GL_DIM+ output, confirm monotonic + clean
  ramp.

### [x] Senseair S8 UART RX level protection

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

### [x] Bulk capacitance on 12 V and 19.5 V rails

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

### [x] TVS clamp diodes on all three power inputs

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[memory: project-power-input-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)

- Three TVS diodes, same SMA-family footprint, three values:
  - **5 V input:** SMAJ5.0CA (working voltage 5 V, clamp ~9 V)
  - **12 V input:** SMAJ15CA (working voltage 15 V, clamp ~24 V)
  - **19.5 V input:** SMAJ24CA (working voltage 24 V, clamp ~39 V)
- Bidirectional `CA` parts — protects against either polarity, useful
  on the Phoenix terminal block where reversed wiring is plausible.
- **Position in input chain:** netlist order is `input connector →
  series Schottky → TVS → bulk cap → load`. ~$0.15 each.

### [x] Schottky plan — single +rail diode per input; **delete D2 / D3 / D6** (GND-return diodes)

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
    to system GND** (no series diode in the return path). Saves
    three parts, ~0.8 V of return-path drop per rail, and three
    through-hole positions on the board.
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

### [x] F1 fuse position — upstream of D5

**Filed:** 2026-05-23 ·
[chat-log entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review)

- Current netlist order is **19V_IN → D5 → F1 → HE_CON**. A shorted
  D5 dumps all 19.5 V before F1 can react.
- **Correct order:** `19V_IN → F1 → D5 → bulk cap → HE_MOSFET drain
  → HE_CON`. Fuse goes first, then series diode, then load chain.
- **Fuse spec:** see "F1 fuse — 10 A 5×20 mm slow-blow" entry above
  for the chosen part. Same fuse covers both single-heater and
  parallel-heater operation.

### [x] Heater channel count — single-MOSFET, parallel heaters, PWM-later

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

### [x] R3 corrected to 10 kΩ pull-down on GP14 buzzer line

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

### [x] I²C pull-ups R1/R2 → 2.2 kΩ for 400 kHz fast-mode rise time

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

### [x] Brownout supervisor on Pico RUN line

**Filed:** 2026-05-23 · updated 2026-05-26 (part-number suffix + button-conflict resistor) ·
[chat-log: original entry](../notes/chat-log.md#2026-05-23--easyeda-files-design-review) ·
[chat-log: 2026-05-26 wiring clarification](../notes/chat-log.md#2026-05-26--brownout-supervisor-part--wiring-clarification)

- RP2040 internal POR threshold is ~2.0 V. A slow rail droop that
  doesn't cross 2.0 V can latch the MCU in undefined state — won't
  reset, won't recover.
- Add a **MAX809TEUR+T** (or **TPS3839K33**) on RUN (Pico pin 30).
  ~3.08 V reset threshold (MAX809**T** suffix — 3.08 V typ), ~$0.30,
  SOT-23-3. Earlier draft listed MAX809**L**EUR+T, which is the
  4.63 V variant intended for 5 V rails — wrong threshold for the
  3.3 V rail this monitors.
- **Wiring (SOT-23-3 pinout):** pin 1 (GND) → board GND; pin 3
  (VCC) → 3V3 rail; pin 2 (/RESET) → **1 kΩ series resistor** →
  Pico RUN (pin 30). 100 nF ceramic between pin 3 and pin 1, close
  to the package.
- **Why the 1 kΩ series resistor:** MAX809T (and TPS3839K33) have
  **push-pull** /RESET outputs. The reset button queued under
  "Button connector rework" also wires RUN to GND. Without a series
  resistor, pressing the button while the supervisor drives high
  shorts the supervisor's high-side transistor to GND. The 1 kΩ
  limits the short-circuit current to ~3.3 mA during a press,
  while still letting the supervisor pull RUN below the Pico's
  logic-low threshold against the internal ~50 kΩ pull-up
  (divider = 1 k / 51 k ≈ 0.06 V at RUN). Alternative if the
  series R is unwelcome: swap to an open-drain supervisor
  (e.g. MAX6328) and let supervisor + button wire-OR directly
  onto RUN.
- Effect: rail droop below 3.08 V forces a clean reset; firmware
  watchdog catches the rest. Improves stability across the
  weeks-of-uptime envelope.

### [x] VBUS + DEBUG_CON 5 V backfeed protection

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

-> Removed vbus and 5v pins from corresponding headers. SS14 in BOM seems unnecessary

### [x] Power-good LEDs — 2 mA current target across all rails

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

### [x] R8 stays — fix the firmware comment, not the schematic

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

**Comment:** The 33 ohm Resistor on MISO was never questioned, but the 10k Pull-Up resistor from SPI_RX to 3V3 that has been soldered in afterwards.

### [x] Button connector rework — menu_btn debounced, reset_btn direct

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

**Comment**: 100nf Capacitor implemented on Button breakout board. check if the pull-up resistor here is appropriate.

### [x] Relay connector cleanup — pull-ups, GND fix, mains-rated header

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Add a **10 kΩ pull-up on each relay IN line** to the relay module's
  VCC, so inputs sit at the inactive (HIGH) level during Pico boot
  and reset (active-low relays).
- The "3V3" pin on the current relay connector goes nowhere (dead).
  **Tie it to GND** so the connector pinout is meaningful.
- After fans move to PCA9685 + IRLZ44N (see fan entry below), the
  remaining relays carry **only 230 V mains loads** (grow light,
  heater). **Replace the current low-voltage header with a
  mains-rated connector** (BOM swap).
- Connector orientation flip and mains-rated trace spacing /
  creepage clearance are tracked under "Relay connector — orientation
  flip + mains-rated spacing" in the PCB layout section.

### [x] I²C / RJ12 connector — swap DHT21 port to RJ12 + add second outward bus

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

### [x] Soil moisture sensor → Adafruit STEMMA #4026 (I²C, 0x36)

**Filed:** 2026-05-22 · superseded 2026-05-26 (analog probe + divider
plan dropped; switch to I²C STEMMA after the 2026-05-15 NE555 dead-end) ·
[chat-log: original analog plan](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes) ·
[chat-log: 2026-05-15 NE555 sensor dead](../notes/chat-log.md#2026-05-15--capacitive-soil-sensor-unresponsive--ne555-unit-replace) ·
[chat-log: 2026-05-26 STEMMA swap](../notes/chat-log.md#2026-05-26--soil-sensor-swap--adafruit-stemma-4026-i2c) ·
[memory: project-soil-sensor-revision](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_soil_sensor_revision.md)

**Chosen part:** [Adafruit STEMMA Soil Sensor #4026](https://www.adafruit.com/product/4026)
— I²C capacitive moisture + temperature sensor, onboard Seesaw
ATSAMD10, default address **0x36** (jumper-selectable 0x36–0x39 if a
bus collision ever appears), 3V3 powered at ~5 mA typical. Replaces
the dead NE555-based analog probe and removes the need for the
earlier 10 kΩ + 15 kΩ ADC divider entirely.

- **Bus:** I²C0 (shared with SHT31 0x44, DS3231 0x68, MCP4725 0x60,
  SSD1306 0x3C, future PCA9685 0x40). Adds one more device — well
  inside the bus capacity once
  [R1/R2 drops to 2.2 kΩ for 400 kHz](#x-ic-pull-ups-r1r2--22-k-for-400-khz-fast-mode-rise-time)
  ships. New address mapped under
  [the silkscreen address-map entry](#--ic-address-map-on-silkscreen).
- **Wiring:** SDA, SCL, 3V3, GND through one of the
  [outward-facing RJ12 / I²C drops](#x-ic--rj12-connector--swap-dht21-port-to-rj12--add-second-outward-bus).
  The breakout exposes both STEMMA QT (JST-SH) and 0.1″ headers —
  cable side decided at harness build.
- **GP28 / ADC2 freed.** No analog soil probe means no divider, no
  ADC_VREF gotcha, no 5 V → 3.3 V step-down problem. `adc_input: 28`
  and the `adc_dry_raw` / `adc_wet_raw` keys are queued for removal
  in the firmware-side rewrite (below). The pin becomes available
  for any future analog peripheral.
- **Firmware change queued (separate commit, lands with the new
  PCB):** [lib/soil_logger.py](../../lib/soil_logger.py) rewritten
  to read the Seesaw `touch_read` (channel 0) and the on-chip
  temperature register over I²C instead of polling an ADC.
  Calibration semantics **invert** versus the resistive-probe model:
  with the capacitive Seesaw, **higher raw = wetter** (typical air
  ≈ 200–400, fully saturated soil ≈ 1000–1500). Header becomes
  `Timestamp,SeesawRaw,Percent,ProbeTempC` so the new probe
  temperature joins the CSV row.
- **Driver source:** port the constants from
  [Adafruit_CircuitPython_seesaw](https://github.com/adafruit/Adafruit_CircuitPython_seesaw)
  (`MOISTURE_BASE`, `TOUCH_CHANNEL_OFFSET`, 16-bit big-endian read
  sequence) into a small `lib/seesaw_soil.py`. No runtime dependency
  on the Adafruit library — Pi Greenhouse is MicroPython, not
  CircuitPython.
- **Verification:** post-fab eyes-on checklist in
  [hw-test-log "Adafruit STEMMA #4026 soil sensor bring-up"](../test/hw-test-log.md).
  Address on bus, dry/wet sweep, probe temperature within 5 °C of
  SHT31 at room temp.

**Configuration impact (queued, not shipped this turn):**

- `DEVICE_CONFIG["pins"]["adc_input"]` → **delete**.
- `DEVICE_CONFIG["soil_logger"]`:
  - `adc_dry_raw` → rename `seesaw_dry_raw`, default ~300 (air).
  - `adc_wet_raw` → rename `seesaw_wet_raw`, default ~1400 (saturated).
    Validator inverts: wet must now be **>** dry.
  - new `i2c_address: 0x36`.
  - new `i2c_bus: 0`.
- `validate_config()` and
  [tests/test_config.py](../../tests/test_config.py) rows move in
  lockstep per
  [configurability.md](../../../.claude/rules/ecc/common/configurability.md).
- `main.py` drops the ADC construction and passes the existing
  `i2c0` instance to `SoilLogger`.

### [x] Case fan voltage selector + ambient fan Pico control

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- Add a **second 2-pole voltage selector switch** for the case fan,
  mirroring the existing ambient fan voltage switch (so each fan can
  be tied to a different rail without re-wiring).
- Make the **ambient fan Pico-controllable** — currently it's
  hardwired and bypasses the Pico. Route it through the new
  PCA9685 + IRLZ44N stage so it joins the rest of the fan control
  surface (see fan entry further below).

**Comment**: removed voltage selector for ambient/chamber fans and instead added a PWM pin to receive pwm from the PCA9685.

### [x] SD card module → **Adafruit 4682** (3 V Micro SD SPI/SDIO Bypass)

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

**Footprint / connector change:** tracked under "SD card module —
Adafruit 4682 header footprint + mounting holes" in the PCB layout
section.

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
  [R8 entry](#x-r8-stays--fix-the-firmware-comment-not-the-schematic).

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

### [x] Move fans from 2× relays to PCA9685 + IRLZ44N MOSFETs

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

**Comment:** please check thoroughly if the wiring from IRLZ44N and Diode is correct


## PCB layout — footprints, routing, silkscreen, test points

### [ ] Hydroponics I²C1 + 1-Wire connectors and pull-up placement

**Filed:** 2026-05-31 ·
[chat-log entry](../notes/chat-log.md#2026-05-31--hydroponics-monitoring-expansion-dwc--hpa-aeroponics)

Layout side of the
[Hydroponics monitoring Schematic entry](#--hydroponics-monitoring--2nd-ic-bus-ds18b20-phec-wet-system-relays).

- **New I²C1 connector** (RJ12 or 4-pin JST `3V3/GND/SDA/SCL`) for the
  pH/EC isolator pair. Place the two new GP26/GP27 → 3V3 pull-ups
  next to it; keep the SDA/SCL pair short and equal-length.
- **Remove R16/R17 footprints** (former GP26/GP27 relay pull-ups to
  +5 V) or repurpose them as the new 3V3 pull-ups if the net can be
  re-pointed cleanly.
- **New 1-Wire connector** for DS18B20(s) (or reuse GP2_CON with its
  power pin re-pointed +5 V → +3V3); 4.7 kΩ GP2→3V3 pull-up beside it.
- **New 2-pin water-level switch connector** (`GP28 / GND`). Place the
  10 kΩ GP28→3V3 pull-up, the ~1 kΩ series resistor, and the 100 nF
  pin-to-GND debounce cap next to it. GP28 is reclaimed from the
  deleted ADC soil probe — clear any leftover analog-divider footprint
  on that net.
- **Silkscreen:** label the new jacks `I2C1 (pH/EC)`, `WATER TEMP
  (1-Wire)`, and `WATER LEVEL`; mark the I²C1 jack as a **separate bus** from the I²C0
  RJ12 drops so a probe never gets plugged into the wrong jack. Add
  `(0x63)` / `(0x64)` near the I²C1 connector.
- REL_CON1 silkscreen: pins 7-8 are no longer relay outputs — relabel
  or depopulate so the harness doesn't drive a dead pin into the
  I²C1 net.

### [ ] MCP6002 → LM358N — DIP-8 socket footprint

**Filed:** 2026-05-24 ·
[chat-log: DIP-8 footprint decision](../notes/chat-log.md#2026-05-24--lm358-footprint-switch-to-dip-8-socket)

- Swap the existing **SOIC-8 land pattern** (was for MCP6002T-I/SN)
  for a **DIP-8 socket** footprint (2.54 mm pitch, 7.62 mm row
  spacing) to accept the LM358N already in stock.
- Footprint costs ~3× the SOIC-8 board area; check clearance against
  surrounding components after replacement.
- Component swap, rail correction, and gain retune are tracked under
  "MCP6002 op-amp → LM358N (DIP-8) + grow-light gain retune" in the
  Schematic section.

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

- Print the 7-bit hex address next to each I²C device's footprint.
  **I²C0** (GP0/GP1):
  - SHT31 → `(0x44)`
  - DS3231 RTC → `(0x68)`
  - MCP4725 DAC → `(0x60)`
  - SSD1306 OLED → `(0x3C)`
  - PCA9685 (future) → `(0x40)`
  - Adafruit STEMMA soil sensor #4026 (future) → `(0x36)`
  - **I²C1** (GP26/GP27, future hydro bus — see
    [Hydroponics monitoring entry](#--hydroponics-monitoring--2nd-ic-bus-ds18b20-phec-wet-system-relays)):
    - Atlas EZO-pH → `(0x63)`
    - Atlas EZO-EC → `(0x64)`
  - Mark the I²C1 group as a **separate bus** so a 0x63/0x64 address
    isn't mistaken for an I²C0 conflict.
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

### [ ] SD card module — Adafruit 4682 header footprint + mounting holes

**Filed:** 2026-05-22 · updated 2026-05-24 ·
[chat-log: module switch](../notes/chat-log.md#2026-05-24--sd-card-module-switch--azdelivery--adafruit-4682)

- Replace the current AZDelivery-shaped land pattern with a header
  matching the **Adafruit 4682** pinout. Single-row, **7-pin in SPI
  mode** (8 pins if DAT2 is exposed for the SDIO upgrade path).
  Spacing per the 4682 mechanical drawing.
- **Mounting hole(s)** per the 4682 mechanical drawing — confirm on
  the bench part before committing layout.
- Module choice, power-rail change, decoupling caps, MISO pull-up,
  and DET pin wiring are tracked under "SD card module → Adafruit
  4682" in the Schematic section.

### [ ] Relay connector — orientation flip + mains-rated spacing

**Filed:** 2026-05-22 ·
[chat-log entry](../notes/chat-log.md#2026-05-22--next-revision-planning-from-bench-notes)

- **Flip the relay connector orientation** — current orientation is
  wrong for the harness.
- Once the connector is mains-only (per the Schematic-side spec
  change), apply **mains-rated trace spacing and creepage clearance**
  for the relay traces and pad-to-pad distances on the relay-side
  copper.
- Connector pin assignments (pull-ups, GND tie, mains-rated header
  spec) are tracked under "Relay connector cleanup" in the Schematic
  section.

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

### [ ] Hydroponics wet-zone wiring — isolation, RCD, drip loops

**Filed:** 2026-05-31 ·
[chat-log entry](../notes/chat-log.md#2026-05-31--hydroponics-monitoring-expansion-dwc--hpa-aeroponics)

Harness side of the
[Hydroponics monitoring Schematic entry](#--hydroponics-monitoring--2nd-ic-bus-ds18b20-phec-wet-system-relays).
The reservoir is the most hazardous addition to the system (mains
pumps/heater in/near conductive water).

- **30 mA RCD / FI-Schutzschalter on the mains feed** to the air
  pump, reservoir heater, and HPA pump. Verify the wall socket's
  circuit already has one (German consumer units usually do); if not
  confirmable, fit a plug-in PRCD adapter. This outranks any
  board-level protection — single most important life-safety item.
- **Galvanic isolation at the probes:** Atlas inline voltage isolator
  per EZO (pH, EC), housed dry. Single-point ground; no other grounded
  metal in the water (plastic-bodied submersibles only).
- **Drip loops** on every cable entering the reservoir lid (probe
  cables, pump cords): route so the cable dips below the entry and
  forms a U, so water tracks off the bottom of the loop, not into the
  connector or enclosure.
- **Probe connectors:** BNC bulkhead for pH/EC at the dry enclosure
  wall; DS18B20 leads sealed where they pass into the humid zone.
- **Water-level float switch:** plastic-bodied float on a sealed
  2-conductor cable, dry contact only — it carries the GP28 logic
  signal + GND, **no mains and no isolator** (a passive switch is
  inherently isolated and adds no second grounded metal in the tank).
  Drip-loop and gland its cable like the probes; mount the float at the
  intended low-water (or high-water) line.
- Pico case + isolators mounted **above** the reservoir at all times
  (confirmed) — gravity keeps condensation/spray off the electronics.
- HPA-only (reserved): accumulator + HP pump pressure-switch wiring is
  self-contained 230 V; if a DC burst solenoid is later added, run its
  flyback (UF4007) at the solenoid and a local bulk cap at its MOSFET.

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
