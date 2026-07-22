#!/usr/bin/env python3
# Regulation explorer generator (HOST ONLY — never runs on the Pico).
#
# Renders the 3.5-D regulation matrix as a single self-contained HTML file:
# no server, no build step, no CDN. Everything the page needs (config values,
# the sampled raw surface grids, adapter blocks, profile anchors) is inlined as
# JSON and the browser reproduces stages 2-5 of the pipeline live so the CO2 and
# time-of-day sliders can move without a regenerate.
#
# The page is also a TUNING tool, not only a viewer: the surface hinge
# parameters, floors, CO2 gain/break, adapter thresholds, slew rates and band
# edges are all editable in the browser, the plot recomputes live, and the
# changed values export as a paste-ready config.py fragment.
#
# That means the surface evaluator has to exist in JS too — a grid baked in
# Python cannot respond to an edited slope. lib/regulation_surface.evaluate is
# therefore mirrored in evalSurface() below, which is a duplication and is
# treated as one: the Python-side grid is STILL baked in (as rawBaked, still
# checked against tests/golden/) and the page asserts on load that its own
# evaluator reproduces it. A port that drifts shows a banner instead of quietly
# plotting fiction.
#
# Everything else — the axis LABELS, the CO2 additive term, the growlight ToD
# value, and the conflict/floor/adapter stages — is cheap arithmetic mirrored in
# JS, because it depends on controls the page owns.
#
# Usage:
#   python prototypes/gen_regulation_explorer.py
#   python prototypes/gen_regulation_explorer.py --out some/other.html
#   python prototypes/gen_regulation_explorer.py --no-golden-check

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: E402
from config import DEVICE_CONFIG  # noqa: E402
from lib.regulation_surface import evaluate, freeze_surface  # noqa: E402

GOLDEN_DIR = _ROOT / "tests" / "golden"
DEFAULT_OUT = _ROOT / "prototypes" / "regulation_explorer.html"
GRID = list(range(0, 101, 5))  # 21 points per axis — same sampling as the goldens
GOLDEN_TOLERANCE = 1e-3

_DIM_UNITS = {"temp": "°C", "humidity": "%RH", "co2": "ppm"}
_DIM_LABELS = {"temp": "temperature", "humidity": "humidity", "co2": "CO₂"}


def _sample_surface(params):
    """Sample one frozen surface over the 21x21 deviation grid as raw[xi][yi]."""
    return [[evaluate(params, float(x), float(y)) for y in GRID] for x in GRID]


def _clamp(v, lo=0.0, hi=100.0):
    return lo if v < lo else (hi if v > hi else v)


def build_data():
    """Extract everything the page needs from DEVICE_CONFIG (read-only)."""
    reg_cfg = DEVICE_CONFIG["regulation"]
    regulators = reg_cfg["regulators"]
    dim_order = list(config._REG_DIMENSIONS)

    # Dimensions a regulator with no surface of its own is displayed against.
    # The follower's band dims in the arbiter are (temp, humidity) — the same
    # pair the heater's surface uses — and the growlight has none at all; it is
    # drawn on those axes purely so the grid has a frame. Derived from the
    # heater rather than hardcoded so a reordering of its dims cannot silently
    # transpose the follower's axis labels.
    fallback_dims = list(regulators["heater"]["dims"])

    # Raw surface grids, straight from the shipped evaluator. These stay the
    # golden-checked reference the page validates its own evaluator against;
    # once a parameter is edited in the browser the plot uses the JS grid.
    raw_grids = {}
    for name in config._REG_NAMES:
        r = regulators[name]
        if r["driven"] == "surface":
            raw_grids[name] = _sample_surface(freeze_surface(r["surface"]))

    # The heater_follower has no surface: its organic command is derived from
    # the heater's, exactly as RegulationEngine._compute_targets does it.
    follower = regulators["heater_follower"]
    f_gain = float(follower["follower_gain"])
    f_floor = float(follower["follower_floor"])
    heater_raw = raw_grids["heater"]
    raw_grids["heater_follower"] = [
        [_clamp(heater_raw[xi][yi] * f_gain + f_floor) for yi in range(len(GRID))] for xi in range(len(GRID))
    ]

    out_regs = {}
    for name in config._REG_NAMES:
        r = regulators[name]
        driven = r["driven"]
        dims = list(r["dims"]) if driven == "surface" else list(fallback_dims)

        # Band dims — what the arbiter's floor step measures severity over.
        # Mirrors RegulationArbiter.from_config: surface regulators use their
        # own dims (exhaust additionally gets co2), the follower uses
        # temp+humidity, and a tod regulator has none (band 0, floor never
        # forced).
        if driven == "surface":
            band_dims = list(r["dims"])
            if "co2_gain" in r and "co2" not in band_dims:
                band_dims.append("co2")
        elif driven == "follower":
            band_dims = ["temp", "humidity"]
        else:
            band_dims = []

        entry = {
            "driven": driven,
            "dims": dims,
            "bandDims": band_dims,
            "adapter": dict(r["adapter"]),
            "slewNormal": float(r["slew_normal"]),
            "slewFast": float(r["slew_fast"]),
            "floor": float(r["floor"]),
            "emergencyValue": r["emergency_value"],
            "safeState": r["safe_state"],
            "rawBaked": raw_grids.get(name),
        }
        if driven == "surface":
            # Full parameter dict (not just the overrides) so the page can
            # evaluate the surface itself and edit any knob.
            entry["surface"] = {k: float(v) for k, v in r["surface"].items()}
        if driven == "follower":
            entry["followerGain"] = f_gain
            entry["followerFloor"] = f_floor
        if driven == "tod":
            entry["lightLevelDay"] = float(r["light_level_day"])
            entry["dimmable"] = bool(r["dimmable"])
        if "co2_gain" in r:
            entry["co2Gain"] = float(r["co2_gain"])
            entry["co2Break"] = float(r["co2_break"])
            entry["external"] = bool(r["external"])
        out_regs[name] = entry

    conflicts = [
        {
            "when": [[dim, op, float(thresh)] for dim, op, thresh in rule["when"]],
            "force": {k: float(v) for k, v in rule.get("force", {}).items()},
            "prefer": {k: float(v) for k, v in rule.get("prefer", {}).items()},
        }
        for rule in reg_cfg["conflicts"]
    ]

    ext = reg_cfg["external_sensor"]
    band_edges = [float(e) for e in reg_cfg["band_edges"]]

    return {
        "grid": GRID,
        "dimOrder": dim_order,
        "dimUnits": _DIM_UNITS,
        "dimLabels": _DIM_LABELS,
        "regNames": list(config._REG_NAMES),
        "regulators": out_regs,
        "profiles": {
            name: {
                "category": p["category"],
                "day": {d: dict(p["day"][d]) for d in dim_order},
                "night": {d: dict(p["night"][d]) for d in dim_order},
            }
            for name, p in reg_cfg["profiles"].items()
        },
        "activeProfile": reg_cfg["profile"],
        # The arbiter derives its four named thresholds from the last four
        # edges, so the page recomputes them whenever the edges are edited.
        "bandEdges": band_edges,
        # Neutral surface defaults + editor metadata (name, range), straight
        # from config._SURFACE_PARAMS so the page's ranges cannot drift from the
        # validator's.
        "surfaceDefaults": {name: float(default) for name, _lo, _hi, default in config._SURFACE_PARAMS},
        "surfaceMeta": [
            {"name": name, "lo": float(lo), "hi": float(hi), "def": float(default)}
            for name, lo, hi, default in config._SURFACE_PARAMS
        ],
        "escalation": {d: dict(reg_cfg["escalation"][d]) for d in dim_order},
        "latch": dict(reg_cfg["latch"]),
        "conflicts": conflicts,
        "tickS": reg_cfg["tick_s"],
        "externalSensor": {
            "enabled": bool(ext["enabled"]),
            "fullDeltaC": ext["full_delta_c"],
            "minFactor": ext["min_factor"],
            "fullDeltaRh": ext["full_delta_rh"],
            "minFactorRh": ext["min_factor_rh"],
        },
    }


def check_goldens(data, tolerance=GOLDEN_TOLERANCE):
    """Assert the sampled raw grids equal the pinned golden vectors.

    The goldens are the blessed truth for the surface math; if this generator
    ever drifts from lib/regulation_surface.evaluate (or from the config the
    goldens were exported against) the page would be plotting fiction. Only
    surface-driven regulators have goldens — the follower and growlight derive
    their command from other stages.
    """
    checked = 0
    index = {v: i for i, v in enumerate(GRID)}
    for name, entry in data["regulators"].items():
        if entry["driven"] != "surface":
            continue
        path = GOLDEN_DIR / "regulation_{}.csv".format(name)
        raw = entry["rawBaked"]
        if not path.exists():
            # tests/golden/ is covered by a blanket *.csv rule in .gitignore, so
            # a fresh clone has none of these files. Say how to get them rather
            # than dying on a bare assertion.
            raise SystemExit(
                "golden vector missing for {}: {}\n"
                "tests/golden/*.csv is gitignored, so a fresh clone has none. Regenerate them with\n"
                "    python prototypes/plot_regulation_surfaces.py\n"
                "or skip this check with --no-golden-check.".format(name, path)
            )
        with open(path, encoding="utf-8") as fh:
            header = fh.readline().strip()
            if header != "x,y,out":
                raise AssertionError("{}: unexpected golden header {!r}".format(path.name, header))
            rows = 0
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                xs, ys, outs = line.split(",")
                x, y, expected = int(xs), int(ys), float(outs)
                if x not in index or y not in index:
                    raise AssertionError(
                        "{}: golden row (x={}, y={}) is off the {}-step sampling grid".format(
                            path.name, x, y, GRID[1] - GRID[0]
                        )
                    )
                got = raw[index[x]][index[y]]
                if abs(got - expected) > tolerance:
                    raise AssertionError(
                        "{} raw surface drifted from golden at x={} y={}: {:.4f} != {:.4f}".format(
                            name, x, y, got, expected
                        )
                    )
                rows += 1
        if rows != len(GRID) * len(GRID):
            raise AssertionError("{}: expected {} golden rows, read {}".format(name, len(GRID) ** 2, rows))
        checked += 1
    return checked


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_CSS = """
:root {
  color-scheme: light;
  --surface-1: #fcfcfb;
  --page: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --muted: #898781;
  --grid-line: #e1e0d9;
  --baseline: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --seq-100: #cde2fb; --seq-200: #9ec5f4; --seq-300: #6da7ec; --seq-400: #3987e5;
  --seq-500: #256abf; --seq-600: #184f95; --seq-700: #0d366b;
  --status-good: #0ca30c;
  --status-warning: #fab219;
  --status-serious: #ec835a;
  --status-critical: #d03b3b;
  --accent: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --page: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --grid-line: #2c2c2a;
    --baseline: #383835;
    --border: rgba(255,255,255,0.10);
    --accent: #3987e5;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19;
  --page: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --grid-line: #2c2c2a;
  --baseline: #383835;
  --border: rgba(255,255,255,0.10);
  --accent: #3987e5;
}
* { box-sizing: border-box; }
/* The page is capped and centred. Without this the flex columns grow to fill a
   widescreen monitor and the heat map — which is aspect-ratio 1 — grows with
   them until it is taller than the viewport, at which point zooming out shrinks
   the labels without ever bringing the whole grid into view. */
body {
  margin: 0 auto; padding: 20px 24px 48px; max-width: 1680px;
  background: var(--page); color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px; line-height: 1.5;
}
h1 { font-size: 19px; margin: 0 0 2px; font-weight: 600; }
h2 { font-size: 13px; margin: 0 0 8px; font-weight: 600; letter-spacing: .02em; }
.sub { color: var(--text-secondary); font-size: 13px; margin: 0 0 18px; max-width: 105ch; }
.controls {
  display: flex; flex-wrap: wrap; gap: 18px 26px; align-items: flex-end;
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 18px; margin-bottom: 18px;
}
.ctl { display: flex; flex-direction: column; gap: 5px; }
.ctl label { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.ctl select {
  font: inherit; padding: 5px 8px; border-radius: 6px;
  border: 1px solid var(--baseline); background: var(--surface-1); color: var(--text-primary);
}
.ctl input[type=range] { width: 210px; accent-color: var(--accent); }
.ctl .readout { font-size: 12px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.ctl.disabled { opacity: .45; }
.ctl.disabled input { cursor: not-allowed; }
.layout { display: flex; gap: 22px; align-items: flex-start; flex-wrap: wrap; }
.chartcard, .panel {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 10px; padding: 16px 18px;
}
/* max-width, not just flex-basis: the heat map is square, so any width the card
   is allowed to reach is also a height it will reach. 780px keeps the grid at
   about 640px square — large enough to read a 21x21 cell, small enough to sit
   beside both panels on a wide screen without scrolling. */
.chartcard { flex: 1 1 560px; min-width: 460px; max-width: 780px; }
.side { flex: 1 1 400px; min-width: 330px; max-width: 520px; display: flex; flex-direction: column; gap: 16px; }
.editcol { flex: 1 1 340px; min-width: 320px; max-width: 440px; display: flex; flex-direction: column; gap: 16px; }
/* The x tick labels are rotated vertical, so the TICK track is the tall one and
   the axis-title track is the short one — not the other way round. */
.gridwrap { display: grid; grid-template-columns: 22px 86px 1fr; grid-template-rows: 1fr 86px 22px; }
.ylab, .xlab {
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: var(--text-secondary); text-align: center;
}
.ylab { grid-column: 1; grid-row: 1; writing-mode: vertical-rl; transform: rotate(180deg); }
.yticks { grid-column: 2; grid-row: 1; display: flex; flex-direction: column-reverse; }
.ytick, .xtick {
  flex: 1; display: flex; align-items: center; justify-content: flex-end;
  font-size: 9px; color: var(--muted); font-variant-numeric: tabular-nums;
  padding-right: 4px; white-space: nowrap;
}
.xticks { grid-column: 3; grid-row: 2; display: flex; }
.xtick { justify-content: flex-start; padding: 4px 0 0; writing-mode: vertical-rl; }
.xlab { grid-column: 3; grid-row: 3; }
#heat {
  grid-column: 3; grid-row: 1;
  display: grid;
  grid-template-columns: repeat(__GRID_N__, 1fr); grid-template-rows: repeat(__GRID_N__, 1fr);
  aspect-ratio: 1; gap: 0; border: 1px solid var(--baseline);
}
.cell { position: relative; cursor: pointer; }
.cell:hover { outline: 2px solid var(--text-primary); outline-offset: -2px; z-index: 3; }
.cell.sel { outline: 3px solid var(--text-primary); outline-offset: -3px; z-index: 4; }
.cell.band::after {
  content: ""; position: absolute; inset: 0;
  background: repeating-linear-gradient(45deg,
    rgba(255,255,255,.85) 0 2px, rgba(0,0,0,0) 2px 5px);
}
.cell.escalate { box-shadow: inset 0 0 0 1.5px var(--status-critical); z-index: 2; }
.cell.conflict::before {
  content: ""; position: absolute; inset: 0;
  background: repeating-linear-gradient(135deg,
    var(--status-warning) 0 1.5px, rgba(0,0,0,0) 1.5px 6px);
}
.legendrow { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-top: 14px; }
.ramp { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-secondary); }
.rampbar { display: flex; height: 10px; width: 190px; border-radius: 3px; overflow: hidden; }
.rampbar span { flex: 1; }
.key { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-secondary); }
.swatch { width: 15px; height: 15px; border-radius: 3px; border: 1px solid var(--baseline); position: relative; }
.swatch.band { background: var(--seq-400); }
.swatch.band::after {
  content: ""; position: absolute; inset: 0;
  background: repeating-linear-gradient(45deg, rgba(255,255,255,.85) 0 2px, rgba(0,0,0,0) 2px 5px);
}
.swatch.esc { box-shadow: inset 0 0 0 2px var(--status-critical); background: transparent; }
.swatch.cfl { background: repeating-linear-gradient(135deg, var(--status-warning) 0 2px, transparent 2px 6px); }
table.kv { width: 100%; border-collapse: collapse; font-size: 12.5px; }
table.kv td { padding: 3px 0; vertical-align: top; }
table.kv td:first-child { color: var(--text-secondary); padding-right: 12px; white-space: nowrap; }
table.kv td:last-child { text-align: right; font-variant-numeric: tabular-nums; }
table.kv tr.sect td { padding-top: 11px; color: var(--muted); font-size: 10.5px;
  text-transform: uppercase; letter-spacing: .06em; }
.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 6px 0 2px; }
.tile { border: 1px solid var(--border); border-radius: 8px; padding: 8px 9px; }
.tile .t { font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.tile .v { font-size: 19px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tile .u { font-size: 11px; color: var(--muted); font-weight: 400; }
.stage { display: grid; grid-template-columns: 1fr auto; gap: 2px 10px; align-items: center;
  font-size: 12.5px; padding: 5px 0; border-bottom: 1px solid var(--grid-line); }
.stage:last-child { border-bottom: none; }
.stage .n { color: var(--text-secondary); }
.stage .v { font-variant-numeric: tabular-nums; font-weight: 600; }
.stage.final { font-size: 15px; }
.stage.final .v { font-size: 22px; color: var(--accent); }
.stage .note { grid-column: 1 / -1; font-size: 11px; color: var(--muted); }
.bars { margin: 10px 0 4px; }
.barrow { display: grid; grid-template-columns: 74px 1fr 52px; gap: 8px; align-items: center;
  font-size: 11.5px; margin-bottom: 5px; }
.bartrack { height: 12px; background: var(--grid-line); border-radius: 3px; overflow: hidden; }
.barfill { height: 100%; border-radius: 3px; }
.barval { text-align: right; font-variant-numeric: tabular-nums; }
.note { font-size: 11.5px; color: var(--muted); }
.warn { font-size: 11.5px; color: var(--text-secondary); border-left: 3px solid var(--status-warning);
  padding: 4px 0 4px 9px; margin: 9px 0 0; }
.empty { color: var(--muted); font-size: 12.5px; padding: 10px 0; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }

/* ---- editor ---- */
.panel h2 .hint { font-weight: 400; text-transform: none; letter-spacing: 0; color: var(--muted); }
.edgroup { margin-top: 10px; }
.edgroup > .gt { font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--muted); margin-bottom: 4px; }
.edrow { display: grid; grid-template-columns: 1fr auto auto; gap: 6px; align-items: center;
  margin-bottom: 4px; font-size: 12px; }
.edrow label { color: var(--text-secondary); }
/* Scoped to the editor, not to .edrow: the band-edge row lays its inputs out in
   a plain flex strip rather than the label/value grid. */
#editor input[type=number] {
  width: 74px; font: inherit; font-size: 12px; padding: 3px 5px; border-radius: 5px;
  border: 1px solid var(--baseline); background: var(--page); color: var(--text-primary);
  font-variant-numeric: tabular-nums; text-align: right;
}
#editor input.dirty { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.edges { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 4px; }
.edges input[type=number] { width: 52px !important; }
.edrow .base { font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums;
  min-width: 62px; text-align: right; }
.edactions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
button {
  font: inherit; font-size: 12px; padding: 5px 11px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--baseline); background: var(--surface-1); color: var(--text-primary);
}
button:hover { border-color: var(--accent); color: var(--accent); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.primary:hover { color: #fff; opacity: .9; }
button:disabled { opacity: .45; cursor: not-allowed; border-color: var(--baseline); color: var(--muted); }
.toggle { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--text-secondary); }
#exportWrap { margin-top: 12px; }
#exportWrap textarea {
  width: 100%; height: 260px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px; line-height: 1.45; padding: 9px; border-radius: 7px;
  border: 1px solid var(--baseline); background: var(--page); color: var(--text-primary);
  white-space: pre; overflow: auto; resize: vertical;
}
.banner {
  border-radius: 8px; padding: 9px 12px; margin: 0 0 14px; font-size: 12.5px;
  border: 1px solid var(--status-critical); color: var(--text-primary);
  background: color-mix(in srgb, var(--status-critical) 12%, transparent);
}
.banner.ok { border-color: var(--status-good); background: color-mix(in srgb, var(--status-good) 10%, transparent); }
.dirtynote { font-size: 11.5px; color: var(--text-secondary);
  border-left: 3px solid var(--accent); padding: 4px 0 4px 9px; margin: 10px 0 0; }
"""


def _html(data):
    # allow_nan=False so a malformed surface surfaces here rather than as a
    # silent JSON.parse failure in the browser. The "</" escape keeps a config
    # string that happens to contain "</script>" from ending the data block.
    payload = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    return (
        _HTML_HEAD
        + "<style>\n"
        + _CSS.replace("__GRID_N__", str(len(GRID)))
        + "\n</style>\n</head>\n<body>\n"
        + _HTML_BODY
        + '<script id="regdata" type="application/json">'
        + payload
        + "</script>\n<script>\n"
        + _JS
        + "\n</script>\n</body>\n</html>\n"
    )


_HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pi Greenhouse — regulation surface explorer</title>
"""

_HTML_BODY = """<h1>Regulation surface explorer
<span style="font-weight:400;color:var(--muted);font-size:14px">3.5-D</span></h1>
<p class="sub">Every cell is coloured by the <strong>final effective actuator output</strong> &mdash;
the command after the surface (or follower / time-of-day driver), the CO&#8322; additive term, the
external-effectiveness multiplier, the floor, the conflict rules, and the device adapter.
Click a cell to see the raw surface value beside that final duty. Slew limiting, the emergency
vector and the latch are temporal and cannot be drawn per cell; escalating cells are outlined and
the forced vectors are listed in the panel. Generated from <code>config.py</code>; the tuning
parameters on the right are <strong>editable</strong> &mdash; the plot recomputes as you change them,
and <em>Export changes</em> gives you a paste-ready <code>config.py</code> fragment. Nothing here
writes to the repo.</p>

<div id="selfcheck"></div>

<div class="controls">
  <div class="ctl">
    <label for="reg">Regulator</label>
    <select id="reg"></select>
  </div>
  <div class="ctl">
    <label for="prof">Species profile</label>
    <select id="prof"></select>
  </div>
  <div class="ctl">
    <label for="tod">Time of day (blend b)</label>
    <input type="range" id="tod" min="0" max="1" step="0.05" value="1">
    <span class="readout" id="todOut"></span>
  </div>
  <div class="ctl" id="co2Ctl">
    <label for="co2">CO&#8322; deviation</label>
    <input type="range" id="co2" min="0" max="100" step="1" value="50">
    <span class="readout" id="co2Out"></span>
  </div>
</div>

<div class="layout">
  <div class="chartcard">
    <h2 id="chartTitle"></h2>
    <p class="note" id="chartNote"></p>
    <div class="gridwrap">
      <div class="ylab" id="ylab"></div>
      <div class="yticks" id="yticks"></div>
      <div id="heat"></div>
      <div class="xticks" id="xticks"></div>
      <div class="xlab" id="xlab"></div>
    </div>
    <div class="legendrow">
      <div class="ramp">
        <span>0</span>
        <div class="rampbar" id="rampbar"></div>
        <span>100 % duty</span>
      </div>
      <div class="key"><span class="swatch band"></span> hysteresis band (history-dependent)</div>
      <div class="key"><span class="swatch esc"></span> would escalate (emergency / latch)</div>
      <div class="key"><span class="swatch cfl"></span> conflict rule fires</div>
    </div>
  </div>

  <div class="side">
    <div class="panel">
      <h2>Cell detail</h2>
      <div id="detail"><p class="empty">Click a cell in the grid.</p></div>
    </div>
    <div class="panel">
      <h2 id="aggTitle">Regulator</h2>
      <div id="agg"></div>
    </div>
  </div>

  <div class="editcol">
    <div class="panel">
      <h2>Tuning <span class="hint" id="edSubtitle"></span></h2>
      <label class="toggle">
        <input type="checkbox" id="showAll"> show every surface parameter
      </label>
      <div id="editor"></div>
      <div class="edactions">
        <button id="btnExport" class="primary">Export changes</button>
        <button id="btnResetReg">Reset this regulator</button>
        <button id="btnResetAll">Reset all</button>
      </div>
      <div id="dirtySummary"></div>
      <div id="exportWrap" hidden>
        <textarea id="exportText" readonly spellcheck="false"></textarea>
        <div class="edactions">
          <button id="btnCopy">Copy to clipboard</button>
          <button id="btnHideExport">Hide</button>
        </div>
        <p class="note">Paste over the matching keys in
          <code>config.py</code>. Surface blocks are emitted as a full
          <code>_surface(...)</code> call listing every non-default parameter, so
          they replace the existing call outright. Then regenerate the golden
          vectors &mdash; <code>python prototypes/plot_regulation_surfaces.py</code>
          &mdash; or the surface tests will fail.</p>
      </div>
    </div>
  </div>
</div>
"""

_JS = r"""
"use strict";
const D = JSON.parse(document.getElementById("regdata").textContent);
const G = D.grid, N = G.length;
const SEQ = ["#cde2fb","#b7d3f6","#9ec5f4","#86b6ef","#6da7ec","#5598e7","#3987e5",
             "#2a78d6","#256abf","#1c5cab","#184f95","#104281","#0d366b"];

const el = id => document.getElementById(id);
const fmt = (v, d) => (v === null || v === undefined) ? "—" : Number(v).toFixed(d === undefined ? 1 : d);

let state = {
  reg: "exhaust",
  profile: D.activeProfile,
  b: 1.0,
  co2dev: 50,
  sel: null,
  showAll: false
};

/* ---------- live, editable config ------------------------------------
   D is the frozen baseline exactly as config.py has it. LIVE is the copy the
   page edits and plots; every "has this changed?" question compares the two. */

const DEF = D.surfaceDefaults, META = D.surfaceMeta;
const clone = o => JSON.parse(JSON.stringify(o));
let LIVE = clone(D.regulators);
let LIVE_EDGES = D.bandEdges.slice();

// The arbiter names its four thresholds off the LAST four band edges, so these
// have to be recomputed rather than baked — the edges are editable.
const eMinor = () => LIVE_EDGES[LIVE_EDGES.length - 4];
const eConflict = () => LIVE_EDGES[LIVE_EDGES.length - 3];
const eEmerg = () => LIVE_EDGES[LIVE_EDGES.length - 2];
const eLatch = () => LIVE_EDGES[LIVE_EDGES.length - 1];

/* ---------- surface evaluator ----------------------------------------
   A direct port of lib/regulation_surface.evaluate. It exists because a grid
   baked in Python cannot answer "what if this slope were 3.0?". selfCheck()
   below proves it still agrees with the baked, golden-checked grids; if this
   ever drifts from the device code, the page says so instead of lying. */

function boostF(v, hi, lo, base, grad) {
  if (v > hi) return base + (v - hi) * grad;
  if (v < lo) return base + (lo - v) * grad;
  return 1.0;
}

function evalSurface(p, x, y) {
  const xc = x - 50.0, yc = y - 50.0;
  let lin = p.gain * (xc * p.ca + yc * p.sa) + p.offset - p.cross * (xc * p.sa + yc * p.ca);
  let d;
  d = x - p.bx_hi1; if (d > 0) lin += p.hx_hi1 * d;
  d = x - p.bx_hi2; if (d > 0) lin += p.hx_hi2 * d;
  d = p.bx_lo1 - x; if (d > 0) lin += p.hx_lo1 * d;
  d = p.bx_lo2 - x; if (d > 0) lin += p.hx_lo2 * d;
  d = y - p.by_hi1; if (d > 0) lin += p.hy_hi1 * d;
  d = y - p.by_hi2; if (d > 0) lin += p.hy_hi2 * d;
  d = p.by_lo1 - y; if (d > 0) lin += p.hy_lo1 * d;
  d = p.by_lo2 - y; if (d > 0) lin += p.hy_lo2 * d;
  const bx = boostF(x, p.x_top, p.x_bot, p.boost_base, p.grad);
  const by = boostF(y, p.y_top, p.y_bot, p.boost_base, p.grad);
  let raw = lin * p.mult * bx * by;
  if (raw < p.out_min) raw = p.out_min; else if (raw > p.out_max) raw = p.out_max;
  return (raw - p.out_min) / (p.out_max - p.out_min) * 100.0;
}

// grid[xi][yi], same indexing as the Python sampler. Cleared wholesale on any
// surface edit — the follower's grid is derived from the heater's.
let gridCache = {};

function surfaceGrid(reg) {
  if (gridCache[reg]) return gridCache[reg];
  const R = LIVE[reg];
  let g = null;
  if (R.driven === "surface") {
    g = G.map(x => G.map(y => evalSurface(R.surface, x, y)));
  } else if (R.driven === "follower") {
    g = surfaceGrid("heater").map(col =>
      col.map(v => clamp(v * R.followerGain + R.followerFloor)));
  }
  gridCache[reg] = g;
  return g;
}

/* ---------- deviation <-> physical ---------------------------------- */

function anchors(dim) {
  const p = D.profiles[state.profile], b = state.b;
  const day = p.day[dim], night = p.night[dim];
  return {
    a0:   night.at_0   + b * (day.at_0   - night.at_0),
    a50:  night.at_50  + b * (day.at_50  - night.at_50),
    a100: night.at_100 + b * (day.at_100 - night.at_100)
  };
}
function devToPhys(dev, a) {
  return dev <= 50 ? a.a0 + (dev / 50) * (a.a50 - a.a0)
                   : a.a50 + ((dev - 50) / 50) * (a.a100 - a.a50);
}
function physLabel(dev, dim) {
  const a = anchors(dim), v = devToPhys(dev, a);
  const dp = dim === "co2" ? 0 : 1;
  return v.toFixed(dp) + " " + D.dimUnits[dim];
}
// Render a conflict rule's when-clause in the operator's language, so the
// explanation stays true if a second rule is ever added to config.py.
function describeWhen(when) {
  return when.map(([dim, op, thresh]) =>
    `${D.dimLabels[dim]} ≥ ${thresh} ${op} ideal`).join(" and ");
}

/* ---------- pipeline (mirrors engine + arbiter + adapters) ---------- */

const severity = d => Math.abs(d - 50);
const clamp = v => v < 0 ? 0 : (v > 100 ? 100 : v);

// Deviations for one cell, keyed by dimension name. The two grid axes are the
// selected regulator's own dims; CO2 always comes from the slider.
function cellDevs(reg, xi, yi) {
  const R = LIVE[reg];
  const devs = { co2: state.co2dev };
  devs[R.dims[0]] = G[xi];
  devs[R.dims[1]] = G[yi];
  return devs;
}

// The external-effectiveness multiplier is always 1.0 here. With the sensor
// disabled that is exactly what the engine does. With it ENABLED the engine
// would derive the factor from a live outside reading, which a static plot has
// no way to supply — so the plot shows the un-gated command and says so.
function externalMult(reg) {
  return 1.0;
}
// Worst case the device could apply, for the caveat text.
function externalMultRange() {
  return D.externalSensor.minFactor * D.externalSensor.minFactorRh;
}

function organicCommand(reg, xi, yi) {
  const R = LIVE[reg];
  if (R.driven === "tod") return clamp(state.b * R.lightLevelDay);
  return surfaceGrid(reg)[xi][yi];
}

function pipeline(reg, xi, yi) {
  const R = LIVE[reg];
  const devs = cellDevs(reg, xi, yi);
  const raw = organicCommand(reg, xi, yi);

  // Stage 2b — the CO2 additive term, then the external multiplier. Both are
  // per-regulator: any regulator carrying a co2_gain takes the term (the
  // exhaust and the circulation pair do), and the external gate applies only
  // where config says so.
  let co2Term = 0, extMult = 1.0, val = raw;
  if (R.co2Gain !== undefined) {
    const over = devs.co2 - R.co2Break;
    if (over > 0) co2Term = R.co2Gain * over;
    val = raw + co2Term;
  }
  if (R.external) {
    extMult = externalMult(reg);
    val = val * extMult;
  }
  if (R.co2Gain !== undefined || R.external) val = clamp(val);
  const afterCo2 = val;

  // Stage 3 — floor, forced when the regulator's own band severity reaches the
  // minor edge. Slew is skipped (temporal); out starts at the organic target.
  let regSev = 0;
  for (const d of R.bandDims) regSev = Math.max(regSev, severity(devs[d]));
  let floored = val, floorFired = false;
  if (R.bandDims.length && regSev >= eMinor() && val < R.floor) {
    floored = R.floor; floorFired = true;
  }

  // Stage 4 — conflict rules, gated on GLOBAL severity reaching the conflict
  // edge. Applied after the floor, matching the arbiter's ordering.
  let gmax = 0;
  for (const d of D.dimOrder) if (devs[d] !== undefined) gmax = Math.max(gmax, severity(devs[d]));
  // A rule can apply to this cell without moving the value (a `prefer` whose
  // max is already met). Those cells are still marked — the rule IS live there
  // — with the panel spelling out that it changed nothing.
  let out = floored, conflictFired = false, conflictWhy = "", conflictWhen = "";
  if (gmax >= eConflict()) {
    for (const rule of D.conflicts) {
      let ok = true;
      for (const [dim, op, thresh] of rule.when) {
        const d = devs[dim];
        if (d === undefined) { ok = false; break; }
        if (op === "above" ? (d - 50 < thresh) : (50 - d < thresh)) { ok = false; break; }
      }
      if (!ok) continue;
      if (reg in rule.force) {
        conflictFired = true;
        conflictWhy = out === rule.force[reg] ? "forced (already at value)" : "forced";
        conflictWhen = describeWhen(rule.when);
        out = rule.force[reg];
      }
      if (reg in rule.prefer) {
        conflictFired = true;
        conflictWhen = describeWhen(rule.when);
        if (out < rule.prefer[reg]) { out = rule.prefer[reg]; conflictWhy = "preferred (max)"; }
        else conflictWhy = "preferred (max) — already higher, no change";
      }
    }
  }
  const command = out;

  // Escalation — which cells WOULD fire the emergency / latch vectors. Only
  // the directions marked in config.escalation count, so this is deliberately
  // not the same as the global severity above.
  let esc = 0;
  for (const d of D.dimOrder) {
    const dv = devs[d];
    if (dv === undefined) continue;
    const allowed = dv > 50 ? D.escalation[d].high : (dv < 50 ? D.escalation[d].low : false);
    if (allowed) esc = Math.max(esc, severity(dv));
  }
  // Escalation is a property of the DEVIATIONS, not of the regulator: the
  // arbiter applies the emergency / safe vectors to every regulator whose hold
  // mask is set, regardless of its band dims. So the growlight gets the overlay
  // too — its command is ToD-driven and flat, but an emergency still forces it
  // to its emergency_value, and that varies across the temp/humidity grid.

  // Stage 5 — the adapter.
  const ad = adapt(R, command);

  return {
    raw, co2Term, extMult, afterCo2, floored, floorFired, regSev, gmax,
    command, conflictFired, conflictWhy, conflictWhen, devs,
    esc, escEmergency: esc >= eEmerg(),
    escLatch: esc >= eLatch(),
    ...ad
  };
}

// Adapter transforms. Relay-backed actuators have no prior state in a static
// grid, so the band between off_below and on_above is reported as undetermined
// rather than guessed.
function adapt(R, command) {
  const a = R.adapter;
  if (a.type === "pwm") {
    const duty = clamp(command);
    return { kind: "pwm", duty, state: duty > 0 ? "on" : "off" };
  }
  if (a.type === "pwm_pair") {
    return {
      kind: "pwm_pair", duty: clamp(command * a.center_scale),
      center: clamp(command * a.center_scale), wall: clamp(command * a.wall_scale),
      state: command > 0 ? "on" : "off"
    };
  }
  if (a.type === "heater") {
    const duty = clamp(command);
    return { kind: "heater", duty, state: duty > 0 ? "on" : "off" };
  }
  // relay + growlight (relay-only mode) share the hysteresis comparison.
  // The comparisons are the adapter's own: strictly ABOVE on_above switches on,
  // strictly BELOW off_below switches off. A command sitting exactly on either
  // threshold holds, so it belongs in the undetermined band, not in ON.
  const dimmable = a.type === "growlight" && R.dimmable;
  if (command > a.on_above) {
    const duty = dimmable ? Math.min(command, a.dac_max_pct) : 100;
    return { kind: a.type, duty, state: "on" };
  }
  if (command < a.off_below) return { kind: a.type, duty: 0, state: "off" };
  return { kind: a.type, duty: null, state: "band" };
}

/* ---------- colour ---------------------------------------------------- */

function colourFor(r) {
  if (r.state === "band") return SEQ[6];
  if (r.duty === null) return SEQ[0];
  const i = Math.min(SEQ.length - 1, Math.max(0, Math.round(r.duty / 100 * (SEQ.length - 1))));
  return SEQ[i];
}

/* ---------- render ---------------------------------------------------- */

function buildControls() {
  const reg = el("reg");
  reg.innerHTML = D.regNames.map(n => `<option value="${n}">${n}</option>`).join("");
  reg.value = state.reg;
  const prof = el("prof");
  prof.innerHTML = Object.keys(D.profiles)
    .map(n => `<option value="${n}">${n} (${D.profiles[n].category})</option>`).join("");
  prof.value = state.profile;
  el("rampbar").innerHTML = SEQ.map(c => `<span style="background:${c}"></span>`).join("");

  reg.onchange = () => { state.reg = reg.value; state.sel = null; render(); renderEditor(); };
  prof.onchange = () => { state.profile = prof.value; render(); };
  el("tod").oninput = e => { state.b = parseFloat(e.target.value); render(); };
  el("co2").oninput = e => { state.co2dev = parseInt(e.target.value, 10); render(); };
}

function render() {
  const reg = state.reg, R = LIVE[reg];
  const takesCo2 = R.co2Gain !== undefined;

  // The CO2 slider only means something for a regulator carrying the additive
  // term — grey it out for the rest.
  const cc = el("co2Ctl");
  cc.classList.toggle("disabled", !takesCo2);
  el("co2").disabled = !takesCo2;
  el("co2Out").textContent = "dev " + state.co2dev + " — " + physLabel(state.co2dev, "co2")
    + (takesCo2 ? "" : " — no effect on " + reg);

  el("todOut").textContent = "b = " + state.b.toFixed(2) + " — "
    + (state.b >= 1 ? "full day" : state.b <= 0 ? "full night" : "transition");

  // Axes.
  const dx = R.dims[0], dy = R.dims[1];
  el("xlab").textContent = D.dimLabels[dx] + " deviation → (" + D.dimUnits[dx] + ")";
  el("ylab").textContent = D.dimLabels[dy] + " deviation → (" + D.dimUnits[dy] + ")";
  el("xticks").innerHTML = G.map(v =>
    `<div class="xtick">${v} · ${physLabel(v, dx)}</div>`).join("");
  el("yticks").innerHTML = G.map(v =>
    `<div class="ytick">${v} · ${physLabel(v, dy)}</div>`).join("");

  el("chartTitle").textContent = reg + " — final effective duty";
  el("chartNote").textContent = chartNote(R, reg);

  // Cells. Row 1 of the CSS grid is the TOP row, so y descends down the DOM.
  const heat = el("heat");
  const frag = document.createDocumentFragment();
  const results = [];
  for (let yi = N - 1; yi >= 0; yi--) {
    for (let xi = 0; xi < N; xi++) {
      const r = pipeline(reg, xi, yi);
      results.push(r);
      const c = document.createElement("div");
      c.className = "cell"
        + (r.state === "band" ? " band" : "")
        + (r.escEmergency ? " escalate" : "")
        + (r.conflictFired ? " conflict" : "")
        + (state.sel && state.sel[0] === xi && state.sel[1] === yi ? " sel" : "");
      c.style.background = colourFor(r);
      c.title = `${D.dimLabels[dx]} dev ${G[xi]} · ${D.dimLabels[dy]} dev ${G[yi]}\n`
        + `raw ${fmt(r.raw)} → final ${r.duty === null ? "history-dependent" : fmt(r.duty) + "%"}`;
      c.onclick = () => { state.sel = [xi, yi]; render(); };
      frag.appendChild(c);
    }
  }
  heat.replaceChildren(frag);

  renderAgg(reg, R, results);
  renderDetail(reg, R);
}

function chartNote(R, reg) {
  if (R.driven === "tod") {
    return "No surface: the grow light is driven by the time-of-day blend alone, so the grid is "
      + "uniform. The axes are drawn only as a frame — move the ToD slider to change the value.";
  }
  if (R.driven === "follower") {
    return "No surface of its own: the command is the heater's organic command × "
      + R.followerGain + " + " + R.followerFloor + ", so the shape follows the heater.";
  }
  if (R.adapter.type === "pwm" || R.adapter.type === "pwm_pair") {
    return "PWM duty as commanded — this is the number handed to the PCA9685 channel."
      + (R.co2Gain !== undefined ? " The CO₂ slider adds its term on top of this surface." : "");
  }
  if (R.adapter.type === "heater") {
    return "Time-proportioned over a " + R.adapter.window_s + " s window, so the plotted duty is the "
      + "average — the MOSFET itself is on/off.";
  }
  return "Relay actuator: the output is binary. Cells above on_above are ON; below off_below "
    + "are OFF; the hatched band in between — thresholds included — depends on the previous state.";
}

function renderAgg(reg, R, results) {
  el("aggTitle").textContent = reg + " — config & sampled grid";
  const a = R.adapter;

  const raws = results.map(r => r.raw);
  const det = results.filter(r => r.duty !== null).map(r => r.duty);
  const bandCount = results.filter(r => r.state === "band").length;
  const escCount = results.filter(r => r.escEmergency).length;
  const latchCount = results.filter(r => r.escLatch).length;
  const cflCount = results.filter(r => r.conflictFired).length;
  const stat = arr => arr.length
    ? { min: Math.min(...arr), max: Math.max(...arr), mean: arr.reduce((s, v) => s + v, 0) / arr.length }
    : { min: null, max: null, mean: null };
  const sr = stat(raws), sf = stat(det);

  let h = `<div class="tiles">
    <div class="tile"><div class="t">final min</div><div class="v">${fmt(sf.min)}<span class="u">%</span></div></div>
    <div class="tile"><div class="t">final mean</div><div class="v">${fmt(sf.mean)}<span class="u">%</span></div></div>
    <div class="tile"><div class="t">final max</div><div class="v">${fmt(sf.max)}<span class="u">%</span></div></div>
    <div class="tile"><div class="t">cells</div><div class="v">${results.length}</div></div>
  </div>
  <table class="kv">
    <tr class="sect"><td colspan="2">Raw surface (sampled)</td></tr>
    <tr><td>min / mean / max</td><td>${fmt(sr.min)} / ${fmt(sr.mean)} / ${fmt(sr.max)}</td></tr>`;

  if (bandCount) {
    h += `<tr><td>history-dependent cells</td><td>${bandCount} (excluded from final stats)</td></tr>`;
  }
  h += `<tr><td>cells that would escalate</td><td>${escCount} emergency / ${latchCount} latch</td></tr>
    <tr><td>cells hit by a conflict rule</td><td>${cflCount}</td></tr>

    <tr class="sect"><td colspan="2">Arbitration (config.py)</td></tr>
    <tr><td>driven</td><td>${R.driven}</td></tr>
    <tr><td>floor</td><td>${fmt(R.floor)} (forced at severity ≥ ${fmt(eMinor(), 0)})</td></tr>
    <tr><td>emergency_value</td><td>${R.emergencyValue === null ? "None — free" : fmt(R.emergencyValue)}</td></tr>
    <tr><td>safe_state</td><td>${R.safeState === null ? "None — free" : fmt(R.safeState)}</td></tr>
    <tr><td>slew_normal / slew_fast</td><td>${fmt(R.slewNormal)} / ${fmt(R.slewFast)} per tick</td></tr>
    <tr><td>band dims</td><td>${R.bandDims.length ? R.bandDims.join(", ") : "— (band 0)"}</td></tr>

    <tr class="sect"><td colspan="2">Adapter — ${a.type}</td></tr>`;

  if (a.pin_key) h += `<tr><td>pin_key</td><td><code>${a.pin_key}</code></td></tr>`;
  if (a.pca9685_ch !== undefined) h += `<tr><td>PCA9685 channel</td><td>${a.pca9685_ch}</td></tr>`;
  if (a.center_ch !== undefined) {
    h += `<tr><td>channels</td><td>center ch${a.center_ch} × ${a.center_scale}, `
      + `wall ch${a.wall_ch} × ${a.wall_scale}</td></tr>`;
  }
  if (a.on_above !== undefined) {
    h += `<tr><td>on_above / off_below</td><td>${fmt(a.on_above)} / ${fmt(a.off_below)}</td></tr>`;
  }
  if (a.window_s !== undefined) h += `<tr><td>window_s</td><td>${a.window_s} s</td></tr>`;
  if (a.min_on_s !== undefined) {
    h += `<tr><td>min_on_s / min_off_s</td><td>${a.min_on_s} s / ${a.min_off_s} s</td></tr>`;
  }
  if (a.dac_max_pct !== undefined) {
    h += `<tr><td>dac_max_pct</td><td>${a.dac_max_pct} % `
      + `${R.dimmable ? "(applied)" : "(unused — relay-only mode)"}</td></tr>`;
  }

  if (R.co2Gain !== undefined) {
    const ca = anchors("co2");
    const devDead = R.co2Break;
    // co2_gain of 0 is a legal config value and disables the term entirely.
    const devFloor = R.co2Gain > 0 ? R.co2Break + R.floor / R.co2Gain : null;
    const devSat = R.co2Gain > 0 ? Math.min(100, R.co2Break + 100 / R.co2Gain) : null;
    const ppmAt = d => d === null || d > 100
      ? "never within this profile's range" : `dev ${fmt(d)} · ${devToPhys(d, ca).toFixed(0)} ppm`;
    h += `<tr class="sect"><td colspan="2">CO₂ additive term</td></tr>
      <tr><td>co2_gain / co2_break</td><td>${fmt(R.co2Gain, 2)} / ${fmt(R.co2Break)}</td></tr>
      <tr><td>deadband ends</td><td>${ppmAt(devDead)}</td></tr>
      <tr><td>term clears the floor (${fmt(R.floor)})</td><td>${ppmAt(devFloor)}</td></tr>
      <tr><td>term saturates (100)</td><td>${ppmAt(devSat)}</td></tr>
      <tr><td>external multiplier</td><td>${!R.external
        ? "not applied to this regulator"
        : D.externalSensor.enabled
        ? "enabled — NOT modelled (needs a live outside reading); device range ×"
          + fmt(externalMultRange(), 2) + "–1.00"
        : "sensor disabled — constant 1.0"}</td></tr>`;
    // The ceiling of the term is gain*(100-break). If that sits under the
    // floor, the floor forces the command up and CO2 changes nothing anywhere
    // in the profile's range — the exact bug this repo shipped twice.
    const ceiling = R.co2Gain * (100 - R.co2Break);
    if (ceiling <= R.floor) {
      h += `<tr><td colspan="2"><strong>CO₂ term tops out at ${fmt(ceiling)}, under the floor of
        ${fmt(R.floor)} — CO₂ cannot move this actuator at any concentration.</strong></td></tr>`;
    }
  }
  h += `</table>`;

  h += `<p class="warn">Not drawn per cell: slew limiting (${fmt(R.slewNormal)} / ${fmt(R.slewFast)} per
    ${D.tickS} s tick) needs the previous command, and emergency / latch need
    ${D.latch.enter_ticks} consecutive ticks past the escalation edge. Escalation is gated to
    ${Object.keys(D.escalation).filter(d => D.escalation[d].high || D.escalation[d].low)
      .map(d => D.dimLabels[d] + (D.escalation[d].high ? " high" : "") + (D.escalation[d].low ? " low" : ""))
      .join(", ") || "nothing"} — outlined cells are where that gated severity reaches
    ${fmt(eEmerg(), 0)}.</p>`;
  el("agg").innerHTML = h;
}

function renderDetail(reg, R) {
  if (!state.sel) { el("detail").innerHTML = `<p class="empty">Click a cell in the grid.</p>`; return; }
  const takesCo2 = R.co2Gain !== undefined;
  const [xi, yi] = state.sel;
  const r = pipeline(reg, xi, yi);
  const dx = R.dims[0], dy = R.dims[1];
  const finalTxt = r.duty === null ? "history" : fmt(r.duty) + "%";

  const bar = (label, value, colour) => {
    const w = value === null ? 0 : Math.max(0, Math.min(100, value));
    return `<div class="barrow"><span>${label}</span>
      <div class="bartrack"><div class="barfill" style="width:${w}%;background:${colour}"></div></div>
      <span class="barval">${value === null ? "—" : fmt(value)}</span></div>`;
  };

  let h = `<table class="kv">
    <tr><td>${D.dimLabels[dx]} deviation</td><td>${G[xi]} · ${physLabel(G[xi], dx)}</td></tr>
    <tr><td>${D.dimLabels[dy]} deviation</td><td>${G[yi]} · ${physLabel(G[yi], dy)}</td></tr>
    <tr><td>CO₂ deviation</td><td>${state.co2dev} · ${physLabel(state.co2dev, "co2")}</td></tr>
    <tr><td>severity (this regulator / global)</td><td>${fmt(r.regSev)} / ${fmt(r.gmax)}</td></tr>
  </table>
  <div class="bars">
    ${bar("raw surface", r.raw, "var(--seq-300)")}
    ${takesCo2 ? bar("+ CO₂ term", r.afterCo2, "var(--seq-400)") : ""}
    ${bar("after floor/conflict", r.command, "var(--seq-500)")}
    ${bar("final duty", r.duty, "var(--accent)")}
  </div>
  <div class="stage"><span class="n">raw surface output</span><span class="v">${fmt(r.raw)}</span></div>`;

  if (takesCo2) {
    h += `<div class="stage"><span class="n">CO₂ term (gain ${fmt(R.co2Gain, 2)} ×
      relu(dev − ${fmt(R.co2Break)}))</span>
      <span class="v">${r.co2Term > 0 ? "+" + fmt(r.co2Term) : "0.0"}</span>
      ${r.co2Term === 0
        ? `<span class="note">inside the CO₂ deadband — the term contributes nothing here</span>`
        : ""}
      </div>`;
  }
  if (R.external) {
    h += `<div class="stage"><span class="n">× external multiplier</span><span class="v">${fmt(r.extMult, 2)}</span>
      <span class="note">${D.externalSensor.enabled
        ? `external sensor ENABLED in config: the device derives this from a live outside reading and `
          + `could scale the command as low as ×${fmt(externalMultRange(), 2)}. A static plot has no `
          + `outside reading, so this shows the un-gated command.`
        : `external sensor disabled in config — the engine uses a constant 1.0`}</span>
      </div>`;
  }

  h += `<div class="stage"><span class="n">after floor${r.floorFired ? " — <strong>floor applied</strong>" : ""}</span>
      <span class="v">${fmt(r.floored)}</span>
      ${r.floorFired
        ? `<span class="note">severity ${fmt(r.regSev)} ≥ ${fmt(eMinor(), 0)} forced the
           command up to the floor of ${fmt(R.floor)}</span>`
        : ""}
    </div>
    <div class="stage"><span class="n">after conflict rules${r.conflictFired
      ? " — <strong>" + r.conflictWhy + "</strong>" : ""}</span>
      <span class="v">${fmt(r.command)}</span>
      ${r.conflictFired ? `<span class="note">${r.conflictWhen}</span>` : ""}
    </div>`;

  // Adapter stage — say what the device actually does with that command.
  let adNote = "";
  if (r.kind === "pwm_pair") {
    adNote = `center ch${R.adapter.center_ch} ${fmt(r.center)} % · wall ch${R.adapter.wall_ch} ${fmt(r.wall)} % `
      + `(grid is coloured by the center channel)`;
  } else if (r.kind === "heater") {
    adNote = `time-proportioned: ${fmt(r.duty)} % of a ${R.adapter.window_s} s window, `
      + `bounded by min_on_s ${R.adapter.min_on_s} s / min_off_s ${R.adapter.min_off_s} s`;
  } else if (r.state === "band") {
    adNote = `command ${fmt(r.command)} sits inside the hysteresis band `
      + `(${fmt(R.adapter.off_below)}–${fmt(R.adapter.on_above)}, inclusive): the relay stays wherever it already was. `
      + `min_on_s ${R.adapter.min_on_s} s / min_off_s ${R.adapter.min_off_s} s also gate the transition.`;
  } else if (r.kind === "relay" || r.kind === "growlight") {
    adNote = `command ${fmt(r.command)} is ${r.state === "on" ? "above on_above " + fmt(R.adapter.on_above)
      : "below off_below " + fmt(R.adapter.off_below)} — relay ${r.state.toUpperCase()}`
      + (r.kind === "growlight" && !R.dimmable
        ? `; relay-only mode, so dac_max_pct ${R.adapter.dac_max_pct} % is unused` : "");
  } else {
    adNote = `PWM duty passes straight through to channel ${R.adapter.pca9685_ch}`;
  }

  h += `<div class="stage final"><span class="n">FINAL effective duty</span><span class="v">${finalTxt}</span>
      <span class="note">${adNote}</span></div>`;

  const delta = r.duty === null ? null : r.duty - r.raw;
  if (delta !== null && Math.abs(delta) >= 0.05) {
    h += `<p class="warn">Raw ${fmt(r.raw)} → final ${fmt(r.duty)}: a difference of
      ${delta > 0 ? "+" : ""}${fmt(delta)} points. The organic surface is <strong>not</strong> what
      the actuator does here.</p>`;
  }
  if (r.escEmergency) {
    h += `<p class="warn">This cell would escalate: gated severity ${fmt(r.esc)} ≥
      ${fmt(eEmerg(), 0)}${r.escLatch ? ` (and ≥ the latch edge ${fmt(eLatch(), 0)})` : ""},
      held for ${D.latch.enter_ticks} ticks. The forced vector would then set this regulator to
      <strong>${R.emergencyValue === null ? "free (keeps its organic command)" : fmt(R.emergencyValue) + " %"}</strong>
      in emergency and <strong>${R.safeState === null ? "free" : fmt(R.safeState) + " %"}</strong> under latch,
      overriding everything above.</p>`;
  }
  el("detail").innerHTML = h;
}

/* ---------- editor ----------------------------------------------------- */

// Hinge pairs are shown as one row because that is how they are tuned: a slope
// and the deviation it starts from. Everything else is a single number.
const HINGES = [
  ["x high hinge 1", "hx_hi1", "bx_hi1"],
  ["x high hinge 2", "hx_hi2", "bx_hi2"],
  ["x low hinge 1", "hx_lo1", "bx_lo1"],
  ["x low hinge 2", "hx_lo2", "bx_lo2"],
  ["y high hinge 1", "hy_hi1", "by_hi1"],
  ["y high hinge 2", "hy_hi2", "by_hi2"],
  ["y low hinge 1", "hy_lo1", "by_lo1"],
  ["y low hinge 2", "hy_lo2", "by_lo2"],
];
const COUPLING = ["ca", "sa", "cross", "gain", "offset"];
const BOOST = ["x_top", "x_bot", "y_top", "y_bot", "boost_base", "grad"];
const OUTPUT = ["mult", "out_min", "out_max"];
const BREAKPOINTS = new Set(HINGES.map(hz => hz[2]));

function stepFor(name) {
  if (name === "grad") return 0.001;
  if (BREAKPOINTS.has(name) || BOOST.includes(name) || OUTPUT.includes(name)) return 1;
  return 0.1;
}

// A parameter is worth showing when it is doing something — non-default now, or
// non-default in the shipped config (so a knob you just zeroed does not vanish
// from under the cursor).
function inPlay(reg, name) {
  return LIVE[reg].surface[name] !== DEF[name] || D.regulators[reg].surface[name] !== DEF[name];
}

function numInput(path, value, base, step) {
  const dirty = value !== base ? " dirty" : "";
  return `<input type="number" class="ed${dirty}" data-path="${path}" value="${value}" step="${step}">`;
}

function edRow(label, cells, baseText) {
  return `<div class="edrow"><label>${label}</label>${cells}<span class="base">${baseText}</span></div>`;
}

function renderEditor() {
  const reg = state.reg, R = LIVE[reg], B = D.regulators[reg];
  el("edSubtitle").textContent = "— " + reg;
  let h = "";

  if (R.driven === "surface") {
    const rows = [];
    for (const [label, slope, brk] of HINGES) {
      if (!state.showAll && !inPlay(reg, slope) && !inPlay(reg, brk)) continue;
      rows.push(edRow(label,
        numInput("surface." + slope, R.surface[slope], B.surface[slope], stepFor(slope))
        + numInput("surface." + brk, R.surface[brk], B.surface[brk], stepFor(brk)),
        "slope / from"));
    }
    if (rows.length) h += `<div class="edgroup"><div class="gt">Hinges — slope, breakpoint</div>${rows.join("")}</div>`;

    for (const [title, names] of [["Coupling", COUPLING], ["Boost", BOOST], ["Output", OUTPUT]]) {
      const rs = names.filter(n => state.showAll || inPlay(reg, n)).map(n =>
        edRow(n, numInput("surface." + n, R.surface[n], B.surface[n], stepFor(n)) + "<span></span>",
          fmt(B.surface[n], 3)));
      if (rs.length) h += `<div class="edgroup"><div class="gt">${title}</div>${rs.join("")}</div>`;
    }
  } else {
    h += `<p class="note">${reg} has no surface: it is driven by
      ${R.driven === "tod" ? "the time-of-day blend" : "the heater's command"}.</p>`;
  }

  const arb = [];
  arb.push(edRow("floor", numInput("floor", R.floor, B.floor, 1) + "<span></span>", fmt(B.floor)));
  arb.push(edRow("slew_normal", numInput("slewNormal", R.slewNormal, B.slewNormal, 5) + "<span></span>",
    fmt(B.slewNormal)));
  arb.push(edRow("slew_fast", numInput("slewFast", R.slewFast, B.slewFast, 5) + "<span></span>",
    fmt(B.slewFast)));
  if (R.co2Gain !== undefined) {
    arb.push(edRow("co2_gain", numInput("co2Gain", R.co2Gain, B.co2Gain, 0.1) + "<span></span>", fmt(B.co2Gain, 2)));
    arb.push(edRow("co2_break", numInput("co2Break", R.co2Break, B.co2Break, 1) + "<span></span>", fmt(B.co2Break)));
  }
  h += `<div class="edgroup"><div class="gt">Arbitration</div>${arb.join("")}</div>`;

  if (R.adapter.on_above !== undefined) {
    const ad = ["on_above", "off_below"].map(k =>
      edRow(k, numInput("adapter." + k, R.adapter[k], B.adapter[k], 0.5) + "<span></span>", fmt(B.adapter[k])));
    h += `<div class="edgroup"><div class="gt">Adapter thresholds</div>${ad.join("")}
      <p class="note">These are points on the surface above, not independent knobs —
      move the slope and both switch points move with it.</p></div>`;
  }

  const edges = LIVE_EDGES.map((v, i) =>
    numInput("edge." + i, v, D.bandEdges[i], 1)).join("");
  h += `<div class="edgroup"><div class="gt">Band edges (global)</div>
    <div class="edges">${edges}</div>
    <p class="note">The arbiter names its minor / conflict / emergency / latch
    thresholds off the last four. The last edge must stay 50.</p></div>`;

  el("editor").innerHTML = h;
  updateDirty();
}

function applyEdit(path, rawValue) {
  const v = parseFloat(rawValue);
  if (!Number.isFinite(v)) return false;
  const R = LIVE[state.reg];
  if (path.startsWith("surface.")) { R.surface[path.slice(8)] = v; gridCache = {}; }
  else if (path.startsWith("adapter.")) R.adapter[path.slice(8)] = v;
  else if (path.startsWith("edge.")) LIVE_EDGES[parseInt(path.slice(5), 10)] = v;
  else R[path] = v;
  return true;
}

/* ---------- change tracking + export ----------------------------------- */

function regChanges(name) {
  const R = LIVE[name], B = D.regulators[name], out = [];
  if (R.surface) {
    for (const m of META) {
      if (R.surface[m.name] !== B.surface[m.name]) out.push("surface." + m.name);
    }
  }
  for (const key of ["floor", "slewNormal", "slewFast", "co2Gain", "co2Break"]) {
    if (R[key] !== undefined && R[key] !== B[key]) out.push(key);
  }
  for (const key of ["on_above", "off_below"]) {
    if (R.adapter[key] !== undefined && R.adapter[key] !== B.adapter[key]) out.push("adapter." + key);
  }
  return out;
}

function edgesChanged() {
  return LIVE_EDGES.some((v, i) => v !== D.bandEdges[i]);
}

function updateDirty() {
  const per = D.regNames.map(n => [n, regChanges(n).length]).filter(e => e[1]);
  const total = per.reduce((s, e) => s + e[1], 0) + (edgesChanged() ? 1 : 0);
  el("btnExport").disabled = total === 0;
  el("dirtySummary").innerHTML = total === 0
    ? `<p class="note">No changes — every value matches <code>config.py</code>.</p>`
    : `<p class="dirtynote">${total} changed value${total === 1 ? "" : "s"}:
       ${per.map(([n, c]) => `${n} (${c})`).join(", ")}${edgesChanged()
         ? (per.length ? ", " : "") + "band edges" : ""}.</p>`;
}

// config.py writes floats with a decimal point and ints without; match that so
// the fragment reads like the file it is going into.
function pyNum(v) {
  if (Number.isInteger(v)) return v.toFixed(1);
  return String(parseFloat(v.toFixed(6)));
}

function buildExport() {
  const out = [];
  if (edgesChanged()) {
    out.push("# --- regulation ---");
    out.push('"band_edges": [' + LIVE_EDGES.map(v => String(v)).join(", ") + "],", "");
  }
  for (const name of D.regNames) {
    const R = LIVE[name], B = D.regulators[name];
    const changed = regChanges(name);
    if (!changed.length) continue;
    const lines = [];
    if (changed.some(c => c.startsWith("surface."))) {
      // Emit the WHOLE call: _surface() fills unlisted params from the neutral
      // defaults, so a partial list would silently reset the ones left out.
      lines.push('"surface": _surface(');
      for (const m of META) {
        if (R.surface[m.name] !== DEF[m.name]) lines.push(`    ${m.name}=${pyNum(R.surface[m.name])},`);
      }
      lines.push("),");
    }
    for (const [key, prop] of [["floor", "floor"], ["slew_normal", "slewNormal"],
                               ["slew_fast", "slewFast"], ["co2_gain", "co2Gain"],
                               ["co2_break", "co2Break"]]) {
      if (changed.includes(prop)) lines.push(`"${key}": ${pyNum(R[prop])},`);
    }
    const adKeys = ["on_above", "off_below"].filter(k => changed.includes("adapter." + k));
    if (adKeys.length) {
      lines.push('"adapter": {  # merge these two into the existing adapter block');
      for (const k of adKeys) lines.push(`    "${k}": ${pyNum(R.adapter[k])},`);
      lines.push("},");
    }
    out.push(`# --- regulation.regulators.${name} ---`, ...lines, "");
  }
  return out.join("\n").trimEnd();
}

/* ---------- self-check -------------------------------------------------
   rawBaked came from lib.regulation_surface.evaluate and was checked against
   tests/golden/ at generate time. If the JS port above reproduces it, the live
   plot is trustworthy; if it does not, say so loudly rather than plot fiction.
   The tolerance is loose enough for the float32 parameter array the device uses
   and tight enough that a real porting error cannot hide under it. */

const SELFCHECK_TOL = 0.05;

function selfCheck() {
  let worst = 0, where = "";
  for (const name of D.regNames) {
    const B = D.regulators[name];
    if (B.driven !== "surface" || !B.rawBaked) continue;
    const g = surfaceGrid(name);
    for (let i = 0; i < N; i++) {
      for (let j = 0; j < N; j++) {
        const d = Math.abs(g[i][j] - B.rawBaked[i][j]);
        if (d > worst) { worst = d; where = `${name} at x=${G[i]} y=${G[j]}`; }
      }
    }
  }
  const box = el("selfcheck");
  if (worst > SELFCHECK_TOL) {
    box.innerHTML = `<p class="banner"><strong>Surface evaluator mismatch.</strong>
      This page's JavaScript port of <code>lib/regulation_surface.evaluate</code> disagrees with the
      golden-checked grid baked in at generate time by up to ${worst.toFixed(4)} (${where}).
      Everything plotted below is suspect — fix the port in
      <code>prototypes/gen_regulation_explorer.py</code> before trusting it.</p>`;
  } else {
    box.innerHTML = `<p class="banner ok">Surface evaluator agrees with the golden-checked
      reference grid (largest difference ${worst.toExponential(1)}). Edits below are computed
      by the same maths the Pico runs.</p>`;
  }
}

/* ---------- wiring ------------------------------------------------------ */

el("editor").addEventListener("input", ev => {
  const t = ev.target;
  if (!t.dataset || !t.dataset.path) return;
  if (!applyEdit(t.dataset.path, t.value)) return;
  render();
  updateDirty();
  // Re-mark just this input; re-rendering the whole editor here would steal
  // focus mid-keystroke.
  const [scope, key] = [t.dataset.path, null];
  const B = D.regulators[state.reg];
  let base;
  if (scope.startsWith("surface.")) base = B.surface[scope.slice(8)];
  else if (scope.startsWith("adapter.")) base = B.adapter[scope.slice(8)];
  else if (scope.startsWith("edge.")) base = D.bandEdges[parseInt(scope.slice(5), 10)];
  else base = B[scope];
  t.classList.toggle("dirty", parseFloat(t.value) !== base);
});

el("showAll").onchange = e => { state.showAll = e.target.checked; renderEditor(); };
el("btnResetReg").onclick = () => {
  LIVE[state.reg] = clone(D.regulators[state.reg]);
  gridCache = {};
  render(); renderEditor();
};
el("btnResetAll").onclick = () => {
  LIVE = clone(D.regulators);
  LIVE_EDGES = D.bandEdges.slice();
  gridCache = {};
  el("exportWrap").hidden = true;
  render(); renderEditor();
};
el("btnExport").onclick = () => {
  el("exportText").value = buildExport();
  el("exportWrap").hidden = false;
  el("exportText").scrollIntoView({ block: "nearest" });
};
el("btnHideExport").onclick = () => { el("exportWrap").hidden = true; };
el("btnCopy").onclick = async () => {
  const ta = el("exportText");
  try {
    await navigator.clipboard.writeText(ta.value);
    el("btnCopy").textContent = "Copied";
  } catch (err) {
    // file:// pages often have no clipboard permission — fall back to a
    // selection the user can copy with the keyboard.
    ta.focus(); ta.select();
    el("btnCopy").textContent = "Selected — press Ctrl+C";
  }
  setTimeout(() => { el("btnCopy").textContent = "Copy to clipboard"; }, 2500);
};

buildControls();
selfCheck();
render();
renderEditor();
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the self-contained regulation explorer HTML.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output HTML path")
    parser.add_argument("--no-golden-check", action="store_true", help="skip the golden-vector assertion")
    args = parser.parse_args(argv)

    # Fail the same way the device would rather than plotting an invalid config.
    config.validate_config()

    data = build_data()
    if not args.no_golden_check:
        checked = check_goldens(data)
        print("golden spot-check: {} surfaces matched tests/golden/ within {}".format(checked, GOLDEN_TOLERANCE))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_html(data), encoding="utf-8")
    print("wrote {} ({:.1f} KB)".format(out, out.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
