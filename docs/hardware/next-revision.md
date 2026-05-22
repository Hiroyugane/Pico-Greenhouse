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

> (none queued yet)
