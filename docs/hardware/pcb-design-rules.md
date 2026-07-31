# PCB design rules — Pico Greenhouse mainboard

> Canonical net-class design ruleset for the next-revision PCB. This is
> the source of truth the EasyEDA DRC profile and net-class assignments
> are built from. Derived from the 2026-06-02 EasyEDA export
> ([Sheet_1_2026-06-02.net](EasyEDA-Files/Sheet_1_2026-06-02.net)) and
> the fab/layout decisions already queued in
> [next-revision.md](next-revision.md).
>
> Companion: full rationale in
> chat-log 2026-06-02.

## Stackup & fab assumptions

These rules are floored to the chosen fab process. Change the process and
the **minimums** below move with it.

| Parameter | Value | Source |
| --- | --- | --- |
| Layers | **2 (top + bottom)** | through-hole vias only; no inner planes |
| Outer copper | **2 oz** | [PCB fab order — 2 oz copper](next-revision.md) |
| Fab capability floor | **JLCPCB 2 oz standard** | sets the hard minimums below |
| Min track / spacing (fab floor) | **0.20 mm** | JLCPCB 2 oz process (8 mil) |
| Min via (fab floor) | **0.45 mm pad / 0.25 mm drill** | JLCPCB; 0.30 mm drill preferred |
| Highest on-board voltage | **+19.5 V** | heater rail — all nets are low-voltage, **no mains creepage on-board** (relay modules and 230 V loads are off-board) |

> **Correction vs. the queued layout note.** The
> [Power trace widths](next-revision.md) entry sets a **0.15 mm default
> clearance**. That is **below the 0.20 mm JLCPCB floor for 2 oz copper**
> and would be DRC-rejected (or silently bumped to the 1 oz process,
> losing the current-carrying margin the 2 oz order was placed for). This
> ruleset sets the **default clearance to 0.20 mm**. A 0.15 mm default is
> only valid if the board is re-ordered as 1 oz — which contradicts the
> heater/12 V trace-width math. See the chat-log entry for the trade-off.

## Global default rule (catch-all)

Any net not explicitly assigned to a class below inherits the default:

| | Value |
| --- | --- |
| Track width | **0.25 mm** |
| Clearance | **0.20 mm** |
| Via pad Ø | **0.60 mm** |
| Via drill Ø | **0.30 mm** |
| Max track length | **200 mm** |

**Fine-pitch escape exception:** under the Pico castellations, the
PCA9685 TSSOP-28 (0.65 mm pitch) and the MCP4725 SOT-23-6 fan-out only,
track and clearance may drop to **0.20 mm / 0.20 mm** for the short
escape segment, then widen to the class value. This is the only place
sub-0.25 mm track is allowed.

## Net classes

Track widths for the power classes are taken from the
[Power trace widths](next-revision.md) entry (IPC-2221, 2 oz, <30 °C rise);
signal max-lengths are SI budgets for the bus speeds in
[config.py](../../config.py) (I²C 400 kHz, SPI 10 MHz, UART 9600).

| Class | Track width | Clearance | Via pad Ø | Via drill Ø | Max length | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| **PWR-HEATER** (≤6.8 A, 19.5 V) | **3.0 mm** (pour preferred) | **0.30 mm** | 1.2 mm | 0.60 mm | n/a — keep shortest | **Avoid layer changes**; if unavoidable use **≥3 parallel vias**. Star-ground return to 19V_IN GND. |
| **PWR-12V** (≤9 A buck) | **2.5 mm** | **0.30 mm** | 0.90 mm | 0.50 mm | n/a | **≥2 parallel vias** per layer change. |
| **PWR-5V** (≤5 A) | **1.5 mm** | **0.30 mm** | 0.90 mm | 0.50 mm | n/a | ≥2 parallel vias per layer change. |
| **PWR-SWITCHED** (fan/solenoid drains, ~1–2 A, switched 12 V) | **1.0 mm** | 0.30 mm | 0.60 mm | 0.30 mm | keep short | Tight flyback loop: drain↔diode↔rail. Route away from I²C/analog. |
| **PWR-3V3** (≤0.8 A) | **0.80 mm** | 0.20 mm | 0.60 mm | 0.30 mm | n/a | Main logic rail. |
| **PWR-FEED** (PPTC-fused / Schottky-protected connector power ≤0.3 A) | **0.50 mm** | 0.20 mm | 0.60 mm | 0.30 mm | n/a | Current-limited by PPTC (U1–U8) or SS14 backfeed diode. |
| **GND** | pour both layers | 0.20 mm | 0.60 mm | 0.30 mm | n/a | Continuous bottom pour; **stitch vias liberally**; heater return star-points at 19V_IN GND (not under signal ground). |
| **SIG-I2C** (400 kHz fast mode) | 0.25 mm | 0.20 mm | 0.60 mm | 0.30 mm | **150 mm** | Route SDA/SCL as a pair, similar length; keep over GND pour; away from PWM-GATE & PWR-SWITCHED. Pull-ups 2.2 kΩ. |
| **SIG-SPI** (10 MHz, SD) | 0.25 mm | **0.25 mm** | 0.60 mm | 0.30 mm | **75 mm** | Reference CLK to GND pour; keep CLK away from MISO/MOSI; series dampers (R8/R10 33 Ω) at the Pico end. |
| **SIG-UART** (9600 baud, CO2) | 0.25 mm | 0.20 mm | 0.60 mm | 0.30 mm | **250 mm** | Slow; divider on RX (R3/R4). Tolerant of length. |
| **SIG-ANALOG** (0–10 V dim, ADC, VREF) | 0.30 mm | **0.25 mm** | 0.60 mm | 0.30 mm | **100 mm** | Guard from digital/PWM; ADC_GND single-point to GND; keep off the switching region. |
| **SIG-PWM-GATE** (PCA9685→gate, MCP1416 chain, switching nodes) | 0.30 mm | 0.20 mm | 0.60 mm | 0.30 mm | **100 mm** | Keep short for clean edges; route away from SIG-ANALOG & SIG-I2C. |
| **SIG-CTRL** (relays, LEDs, buttons, buzzer, RUN, 1-Wire, misc GPIO) | 0.25 mm | 0.20 mm | 0.60 mm | 0.30 mm | **200 mm** | Slow digital; default-equivalent, named for clarity. |
| **SIG-SWD** (debug) | 0.25 mm | 0.20 mm | 0.60 mm | 0.30 mm | **100 mm** | SWCLK/SWDIO; keep clear of switching nodes. |

## Per-net assignment

Every net in the 2026-06-02 netlist, mapped to its class. Input-rail
fuse/Schottky segments are named after the netlist labels (e.g. `F3_1`
is `19.5V_IN → F3`, `F3_2` is `F3 → D2`).

### PWR-HEATER — 3.0 mm / 0.30 mm
- `F3_1` (19.5V_IN → F3 fuse)
- `F3_2` (F3 → D2 / MBR20100CT)
- `+19.5V` (post-Schottky 19.5 V rail → HE_CON, bulk caps, dim-LED R23)
- `HE_CON1_4` (heater MOSFET T1 drain → HE_CON, D15 flyback)

### PWR-12V — 2.5 mm / 0.30 mm
- `F2_1` (12V_IN → F2 fuse)
- `F2_2` (F2 → D6 / MBRD1045)
- `+12V` (12 V rail: fans, HPA solenoid, LM358 V+, op-amp, dim-LED R22)

### PWR-5V — 1.5 mm / 0.30 mm
- `5V_IN1_2` (5V_IN → F1 fuse)
- `F1_2` (F1 → D5 / MBRD1045)
- `+5V` (5 V rail: PCA9685 V+, MCP1416 V+, buzzer, dim-LED R21)

### PWR-SWITCHED — 1.0 mm / 0.30 mm (tight flyback loop)
- `FAN_CHA1_4` (Q2 drain → case fan + D10 flyback)
- `FAN_GR_C1_4` (Q4 drain → growroom-center fan + D12)
- `FAN_GR_E1_4` (Q3 drain → growroom-east fan + D11)
- `FAN_GR_W1_4` (Q5 drain → growroom-west fan + D13)
- `FAN_H1_4` (Q6 drain → heater-distribution fan + D14)
- `HPA_SOL1_4` (Q1 drain → HPA solenoid + D9)

### PWR-3V3 — 0.80 mm / 0.20 mm
- `+3.3V` (main 3V3 logic rail — Pico, sensors, PPTC inputs, dim-LED R20)

### PWR-FEED — 0.50 mm / 0.20 mm (PPTC / SS14 protected, ≤0.3 A)
- `TH_CON1_2` (3V3 via U1 → SHT31/TH connector)
- `ADC_CON1_3` (3V3 via U2 → ADC/soil connector)
- `U3_1` (3V3 via U3 → I2C0_CON1)
- `W_TEMP_CON1_2` (3V3 via U6 → water-temp connector)
- `U7_1` (3V3 via U7 → W_FLOAT connector + R7 pull-up)
- `I2C0_CON2_2` (5V via U4 → I2C0_CON2)
- `U5_1` (5V via U5 → I2C1_CON1)
- `U8_1` (5V via U8 → CO2 connector)
- `INT_CON2_2` (5V via D8/SS14 → INT_CON1/2)
- `INT_CON2_3` (3V3 via D7/SS14 → INT_CON1/2)

### GND — pour both layers, stitch vias
- `GND`

### SIG-I2C — 0.25 mm / 0.20 mm, ≤150 mm, route as pair
- `I2C0_SDA`
- `I2C0_SCL`
- `I2C1_SDA`
- `I2C1_SCL`

### SIG-SPI — 0.25 mm / 0.25 mm, ≤75 mm
- `SPI_CLK`
- `SPI_CS`
- `SPI_TX` (Pico MOSI → R10)
- `SD_CON1_5` (R10 → SD MOSI)
- `SPI_RX` (Pico MISO ← R11, R15 10 kΩ pull-up)
- `SD_CON1_4` (R11 → SD MISO)

### SIG-UART — 0.25 mm / 0.20 mm, ≤250 mm
- `UART0_TX` (R40 → CO2 connector)
- `U13_21` (Pico TX → R40)
- `UART0_RX` (divider node R3/R4 → Pico RX)
- `CO2_CON1_3` (S8 5 V TTL TXD → R4 series)

### SIG-ANALOG — 0.30 mm / 0.25 mm, ≤100 mm, guard from digital
- `GL_DAC_VOUT` (MCP4725 out → LM358 in)
- `GL_DIM+` (LM358 out → grow-light 0–10 V dim)
- `U11_1` (LM358 feedback / unused-section tie)
- `R39_2` (LM358 feedback node R38/R39)
- `ADC_VREF` (Pico ADC_VREF → ADC connector)
- `ADC_GP28` (Pico GP28/ADC2 → ADC connector)
- `ADC_GND` (ADC single-point ground → Pico AGND)

### SIG-PWM-GATE — 0.30 mm / 0.20 mm, ≤100 mm, keep short
- `PWM0` `PWM1` `PWM2` `PWM3` `PWM4` `PWM5` (PCA9685 → fan/solenoid gate resistors)
- `R30_1` `R31_1` `R32_1` `R33_1` `R34_1` `R35_1` (MOSFET gate nodes + 10 kΩ pull-downs)
- `PWM6` `PWM7` `PWM8` `PWM9` `PWM10` `PWM11` `PWM12` `PWM13` `PWM14` `PWM15` (reserve header PWM_RES1 — unrouted unless a stage is fitted)
- `GP3` (Pico → MCP1416 input)
- `U10_5` (MCP1416 out → R36)
- `T1_1` (heater MOSFET gate node, R36/R37)

### SIG-CTRL — 0.25 mm / 0.20 mm, ≤200 mm
- `GP18` `GP19` `GP20` `GP21` `GP22` (relay control / level-switch input)
- `GP4` `GP5` `GP6` `GP7` `GP8` (LED_CON status LEDs)
- `GP9` (menu button)
- `GP14` (buzzer)
- `GP15` (SD card-detect — slow, routed with SD cluster)
- `GP2` (1-Wire / W_TEMP reserved)
- `RUN` (Pico run, button + supervisor)
- `3V3_EN` (Pico 3V3 enable / reset switch)
- `U9_2` (MAX809 /RESET → R14 → RUN)
- `W_FLOAT_CON1_4` (water-float switch signal → R6)
- `R20_1` `R21_1` `R22_2` `R23_1` (power-good LED anodes)

### SIG-SWD — 0.25 mm / 0.20 mm, ≤100 mm
- `SWCLK`
- `SWDIO`

## Routing priority (place/route order)

1. **GND pour** on bottom, stitched.
2. **PWR-HEATER** first — wide pour, star-ground return, then heatsink/thermal-via cluster under T1/D2.
3. **PWR-12V / PWR-5V** rails and bulk-cap loops.
4. **PWR-SWITCHED** flyback loops (drain–diode–rail kept tight).
5. **SIG-ANALOG** away from all switching copper.
6. **SIG-SPI** then **SIG-I2C** over continuous GND.
7. Remaining **SIG-CTRL / SIG-UART / SIG-SWD** fill.
