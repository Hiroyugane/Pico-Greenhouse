# Hardware inventory — parts on hand

> Snapshot of physical stock available for the Pi Greenhouse build,
> grouped by function. Compare against
> [next-revision.md](next-revision.md) before placing the next order;
> the shopping list at the bottom of this file does that comparison
> explicitly.
>
> Quantities reflect packs as purchased — split packs / partial use
> not tracked here. Update when a part is consumed below a threshold
> worth re-ordering, or when new stock arrives.
>
> **Last reconciled:** 2026-05-24 against
> [next-revision.md](next-revision.md), now also covering the SD card
> module swap (AZDelivery generic → Adafruit 4682 3 V bypass); earlier
> the same day picked up the two previously-unidentified AliExpress
> orders and the LM358 next-rev path switched from SOIC-8 LM358DR to a
> DIP-8 socket + the LM358N already in stock.

## Active components — semiconductors

### MOSFETs

- **IRLZ44N** (TO-220, logic-level N-channel, 47 A / 55 V) — **10 pcs**.
  Used for HE_MOSFET (heater) and the future PCA9685-driven fan stage
  per [next-revision: heater channel count](next-revision.md) and
  [next-revision: fans → PCA9685 + IRLZ44N](next-revision.md).

### Diodes

- **1N5822** (DO-27 axial Schottky, 3 A / 40 V) — **20 pcs**. Limited
  use — under-rated for the rail diodes specced as MBRD1045
  (10 A / 45 V D-PAK) in [next-revision: Schottky diode plan](next-revision.md).
  Acceptable only as breadboard / prototype substitute, not for the
  fabricated board.
- **1N4007** (DO-41, 1 A / 1000 V) — **5 pcs** (ELEGOO Fun Kit).
  Earmarked for fan flyback per
  [next-revision: fans → PCA9685 + IRLZ44N](next-revision.md). 5 fans
  planned → order more.

### Op-amps and small-signal ICs

- **MCP6002** (SOIC-8, dual op-amp, abs-max V_DD–V_SS = 7 V) —
  **10 pcs**. **Do not reuse on next rev** — abs-max violation on the
  12 V rail is the reason for the
  [next-revision: MCP6002 → LM358 retune](next-revision.md). Keep
  current stock for breadboarding 3.3 V / 5 V circuits only.
- **LM358N** (DIP-8 dual op-amp, V_CC max 32 V) — **10 pcs**. **Now
  the chosen part for the next-rev grow-light op-amp** — the
  schematic was updated to use a DIP-8 socket footprint (instead of
  the original SOIC-8 LM358DR plan) so this on-hand stock can be
  used without a procurement step. See
  [next-revision: MCP6002 → LM358 + grow-light gain retune](next-revision.md).
- **MCP4725A0T-E/CH** (SOT23-6, 12-bit I²C DAC) — **10 pcs**. Matches
  current grow-light DAC role.
- **MCP4725 breakout board** (12-bit DAC, I²C) — **1 pc**. Useful for
  bench bring-up before the SMD chips land on the PCB.
- **74HC595** (8-bit shift register, DIP) — **1 pc** (ELEGOO kit).
  Not in current design.
- **4N35** (optocoupler, DIP-6) — **1 pc** (ELEGOO kit). Not in
  current design; potentially useful for mains-side relay drive
  isolation.
- **PN2222** (NPN, TO-92) — **5 pcs** (ELEGOO kit). General-purpose
  small-signal switching, not in current design.

### Fuses (resettable)

- **PPTC resettable fuse** (250 V, 0.3 A trip) — **10 pcs**. Not part
  of any current next-rev entry; potentially useful for signal-line
  protection on the RJ12 ports.

## Power — supplies, fuses, holders, connectors, heating

### External power supplies

- **Dell 180 W AC adapter** (model "DWSG3" — label string approximate,
  re-verify on next physical inspection) — **1 pc**. Feeds the 19.5 V
  input rail (the heater path via D5 / F1 / HE_MOSFET).
  - **Input:** 100–240 V~, 50–60 Hz, 2.5 A
  - **Output:** 19.5 V DC, 9.23 A (180 W)
  - Drives the **19.5 V rail** referenced throughout
    [next-revision.md](next-revision.md); the 9.23 A nameplate is the
    upper-bound figure used to size MBRD1045 (10 A / 45 V) headroom
    on D6 and to sanity-check the 6.8 A parallel-heater steady-state.
  - 5 V and 12 V input rails come from separate bricks (not yet
    catalogued here — add when re-verified on the bench).

### Fuses (one-shot)

- **5×20 mm glass fuse assortment**, **fast-blow F-rated** —
  **100 pcs total** across 0.2 A / 0.5 A / 1 A / 2 A / 3 A / 5 A /
  8 A / 10 A / 15 A / 20 A. **F rating is wrong for F1.**
  [next-revision: F1 fuse — 10 A 5×20 mm slow-blow](next-revision.md)
  requires **T (slow-blow)** to tolerate bulk-cap inrush.
  Keep this kit for bench prototyping; **order T-rated 10 A** for the
  build.

### Fuse holders

- **5×20 mm PCB-mount fuse holder** ("PCB welding plate") —
  **10 pcs**. Matches the F1 footprint requirement.
- **5×20 mm / 6×30 mm spiral glass tube fuse holder** — **10 pcs**.
  Alternative form factor; useful spare.

### Power input connectors

- **XT60 male / female bullet pair** — **5 pairs**. Standard XT60
  with bullet crimps; cable-side.
- **XT60PW-F** (panel / PCB-mount female, board-edge prongs) —
  **5 pcs**. Matches the
  [next-revision: power input → XT60 across all three rails](next-revision.md)
  requirement; one per input rail (5 V, 12 V, 19.5 V) + spares.

### Mains distribution (post-relay)

- **Heavy-duty screw-terminal distribution block** ("462d") —
  **4 units**. Useful for mains-side wiring from the two remaining
  relays (grow light, heater) once fans move to PCA9685 per
  [next-revision: relay connector cleanup](next-revision.md).

### Heater elements

- **Polyimide film heater** (100 × 100 mm, 24 V, 100 W, self-adhesive) —
  **3 pcs**. Two go in parallel on the HE_MOSFET output per
  [next-revision: heater channel count](next-revision.md); one spare.

### AC mains entry (enclosure-side)

- **IEC320 C14 panel inlet** with rocker switch + LED + 5×20 mm
  10 A fuse holder (250 V, brass contacts, "AC-08A" 3-pin combo
  module) — **5 pcs**. System-level AC mains entry for the
  enclosure: brings line + neutral + earth into the box behind one
  switched and fused inlet, before the DC bricks and the grow-light
  / heater relay loads. **Not currently a next-revision queue item;
  reserved for the enclosure / harness redesign.**
- **5×20 mm 10 A glass fuse** (F-rated, packaged separately with the
  IEC inlets above) — **20 pcs** (2 packs × 10). Spare fuses for
  the IEC inlet only; **does not satisfy the T-rated F1
  requirement** on the PCB (see fuse assortment note above).

## Sensors and display modules

- **SSD1306 OLED display** (0.96", 128×64, I²C, 3.3 V–5 V) —
  **2 pcs**. Matches current `oled` config.
- **VEML7700 ambient light sensor module** (I²C, 0–120 k lux) —
  **5 pcs**. **Not in current next-revision.** Candidate for a future
  light-feedback feature on the grow-light loop; reserved.
- **Capacitive soil moisture sensor** (analog 0–5 V output) —
  **10 pcs** (refunded by seller, kept as-is per their goodwill).
  Matches the soil-ADC stage planned in
  [next-revision: ADC / soil-moisture interface](next-revision.md).
- **SHT31** — **not in this inventory** (assumed already mounted on
  the bench unit).

## SD card / storage

- **AZDelivery generic "SPI Reader Micro Speicher SD TF Karte" module** —
  **on the current PCB, not separately catalogued.** Accepts 5 V Vcc
  via onboard AMS1117-3.3 LDO + (typically) a 74HC125 buffer. Stays on
  the **current** revision; superseded on the next revision per
  [next-revision: SD card module → Adafruit 4682](next-revision.md).
  No separate spare stock recorded — the only known unit is the one
  populated on the existing board.
- **Adafruit 4682 "Micro SD SPI or SDIO Card Breakout — 3V ONLY!"** —
  **0 pcs on hand, on the order list below.** 3 V bypass variant of
  the older Adafruit 254 — no LDO regulator, no level shifter, onboard
  pull-ups on every SPI logic line, dedicated DET (card-detect) pin
  with 4.7 kΩ pull-up, 25.4 × 22.8 × 3.5 mm. Chosen part for
  [next-revision: SD card module → Adafruit 4682](next-revision.md).

## I²C / serial / RJ12 connectors

- **RJ11 6P4C double-port female PCB jack** — **10 pcs** (two
  separate orders, see source list at bottom). Suitable for the
  paired-port silkscreen on the enclosure wall.
- **RJ11 6P6C curved-pin PCB jack** — **30 pcs**. 6P6C is the
  full-conductor variant used for RJ12; matches the
  [next-revision: rename "I2C con_1" → "SHT31" + second outward RJ12](next-revision.md)
  requirement.
- **RJ11 6P4C crystal head (cable plug)** — **50 pcs**. Cable-side
  crimp connectors for sensor harnesses.
- **RJ45 / RJ11 crimper tool** — **1 pc**.
- **4-pin PWM CPU fan extension cable** (M / F, 24 AWG) — **10 pcs**.
  Matches the case / ambient fan harness style.

## Passives

### Resistor kits (Through-hole, ±1 %, 1/4 W)

- **WayinTop 600 pc kit** — ±1 %, 1/4 W, 20 pcs each. Authoritative
  value list per the seller's product page: **10 Ω, 22 Ω, 47 Ω,
  100 Ω, 150 Ω, 200 Ω, 220 Ω, 270 Ω, 470 Ω, 680 Ω, 1 kΩ, 2 kΩ,
  2.2 kΩ, 3.3 kΩ, 4.7 kΩ, 5.1 kΩ, 6.8 kΩ, 10 kΩ, 47 kΩ, 51 kΩ,
  68 kΩ, 100 kΩ, 220 kΩ, 300 kΩ, 470 kΩ, 680 kΩ, 1 MΩ.**
  (The seller copy is OCR-garbled — "4 Ω Ω, 6 Ω Ω, 6 kΩ" reads as
  470 Ω, 680 Ω, and an unidentified 28th value; assume the kit covers
  nothing not listed above.)
  **Confirmed not in the kit: 1.5 kΩ, 8.2 kΩ, 15 kΩ** — all three
  required by next-revision entries (LED current limiters and
  soil-ADC divider) and now on the order list below.
- **ELEGOO Fun Kit 10 pc rows** — 10, 100, 220, 330, 1 k, 2 k, 5.1 k,
  10 k, 100 k, 1 MΩ (10 pcs each). 330 Ω is **only** available from
  this kit (WayinTop list above does not include 330 Ω).

### Capacitors (kit-included only)

- **Electrolytic** (ELEGOO kit): **100 µF 5 pcs, 10 µF 5 pcs.** No
  larger values — the bulk caps required by
  [next-revision: bulk capacitance on 12 V and 19.5 V](next-revision.md)
  (220 µF / 25 V, 470 µF / 35 V, 1000 µF / 16 V) are **not on hand**.
- **Ceramic** (ELEGOO kit): **22 pF 10 pcs, 104 (100 nF) 10 pcs.**
  100 nF covers menu-button debounce, decoupling, and per-rail
  ceramic shunts.

### Discrete sensors and trimmers

- **Precision potentiometer** (ELEGOO) — **1 pc**.
- **Thermistor** (ELEGOO) — **1 pc**.
- **Photoresistor** (ELEGOO) — **2 pcs**.

## LEDs and indicators

- **5 mm LEDs, mixed colors** — **~100 pcs total**. WayinTop 50 pcs
  (red, yellow, blue, green, white × 10 each) + ELEGOO 50 pcs
  (same 5 colors × 10 each). Covers power-good indicators per
  [next-revision: power-good LEDs](next-revision.md).
- **RGB LED** (5 mm, common-cathode) — **1 pc** (ELEGOO kit).
- **Active buzzer** (3 V, 12095 piezo) — **10 pcs**.
- **Active buzzer + passive buzzer** (ELEGOO) — **1 pc each**.

## Connectors and headers

- **Pin headers, 2.54 mm** — WayinTop 26 pc kit (M, F, dual-row,
  right-angle) + ELEGOO 40-pin headers × 2.
- **XH2.54 connector kit** (M / F shells + crimps, 2–10 pin) —
  **1330 pc kit**.
- **Dupont 2.54 mm connector kit** (M / F crimps + shells) —
  **620 pc kit**.
- **Dupont jumper wires** (20 cm, M-M / M-F / F-F) — **120 pcs**.
- **KF2510 4-pin right-angle header** — **20 pcs**.
- **KF301 5 mm PCB screw terminal block, 2P** — **20 pcs**.
- **5 mm PCB screw terminal block, 2P / 3P** — **15 pcs** (WayinTop
  kit, 10 × 2P + 5 × 3P).
- **Tactile switch, 12 × 12 × 7.3 mm** — **12 pcs** (WayinTop,
  6 cap colors). Covers reset / menu button slots per
  [next-revision: button connector rework](next-revision.md).
- **Tactile button** (ELEGOO) — **10 pcs**.

## Prototyping / mechanical

- **PCB prototype boards** (2.54 mm pitch, 4×6 / 3×7 / 4×69 /
  5×7 / 7×9 / 8×12 cm) — **19 pcs total**.
- **Breadboard** — **1 pc** (ELEGOO).
- **DIP IC socket kit** (6 / 8 / 14 / 16 / 18 / 20 / 24 / 28 pin) —
  **66 pcs**. Includes DIP-8 for the LM358N (DIP variant) on
  protoboards.
- **Nylon spacers** (M3.2, OD 7 mm, 6 mm length, unthreaded) —
  **50 pcs**.
- **M3 brass hot-melt inserts** (OD 4.5 mm, 6 mm length, double-twill
  knurl for injection / heat-press into plastic) — **30 pcs**. For
  threading the 3D-printed enclosure to take M3 screws.
- **M3 hex brass standoff** (M / F, 6 mm thread + 6 mm body) —
  **30 pcs**. PCB-to-enclosure mounting.
- **Laptop screw set** (M2 / M2.5 / M3, 12 sizes) — **360 pcs**.
- **Tiny magnets** (6 × 2 mm) — **100 pcs**.

## Tools and consumables

- Soldering iron tips (900M lead-free, 11-pc kit) — **1 set**.
- Diagonal wire cutters / flush nippers — **5 pcs**.
- Deburring tool set (11-pc) — **1 set**.
- RJ45 / RJ11 crimper — **1 pc**.
- 3D-printer grease — **3 tubes**.
- Hot glue sticks (black, 7 × 100 mm) — **20 pcs**.
- Cyanoacrylate glue 401 (20 ml) — **3 bottles**.

---

## Comparison with [next-revision.md](next-revision.md) — to order

Exact part-number matching. Where a queued change names a specific
part, the entry below counts as "in stock" only when that exact part
is on the shelf. Functional substitutes are flagged separately
("substitute on hand, not fab-ready").

### Must order before next fab run

Quantities include design needs plus a small spares pool sized for
the expected pack size on AliExpress (typically 5 or 10 pcs per
pack). Unit costs are **rough budgeting estimates** based on
AliExpress small-quantity pricing in EUR; subtotals are
`qty × unit` rounded to €0.10. Use this list to size the order, not
as a purchase quotation.

| # | Part | Qty to order | Est. unit (€) | Est. subtotal (€) | Source |
| - | --- | --- | --- | --- | --- |
| 1 | **MCP1416T-E/OT** (SOT-23-5, gate driver) | 5 (1 + 4 spare) | 0.40 | 2.00 | [MCP1416 gate driver](next-revision.md) |
| 2 | **MBR20100CT** (TO-220, 20 A / 100 V Schottky) for D5 | 3 (1 + 2 spare) | 0.80 | 2.40 | [Schottky plan](next-revision.md) |
| 3 | **MBRD1045** (D-PAK, 10 A / 45 V Schottky) for D1–D4, D6 | 10 (5 + 5 spare) | 0.45 | 4.50 | [Schottky plan](next-revision.md) |
| 4 | **SS14** (SMA, 1 A / 40 V Schottky) for VBUS + DEBUG_CON | 10 (2 + 8 spare) | 0.06 | 0.60 | [VBUS + DEBUG_CON backfeed](next-revision.md) |
| 5 | **10 A T (slow-blow) 5×20 mm fuse** (e.g. Littelfuse 0234010.MXP) | 5 (1 + 4 spare) | 0.50 | 2.50 | [F1 fuse](next-revision.md) |
| 6 | **SMAJ5.0CA** (TVS, 5 V bidirectional) | 3 (1 + 2 spare) | 0.15 | 0.50 | [TVS on all three rails](next-revision.md) |
| 7 | **SMAJ15CA** (TVS, 12 V bidirectional) | 3 (1 + 2 spare) | 0.15 | 0.50 | [TVS on all three rails](next-revision.md) |
| 8 | **SMAJ24CA** (TVS, 19.5 V bidirectional) | 3 (1 + 2 spare) | 0.15 | 0.50 | [TVS on all three rails](next-revision.md) |
| 9 | **1000 µF / 16 V** low-ESR electrolytic (5 V VSYS bulk) | 3 (1 + 2 spare) | 0.30 | 0.90 | [5 V VSYS bulk cap upgrade](next-revision.md) |
| 10 | **220 µF / 25 V** low-ESR electrolytic (12 V bulk) | 3 (1 + 2 spare) | 0.20 | 0.60 | [bulk capacitance](next-revision.md) |
| 11 | **470 µF / 35 V** low-ESR electrolytic (19.5 V bulk) | 3 (1 + 2 spare) | 0.40 | 1.20 | [bulk capacitance](next-revision.md) |
| 12 | **MAX809LEUR+T** or **TPS3839K33** (SOT-23-3, ~3.0 V reset supervisor) | 3 (1 + 2 spare) | 0.30 | 0.90 | [brownout supervisor](next-revision.md) |
| 13 | **Fischer SK 104-25 STS** (TO-220 clip-on heatsink) | 2 (1 heater MOSFET + 1 spare; add 1 per fan-stage TO-220) | 0.50 | 1.00 | [TO-220 thermal management](next-revision.md) |
| 14 | **PCA9685** 16-ch PWM driver (breakout preferred for socketing) | 2 (1 + 1 spare) | 3.50 | 7.00 | [fans → PCA9685 + IRLZ44N](next-revision.md) |
| 15 | **1N4007** (or UF4007) flyback diodes for fan stage | 10 (5 fans + 5 spare; ELEGOO kit has 5 only) | 0.05 | 0.50 | [fans → PCA9685 + IRLZ44N](next-revision.md) |
| 16 | **Banana plug PCB jacks** (12 V and 19.5 V rails) | 4 (2 pairs red + black) | 1.00 | 4.00 | [external power connectors](next-revision.md) |
| 17 | **15 kΩ** ±1 % 1/4 W resistor (soil-ADC divider top leg) | 20 (pack) | 0.02 | 0.40 | [ADC / soil-moisture interface](next-revision.md) |
| 18 | **1.5 kΩ** ±1 % 1/4 W resistor (5 V power-good LED) | 20 (pack) | 0.02 | 0.40 | [power-good LEDs](next-revision.md) |
| 19 | **8.2 kΩ** ±1 % 1/4 W resistor (19.5 V power-good LED) | 20 (pack) | 0.02 | 0.40 | [power-good LEDs](next-revision.md) |
| 20 | **Dielectric grease** (small tube, RJ12 plug sealing) | 1 | 5.00 | 5.00 | [sensor cable moisture protection](next-revision.md) |
| 21 | **Silicone-insulated hookup wire** (~20 AWG) | ~5 m total | 1.50/m | 7.50 | [sensor cable moisture protection](next-revision.md) |
| 22 | **Desiccant sachets** (1 g) | 5 (one per sensor breakout enclosure) | 0.50 | 2.50 | [sensor cable moisture protection](next-revision.md) |
| 23 | **Adafruit 4682** (Micro SD SPI/SDIO 3V breakout) | 2 (1 + 1 spare) | 4.50 | 9.00 | [SD card module → Adafruit 4682](next-revision.md) |
| 24 | **100 µF / 10 V** low-ESR electrolytic (SD 3V3 decoupling at 4682 pad) | 5 (1 + 4 spare) | 0.10 | 0.50 | [SD card module → Adafruit 4682](next-revision.md) |
| | **Grand total (estimate)** | | | **~€ 54.80** | |

### Substitute on hand, not fab-ready

- **1N5822** (DO-27 axial, 3 A / 40 V Schottky) — **not** a substitute
  for MBRD1045 on the fabricated board (wrong package, half the
  current rating). Useable on protoboards for sub-3 A bench rigs only.

### In stock, covered by next-revision

| Queued change | Part on hand |
| --- | --- |
| Heater channel + future fan stage MOSFET | IRLZ44N × 10 |
| Power input → XT60 on all three rails | XT60PW-F × 5 + XT60 bullet × 5 pairs |
| F1 fuse holder (PCB) | 5×20 mm PCB fuse holder × 10 (+ 10 spiral) |
| Heater element (parallel-heater option) | 24 V / 100 W polyimide pad × 3 |
| MCP4725 DAC (grow-light) | MCP4725A0T × 10 + breakout × 1 |
| OLED display | SSD1306 0.96" × 2 |
| RJ12 silkscreen rename + second outward jack | 6P6C PCB jack × 30 + 6P4C double-port × 10 + 6P4C plug × 50 |
| Button rework (menu + reset) | tactile switch × 12 + button × 10 |
| Menu-button debounce cap | ceramic 100 nF (104) × 10 |
| I²C pull-up retune to 2.2 kΩ | 2.2 kΩ × 20 (WayinTop kit) |
| R3 buzzer pull-down → 10 kΩ | 10 kΩ × 30+ (WayinTop + ELEGOO) |
| R6 gate resistor 47 Ω | 47 Ω × 20 (WayinTop kit) |
| Power-good LEDs | 5 mm LEDs ×~100 |
| Soil-ADC divider bottom leg (10 kΩ) | 10 kΩ × 20 |
| Senseair S8 RX divider | 2.2 kΩ + 3.3 kΩ × 20 each |
| Grow-light op-amp (DIP-8 socket footprint) | LM358N DIP-8 × 10 + DIP-8 from 66-pc socket kit |
| Op-amp gain divider retune (R4 = 10 k, R5 = 4.7 k) | 10 kΩ + 4.7 kΩ × 20 each (WayinTop kit) |
| Heavy-duty mains distribution post-relay | 4-unit screw-terminal block "462d" |
| Enclosure-side AC mains entry | IEC320 C14 inlet (switch + LED + 10 A fuse) × 5 |
| 3D-printed enclosure threading | M3 brass hot-melt insert × 30 |
| PCB-to-enclosure mounting | M3 hex M/F standoff × 30 |
| SD-CS pull-up (10 kΩ to 3V3 on GP13) | 10 kΩ × 30+ (WayinTop + ELEGOO) |
| SD 3V3 decoupling — ceramic (100 nF) | ceramic 100 nF (104) × 10 |

---

## Sources (order trail)

Compact reference back to the original AliExpress / Amazon orders that
landed each item. Order numbers preserved for invoice cross-reference.

### AliExpress — 2026-04-15

- 3071545004877331 — 5×20 mm fuse holders ×10
- 3071545004897331 — XT60PW-F ×5
- 3071545004917331 — 5×20 mm fast-blow fuse kit (100 pcs)
- 3071545004937331 — IRLZ44N ×10
- 3071545004817331 — KF2510 4-pin right-angle header ×20
- 3071545004837331 — PPTC 250 V 0.3 A ×10
- 3071545004857331 — 1N5822 ×20

### AliExpress — 2026-04-12

- 3071396442817331 — XT60 bullet pair ×5
- 3071396442797331 — 3D printer grease ×3
- 3071396442837331 — laptop screw kit (360 pcs)
- 3071396442857331 — hot glue sticks ×20

### AliExpress — 2026-04-10

- 3071346276877331 — MCP4725A0T-E/CH ×10
- 3071195546147331 — MCP6002 SOIC-8 ×10
- 3071195546167331 — tiny magnets 6×2 mm ×100
- 3071191067167331 — LM358N DIP-8 ×10
- 3071191067187331 — MCP4725 breakout × 1
- 3071191067207331 — DIP IC socket kit (66 pcs)

### AliExpress — 2026-04-07

- 3071008417197331 — cyanoacrylate glue 401 ×3
- 3071008417217331 — XH2.54 connector kit (1330 pcs)
- 3071008417237331 — RJ11 6P4C double-port jack ×10

### AliExpress — 2026-02-16

- 3068961230977331 — polyimide heater 100×100 mm 24 V 100 W ×3
- 3068961230997331 — 900M soldering tips ×11
- 3068961231017331 — M3.2 nylon spacers ×50
- 3068961231037331 — deburring tool set
- 3068961231057331 — wire cutters ×5

### AliExpress — 2026-02-15

- 3068920990147331 — Dupont jumper wire 20 cm (120 pcs)
- 3068920990357331 — SSD1306 OLED 0.96" ×2
- 3068920990377331 — capacitive soil moisture sensor ×10 (refunded)
- 3068920990167331 — RJ11 6P4C crystal head ×50
- 3068920990187331 — active buzzer 3 V ×10
- 3068920990037331 — KF301 5 mm screw terminal block 2P ×20
- 3068920990207331 — Dupont 2.54 mm connector kit (620 pcs)
- 3068920990057331 — RJ45 / RJ11 crimper tool
- 3068920990227331 — 4-pin PWM CPU fan extension ×10
- 3068920990077331 — 5×20 mm / 6×30 mm spiral fuse holder ×10
- 3068920990247331 — RJ11 6P6C PCB jack ×30
- 3068920990267331 — IEC320 C14 panel inlet (switch + LED + 10 A fuse holder, "AC-08A") ×5 + 5×20 mm 10 A glass fuse 10-pack ×2
- 3068920990317331 — heavy-duty screw terminal block "462d" ×4
- 3068920990097331 — M3 brass hot-melt insert (6 mm length) ×30 + M3 hex M/F standoff (6 mm + 6 mm) ×30
- 3068920990337331 — VEML7700 light sensor module ×5

### Amazon

- WayinTop double-sided PCB + 600-pc resistor kit + 26-pc pin header
  set + 15-pc 5 mm screw terminal + 50 LEDs + 12 tactile switches
- ELEGOO Electronic Fun Kit (200+ pieces: 74HC595, 4N35, PN2222 ×5,
  precision potentiometer, breadboard, jumper wires, active + passive
  buzzer, 5 button colors, thermistor, photoresistor ×2, electrolytic
  100 µF ×5 + 10 µF ×5, ceramic 22 pF ×10 + 100 nF ×10, RGB LED,
  red / yellow / blue / green / white LEDs ×10 each, resistors 10 Ω /
  100 Ω / 220 Ω / 330 Ω / 1 kΩ / 2 kΩ / 5.1 kΩ / 10 kΩ / 100 kΩ /
  1 MΩ ×10 each, 1N4007 ×5, 40-pin header ×2)
