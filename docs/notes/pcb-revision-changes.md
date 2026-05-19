# PCB revision changes

> Rolling list of physical changes required on the next PCB spin
> (post-`SCH_Pico-Greenhouse-PCB_2026-05-14`). Each entry is a
> change that **cannot be fixed in firmware** and must land on the
> board itself. Companion to
> [`2026-05-14-pcb-codebase-gap-plan.md`](2026-05-14-pcb-codebase-gap-plan.md)
> (which tracks firmware gaps against the current board) and
> [`chat-log.md`](chat-log.md) (decisions and context).
>
> Format per entry:
>
> - **Status** — `pending`, `confirmed`, `done-on-next-rev`,
>   `mitigated-in-fw`.
> - **Source** — what diagnostic / log / chat entry produced the
>   finding.
> - **Net / refdes** — schematic net name and any affected
>   reference designators.
> - **Change** — exactly what to add/remove/modify.
> - **Why** — observed symptom and root-cause analysis.
> - **Firmware workaround** — what (if anything) the firmware does
>   today to mitigate, and what it can't cover.

Newest entry on top.

## 2026-05-19 · Remove R8 (MISO series resistor on SD_CON)

- **Status:** done-on-current-board (R8 bypassed/removed); confirmed
  as the SD-failure root cause on the bench. Next PCB spin should
  delete the footprint from the schematic.
- **Source:** [`sd/logs/system.log`](../../sd/logs/system.log)
  field run 2026-05-16/18 (32× `SD status changed: FAILED` in 42 h);
  bench re-test 2026-05-19;
  [chat-log 2026-05-19 R8 entry](chat-log.md).
- **Net / refdes:** `SPI1_MISO` between `GP12` (Pico) and
  `SD_CON` pin 3. Affected refdes: **R8**.
- **Change:** remove R8 and bridge the pads (or replace with a
  0 Ω jumper). MISO becomes a direct trace from GP12 to SD_CON
  pin 3. R10 on MOSI stays — only MISO was implicated.
- **Why:** the series resistor on the SD-card's return path
  attenuated the read signal enough to produce intermittent SPI
  bit errors at 40 MHz, presenting as MBR read failures and
  forced re-mounts. Removing R8 made the link stable on the bench.
  R10 on MOSI never showed symptoms — likely because the Pico's
  output drive overcomes the series resistance on the forward
  path, while the SD card's output is the weaker driver on MISO.
- **Firmware workaround:** [`config.py:92-108`](../../config.py#L92-L108)
  drops `spi.baudrate` from 40 MHz to 10 MHz. This was originally
  shipped to mask the R8 symptom and is left in place as a
  precaution until the next bench session validates 40 MHz on the
  bypassed board. Once validated, bump the baudrate back in a
  separate commit. Watchdog / migrate-fallback resilience changes
  from the same 2026-05-19 session stay — they cover unrelated
  silent-reset paths.

## 2026-05-15 · Relay IN-line pull-ups (REL_CON pins 2–8)

- **Status:** pending
- **Source:** [`tools/relay_diag.py`](../../tools/relay_diag.py)
  bench run 2026-05-15;
  [`hw-test-log.md` 2026-05-15 entry](../test/hw-test-log.md);
  [chat-log 2026-05-15 relay-diag findings](chat-log.md).
- **Net / refdes:** all 7 wired REL_CON IN lines —
  `GP18` (REL_CON 2), `GP19` (REL_CON 3), `GP20` (REL_CON 4),
  `GP21` (REL_CON 5), `GP22` (REL_CON 6), `GP26` (REL_CON 7),
  `GP27` (REL_CON 8).
- **Change:** add a **10 kΩ pull-up resistor from each IN line to
  the relay module's VCC** (the rail that powers the opto LEDs on
  the relay board — typically 5V on a JD-VCC module). One resistor
  per line, 7 total. Place them as close to REL_CON as routing
  allows so they hold the line HIGH even with the Pico
  disconnected.
- **Why:** at hardware reset and during 3V3_EN cycling, the
  RP2040 GPIOs come up as high-impedance inputs with no internal
  pull engaged. The active-low relay module then sees a floating
  IN line, drifts below its logic-low threshold, and the relay
  latches ON before MicroPython can drive the pin HIGH.
  Diagnostic confirmed:
  - **GP27** persistently floats LOW (raw=0 in the float-state
    probe) — `reserved_4` clicks on at every reset.
  - **GP26** (and on some 3V3_EN cycles GP22) latch on
    transiently — the float-state probe shows raw=1 because by
    the time MicroPython runs the line has drifted back HIGH, but
    during the boot window it dipped low enough to fire the
    coil.
  - In REPL idle state (Pico booted, pins not configured by
    `main.py`) all 7 relay indicator LEDs glow dim — the canonical
    floating-input signature.
- **Firmware workaround:** [`config.py:296-304`](../../config.py#L296-L304)
  declares all relay pins inverted and [`lib/relay.py`](../../lib/relay.py)
  initialises them with `Pin(gp, Pin.OUT, value=1)` so they are
  driven HIGH as soon as MicroPython reaches that line. This
  closes the window from MicroPython startup onward but **cannot
  cover the hardware reset transient** (the ~hundreds of ms
  between 3V3_EN release and the firmware running) nor REPL idle
  state. Only an external pull-up fixes those.

## 2026-05-15 · REL_CON channel-1 wiring decision (8-channel module, 7 GPIOs)

- **Status:** pending — needs explicit decision before next spin.
- **Source:** [chat-log 2026-05-15 relay-diag findings](chat-log.md);
  user observation that "port 8 enables on 3V3_EN reset, tied to
  3V3".
- **Net / refdes:** REL_CON pin 1 / module IN1 (or IN8 depending
  on module variant — the unwired channel).
- **Change:** pick one and route it:
  1. **Leave unwired but tie to VCC via 10 kΩ pull-up at REL_CON
     pin 1**, so the unused channel is held off and cannot float.
     Simplest if we don't need the 8th channel.
  2. **Wire to a spare GPIO** (none currently free in the 18-27
     range — would require relocating another peripheral or using
     GP15, currently marked free since DHT22 moved to SHT31).
- **Why:** the user observed that the unwired channel activates
  during 3V3_EN reset. With nothing driving it the IN line sits at
  whatever voltage stray capacitance and the relay board's
  internal bias produce — sometimes below the active-low threshold.
  A direct strap to 3V3 was *intended* to hold it off, but the
  symptom suggests either the strap isn't actually connected or
  the module variant on the bench is active-HIGH on that channel
  (worth metering the IN1 pad at the relay board during a reset
  to settle which).
- **Firmware workaround:** none possible — the line has no GPIO
  to drive.

## How to use this file

- When a diagnostic, hardware test, or chat session uncovers a
  problem that needs board changes, add an entry here **in the
  same turn**.
- When the change is incorporated into a new schematic revision,
  flip the status to `done-on-next-rev` and add a one-line
  reference to the new schematic file.
- When a problem listed here turns out to be fixable in firmware
  after all, flip status to `mitigated-in-fw` and link the commit.
- Do not delete entries — historical revisions need the trail.
