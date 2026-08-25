# Case legend PDF generator - printable operator quick-reference
# Dennis Hiro, 2026-07-21
#
# Renders docs/hardware/case-legend.pdf: a two-page, 160x60 mm landscape
# strip meant to be printed and glued to the controller enclosure.
# Page 1 = how it works + OLED screens; page 2 = wiring map + fault first aid.
#
# THIS FILE IS THE SOURCE OF TRUTH for the printed legend. The CONTENT
# structure below is the copy; everything under "rendering" is layout only.
# When operator-visible behaviour changes (OLED pages/fields, relay or PWM
# channel assignment, LED policy, alert keys, button timings), edit CONTENT
# here, bump LEGEND_REV, and regenerate (see the case-legend convention in CLAUDE.md).
#
# Usage (from the repo root, with the project venv active):
#     python tools/gen_case_legend.py
#     python tools/gen_case_legend.py --output some/other.pdf
#
# Requires reportlab (dev-only dependency, see requirements.txt).

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------------------
# Revision stamp
# ---------------------------------------------------------------------------
# Bump this date whenever CONTENT changes, so a legend glued to the case can
# be compared against the repo without diffing the PDF.
LEGEND_REV = "2026-08-25"

DEFAULT_OUTPUT = Path("docs/hardware/case-legend.pdf")

# ---------------------------------------------------------------------------
# Page geometry (160 x 60 mm landscape, three columns)
# ---------------------------------------------------------------------------
PAGE_W = 160 * mm
PAGE_H = 60 * mm
MARGIN_X = 4 * mm
MARGIN_TOP = 3.2 * mm
MARGIN_BOTTOM = 3.0 * mm
GUTTER = 3.5 * mm
COLUMNS = 3
COL_W = (PAGE_W - 2 * MARGIN_X - (COLUMNS - 1) * GUTTER) / COLUMNS

TITLE_SIZE = 6.4
HEAD_SIZE = 5.0
BODY_SIZE = 4.3
LEADING = 5.2
HEAD_GAP = 1.4  # extra space above a section head
KEY_W = 15.5 * mm  # left column width inside a key/value row

INK = HexColor("#000000")
MUTED = HexColor("#555555")
RULE = HexColor("#999999")

# ---------------------------------------------------------------------------
# CONTENT - the printed copy. Edit here, not in the renderer.
# ---------------------------------------------------------------------------
# Each page is a list of three columns; each column is a list of blocks.
# Block kinds:
#   ("head", "SECTION TITLE")
#   ("text", "a paragraph, wrapped automatically")
#   ("kv",   [("key", "value"), ...])   two-column rows
#   ("gap",  None)                      a half blank line

PAGE1 = [
    # ---- column 1 -------------------------------------------------------
    [
        ("head", "WHAT IT DOES"),
        (
            "text",
            "Keeps the tent at the target climate for the selected grow "
            "profile. Every 30 s it reads temperature, humidity and CO2, "
            "scores how far each is off ideal (0-100, 50 = on target), and "
            "commands all actuators at once from that score.",
        ),
        (
            "text",
            "Sensor and event data is written to the SD card; if the card is "
            "missing it falls back to internal flash, then to RAM, and "
            "migrates the backlog once the card returns.",
        ),
        ("gap", None),
        ("head", "BUTTON"),
        (
            "kv",
            [
                ("Tap", "next screen"),
                ("Hold 3 s", "screen action"),
                ("Idle 30 s", "back to screen 1"),
                ("Idle 120 s", "display sleeps"),
                ("Any press", "wakes display"),
            ],
        ),
        ("gap", None),
        ("head", "PHASENWECHSEL (grow phase)"),
        (
            "text",
            "The grow phase advances on its own after so many weeks. The "
            "screen then shows PHASENWECHSEL with the new humidity target, "
            "the new light level, and whether the humidifier still runs.",
        ),
        (
            "text",
            "It stays up until you press the button - through sleep and "
            "power cuts - and the Service LED stays on until you do. The "
            "first press on a dark screen only wakes it; press again to "
            "confirm.",
        ),
    ],
    # ---- column 2 -------------------------------------------------------
    [
        ("head", "OLED SCREENS (tap to cycle)"),
        (
            "kv",
            [
                ("TEMPERATURE", "now/hi/lo/avg, 1 h. Hold = clear"),
                ("HUMIDITY", "now/hi/lo/avg, 1 h. Hold = clear"),
                ("SERVICE", "days since service. Hold = reset"),
                ("SD CARD", "mount state + MB. Hold = remount"),
                ("ALERTS", "active ERR/WRN keys, or All OK"),
                ("SYSTEM", "clock, firmware, uptime, RAM"),
                ("RELAYS", "mains channels + PWM fan duty"),
                ("REGULATION", "title = grow phase; band, commands"),
                ("CO2", "ppm + vent override"),
                ("SOIL", "moisture % + root temperature"),
                ("DEBUG", "Hold = open test menu"),
            ],
        ),
    ],
    # ---- column 3 -------------------------------------------------------
    [
        ("head", "REGULATION SCREEN"),
        (
            "text",
            "Title  REG bloom  -  the grow phase now running (seedling / "
            "stretch / bloom). Plain REGULATION means no phase plan.",
        ),
        (
            "text",
            "Line 1  Band 2 ok  -  severity band, and mode: ok / EMERG "
            "(emergency vector) / LATCHED (held in safe state, needs a "
            "power cycle or a fixed climate to clear).",
        ),
        (
            "kv",
            [
                ("T H C", "deviation temp / humidity / CO2"),
                ("", "0 = far low, 50 = ideal, 100 = far high"),
            ],
        ),
        ("gap", None),
        ("text", "Lines 3-5 are commanded output, 0-100 %:"),
        (
            "kv",
            [
                ("He", "heater"),
                ("Fo", "heater follower fan"),
                ("Cl", "cooler"),
                ("Hu", "humidifier"),
                ("Ex", "exhaust fan"),
                ("Ci", "circulation fans"),
                ("Gl", "grow light"),
                ("b", "day/night blend, 0 = night, 1 = day"),
            ],
        ),
    ],
]

PAGE2 = [
    # ---- column 1 -------------------------------------------------------
    [
        ("head", "MAINS RELAYS (REL_CON1)"),
        (
            "kv",
            [
                ("Cool GP18", "cooler / AC"),
                ("Humi GP19", "humidifier"),
                ("Lite GP20", "grow light (+ 0-10 V dimmer)"),
                ("Spar GP21", "spare, unassigned"),
            ],
        ),
        ("text", "Screen shows ON / OFF, or -- when the channel has no controller."),
        ("gap", None),
        ("head", "PWM FANS (PCA9685, 12 V)"),
        (
            "kv",
            [
                ("ch0", "circulation, centre"),
                ("ch1", "circulation, walls"),
                ("ch2", "heater follower"),
                ("ch3", "case fan, always on 60 %"),
                ("ch4", "exhaust"),
            ],
        ),
    ],
    # ---- column 2 -------------------------------------------------------
    [
        ("head", "STATUS LEDS"),
        (
            "kv",
            [
                ("Activity", "blinks on each read/write"),
                ("SD", "off = mounted, solid = no card,"),
                ("", "blink = card present but unreadable"),
                ("Warning", "solid = degraded, still running"),
                ("Error", "solid = fault, needs attention"),
                ("Service", "blinks when service is due"),
                ("Pico LED", "heartbeat, firmware is alive"),
            ],
        ),
        ("gap", None),
        ("head", "SENSORS"),
        (
            "kv",
            [
                ("SHT31-D", "temperature + humidity, I2C"),
                ("Senseair S8", "CO2 ppm, UART"),
                ("DS3231", "real-time clock, I2C"),
                ("Soil STEMMA", "moisture + root temp, I2C"),
            ],
        ),
        ("gap", None),
        # Moved here from column 3: the alert-key list outgrew its column when
        # the intake-sensor, clock-hold and task-leak keys were added.
        ("head", "FIRST AID"),
        (
            "kv",
            [
                ("PHASENWECHSEL", "not a fault; press to confirm"),
                ("SD LED on", "reseat the card, then SD screen, hold"),
                ("LATCHED", "fix climate, then power cycle"),
                ("Blank screen", "tap the button; it sleeps at 120 s"),
                ("Nothing runs", "check 12 V input and the fuse"),
            ],
        ),
    ],
    # ---- column 3 -------------------------------------------------------
    [
        ("head", "ALERT KEYS (ALERTS screen)"),
        (
            "kv",
            [
                ("ERR sd_required", "SD needed but unavailable"),
                ("ERR th_dead", "climate sensor not answering"),
                ("ERR mem_error", "RAM critically low"),
                ("ERR logged_error", "see system.log on the SD card"),
                ("WRN th_intermit", "sensor dropping reads"),
                ("WRN fallback_act", "logging to flash, not SD"),
                ("WRN buffer_backlog", "writes queueing up"),
                ("WRN mem_warn", "RAM above warn level"),
                ("WRN rtc_invalid", "clock time implausible"),
                ("WRN co2_stale", "CO2 reading too old; timed venting"),
                ("WRN co2_unreach", "CO2 sensor silent; check its plug"),
                ("WRN sht31_unreach", "climate sensor silent; check its plug"),
                ("WRN humidifier_in", "humidifier runs, air stays dry: refill it"),
                ("WRN rh_target_unr", "room air too humid for the target"),
                ("WRN soil_unreach", "soil probe silent; check its plug"),
                ("WRN root_temp_low", "root zone under 20 C"),
                ("WRN root_temp_hig", "root zone over 26 C"),
                ("WRN ext_sht31_unr", "intake air sensor silent; check its plug"),
                ("WRN rtc_phase_held", "clock date wrong, grow phase frozen:"),
                ("", "replace the clock battery and set the time"),
                ("WRN task_leak", "a background job stopped; power cycle"),
            ],
        ),
    ],
]

PAGES = [
    ("PI GREENHOUSE  -  OPERATOR LEGEND", PAGE1),
    ("PI GREENHOUSE  -  WIRING & FAULTS", PAGE2),
]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _wrap(c: canvas.Canvas, text: str, width: float, font: str, size: float) -> list[str]:
    """Greedy word wrap against the real string width of `font` at `size`."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if c.stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_column(c: canvas.Canvas, blocks, x: float, top: float, width: float) -> None:
    y = top
    for kind, payload in blocks:
        if kind == "gap":
            y -= LEADING * 0.5
            continue

        if kind == "head":
            y -= HEAD_GAP
            c.setFont("Helvetica-Bold", HEAD_SIZE)
            c.setFillColor(INK)
            c.drawString(x, y, payload)
            y -= 1.1 * mm
            c.setStrokeColor(RULE)
            c.setLineWidth(0.25)
            c.line(x, y, x + width, y)
            y -= LEADING * 0.75
            continue

        if kind == "text":
            c.setFont("Helvetica", BODY_SIZE)
            c.setFillColor(INK)
            for line in _wrap(c, payload, width, "Helvetica", BODY_SIZE):
                c.drawString(x, y, line)
                y -= LEADING
            continue

        if kind == "kv":
            value_x = x + KEY_W
            value_w = width - KEY_W
            for key, value in payload:
                c.setFont("Helvetica-Bold", BODY_SIZE)
                c.setFillColor(INK)
                c.drawString(x, y, key)
                c.setFont("Helvetica", BODY_SIZE)
                c.setFillColor(MUTED if not key else INK)
                value_lines = _wrap(c, value, value_w, "Helvetica", BODY_SIZE)
                for i, line in enumerate(value_lines):
                    c.drawString(value_x, y - i * LEADING, line)
                y -= LEADING * max(1, len(value_lines))
            continue

        raise ValueError(f"unknown block kind: {kind!r}")

    if y < MARGIN_BOTTOM:
        overflow_mm = (MARGIN_BOTTOM - y) / mm
        raise SystemExit(
            f"case legend overflows the page by {overflow_mm:.1f} mm - "
            "shorten CONTENT or move a block to the other page"
        )


def build(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Pi Greenhouse - case legend")
    c.setAuthor("Pi Greenhouse")

    for page_index, (title, columns) in enumerate(PAGES):
        y = PAGE_H - MARGIN_TOP - TITLE_SIZE * 0.35

        c.setFont("Helvetica-Bold", TITLE_SIZE)
        c.setFillColor(INK)
        c.drawString(MARGIN_X, y, title)

        stamp = f"rev {LEGEND_REV}   {page_index + 1}/{len(PAGES)}"
        c.setFont("Helvetica", BODY_SIZE)
        c.setFillColor(MUTED)
        c.drawRightString(PAGE_W - MARGIN_X, y, stamp)

        y -= 1.5 * mm
        c.setStrokeColor(INK)
        c.setLineWidth(0.5)
        c.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)
        column_top = y - LEADING * 0.9

        for col_index, blocks in enumerate(columns):
            x = MARGIN_X + col_index * (COL_W + GUTTER)
            _draw_column(c, blocks, x, column_top, COL_W)

        c.showPage()

    c.save()
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the printable case legend PDF.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output PDF path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    path = build(args.output)
    print(f"wrote {path} (rev {LEGEND_REV}, {len(PAGES)} pages, 160x60 mm landscape)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
