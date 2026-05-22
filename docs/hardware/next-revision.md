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

> (none queued yet)

## Wiring / harness

> (none queued yet)
