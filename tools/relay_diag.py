"""Relay diagnostic tool — standalone Pico script.

Upload this file to the Pico via Thonny and run it directly (not via
main.py). It bypasses lib/relay.py, config.py, and all DI wiring so
the behavior observed is pure hardware + raw machine.Pin.

What it does, in order:

  1. Float-state probe. For each of the 7 wired relay GPIOs, configure
     the pin as Pin.IN with no pull and read its value. A pin that
     reads 0 here at boot is likely the cause of "relay clicks on at
     restart" — the line is floating low into the active-low input.

  2. Drive HIGH (off). Reconfigure each pin as Pin.OUT and write 1
     (relay module is active-low → HIGH = off).

  3. Per-relay sweep. For each relay in order: write LOW (on), dwell,
     write HIGH (off), gap, move to next. Listen for the click and
     watch the indicator LED on the relay module.

  4. All-on stress. Drive all 7 lines LOW simultaneously for one
     dwell. This catches power-rail brownouts that only show up when
     all coils are energized at once.

  5. All-off. Drive everything HIGH and leave it there.

Wiring reference (from config.py):

  REL_CON pin 2 → GP18 — fan_1
  REL_CON pin 3 → GP19 — fan_2
  REL_CON pin 4 → GP20 — growlight
  REL_CON pin 5 → GP21 — reserved_1
  REL_CON pin 6 → GP22 — reserved_2
  REL_CON pin 7 → GP26 — reserved_3
  REL_CON pin 8 → GP27 — reserved_4

The 8-channel relay module has one input (IN1 or IN8 depending on
module) not wired to the Pico — only 7 channels are driveable from
this board. If you have an 8th relay that needs testing, jumper its
IN line to a spare GPIO first.
"""

import time

from machine import Pin

# Dwell timings for the diagnostic only. Not in DEVICE_CONFIG because
# this script is a one-off bench tool, not part of the runtime path.
DWELL_S = 1.0      # how long each relay stays ON during sweep
GAP_S = 0.5        # quiet time between relays during sweep
STRESS_S = 2.0     # how long all relays stay ON during the stress phase

# (label, gpio_number) — order is the test order.
RELAYS = (
    ("fan_1       (REL_CON 2)", 18),
    ("fan_2       (REL_CON 3)", 19),
    ("growlight   (REL_CON 4)", 20),
    ("reserved_1  (REL_CON 5)", 21),
    ("reserved_2  (REL_CON 6)", 22),
    ("reserved_3  (REL_CON 7)", 26),
    ("reserved_4  (REL_CON 8)", 27),
)


def probe_float_state():
    print("=" * 60)
    print("Phase 1/5  Float-state probe (Pin.IN, no pull)")
    print("=" * 60)
    print("A pin reading 0 here will momentarily energize its relay")
    print("the instant it is configured as OUT before being driven HIGH.")
    print()
    for label, gp in RELAYS:
        p = Pin(gp, Pin.IN)
        v = p.value()
        marker = "  <-- floats LOW (likely cause of boot-click)" if v == 0 else ""
        print("  GP{:>2}  {}  raw={}{}".format(gp, label, v, marker))
    print()


def drive_all_off():
    print("=" * 60)
    print("Phase 2/5  Configure as OUT, drive HIGH (all relays off)")
    print("=" * 60)
    pins = []
    for label, gp in RELAYS:
        # Pin() constructor with value=1 sets the latch BEFORE switching
        # direction to OUT — minimises the boot-glitch window.
        p = Pin(gp, Pin.OUT, value=1)
        pins.append((label, gp, p))
        print("  GP{:>2}  {}  driven HIGH".format(gp, label))
    print()
    return pins


def sweep(pins):
    print("=" * 60)
    print("Phase 3/5  Per-relay sweep ({:.1f}s ON, {:.1f}s gap)".format(DWELL_S, GAP_S))
    print("=" * 60)
    for label, gp, p in pins:
        print("  GP{:>2}  {}  ON  ...".format(gp, label), end="")
        p.value(0)  # LOW = on (active-low module)
        time.sleep(DWELL_S)
        p.value(1)  # HIGH = off
        print("  OFF")
        time.sleep(GAP_S)
    print()


def all_on_stress(pins):
    print("=" * 60)
    print("Phase 4/5  All-on stress ({:.1f}s)".format(STRESS_S))
    print("=" * 60)
    print("  Listen for brownout, watch for Pico reset.")
    for _, _, p in pins:
        p.value(0)
    time.sleep(STRESS_S)
    for _, _, p in pins:
        p.value(1)
    print("  done")
    print()


def main():
    print()
    print("Pi Greenhouse — relay diagnostic")
    print("Time: {}".format(time.ticks_ms()))
    print()
    probe_float_state()
    pins = drive_all_off()
    sweep(pins)
    all_on_stress(pins)
    print("=" * 60)
    print("Phase 5/5  Done. All relays left in OFF state (HIGH).")
    print("=" * 60)


if __name__ == "__main__":
    main()
