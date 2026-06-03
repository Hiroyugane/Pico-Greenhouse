# Chat log

> Decisions, spec clarifications, deviations, issues, and non-obvious
> notes from Claude sessions. See
> [.claude/rules/ecc/common/documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md)
> for the entry format. Newest topic on top.

## 2026-06-03 · graphify code-health cleanups

### decision · orphan CO2 scripts relocated, not deleted

`tests/co2log.py` and `tests/co2test.py` were bare-`main()` hardware
loops with no `test_` prefix (never collected by pytest, would error on
collection if they were — they import `machine`/`lib.ds3231` at module
top). They duplicate the `prototypes/co2-test.py` lineage. Chose to
`git mv` them into `prototypes/` rather than delete, keeping the bench
scripts available alongside their siblings while un-polluting `tests/`.
No code imports them; pytest still collects 1037 tests.

### note · only cheap-win items actioned; #4/#5/#6 deferred

From the six-item graphify review, only the three low-risk cleanups
were taken this session: untracking `prototypes/logs/` SD-card cruft
(`git rm --cached` + `.gitignore prototypes/logs/`), fixing the broken
`rtc_set_time.py` link in CLAUDE.md (the file lives at
`prototypes/rtc_set_time.py`), and the orphan relocation above.
Deferred by choice: item #4 (split the 131-method
`TestValidateConfig`), item #5 (continue `_validate_<section>`
extraction from the ~525-line `validate_config()`), and item #6 (split
the 999-line `lib/buffer_manager.py`, flagged investigate-first). These
are larger behavior-preserving refactors left for a dedicated pass.

### issue · pre-existing corruption in next-revision.md (untouched)

`docs/hardware/next-revision.md` carried an unstaged edit at session
start that garbled "float/level switch" into "w/level switch" (item 5,
water-level switch section). Not made this session; left untouched and
flagged for the user rather than silently committed or reverted.

## 2026-06-02 · PCB design ruleset (net classes)

### decision · net-class design rules authored in a standalone doc

Authored [docs/hardware/pcb-design-rules.md](../hardware/pcb-design-rules.md):
track width / clearance / via pad Ø / via drill Ø / max track length per
net class, plus every net in the 2026-06-02 netlist
([Sheet_1_2026-06-02.net](../hardware/EasyEDA-Files/Sheet_1_2026-06-02.net))
assigned to a class. Scoped to **2-layer, 2 oz copper, JLCPCB standard
floor** per the answers given. Standalone doc (cross-linked from
next-revision.md) chosen over inlining so the EasyEDA DRC profile has one
source of truth that survives the change-queue churn. Max length is an
SI budget per class (SPI 10 MHz → 75 mm, I²C 400 kHz → 150 mm, UART 9600
→ 250 mm, analog → 100 mm), n/a on power/GND.

### spec · default clearance corrected 0.15 mm → 0.20 mm for the 2 oz process

The [Power trace widths](../hardware/next-revision.md) entry sets a
0.15 mm default clearance. **JLCPCB's 2 oz copper process floors
trace/space at 0.20 mm (8 mil)** — 0.15 mm would be DRC-rejected or
silently kicked to the 1 oz process, forfeiting the current margin the
2 oz order exists for. The ruleset sets default clearance to 0.20 mm and
keeps power-net clearance at 0.30 mm. A 0.15 mm default is only valid on
a 1 oz reorder, which contradicts the heater (3.0 mm) and 12 V (2.5 mm)
trace-width math. Flagged on the next-revision layout entry; the queued
entry itself is left intact pending the user's call on whether to amend it.

### note · highest on-board voltage is 19.5 V — no mains creepage on the PCB

All 230 V loads (grow light, heater feed, wet-system pumps) switch
through **off-board relay modules**; REL_CON carries only logic + GND.
The heater rail (HE_CON, 19.5 V DC) is the highest potential on copper,
so the ruleset needs no mains creepage/clearance class — every net is a
sub-50 V low-voltage net. Mains creepage stays a wiring/harness concern,
not a board-layout one.

## 2026-06-01 · PCB shrink review of the 2026-06-01 EasyEDA export

### issue · LM358 (U24) negative-supply pin floats — net `R30_2` never reaches GND

In the 2026-06-01 netlist the LM358 footprint swap (PDIP-8 → SOIC-8,
`LM358DR2G` C7950, U24) left pin 4 (V−/GND), pin 3 (IN1+), the bottom of
gain resistor R30, and bypass cap C12-1 all on an isolated net **`R30_2`**
that has **no tie to the board GND net**. Pin 4 is the op-amp's negative
supply and MUST be GND; R30's lower end is the non-inverting gain
reference and must be GND; C12 is the +12 V supply bypass and its return
must be GND. As drawn the grow-light dimmer won't work and the floating V−
risks erratic/latch behaviour. **Fix:** relabel net `R30_2` to `GND` (merge
U24-3, U24-4, R30-2, C12-1 into GND). Almost certainly an accidental
net-name split during the symbol swap — every other LM358 connection is
correct (DAC→IN2+ pin5, R41 10 k feedback + R30 4.7 k → gain 3.13,
OUT2→GL_DIM+/GL_CON, VCC pin8→+12 V).

### note · everything else in the shrink pass is integrated correctly

Verified against the netlist: PCA9685 module → bare `PCA9685PW` TSSOP-28
(U1) is wired right — A0–A5→GND (address 0x40, matches `config.py`),
/OE→GND (outputs enabled), EXTCLK→GND (internal osc), VDD→+5 V, decoupling
C16 100 nF + C15 100 µF, all 16 PWM + SCL(26)/SDA(27) correct. Fan/solenoid
MOSFETs → AO3400A SOT-23 (Q1–Q6) low-side, 150 Ω gate series + 10 k
pulldown + US1J flyback. Heater stays IRLZ44N TO-220 (T1) driven by MCP1416
SOT-23-5 (U13) from GP3. All resistors 0603/0805, 100 nF 0603, LEDs 0805,
Schottkys SMD (MBRD1045 TO-252, SS14/SS54 SMA). The big-win swaps all
landed.

### note · further area + manual-labour reductions still on the table

(1) **8× PPTC resettable fuses (U7/U8/U10/U11/U12/U15/U16/U17)** are THT
radial `250V.3APPTC` on sensor-connector lines — move to SMD PPTC
(1206/1812) and downsize from 3 A (sensor lines draw <0.5 A); removes 8
hand-solder points and reclaims the radial footprints. (2) **100 µF
electrolytics C3/C15** THT → SMD (1210 MLCC or SMD alu). (3) **1000 µF ×3
(C4/C7/C10)** 12.5 mm⌀ × 30 mm dominate remaining volume — keep for rail
bulk but note Z-height; confirm all three rails need 1000 µF.

### note · BOM consolidation / feeder-fee cleanup

(1) Same physical JST part under multiple `Name` rows: `B3B-XH-A-BK`
(C493416) appears as "B3B-XH-A-BK"/"JST-3P"/"GP2 Reserved" (5 pcs);
`B4B-XH-A-R` (C595709) as "I2C0 Free Connector"/"I2C0 Free 12V
Connector"/"JST-4P" (4 pcs). Consolidate names for assembly clarity (no
feeder saving — JLC dedupes by LCSC #). (2) `FAN_CHA1` BOM Name is
mislabelled "I2C0 Free Connector". (3) **US1J flyback (U18–U23) is an
Extended part** — a 40 V Basic Schottky (SS34, or the SS14 already in BOM)
is electrically better for 12 V flyback and drops one Extended feeder
(~$3) while merging into an existing Basic diode line. (4) Confirm AO3400A
SOT-23 thermal headroom for the HPA solenoid on Q1 (prior plan called for
IRLZ44N there); fans are fine.

## 2026-05-31 · RJ12 → JST-XH swap rejected (PCB shrink effort)

### decision · keep RJ12 on all 9 external ports

While hunting for footprint reductions to fit routing on the fixed
98×149 mm board, evaluated swapping the 9 RJ12 (6P6C) external ports
to right-angle JST-XH 2.5 mm (sized per port: 2P GL, 3P W_TEMP, 4P
TH/CO2, 5P I2C, 6P ADC; verified LCSC S#B-XH-A parts C157931/C157928/
C157925/C263757/C495565). User measured the XH right-angle footprint
as **near-identical** to RJ12, so the swap frees almost no board area
while losing RJ12's keying and the existing field cabling. Decision:
**RJ12 stays.** Area savings will come from the other swaps in this
effort (PCA9685 module→TSSOP-28 bare chip, LM358 PDIP→SOIC, THT
passives/diodes→SMD) instead. Do not re-propose the XH connector swap.

## 2026-05-31 · Fan logging demote + CO₂ override retune

### decision · scheduled fan transitions → DEBUG; CO₂ override 1000→2500 ppm

Acting on two findings from the [12-day analysis](2026-05-31-sd-log-analysis.md).
(1) `growroom_walls SCHEDULE ON/OFF` was 94 % of `system.log`; demoted
both calls in [lib/relay.py](../../lib/relay.py) from `.info()` to
`.debug()` (console-only by default, `debug_to_file=False`), so they no
longer hit the SD card. THERMOSTAT and EXTERNAL OVERRIDE transitions stay
at INFO. A redundant structured `debug("schedule state change", …)` line
already sat directly above, so no signal is lost.
(2) The CO₂→exhaust override never tripped in steady state — but the user
clarified the rig was **not in production**: no colonization/fruiting, and
the SHT31/S8 sensors sat **outside** the chamber, so the 1471 ppm floor was
ambient drift, not a capacity failure. Bumped `override_ppm_on` 1000→2500
and `override_ppm_off` 800→2200 in [config.py](../../config.py) as a more
meaningful placeholder until a real crop phase picks the setpoint. Validator
unchanged (still asserts on > off ≥ 0); 1037 tests green, coverage 91.6 %.

## 2026-05-31 · 12-day SD log & sensor analysis

### note · first field-run analysis of the >10 d SD snapshot

Analyzed `sd/` after 11.9 days continuous uptime (mushroom mode). Full
write-up + daily/overall aggregation tables in
[2026-05-31-sd-log-analysis.md](2026-05-31-sd-log-analysis.md). Steady
state is healthy: zero resets, zero data gaps, zero sensor failures since
05-19 20:58; all 10 boots and all 37 WARN/ERR were on commissioning day.
Sensor means over the run: temp 23.2 °C (rising 20.4→24.5), RH 57 %
(noisy), CO₂ 2418 ppm (falling 3340→1730).

### issue · system.log is 94 % routine fan-schedule spam

`growroom_walls` 20 s-ON / 8.3 min circulation cycle logs every transition
at INFO — 4096 of 4366 lines — burying the 2 ERR + 35 WARN and adding an
SD append per transition. Proposed fix: demote scheduled (non-override)
fan transitions to DEBUG, keep THERMOSTAT/OVERRIDE at INFO. Not yet
implemented; logged for a follow-up firmware change.

### issue · CO₂ override threshold (>1000 ppm) never met in steady state

CO₂ floor over 12 days is 1471 ppm; only 2 `exhaust EXTERNAL OVERRIDE ON`
events exist, both on commissioning day, none after. Either the override
path isn't firing in steady state or exhaust lacks the air-exchange
capacity to reach 1000 ppm. Needs instrumenting to confirm which; if the
high CO₂ is intentional for colonization the threshold is misleading.

### note · relay-cycle wear quantifies the queued PCA9685 fan revision

`growroom_walls` relay cycles ~62,600×/yr (172/day) — ~1.6 yr contact
life on a mechanical relay switching an inductive fan. Reinforces
[[project_fan_hardware_revision]] (PCA9685 PWM fans); no new
next-revision entry filed since the change is already queued.

## 2026-05-31 · HPA mist-solenoid PWM breakout connector

### decision · one PCA9685 channel (ch5) for the HPA solenoid, broken out as a plug-in 12 V valve connector; no raw PWM exposed

Follow-up to the hydroponics expansion: user asked which PWM ports (and
other nets) the next PCB must break out to an external connector for DWC
and HPA aeroponics. After a clarifying round the scope is **the HPA mist
solenoid only** — every other wet-system load is already placed (air
pump / reservoir heater / HPA pump → 230 V REL_CON; pH/EC → I²C1; water
temp → 1-Wire GP2; water-level switch → GP22 input). So the entire PWM
question reduces to **one channel**.

Decisions:

- **PCA9685 ch5** is reserved for the solenoid (ch0–ch4 = the five
  fans). ch6–ch15 stay unrouted; the solenoid-only scope needs no other
  DC PWM load, so no other PWM port is broken out.
- **No raw PWM line is broken out.** Per the user's "each component = 1
  connector, plugged in to its own spec" framing, ch5 stays on-board
  driving an IRLZ44N low-side stage (150 Ω gate R + 10 kΩ pull-down +
  UF4007 flyback, identical to the fan stages). A **dedicated 2-pin
  keyed valve connector** exposes only `SOL+` (12 V) and `SOL−` (drain);
  the 12 V solenoid plugs straight in.
- **Solenoid specced at 12 V DC**, off the 12 V buck rail (9 A, huge
  headroom for a ~1 A coil). No native 24 V rail exists and 19.5 V is
  marginal for a 24 V coil — so the valve choice is constrained to 12 V
  rather than adding a rail.
- **Why PWM and not a relay:** the solenoid is the one load that cycles
  every few minutes 24/7 (relay contact wear) and benefits from PWM
  current-hold (full-duty pull-in, reduced-duty hold → far less coil
  heat). Slow on/off 230 V loads stay on relays; this fast, repetitive,
  hold-capable DC load belongs on the PCA9685 + MOSFET surface.
- Firmware queued: `DEVICE_CONFIG["hpa_solenoid"]` (`pca9685_ch: 5`,
  pull-in / hold duties + burst timing) with validator + tests, and
  `lib/hpa_solenoid.py`; the fan duplicate-channel validator extends to
  cover ch5 so a fan can't collide with the solenoid. Gated behind
  `enabled` until HPA hardware is fitted.

## 2026-05-31 · Hydroponics monitoring expansion (DWC + HPA aeroponics)

### decision · future-proof the board for DWC now and HPA aeroponics later, monitor-only chemistry, no new MCU

User asked what hardware the next PCB needs to support a more
automated DWC reservoir and/or HPA aeroponics. After a clarifying
round the scope settled deliberately small:

- **Both systems future-proofed on one board.** DWC (single ~20 L
  reservoir, 2–4 plants) is the near-term target; HPA aeroponics is
  the reserved-for-later path. The board should drive DWC now and
  accept HPA with a harness/connector change, not a respin.
- **Closed-loop automation: water temperature only.** Level top-off
  is **manual** (single small reservoir), which deletes the entire
  float-switch + solenoid + top-off-pump loop that an earlier draft
  carried. Water heating is a 230 V aquarium heater on a relay (or a
  self-thermostatting heater needing no MCU pin at all). **No
  chiller** — for 20 L it's impractical (compressor/Peltier both dump
  heat to room air, 150–300 €, oversized); mitigate warm spells with
  an insulated opaque reservoir + aeration, monitor-and-alarm on high
  water temp via the existing buzzer/LED surface.
- **pH + EC are monitor-only (no dosing).** Atlas Scientific EZO-pH
  (≈0x63) and EZO-EC (≈0x64) in I²C mode, ~50 € each in DE. No
  dosing pumps → no safety-critical chemical actuators, much simpler
  and safer build. Drift only mis-reports, never mis-doses.
- **Second I²C bus approved** to keep the wet-probe traffic off the
  RTC/OLED/DAC bus.

Why these specific hardware choices:

- **Ground loops (the real DWC/RDWC failure mode).** Multiple
  grounded probes + pumps in one conductive reservoir form
  circulating currents that land on the pH/EC mV signal. Mitigation:
  **galvanic isolation per probe** — an Atlas inline voltage isolator
  (isolated DC/DC + digital isolator) between each EZO and the bus,
  plus single-point grounding and plastic-bodied submersibles. User
  flagged isolators at 25 € + shipping as pricey and asked for a
  cheaper alternative; the EZO isolator (or an isolated Tentacle/
  Whitebox-style carrier) remains the correct part — un-isolated
  twin probes in one tank interfere per Atlas's own docs. Cheaper-but-
  acceptable fallback if budget forces it: keep **one** isolated
  probe (pH, the more drift-sensitive) and run EC through the EC
  circuit's own AC-excitation isolation, accepting some coupling.
  Documented as a fallback, not the recommendation.
- **Water temp = DS18B20 on 1-Wire.** One pin (GP2), one 4.7 kΩ
  pull-up, multiple probes (reservoir + root zone) share the bus via
  unique 64-bit ROMs. Foundational: **both pH and EC need it for
  temperature compensation.**
- **Watchdog vs. aeroponics.** HPA roots dry in minutes and the async
  WDT resets the Pico (mist defaults off during boot/SD-retry). User
  **accepts the risk** (>10 d uptime on current firmware, plant
  checked daily), so the hardware dead-man's wetting fallback
  (mechanical pressure switch / NC flood solenoid) is **not**
  required. Recorded as accepted risk.
- **HPA pump vs. solenoid clarified.** The HP pump *makes* pressure
  (230 V, self-regulating via its own pressure switch + accumulator);
  a separate fast solenoid *times* each mist burst. For LPA or simple
  on/off HPA only the 230 V pump-on-a-relay is needed; a burst
  solenoid is added only for true HPA timing (230 V → relay, or
  12/24 V DC → a spare PCA9685 channel + IRLZ44N + flyback). Reserve,
  don't build.

GPIO reality check against the as-built 2026-05-31 board
(`docs/hardware/EasyEDA-Files/`): fans already moved to PCA9685
(PWM0–4 → T2–T6; PWM5–15 free), heater on T1 via MCP1416, GP15 is
SD-DET, GP28/ADC still present. The Pico has **no unrouted GPIO
left** — the second I²C bus must repurpose a relay pair. RP2040 maps
I²C1 only to (GP18,GP19) or (GP26,GP27) on this board. Chose
**GP26=I²C1 SDA / GP27=I²C1 SCL** (REL_CON1 pins 7 & 8, the two
never-loaded "reserved" relays), leaving GP18/19/21/22 as four spare
mains relays for air pump + heater + HPA pump. **Must-fix:** GP26/
GP27 currently carry 10 kΩ pull-ups to **+5 V** (R17/R16); left in
place I²C idle would put 5 V on the Pico pins (abs-max violation), so
the next PCB **deletes R16/R17** and adds 2.2–4.7 kΩ pull-ups to
**3V3**. DS18B20 1-Wire repurposes **GP2_CON** (power pin +5 V → +3V3,
add 4.7 kΩ GP2→3V3). While auditing the +5 V net it surfaced that
**all seven relay-line pull-ups R16–R22 currently pull to +5 V**: R16/
R17 (GP26/GP27) **must** move because those pins become I²C (5 V on an
idle-high open-drain line = abs-max), and the surviving relay pull-ups
**R18–R22 should move to 3V3 too** — keep 10 kΩ, change only the rail.
5 V there isn't a hard fault (the lines are driven push-pull almost
always) but it stresses the ESD clamp during boot Hi-Z (same mechanism
as the CO2 RX fix) and backfeeds ~0.17 mA into 3.3 V when driven high.
3.3 V is the correct inactive-HIGH level and matches the Pico's own
driven-high, so it's the consistent fix with no downside.

Mains-side safety (above any PCB concern): pump + heater on a
**30 mA RCD / FI-Schutzschalter** (verify the socket's circuit, or
use a plug-in PRCD); **drip loops** on every probe/pump cable into
the reservoir lid; isolators + Pico case mounted dry **above** the
reservoir (user confirmed the case sits above the water at all
times).

This turn lands documentation only — no schematic/firmware change.
Queued into
[next-revision.md](../hardware/next-revision.md) (Schematic + PCB
layout + Wiring sections), an hw-test-log post-fab checklist, and a
memory file `project_hydro_automation_revision.md`. Firmware
(`lib/water_temp_logger.py`, `lib/ph_logger.py`, `lib/ec_logger.py`,
I²C1 init in `hardware_factory`, `DEVICE_CONFIG` + validator +
`tests/test_config.py`) is queued for the commit that lands with the
new PCB.

### deviation · add a monitor-only water-level switch (GP28), top-off stays manual

User wants a simple water-level meter back on the board — "a very
simple sensor that just closes a circuit once the water level is below /
above the sensor." This **refines, not reverses,** the earlier
decision in this same topic that "deletes the entire float-switch +
solenoid + top-off-pump loop." What was deleted was the *actuation*
loop (automatic top-off); top-off stays **manual**. The new part is a
passive **sense input only**: a dry-contact float/level switch wired to
a GPIO so the controller can raise a low-water (and/or high-water)
**alarm** on the existing buzzer/LED surface and log the edge, instead
of a dry reservoir being silent between daily checks. No pump, no
solenoid, no closed loop — same monitor-and-alarm philosophy already
chosen for water temperature.

Pin choice: **GP28**, which the
[soil-sensor STEMMA swap](#2026-05-26--soil-sensor-swap--adafruit-stemma-4026-i2c)
frees by deleting `adc_input: 28`. It's the only pin freed on this
revision; the four spare mains-relay channels are earmarked for the
wet-system actuators, so GP28 (used as a plain digital input, not ADC)
is the clean home. This couples the level switch to the STEMMA swap
shipping on the same board — noted as a dependency in the next-rev
entry, with "reuse a spare relay channel as an input" as the lower-
preference fallback if GP28 is ever kept analog.

Electrical: 10 kΩ pull-up GP28→3V3 (defined HIGH when the float contact
is open, LOW when it closes to GND), plus a ~1 kΩ series resistor and a
100 nF pin-to-GND cap (RC ≈ 100 µs) to debounce float chatter and shunt
ESD off the long wet-zone cable; firmware adds a software debounce on
top. New 2-pin connector (`GP28 / GND`). The float must be
plastic-bodied so it adds no second grounded metal object to the tank
(consistent with the single-point-ground note); contact polarity
(NO "closes when low" vs NC) is handled in firmware via `active_low` +
`alarm_on`, so either float type works. Documentation-only turn —
queued into next-revision.md (Schematic item 5, PCB-layout connector,
Wiring wet-zone bullet), the hw-test-log bring-up checklist, and the
`project_hydro_automation_revision` memory. Firmware
(`lib/water_level_monitor.py`, `DEVICE_CONFIG["water_level_monitor"]` +
validator + tests) lands with the PCB.

### decision · water-level switch moved off GP28 onto a spare relay channel (GP22)

Follow-up to the entry above: rather than spend the freed analog pin
(GP28/ADC2) on the level switch, use a **spare relay-header channel as
a digital input** and keep GP28 free for a possible future analog
peripheral. Chosen pin: **GP22** (`relay_reserved_2`, REL_CON pin 6) —
an unused reserved channel whose relay pull-up is already in the
R18–R22 → 3V3 move (item 1b), so that pull-up doubles as the switch
pull-up and no new 10 kΩ is added. The float wires to REL_CON pin 6 +
GND instead of a relay module; the ~1 kΩ series + 100 nF debounce RC
stays. Net relay-channel map: grow light GP20, wet actuators
GP18/GP19/GP21, level-switch input GP22, GP26/GP27 → I²C1 (REL_CON
fully allocated, no spare). Config delta vs. the entry above:
`water_level: 22` (not 28), `adc_input: 28` **stays**, and with GP22
(`relay_reserved_2`) plus GP21/26/27 all assigned, no `relay_reserved_*`
channels remain.

## 2026-05-26 · Soil sensor swap → Adafruit STEMMA #4026 (I²C)

### decision · drop analog capacitive probe path; go I²C with Seesaw STEMMA

The 2026-05-15 bench session ended with the cheap capacitive
NE555-based probe confirmed dead even at 5 V with a divider. The
queued next-revision entry "ADC / soil-moisture interface" still
described an analog 0–5 V probe with a 10 kΩ + 15 kΩ divider into
GP28 — a plan that was already on shaky ground (3.3 V is below the
NE555 start threshold; any TLC555 replacement still needs analog
front-end work and per-batch calibration drift). Decision: skip the
whole analog story and use the
[Adafruit STEMMA Soil Sensor #4026](https://www.adafruit.com/product/4026)
on I²C0 going forward.

Why this is the right swap:

- **Native 3V3, no level conversion.** Seesaw ATSAMD10 onboard runs
  at the I²C bus voltage; no divider, no abs-max concerns, no
  ADC_VREF gotchas.
- **Joins an existing bus.** I²C0 already carries SHT31, DS3231,
  MCP4725, SSD1306 (and PCA9685 once that lands). Adding 0x36 stays
  inside the bus-capacity envelope once the queued R1/R2 drop to
  2.2 kΩ ships (see
  [next-revision.md](../hardware/next-revision.md)). No new bus
  required.
- **GP28/ADC2 freed.** Removing the analog probe drops `adc_input`
  and the soil_logger ADC calibration keys from `DEVICE_CONFIG`,
  opening the pin for any future analog peripheral without board
  work.
- **Bonus: probe temperature.** The Seesaw exposes the chip's
  on-die temperature register. Cheap data point — appended to the
  soil CSV row.
- **Capacitive semantics invert.** The resistive-probe convention
  (lower raw = wetter) flips on the Seesaw: **higher raw = wetter**
  (typical air ≈ 200–400, fully saturated ≈ 1000–1500). New
  calibration constants `seesaw_dry_raw` / `seesaw_wet_raw` with
  the validator inequality reversed.
- **Driver:** port the constants from
  [Adafruit_CircuitPython_seesaw](https://github.com/adafruit/Adafruit_CircuitPython_seesaw)
  (MOISTURE_BASE, TOUCH_CHANNEL_OFFSET, 16-bit BE read) into a small
  MicroPython-side `lib/seesaw_soil.py`. No runtime dependency on
  the Adafruit library.

This turn lands docs + config marker only:

- `docs/hardware/next-revision.md` "ADC / soil-moisture interface"
  entry rewritten as "Soil moisture sensor → Adafruit STEMMA #4026
  (I²C, 0x36)".
- Silkscreen I²C address map entry gets a new `(0x36)` row.
- `config.py` soil_logger section gets a comment block flagging the
  queued sensor swap; functional keys (`adc_input`,
  `adc_dry_raw`, `adc_wet_raw`) are unchanged so the running
  firmware keeps booting until the driver rewrite lands.
- `hw-test-log.md` gets a STEMMA bring-up checklist; the
  2026-05-15 analog-replacement checklist is marked superseded.
- New memory file
  `project_soil_sensor_revision.md`; MEMORY.md gets the pointer.

Firmware-side rewrite (`lib/soil_logger.py` → Seesaw I²C, new
config keys, `validate_config()` and `tests/test_config.py`
updates, `main.py` wiring) is queued for the commit that lands with
the new PCB — out of scope for this documentation turn.

## 2026-05-26 · brownout supervisor part + wiring clarification

### spec · MAX809 suffix corrected to T (3.08 V), plus 1 kΩ series resistor to RUN

User asked how the brownout supervisor in the
[next-revision.md "Brownout supervisor on Pico RUN line" entry](../hardware/next-revision.md#--brownout-supervisor-on-pico-run-line)
should be wired to the Pico's RUN pin. Walking the SOT-23-3 pinout
surfaced two issues in the originally-filed entry:

- **Part suffix wrong.** The entry listed **MAX809LEUR+T**. The `L`
  suffix in the MAX809 family is the **4.63 V** typical reset
  threshold — intended for 5 V rails. To trip at ~3.0 V on the 3V3
  rail (which the entry called out as the target), the correct
  suffix is **T** (3.08 V typ): **MAX809TEUR+T**. Adjacent suffixes
  for future reference: S = 2.93 V, R = 2.63 V, M = 4.38 V,
  L = 4.63 V.
- **Push-pull output conflicts with the reset button on RUN.**
  MAX809T (and the alternative TPS3839K33) drive /RESET with a
  push-pull stage. The
  [reset button queued under "Button connector rework"](../hardware/next-revision.md#--button-connector-rework--menu_btn-debounced-reset_btn-direct)
  wires RUN directly to GND. Without mitigation, pressing the reset
  button while the supervisor holds RUN high shorts the
  supervisor's high-side transistor through the button to GND.
  Resolution: insert a **1 kΩ series resistor between the
  supervisor's pin 2 (/RESET) and the RUN node**. Limits short-
  circuit current during a press to ~3.3 mA while still letting
  the supervisor pull RUN below logic-low against the Pico's
  internal ~50 kΩ pull-up (divider = 1 k / 51 k ≈ 0.06 V).
  Alternative considered and recorded as the fallback in the
  entry: swap to an open-drain supervisor (e.g. MAX6328) so
  supervisor + button wire-OR onto RUN without a series resistor.

Final wiring captured in the next-revision entry: MAX809T pin 1
(GND) → board GND; pin 3 (VCC) → 3V3 with 100 nF decoupling; pin 2
(/RESET) → 1 kΩ → RUN (Pico pin 30).

## 2026-05-24 · next-revision.md consistency pass

### decision · Schematic section verified to contain only schematic-stage concerns

Follow-up to the EasyEDA-workflow restructure earlier this date. The
user asked to verify that every bullet under **Schematic — nets,
components, BOM** is actually a schematic concern, with no layout or
other stage content embedded. Sweep results, and how each
misplacement was resolved:

- **MCP6002 → LM358N entry** carried a "PCB footprint change" bullet
  describing the SOIC-8 → DIP-8 socket land-pattern swap with
  dimensions. Moved to a new PCB layout entry "MCP6002 → LM358N —
  DIP-8 socket footprint". The schematic-side bullet kept the
  procurement rationale (use in-stock LM358N DIP-8) and now
  cross-references the layout entry. Entry title renamed from
  "...+ footprint to DIP-8 socket + grow-light gain retune" to
  "...LM358N (DIP-8) + grow-light gain retune" so the title no
  longer advertises layout content that isn't here.
- **Relay connector cleanup entry** carried a "Flip the relay
  connector orientation" bullet and a trailing mention of "spacing
  for mains creepage and clearance". Both are layout work. Moved to
  a new PCB layout entry "Relay connector — orientation flip +
  mains-rated spacing". The schematic-side kept the component-spec
  swap (mains-rated header replaces the low-voltage header) and the
  pull-up / GND-tie / pinout fixes. Title renamed to drop "flip".
- **SD card module → Adafruit 4682 entry** had an entire
  "**Footprint / connector change:**" subsection covering the land
  pattern swap and mounting holes. Moved to a new PCB layout entry
  "SD card module — Adafruit 4682 header footprint + mounting
  holes". The schematic-side now has a one-line cross-reference at
  the same position so readers know where the footprint work lives.
- **I²C / RJ12 connector entry** title was "...connector layout —
  rename, add second outward bus". Two problems: "layout" inside a
  Schematic-section title is confusing, and "rename" referred to a
  silkscreen change that had already moved to PCB layout. Renamed
  to "I²C / RJ12 connector — swap DHT21 port to RJ12 + add second
  outward bus".
- **TVS clamp diodes entry** used the bullet header "**Placement:**"
  to describe netlist order (input → Schottky → TVS → bulk cap →
  load). "Placement" reads as physical PCB placement; the content
  is actually electrical sequence. Reworded to "**Position in input
  chain:**" so the schematic intent is unambiguous.
- **Schottky plan entry** described the deleted GND-return diodes
  as "Connector negative pins tie directly to system GND (copper
  trace, no diode)". "Copper trace" is layout terminology used for
  what is really a schematic intent (no series component in the
  return path). Reworded to "(no series diode in the return path)";
  the saved through-hole positions are still counted as a
  consequence.

What stayed in Schematic — borderline-but-defensible:

- Procurement-side footprint notes like "identical footprint family"
  (5 V VSYS bulk cap entry, justifying the voltage-rating bump fits
  the same body), "same SMA-family footprint" (TVS entry, uniform
  package across three SKUs), and "Footprint-constrained fallback
  parts" (Schottky entry, naming fallback SKUs if the primary part
  cannot be sourced). These are component-selection rationale, not
  layout work — kept.
- Decoupling-placement intent in component bullets ("close to the
  load", "leads as short as practical"). Standard schematic-side
  annotation that travels with the component; treated as design
  intent rather than layout DRC work.
- The F1 fuse rating bullet referenced the 2 oz / 3 mm trace
  fusing limit as a sanity check on the 10 A choice. The trace
  parameters themselves are layout-side, but they're cited here to
  justify a schematic-side component choice. Kept.

Rule going forward: a bullet stays in **Schematic** if its primary
action is component selection, value, or netlist topology, even when
it mentions layout consequences in passing. A bullet moves to **PCB
layout** if its primary action is footprint, placement, routing,
silkscreen, or DRC. Mixed entries keep one cross-reference line in
each section so the connection is one click away.

### decision · input connectors — XT60 on all three rails, drop banana-plug proposal

[`docs/hardware/next-revision.md`](../hardware/next-revision.md) had
two entries proposing different input-connector strategies: the
2026-05-23 "Power input connectors → XT60 across all three rails"
entry standardised XT60 on 5 V, 12 V, and 19.5 V; an older bullet
inside "External power connectors and silkscreen polish" still
called for banana plugs on the 12 V and 19.5 V rails with the 5 V
on the current Phoenix block. Both could not be right. Resolved in
favour of XT60 across the board — single connector SKU, 30 A
continuous headroom on every rail, one mating-tool requirement.
Banana-plug bullet removed.

### decision · merge older Schottky entry into the 2026-05-24 plan

The earlier "Replace 1N4002 input diodes with Schottky (+ bulk cap
at VSYS)" entry (filed 2026-05-19, updated 2026-05-22) had been
superseded by the 2026-05-24 "Schottky plan — single +rail diode
per input; delete D2 / D3 / D6" entry but still lived alongside it,
re-stating part choices and the D2-on-GND-return correction in
parallel. Folded the unique bits (post-fab XL4015 setpoint revert,
footprint-constrained fallback parts list) into the newer entry's
trailing bullets and deleted the older one. The Schottky story now
has one canonical home in the Schematic section.

### note · ride-along cleanups in the same pass

Two duplicates removed alongside the decisions above:

- The "Bulk capacitance on 12 V and 19.5 V rails" entry still
  listed 5 V VSYS at the stale **1000 µF / 6.3 V** value. The
  dedicated "5 V VSYS bulk cap voltage rating upgrade" entry
  already owns the corrected **16 V** spec; the duplicate bullet
  was replaced with a pointer to that entry.
- The "Board size reduction" entry carried a cross-reference
  bullet to the XT60 board-edge clearance discussion that lives
  in "External power connectors and silkscreen polish" — the two
  entries are adjacent in the same PCB layout section, so the
  pointer was redundant and was removed.
- Internal link in the SD card entry repointed from the deleted
  Schottky anchor to the surviving "5 V VSYS bulk cap" anchor.

## 2026-05-24 · next-revision.md restructured along EasyEDA workflow

### decision · group queued hardware changes by workflow stage instead of one flat Electrical / PCB section

[`docs/hardware/next-revision.md`](../hardware/next-revision.md) had
grown to ~30 entries under one **Electrical / PCB** heading, mixed with
**Mechanical / enclosure** and **Wiring / harness** at the bottom. The
section split no longer matched how the file is actually consumed
during a next-rev pass — schematic edits happen in EasyEDA's schematic
editor, then layout / silkscreen / DRC happen in the PCB editor, then
fab options are set at order time. Scrolling through one giant list to
find "what changes do I make in the schematic editor right now?" took
longer than it should.

**New section order — follows the EasyEDA workflow:**

1. **Schematic — nets, components, BOM** (component swaps, new parts,
   deleted parts, value changes, netlist topology, design decisions).
2. **PCB layout — footprints, routing, silkscreen, test points**
   (footprint changes, copper pours, trace widths, DRC clearances,
   silkscreen labels, test-point rows, board size).
3. **PCB ordering — fabrication settings** (copper weight, stackup
   options, anything set in the fab order form).
4. **Mechanical / enclosure** (kept as its own section; currently
   empty after the reshuffle but reserved for enclosure-only items).
5. **Wiring / harness** (off-PCB cables and connectors).

**Three sub-decisions during the restructure** (resolved via clarifying
questions before the edit):

- **Mixed-stage entries go under the primary stage** with the secondary
  noted in the body — e.g. MCP6002 → LM358N stays under Schematic
  because the component swap is the load-bearing change, with the
  DIP-8 socket footprint mentioned in the body. Avoided splitting
  every multi-stage entry into N pieces.
- **The old "PCB stackup → 2 oz copper, trace width, clearance"
  entry was split into two**: trace widths and DRC clearances went to
  PCB layout; the 2 oz copper fab option went to PCB ordering. The
  two new entries cross-link each other so the trace-width math
  (which assumes 2 oz copper) stays traceable.
- **Star-ground topology and TO-220 thermal management moved from
  Mechanical / enclosure to PCB layout**, where they belong — both
  are board-level routing / copper-pour changes, not enclosure work.
  The Mechanical section is now empty with a placeholder note
  explaining where its prior entries went.

**Cross-reference cleanup:** updated two "above/below" textual
references in the Heater channel count entry (which previously
pointed at the stackup and thermal entries in their old positions) to
point at their new section homes. Anchor-based markdown links are
unchanged because every heading text was preserved verbatim.

**Content preservation:** every existing bullet, body paragraph, link,
and date stamp was kept. Only the section headings around the entries
moved, plus the two-way split of the stackup entry. No queued change
was dropped, added, or reworded substantively.

## 2026-05-24 · SD card module switch — AZDelivery → Adafruit 4682

### decision · next revision replaces the AZDelivery generic SD breakout with **Adafruit 4682** (3 V Micro SD SPI/SDIO Bypass Card)

Current PCB carries an **AZDelivery "SPI Reader Micro Speicher SD TF
Karte" module** (Arduino-compatible generic). That family has an
onboard AMS1117-3.3 LDO regulator and (typically) a 74HC125 / equivalent
buffer to accept 5 V Vcc and 5 V logic. None of that helps a 3.3 V Pico
— the Pico already speaks 3.3 V directly, and the LDO + buffer add
heat, dropout, and an extra failure surface for no functional gain. The
generic module also has no card-detect signal and no published spec
sheet, which has cost bring-up time on this project.

**Replacement:** [Adafruit 4682 "Micro SD SPI or SDIO Card Breakout
Board"](https://www.adafruit.com/product/4682) — the **3 V bypass**
variant of the older Adafruit 254. Verbatim from the Adafruit product
page and pinouts page (2026-05-24 fetch):

- "For use with 3V power and logic microcontollers only!"
- "does not have level shifters"
- "Unlike our other adapter, it is not fixed for SPI usage, and can be
  used with SDIO hardware support."
- Power: **"3V — This is the power pin. MicroSD cards must use 3.3V"**
  and **"GND — common ground for power and logic"**.
- SPI pins: **"CLK, SO, SI, CS"** with **"Pull ups are provided on all
  SPI logic pins"** (value not published).
- SDIO pins: **"CLK, CMD, D0, D1, DAT2, D3"** with **"Pull ups are
  provided on all SDIO logic pins"**.
- Card detect: **"DET — Detect whether a microSD card is inserted"**,
  with **"a 4.7 kΩ resistor"** as the pull-up. Open when no card,
  pulled low (or vice-versa per the breakout's design — to be confirmed
  on a bench unit before firmware wires it).
- Dimensions: **25.4 mm × 22.8 mm × 3.5 mm**, 2.5 g.

**Why it's a fit:**

- No level shifter, no LDO → fewer parts in the SD signal chain, no
  thermal margin to budget, no extra dropout on the 3V3 rail.
- Onboard pull-ups on every SPI logic line → robust default state on
  CLK/SO/SI/CS even before firmware drives them.
- DET pin → firmware can finally distinguish "no card inserted" from
  "card present but mount failed", which the AZDelivery module can't
  report at all.
- SDIO-capable footprint → future-proof if the project ever moves off
  RP2040 (no native SDIO) to RP2350 (PIO-SDIO viable) or another MCU.

### correction · the prior 2026-05-24 entry described the Adafruit module as having a 74LVC125 level shifter — that's the Adafruit 254, not the 4682

[The earlier entry today on the SD-CS pull-up](#2026-05-24--sd-cs-pull-up-correction)
described the Adafruit Micro SD breakout as having "10 kΩ pull-ups on
the **card** side of its 74LVC125 level shifter." That description
applies to the **Adafruit 254** (the older SPI-only board with a
74LVC125 buffer), not to the **Adafruit 4682** chosen for this revision.
Per the 4682 product page: "does not have level shifters." The
"card side" / "Pico side" distinction therefore doesn't apply — both
ends of every signal pin on the 4682 are the same electrical node.
The Adafruit pinouts page also doesn't publish a value for the SPI
pull-ups; the **10 kΩ** value in the prior entry was assumed, not
confirmed.

Historical chat-log entries stay as written per
[documentation-routine.md](../../.claude/rules/ecc/common/documentation-routine.md);
this entry supersedes the prior description. The CS pull-up *decision*
still stands — see next sub-section.

### decision · keep the external 10 kΩ Pico-side CS pull-up — reasoning updated

The prior reasoning ("onboard pull-up is on the wrong side of a level
shifter") was wrong for the 4682. The corrected reasoning still
justifies the external resistor:

- The 4682's onboard SPI pull-ups exist but the value and exact node
  location relative to any series components are not published. Treat
  them as "present, unspecified."
- A defined CS state during MCU power-on-reset is needed because the
  SD card samples CS during its own internal reset to choose SPI vs
  SDIO mode. A floating CS can lock the card into SDIO mode, after
  which the SPI init in [lib/sdcard.py](../../lib/sdcard.py) refuses
  to mount — the classic "first boot fails, second boot works" SD
  failure mode.
- One **10 kΩ 0603 from GP13 to 3V3** guarantees a defined Pico-side
  CS during MCU reset regardless of the breakout's topology. In
  parallel with whatever onboard pull-up exists, the combined value
  stays well within the SD spec for CS pull-up (≤ 50 kΩ). One
  resistor, ~$0.01 BOM, eliminates an entire class of intermittent
  boot failures.

No external pull-ups on MOSI / MISO / SCK. R8 = 33 Ω MISO damper and
R10 = 33 Ω MOSI damper stay per the
[2026-05-23 EasyEDA review](#2026-05-23--easyeda-files-design-review)
and the [R8 next-rev entry](../hardware/next-revision.md).

### decision · SD module supply moves from 5 V (via onboard LDO) to 3V3 directly

AZDelivery generic module accepts 5 V Vcc and drops it through an
onboard AMS1117-3.3 LDO. 4682 has no regulator and requires 3.3 V
directly. PCB change: the SD module power net switches from `5V` to
`3V3`. Net consequences:

- **Pico 3V3 reg current budget tightens.** RP2040 internal 3V3
  regulator (RT6150 buck-boost) is rated 800 mA continuous, shared
  across the Pico itself, SHT31, DS3231, SSD1306 ×2, MCP4725, future
  PCA9685, and now SD. SD active write draws ~50–100 mA average with
  inrush peaks to ~200 mA. Margin is still comfortable but the
  budget should be re-checked once PCA9685 + SDIO future-work are
  on the bus.
- **Bulk decoupling moves locality.** The
  [VSYS 1000 µF entry](../hardware/next-revision.md) was sized to
  absorb SD inrush on the **5 V** side of the AMS1117. With SD on
  3V3, that cap still helps the upstream 5 V rail but doesn't
  decouple SD inrush from the 3V3 node where it now lives. Add a
  **100 µF + 100 nF** decoupling pair right at the 4682's 3V pad.
  Cheap, near-the-load placement, doesn't bloat the BOM.
- **Free silicon on the BOM.** No more AMS1117 dissipating
  ~(5 V − 3.3 V) × 100 mA = 170 mW in the SD module's plastic body.
  No more 74HC125 level shifter (the AZDelivery has one). Both are
  failure modes that just leave the design.

### decision · wire DET (card detect) to a free Pico GPIO

The 4682 exposes a DET pin that's electrically isolated from the
SPI signals and pulled up via 4.7 kΩ. This is new capability vs.
the AZDelivery, which has no card-detect.

- **Wire DET to a free GPIO** (candidates: GP14, GP15, GP16 — all
  currently unassigned per [config.py:55-98](../../config.py#L55-L98)).
  Leaning toward **GP15** because it's adjacent to the existing SPI
  block (GP10–GP13), keeping the SD signal cluster compact in
  layout.
- **Firmware-readable card presence** lets
  [HardwareFactory](../../lib/hardware_factory.py) and the
  [SD recovery loop](../../main.py) distinguish "no card inserted"
  (operator pulled the SD card → fall back gracefully, don't waste
  retry budget) from "card present but mount failed" (genuine bus
  / filesystem fault → escalate to the SD-problem LED).
- Treat as a **revision-scoped enhancement, not a blocker.** The
  module swap works without wiring DET; the GPIO line and firmware
  change are an optional follow-up.

### note · firmware and config implications

- **SPI pin assignments unchanged.** GP10/11/12/13 stay as
  SCK/MOSI/MISO/CS per [config.py:108-115](../../config.py#L108-L115).
  The 4682's CS pin maps 1:1 to the AZDelivery module's CS pin from
  the firmware perspective.
- **Timing constants likely unchanged.** Without the AMS1117 LDO
  ramp and 74HC125 buffer init, the 4682's cold-start envelope
  should be *at least as fast* as the current module. Current
  values:
  - `sd_power_up_ms = 1500` (cold stabilization delay)
  - `sd_mount_retries = 3`
  - `sd_retry_delay_ms = 1000`
  - `spi.baudrate = 10_000_000` (capped from 40 MHz post-2026-05-16
    R8 incident; the swap doesn't unblock raising this — that
    would need a separate bench validation pass)

  Leave all four as-is until a 4682 is on the bench and cold-mount
  timing is measured. Don't pre-tune speculatively.
- **`sdcard.py` driver is unchanged.** Standard SPI-mode SD protocol
  is identical between the two breakouts.
- **If DET is wired:** new `DEVICE_CONFIG["pins"]["sd_detect"]` entry,
  matching `validate_config()` row, and a `tests/test_config.py`
  row per
  [configurability.md](../../.claude/rules/ecc/common/configurability.md).
  Wired into `HardwareFactory` to short-circuit the mount-retry loop
  when the card is physically absent.

### note · hot-swap recovery code must be refactored once DET is live

The current SD hot-swap path at
[main.py:942-981](../../main.py#L942-L981) polls `refresh_sd()`
(block-level `readblocks` over SPI) every health-check interval
whenever `is_primary_available()` is false *or* `buffered > 0`. That's
the only mechanism available today — the AZDelivery module can't
report card presence at all, so the firmware has to probe the bus to
find out whether the operator pulled the card or the card itself is
sick. Once the 4682's DET pin reaches GP15 the loop should be
rewritten:

1. **Skip `refresh_sd()` entirely when DET reads "no card".** Saves
   the SPI traffic, the CPU cycles, and stops emitting misleading
   `logger.warning("SD card not accessible, retrying soon")` entries
   when the operator deliberately pulled the card. Today those
   warnings fire every 10 s for as long as the card is out, which
   makes the EventLog noisy and conceals genuine bus faults.
2. **Trigger an immediate remount on the DET absent → present edge**
   instead of waiting up to `sd_recovery_interval_s = 10 s` for the
   next health-check tick. Poll-driven now; edge-driven once DET is
   wired.
3. **Surface three distinct states to `StatusManager`** —
   `no_card_inserted`, `mounted`, `mount_failed` — replacing today's
   binary `sd_status` flag. The `sd_problem_led` behaviour and the
   boot-time `require_sd_startup` reset path should both branch on
   the new states so a missing card lights a different indicator
   than a real SPI / filesystem fault.

**Sequencing:** firmware-only follow-up that lands **after** the new
PCB lands and DET polarity is confirmed on the bench — not part of
the hardware change itself, and not part of the initial `sd_detect`
config + `HardwareFactory` wiring commits. Each piece ships as its
own commit per
[commit-granularity.md](../../.claude/rules/ecc/common/commit-granularity.md):
`sd_detect` config plumbing → `HardwareFactory` reads DET → recovery
loop refactor → `StatusManager` tri-state.

### note · current PCB stays on the AZDelivery module until the next fab run

Don't yank the existing module — the SPI signal contract is the same
(GP10/11/12/13), and the only field change available right now is
the [interim XL4015 setpoint](#2026-05-19--external-5-v-supply-starves-vsys--1n4002-drop-traced)
which is unrelated. The 4682 lands when the next PCB lands, which
already needs the Schottky swap and the rest of the queued changes.

## 2026-05-24 · Input diode topology correction — drop GND-return diodes

### decision · single Schottky per input rail; delete D2 / D3 / D6

Earlier next-rev plan listed all six input diodes (D1–D6) for Schottky
replacement on the assumption that each rail had two diodes in series
on the +line — the project-power-input-revision memory literally said
"two 1N4002 silicon diodes sit between the XL4015 5 V buck output and
the Pico VSYS." That framing was wrong.

**Actual topology from `Sheet_1_2026-05-22.net`:** each input has one
diode on the **positive line** (D1 on 5 V, D4 on 12 V, D5 on 19.5 V)
and one on the **GND return** (D2 on 5 V GND, D3 on 12 V GND, D6 on
19.5 V GND). Normal current loops through both — combined drop is the
same ~1.6 V per rail, but the diodes aren't physically stacked on one
trace. It's a "balanced" reverse-polarity scheme: if the connector is
plugged in backwards, both diodes block, no current flows.

**Three options considered for the next rev:**

1. **Single Schottky on +line only, tie GND directly, drop D2/D3/D6.**
   ~0.3 V loop drop, three fewer parts, same protection (reversed
   connector → +line Schottky reverse-biases → no current).
2. **P-channel MOSFET on +line.** Zero forward drop, full protection,
   more parts and layout complexity. Overkill at these currents.
3. **Keep dual-diode but both Schottky.** ~0.6 V loop drop. Worse than
   option 1 with no benefit.

**Decision: option 1.** Final input-protection diode set on next rev:
**D5 → MBR20100CT** (heater path, unchanged), **D1 / D4 → MBRD1045**
(single SKU for both +rail Schottkys), **D2 / D3 / D6 → deleted**
(connector negatives tie directly to system GND via copper).

Cuts ~0.8 V of GND-return drop per rail, frees the ~1.3 V VSYS
headroom currently consumed by two-diode loss, halves the +rail part
count for input protection.

## 2026-05-24 · SD-MISO pull-up correction (supersedes the CS draft)

### decision · add 10 kΩ from SD-MISO (GP12) to 3V3 on the next PCB

The 2026-05-22 next-revision entry was originally filed as "remove the
10 kΩ resistor currently on the SD card line." First operator
correction said the resistor wasn't on the PCB — meaning the note was
a candidate **addition**, not a removal. Reframed as an addition.
Second operator correction today: the resistor is on **GP12 (MISO)**,
not GP13 (CS). The earlier reframe assumed CS. Both the doc and this
chat-log entry are now updated to MISO.

**Electrically justified.** MISO is tri-stated by the card outside
response windows — CS high, no card inserted, or during the 80+ dummy
clocks the SPI init in `lib/sdcard.py` sends before CMD0. With MISO
floating, the Pico's SPI peripheral latches garbage (0x00 / 0xFF /
noise depending on board capacitance and trace coupling) and the init
state machine either misreads a false response or misses the real
one. A 10 kΩ pull-up to 3V3 establishes a defined idle-high state —
matches the SPI mode convention; "no response yet" reads as 0xFF,
which is what `sdcard.py`'s timeout logic expects.

It coexists cleanly with R8 (33 Ω MISO damper): R8 sits in series on
the trace for edge damping; the 10 kΩ is a shunt to 3V3 on the Pico
side. The Adafruit 4682 has an onboard pull-up on MISO at unspecified
value; the external 10 kΩ guarantees the idle state regardless of the
4682's internal topology and keeps the combined value inside SD spec
(≤ 100 kΩ on DAT lines).

Decision: add one 10 kΩ 0603 from GP12 to 3V3. No external pull-ups
on CS / MOSI / SCK — those are actively driven by the Pico or by the
card during transactions and don't need idle clamping. The GP12 line
was originally noted in the button-rework bench notes by accident;
moved to the SD section in next-revision.md where it belongs
electrically.

## 2026-05-24 · LM358 footprint switch to DIP-8 socket

### decision · use LM358N in stock via a DIP-8 socket footprint, drop the LM358DR SOIC-8 plan

The 2026-05-23 next-revision entry called for **LM358DR (SOIC-8)** as
a pin-compatible drop-in for the MCP6002 — i.e. keep the SOIC-8
footprint and order new SOIC parts. Today's operator preference:
**keep the LM358N (DIP-8) already in stock** (10 pcs from order
3071191067167331) and instead **change the next-rev footprint** from
SOIC-8 to a DIP-8 socket land pattern. DIP-8 sockets are already on
hand from the 66-pc socket kit (order 3071191067207331).

Trade-offs:

- **Pro:** zero procurement step for the op-amp; the chip can be
  swapped without rework if it ever fails; through-hole DIP is
  hand-solderable for bring-up boards too.
- **Con:** DIP-8 occupies ~3× the SOIC-8 board area (~10 × 10 mm vs.
  ~5 × 4 mm). Layout pass on the next rev re-checks the op-amp
  footprint clearance against the adjacent GL_DIM connector and the
  12 V rail trace.

Gain divider (R4 = 10 kΩ, R5 = 4.7 kΩ) and the 10.3 V max output
calculation are unchanged — both resistor values are in the WayinTop
600-pc kit, so no new resistor order either. The next-rev entry,
inventory shopping list, and `project-grow-light-opamp-revision`
memory were all updated in the same session to reflect the new path.

## 2026-05-24 · 19V power supply spec correction (Dell 180W brick)

### spec · actual brick is Dell 180W, 19.5V / 9.23A, not generic 19V

The supply feeding the heater-side input rail is a **Dell 180W AC
adapter, model "DWSG3" (label string approximate, to be re-verified
on the part)**. Nameplate:

- Input: 100–240 V~, 50–60 Hz, 2.5 A
- Output: **19.5 V DC, 9.23 A** (180 W)

Prior docs referred to this rail as "19 V" with a 9.2 A figure (see
[project-power-input-revision memory](../../../.claude/projects/l--projects-Pi-Greenhouse-Git-codebase/memory/project_power_input_revision.md)
and the 2026-05-22/23 chat-log entries below). Both numbers were
shorthand approximations of the real brick spec; this entry pins
them down. The brick is now catalogued in
[inventory.md → External power supplies](../hardware/inventory.md).

### decision · rename rail label "19V" → "19.5V" across active docs

Active artifacts (next-revision.md, hw-test-log.md, inventory.md,
the power-input memory) get the rename. Historical chat-log entries
stay as written — they reflect the understanding at the time and
this entry supersedes them. Net-level identifier `19V_IN` is
**retained** as a schematic net name (it's an identifier, not a
voltage spec; renaming would force netlist regeneration in EasyEDA
without changing anything electrical).

Downstream parts already specced for this rail keep their values —
all were sized with headroom over 19.5 V:

- **D5 = MBR20100CT** (100 V) — fine.
- **MBRD1045** D-PAK Schottkys on the 19.5 V series/shunt (45 V) — fine.
- **SMAJ24CA TVS** (24 V working, ~39 V clamp) — fine; 24 V working
  voltage was already chosen for headroom over the 19 V approximation,
  so the 0.5 V correction lands well within margin.
- **470 µF / 35 V bulk cap** — 35 V on a 19.5 V rail is 56 % derating,
  unchanged from prior calculation.
- **8.2 kΩ power-good LED resistor** — designed for ~2.1 mA at the
  rail voltage; at 19.5 V draws ~2.2 mA (still in the visible-uniform
  bracket).

No re-spec needed; just the label correction.

### note · silkscreen text width on next-rev PCB

`19.5V` is 5 glyphs vs. `19V` at 3 glyphs. Layout pass on the next
rev should confirm the existing silkscreen area next to the 19.5 V
XT60 still fits the label cleanly at the chosen font size; shrink to
`19V5` (no decimal, common convention) only if the longer string
collides with another silkscreen feature. Logged here so the layout
session doesn't burn time re-discovering the constraint.

## 2026-05-24 · parts-on-hand inventory + shopping list against next-revision

### note · inventory.md catalogues current storage and surfaces what to order

Operator dumped the storage list (AliExpress + Amazon orders) and asked
for a sorted inventory cross-referenced against
[next-revision.md](../hardware/next-revision.md). Result:
[docs/hardware/inventory.md](../hardware/inventory.md) — by-function
parts list with a shopping-list comparison section at the bottom.

### issue · LM358N on hand is DIP-8, not the SOIC-8 originally specced for the fab — *resolved by footprint switch*

Order from 2026-04-10 was **LM358N DIP-8**, but the original
2026-05-23 next-revision entry called for **LM358DR (SOIC-8)** as a
pin-compatible drop-in for the MCP6002. Initial conclusion: the
DIP part is only useable on protoboards and the fab still needs
SOIC-8. **Superseded** later the same day by the "LM358 footprint
switch to DIP-8 socket" decision above — the fab now uses a DIP-8
socket footprint and the on-hand LM358N is the chosen part.

### issue · 100 pcs fuse kit is F-rated (fast-blow), F1 needs T (slow-blow)

The 5×20 mm fuse assortment on hand is **F (fast-blow)** including the
10 A value, but
[next-revision: F1 fuse — 10 A 5×20 mm slow-blow](../hardware/next-revision.md)
requires **T-rated** to ride out the bulk-cap inrush without nuisance
trips. Order Littelfuse 0234010.MXP (or equivalent 10 A T) separately.

### note · XT60PW-F is the correct board-edge variant of XT60

Order from 2026-04-15 explicitly bought **XT60PW-F** (the panel /
PCB-mount female with the right-angle prongs), not just bullet XT60.
That's the variant needed for the
[next-revision: XT60 across all three rails](../hardware/next-revision.md)
entry — five units, one per rail with two spares. Worth recording so
future sessions don't re-order regular XT60 thinking the board-mount
variant is missing.

### issue · 1N5822 (DO-27, 3 A) is not a substitute for MBRD1045 on the fab

Order from 2026-04-15 bought 20× **1N5822** axial Schottky (3 A / 40 V),
which is **under-rated and wrong package** for the MBRD1045 (D-PAK,
10 A / 45 V) spec on D1–D4 and D6. Useable on protoboards for
sub-3 A bench rigs only; the fabricated board still needs MBRD1045.

### issue · soil-moisture sensor refund leaves 10 pcs "as-is" stock

Order from 2026-02-15 for 10× capacitive soil-moisture sensors was
refunded by the seller without return ("as our high-loyalty
customer"). Sensors are physically on hand and useable for the
[next-revision: ADC / soil-moisture interface](../hardware/next-revision.md)
stage; no need to re-order. Recorded so the cost basis is clear if
the original invoice is audited later.

### note · two previously-undocumented AliExpress orders identified

Two 2026-02-15 orders showed totals only on the order list page.
Operator re-read the product pages to identify them, and the
contents are now catalogued in [inventory.md](../hardware/inventory.md):

- **3068920990267331** (MINGYUE TRADING, 9.83 €) — 5× **IEC320 C14
  panel inlet** with rocker switch + LED + 10 A fuse holder
  ("AC-08A"), plus 2× packs of 10× 5×20 mm 10 A glass fuses (for
  the inlet, not for F1 on the PCB). System-level AC mains entry
  for the enclosure; not currently a queue item on next-revision.
- **3068920990097331** (HUI JI, 4.92 €) — 30× M3 brass hot-melt
  inserts (6 mm length, OD 4.5 mm, for threading the 3D-printed
  enclosure) + 30× M3 hex brass M / F standoffs (6 mm thread + 6 mm
  body, for PCB-to-enclosure mounting).

Earlier draft of this note had the HUI JI order number as
**3068920990337331** — that's actually the **VEML7700** light
sensor order. Corrected in the inventory source-trail.

## 2026-05-23 · EasyEDA files design review

### note · critical review of current schematic against next-revision queue

Operator added the EasyEDA export (BOM, schematic JSON, netlist) for
the current PCB revision under
[docs/hardware/EasyEDA-Files/](../hardware/EasyEDA-Files/) and asked
for a critical pass to find what the next-revision queue was missing.
Result: 18 new queued entries in
[next-revision.md](../hardware/next-revision.md), of which the items
below are the load-bearing decisions or specs that don't fall out of
the schematic on a second read.

### decision · MCP6002 op-amp → LM358DR, gain divider retuned to 10 k / 4.7 k

MCP6002T-I/SN abs-max V_DD-V_SS is 7.0 V; the current schematic powers
it from the 12 V rail (op-amp pin 8 on the 12 V net). Operating
~5 V above absolute maximum — the chip degrades silently and was the
likely root cause of any flaky grow-light dim behaviour. Replacement:
**LM358DR** in the same SOIC-8 footprint, V_CC max 32 V, pin-compatible
drop-in. LM358 is not rail-to-rail at the top — that's a feature here:
at 12 V supply the output swings to ~10.5 V max, a natural ceiling
below the 10 V dim-signal damage threshold. Feedback divider retuned
from the existing R4 = 47 k / R5 = 20 k (gain ≈ 3.35 → 11 V max, above
spec) to **R4 = 10 kΩ / R5 = 4.7 kΩ** (gain = 1 + 10/4.7 = 3.13 → 10.3 V
max). Firmware clips to 10 V via `growlight.max_level_pct` so brief
over-spec excursions can't happen.

### decision · two-SKU Schottky plan — MBR20100CT for D5, MBRD1045 elsewhere

Earlier note (2026-05-22) settled on MBR20100CT for all six diodes
"because it's on hand". Critical re-read reveals D5 alone needs the
20 A package — at 3.4 A heater current the existing 1N4002 is at 3.4×
continuous rating and is a fire hazard, not just an efficiency issue.
Initial follow-up draft used **SS54** (5 A SMA) for the other five
diodes, but cross-checking against rail capacities (5 V/5 A, 12 V/9 A,
19 V/9.2 A) shows SS54 at the 12 V or 19 V buck would run at or above
its rated current. Final plan: **D5 → MBR20100CT** (TO-220, 20 A) on
the heater path, **D1–D4 and D6 → MBRD1045** (D-PAK, 10 A / 45 V)
everywhere else. Two SKUs across the rail-protection diodes
(~$0.45 × 5 = $2.25 + MBR20100CT), 10 A headroom across all buck
capacities, larger D-PAK tab also helps thermal margin. V_f drops
from ~0.8 V to ~0.3 V at every node. SS14 stays as a third SKU for
the VBUS / DEBUG_CON backfeed-protection diodes (different package,
low current path).

### decision · power-input connectors standardised on XT60 across all three rails

Current PCB mixes connectors per rail (5 V Phoenix block, 12 V JST
B2B-XH at ~3 A rating against a 9 A buck, 19 V XT60). The 12 V JST is
a thermal liability under multi-fan load. Decision: all three input
rails get **XT60** connectors. XT60 is rated 30 A continuous, single
connector family across the board, one cable type in the harness,
massive headroom for every rail. Silkscreen labels `5V` / `12V` /
`19V` plus `+` / `-` polarity marks next to each XT60 — XT60 is keyed
but redundant polarity labelling catches reversed crimps during
harness assembly. Board-edge clearance issue already tracked under
"External power connectors and silkscreen polish" needs re-checking
for all three XT60s after layout.

### decision · PCB stackup → 2 oz copper, heater trace 3 mm, 0.15 mm clearance

Three layout decisions land together because they all trade off
copper weight against trace width and clearance. Fab order specifies
**2 oz copper on both outer layers** (vs default 1 oz) — roughly
doubles current-carrying capacity per mm of trace width and assists
the TO-220 thermal pour. **Heater current path = 3 mm minimum trace
width** on 2 oz copper (handles 6.8 A parallel-heater case at <30 °C
rise per IPC-2221); **12 V buck output = 2.5 mm minimum** (handles
9 A). **Default trace clearance: 0.15 mm** (down from 0.2 mm) to free
layout real estate for the bulk caps, TVS clamps, and new gate
driver footprints near the input area — safe for sub-50 V nets.
Power traces keep 0.3 mm clearance to the adjacent net.

### decision · 5 V VSYS bulk cap voltage rating bumped from 6.3 V to 16 V

Earlier entry pinned the 5 V VSYS bulk cap as 1000 µF / **6.3 V** —
79 % voltage derating at 5 V nominal, tight for long-life
electrolytics with TVS clamp transients in the picture. Bumping to
**1000 µF / 16 V** drops derating to 31 %, costs ~$0.10 more, same
footprint family. The 12 V and 19 V bulk caps already specified are
fine (220 µF / 25 V = 48 % derating, 470 µF / 35 V = 56 % derating).

### decision · F1 = 10 A 5×20 mm slow-blow glass cartridge

Single MOSFET channel with two parallel 100 W / 24 V heaters at
19.6 V draws 6.8 A steady-state. Fuse spec: **10 A T (slow-blow),
5×20 mm glass cartridge** in through-hole holder — Littelfuse
0234010.MXP or equivalent. T-rating tolerates the bulk-cap inrush
spike without nuisance trips; 10 A clears on a hard short well
within the trace-fusing limit of 3 mm at 2 oz copper. Replaces the
earlier 5 A fast-blow placeholder. Position: upstream of D5.

### decision · MCP1416T-E/OT gate driver for HE_MOSFET (PWM-ready)

Direct-driving the IRLZ44N gate from Pico GP3 at 3.3 V leaves the
MOSFET in the linear region of its V_GS curve: R_DS(on) ~0.05–0.08 Ω,
~2 W package dissipation at 3.4 A heater current. At 6.8 A
(parallel-heater single-channel decision above) the gate-drive
shortfall becomes a thermal cliff. Add **MCP1416T-E/OT** (SOT-23-5,
1.5 A peak, ~$0.40) powered from the 5 V rail. Drives the gate
0 → 5 V cleanly; R_DS(on) drops to ~0.022 Ω → ~1 W dissipation at
6.8 A. Wiring: GP3 → MCP1416 IN → MCP1416 OUT → R6 = 47 Ω (was
100 Ω, shrunk now that the driver can source the current) → IRLZ44N
gate. Add **10 kΩ pull-down from MOSFET gate to source/GND** so the
heater stays OFF during Pico boot / reset (otherwise the gate floats
while GP3 is high-Z, partial turn-on possible). Side benefit: GPIO
sources only µA, switching edges become clean, EMI improves.

### decision · single-channel heater + parallel heaters + PWM-later

Three open items collapse into one decision. Operator confirms two
heaters always run in parallel (surface-area / wattage goal, no
selective-control use case). That points to **single-MOSFET
channel (option a)**, not the earlier "recommended" dual-channel
plan. Current handled by the F1 / D5 / MCP1416 / IRLZ44N / trace
stack-up specced above. **Heater PWM is queued for a later firmware
revision** — the MCP1416 makes audio-frequency PWM electrically
viable on GP3; firmware adds duty-cycle modulation when the control
loop wants finer than on/off. Schematic / PCB lands the gate driver
now to keep the door open.

### decision · MBRD1045 vs SS54 trade-off

Diode comparison summary captured for future reference:
**SS54** (SMA, 5 A / 40 V, ~$0.15) — small footprint, low cost,
adequate for a 5 A buck rail but **at the rated limit** for the
12 V/9 A and 19 V/9.2 A bucks. **MBRD1045** (D-PAK, 10 A / 45 V,
~$0.45) — 3× cost, 2× footprint area, ~150 pF junction capacitance
(vs ~120 pF for SS54, negligible at rail-protection frequencies),
same V_F at operating current, larger thermal tab. Net: replacing
all SS54s with MBRD1045 costs ~$1.50 per board for 2× current
headroom across every rail-protection diode. Decision goes to
reliability over cost on a system meant to run weeks without
intervention.

### decision · keep R8 = 33 Ω; fix the firmware comment instead

`config.py:36-40` claims R8 was removed after the 2026-05-16/18 SD
bit-error incident. Physical board (per BOM and netlist) still has
R8. The 2026-05-19 root-cause was VSYS starvation, not R8 itself —
once the Schottky + bulk cap lands, VSYS stabilises and R8 acts as a
useful SPI signal damper at the 10 MHz baud. Decision: leave R8 in
place on the next rev, update the firmware comment to align with
reality. Filed as a non-PCB cleanup to ship with the next-rev sweep.

### spec · Senseair S8 UART TXD is 5 V TTL, not 3.3 V

S8 datasheet says UART logic is referenced to V+ (the 5 V supply).
Pico GPIO abs-max is 3.3 V + 0.5 V = 3.8 V — the existing 100 Ω in
series (R11) is signal damping, not voltage protection. The Pico's
internal clamp diodes have been shouldering ~10 mA into the 3V3 rail
on every UART byte, which works but degrades the input pin over
weeks of continuous logging. Fix is a divider on the RX line:
R11 → 2.2 kΩ in series, new 3.3 kΩ to GND, output 3.0 V — well within
Pico spec at 9600 baud over 1 m cable. R9 on the TX line stays
100 Ω; Pico's 3.3 V drive clears the S8 RX threshold (~1.5 V) easily.

### spec · heater wattage scales with V², not linearly

A 24 V / 100 W resistive heater is **5.76 Ω**. At 19.6 V it dissipates
P = V²/R = **66.7 W** and draws **3.4 A** — not the linearly-scaled
~82 W an operator might calculate. F1 = 5 A fast-blow keeps ~50 %
headroom over steady-state current; no fuse change needed for the
single-heater case.

### decision · parallel-heater handling — schematic choice deferred

Two 24 V / 100 W heaters in parallel = 2.88 Ω → 6.8 A → 134 W at
19.6 V. Exceeds F1 = 5 A and stresses the IRLZ44N. Three options
queued in next-revision.md under "Heater channel count":
(a) single MOSFET, bump fuse to 7.5 A T-rated, 16 AWG harness;
(b) two MOSFETs on two GPIOs with two fuses (each channel sees 3.4 A
within today's envelope, supports graceful degradation, recommended
for weeks-of-uptime);
(c) PWM at ~50 % duty cycle (peak current unchanged so fuse still
trips; IRLZ44N at 100 Ω gate doesn't switch fast enough for clean
audio-range PWM anyway). Final pick deferred to schematic-design
time.

### decision · I²C pull-ups R1/R2 → 2.2 kΩ for fast-mode rise time

`config.py.system.i2c_freq = 400000` (fast mode). Bus carries 7+
devices (Pico + RTC + OLED + DAC + SHT31 + future PCA9685 + three
external drops) with estimated bus capacitance ~250 pF. With
R1/R2 = 10 kΩ the RC rise time is 2.5 µs — ~8× the I²C fast-mode
limit of 300 ns. Dropping to 2.2 kΩ brings rise time to ~550 ns,
within spec at the device-end inputs after RC settling. Likely
suspect for any "MCP4725 doesn't respond" or "OLED tears"
intermittent symptoms.

### decision · TVS clamp diodes use three SMA-family values

One TVS part can't optimally protect 5 V, 12 V, and 19 V at the same
time — clamp voltages differ by ~30 V across the range. Instead of
compromising on a single high-value part, queue **three SMAJ values
in the same SMA footprint and supplier family**: SMAJ5.0CA on 5 V,
SMAJ15CA on 12 V, SMAJ24CA on 19 V. Three reels, uniform package,
proper clamping at each rail. Bidirectional `CA` parts handle either
input polarity — useful on the Phoenix terminal block where reversed
wiring is plausible.

### decision · star-ground heater current return at input node

Common GND plane stays single. Layout rule: the HE_MOSFET source pad
routes via a wide trace **directly to the 19V_IN GND terminal**, not
into the general logic-side GND pour. Logic ground merges at the
input GND node. Effect: heater switching current (3.4 A today, up to
6.8 A if both heaters land on one MOSFET) loops through dedicated
copper, not through the I²C / RTC / Pico ground return paths. Avoids
ground bounce that could glitch the bus or reset the MCU during
heater on/off transitions.

### decision · TO-220 thermal pattern is copper pour PLUS clip-on heatsink

At 3.3 V gate drive the IRLZ44N R_DS(on) is ~0.05–0.08 Ω → ~2 W
dissipation at 5 A heater current → junction at ~150 °C in free
air with no heatsinking (62 °C/W thermal resistance). Borderline,
fails over weeks. Pattern for every TO-220 carrying real load: 1 sq
inch copper pour on both layers, 6–10 thermal vias to stitch them,
plus a clip-on SK 104-25 STS heatsink ($0.50). Net thermal resistance
drops to ~20–30 °C/W; junction lands 40–60 °C above ambient at 2 W.
Applied to HE_MOSFET first; also applies to any future PCA9685 +
MOSFET fan stage.

### note · PCB enclosure sits outside the greenhouse; sealing concern shifts

Original review flagged conformal coating for the PCB. Operator
clarifies: the main PCB and its enclosure live outside the greenhouse
proper. Only the sensor cables (RJ12 to SHT31, S8, soil ADC), the
two ambient fan cables, the case fan (in-case only), and the
grow-light DAC cable enter the greenhouse atmosphere. Moisture
protection accordingly applies to the cable ends and sensor breakout
enclosures, not the main PCB. Queued under Wiring / harness.

### note · LED current target 2 mA gives uniform brightness across four rails

A single resistor value across all power-good LEDs gives wildly
uneven brightness (1.3 mA on 3V3 vs. 17 mA on 19 V with 1 kΩ). At
2 mA the LED runs comfortably below typical 20 mA max, drastically
extending operating life across weeks of always-on use. Resistor
values per rail: 680 Ω (3V3), 1.5 kΩ (5 V), 4.7 kΩ (12 V), 8.2 kΩ
(19 V). Different values per rail are intentional — uniform current
beats uniform BOM line at this scale.

### note · Pico footprint label is V2 but board uses V1

BOM row 37 specifies footprint `RPI-PICO-V2 COPY` but the operator
confirms the actual part on hand is the original Pico (V1, RP2040).
V2 was simply the best-fitting footprint at design time. Pinout is
identical so no electrical change needed; queue a silkscreen /
footprint label rename only.

## 2026-05-22 · Next-revision planning from bench notes

### note · operator handed over a flat list of bench observations

Single batch of accumulated bench notes (mix of layout fixes, missed
features, and component choices) consolidated into
[docs/hardware/next-revision.md](../hardware/next-revision.md). Each
note filed as its own entry under the existing Electrical / PCB or
Mechanical / enclosure section. This entry captures the decisions and
non-obvious interpretations behind the consolidation; the individual
queue items live in next-revision.md.

### decision · chosen Schottky part is MBR20100CT

The 2026-05-19 entry listed SS14 / 1N5817 / MBRS340 as candidates.
Operator has settled on **MBR20100CT** (TO-220, 20 A / 100 V). Massive
overkill for a 5 V input rail at well under 1 A, but it's already on
hand and the headroom costs nothing in this footprint. The smaller SMA
and DO-41 parts stay as fallback if the TO-220 doesn't fit the next
layout. Bulk cap value also pinned at **1000 µF** (upper bound of the
previous 470–1000 µF range), in parallel with 100 nF ceramic.

### decision · button topology — menu_btn debounced, reset_btn direct

Earlier note (2026-05-19) sketched GP9/reset_btn with a 10 kΩ pull-up,
1 kΩ series, and a "needs testing" capacitor. After bench thought,
revised: **reset_btn is direct contact only** (no pull-up, no series,
no cap), and **menu_btn carries the 10 kΩ pull-up + debounce cap.**
The menu button is the one actually broken on the current board, so
the debounce and pull-up belong there. The 3V3_EN → GND capacitor
that was previously sketched is also dropped — not needed. A separate
10 kΩ pull-up on GP12 to 3V3 is queued alongside.

### decision · banana plugs on 12 V and 19 V only; 5 V stays as-is

Power input survey concluded with banana-plug breakouts for the 12 V
and 19 V rails (the two rails most likely to be probed during bench
work and external load testing). 5 V stays on the existing connector —
it's already constrained by the XL4015 + Schottky / VSYS work, and
adding a banana plug there would invite probes into a rail with little
abs-max margin.

### decision · relays carry only 230 V mains after fan move

Once the PCA9685 + IRLZ44N stage lands and fans move off the relays,
the remaining relays carry **only 230 V mains loads** (grow light,
heater). This changes the connector spec (creepage / clearance,
terminal block style) and the silkscreen labels for the relay section
in the new rev. The dead "3V3" pin on the current relay connector
gets re-tied to GND in the same pass so the pinout is meaningful.

### decision · soil-moisture ADC divider is 10 kΩ + 15 kΩ

Soil-moisture sensor outputs 0–5 V analog; Pico ADC is 0–3.3 V max.
Divider chosen: **10 kΩ top + 15 kΩ bottom** between sensor output and
ADC pin. 5 V full-scale → ~3.0 V at the Pico (margin under abs max).
ADC connector also gains a 3V3 pin so 3V3-powered analog peripherals
can be powered from the same jack.

### note · I²C / RJ12 layout is about external accessibility

The terse note "i2c port 1 → sht31, t/h port: gp port (and another
i2c please)" is **not** about renaming bus addresses or moving
peripherals between buses. It's about the **outward-facing RJ12
connectors** on the enclosure wall. Plan: rename the silkscreen
label of the existing I²C connector to "SHT31" (since that's the
only device that uses it), add a **second outward-facing RJ12
connector** for an additional I²C drop, and replace the current
DHT21-style port with an I²C-compatible one for the SHT31 itself.
Bus topology (one I²C bus or two) stays flexible — what matters is
the second exposed jack on the case so future I²C peripherals don't
need bus stubs through the wall.

## 2026-05-19 · External 5 V supply starves VSYS — 1N4002 drop traced

### issue · root cause of SD / boot failures on external 5 V supply

Symptoms on the production wiring (XL4015 buck + 1N4002 input diodes →
Pico VSYS): boot halts after the I²C1-init line in `/boot.log`,
sometimes with sd+error LEDs lit, sometimes silent with the relay
LEDs dim-then-HIGH cycling on WDT reset. Working from USB power.
Bench measurements:

- Connector (pre-diode): 4.99 V
- Post-diode → Pico VSYS: **3.05–3.4 V**
- XL4015 no-load output: 5.14 V, CC trimpot maxed (clicker), CV pot
  reaches setpoint, indicator stays in CV mode.

The XL4015 was the first suspect (CC limit, clone module, transient
response), but tracing the rail showed two 1N4002s in series before
VSYS. Two silicon diodes drop ~1.6 V at the SD-inrush load, which
collapses VSYS to ~3.4 V — barely above the on-board RT6150B-33
buck-boost's working minimum (~1.8 V) and far below what the SD card
needs through inrush. USB power bypasses the diode chain entirely,
which is why the device works on USB.

### decision · swap 1N4002 → Schottky in next PCB revision

Next hardware revision replaces the input diodes with Schottky (e.g.
**SS14** SMA / **1N5817** DO-41 / **MBRS340** for ≥ 3 A headroom).
Forward drop falls from ~0.8 V to ~0.3 V per diode, restoring ~1 V of
headroom and keeping VSYS comfortably in the Pico's operating range
under SD inrush. Also evaluate whether the two-diode series is
genuinely needed (reverse-polarity protection only needs one); if
redundant, drop to a single Schottky.

Pair the swap with a **470 µF–1000 µF electrolytic + 100 nF ceramic**
at the Pico VSYS pin to absorb SD inrush — the buck's transient
response is poor for sudden 200 mA steps and the bulk cap is cheap
insurance regardless of diode choice. See linked entry in
[hw-test-log.md](../test/hw-test-log.md) for post-revision
verification steps.

### decision · interim workaround: raise buck output to ~6.0 V

Until the PCB revision lands, the XL4015 CV trimpot can be set to
**~6.0 V** (not higher) so that VSYS post-diode lands ~5.0 V under
typical idle and ≥ 4.4 V through SD inrush. Hard ceiling is **Pico
VSYS abs max = 5.5 V**; the diode drop is current-dependent (smaller
at idle than under load), so cranking the buck above 6.2 V risks
overshooting abs max when the system goes quiet.

Workaround is conditional on **only the Pico being downstream of
the diodes** — anything else on the post-diode rail (SHT31, OLED,
relay coil drive) would see 5.0+ V and may exceed its own abs-max.
Trace the rail before adjusting. Mark the buck physically so future
sessions don't crank it further by mistake.

## 2026-05-19 · Boot.log proves ENODEV on mount; classify and reformat

### issue · all 3 mount_sd attempts return ENODEV on the operator's card

Post-revert boot.log capture confirms the SD card has no readable FAT
filesystem: every `os.mount(sd, '/sd')` raises `OSError(19) / ENODEV`,
which on MicroPython's VfsFat means "no FAT signature on sector 0".
Three retries + the `is_mounted` fallback all return the same code, so
this is **not** a transient bus glitch — it's persistent filesystem
corruption. Most plausible cause: the prior [a4f3acc](a4f3acc) fix did
unfed-WDT mkdir writes immediately after mount; a watchdog reset
mid-write would have left the FAT table inconsistent. Recovery is
manual: reformat the card on a PC as FAT32, then reflash.

### decision · classify ENODEV in mount_sd and emit a recovery hint

`lib/sd_integration.py` now distinguishes two failure flavours when
`os.mount` returns ENODEV:

- `_probe_block_read(sd)` succeeds → card responds at the SPI block
  layer, filesystem is the problem → log "NO FILESYSTEM (reformat
  the SD card as FAT32)".
- `_probe_block_read(sd)` fails → card or bus is dead → log "raw
  block read also failed (SPI bus / card unresponsive)".

This is diagnostic-only; behavior (return `(False, None)`) is
unchanged. The operator who opens `/boot.log` after a reset loop now
sees which path to take (reformat the card vs. check wiring) instead
of just the raw errno.

## 2026-05-19 · Revert SD path-tree creation at mount

### issue · _ensure_sd_layout at mount caused detection regression

After [a4f3acc](a4f3acc) shipped, the operator reported the
require_sd_startup reset loop *even with `/sd/logs` already present*
on the card. Same Pico, same card that booted fine before the
commit. So the fix made detection worse, not better.

### deviation · revert the mount-time layout step

Reverted the `_ensure_sd_layout` / `_mkdir_p` helpers and their
three call sites in `_init_sd`. Tree creation at mount-time did
five synchronous SD writes with **no WDT feeding**, on a bus that
the chat-log already documents as flaky under sustained write
traffic ([10257d9](10257d9), [4692303](4692303)). The plausible
failure modes are (a) watchdog tripping mid-mkdir and leaving the
FAT inconsistent for the next mount, and (b) bus glitches turning
the post-mount writes into a destabilising salvo. Either way,
adding writes to the mount-success path is the wrong move.

### note · lazy parent creation already covers the original symptom

The original "missing /sd/logs causes reset loop" hypothesis is
not actually supported by the code: `BufferManager._ensure_parent_dir`
([lib/buffer_manager.py:302](../../lib/buffer_manager.py#L302)) and
`Updater._makedirs` ([lib/updater.py:68](../../lib/updater.py#L68))
both create parent dirs recursively on first write. EventLogger
and the updater therefore already tolerate a missing `/sd/logs`.
The real root cause of the original symptom is more likely the
SD bus stability work already in flight (verify retries, baud-rate
drop, R8 removal) — see [4692303](4692303) and prior entries.
Re-investigate from boot.log when the operator can capture it.

## 2026-05-19 · SD detection tolerant of missing /sd/logs and empty cards

### issue · fresh FAT-formatted card with no /sd/logs triggers reset loop

Operator reported the require_sd_startup failure state (sd_led +
error_led, reset after 10 s) on cards that mount cleanly but have no
`/sd/logs/` directory — i.e. freshly FAT-formatted with no files. The
mount itself succeeds; the cascade comes from downstream writers
hitting a missing parent and racing the boot-time SD health logic.

### decision · ensure DEVICE_CONFIG["paths"] tree at every successful mount

`HardwareFactory._init_sd()` now calls a new `_ensure_sd_layout()`
helper on each success path (host simulation, retry-loop mount,
is_mounted fallback). The helper mkdirs every entry from
`DEVICE_CONFIG["paths"]` that lives under the mount point — `logs`,
`sensors`, `ota/pending`, `ota/applied`, `diagnostics` by default — so
the first EventLogger / updater / sensor-logger write lands in a real
directory instead of falling through to fallback. Failures during
layout creation append to `self.errors` but do **not** flip
`sd_mounted` back to False; the card is mounted and writable at the
root, and the affected subtree degrades to fallback as before.

The layout list is derived from existing config (no new tunables) per
[configurability.md](../../.claude/rules/ecc/common/configurability.md);
the only new code is in `lib/hardware_factory.py`.

## 2026-05-19 · Verify retry-on-OSError to tolerate SD bus stalls

### issue · breadcrumb run pinpointed SD bus drop at lib/co2_logger.mpy

On-hardware run after [42c010c](42c010c) (breadcrumbs) and a manual
mpremote flash produced a definitive failure trail in `/boot.log`:
verify passed `main.py`, `config.mpy`, and the first five lib `.mpy`
files, then hit `hash_fail timeout waiting for response` on
`lib/co2_logger.mpy`. Every one of the 25 files after that point was
reported as `missing` — but they aren't actually missing. The SD bus
was wedged after the timeout, so every subsequent `os.stat()` raised
`OSError` and `_exists()` swallowed it as False, producing a
misleading 25-file "missing" cascade in the `verify_fail` detail.

Diagnosis: SD bus drops under sustained read traffic at 10 MHz SPI,
even after the R8 removal in [10257d9](10257d9). The updater logic
itself is correct; the bus is the bottleneck.

### decision · add `updater.verify_max_retries` / `verify_retry_delay_ms`

Mirror the existing `apply()` retry pattern in `verify_payload()`.
A transient `OSError` on `os.stat()` or `_hash_file()` now retries up
to `verify_max_retries` times with `verify_retry_delay_ms` sleep
between attempts, feeding the WDT in the gap. Semantic mismatches
(`size_mismatch`, `hash_mismatch`) return immediately — they aren't
bus glitches and retrying would just waste time + WDT budget.

Behavior change: the old "missing file: X" error string is now
"stat failed for X: `<oserror>`" because the retry boundary is OSError,
not the False return of `_exists()`. A genuinely missing file
surfaces as `stat_fail ENOENT …` instead of `missing`. Honest, and
distinguishes "ENOENT" from "bus timeout" via the included error
message.

### deviation · `_verify_one_with_retry` helper instead of inlining

verify_payload was already at ~50 lines and adding the retry loop
inline would have pushed it past the project's 50-line function
budget. Pulled the per-file stat/hash sequence into
`_verify_one_with_retry` returning either `None` (ok) or
`(breadcrumb_kind, detail)` so the caller stays simple.

### note · the new knobs are configurable per the configurability rule

Default values (`3` retries, `200 ms`) match the existing
`max_retries` / `retry_delay_ms` for apply. New keys plumbed through
`DEVICE_CONFIG`, `validate_config()`, and `tests/test_config.py` in
[c6200dd](c6200dd) as required.

## 2026-05-19 · SD-update verify/apply breadcrumbs

### issue · Pico's `start` line lands on SD, no follow-up line lands, fail jingle still plays

On-hardware test after the path-fix deploy produced TWO consecutive
`start ? payload detected` lines in `/sd/logs/updates.log` (canonical
path confirmed) with NO `verify_fail` / `apply_fail` follow-up,
despite the two-tone descending fail jingle playing each time. The
boot_log mirror added in [1b5baae](1b5baae) cannot help here yet
because the new updater is in the *payload on SD*; the Pico's flash
still runs the pre-mirror updater. Chicken-and-egg.

Concurrent observation in `/sd/logs/system.log`: the 14:42 boot enters
`SD status changed: FAILED` at 14:43:26 and stays in fallback for ~45
minutes, so the SD bus is dropping during sustained traffic even
after R8 removal. Most likely failure mode: `_hash_file` raises
`OSError` mid-verify, `verify_payload` records the error, but the
subsequent `updater.log("verify_fail", …)` SD append silently fails
because the same bus glitch is still in flight.

### decision · add per-file `[updater.crumb]` breadcrumbs to `/boot.log`

Added `_breadcrumb(message)` on `Updater` and wired it into every
verify branch (start, ok, missing, not_allowed, malformed_entry,
stat_fail, size_mismatch, hash_fail, hash_mismatch, done) plus apply
(start, per-file ok / fail, done). Writes go through
`lib.boot_log.write()` only — bypasses both SD and the regular
`Updater.log()` path, so the trail survives even when the SD-side
append is the thing that's silently broken. Operator can mount Pico
flash over USB MSC and read where verify died: filename + reason.

Independent from the existing `updates.log` mirror; both fire. The
breadcrumb is verbose-per-file, the mirror is the structured event.

### note · breadcrumbs only help once the new updater is on flash

The same chicken-and-egg applies. To get the new breadcrumb-emitting
updater live, flash via `flash-mpremote-nocheck` (bypasses SD update).
After that, re-trigger an SD update; `/boot.log` will then contain
`[updater.crumb] verify <path> <kind>` lines pinpointing the failure.

## 2026-05-19 · SD-update deploy path + updater log mirror

### issue · deploy task was writing to legacy /sd/update, hiding canonical layout from operators

`.vscode/tasks.json` `deploy-update-to-sdcard[-nocheck]` shipped with
`--copy-to G:/update` from the pre-2026-05-15 layout. Every deploy
landed in the legacy fallthrough path, so `/sd/logs/updates.log` always
opened with `payload detected at legacy /sd/update` even on fresh
builds. Repointed both tasks at `G:/ota/pending` (canonical).

### deviation · `tools/build_update_payload.py` now `mkdir -p`s the parent when SD root exists

Repointing exposed a second bug: the `--copy-to G:/ota/pending`
destination had no parent (`G:\ota`) on the SD card, so the deploy
crashed with `destination parent does not exist`. Loosened the
pre-check to verify only the drive **root** (`G:\`) — the SD-mounted
state — and `mkdir parents=True` for everything below it. Operators
no longer have to hand-create canonical subdirs on a freshly migrated
card.

### decision · mirror every `updater.log()` line into `/boot.log` on internal flash

A failing on-hardware update produced only the `start` line in
`/sd/logs/updates.log` — no `verify_fail` / `apply_fail` followed,
despite the fail jingle and red-status feedback playing. The leading
hypothesis is that the SD-side append silently failed after the first
write (best-effort log path in [updater.py:338](../../lib/updater.py#L338)).
The updater already mirrored to stdout for USB-serial debugging, but
that's invisible on a standalone Pico. Added a third sink: each
`Updater.log()` call now also writes through `lib.boot_log.write()`
into `/boot.log`. Reusing `boot_log` rather than introducing a new
flash log keeps the cap-controlled append path single-sourced and
costs no new config knobs. The success path (`apply_ok` → `machine.reset()`)
loses the entry on the next-boot truncation, which is fine; the failure
path preserves it because no reset fires.

## 2026-05-19 · R8 (MISO series resistor) identified as root cause of SD bit errors

### issue · earlier "40 MHz too aggressive" call was wrong — the resistor was the culprit

The same 2026-05-16/18 field run that produced 32× `SD status changed:
FAILED` over 42 h has been re-investigated on the bench. The cause was
not the 40 MHz SPI baudrate or the cabling — it was the series resistor
**R8** on the MISO line (GP12 ↔ SD_CON pin 3). R8 has been removed and
MISO is now a direct trace; SD mount and read/write have been stable
since.

### decision · keep `spi.baudrate` at 10 MHz for now, revisit on next bench run

The 10 MHz setting from earlier today is left in place as a precaution
until the next bench session confirms 40 MHz is reliable without R8.
Bandwidth is not the bottleneck (CSV rows are ~30 bytes), so the
downside of the conservative setting is zero; the upside of leaving
margin on the link is real until we have data. When the bench
confirms, bump `DEVICE_CONFIG["spi"]["baudrate"]` back to 40 MHz in a
separate commit.

### deviation · update earlier chat-log "drop default SPI baudrate" entry framing

The 2026-05-19 entry below ("drop default SPI baudrate from 40 MHz →
10 MHz") attributes the field failure to "40 MHz over the Pico SD_CON
path with series resistors R8/R10". That framing is now known to be
wrong: R10 (on MOSI) is fine; R8 (on MISO) was the failure mode. The
entry is left in place for history — read it together with this new
entry.

### note · PCB schematic and pin-map docs updated in the same turn

[config.py:30-40](../../config.py#L30-L40),
[config.py:92-108](../../config.py#L92-L108), and
[docs/notes/2026-05-14-pcb-codebase-gap-plan.md:33](2026-05-14-pcb-codebase-gap-plan.md#L33)
all dropped the "via R8" notation on MISO. The schematic JSON under
[docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json](../SCH_Pico-Greenhouse-PCB_2026-05-14.json)
is the original board design and is intentionally **not** rewritten —
it stays as the as-designed reference; the bypass is captured in the
PCB-revision changelog instead.

## 2026-05-19 · SD reliability + watchdog resilience pass

### issue · Pico restarted ~86× in 42 h with no exceptions in the log

The shipped `sd/logs/system.log` (1491 lines, 2026-05-16 23:30 →
2026-05-18 16:38) contained 86 `System startup` lines but zero
`[ERR]` / traceback / exception markers. Many restart clusters
were tight (1–3 min apart). Watchdog timeout was 8000 ms; the
trips were silent — no console message, just an immediate reboot.

### decision · bound `migrate_fallback()` per call and feed WDT between rows

Root cause of the silent resets was identified as
`BufferManager.migrate_fallback()` running synchronously inside the
60 s health loop with no row cap and no WDT feed. A backlog of
30+ rows on a slow SD takes longer than 8 s of synchronous SPI
work, which is the exact failure mode that resets the Pico without
logging anything.

`migrate_fallback()` now drains at most
`system.fallback_migrate_batch_max` rows per call (default 20),
feeds the watchdog between every row, and rewrites the fallback
file with the remainder so chronological order is preserved across
the multi-pass drain. The health-check loop fires it once per
cycle, so a 100-row backlog drains in ~5 health cycles instead of
one watchdog-tripping pass.

### decision · drain fallback at boot instead of wiping it

`buffer_manager.clear_fallback_startup()` was called unconditionally
in `main()` at boot, wiping the fallback CSV. That is what caused
the "truncated startup" log pattern (only `System startup`,
`CO2 override wired`, `OLED display initialized`, `Growlight ON`
surviving): log entries that hadn't flushed to primary before the
prior reset went to fallback, then got wiped on the next boot.

`main()` now calls `migrate_fallback()` up to twice at boot when SD
is mounted, preserving the prior boot's data and emitting
`[STARTUP] Drained N fallback row(s) from previous boot`. The bound
on the loop keeps init time predictable; the health loop drains
any remainder.

### decision · feed WDT inside `WriteQueueManager._drain_batch` and `sd_integration.is_mounted` recovery

Two more synchronous SD paths were unprotected: the write-queue
drain (up to 5 SPI writes per cycle) and the MBR-read-fail recovery
inside `is_mounted` (umount + SPI deinit + sleep_ms(200) + reinit +
re-read). Both now accept a `wdt_feed` callable injected from
`main.feed_wdt` and call it between each blocking step. Exceptions
from the callback are swallowed so a misbehaving WDT driver can
never abort the recovery path.

### decision · drop default SPI baudrate from 40 MHz → 10 MHz

40 MHz over the Pico SD_CON path with series resistors R8/R10 was
too aggressive for the field cabling — the 32× `SD status changed:
FAILED` over 42 h indicates SPI bit errors, not yanked cards.
10 MHz is the field-tested setting; bandwidth is not the bottleneck
(CSV rows are ~30 bytes), so this is a pure reliability win.

### decision · log `machine.reset_cause()` on every boot

`[MAIN] System startup` lines now end with the named reset cause
(`PWRON_RESET`, `WDT_RESET`, `BROWNOUT_RESET`, …). When the next
silent-reset bug shows up, the operator can tell at a glance
whether it was the watchdog, a brown-out, a soft reset from the
updater, or the user pressing RES_BTN. Mapping is best-effort:
unknown codes fall through to `code=N`; failures (older firmware
that lacks `reset_cause`) fall back to `unknown` without blocking
boot. Host shim exposes the same constants so tests stay valid.

### issue · CO2 sensor reading constant 10000 ppm on 2026-05-18

`sd/sensors/co2/2026/co2_2026-05-18.csv` has all 1696 rows pinned
at 10000 ppm, which keeps the CO2 override permanently ON and the
exhaust fan running non-stop. This is sensor-side (likely
calibration, ABC drift, or a UART framing issue) — not a software
bug — but it's contributing to the I/O / power load that the rest
of this session is trying to stabilise. **Flagged for bench
verification, not auto-fixed.** Operator should run
`prototypes/co2_test.py` (or similar) with a known-clean room and
compare against the sensor datasheet's ABC window.

### note · log timestamps go backwards in the wild

[sd/logs/system.log:230-239](../../sd/logs/system.log#L230-L239)
contains a row stamped `16:18:29` after rows stamped `16:23:23`,
because `migrate_fallback()` re-injects old rows into the primary
log after newer rows have already been written. The bounded-batch
migration doesn't fully solve this — it just makes the windows
smaller. A proper fix would teach `EventLogger` to write fallback
rows under a separate `*.replay.log` file at migration time. Left
as a follow-up; current session's priority was stopping the silent
resets.

## 2026-05-17 · OLED SYSTEM screen surfaces build version

### decision · combine date+time on row 0 to free a slot for `Ver:<hash>` on row 1

`_render_system()` previously used 5 rows for date / time / uptime /
buf / RAM, leaving no room for build identity. Row 0 now collapses
into a 16-char `YYYY-MM-DD HH:MM` (slicing `now_timestamp()[:16]`,
which fits the 16-char row truncation exactly), and row 1 becomes
`Ver:<7-char git short hash>` — e.g. `Ver:c195be2` (11 chars). No
existing field is dropped. Uptime / buf / RAM keep their rows 2–4.

### decision · stamp `lib/build_info.py` from the payload builder, fall back to `Ver:dev`

`tools/build_update_payload.py` now writes `lib/build_info.py`
(VERSION = git short hash, BUILD_TIME = full ISO timestamp) into
the working tree before collecting sources, so the raw-mode payload
picks it up automatically, Thonny-direct flashes also get a stamped
file, and `--compiled` mode additionally drops the same file into
`<out>/lib/` with a manifest entry (since the compiled collector only
takes `.mpy`). The file is gitignored. `lib/oled_display.py` does a
guarded `from lib.build_info import VERSION` with two fallbacks (`from
build_info import …` for on-device sys.path quirks, then literal
`"dev"`), so unbuilt working trees and host runs read `Ver:dev`. No
new `DEVICE_CONFIG` entries — build identity is build-time metadata,
not operator-tunable behavior.

## 2026-05-17 · Updater short-circuits when payload already on flash

### issue · same-version SD update failed with only "start" line and failure jingle

Operator boots Pico with payload at `/sd/update/` whose contents
already match what's on flash (e.g. Pico just flashed via
`flash-mpremote`, SD payload built from same git commit via
`deploy-update-to-sdcard`). Symptom: failure jingle plays,
`/sd/logs/updates.log` contains only the `start` line — no
`verify_fail` / `apply_fail` entry — and `/sd/update/` is still in
place. Root cause not fully pinned on host (host repro succeeds);
hypothesis is a MicroPython-side write-during-overwrite quirk when
apply rewrites `/lib/updater.mpy` or another in-use module, with
the subsequent `log()` call also silently failing, masking the
real error.

### decision · add `Updater.is_already_applied(manifest)` short-circuit before apply

After `verify_payload` passes, `run_pending_update` now hashes
every manifest file at `_FLASH_ROOT` and compares to the manifest
entry. If all hashes match, the apply step is skipped entirely,
`finalize()` still runs (so the trigger is consumed and the
payload is renamed under `applied/<version>/`), a new `noop`
log line is written, and a distinct `already_applied` jingle
plays. **No `machine.reset()`** — the live code is unchanged, so
boot just continues. Eliminates the failure jingle on
idempotent payloads and avoids unnecessary flash writes.

### decision · `Updater.log()` mirrors every entry to stdout

The bare `except Exception: pass` in `log()` previously hid the
real failure when the SD-side append broke (the exact bug the
operator just hit). `log()` now `print("[updater]", line)`s
before the file write so the verify_fail / apply_fail message is
visible over USB serial even when the SD log is unwritable. Print
is itself try-wrapped — logging stays best-effort.

### decision · new `updater_feedback.noop_pattern` + `UpdateFeedback.already_applied()`

Two-blip 880 Hz pattern (`[(880, 80, 60), (880, 80, 0)]`),
distinct from success (3-note rising) and failure (2-note
descending). LED row shows every other LED lit while the chime
plays so the operator can distinguish "no-op apply" from "real
apply" at a glance without listening. Wired through
`build_from_config` like the existing patterns; new validator
entry in `config.py` rejects an empty `noop_pattern`.

## 2026-05-16 · Fan-control pre-PCB refactor (FanOutput + fans dict + new policies)

### decision · land all six pre-hardware build steps in one session as a clean six-commit series

User said "implement everything that can be implemented before making
physical changes to the hardware". Steps 1-6 from
[[project_fan_hardware_revision]] all run on the current relay PCB
because the relay path stays live until the PCA9685 PCB lands. Each
step shipped as its own logical commit per
[.claude/rules/ecc/common/commit-granularity.md](../../.claude/rules/ecc/common/commit-granularity.md);
tests stay green at every commit (901 -> 989). Step 7 (flipping the
per-fan output from relay to PCA9685) is the only remaining item and
needs the new PCB.

### decision · FanController composes a FanOutput instead of inheriting RelayController

`FanController` no longer extends `RelayController`. It takes an
`output: FanOutput` argument and routes `turn_on()`/`turn_off()`
through `output.on()`/`output.off()`. `RelayFanOutput` wraps a
`RelayController` (binary), `Pca9685FanOutput` wraps a PCA9685 PWM
channel (variable). Policy code stays identical; the next-rev PCB
swap is one-line per-fan wiring in `main.py`. `.pin` exposed as a
backward-compat property for tests and OLED diagnostics.

### decision · fans dict ships all 5 roles up front, disabled-by-default for the three not yet wired

`DEVICE_CONFIG["fan_1"]` / `["fan_2"]` are gone. The new
`DEVICE_CONFIG["fans"]` dict keys by role: `exhaust`,
`growroom_walls`, `growroom_center`, `heater_distribution`, `case`.
The first two stay relay-backed and enabled today. The three
PCA9685-backed roles ship with `enabled: false` so the validator
can keep them honest and `main.py` skips them at construct time.
When the chip lands: flip `pca9685.enabled` and the three fan
`enabled` flags; no code change needed. Chosen over "migrate only
existing 2 fans now" because it makes the eventual hardware
turn-on a config-only change.

### decision · validator dispatches on mode + output rather than one-size-fits-all required-keys

`_validate_fans()` runs after the bulk required-keys pass. It
enforces: enabled bool, mode in {thermostat_schedule, always_on,
heater_follower}, output in {relay, pca9685}, no duplicate relay
pins, no duplicate PCA9685 channels, plus the per-mode required
tunables. Keeps the validator strict without coupling to one fan
shape; matches the `growlight.mode` dispatch pattern already in the
codebase.

### decision · co2_logger.override_fan switches from "fan_2" -> "exhaust", validated against fans dict keys

The CO2 override target is now a role name resolved by `main.py`
walking the constructed `fans` list looking for matching `.name`.
Validator rejects any value not present as a key in the `fans`
dict, regardless of `enabled`. Exhaust is the natural CO2 vent
target - keeping the override pointed at the highest-airflow role
survives future re-tuning of the other fans.

### decision · AlwaysOnFanController re-asserts duty every refresh_interval_s as cheap insurance

Constructor calls `output.set_duty(duty_pct)` once. `start_cycle()`
sleeps for `refresh_interval_s` (configurable, default 300 s in the
`case` entry) and re-issues the same `set_duty`. PCA9685 registers
are persistent across normal operation but I2C bus glitches happen
in long runs - a re-assert every 5 minutes is cheap and means a
hung-fan investigation has one fewer suspect. `refresh_interval_s`
is a per-fan tunable per [.claude/rules/ecc/common/configurability.md](../../.claude/rules/ecc/common/configurability.md).

### decision · HeaterFollowerFanController tracks afterrun in a per-tick countdown

Heater on -> fan on + afterrun budget set to `post_run_s`. Heater
off with budget > 0 -> fan stays on, budget decrements by
`poll_interval_s` per tick. Heater on again -> budget resets to
full. Budget reaches 0 -> fan off. Simple integer countdown rather
than monotonic-time deadline because MicroPython `time.ticks_ms()`
semantics differ across host and Pico - counting ticks is
platform-neutral and matches the existing thermostat pattern in
`FanController`.

### decision · move HeaterController construction before the fan loop in main.py

`HeaterFollowerFanController` takes the heater instance as a
constructor arg (no late wiring). The heater was constructed at
step 7b2 (after the fans loop); moved to step 6b (before the fans
loop) so the heater_follower dispatch in the loop has the reference
available. Heater depends only on time_provider/th_logger/logger
which already exist by step 6, so the move is safe.

### note · per-fan PWM proportional mode deferred

The clarifying question on whether `thermostat_schedule` should
grow a true variable-speed PWM mode was answered "binary via
`set_duty(0)/set_duty(default)` for now, revisit later". Implemented
as binary: thermostat_schedule fans call `output.set_duty(default)`
when on and `output.set_duty(0)` when off. Adding a proportional
mode later is additive - new `mode: "thermostat_proportional"`
value with its own controller class, no breaking changes to the
existing mode.

## 2026-05-16 · OLED debug actions sub-menu

### decision · separate "debug" entry menu, long-press opens sub-menu, short=cycle, long=execute

Added a tenth top-level OLED menu (`debug`) instead of overloading an
existing one. From the entry view, a long press flips the display
into a sub-menu mode where short-press cycles actions and long-press
executes the highlighted one. This keeps every other menu's
long-press semantics (clear history, reset reminder, remount SD)
untouched — an operator cannot accidentally trigger a destructive
action by holding the button on the wrong screen.

Shipped actions: `wipe_logs`, `cycle_relays`, `test_heater` (5 s),
`test_growlight` (relay pulse), `test_growlight_dim` (DAC sweep, only
listed when MCP4725 is wired). Per-fan PWM is intentionally **out**
until the PCA9685 revision lands; see
[[project_fan_hardware_revision]] for the planned hardware that
makes per-fan duty meaningful.

### decision · wipe_logs needs two-step confirm; scope = buffers + fallback + system.log

`wipe_logs` is the only destructive action. First long-press arms a
`CONFIRM?` prompt; second long-press inside `confirm_timeout_s`
(default 8 s) wipes. A short press cancels. Wipe scope is
deliberately narrow: BufferManager in-memory ring buffer, fallback
CSV (via `clear_fallback_startup`), and the EventLogger file. Sensor
CSVs under `/sd/sensors/**` are **never** removed — those are
scientific data, and an operator who needs a full reset can format
the card.

### decision · debug actions spawn async tasks; OLED stays event-loop friendly

`long_press_action()` runs from the button-poll task. Multi-second
actions (heater 5 s, dim sweep, cycle relays) would block the WDT
feeder if executed inline, so each handler is a coroutine and the
dispatcher schedules it with `asyncio.create_task()`. While an
action runs, `_debug_running=True` suppresses further button input
and the OLED shows `RUNNING...`. On completion, a `done`/`FAIL`
status line stays on screen for `status_show_ms` (3 s) and the
reminder LED plays a brief feedback blink so the operator gets
confirmation even at arm's length.

### note · per-fan PWM 0-100% deferred to PCA9685 revision

The user asked about individually testable fan PWM, but on the
current PCB fans are bare on/off relays — duty cycle isn't a
meaningful concept. The cycle_relays test pulses each fan ON for
~1 s in sequence so an operator can hear the relay click and confirm
wiring. Per-fan dim sweeps will be added in the same change that
introduces `AlwaysOnFanController` /
`HeaterFollowerFanController` on top of the PCA9685.

## 2026-05-16 · Fan control policies for PCA9685 hardware revision

### decision · case fan = always-on constant duty; heater-distribution fan = follows heater + afterrun

The next hardware revision (IRLZ44N MOSFETs on a PCA9685 PWM driver,
replacing the current 2-relay fan path) expands the fan roster to
five: exhaust, growroom_walls, growroom_center, heater_distribution,
case. Three of these inherit the existing schedule + SHT31
thermostat behavior of the current `FanController`. The two new
roles get their own control policies:

- **Case fan** runs at a constant, configurable PWM duty cycle
  whenever the system is up. No thermostat, no schedule — its job
  is steady airflow over the electronics. Implemented as a thin
  `AlwaysOnFanController` that calls `output.set_duty(duty_pct)`
  once at startup. RP2040 internal temp sensing is intentionally
  deferred until there's measured evidence the constant-duty
  approach is wrong.
- **Heater distribution fan** runs whenever the heater MOSFET is
  on, plus a configurable post-run / afterrun window so residual
  heat in the element gets purged into the room instead of
  back-soaking the device. Implemented as a new
  `HeaterFollowerFanController` that polls
  `HeaterController.is_on()` and tracks an afterrun timer.
  Polling (rather than callbacks on `HeaterController`) keeps the
  coupling to the existing codebase's polling idiom; up to one
  poll interval of lag is fine for airflow.

The cross-cutting seam for the whole revision is a `FanOutput`
abstraction (`RelayFanOutput` today, `Pca9685FanOutput` post-PCB)
so policy classes don't know whether they're driving a relay or a
PWM channel. Build steps 1–4 (output abstraction, PCA9685 driver,
config migration to a role-keyed `fans` dict with per-mode
validator dispatch) are valuable before the hardware revision;
steps 5–6 add the two new controller classes; step 7 is the
one-line per-fan wiring flip when the new PCB lands.

### note · grow-room fan variable-speed mode left open

Whether the three `thermostat_schedule` grow-room fans should grow
a true variable-speed PWM mode (duty proportional to temperature
delta above setpoint) — or stay binary on/off through
`set_duty(0)` / `set_duty(default_duty_pct)` — is not yet decided.
Worth a clarifying round when the config migration (build step 4)
lands, since that's when the per-fan duty schema crystallizes.

## 2026-05-16 · .gitignore refactor

### decision · trimmed 676-line .gitignore to ~80 lines of project-relevant rules

The old `.gitignore` was a stacked dump of GitHub templates: full
Visual Studio / .NET, Django, Flask, Scrapy, RabbitMQ, ActiveMQ,
Marimo, Streamlit, VS6, etc. — none of which apply to a MicroPython
Pi Pico project. Rewrote it to keep only: OS/editor noise (incl.
useful bits cherry-picked from a Flutter reference gitignore —
`Thumbs.db`, `Desktop.ini`, `*.swp`, `.idea/`), Python essentials
(bytecode, venv, test/lint caches), MicroPython `*.mpy`, Claude
tooling, and Pi Greenhouse runtime artifacts (`sd/`, `*.csv`,
`*.log`, `hw_probe_result.*`, `typings/`, `service_reminder.txt`,
`.main_original.py`).

### decision · .vscode/ allow-list expanded to all workspace-relative files

Audited every file in `.vscode/` for absolute-path leakage before
allow-listing. All current files use `${workspaceFolder}`, `~/`, or
`$env:` only — no `C:\Users\...` paths. So the allow-list now
covers `extensions.json`, `launch.json`, `settings.json`,
`tasks.json`, `Git-codebase.code-workspace`, `micropico-port.ps1`,
and `*.code-snippets`. Re-audit before allow-listing any new
`.vscode/` file.

### issue · `.github/workflows/ci.yml` was hidden by an accidental `.github/` ignore

The old gitignore had `.github/` as a blanket ignore, which silently
suppressed `.github/workflows/ci.yml`. `.github/copilot-instructions.md`
was already tracked despite the ignore. Dropping the `.github/` rule
in this refactor exposes `ci.yml` as untracked. Decide whether to add
it to git — it's not part of the gitignore refactor commit.

## 2026-05-16 · Updater legacy update_dir fallback

### decision · `updater.legacy_update_dirs` keeps pre-2026-05-15 payloads applicable

After the SD layout refactor moved `/sd/update` → `/sd/ota/pending`
([c1f4c07](c1f4c07)), a field Pico booted normally instead of
applying a payload that had been copied to the old `/sd/update`
location. `lib/updater.py` `has_pending_update()` only checks the
canonical `update_dir`, so the legacy path was invisible.

Added a new config key `updater.legacy_update_dirs` (default
`["/sd/update"]`) and a fallback in `run_pending_update()`: if the
canonical `update_dir` has no `manifest.json`, the boot hook walks
the legacy list in order and uses the first one that does. The
matched directory is fed straight into `Updater`, so `finalize()`
still renames it into the **canonical** `applied_dir`
(`/sd/ota/applied/<version>/`) — legacy payloads end up in the new
applied tree on success, so the legacy path self-clears.

The start-log line is annotated `payload detected at legacy <path>`
when the fallback fires, to make it obvious in `/sd/logs/updates.log`
which path was consumed. Operators clear the fallback by setting
`legacy_update_dirs: []` once all field cards are migrated.

### note · canonical wins when both paths have a manifest

If someone builds a payload at the new path AND leaves an old one at
`/sd/update`, the canonical `update_dir` always wins. The legacy
directory is only consulted when the canonical has no manifest, so a
fresh build is never silently overridden by stale legacy data.

### note · `tools/build_update_payload.py` examples now show `G:/ota/pending`

Docstring examples were still showing `--copy-to G:/update`, which is
how the legacy payload got onto the card in the first place. Updated
all five example lines so future copies land at the canonical path.

## 2026-05-15 · Boot SD diagnostics tee'd to /boot.log

### decision · mirror HardwareFactory pre-EventLogger output to flash file

Standalone Pico has no USB serial reader attached, so the diagnostic
prints that explain *why* the boot SD mount failed
(`[HardwareFactory] SD mount attempt N/M...`, the `mount_sd` error
line, the `is_mounted fallback` step) were invisible when the system
entered the `require_sd_startup` reset loop. New
[lib/boot_log.py](../../lib/boot_log.py) tees those lines into a file
on internal flash so the operator can read them over USB MSC after
power-cycling out of the loop.

Defaults: `/boot.log`, 10 KB cap, truncated on the first write per
process so each boot starts fresh. `boot_log_path` and
`boot_log_max_kb` live in `DEVICE_CONFIG["system"]` with the usual
validator+test plumbing. `main.py` calls `boot_log.configure()`
immediately after `validate_config()` so HardwareFactory's first
`_debug` / explicit `boot_log.log` calls land in the configured
file.

### note · boot_log only routes when no EventLogger is wired

`HardwareFactory._debug` falls through to `boot_log.log` only when
neither a logger nor a debug_callback is attached — i.e. during
boot, before `EventLogger` is constructed. Once the logger is wired,
every debug call goes there and the boot log stops growing. This
keeps the helper scoped to the diagnostic gap it was created for and
avoids overlap with `system.log` rotation.

## 2026-05-15 · Cold-boot SD mount — timing + is_mounted fallback

### issue · SPI reinit alone did not unblock cold-boot mount

After landing the SPI-reinit-between-retries fix and the
`require_sd_startup` hard-fail wiring, on-hardware test still showed
boot mount failing — the new sd_led+error_led countdown was firing
correctly and the Pico kept cycling. Manual menu remount continued to
work. That ruled out SPI bus state as the dominant cause and pointed
at total elapsed time: by the time the operator can press the menu
button, the card has had many seconds to settle; at boot, the retry
loop gave it ~1.75 s before declaring failure.

### decision · longer cold-boot waits + is_mounted as final fallback

`_init_sd` now:

- feeds the injected WDT inside the retry loop so longer waits don't
  trip the watchdog (HardwareFactory now takes a `wdt=` constructor
  arg, wired from `main.py`),
- `_safe_umount()`s the mount point between attempts to clear any
  half-mounted node a previous attempt left behind,
- after all `mount_sd` attempts fail, runs one more pass via
  `lib.sd_integration.is_mounted(None, None, return_instances=True)`
  — the exact code path the menu remount uses, which builds a fresh
  SPI/SDCard pair and has its own MBR-read retry,
- prints `[HardwareFactory] SD mount attempt N/M...` and the
  fallback line so the operator can capture the failing step from
  the USB console.

Config defaults bumped: `system.sd_power_up_ms` 250 → 1500 and
`system.sd_retry_delay_ms` 500 → 1000. Total cold-boot budget is
now ~5.5 s, still well under the 8 s WDT (which is fed mid-loop).

### note · why "just call is_mounted" works

`is_mounted(sd=None, spi=None)` builds a brand-new SPI bus inside
its own `_init_sd_local` helper, attempts `os.mount`, falls back to
a `umount → deinit → sleep 200 ms → re-init → re-read MBR`
sequence on MBR-read failure, and only returns True after the MBR
has actually been read. That second-chance MBR retry is the bit the
`mount_sd` retry loop doesn't have. Folding it in as the boot
path's final attempt closes that gap without having to duplicate
the recovery code into `mount_sd` itself.

## 2026-05-15 · Boot SD mount recovery + hard-fail

### issue · SD failed to mount on cold boot but worked from menu remount

User reported that since the SD layout refactor landed, the card no
longer mounts at boot — yet a long-press menu remount succeeded every
time. Investigation found three problems compounding rather than one
clean regression:

1. `HardwareFactory._init_sd` reused the same `self.spi` across its
   three retries. A failed `sdcard.SDCard(spi, cs)` call can leave the
   SPI bus in a half-init state that every subsequent retry on the
   same bus inherits, so the loop never recovered. `is_mounted()`
   (the menu remount path) builds a fresh `SPI()` each call, which is
   why manual remount worked.
2. `StatusManager.run_post()` drives every owned LED OFF at the end
   of the walk. `main.py` called `set_sd_status()` *before* POST, so
   even when boot mount failed the visual walk masked the LED.
3. `system.require_sd_startup` existed in config but was never read
   anywhere — there was no path that turned SD failure into a hard
   stop.

### decision · cold-boot SD mount reinits SPI between retries

`_init_sd` now calls a new `_reinit_spi()` helper between attempts,
which `deinit()`s the existing bus (best-effort) and rebuilds it via
`_init_spi()`. Matches the implicit fresh-bus behavior of
`is_mounted()` on the menu path. Retry count and delay are unchanged
(3 × 500 ms with a 250 ms power-up); the bus reinit is the change
that makes retries meaningful rather than free.

### decision · require_sd_startup now defaults True, drives hard-fail

`system.require_sd_startup` defaults to `True` and is consumed in
`main.py` right after `status_manager.set_sd_status()`. On failure
the new helper `_enter_sd_failure_state()` lights sd_led + error_led,
feeds the WDT in 0.5 s ticks for `system.sd_fail_reset_s` seconds
(default 10), then calls `machine.reset()`. The visible countdown
gives the operator a chance to see *why* the Pico cycled, which is
the key difference from a watchdog-induced reset. Cold-boot SD
failures are usually transient (connector seating, brown-out, slow
card), so a bounded reset loop tends to recover on its own.

### note · POST now reasserts SD state after the walk

After `run_post()` returns, `main.py` re-calls
`status_manager.set_sd_status(hardware.is_sd_mounted())` so the SD
LED reflects reality once the walk is over. Currently only SD state
gets this treatment because it is the only condition raised before
POST; warnings/errors raised later are unaffected.

### deviation · no compatibility shim for the old behavior

Per `coding-style.md` and the user's prior preference, no flag was
added to preserve the old "boot continues silently on SD failure"
default. Operators who want that path set
`system.require_sd_startup=False` explicitly — that branch is still
wired and tested.

## 2026-05-15 · SD card layout refactor

### decision · sensor-first tree under `/sd/sensors/<type>/YYYY/`

Reshaped the SD root from a flat dump of CSVs and logs into a typed
hierarchy so adding a new sensor type only needs a config row, not
new path code. Layout:

- `/sd/sensors/<type>/YYYY/<type>_YYYY-MM-DD.csv` — daily-rotated
  CSVs, kept forever (no auto-pruner — operator clears manually).
  All paths flow through [lib/sensor_paths.py](../../lib/sensor_paths.py)
  `daily_csv_path()`.
- `/sd/logs/system.log` — EventLogger, existing size-based rotation
  (`event_logger.max_size`).
- `/sd/logs/updates.log` — Updater log, **new** size-based rotation
  via `updater.log_max_size` (default 50 KB → renames to
  `updates_<ts>.log`).
- `/sd/ota/{pending,applied}` — OTA payload staging (was `/sd/update`
  and `/sd/applied`).
- `/sd/diagnostics/hw_probe_*.json` — hw_probe output.

Layout roots live in `DEVICE_CONFIG["paths"]`; the validator enforces
that every entry is absolute and lives under `spi.mount_point`.

### deviation · no boot-time migration of legacy root files

Per operator preference, files left at `/sd/*.csv`, `/sd/system.log`,
`/sd/updates.log`, `/sd/update/`, `/sd/applied/`, and
`/sd/hw_probe_*.json` are **not** moved by the Pico. New writes go
straight to the new tree; the old files coexist until the operator
decides what to do. Skipping migration removes a class of boot-time
failures and keeps the apply path simple — the cost is that
historical data must be merged manually if you want one continuous
timeline.

### note · BufferManager now auto-creates parent dirs

`BufferManager.write` / `_flush_inner` / `_migrate_fallback_inner`
call a new `_ensure_parent_dir()` before each `open(..., "a")`.
Required because nested relpaths like
`sensors/co2/2026/co2_2026-05-15.csv` would otherwise fail with
`OSError(ENOENT)` on the year subdir. MicroPython build uses a
recursive `os.mkdir` walk (no `os.makedirs` available); host CPython
uses `os.makedirs(..., exist_ok=True)`.

### note · sensor logger constructors took a clean break

Dropped the `filename_base` / `filename` constructor args on
CO2Logger, SoilLogger, TempHumidityLogger and replaced them with
`sensor_root` + `sensor_type`. Config keys followed
(`co2_logger.filename_base` → `co2_logger.sensor_type`, same for
soil and a new `temp_humidity_logger.sensor_type`). Per coding-style
guidance, no backward-compat shim was kept.

## 2026-05-15 · Plant/mushroom operating mode

### decision · single top-level `mode` key drives optional component wiring

Added `DEVICE_CONFIG["mode"]` with two values: `"plant"` enables the
MCP4725-dimmed grow light path and constructs the soil-moisture
logger on GP28; `"mushroom"` runs the relay-only grow light and
skips `SoilLogger` entirely (no task, no ADC init). The mode is
validated at boot and is the sole switch — operators flip one key
and reboot. Default is `"mushroom"` per user preference.

### deviation · `growlight.mode` is no longer consulted at runtime

The previous `growlight.mode` key (`"dimmed"` vs `"relay_only"`) is
shadowed by the new top-level `mode`: plant ⇒ dimmed, mushroom ⇒
relay-only. The growlight.mode field still validates so existing
configs don't fail, but `main.py` derives the wiring purely from the
top-level mode. Kept the field rather than deleting it to avoid
churning every test fixture; future cleanup can remove it.

### note · disabled components are not constructed at all

Per user direction the disabled-in-mushroom path is "skip
construction" rather than "construct then idle". This keeps RAM
free on the Pico and means a mushroom-mode boot leaves GP28 as a
plain GPIO and skips MCP4725 I2C probing — both visible in the
startup log lines.

## 2026-05-15 · Relay diagnostic tool added

### issue · relays behave randomly across restarts — needs bench probe

User reports the 8-channel relay board behaves erratically, especially
after a reset. Added [tools/relay_diag.py](../../tools/relay_diag.py)
as a standalone MicroPython script that bypasses `lib/relay.py`,
config, and DI. It probes each of the 7 wired relay GPIOs in input
mode first (to capture float-state at boot — the most likely cause
of "clicks on at restart" with an active-low module), then drives
each HIGH, sweeps one at a time, runs an all-on stress, and leaves
everything off. Eyes-on checklist filed in
[docs/test/hw-test-log.md](../test/hw-test-log.md). The 8th relay
channel on REL_CON is intentionally unwired on this PCB — only 7
GPIO control lines exist (REL_CON pins 2-8).

### note · diag-script dwell/gap timings stay inline, not in DEVICE_CONFIG

`DWELL_S`, `GAP_S`, `STRESS_S` in the diag script are named constants
at the top of the file rather than `DEVICE_CONFIG` entries, because
this tool is a one-off bench utility run standalone via Thonny —
the [configurability.md](../../.claude/rules/ecc/common/configurability.md)
rule targets the runtime path, not tooling. Adjust by editing the
script.

### finding · relay-diag bench run — runtime path clean, boot transient is the cause

Bench run of `tools/relay_diag.py` (2026-05-15) confirmed three
distinct symptoms and split them by root cause:

1. **GP27 floats LOW persistently** (raw=0 in Phase 1) — explains
   `reserved_4` (REL_CON 8) clicking on at every reset.
2. **GP26 latches transiently during 3V3_EN reset** — Phase 1 reports
   raw=1 because by the time MicroPython probes, the line has
   drifted back HIGH. The relay still fires because the boot-window
   dip is long enough to latch the coil.
3. **REPL idle dim-LED on all 7 channels** — canonical floating-input
   signature; the GPIOs are high-Z whenever MicroPython hasn't taken
   ownership.

Phases 2–5 (Pico actively driving the pins) all passed: single
clicks per channel, no neighbour activity, no brownout under
simultaneous all-on stress. **The firmware path is healthy; the
problem is exclusively pre-MicroPython and REPL-idle, both of which
are windows the firmware cannot reach.** Full notes recorded in the
hw-test-log entry for the same date.

### decision · fix is hardware-only — track in dedicated PCB-revision doc

Software can't close the reset transient (the window between 3V3_EN
release and `Pin(gp, Pin.OUT, value=1)` executing) — by then the
relay has already latched. The correct fix is an external 10 kΩ
pull-up from each REL_CON IN line to the relay module's VCC rail.
That holds the line HIGH even with the Pico unpowered or in REPL
idle.

Created [pcb-revision-changes.md](pcb-revision-changes.md) as the
rolling source of truth for changes that require a PCB spin
(separate from [2026-05-14-pcb-codebase-gap-plan.md](2026-05-14-pcb-codebase-gap-plan.md),
which covers firmware gaps against the *current* board). Filed two
entries: (a) pull-ups on REL_CON pins 2–8, (b) decision on the
unwired 8th channel (pull-up vs. wire to spare GPIO — needs DMM
check of the existing 3V3 strap first).

## 2026-05-15 · Capacitive soil sensor unresponsive — NE555 unit, replace

### decision · require TLC555/7555-class chip; this unit was dead

Operator reported the soil sensor on GP28 returning random low values
that didn't move when the probe was submerged in water and only
"changed on restart". Bench-trace:

1. Initial wiring had sensor VCC tied to ADC_VREF (Pico pin 35) instead
   of 3V3 (pin 36). ADC_VREF is an RC-filtered reference, not a power
   rail; loading it with the sensor's ~5 mA draw dragged the reference
   itself, corrupting every ADC read on the Pico. Rewired VCC to 3V3.
2. After rewire, `print_raw()` returned 0–14 and AOUT-to-GND sat at
   ~0.3 V. Chip on the sensor PCB confirmed as **NE555** (bipolar,
   ≥4.5 V to oscillate), not TLC555 / 7555 / LMC555 (CMOS, run at 2 V).
   3.3 V is below the NE555's start threshold, so the oscillator never
   ran and AOUT floated.
3. Moved VCC to VBUS (Pico pin 40, measured 4.7 V) and added a 6.8 kΩ
   top + 10 kΩ bottom divider on AOUT → GP28 (ratio 0.595; worst-case
   5 V → 2.98 V at GP28, safely under the 3.3 V ADC ceiling, source
   impedance ~4 kΩ within the RP2040's recommended <10 kΩ window).
4. AOUT-to-GND still read 0 V at the sensor header even with the
   divider lifted (one resistor leg disconnected to rule out loading).
   The NE555 is dead — likely a damaged passive on the oscillator or
   the chip itself. 0.2 V residual is leakage, not a real signal.

Decision: replace with a TLC555-class capacitive sensor (DFRobot
SEN0193, Adafruit #4026, or any board where the seller confirms the
timer chip is CMOS — TLC555 / 7555 / ICM7555 / LMC555). With a
TLC555 unit the wiring reverts to VCC → 3V3 (pin 36), GND → any GND,
AOUT → GP28 with **no divider**. Keep the 6.8 k + 10 k pair for the
next project. Calibration values in `config.py` (`adc_dry_raw=850`,
`adc_wet_raw=350`) stay until the replacement arrives and a fresh
three-point `print_raw()` (air / moist soil / water) gives real
numbers; the eyes-on verification lives in
[docs/test/hw-test-log.md](../test/hw-test-log.md).

### note · ADC_VREF is not a power rail

For future reference on this board: Pico pin 35 (ADC_VREF) is filtered
3V3 meant to feed the ADC's reference voltage, not source current to
external loads. Anything that draws more than a few µA must come from
3V3 OUT (pin 36) or VBUS (pin 40), never ADC_VREF. Mis-wiring VCC to
ADC_VREF corrupts **every** ADC channel on the Pico, not just the
sensor's own pin.

## 2026-05-15 · Reserved relay GPIOs floated, parked HIGH

### decision · park GP21/22/26/27 HIGH via output_pins, not Pin.IN+PULL_UP

Operator reported the four reserved relay channels on REL_CON
(GP21, GP22, GP26, GP27) sitting in a half-powered pseudo-state and
asked for them to be pulled if unused. Root cause: the pins were
declared under `DEVICE_CONFIG["pins"]` but not listed in
`output_pins`, so `HardwareFactory._init_pins()` never configured
them — they boot as floating inputs and feed the active-low relay
inputs with an indeterminate voltage. Fix is to add all four to
`output_pins` with `True` (HIGH = relay off, matching the three
active relays). Chose Pin.OUT driven HIGH over Pin.IN + PULL_UP
because (a) it matches the existing pattern for `relay_fan_1/2` and
`relay_growlight`, (b) a deterministic CMOS drive is stiffer than
the RP2040's ~50 kΩ internal pull against a relay opto-isolator
load, and (c) the validator/test plumbing for output_pins already
exists. Validator entry and a `test_reserved_relays_parked_high`
guard ship in the same commit.

### issue · 3V3 rail on REL_CON measures dead

Separately reported: the REL_CON 3V3 pin reads 0 V. Pure hardware,
not addressable in software. Logged under `docs/test/hw-test-log.md`
with a bench checklist (3V3 pin continuity to Pico 3V3, JD-VCC /
VCC jumper position on the relay board, R/trace check on the rail).

## 2026-05-15 · SD-update version string scheme

### decision · use UTC datetime + git short hash, drop per-day bump

`tools/build_update_payload.py` previously generated versions of the
form `YYYY-MM-DD.N` and tried to bump `N` per day. Two bugs made `N`
always 1: the lookup path was `out_dir.parent` instead of `out_dir`
(stat'd `build/manifest.json`, which never exists), and `_clean_out_dir`
wiped the directory before the bump logic ran. Rather than fix the
bump, the format now embeds the build identity directly:
`YYYYMMDDTHHMMSSZ-<shorthash>` (UTC, ISO 8601 basic, FAT32-safe — no
colons). Hash comes from `git rev-parse --short HEAD`; falls back to
`nogit` when git is unavailable. `lib/updater.py` treats version as an
opaque string, so no consumer changes were needed and all 55 updater
tests still pass.

## 2026-05-15 · SD-update loading-screen feedback

### decision · standalone UpdateFeedback, built only when an update fires

The updater runs at `main.py:175` BEFORE EventLogger and BEFORE the
full `StatusManager` / `BuzzerController` are wired (per the
comments at `main.py:168-181`). To keep that ordering intact, the
loading-screen feedback ships as `lib/updater_feedback.UpdateFeedback`
— a self-contained class that owns its own `machine.Pin` row and
`machine.PWM` buzzer, with no dependency on `StatusManager` or
`BuzzerController`. `run_pending_update` only constructs it after
`has_pending_update()` returns True, so a boot with no payload leaves
the LED row dark and the buzzer silent.

### decision · reuse `status_leds.walk_order` for the chase direction

The chase LEDs are driven from `pins.{activity,sd,reminder,warning,
error}_led` resolved through `config["status_leds"]["walk_order"]`
rather than a new pin list under `updater_feedback`. That keeps the
POST sweep and the update sweep visually consistent — reorder the row
in one place and both follow.

### decision · per-file ticks audible, per-chunk steps silent

`Updater._step_feedback(audio=True)` fires once per file in
`verify_payload` and in `apply` so the buzzer chirps at honest "one
file done" intervals. The per-chunk calls inside `_hash_file` and
`_copy_file` pass `audio=False` so the chase keeps moving on big
payloads without turning the buzzer into a buzzsaw. A user
`step_delay_ms` knob throttles the visible chase when chunks come
faster than the row can read.

### decision · success/fail jingles play before `machine.reset()`

On `apply_ok` the success jingle plays while all five LEDs are lit,
then `finish()` clears outputs and `machine.reset()` reboots into the
new code. On verify/apply/load-manifest failure, the failure jingle
plays and the function returns normally so the rest of boot can
continue with the still-installed code.

## 2026-05-15 · Button debounce: no caps, external pull-up only (this rev)

### decision · RES_BTN direct short; MEN_BTN with 10 kΩ external pull-up, no cap

Bench-tested both buttons on the assembled PCB. RES_BTN (3V3_EN to GND)
and MEN_BTN (GP9 to GND) both behaved sporadically with a 100 nF cap to
GND; RES_BTN as a direct short worked flawlessly, and MEN_BTN works
reliably with an external 10 kΩ pull-up to 3V3 and no cap. A 100 nF
cap on MEN_BTN was also tried in parallel with the 10 kΩ pull-up and
still misbehaved.

Why the cap fails on 3V3_EN: that pin is the RT6150 regulator enable,
not a logic input. It has a real on/off threshold with a deadband
(~1.0–1.2 V). With 100 nF the line drifts up through the deadband over
~10 ms on release, so the regulator brown-outs / restarts / oscillates
during POR. Direct switch crosses the threshold in ns and POR is
clean.

Why the cap fails on GP9 even with a stronger pull-up: with the cap
sitting directly across the switch (no series resistance), each
contact closure dumps the cap instantly. The cap therefore provides no
press-side debounce benefit, and on release the bounce can still pull
the partly-recharged cap back to 0 V — producing extra falling edges
*outside* the 60 ms software debounce window. Result: false "press"
events on release. A 10 kΩ pull-up alone (no cap) leaves GP9 as a
clean digital input that the 60 ms software debounce in
[lib/led_button.py:142](../../lib/led_button.py#L142) handles fine.

Next board revision adds a 1 kΩ series resistor between the MEN_BTN
switch and GP9 so the canonical three-component debounce (10 kΩ
pull-up + 1 kΩ series + 100 nF cap to GND) can be reinstated. Until
then: caps are off the BOM for both buttons. The firmware still asks
for `Pin.PULL_UP` internally; that's redundant with the external 10 kΩ
but harmless — leave it for the host-shim path and so the input
floats sanely if the external resistor is ever removed.

## 2026-05-15 · POST LED walk follows physical row order

### decision · Drive POST walk from `status_leds.walk_order`

The five status LEDs on LED_CON sit in one row, left-to-right: green
(activity, GP4), blue (sd, GP5), white (reminder, GP8), yellow
(warning, GP6), red (error, GP7). `run_post()` previously walked them
in GPIO-instantiation order (activity → reminder → sd → warning →
error), which visually jumps across the row instead of sweeping
along it. Added a new `status_leds.walk_order` config entry — a list
of role names — that `run_post()` resolves to LED instances at boot,
with the on-board heartbeat LED always appended last so it's still
verified. Stored as role names rather than GPIO numbers so the
physical layout is readable in `config.py` without cross-referencing
the pin map. Validator rejects empty lists, unknown roles, and
duplicates; matching tests cover the new ordering and a missing-
reminder fallback. Operator can rewire the LED row and re-tune the
walk by editing one config line, no code change.

## 2026-05-15 · OLED warmup delays moved to config

### decision · Promote SSD1306 init sleeps to DEVICE_CONFIG["display"]

`OLEDDisplay._init_display()` ran a fixed `time.sleep(2.0)` startup
banner plus several smaller VRAM-clear / invert sleeps totalling ~2.4 s
per construction. Under host pytest this was ~150 s of the 155 s
suite (~50 fixture builds + ~14 `test_main` runs that build a real
OLEDDisplay). Promoted to three config keys — `startup_banner_s`
(2.0), `vram_clear_delay_s` (0.05), `invert_delay_s` (0.1) — with
validator entries and `test_config` rows. Tests pass 0 to skip the
sleeps; production defaults are unchanged. `test_main` additionally
stubs `OLEDDisplay` with `Mock()` since those tests don't exercise
the display. Full suite: 155 s → 9.5 s.

### note · Two construction sites in test_oled_display

Both the `oled_display` conftest fixture and the local
`_make_display` helper / `test_init_failure_is_non_fatal` /
`test_long_press_no_remount_cb_safe` direct constructions had to be
updated to pass `startup_banner_s=0`. If a future OLED test
constructs `OLEDDisplay` directly without those kwargs, it will be
~2.4 s slow — fixture this in the test if it spreads.

## 2026-05-15 · SD-update payload now ships compiled .mpy

### decision · Compile config and lib for SD-update payloads, keep main.py raw

`deploy-update-to-sdcard` (and `-nocheck`) now depend on `build-mpy`
and call `tools/build_update_payload.py --compiled`, which reads from
the `build/` tree instead of the source tree. Payload layout matches
flash-mpremote exactly: `main.py` raw (boot entry name), `config.mpy`,
and `lib/*.mpy`. Rationale: same size win on the SD-update path as on
the flash path, and a single artifact shape for both deployment
routes. `build_update_payload.py` still defaults to source-py mode
when run by hand without `--compiled`.

### decision · allowed_paths gains config.mpy, keeps config.py

`DEVICE_CONFIG["updater"]["allowed_paths"]` now lists `"main.py"`,
`"config.py"`, `"config.mpy"`, `"lib/"`. The `lib/` prefix already
matches `lib/*.mpy`. Both raw-py and compiled payloads pass the
updater's whitelist so an operator running the script manually
without `--compiled` still gets a valid payload.

## 2026-05-15 · Coverage push to 90%

### decision · Bumped global coverage from 88.68% to 92.94%

Added targeted tests for the lowest-covered modules so every `lib/`
file is ≥88% individually while leaving the `pyproject.toml`
`fail_under` gate at 88. New file `tests/test_sht31.py` covers the
driver end-to-end (100%). Existing test files were extended:
`test_sd_integration.py` (75 → 93%), `test_buffer_manager.py`
(78 → 89%, including the previously-untested
`start_fallback_prune_task` loop body), `test_co2_logger.py`
(85 → 96%), `test_soil_logger.py` (83 → 97%), `test_led_button.py`
(87 → 90%). 767 tests pass; the gate stays at 88 so future changes
can absorb minor regressions without rewriting tests.

### note · Async-loop test idiom for the prune task

`start_fallback_prune_task` is a `while True` loop driven by
`asyncio.sleep`. The pattern used for buffer_manager / co2_logger /
soil_logger error-path tests: patch `asyncio.sleep` with a side-effect
list that returns `None` once (allowing one iteration of the loop
body) then raises `CancelledError`. Combined with `pytest.raises`
this exercises both the body and the cancellation handler in one
test without leaking tasks.

## 2026-05-15 · SD-payload software updater — implementation

### decision · Updater promoted from scaffold to working implementation

All 15 xfailed scaffold tests now drive the real `lib/updater.py`
implementation. `has_pending_update`, `load_manifest`, `verify_payload`,
`apply`, `finalize`, `log`, `_is_path_allowed`, `_hash_file`, and
`run_pending_update` are functional on both host (CPython) and target
(MicroPython). Hex digests come from `binascii.hexlify(h.digest())` for
portability — MicroPython's `uhashlib.sha256` has no `hexdigest()`.

### decision · Apply target lives on a module-level `_FLASH_ROOT`

`apply()` writes verified files under `lib.updater._FLASH_ROOT` (default
`"/"` on the Pico). Tests monkeypatch this to a `tmp_path` so the host
flow can run end-to-end without touching real flash. Keeping it as a
module global (not a constructor arg) matches the test contract from
the scaffold round.

### note · Finalize is idempotent against half-finished prior runs

`finalize()` clears any stale `applied/<version>/` directory before
renaming `update/` into place. Without this, a Pico that died between
apply and reset would leave the previous apply's directory there and
`os.rename` would fail on the next boot.

### note · Apply-OK still resets even if finalize warns

If `apply` succeeded but `finalize` raises (rare: e.g. SD pull-out
between writing the last file and renaming the dir), the new code is
already live on flash. `run_pending_update` logs the finalize warning,
then still calls `machine.reset()` so the freshly-applied code boots
clean. `/sd/update/` may still be present and would re-trigger on next
boot, but verify would pass again (hashes match what we just wrote), so
worst case is a redundant apply.

### decision · Host helper `tools/build_update_payload.py` ships

Operator workflow: `python tools/build_update_payload.py [--copy-to
G:/update]`. Walks `main.py`, `config.py`, and `lib/*.py` excluding
vendored drivers (`ds3231.py`, `ds2321_gen.py`, `sdcard.py`, `ssd1306.py`,
and any `picozero*` / `sdcard-*` / `ssd1306-*` siblings). Auto-versions
as `YYYY-MM-DD.N` bumping N when a same-day build already exists in the
parent output dir. Round-trip verified against `Updater.verify_payload`
on the just-built output.

### note · VSCode tasks `build-update-payload` / `deploy-update-to-sdcard`

Two tasks added to `.vscode/tasks.json`: `build-update-payload` writes
into `build/update_payload/`, `deploy-update-to-sdcard` runs pytest
first then copies to `G:/update` with `--no-confirm`. A
`deploy-update-to-sdcard-nocheck` variant skips pytest for tight inner
loops. `.vscode/` is gitignored, so these tasks live only on Dennis's
working copy; the helper script itself (`tools/build_update_payload.py`)
is committed and works standalone from the CLI.

## 2026-05-15 · SD-payload software-update scaffold

### decision · Boot-time SD-payload updater replaces lib/, main.py, config.py

New `lib/updater.py` (scaffold) implements an operator workflow: drop a
payload tree under `/sd/update/` with a `manifest.json` listing per-file
SHA-256 hashes, power-cycle the Pico, and the device replaces its own
code without Thonny. Wire-in lives in `main.py` between
`HardwareFactory.setup()` (SD must be mounted) and `EventLogger` init
(so logging code can itself be replaced). On success the updater renames
`/sd/update/` to `/sd/applied/<version>/`, appends to `/sd/updates.log`,
and calls `machine.reset()`.

### decision · Full code+config replacement (overwrites config.py)

The payload is allowed to replace `main.py`, `config.py`, and any file
under `lib/`. Operator-tuned values in `config.py` are NOT preserved
across updates — the payload's `config.py` wins. The whitelist is
enforced by `Updater._is_path_allowed` and configured via
`updater.allowed_paths`. Anything outside the whitelist is a
verification failure and live code is never touched.

### decision · Integrity = per-file SHA-256 in manifest.json

Every file in the payload has a SHA-256 hash and byte count in
`manifest.json`. `verify_payload()` checks all files before any write;
a single hash mismatch or path-whitelist violation aborts the apply
with `/sd/update/` left untouched, so the next boot can retry after
the operator fixes the payload.

### decision · No backup of live code; retry-on-failure recovery

Per the 2026-05-15 clarifying round, the updater does NOT snapshot the
current `/lib/` before writing. If a write fails mid-loop, the updater
retries each file up to `updater.max_retries` (default 3). If retries
exhaust, the apply halts and logs `apply_fail`; live code may be in a
partial state, but `/sd/update/` is left in place so the next reboot
re-attempts. Recovery from a fundamentally bad payload is the
operator's responsibility — fix the SD card and reboot.

### note · Wire-in is live but guarded against the scaffold stub

`main.py` calls `run_pending_update(DEVICE_CONFIG, hardware, wdt)`
inside a `try/except Exception` so the current `NotImplementedError`
from the stub is caught and printed without blocking boot. Once the
real implementation lands, the same call site continues to work; the
guard remains as the documented "updater failures must never block
normal boot" policy.

### issue · Operator tooling not in scaffold — RESOLVED 2026-05-15

A helper (`tools/build_update_payload.py`) that walks a source tree
and emits `manifest.json` with computed hashes was out of scope for
the scaffold. It now ships in the implementation commit alongside
VSCode tasks `build-update-payload` and `deploy-update-to-sdcard`.

## 2026-05-15 · Growlight mode flag (relay_only vs dimmed)

### decision · Add `growlight.mode` config flag, default `relay_only`

Introduce `DEVICE_CONFIG["growlight"]["mode"]` with values `"dimmed"`
(MCP4725 DAC drives ViparSpectra XS1500 brightness over the GP20 relay
master-switch) or `"relay_only"` (skip MCP4725 init entirely, treat the
lamp as plain on/off). Default is `"relay_only"` — the current
deployment has reverted to the bare relay-pin connection and the
dimming hardware is not wired in. Operators that want XS1500 dimming
must opt in by setting `mode="dimmed"`. The existing implicit fallback
(warn + relay-only if DAC init throws while `mode="dimmed"`) is
preserved so a flaky DAC doesn't brick the lamp schedule.

### note · Validator enforces the enum

`validate_config()` rejects any value other than `"dimmed"` or
`"relay_only"`. Two new rows in `tests/test_config.py` cover the
invalid-string and the dimmed-happy-path. No change to the
`GrowlightController` class — `main.py` already passes `dac=None`
through the same constructor, so the controller is mode-agnostic.

## 2026-05-15 · DHT22 → SHT31 sensor migration

### decision · Replace DHT22 with SHT31-D on shared I2C0, no fallback path

The one-wire DHT22 on GP15 is replaced by a Sensirion SHT31-D on the
shared I2C0 bus (RTC + OLED + DAC). New driver is `lib/sht31.py`
(CRC-validated single-shot high-repeatability, addresses 0x44 / 0x45).
GP15 becomes free for future use. The user explicitly waived a DHT21
fallback path — no dual-sensor support, no probe wrapper. Existing
`/sd/dht_log_*.csv` files stay on disk but new logs use `th_log_*.csv`.

### decision · Rename DHTLogger → TempHumidityLogger and inject sensor

`lib/dht_logger.py` becomes `lib/temp_humidity_logger.py` with class
`TempHumidityLogger`. The sensor is now constructor-injected (any
object with `measure() / temperature() / humidity()`) instead of
being built from a GPIO pin inside `__init__`. Downstream consumers
that previously took `dht_logger=` now take `th_logger=`
(FanController, HeaterController, OLEDDisplay). Status-manager keys
follow the rename: `dht_intermittent` → `th_intermittent`,
`dht_dead` → `th_dead`.

### decision · CSV columns unchanged, filename renamed to th_log

CSV header stays `Timestamp,Temperature,Humidity` so downstream
dashboards / readers keep working. Filename basename moves from
`dht_log` to `th_log` to match the rename-everywhere choice. Old
`dht_log_*.csv` files are not migrated; they sit alongside the new
files until the operator archives them manually.

### note · Probe data carries over, fail-rate revised

`PROBE.dht` becomes `PROBE.sht31` in `host_shims/_probe_data.py`.
Temperature/humidity distributions inherit the legacy DHT22 probe
data (same greenhouse) but the simulated fail rate drops from 2% to
0.5% and `min_interval_s` drops to 0.05 s to reflect I2C reliability
and a 16 ms high-repeatability conversion time. `hw_probe.py` now
runs `probe_sht31_endurance` in place of the old DHT22 bucket.

## 2026-05-14 · Phase 4 — Soil moisture (GP28 ADC)

### decision · SoilLogger mirrors CO2Logger / DHTLogger shape

`SoilLogger` is another BufferManager-backed CSV writer with date
rollover and an async `log_loop()` that yields. The only structural
difference is the input source (`machine.ADC.read_u16()` instead of a
UART frame) and a status-manager hook for the low-moisture warning.
Keeping the shape uniform across loggers means the next agent reads
one pattern, not three.

### decision · Calibration constants live in 0-1023 space, not raw u16

`read_u16()` returns 0–65535 on the RP2040, but the project convention
(plan section 4.1, REPL `print_raw()`, hardware datasheets) all speak
in 10-bit 0–1023. `SoilLogger` scales the u16 read down internally and
exposes only the 10-bit value as `last_raw` / in the CSV / in the OLED
"Raw:" row. Operators recalibrating with `print_raw()` see the same
units that go into `adc_dry_raw` / `adc_wet_raw`.

### decision · Warning LED via StatusManager.set_warning("soil_low", …)

Per the chosen option, soil low-moisture surfaces only on the warning
LED + OLED, not via the buzzer or EventLogger (beyond the natural
`WARN`/`INFO` lines on each transition). The warning key is
`soil_low`; the LED stays solid as long as the percent is below
`warn_pct_below` and clears on the first recovery cycle. No event-log
re-firing on every cycle because StatusManager already de-duplicates
keys.

### decision · `validate_config()` rejects dry <= wet at boot

Calibration mistakes (swapping dry/wet, or using the same raw value
for both) would silently produce nonsensical percentages or
divide-by-zero ratios. Catching it at boot is consistent with how the
heater's `day_min_temp >= night_min_temp` and the CO2 logger's
`override_ppm_on > override_ppm_off` are guarded. SoilLogger's
constructor also re-asserts the inequality so the unit tests can
exercise the guard without booting the whole config.

### note · OLED CO2 page upgraded as part of this phase

Phase 3 landed the CO2 logger but left the OLED `co2` menu as a
"Not active / future" placeholder. Phase 4 already had to extend
`OLEDDisplay` to inject `soil_logger`, so the `co2_logger` kwarg
landed in the same commit and the placeholder render was replaced
with `PPM: N` + `Vent: ON/off`. Future phases should not re-touch
this surface unless they add new fields.

### decision · ADC `read_u16` → 0-1023 uses round-half-up

The naive integer downscale `(u16 * 1023) // 65535` truncates and
gives off-by-one results at calibration anchor points
(`u16 == raw10 * 65535 / 1023`). `SoilLogger` uses
`(u16 * 1023 + 32767) // 65535` so a round-tripped calibration value
maps back to itself. Negligible cost on the Pico and removes a class
of test-flakiness.

## 2026-05-14 · Phase 3 — CO2 logger + fan override

### decision · CO2Logger mirrors DHTLogger shape, not a new abstraction

`CO2Logger` is structurally a `DHTLogger` clone: BufferManager-backed
CSV with `Timestamp,PPM`, date-based rollover, optional WriteQueue
plumbing, async `log_loop()` that yields between polls. Reusing the
same shape keeps the read path obvious for the next agent and the
SD-resilience guarantees come for free. The differences are scoped to
the sensor (UART instead of DHT22 driver) and the override flag.

### decision · External override is a callable attribute on FanController, not a setter method

`FanController.external_override` is a plain attribute typed as
"callable returning bool or None". The CO2 path assigns it via DI in
`main.py:417` (`fans[fan_index].external_override = co2_logger_obj.is_override_active`).
This keeps the FanController interface unchanged for legacy callers
that don't wire an override (default `None` = no hook) and lets a
future feature (e.g. an OLED manual-override page) replace the
callable without subclassing.

### decision · Override priority: thermostat > external > schedule

In the cycle tick, thermostat fires first and latches; if it's
active, the external override is skipped entirely. This protects
against the corner case where CO2 reads stale-low (false negative
release) while temperature is genuinely high — we never want CO2 to
release the thermostat-fired fan. The external override only outranks
the time-of-day schedule.

### deviation · Removed the cargo-cult `uart.flush()` call

The CO2 prototype in [`tests/co2log.py`](../../tests/co2log.py) called
`uart.flush()` before every write. MicroPython's UART has no documented
`flush()` semantics that affect RX (and on some ports the method does
not exist at all), so the call was meaningless or actively harmful
depending on the host shim. The driver omits it. The test fixture's
fake-UART originally cleared RX on flush, which surfaced the issue.

### decision · fan_2 is the CO2 override target

`co2_logger.override_fan` defaults to `"fan_2"` because fan_2 has the
higher `max_temp` and thus the larger ventilator role in the existing
schedule. Operators can flip to `"fan_1"` in config.py without code
changes. Validator rejects anything else so a typo doesn't silently
mean "no override".

### note · OLED CO2 page and warmup-tier escalation still deferred

The plan section 4.1 calls for a dedicated OLED page (ppm + 1-hour
trend arrow) and treating sensor warm-up vs steady-state failures
distinctly in StatusManager. Phase 3 lands the override + logging
core; OLED page and StatusManager wiring follow with the deferred
OLED batch from phases 1-2.

## 2026-05-14 · PCB gap plan — phases 0, 2, 1 implemented

### decision · Ordered phase 2 (heater) before phase 1 (DAC dimming)

Followed the plan's recommended order (section 7) rather than the
section-numbered order: phase 0 I2C scan → phase 2 heater → phase 1
DAC dimming. Heater is the smallest scope with the biggest immediate
field value, and it's independent of the I2C probe. Phase 1 depends
on the MCP4725 address being confirmed but proceeds with the
tentative `0x60` default per
[`2026-05-14-pcb-codebase-gap-plan.md`](2026-05-14-pcb-codebase-gap-plan.md).

### deviation · MCP4725 driver vendored under The Unlicense, not Apache-2.0

The plan listed `wayoda/micropython-mcp4725` as Apache-2.0; the
upstream LICENSE file actually says The Unlicense (public domain
dedication). Even more permissive than expected, so vendoring is
safe. The vendored copy at [`lib/mcp4725.py`](../../lib/mcp4725.py)
is a minimal adaptation (default address `0x60`, fast-write only —
the `read()` and `config()` paths were dropped as unused).

### decision · Heater is active-HIGH, NOT routed through `RelayController`

`HeaterController` in [`lib/heater.py`](../../lib/heater.py) talks
directly to `machine.Pin` with `value(1)` = on, `value(0)` = off.
Reusing `RelayController(invert=True)` would have implied "drive
LOW to activate", which is wrong for the MOSFET gate on GP3.
Sharing the relay base class also would have hidden the polarity
difference behind a flag — the explicit pin-level driver makes the
gate logic visible at the call site.

### decision · Heater day/night window inherits growlight schedule

Per locked design (plan section 4.1), the heater day window is
`growlight.dawn_*` + `heater.day_offset_min`, and the night window
is `growlight.sunset_*` + `heater.night_offset_min`. With both
offsets at 0 (the defaults) the heater follows the lamp 1:1. The
window computation lives in [`main.py`](../../main.py) so
`HeaterController` stays unaware of the growlight schedule — it
just gets `day_start_*` / `night_start_*` numbers via DI.

### decision · Dimming layer baked into `GrowlightController`, not a wrapper

`set_level(pct)` was added to `GrowlightController` directly rather
than introducing a `DimmableGrowlight` wrapper. The controller
already owns the relay; the DAC is a second device on the same
on/off boundary, so co-locating brightness with the master switch
is the smallest readable surface. DAC injection is optional —
passing `dac=None` keeps the relay-only legacy path so the unit
tests that don't care about brightness still work unchanged.

### decision · DAC write fires before relay close on rising edges

`set_level()` writes the DAC value first, then closes the relay.
This prevents a brief full-brightness flash when the DAC was sitting
at a stale high value from a previous session. The reverse on
falling edges is fine — the relay opens, then DAC goes to 0 — the
op-amp output collapses with the load.

### note · OLED pages and ramp scheduler deferred

Per scope agreed at the start of this session: phases 0, 2, and 1
land the controllers and the static-default brightness, but the
OLED menu pages for CO2 / Soil / Heater / Dim and the dawn/sunset
ramp scheduler are deferred to a later phase. The dimming layer
already supports arbitrary `set_level()` calls; a future ramp task
just needs to schedule those calls over `ramp_duration_s`.

## 2026-05-14 · Configurability rule

### decision · Added `.claude/rules/ecc/common/configurability.md` as a load-bearing rule

Policy: every tunable behavior value (pins, intervals, thresholds,
timeouts, retry counts, buffer sizes, feature toggles, paths,
freq/duty/brightness defaults) MUST go through `DEVICE_CONFIG` in
[config.py](../../config.py), with a matching `validate_config()`
entry and a row in [tests/test_config.py](../../tests/test_config.py),
landing in the same commit. Pure algorithmic constants stay inline.
Escape hatch is a `# fixed: <reason>` comment above the literal —
the only acceptable form of hardcoded tunable. Consumers in `lib/`
receive values via DI from [main.py](../../main.py) and don't import
`DEVICE_CONFIG`. Chose "any tunable behavior value" as the trigger
(strictest reasonable bar without forcing math constants into the
dict) so the field can be retuned without touching logic, matching
the project's embedded long-life profile.

## 2026-05-14 · PCB ↔ codebase gap analysis

### note · Full netlist walk produced a per-peripheral implementation plan

Extracted the complete netlist from
`docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json` (union-find over wire
endpoints + pin endpoints + netflag anchors → 49 named nets, 23
short unnamed nets). Cross-checked every Pico GPIO and shared bus
against `config.py`, `main.py`, and `lib/`. Result lives in
[`2026-05-14-pcb-codebase-gap-plan.md`](2026-05-14-pcb-codebase-gap-plan.md).

### issue · Four firmware-actionable gaps identified

1. **Dimmable grow light** — MCP4725 DAC + op-amp + GL_CON wired on
   the PCB but no driver and no hook into `GrowlightController`. The
   relay (GP20) is currently the only control; brightness is wasted.
2. **Heater control** — GP3 → R6 → IRLZ44N → HE_CON path exists but no
   `HeaterController`. Config has the pin key only.
3. **CO2 sensor in main loop** — UART0 on GP16/17 wired through R9/R11
   to CO2_CON, but only prototype code in `tests/co2log.py` /
   `co2test.py`. No production driver, no main-loop wiring.
4. **GP28 ADC** — ADC_CON pin 4 wired but firmware purpose
   unspecified (soil moisture? light meter? second thermistor?).

Reserved relays GP21/22/26/27 are wired to REL_CON 5–8 but
intentionally dormant; low-priority.

### decision · Phase order = heater → DAC dim → CO2 → ADC

Recorded in the plan doc. Rationale: heater is smallest-scope and
biggest immediate value (greenhouse needs heat before it needs
brightness control); DAC dimming follows because it depends on Q5
(I2C address verification, which Phase 0 resolves); CO2 is largest
scope; ADC is gated on Q1 (purpose). Six open questions (Q1–Q6) are
listed at the top of the plan doc and should be answered via a
single `AskUserQuestion` round at the start of phase 1.

## 2026-05-14 · PCB pin remap (Pi-Greenhouse-PCB v2026-05-14)

### decision · Remapped every GPIO to match the printed PCB

The board layout in `docs/SCH_Pico-Greenhouse-PCB_2026-05-14.json` (EasyEDA
schematic, post-PCB-print) reassigns almost every Pico GPIO from the original
prototype wiring. `config.py` is now the single source of truth, and
`validate_config()` requires the new pin keys.

Key moves:

- **Status LEDs reshuffled on LED_CON** — activity=GP4 (unchanged),
  SD=GP5 (was GP8), warning=GP6 (unchanged), error=GP7 (unchanged),
  reminder=GP8 (was GP5). Net effect: SD ↔ reminder swap vs. the original
  prototype wiring. (Corrected post-PCB-print after eyes-on confirmation
  by the user.)
- **CO2 UART → UART0 on GP16/GP17** (was UART1 on GP2/GP3). R9/R11 sit between
  the Pico and CO2_CON as series resistors.
- **Buzzer GP14** (was GP20), with R3 pull-down to GND on the buzzer line.
- **Relays consolidated on REL_CON** — fan_1=GP18, fan_2=GP19, growlight=GP20
  (old values were 16/18/17). Four further relay slots reserved on
  GP21/GP22/GP26/GP27.
- **New peripherals** added as config keys with no behavior yet: heater MOSFET
  on GP3 (via R6 → IRLZ44N gate), ADC input on GP28 (ADC_CON pin 4), and the
  MCP4725 grow-light DAC on the existing I2C0 bus (default address 0x60).
- **RES_BTN now drives 3V3_EN** (Pico hardware reset), not a GPIO. The legacy
  `button_reserved` key is kept (validator stability) and points at the GP2
  breakout header for any future software-side button.

### note · `main.py` and `lib/hardware_factory.py` are fully config-driven

Confirmed by grep: no hardcoded GPIO numbers outside `config.py` (only
`Pin(<config>...)` constructions through DI). The remap therefore touched
zero `lib/` files. 546 pytest tests + ruff stayed green after the edit.

### issue · GL_DAC / heater / ADC have no driver yet

The PCB exposes hardware the firmware does not yet exercise: MCP4725 grow-light
DAC on I2C0 (0x60), heater MOSFET on GP3, and ADC input on GP28. Config keys
are in place so future work can wire them without touching the schema again.
Verification of these channels is captured in `docs/test/hw-test-log.md` as
"no driver yet — must not energize" checks.

## 2026-05-14 · Commit-on-stop enforcement

### decision · Stop hook blocks turn-end while tracked tree is dirty

Extended `commit-granularity.md` with a "Commit before ending the
turn" section: when Claude finishes a task, all of its work must
already be committed. Enforced by `.claude/hooks/check-clean-tree.ps1`,
wired as a `Stop` hook in `.claude/settings.json`. The hook runs
`git status --porcelain`, ignores untracked entries (`??`), and
returns `{"decision":"block","reason":"..."}` if any tracked file is
modified or staged — re-prompting Claude with the dirty file list
and a pointer to the rule.

### deviation · Hook scope limited to tracked changes

User chose "any tracked changes Claude touched" over "entire working
tree must be clean" for the scope. Practical consequence: if Claude
creates a brand-new file and forgets to `git add` it, the hook
**will not catch it** — only the rule does. The hook is a backstop
for the common case (modifying tracked files); Claude is still
expected to follow the rule's letter for new files. This was the
explicit trade-off to avoid blocking on user-vintage untracked junk
(scratch files, build artifacts, `docs/notes/` before it was
committed).

### decision · Per-turn opt-out via sentinel file

When the user says "leave it uncommitted" / "don't commit yet" /
equivalent, Claude creates `.claude/.skip-commit-check`. The hook
consumes and deletes the sentinel on next Stop, allowing one turn to
end uncommitted. The opt-out is per-turn, not per-session — each
subsequent dirty Stop needs its own sentinel. This keeps the default
("commit before done") strict and makes the escape hatch feel
deliberate.

### note · `.claude/` is gitignored on this repo

The new rule file, hook script, and settings change all live under
`.claude/` which is in `.gitignore` (line 21). They exist only on
this machine and won't propagate via `git pull`. Other contributors
who want the same enforcement need to add the same files locally.
Promoting any of this to checked-in territory would require either
unignoring `.claude/` or moving the rule/hook to a tracked location
(e.g. `docs/` for the rule, a top-level `hooks/` for the script).

## 2026-05-14 · Commit granularity rule

### decision · One logical change per commit, with refactor/behavior split

Added [.claude/rules/ecc/common/commit-granularity.md](../../.claude/rules/ecc/common/commit-granularity.md)
as a third load-bearing rule alongside `clarifying-questions.md` and
`documentation-routine.md`. Sizing is "one logical change per commit"
regardless of file count — a coherent change can span multiple files
when they form one indivisible unit (e.g. a config key + its validator
+ its test row), but a refactor and a behavior change in the same
working tree must split into two commits. Banned patterns:
`wip`/`checkpoint`/`misc` messages, refactor mixed with behavior change,
tests bundled with unrelated code, and squash-merging into `main`.
Rationale: future AI sessions read `git log` to reconstruct intent;
construction-site commits force them to diff a swamp.
