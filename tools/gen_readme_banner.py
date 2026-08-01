# README banner generator - the project's identity strip
# Dennis Hiro, 2026-08-01
#
# Renders docs/images/banner-light.svg and docs/images/banner-dark.svg: a
# 1280x290 strip carrying the wordmark beside a slice of the engine's own
# output. GitHub picks between the pair with a <picture> element keyed on
# prefers-color-scheme (see the top of readme.md).
#
# THIS FILE IS THE SOURCE OF TRUTH for the banner. The field is sampled from
# the LIVE exhaust surface in config.py through the shipped evaluator, not
# from baked numbers, so a deliberate surface retune changes the banner too --
# regenerate after one, the same way the golden vectors get regenerated.
#
# Every colour is a Pi Greenhouse design-system token (grow green ramp, bloom
# magenta as the single accent). Type is a monospace stack: GitHub cannot
# fetch a webfont for an SVG, and the design system already treats monospace
# as the voice that carries data.
#
# Usage (from the repo root, with the project venv active):
#     python tools/gen_readme_banner.py
#     python tools/gen_readme_banner.py --outdir some/other/dir
#
# Host-only. Never imported by device code; needs no third-party packages.

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import DEVICE_CONFIG  # noqa: E402
from lib.regulation_surface import evaluate, freeze_surface  # noqa: E402

DEFAULT_OUTDIR = Path("docs/images")

W, H = 1280, 290

# ---------------------------------------------------------------------------
# Design-system tokens
# ---------------------------------------------------------------------------
# Grow-green sequential ramp, seven stops, low -> high duty.
GROW = ["#0c3d22", "#135731", "#1f8a4c", "#25a65b", "#4cbf7a", "#7ad6a0", "#d6f1e0"]
BLOOM = "#db2a8a"  # the single accent; spent once, on the ideal column

DARK = {
    "ground": "#05080a",
    "fg1": "#eef3f2",
    "fg2": "#9fb0ad",
    "fg3": "#6c7c7a",
    "rule": "#232a2c",
    "rule_strong": "#333c3e",
}
LIGHT = {
    "ground": "#eceee9",
    "fg1": "#14181b",
    "fg2": "#5b6770",
    "fg3": "#7e8b93",
    "rule": "#d9ddd6",
    "rule_strong": "#c3ccd1",
}

MONO = "ui-monospace,'Cascadia Mono','SF Mono',Menlo,Consolas,'DejaVu Sans Mono',monospace"

# ---------------------------------------------------------------------------
# The sampled field
# ---------------------------------------------------------------------------
# 21 columns of temperature deviation (0..100 step 5) by six rows of humidity
# deviation (50..75 step 5) -- the band just above ideal humidity, where the
# exhaust surface is actually doing something interesting.
REGULATOR = "exhaust"
COL_DEVS = [float(v) for v in range(0, 101, 5)]
ROW_DEVS = [50.0, 55.0, 60.0, 65.0, 70.0, 75.0]
IDEAL_DEV = 50.0


def sample_field():
    """Sample the live exhaust surface as field[row][col].

    The regulator's ``dims`` decides which deviation is the evaluator's x and
    which is its y. Reading it rather than assuming keeps a config reordering
    from silently transposing the banner's axis label.
    """
    reg = DEVICE_CONFIG["regulation"]["regulators"][REGULATOR]
    dims = list(reg["dims"])
    if dims != ["temp", "humidity"]:
        raise SystemExit(
            f"{REGULATOR}.dims is {dims}, expected ['temp', 'humidity'] -- "
            "the banner's axis labels would be wrong; update this generator."
        )
    params = freeze_surface(reg["surface"])
    # x = temperature deviation (across), y = humidity deviation (down).
    return [[evaluate(params, col, row) for col in COL_DEVS] for row in ROW_DEVS]


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mono_w(text: str, size: float, ls: float = 0.0) -> float:
    """Advance width of monospace text: 0.6em per glyph, plus tracking."""
    return len(text) * (size * 0.6 + ls)


def txt(x, y, s, size, fill, ls=0.0, weight=400, anchor="start") -> str:
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    tracking = f' letter-spacing="{ls}"' if ls else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{MONO}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}"{tracking}{a}>{esc(s)}</text>'
    )


def ramp(value: float, dark: bool) -> str:
    """Map a 0-100 duty onto the grow ramp.

    On the dark ground low duty is deep green and high duty is pale (more duty
    reads as more light); on paper that inverts, so more ink means more duty.
    Quantising to the nearest stop keeps the field reading as discrete cells.
    """
    stops = GROW if dark else list(reversed(GROW))
    t = max(0.0, min(100.0, value)) / 100.0 * (len(stops) - 1)
    i = int(t)
    if i >= len(stops) - 1:
        return stops[-1]
    return stops[i + 1] if (t - i) > 0.5 else stops[i]


def render(field, dark: bool) -> str:
    """Render one banner. ``field`` is field[row][col] of 0-100 duties."""
    t = DARK if dark else LIGHT
    p: list[str] = []

    # ── identity block ────────────────────────────────────────────────────
    name, size, ls = "PI GREENHOUSE", 34, 5.5
    p.append(txt(64, 118, name, size, t["fg1"], ls=ls, weight=600))
    p.append(f'<rect x="64" y="135" width="{mono_w(name, size, ls) - ls:.1f}" height="1" fill="{t["rule_strong"]}"/>')
    p.append(txt(64, 159, "CLOSED-LOOP GROW CONTROL", 12, t["fg2"], ls=2.2))
    p.append(txt(64, 186, "RASPBERRY PI PICO  ·  MICROPYTHON", 11.5, t["fg3"], ls=1.8))
    p.append(txt(64, 206, "7 ACTUATORS  ·  30 s TICK", 11.5, t["fg3"], ls=1.8))

    # ── the field ─────────────────────────────────────────────────────────
    gx, gy, cw, ch = 556, 68, 32, 27
    cols, rows = len(COL_DEVS), len(ROW_DEVS)
    gw, gh = cols * cw - 1.5, rows * ch - 1.5

    p.append(f'<rect x="{gx - 28}" y="0" width="1" height="{H}" fill="{t["rule"]}"/>')
    p.append(txt(gx, 40, "EXHAUST · FINAL EFFECTIVE DUTY", 10.5, t["fg3"], ls=2))

    for r, row in enumerate(field):
        for c, value in enumerate(row):
            p.append(
                f'<rect x="{gx + c * cw}" y="{gy + r * ch}" width="{cw - 1.5}" '
                f'height="{ch - 1.5}" fill="{ramp(value, dark)}"/>'
            )

    # The ideal column: the one idea the whole engine turns on, and the only
    # place the accent is spent.
    ideal_col = COL_DEVS.index(IDEAL_DEV)
    ix = gx + ideal_col * cw + (cw - 1.5) / 2
    p.append(f'<rect x="{ix - 0.75:.1f}" y="{gy - 14}" width="1.5" height="{gh + 14:.1f}" fill="{BLOOM}"/>')
    p.append(txt(ix, 40, "50 · IDEAL", 10, BLOOM, ls=1.6, anchor="middle"))

    ay = gy + gh + 20
    p.append(txt(gx, ay, "0", 10, t["fg3"]))
    p.append(txt(gx + gw, ay, "100", 10, t["fg3"], anchor="end"))
    p.append(txt(gx + gw / 2, ay + 17, "TEMPERATURE DEVIATION", 10, t["fg3"], ls=2, anchor="middle"))
    p.append(txt(gx + gw, ay + 17, "HUMIDITY DEV 50-75", 10, t["fg3"], ls=1.2, anchor="end"))

    label = "Pi Greenhouse - closed-loop grow control for the Raspberry Pi Pico"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}" role="img" aria-label="{esc(label)}">'
        f"<title>{esc(label)}</title>"
        f'<rect width="{W}" height="{H}" fill="{t["ground"]}"/>'
        f"{''.join(p)}</svg>"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the Pi Greenhouse README banner pair.")
    ap.add_argument(
        "--outdir", type=Path, default=DEFAULT_OUTDIR, help=f"directory for the SVG pair (default: {DEFAULT_OUTDIR})"
    )
    args = ap.parse_args()

    field = sample_field()
    args.outdir.mkdir(parents=True, exist_ok=True)
    for theme, dark in (("light", False), ("dark", True)):
        path = args.outdir / f"banner-{theme}.svg"
        path.write_text(render(field, dark), encoding="utf-8")
        print(f"{path}  ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
