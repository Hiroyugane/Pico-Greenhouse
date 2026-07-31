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
        # Anchor key ORDER, not just the names: the profile editor lays its
        # three columns out in this order, so taking it from the validator's
        # tuple keeps the editor from transposing "far too low" and "ideal" if
        # config ever reorders them.
        "anchorKeys": list(config._ANCHOR_KEYS),
        # Day/night blend window. Editable on the page, where it drives the
        # clock mode of the time-of-day control (b is derived from a wall-clock
        # minute exactly as regulation_normalizer.blend_factor does it).
        "schedule": {
            "day_start_min": reg_cfg["day_start_min"],
            "day_end_min": reg_cfg["day_end_min"],
            "transition_min": reg_cfg["transition_min"],
        },
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
/* ============================================================================
   Pi Greenhouse — Regulation surface explorer (redesign)
   Engineer's-instrument aesthetic per the Pi Greenhouse design system:
   graphite ink on warm datasheet paper (light) / near-black terminal (dark),
   monospace carries all data, ruled tables over floating cards.
   No CDN, no webfonts (offline bench file) — system stacks stand in for
   IBM Plex Sans / IBM Plex Mono / VT323.
   ============================================================================ */
:root {
  color-scheme: light;
  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Mono", "Segoe UI Mono", Menlo, Consolas, monospace;

  /* brand */
  --grow-900:#0c3d22; --grow-700:#135731; --grow-600:#1f8a4c; --grow-500:#25a65b;
  --grow-400:#4cbf7a; --grow-300:#7ad6a0; --grow-100:#d6f1e0;
  --bloom-700:#8e1a63; --bloom-500:#db2a8a; --bloom-300:#f06ab2; --bloom-100:#fbd9ec;

  /* status = LEDs = severity */
  --led-red:#e5484d; --led-amber:#f2a93b; --led-green:#46a758; --led-blue:#3e8fe0;

  /* light surface — warm datasheet paper */
  --page:#eceee9;
  --surface:#fbfbf9;
  --surface-sunken:#f1f2ee;
  --fg-1:#14181b;
  --fg-2:#5b6770;
  --fg-3:#7e8b93;
  --border:#d9ddd6;
  --border-strong:#c3ccd1;
  --grid-line:#e3e6df;
  --band-fill:#e0ddd3;   /* history-dependent cells — deliberately NON-green */
  --band-stroke:#b9b6aa;
  --accent:var(--grow-600);

  --radius-sm:3px; --radius-md:6px; --radius-lg:10px; --radius-pcb:2px;
  --shadow-sm:0 1px 2px rgba(20,24,27,.06);
  --shadow-md:0 2px 8px rgba(20,24,27,.08),0 1px 2px rgba(20,24,27,.06);
  --tracking-caps:0.12em;
}
:root[data-theme="dark"] {
  color-scheme: dark;
  /* dark surface — near-black device/terminal glass */
  --page:#05080a;
  --surface:#111417;
  --surface-sunken:#0b0e10;
  --fg-1:#eef3f2;
  --fg-2:#9fb0ad;
  --fg-3:#6c7c7a;
  --border:#232a2c;
  --border-strong:#333c3e;
  --grid-line:#1a2022;
  --band-fill:#42423a;
  --band-stroke:#5a5a4e;
  --led-green:#46a758;
  --shadow-sm:none;
  --shadow-md:none;
}
* { box-sizing:border-box; }
html,body { margin:0; }
/* The page is capped and centred. Without this the grid columns grow to fill a
   widescreen monitor and the heat map — which is aspect-ratio 1 — grows with
   them until it is taller than the viewport. */
body {
  margin:0 auto; max-width:1900px;
  background:var(--page); color:var(--fg-1);
  font-family:var(--font-sans); font-size:14px; line-height:1.5;
  padding:22px 26px 56px;
  -webkit-font-smoothing:antialiased;
}
.mono { font-family:var(--font-mono); font-feature-settings:'zero' 1; }
.eyebrow {
  font-family:var(--font-mono); font-size:11px; font-weight:600;
  letter-spacing:var(--tracking-caps); text-transform:uppercase; color:var(--fg-2);
}
a { color:var(--grow-600); }
a:hover { color:var(--grow-700); }
code { font-family:var(--font-mono); font-size:12px; }
.note { font-size:11.5px; color:var(--fg-3); line-height:1.5; }

/* ── header ─────────────────────────────────────────────────────────────── */
.topbar { display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:18px; }
.brandline { display:flex; align-items:center; gap:9px; margin-bottom:7px; }
.brand-dot { width:9px; height:9px; border-radius:50%; background:var(--grow-600);
  box-shadow:0 0 0 3px rgba(31,138,76,.18); }
h1 { font-size:26px; font-weight:600; letter-spacing:-0.01em; margin:0 0 4px; }
.sub { color:var(--fg-2); font-size:13px; margin:0; max-width:100ch; }
.sub code { font-family:var(--font-mono); font-size:12px; color:var(--fg-1); }
.themetoggle { display:flex; border:1px solid var(--border-strong); border-radius:var(--radius-md); overflow:hidden;
  flex:none; }
.themetoggle button {
  font-family:var(--font-mono); font-size:11px; letter-spacing:.06em; text-transform:uppercase;
  padding:7px 12px; border:0; background:var(--surface); color:var(--fg-2); cursor:pointer;
}
.themetoggle button + button { border-left:1px solid var(--border); }
.themetoggle button[aria-pressed="true"] { background:var(--fg-1); color:var(--page); }

/* ── control bar ────────────────────────────────────────────────────────── */
.controls {
  display:grid; grid-template-columns:1fr; gap:16px;
  background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-lg);
  padding:16px 18px; margin-bottom:18px; box-shadow:var(--shadow-sm);
}
.ctl-label { display:block; margin-bottom:8px; }
.ctl-row { display:flex; flex-wrap:wrap; gap:20px 34px; align-items:flex-start; }
.ctl { display:flex; flex-direction:column; }
.ctl.grow { flex:1 1 240px; min-width:220px; }

/* segmented regulator rail */
.segrail { display:flex; flex-wrap:wrap; gap:0; border:1px solid var(--border-strong); border-radius:var(--radius-md);
  overflow:hidden; width:fit-content; max-width:100%; }
.segrail button {
  font-family:var(--font-mono); font-size:12.5px; padding:8px 14px; border:0; cursor:pointer;
  background:var(--surface); color:var(--fg-2); border-left:1px solid var(--border);
  transition:background var(--dur,120ms) ease, color 120ms ease;
}
.segrail button:first-child { border-left:0; }
.segrail button:hover { background:var(--surface-sunken); color:var(--fg-1); }
.segrail button[aria-pressed="true"] { background:var(--grow-600); color:#fff; font-weight:600; }

/* profile select */
select#prof {
  font-family:var(--font-mono); font-size:13px; padding:8px 30px 8px 11px; color:var(--fg-1);
  background:var(--surface); border:1px solid var(--border-strong); border-radius:var(--radius-md);
  appearance:none;
  background-image:linear-gradient(45deg,transparent 50%,var(--fg-3) 50%),
    linear-gradient(135deg,var(--fg-3) 50%,transparent 50%);
  background-position:calc(100% - 15px) 55%, calc(100% - 10px) 55%; background-size:5px 5px,5px 5px;
    background-repeat:no-repeat;
  min-width:210px;
}

/* sliders */
.slider-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:9px; }
.readout { font-family:var(--font-mono); font-size:12px; color:var(--fg-1); font-variant-numeric:tabular-nums; }
input[type=range] { -webkit-appearance:none; appearance:none; width:100%; height:4px; border-radius:3px;
  background:var(--border-strong); outline:none; cursor:pointer; }
input[type=range]::-webkit-slider-thumb { -webkit-appearance:none; width:16px; height:16px; border-radius:50%;
  background:var(--grow-600); border:2px solid var(--surface); box-shadow:var(--shadow-sm); }
input[type=range]::-moz-range-thumb { width:16px; height:16px; border-radius:50%; background:var(--grow-600);
  border:2px solid var(--surface); }
input[type=range]:disabled { cursor:not-allowed; }
input[type=range]:disabled::-webkit-slider-thumb { background:var(--fg-3); }
input[type=range]:disabled::-moz-range-thumb { background:var(--fg-3); }

/* CO2 disabled — designed, not just faded */
.ctl.co2.disabled input[type=range] { background:var(--grid-line); }
.co2-inert {
  display:none; margin-top:9px; padding:7px 10px; border-radius:var(--radius-sm);
  background:var(--surface-sunken); border:1px dashed var(--border-strong);
  font-family:var(--font-mono); font-size:11.5px; color:var(--fg-2); line-height:1.45;
}
.ctl.co2.disabled .co2-inert { display:block; }
.co2-inert strong { color:var(--fg-1); font-weight:600; }

/* ── layout ─────────────────────────────────────────────────────────────── */
.layout { display:grid; grid-template-columns:minmax(0,1.5fr) minmax(360px,1fr) minmax(320px,.85fr); gap:20px;
  align-items:start; }
@media (max-width:1500px){ .layout { grid-template-columns:minmax(0,1.5fr) minmax(360px,1fr); } }
@media (max-width:1080px){ .layout { grid-template-columns:1fr; } }
.card {
  background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-lg);
  box-shadow:var(--shadow-sm);
}
.card-h { display:flex; align-items:baseline; justify-content:space-between; gap:14px; padding:15px 18px 0; }
.card-h h2 { font-size:15px; font-weight:600; margin:0; letter-spacing:-0.005em; }
.card-h .tag { font-family:var(--font-mono); font-size:11px; color:var(--fg-3); }
.card-body { padding:12px 18px 18px; }
.side, .editcol { display:flex; flex-direction:column; gap:20px; min-width:0; }
.chartnote { font-size:12px; color:var(--fg-2); margin:6px 18px 0; line-height:1.45; }

/* ── heat map ───────────────────────────────────────────────────────────── */
.gridwrap { display:grid; grid-template-columns:22px 52px minmax(0,1fr); grid-template-rows:minmax(0,1fr) 34px 24px;
  margin-top:12px; }
.ylab { grid-column:1; grid-row:1; writing-mode:vertical-rl; transform:rotate(180deg); display:flex;
  align-items:center; justify-content:center; text-align:center; font-size:11px; color:var(--fg-2); }
.xlab { grid-column:3; grid-row:3; display:flex; align-items:center; justify-content:center; text-align:center;
  font-size:11px; color:var(--fg-2); }
.yticks { grid-column:2; grid-row:1; display:flex; flex-direction:column-reverse; }
.xticks { grid-column:3; grid-row:2; display:flex; }
.ytick { flex:1; display:flex; align-items:center; justify-content:flex-end; padding-right:6px;
  font-family:var(--font-mono); font-size:9px; color:var(--fg-3); font-variant-numeric:tabular-nums; }
.xtick { flex:1; display:flex; align-items:flex-start; justify-content:center; padding-top:5px;
  font-family:var(--font-mono); font-size:9px; color:var(--fg-3); font-variant-numeric:tabular-nums; }
.ytick.maj, .xtick.maj { color:var(--fg-1); font-weight:600; }
#heat {
  grid-column:3; grid-row:1; position:relative;
  display:grid; grid-template-columns:repeat(__GRID_N__,1fr); grid-template-rows:repeat(__GRID_N__,1fr);
  aspect-ratio:1; gap:1px; background:var(--grid-line);
  border:1px solid var(--border-strong);
}
/* ideal (dev 50) crosshair */
#heat::before, #heat::after { content:""; position:absolute; background:rgba(20,24,27,.16); z-index:5;
  pointer-events:none; }
:root[data-theme="dark"] #heat::before, :root[data-theme="dark"] #heat::after { background:rgba(255,255,255,.16); }
#heat::before { left:50%; top:0; bottom:0; width:1px; transform:translateX(-.5px); }
#heat::after { top:50%; left:0; right:0; height:1px; transform:translateY(-.5px); }
.cell { position:relative; cursor:pointer; }
.cell:hover { outline:2px solid var(--fg-1); outline-offset:-2px; z-index:8; }
.cell.sel { outline:3px solid var(--fg-1); outline-offset:-3px; z-index:9; }
/* history-dependent (relay hysteresis band) — distinct neutral + fine texture */
.cell.band { background:var(--band-fill) !important;
  background-image:radial-gradient(var(--band-stroke) 0.7px, transparent 0.8px) !important;
  background-size:4px 4px !important; }
/* would-escalate — single clean red inset outline */
.cell.escalate { box-shadow:inset 0 0 0 1.5px var(--led-red); z-index:6; }
/* conflict rule — corner wedge (moved out of the fill; no muddy hatch) */
.cell.conflict::after { content:""; position:absolute; top:0; right:0; border-width:0 7px 7px 0; border-style:solid;
  border-color:transparent var(--bloom-500) transparent transparent; z-index:7; }

/* hover tooltip */
#celltip {
  position:fixed; z-index:50; pointer-events:none; display:none;
  background:var(--fg-1); color:var(--page); font-family:var(--font-mono); font-size:11px;
  padding:6px 9px; border-radius:var(--radius-sm); box-shadow:var(--shadow-md); line-height:1.5; white-space:nowrap;
}
#celltip b { color:#fff; font-weight:600; }
:root[data-theme="dark"] #celltip { border:1px solid var(--border-strong); }

/* ── legend ─────────────────────────────────────────────────────────────── */
.legend { display:flex; flex-wrap:wrap; align-items:center; gap:14px 22px; margin-top:16px; padding-top:14px;
  border-top:1px solid var(--border); }
.ramp { display:flex; align-items:center; gap:9px; }
.ramp .cap { font-family:var(--font-mono); font-size:10.5px; color:var(--fg-2); }
#rampbar { display:flex; height:11px; width:180px; border-radius:2px; overflow:hidden;
  border:1px solid var(--border-strong); }
#rampbar span { flex:1; }
.keys { display:flex; flex-wrap:wrap; gap:12px 18px; }
.key { display:flex; align-items:center; gap:7px; font-size:11.5px; color:var(--fg-2); }
.sw { width:15px; height:15px; border-radius:2px; position:relative; flex:none; border:1px solid var(--border-strong);
  background:var(--grow-400); }
.sw.band { background:var(--band-fill); background-image:radial-gradient(var(--band-stroke) .7px,transparent .8px);
  background-size:4px 4px; }
.sw.esc { background:var(--grow-300); box-shadow:inset 0 0 0 1.5px var(--led-red); }
.sw.cfl::after { content:""; position:absolute; top:0; right:0; border-width:0 7px 7px 0; border-style:solid;
  border-color:transparent var(--bloom-500) transparent transparent; }

/* ── datasheet table ────────────────────────────────────────────────────── */
table.kv { width:100%; border-collapse:collapse; font-size:12.5px; }
table.kv td { padding:4px 0; vertical-align:baseline; }
table.kv td:first-child { color:var(--fg-2); padding-right:14px; }
table.kv td:last-child { text-align:right; font-family:var(--font-mono); font-variant-numeric:tabular-nums;
  color:var(--fg-1); white-space:nowrap; }
table.kv tr.sect td { padding:14px 0 5px; border-bottom:1px solid var(--border); }
table.kv tr.sect td { font-family:var(--font-mono); font-size:10.5px; letter-spacing:var(--tracking-caps);
  text-transform:uppercase; color:var(--fg-3); font-weight:600; text-align:left; }
table.kv tr.sect:first-child td { padding-top:2px; }
table.kv code { font-family:var(--font-mono); font-size:11.5px; color:var(--fg-1); }
/* "None — free" — meaningful, must not read as missing */
.free-tag { display:inline-flex; align-items:center; gap:6px; }
.free-tag b { font-family:var(--font-mono); font-weight:600; color:var(--grow-600); background:var(--grow-100);
  border-radius:var(--radius-pcb); padding:1px 6px; font-size:11px; }
:root[data-theme="dark"] .free-tag b { background:rgba(31,138,76,.18); }
.free-tag small { color:var(--fg-3); font-size:11px; }

/* KPI tiles */
.tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:9px; margin-bottom:4px; }
.tile { border:1px solid var(--border); border-top:3px solid var(--tilecol,var(--grow-600));
  border-radius:var(--radius-md); padding:9px 11px 10px; background:var(--surface); }
.tile .t { font-family:var(--font-mono); font-size:10px; text-transform:uppercase; letter-spacing:.05em;
  color:var(--fg-3); white-space:nowrap; }
.tile .v { font-family:var(--font-mono); font-size:22px; font-weight:600; color:var(--fg-1);
  font-variant-numeric:tabular-nums; line-height:1.15; margin-top:3px; }
.tile .v small { font-size:11px; color:var(--fg-2); font-weight:500; }

/* console-style caveat */
.console {
  margin-top:14px; background:var(--surface-sunken); border:1px solid var(--border);
    border-left:3px solid var(--led-amber);
  border-radius:var(--radius-sm); padding:9px 11px; font-family:var(--font-mono); font-size:11px; color:var(--fg-2);
    line-height:1.55;
}
.console .lv { color:var(--led-amber); font-weight:600; }

/* ── cell detail ────────────────────────────────────────────────────────── */
#detail { min-height:520px; }
.empty { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; min-height:480px;
  border:1.5px dashed var(--border-strong); border-radius:var(--radius-md); color:var(--fg-3); text-align:center;
  padding:24px; }
.empty .em-badge { width:44px; height:44px; border:2px solid var(--border-strong); border-radius:var(--radius-sm);
  position:relative; }
.empty .em-badge::before, .empty .em-badge::after { content:""; position:absolute; background:var(--border-strong); }
.empty .em-badge::before { left:50%; top:6px; bottom:6px; width:1.5px; transform:translateX(-.75px); }
.empty .em-badge::after { top:50%; left:6px; right:6px; height:1.5px; transform:translateY(-.75px); }
.empty p { margin:0; font-size:13px; }
.empty .hint { font-family:var(--font-mono); font-size:11px; color:var(--fg-3); max-width:34ch; }

.coordgrid { display:grid; grid-template-columns:1fr 1fr; gap:1px; background:var(--border);
  border:1px solid var(--border); border-radius:var(--radius-sm); overflow:hidden; margin-bottom:16px; }
.coord { background:var(--surface); padding:8px 11px; }
.coord .t { font-family:var(--font-mono); font-size:9.5px; text-transform:uppercase; letter-spacing:.05em;
  color:var(--fg-3); }
.coord .v { font-family:var(--font-mono); font-size:14px; font-weight:600; color:var(--fg-1);
  font-variant-numeric:tabular-nums; margin-top:2px; }
.coord .v small { font-size:11px; color:var(--fg-2); font-weight:400; }

/* the headline: raw -> final */
.headline { display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:8px; padding:16px 12px;
  border-radius:var(--radius-md); background:var(--surface-sunken); border:1px solid var(--border); margin-bottom:6px;
  }
.headline.changed { border-color:var(--bloom-500);
  background:linear-gradient(0deg,var(--bloom-100),var(--surface-sunken)); }
:root[data-theme="dark"] .headline.changed { background:rgba(219,42,138,.10); }
.hl-col { text-align:center; }
.hl-col .t { font-family:var(--font-mono); font-size:10px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--fg-3); }
.hl-col .n { font-family:var(--font-mono); font-size:34px; font-weight:600; color:var(--fg-1);
  font-variant-numeric:tabular-nums; line-height:1.05; }
.hl-col .n.final { color:var(--grow-600); }
.hl-col .n small { font-size:15px; color:var(--fg-2); }
.hl-arrow { font-family:var(--font-mono); font-size:22px; color:var(--fg-3); padding:0 4px; }
.hl-verdict { text-align:center; font-family:var(--font-mono); font-size:11.5px; margin:8px 0 18px; }
.hl-verdict.changed { color:var(--bloom-700); }
:root[data-theme="dark"] .hl-verdict.changed { color:var(--bloom-300); }
.hl-verdict.same { color:var(--fg-3); }
.hl-verdict strong { font-weight:600; }

.sub-h { font-family:var(--font-mono); font-size:10.5px; letter-spacing:var(--tracking-caps); text-transform:uppercase;
  color:var(--fg-3); font-weight:600; margin:20px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--border); }

/* waterfall */
.waterfall { display:flex; flex-direction:column; gap:0; }
.wf-row { display:grid; grid-template-columns:118px minmax(0,1fr) 46px; gap:10px; align-items:center; padding:5px 0; }
.wf-row .wf-name { font-size:11.5px; color:var(--fg-2); line-height:1.25; }
.wf-row.active .wf-name { color:var(--fg-1); font-weight:600; }
.wf-track { position:relative; height:15px; background:var(--surface-sunken); border-radius:2px; overflow:hidden; }
.wf-base { position:absolute; top:0; bottom:0; background:var(--grow-300); opacity:.5; }
.wf-delta { position:absolute; top:0; bottom:0; }
.wf-delta.up { background:var(--grow-600); }
.wf-delta.down { background:var(--bloom-500); }
.wf-delta.hold { background:var(--border-strong); }
.wf-val { text-align:right; font-family:var(--font-mono); font-size:12px; font-weight:600; color:var(--fg-1);
  font-variant-numeric:tabular-nums; }
.wf-note { grid-column:1 / -1; font-family:var(--font-mono); font-size:10.5px; color:var(--fg-3); line-height:1.45;
  padding:1px 0 3px 128px; }
.wf-note b { color:var(--fg-2); }
.wf-row.final { border-top:1px solid var(--border); margin-top:3px; padding-top:9px; }
.wf-row.final .wf-name { font-size:12px; font-weight:600; color:var(--fg-1); letter-spacing:.02em; }
.wf-row.final .wf-val { font-size:16px; color:var(--grow-600); }
.wf-scale { display:flex; justify-content:space-between; font-family:var(--font-mono); font-size:9px;
  color:var(--fg-3); padding:2px 46px 0 128px; }

.adnote { margin-top:12px; font-family:var(--font-mono); font-size:11.5px; color:var(--fg-2); line-height:1.5;
  background:var(--surface-sunken); border-radius:var(--radius-sm); padding:9px 11px; border:1px solid var(--border);
  }
.adnote .k { color:var(--fg-3); }

.callout { margin-top:12px; padding:10px 12px; border-radius:var(--radius-sm); font-size:12px; line-height:1.5;
  border:1px solid; }
.callout.money { background:var(--bloom-100); border-color:var(--bloom-300); color:var(--bloom-700); }
:root[data-theme="dark"] .callout.money { background:rgba(219,42,138,.12); color:var(--bloom-300);
  border-color:var(--bloom-700); }
.callout.esc { background:rgba(229,72,77,.08); border-color:var(--led-red); color:var(--led-red); }
.callout strong { font-weight:600; }
.callout .mono { color:inherit; }

/* mini slice charts */
.slices { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:8px; }
@media (max-width:460px){ .slices { grid-template-columns:1fr; } }
.slice { border:1px solid var(--border); border-radius:var(--radius-sm); padding:8px 9px 6px;
  background:var(--surface); }
.slice .st { font-family:var(--font-mono); font-size:10px; color:var(--fg-3); text-transform:uppercase;
  letter-spacing:.04em; margin-bottom:4px; }
.slice svg { display:block; width:100%; height:78px; }

/* co2 curve */
.co2curve { margin-top:6px; }
.co2curve svg { display:block; width:100%; height:150px; }
.curve-legend { display:flex; flex-wrap:wrap; gap:10px 16px; margin-top:8px; font-family:var(--font-mono);
  font-size:10.5px; color:var(--fg-2); }
.curve-legend .li { display:flex; align-items:center; gap:6px; }
.curve-legend .dash { width:16px; height:0; border-top:2px dashed currentColor; }

.footnote { margin-top:16px; font-size:11px; color:var(--fg-3); line-height:1.5; }

/* ── self-check banner ──────────────────────────────────────────────────── */
.banner {
  border-radius:var(--radius-md); padding:9px 12px; margin:0 0 16px; font-size:12.5px;
  border:1px solid var(--led-red); background:rgba(229,72,77,.08); color:var(--fg-1);
}
.banner.ok { border-color:var(--led-green); background:rgba(70,167,88,.08); }

/* ── tuning editor (not in the design mockup — same token language) ─────── */
.toggle { display:flex; align-items:center; gap:7px; font-size:12px; color:var(--fg-2); margin-bottom:2px; }
.toggle input { accent-color:var(--grow-600); }
.edgroup { margin-top:14px; }
.edgroup > .gt {
  font-family:var(--font-mono); font-size:10.5px; letter-spacing:var(--tracking-caps);
  text-transform:uppercase; color:var(--fg-3); font-weight:600;
  padding-bottom:5px; border-bottom:1px solid var(--border); margin-bottom:7px;
}
.edrow { display:grid; grid-template-columns:1fr auto auto; gap:6px; align-items:center; margin-bottom:4px;
  font-size:12px; }
.edrow label { color:var(--fg-2); }
.edrow .base { font-family:var(--font-mono); font-size:10.5px; color:var(--fg-3); font-variant-numeric:tabular-nums;
  min-width:62px; text-align:right; }
/* Scoped to the editor, not to .edrow: the band-edge row lays its inputs out in
   a plain flex strip rather than the label/value grid. */
#editor input[type=number] {
  width:76px; font-family:var(--font-mono); font-size:12px; padding:4px 6px;
  border-radius:var(--radius-sm); border:1px solid var(--border-strong);
  background:var(--surface-sunken); color:var(--fg-1);
  font-variant-numeric:tabular-nums; text-align:right;
}
#editor input.dirty { border-color:var(--grow-600); box-shadow:inset 0 0 0 1px var(--grow-600); }
.edges { display:flex; gap:4px; flex-wrap:wrap; margin-bottom:4px; }
.edges input[type=number] { width:54px !important; }
.edactions { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }
.edactions button {
  font-family:var(--font-mono); font-size:11.5px; padding:6px 12px; cursor:pointer;
  border-radius:var(--radius-md); border:1px solid var(--border-strong);
  background:var(--surface); color:var(--fg-1);
}
.edactions button:hover { border-color:var(--grow-600); color:var(--grow-600); }
.edactions button.primary { background:var(--grow-600); border-color:var(--grow-600); color:#fff; }
.edactions button.primary:hover { opacity:.9; color:#fff; }
.edactions button:disabled { opacity:.45; cursor:not-allowed; border-color:var(--border-strong); color:var(--fg-3); }
/* ── species-profile editor ─────────────────────────────────────────────── */
/* Three anchor columns per row, captioned once per phase. The label column
   flexes so the widest dimension name ("temperature") sets it; the inputs are
   fixed-width so at_0/ideal/at_100 line up down the whole card. */
.profgrid { display:grid; grid-template-columns:1fr repeat(3, 58px); gap:4px 6px; align-items:center; }
.profgrid .cap {
  font-family:var(--font-mono); font-size:9.5px; letter-spacing:.04em; text-transform:uppercase;
  color:var(--fg-3); text-align:center; padding-bottom:2px;
}
.profgrid .rl { font-size:12px; color:var(--fg-2); }
.profgrid .rl small { display:block; font-family:var(--font-mono); font-size:9.5px; color:var(--fg-3); }
.profgrid input[type=number] {
  width:100%; font-family:var(--font-mono); font-size:11.5px; padding:4px 5px; text-align:right;
  color:var(--fg-1); background:var(--surface); border:1px solid var(--border-strong);
  border-radius:var(--radius-sm); font-variant-numeric:tabular-nums;
}
.profgrid input.dirty { border-color:var(--grow-600); box-shadow:inset 0 0 0 1px var(--grow-600); }
.profgrid input.bad { border-color:var(--led-red); box-shadow:inset 0 0 0 1px var(--led-red); }
.schedrow { display:grid; grid-template-columns:1fr 72px auto; gap:4px 8px; align-items:center; margin-bottom:4px;
  font-size:12px; }
.schedrow label { color:var(--fg-2); }
.schedrow input[type=number] {
  width:100%; font-family:var(--font-mono); font-size:11.5px; padding:4px 5px; text-align:right;
  color:var(--fg-1); background:var(--surface); border:1px solid var(--border-strong);
  border-radius:var(--radius-sm); font-variant-numeric:tabular-nums;
}
.schedrow input.dirty { border-color:var(--grow-600); box-shadow:inset 0 0 0 1px var(--grow-600); }
.schedrow input.bad { border-color:var(--led-red); box-shadow:inset 0 0 0 1px var(--led-red); }
.schedrow .clk { font-family:var(--font-mono); font-size:10.5px; color:var(--fg-3);
  font-variant-numeric:tabular-nums; }
.profwarn {
  margin-top:10px; padding:7px 10px; border-radius:var(--radius-sm);
  border:1px solid var(--led-red); background:rgba(198,64,58,.08);
  font-size:11.5px; color:var(--fg-1); line-height:1.45;
}
.profwarn:empty { display:none; }
/* Compact rail for the two mode switches that sit under / beside a slider. */
.segrail.mini { border-radius:var(--radius-sm); }
.segrail.mini button { padding:5px 10px; font-size:11px; }
.todmode { margin-top:9px; align-self:flex-start; }

.dirtynote { font-size:11.5px; color:var(--fg-2); border-left:3px solid var(--grow-600); padding:4px 0 4px 9px;
  margin:10px 0 0; }
#exportWrap { margin-top:12px; }
#exportWrap textarea {
  width:100%; height:260px; font-family:var(--font-mono); font-size:11.5px; line-height:1.45;
  padding:9px; border-radius:var(--radius-md); border:1px solid var(--border-strong);
  background:var(--surface-sunken); color:var(--fg-1);
  white-space:pre; overflow:auto; resize:vertical;
}
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
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pi Greenhouse — regulation surface explorer</title>
"""

_HTML_BODY = """<div class="topbar">
  <div>
    <div class="brandline"><span class="brand-dot"></span>
      <span class="eyebrow">Pi Greenhouse · regulation engine</span></div>
    <h1>Regulation surface explorer</h1>
    <p class="sub">Each cell is coloured by the <strong>final effective actuator output</strong> &mdash; the command
    after the surface (or follower / time-of-day driver), the CO&#8322; additive term, the external-effectiveness
    multiplier, the floor, the conflict rules, and the device adapter. Click a cell to compare the
    <strong>raw surface value against what the actuator actually does</strong>. Generated from
    <code>config.py</code>; the species profile and the tuning parameters on the right are
    <strong>editable</strong> &mdash; anchors, day/night schedule, surfaces, floors, adapter thresholds and
    band edges &mdash; the plot recomputes live, and <em>Export changes</em> gives a paste-ready
    <code>config.py</code> fragment. Nothing here writes to the repo.</p>
  </div>
  <div class="themetoggle" role="group" aria-label="Surface theme">
    <button id="thLight" aria-pressed="true">Paper</button>
    <button id="thDark" aria-pressed="false">Terminal</button>
  </div>
</div>

<div id="selfcheck"></div>

<div class="controls">
  <div class="ctl-row">
    <div class="ctl" style="flex:1 1 100%">
      <span class="eyebrow ctl-label">Regulator</span>
      <div class="segrail" id="reg" role="group" aria-label="Regulator"></div>
    </div>
  </div>
  <div class="ctl-row">
    <div class="ctl">
      <span class="eyebrow ctl-label">Species profile</span>
      <select id="prof"></select>
    </div>
    <div class="ctl">
      <span class="eyebrow ctl-label">Axis ticks</span>
      <div class="segrail mini" id="axisMode" role="group" aria-label="Axis tick units">
        <button type="button" data-axis="dev">deviation</button>
        <button type="button" data-axis="phys">physical</button>
      </div>
    </div>
    <div class="ctl grow">
      <div class="slider-head"><span class="eyebrow" id="todLabel">Time of day (blend b)</span>
        <span class="readout" id="todOut"></span></div>
      <input type="range" id="tod" min="0" max="1" step="0.05" value="1">
      <div class="segrail mini todmode" id="todMode" role="group" aria-label="Time-of-day input mode">
        <button type="button" data-mode="b">set b</button>
        <button type="button" data-mode="clock">set clock</button>
      </div>
    </div>
    <div class="ctl grow co2" id="co2Ctl">
      <div class="slider-head"><span class="eyebrow">CO&#8322; deviation</span>
        <span class="readout" id="co2Out"></span></div>
      <input type="range" id="co2" min="0" max="100" step="1" value="50">
      <div class="co2-inert" id="co2Inert"></div>
    </div>
  </div>
</div>

<div class="layout">
  <div class="card">
    <div class="card-h">
      <h2 id="chartTitle"></h2>
      <span class="tag mono" id="gridTag"></span>
    </div>
    <p class="chartnote" id="chartNote"></p>
    <div class="card-body">
      <div class="gridwrap">
        <div class="ylab" id="ylab"></div>
        <div class="yticks" id="yticks"></div>
        <div id="heat"></div>
        <div class="xticks" id="xticks"></div>
        <div class="xlab" id="xlab"></div>
      </div>
      <div class="legend">
        <div class="ramp">
          <span class="cap">0</span>
          <div id="rampbar"></div>
          <span class="cap">100 % duty</span>
        </div>
        <div class="keys">
          <div class="key"><span class="sw band"></span> history-dependent</div>
          <div class="key"><span class="sw esc"></span> would escalate</div>
          <div class="key"><span class="sw cfl"></span> conflict rule fires</div>
        </div>
      </div>
    </div>
  </div>

  <div class="side">
    <div class="card">
      <div class="card-h"><h2>Cell detail</h2><span class="tag mono" id="detailTag"></span></div>
      <div class="card-body"><div id="detail"></div></div>
    </div>
    <div class="card">
      <div class="card-h"><h2 id="aggTitle">Regulator</h2><span class="tag mono">config.py</span></div>
      <div class="card-body"><div id="agg"></div></div>
    </div>
  </div>

  <div class="editcol">
    <div class="card">
      <div class="card-h"><h2>Species profile</h2><span class="tag mono" id="profTag"></span></div>
      <div class="card-body">
        <p class="note">Anchors are physical values: <strong>at&nbsp;0</strong> = far too low (deviation 0),
        <strong>ideal</strong> = deviation 50, <strong>at&nbsp;100</strong> = far too high (deviation 100).
        They define what each deviation <em>means</em> for this species &mdash; no surface reads &deg;C or %RH,
        so editing them moves the axis values, the tooltips and the cell detail, not the plotted duty.
        The effective anchor is <code>night + b&nbsp;&times;&nbsp;(day &minus; night)</code>.</p>
        <div id="profeditor"></div>
        <div id="profWarn" class="profwarn"></div>
        <div class="edactions">
          <button id="btnCopyNight">Night &larr; day</button>
          <button id="btnResetProf">Reset profile</button>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h2>Tuning</h2><span class="tag mono" id="edSubtitle"></span></div>
      <div class="card-body">
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
            <code>_surface(...)</code> call listing every non-default parameter, and profile
            blocks as the whole species entry, so both replace what is there outright.
            A changed <strong>surface</strong> also needs the golden vectors regenerated
            &mdash; <code>python prototypes/plot_regulation_surfaces.py</code> &mdash; or the
            surface tests will fail; profile, schedule and adapter edits do not touch them.</p>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="celltip"></div>

<p class="footnote mono">Surface grids are baked from <code>lib/regulation_surface.evaluate</code> at generate time
and re-evaluated live in-browser by a JS port of the same maths &mdash; the banner above proves the two agree.
Fonts fall back to the system stack (offline file, no webfonts).</p>
"""

_JS = r"""
"use strict";
const D = JSON.parse(document.getElementById("regdata").textContent);
const G = D.grid, N = G.length;

const el = id => document.getElementById(id);
const fmt = (v, d) => (v === null || v === undefined) ? "—" : Number(v).toFixed(d === undefined ? 1 : d);

/* ---------- state -----------------------------------------------------
   Controls persist across regenerations (localStorage) so a tuning session
   survives a page rebuild; anything stored is validated against the data. */

let state = {
  reg: localStorage.getItem("rse.reg") || "exhaust",
  profile: localStorage.getItem("rse.profile") || D.activeProfile,
  b: parseFloat(localStorage.getItem("rse.b") ?? "1"),
  // Wall-clock minute behind the "set clock" mode of the time-of-day control.
  // Defaults to noon, which is inside every sane day window.
  clockMin: parseInt(localStorage.getItem("rse.clock") ?? "720", 10),
  todMode: localStorage.getItem("rse.todmode") || "b",
  axis: localStorage.getItem("rse.axis") || "dev",
  co2dev: parseInt(localStorage.getItem("rse.co2") ?? "50", 10),
  sel: null,
  showAll: false
};
if (!D.regNames.includes(state.reg)) state.reg = "exhaust";
if (!D.profiles[state.profile]) state.profile = D.activeProfile;
if (!Number.isFinite(state.b)) state.b = 1.0;
state.b = Math.min(1, Math.max(0, state.b));
if (!Number.isFinite(state.clockMin)) state.clockMin = 720;
state.clockMin = Math.min(1435, Math.max(0, state.clockMin));
if (state.todMode !== "clock") state.todMode = "b";
if (state.axis !== "phys") state.axis = "dev";
if (!Number.isFinite(state.co2dev)) state.co2dev = 50;
state.co2dev = Math.min(100, Math.max(0, state.co2dev));

/* ---------- live, editable config ------------------------------------
   D is the frozen baseline exactly as config.py has it. LIVE is the copy the
   page edits and plots; every "has this changed?" question compares the two.
   Profiles and the day/night window get the same treatment as the regulators:
   edited in place, diffed against D, exported as a config fragment. */

const DEF = D.surfaceDefaults, META = D.surfaceMeta;
const clone = o => JSON.parse(JSON.stringify(o));
let LIVE = clone(D.regulators);
let LIVE_EDGES = D.bandEdges.slice();
let LIVE_PROFILES = clone(D.profiles);
let LIVE_SCHED = Object.assign({}, D.schedule);
const PHASES = ["day", "night"];
const SCHED_KEYS = ["day_start_min", "day_end_min", "transition_min"];

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

/* ---------- time of day ------------------------------------------------
   A port of lib/regulation_normalizer.blend_factor, so the "set clock" mode of
   the ToD control derives b the way the device does — which is what makes the
   editable day window mean anything on this page. */

function blendFactor(minutes, dayStart, dayEnd, transition) {
  if (minutes < dayStart || minutes >= dayEnd) return 0.0;
  if (transition <= 0) return 1.0;
  const half = (dayEnd - dayStart) * 0.5;
  const ramp = transition < half ? transition : half;
  if (ramp <= 0) return 1.0;
  const into = minutes - dayStart, left = dayEnd - minutes;
  if (into < ramp) return into / ramp;
  if (left < ramp) return left / ramp;
  return 1.0;
}

// The single source of b for the whole page: either dragged directly, or
// derived from the clock through the (editable) day window.
function currentB() {
  if (state.todMode !== "clock") return state.b;
  return blendFactor(state.clockMin, LIVE_SCHED.day_start_min,
                     LIVE_SCHED.day_end_min, LIVE_SCHED.transition_min);
}

function hhmm(min) {
  const m = ((Math.round(min) % 1440) + 1440) % 1440;
  return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
}

/* ---------- deviation <-> physical ---------------------------------- */

function anchors(dim) {
  const p = LIVE_PROFILES[state.profile], b = currentB();
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
// Regulators that carry the CO2 additive term — the slider only means
// something for these (the exhaust and the circulation pair, per config).
function co2Regs() {
  return D.regNames.filter(n => LIVE[n].co2Gain !== undefined);
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
  if (R.driven === "tod") return clamp(currentB() * R.lightLevelDay);
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

/* ---------- colour ----------------------------------------------------
   Single-hue grow-green sequential ramp, one per theme, validated against
   both page surfaces in the design pass (see the redesign notes). The fill is
   interpolated so it reads as continuous, not stepped; history-dependent
   cells leave the ramp entirely (warm grey + dot texture, via CSS). */

const RAMP = {
  light: ["#cfe4d6","#a6d4b4","#7cc194","#54ad74","#33995a","#22894e","#1a7342","#125c34","#0c3d22"],
  dark:  ["#0f2a1f","#16452c","#1a6338","#1f8a4c","#2aa860","#48c07c","#77d69e","#a8e8c4","#d9f2e2"],
};
function ramp() { return document.documentElement.dataset.theme === "dark" ? RAMP.dark : RAMP.light; }
function hex2rgb(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
function lerpRamp(t) {
  const r = ramp(); t = Math.max(0, Math.min(1, t));
  const x = t * (r.length - 1), i = Math.floor(x), f = x - i;
  if (i >= r.length - 1) return r[r.length - 1];
  const a = hex2rgb(r[i]), b = hex2rgb(r[i + 1]);
  const c = k => Math.round(a[k] + (b[k] - a[k]) * f);
  return `rgb(${c(0)},${c(1)},${c(2)})`;
}
function colourFor(rr) {
  if (rr.state === "band" || rr.duty === null) return "var(--band-fill)";
  return lerpRamp(rr.duty / 100);
}

/* ---------- controls --------------------------------------------------- */

function buildControls() {
  const reg = el("reg");
  reg.innerHTML = D.regNames.map(n => `<button type="button" data-reg="${n}">${n}</button>`).join("");
  reg.querySelectorAll("button").forEach(b => {
    b.onclick = () => {
      state.reg = b.dataset.reg; state.sel = null;
      localStorage.setItem("rse.reg", state.reg);
      render(); renderEditor();
    };
  });
  const prof = el("prof");
  prof.innerHTML = Object.keys(D.profiles)
    .map(n => `<option value="${n}">${n} · ${D.profiles[n].category}</option>`).join("");
  prof.value = state.profile;
  prof.onchange = () => {
    state.profile = prof.value;
    localStorage.setItem("rse.profile", state.profile);
    render(); renderProfileEditor();
  };

  const axis = el("axisMode");
  axis.querySelectorAll("button").forEach(b => {
    b.onclick = () => {
      state.axis = b.dataset.axis;
      localStorage.setItem("rse.axis", state.axis);
      render();
    };
  });

  const todm = el("todMode");
  todm.querySelectorAll("button").forEach(b => {
    b.onclick = () => {
      state.todMode = b.dataset.mode;
      localStorage.setItem("rse.todmode", state.todMode);
      syncTodSlider();
      render();
    };
  });
  syncTodSlider();
  el("tod").oninput = e => {
    if (state.todMode === "clock") {
      state.clockMin = parseInt(e.target.value, 10);
      localStorage.setItem("rse.clock", state.clockMin);
    } else {
      state.b = parseFloat(e.target.value);
      localStorage.setItem("rse.b", state.b);
    }
    render();
  };
  el("co2").value = state.co2dev;
  el("co2").oninput = e => {
    state.co2dev = parseInt(e.target.value, 10);
    localStorage.setItem("rse.co2", state.co2dev);
    render();
  };

  el("gridTag").textContent = `${N} × ${N} · ${N * N} cells`;
  el("thLight").onclick = () => setTheme("light");
  el("thDark").onclick = () => setTheme("dark");
}

// The ToD slider is one control in two units: blend factor 0-1, or minutes past
// midnight. Retarget its range and value whenever the mode changes.
function syncTodSlider() {
  const s = el("tod"), clock = state.todMode === "clock";
  s.min = 0;
  s.max = clock ? 1435 : 1;
  s.step = clock ? 5 : 0.05;
  s.value = clock ? state.clockMin : state.b;
  el("todLabel").textContent = clock ? "Time of day (clock)" : "Time of day (blend b)";
  el("todMode").querySelectorAll("button")
    .forEach(b => b.setAttribute("aria-pressed", b.dataset.mode === state.todMode));
}

function setTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("rse.theme", t);
  el("thLight").setAttribute("aria-pressed", t === "light");
  el("thDark").setAttribute("aria-pressed", t === "dark");
  render();  // the ramp is theme-dependent — recolour every cell
}

/* ---------- render: heat map + axes + legend --------------------------- */

function tipHTML(reg, xi, yi, r) {
  const R = LIVE[reg], dx = R.dims[0], dy = R.dims[1];
  return `<b>${D.dimLabels[dx]}</b> dev ${G[xi]} · <b>${D.dimLabels[dy]}</b> dev ${G[yi]}<br>`
    + `raw <b>${fmt(r.raw)}</b> → final <b>${r.duty === null ? "history-dep." : fmt(r.duty) + "%"}</b>`;
}

function render() {
  const reg = state.reg, R = LIVE[reg];
  const takesCo2 = R.co2Gain !== undefined;

  el("reg").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b.dataset.reg === reg));

  // The CO2 slider only means something for a regulator carrying the additive
  // term — disable it for the rest, with the inert note saying WHY.
  const cc = el("co2Ctl");
  cc.classList.toggle("disabled", !takesCo2);
  el("co2").disabled = !takesCo2;
  el("co2Out").textContent = "dev " + state.co2dev + " · " + physLabel(state.co2dev, "co2");
  el("co2Inert").innerHTML = takesCo2 ? "" :
    `Inert for <strong>${reg}</strong> — CO&#8322; enters the engine only as the additive term on
     regulators carrying <strong>co2_gain</strong> (${co2Regs().join(", ")}). No surface takes
     CO&#8322; as a dimension, so this slider has <strong>no effect</strong> here.`;

  const b = currentB();
  el("todOut").textContent = (state.todMode === "clock" ? hhmm(state.clockMin) + " · " : "")
    + "b = " + b.toFixed(2) + " · "
    + (b >= 1 ? "full day" : b <= 0 ? "full night" : "transition");

  // Axes. In deviation mode: the number every other tick (majors at 0/50/100
  // bold), physical anchors in the axis title, exact values in the detail
  // panel. In physical mode the ticks carry the profile's own units instead —
  // at the quarters only, because "24.0" needs four times the room "40" does,
  // and on the quarters specifically so that dev 50 (ideal, the one value an
  // operator looks for) always carries a number.
  // The cells never move: the deviation grid is evenly spaced, so physical
  // ticks are unevenly VALUED either side of ideal whenever the profile's
  // anchors are asymmetric. The axis title says so.
  const dx = R.dims[0], dy = R.dims[1];
  const ax = anchors(dx), ay = anchors(dy);
  const dp = d => d === "co2" ? 0 : 1;
  const phys = state.axis === "phys";
  const axisTitle = (dim, a) => phys
    ? `${D.dimLabels[dim]} → <span class="mono" style="color:var(--fg-3)">${D.dimUnits[dim]}`
      + ` · non-linear at ideal ${a.a50.toFixed(dp(dim))}</span>`
    : `${D.dimLabels[dim]} deviation → <span class="mono" style="color:var(--fg-3)">`
      + `${a.a0.toFixed(dp(dim))} · ${a.a50.toFixed(dp(dim))} · ${a.a100.toFixed(dp(dim))}`
      + ` ${D.dimUnits[dim]}</span>`;
  el("xlab").innerHTML = axisTitle(dx, ax);
  el("ylab").innerHTML = axisTitle(dy, ay);
  const tickCls = v => (v % 50 === 0) ? " maj" : "";
  const tickText = (v, i, dim, a) => {
    if (!phys) return i % 2 === 0 ? String(v) : "";
    return v % 25 === 0 ? devToPhys(v, a).toFixed(dp(dim)) : "";
  };
  el("xticks").innerHTML = G.map((v, i) =>
    `<div class="xtick${tickCls(v)}">${tickText(v, i, dx, ax)}</div>`).join("");
  el("yticks").innerHTML = G.map((v, i) =>
    `<div class="ytick${tickCls(v)}">${tickText(v, i, dy, ay)}</div>`).join("");
  el("axisMode").querySelectorAll("button")
    .forEach(b => b.setAttribute("aria-pressed", b.dataset.axis === state.axis));

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
      c._tip = tipHTML(reg, xi, yi, r);
      c.onclick = () => { state.sel = [xi, yi]; render(); };
      frag.appendChild(c);
    }
  }
  heat.replaceChildren(frag);
  el("rampbar").innerHTML = ramp().map(c => `<span style="background:${c}"></span>`).join("");

  renderAgg(reg, R, results);
  renderDetail(reg, R);
}

function chartNote(R, reg) {
  if (R.driven === "tod") {
    return "No surface: the grow light is driven by the time-of-day blend alone, so the grid is "
      + "uniform. The axes are a frame only — move the ToD slider to change the value.";
  }
  if (R.driven === "follower") {
    return "No surface of its own: the command is the heater's organic command × "
      + R.followerGain + " + " + R.followerFloor + ", so the shape follows the heater.";
  }
  if (R.adapter.type === "pwm" || R.adapter.type === "pwm_pair") {
    return "PWM duty as commanded (pre-inversion — the PCA9685 invert flag lives in the output driver)."
      + (R.co2Gain !== undefined ? " The CO₂ slider adds its term on top of this surface." : "");
  }
  if (R.adapter.type === "heater") {
    return "Time-proportioned over a " + R.adapter.window_s + " s window, so the plotted duty is the "
      + "average — the MOSFET itself is on/off.";
  }
  return "Relay actuator: the output is binary. Cells above on_above are ON, below off_below are OFF; "
    + "the textured band between — thresholds included — depends on the previous state.";
}

/* hover tooltip via delegation — replaces the native title attribute */
(function () {
  const tip = document.getElementById("celltip");
  document.addEventListener("mouseover", e => {
    const c = e.target.closest && e.target.closest(".cell");
    if (c && c._tip) { tip.innerHTML = c._tip; tip.style.display = "block"; }
  });
  document.addEventListener("mousemove", e => {
    if (tip.style.display !== "block") return;
    let x = e.clientX + 14, y = e.clientY + 16;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > innerHeight - 8) y = e.clientY - h - 16;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  });
  document.addEventListener("mouseout", e => {
    const c = e.target.closest && e.target.closest(".cell");
    if (c) tip.style.display = "none";
  });
})();

/* ---------- aggregation panel ------------------------------------------ */

// "None — free" is meaningful (the regulator stays under its own control
// during an emergency) and must not read as a missing value.
function freeCell(v) {
  return v === null ? `<span class="free-tag"><b>free</b><small>none — under own control</small></span>` : fmt(v);
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
  const tile = (t, v, u, col) => `<div class="tile" style="--tilecol:${col}"><div class="t">${t}</div>`
    + `<div class="v">${fmt(v)}${u ? `<small> ${u}</small>` : ""}</div></div>`;

  let h = `<div class="tiles">
    ${tile("final · min", sf.min, "%", "var(--grow-400)")}
    ${tile("final · mean", sf.mean, "%", "var(--grow-600)")}
    ${tile("final · max", sf.max, "%", "var(--grow-900)")}
    <div class="tile" style="--tilecol:var(--led-blue)"><div class="t">cells</div>
      <div class="v">${results.length}</div></div>
  </div>
  <table class="kv">
    <tr class="sect"><td colspan="2">Raw surface · sampled</td></tr>
    <tr><td>min / mean / max</td><td>${fmt(sr.min)} / ${fmt(sr.mean)} / ${fmt(sr.max)}</td></tr>`;

  if (bandCount) {
    h += `<tr><td>history-dependent cells</td><td>${bandCount} · excluded from final stats</td></tr>`;
  }
  h += `<tr><td>would escalate</td><td>${escCount} emergency / ${latchCount} latch</td></tr>
    <tr><td>hit by a conflict rule</td><td>${cflCount}</td></tr>

    <tr class="sect"><td colspan="2">Arbitration · config.py</td></tr>
    <tr><td>driven</td><td>${R.driven}</td></tr>
    <tr><td>floor</td><td>${fmt(R.floor)} · forced at sev ≥ ${fmt(eMinor(), 0)}</td></tr>
    <tr><td>emergency_value</td><td>${freeCell(R.emergencyValue)}</td></tr>
    <tr><td>safe_state</td><td>${freeCell(R.safeState)}</td></tr>
    <tr><td>slew normal / fast</td><td>${fmt(R.slewNormal)} / ${fmt(R.slewFast)} per tick</td></tr>
    <tr><td>band dims</td><td>${R.bandDims.length ? R.bandDims.join(", ") : "— · band 0"}</td></tr>

    <tr class="sect"><td colspan="2">Adapter · ${a.type}</td></tr>`;

  if (a.pin_key) h += `<tr><td>pin_key</td><td><code>${a.pin_key}</code></td></tr>`;
  if (a.pca9685_ch !== undefined) h += `<tr><td>PCA9685 channel</td><td>ch${a.pca9685_ch}</td></tr>`;
  if (a.center_ch !== undefined) {
    h += `<tr><td>channels</td><td>center ch${a.center_ch} × ${a.center_scale}, `
      + `wall ch${a.wall_ch} × ${a.wall_scale}</td></tr>`;
  }
  if (a.on_above !== undefined) {
    h += `<tr><td>on_above / off_below</td><td>${fmt(a.on_above)} / ${fmt(a.off_below)}</td></tr>`;
  }
  if (a.window_s !== undefined) h += `<tr><td>window_s</td><td>${a.window_s} s</td></tr>`;
  if (a.min_on_s !== undefined) {
    h += `<tr><td>min_on_s / min_off_s</td><td>${a.min_on_s} / ${a.min_off_s} s</td></tr>`;
  }
  if (a.dac_max_pct !== undefined) {
    h += `<tr><td>dac_max_pct</td><td>${a.dac_max_pct} % · ${R.dimmable ? "applied" : "unused (relay-only)"}</td></tr>`;
  }
  h += `</table>`;

  if (R.co2Gain !== undefined) {
    h += `<div class="sub-h" style="margin-top:20px">CO₂ additive term</div>` + co2CurveHTML(R);
    // The ceiling of the term is gain*(100-break). If that sits under the
    // floor, the floor forces the command up and CO2 changes nothing anywhere
    // in the profile's range — the exact bug this repo shipped twice.
    const ceiling = R.co2Gain * (100 - R.co2Break);
    if (ceiling <= R.floor) {
      h += `<div class="callout money"><strong>CO₂ term tops out at ${fmt(ceiling)}, under the floor of
        ${fmt(R.floor)} — CO₂ cannot move this actuator at any concentration.</strong></div>`;
    }
  }

  h += `<div class="console"><span class="lv">NOTE</span> Not drawn per cell: slew limiting
    (${fmt(R.slewNormal)}/${fmt(R.slewFast)} per ${D.tickS} s tick) needs the previous command;
    emergency / latch need ${D.latch.enter_ticks} consecutive ticks past the escalation edge.
    Escalation is gated to `
    + (Object.keys(D.escalation).filter(d => D.escalation[d].high || D.escalation[d].low)
      .map(d => D.dimLabels[d] + (D.escalation[d].high ? " high" : "") + (D.escalation[d].low ? " low" : ""))
      .join(", ") || "nothing")
    + ` — outlined cells are where that gated severity reaches ${fmt(eEmerg(), 0)}.</div>`;
  el("agg").innerHTML = h;
}

/* CO2 response curve — the additive term vs CO2 deviation, annotated with the
   deadband end, the point the term clears the floor, saturation, the floor
   level and the live slider position. Replaces three table rows. */
function co2CurveHTML(R) {
  const W = 100, H = 100;
  const term = dev => { const over = dev - R.co2Break; return over > 0 ? Math.min(100, R.co2Gain * over) : 0; };
  const ca = anchors("co2");
  const pts = []; for (let dev = 0; dev <= 100; dev += 2) pts.push([dev, term(dev)]);
  const sx = dev => (dev / 100) * W;
  const sy = v => H - (v / 100) * H;
  const poly = pts.map(p => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ");
  // co2_gain of 0 is a legal config value and disables the term entirely.
  const devFloor = R.co2Gain > 0 ? R.co2Break + R.floor / R.co2Gain : null;
  const devSat = R.co2Gain > 0 ? Math.min(100, R.co2Break + 100 / R.co2Gain) : null;
  const cur = state.co2dev;
  const vline = (dev, col, dash) => {
    if (dev === null || dev > 100) return "";
    const x = sx(dev).toFixed(1);
    return `<line x1="${x}" y1="0" x2="${x}" y2="${H}" stroke="${col}" stroke-width="1"`
      + (dash ? ` stroke-dasharray="3 2"` : "") + `/>`;
  };
  const ppmAt = d => (d === null || d > 100) ? "—" : `${devToPhys(d, ca).toFixed(0)} ppm`;
  const fy = (H - (R.floor / 100) * H).toFixed(1);
  const cx = sx(cur).toFixed(1);
  return `<div class="co2curve">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <line x1="0" y1="${H}" x2="${W}" y2="${H}" stroke="var(--border-strong)" stroke-width="1"/>
      <line x1="0" y1="${fy}" x2="${W}" y2="${fy}" stroke="var(--led-amber)"
        stroke-width="1" stroke-dasharray="3 2"/>
      ${vline(R.co2Break, "var(--fg-3)", true)}
      ${vline(devFloor, "var(--grow-600)", true)}
      ${vline(devSat, "var(--bloom-500)", true)}
      <polyline points="${poly}" fill="none" stroke="var(--grow-600)" stroke-width="2"
        vector-effect="non-scaling-stroke"/>
      <line x1="${cx}" y1="0" x2="${cx}" y2="${H}" stroke="var(--fg-1)" stroke-width="1.5"
        vector-effect="non-scaling-stroke"/>
    </svg>
    <div class="curve-legend">
      <span class="li" style="color:var(--fg-1)"><span
        style="width:2px;height:12px;background:currentColor;display:inline-block"></span>
        now: dev ${cur} · ${term(cur).toFixed(1)} term</span>
      <span class="li" style="color:var(--fg-3)"><span class="dash"></span> deadband ends ${ppmAt(R.co2Break)}</span>
      <span class="li" style="color:var(--grow-600)"><span class="dash"></span> clears floor ${ppmAt(devFloor)}</span>
      <span class="li" style="color:var(--bloom-500)"><span class="dash"></span> saturates ${ppmAt(devSat)}</span>
      <span class="li" style="color:var(--led-amber)"><span class="dash"></span> floor ${fmt(R.floor)}</span>
    </div>
    <table class="kv" style="margin-top:8px"><tr><td>co2_gain / co2_break</td>
      <td>${fmt(R.co2Gain, 2)} / ${fmt(R.co2Break)}</td></tr>
    <tr><td>external multiplier</td><td>${!R.external
      ? "not applied to this regulator"
      : D.externalSensor.enabled
      ? "enabled — not modelled; device range ×" + fmt(externalMultRange(), 2) + "–1.00"
      : "sensor off · constant 1.0"}</td></tr></table>
  </div>`;
}

/* ---------- cell detail: headline + waterfall + adapter + slices ------- */

function renderDetail(reg, R) {
  const dt = el("detail"), tagEl = el("detailTag");
  if (!state.sel) {
    tagEl.textContent = "";
    dt.innerHTML = `<div class="empty"><div class="em-badge"></div>
      <p>Click any cell to inspect its pipeline.</p>
      <p class="hint">You'll see the raw surface value beside what the actuator actually does,
      and the stage that changed it.</p></div>`;
    return;
  }
  const takesCo2 = R.co2Gain !== undefined;
  const [xi, yi] = state.sel;
  const r = pipeline(reg, xi, yi);
  const dx = R.dims[0], dy = R.dims[1];
  tagEl.textContent = `${dx} ${G[xi]} · ${dy} ${G[yi]}`;
  const finalTxt = r.duty === null ? "history" : fmt(r.duty);
  const finalUnit = r.duty === null ? "" : "%";

  // --- headline: raw vs final — the money comparison ---
  const delta = r.duty === null ? null : r.duty - r.raw;
  const changed = delta !== null && Math.abs(delta) >= 0.05;
  const mover = moverStage(r, R, takesCo2);
  let h = `<div class="coordgrid">
      <div class="coord"><div class="t">${D.dimLabels[dx]} dev</div>
        <div class="v">${G[xi]} <small>· ${physLabel(G[xi], dx)}</small></div></div>
      <div class="coord"><div class="t">${D.dimLabels[dy]} dev</div>
        <div class="v">${G[yi]} <small>· ${physLabel(G[yi], dy)}</small></div></div>
      <div class="coord"><div class="t">CO₂ dev</div>
        <div class="v">${state.co2dev} <small>· ${physLabel(state.co2dev, "co2")}</small></div></div>
      <div class="coord"><div class="t">severity · this / global</div>
        <div class="v">${fmt(r.regSev, 0)} / ${fmt(r.gmax, 0)}</div></div>
    </div>
    <div class="headline ${changed ? "changed" : ""}">
      <div class="hl-col"><div class="t">raw surface</div><div class="n">${fmt(r.raw)}</div></div>
      <div class="hl-arrow">→</div>
      <div class="hl-col"><div class="t">actuator does</div>
        <div class="n final">${finalTxt}<small>${finalUnit}</small></div></div>
    </div>
    <div class="hl-verdict ${changed ? "changed" : "same"}">${
      changed
        ? `<strong>${delta > 0 ? "+" : ""}${fmt(delta)}</strong> — the ${mover} changed it.
           The surface is <strong>not</strong> what the actuator does here.`
        : (r.duty === null
          ? `history-dependent — the relay holds its previous state in this band`
          : `raw = final — the surface passes straight through`)
    }</div>`;

  h += `<div class="sub-h">Stage waterfall</div>` + waterfallHTML(reg, R, r, takesCo2);
  h += `<div class="adnote"><span class="k">adapter · ${r.kind}</span> — ${adapterNote(R, r)}</div>`;

  if (r.escEmergency) {
    const latchTxt = r.escLatch ? ` (≥ latch ${fmt(eLatch(), 0)})` : "";
    h += `<div class="callout esc"><strong>Would escalate.</strong> gated severity
      <span class="mono">${fmt(r.esc, 0)} ≥ ${fmt(eEmerg(), 0)}</span>${latchTxt},
      held ${D.latch.enter_ticks} ticks. Forced to
      <strong>${R.emergencyValue === null ? "free" : fmt(R.emergencyValue) + " %"}</strong> in emergency,
      <strong>${R.safeState === null ? "free" : fmt(R.safeState) + " %"}</strong> under latch —
      overriding everything above.</div>`;
  }

  h += `<div class="sub-h">1-D slices through this cell</div>` + slicesHTML(reg, R, xi, yi);

  dt.innerHTML = h;
}

function moverStage(r, R, takesCo2) {
  if (r.conflictFired && Math.abs(r.command - r.floored) >= 0.05) return "conflict rule";
  if (r.floorFired) return "floor";
  if (takesCo2 && r.co2Term > 0) return "CO₂ term";
  return "adapter";
}

/* Stage waterfall — a floating-bar bridge from raw surface through each stage
   to FINAL, with the stage that actually moved the value highlighted and its
   note shown only when it fired. */
function waterfallHTML(reg, R, r, takesCo2) {
  const seq = [];
  seq.push({ name: "raw surface", val: r.raw, from: 0, note: null });
  if (takesCo2) {
    const v1 = clamp(r.raw + r.co2Term);
    seq.push({ name: "+ CO₂ term", val: v1, from: r.raw, active: r.co2Term > 0,
      note: r.co2Term > 0
        ? `+${fmt(r.co2Term)} · gain ${fmt(R.co2Gain, 2)} × relu(dev − ${fmt(R.co2Break)})`
        : `0 · inside the CO₂ deadband` });
    if (R.external) {
      seq.push({ name: "× external", val: r.afterCo2, from: v1, active: Math.abs(r.afterCo2 - v1) >= 0.05,
        note: D.externalSensor.enabled
          ? `enabled — not modelled; device range ×${fmt(externalMultRange(), 2)}–1.00`
          : `×1.00 · sensor off (constant)` });
    }
  }
  seq.push({ name: "after floor", val: r.floored, from: r.afterCo2, active: r.floorFired,
    note: r.floorFired
      ? `sev ${fmt(r.regSev, 0)} ≥ ${fmt(eMinor(), 0)} forced up to floor ${fmt(R.floor)}`
      : (R.floor > 0 ? `floor ${fmt(R.floor)} not forced (sev < ${fmt(eMinor(), 0)} or already above)` : null) });
  seq.push({ name: "after conflict", val: r.command, from: r.floored, active: Math.abs(r.command - r.floored) >= 0.05,
    note: r.conflictFired ? `${r.conflictWhy} · ${r.conflictWhen}` : null });

  const rows = seq.map((s, i) => {
    const lo = Math.min(s.from, s.val), hi = Math.max(s.from, s.val);
    const dir = i === 0 ? "up" : (s.val > s.from ? "up" : (s.val < s.from ? "down" : "hold"));
    const bar = i === 0
      ? `<div class="wf-delta up" style="left:0;width:${clamp(s.val)}%"></div>`
      : `<div class="wf-delta ${dir}" style="left:${lo}%;width:${Math.max(hi - lo, dir === "hold" ? 0 : 0.6)}%"></div>`
        + `<div class="wf-base" style="left:0;width:${lo}%"></div>`;
    return `<div class="wf-row ${s.active ? "active" : ""}">
        <div class="wf-name">${s.name}</div>
        <div class="wf-track">${bar}</div>
        <div class="wf-val">${fmt(s.val)}</div>
      </div>${s.note ? `<div class="wf-note">${s.active ? "<b>changed</b> · " : ""}${s.note}</div>` : ""}`;
  }).join("");

  const fv = r.duty === null ? null : r.duty;
  const finalBar = fv === null
    ? `<div class="wf-delta hold" style="left:0;width:100%"></div>`
    : `<div class="wf-delta up" style="left:0;width:${clamp(fv)}%"></div>`;
  const finalRow = `<div class="wf-row final">
      <div class="wf-name">FINAL effective</div>
      <div class="wf-track">${finalBar}</div>
      <div class="wf-val">${r.duty === null ? "—" : fmt(r.duty)}</div>
    </div>`;
  return `<div class="waterfall">${rows}${finalRow}`
    + `<div class="wf-scale"><span>0</span><span>50</span><span>100 %</span></div></div>`;
}

function adapterNote(R, r) {
  const a = R.adapter;
  if (r.kind === "pwm_pair") {
    return `center ch${a.center_ch} ${fmt(r.center)} % · wall ch${a.wall_ch} ${fmt(r.wall)} % `
      + `(grid coloured by center)`;
  }
  if (r.kind === "heater") {
    return `time-proportioned: ${fmt(r.duty)} % of a ${a.window_s} s window, `
      + `bounded by min_on ${a.min_on_s} s / min_off ${a.min_off_s} s`;
  }
  if (r.state === "band") {
    return `command ${fmt(r.command)} sits in the hysteresis band (${fmt(a.off_below)}–${fmt(a.on_above)}, inclusive): `
      + `the relay holds its previous state. min_on ${a.min_on_s} s / min_off ${a.min_off_s} s also gate it.`;
  }
  if (r.kind === "relay" || r.kind === "growlight") {
    const side = r.state === "on" ? "above on_above " + fmt(a.on_above) : "below off_below " + fmt(a.off_below);
    return `command ${fmt(r.command)} is ${side}`
      + ` — relay ${r.state.toUpperCase()}`
      + (r.kind === "growlight" && !R.dimmable ? `; relay-only, dac_max_pct ${a.dac_max_pct} % unused` : "");
  }
  return `PWM duty passes straight through to channel ch${a.pca9685_ch}`;
}

/* 1-D slice charts: duty along X at the clicked Y, and along Y at the clicked
   X — reads a row/column far faster than scanning fills. Nulls (hysteresis
   band) break the line. */
function sliceSVG(vals, markIdx) {
  const W = 100, H = 100, n = vals.length;
  const sx = i => (i / (n - 1)) * W, sy = v => H - (v / 100) * H;
  let segs = [], cur = [];
  vals.forEach((v, i) => {
    if (v === null) { if (cur.length) { segs.push(cur); cur = []; } }
    else cur.push(`${sx(i).toFixed(1)},${sy(v).toFixed(1)}`);
  });
  if (cur.length) segs.push(cur);
  const polys = segs.map(s =>
    `<polyline points="${s.join(" ")}" fill="none" stroke="var(--grow-600)" stroke-width="2"`
    + ` vector-effect="non-scaling-stroke"/>`).join("");
  const mv = vals[markIdx];
  const mx = sx(markIdx).toFixed(1);
  const mark = `<line x1="${mx}" y1="0" x2="${mx}" y2="${H}" stroke="var(--fg-1)" stroke-width="1.25"`
    + ` vector-effect="non-scaling-stroke"/>`
    + (mv !== null ? `<circle cx="${mx}" cy="${sy(mv).toFixed(1)}" r="2.6" fill="var(--bloom-500)"/>` : "");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`
    + `<line x1="0" y1="${H - 0.5}" x2="${W}" y2="${H - 0.5}" stroke="var(--border-strong)" stroke-width="1"/>`
    + `<line x1="50" y1="0" x2="50" y2="${H}" stroke="var(--grid-line)" stroke-width="1"/>`
    + polys + mark + `</svg>`;
}
function slicesHTML(reg, R, xi, yi) {
  const dx = R.dims[0], dy = R.dims[1];
  const rowX = G.map((_, i) => pipeline(reg, i, yi).duty);   // vary X, fixed Y
  const colY = G.map((_, j) => pipeline(reg, xi, j).duty);   // vary Y, fixed X
  return `<div class="slices">
    <div class="slice"><div class="st">duty vs ${D.dimLabels[dx]} · at ${D.dimLabels[dy]} dev ${G[yi]}</div>
      ${sliceSVG(rowX, xi)}</div>
    <div class="slice"><div class="st">duty vs ${D.dimLabels[dy]} · at ${D.dimLabels[dx]} dev ${G[xi]}</div>
      ${sliceSVG(colY, yi)}</div>
  </div>`;
}

/* ---------- species-profile editor -------------------------------------
   The anchors and the day/night window, edited in physical units. These feed
   the normalizer, not the surfaces, so a change here re-labels the plot rather
   than reshaping it — the card says so, and the tuning card next to it is
   where the shape lives. */

// CO2 is tuned in coarse steps (a 25 ppm nudge is noise); temperature and
// humidity in half-units, which is finer than any sensor this thing carries.
const anchorStep = dim => dim === "co2" ? 25 : 0.5;
const anchorCaps = { at_0: "at 0", at_50: "ideal", at_100: "at 100" };

// A profile whose anchors are not strictly ascending is one validate_config()
// would reject. The page still plots it — refusing the keystroke would make the
// field impossible to retype through — but says so, and marks the export.
function profileProblems(name) {
  const P = LIVE_PROFILES[name], out = [];
  for (const ph of PHASES) {
    for (const dim of D.dimOrder) {
      const a = P[ph][dim];
      if (!(a.at_0 < a.at_50 && a.at_50 < a.at_100)) out.push(ph + " · " + D.dimLabels[dim]);
    }
  }
  return out;
}

function schedProblems() {
  const out = new Set();
  for (const k of SCHED_KEYS) {
    const v = LIVE_SCHED[k];
    if (!Number.isInteger(v) || v < 0 || v > 1440) out.add(k);
  }
  if (LIVE_SCHED.day_start_min >= LIVE_SCHED.day_end_min) {
    out.add("day_start_min"); out.add("day_end_min");
  }
  return out;
}

function profInput(path, value, base, step, dp) {
  const dirty = value !== base ? " dirty" : "";
  return `<input type="number" class="pe${dirty}" data-path="${path}" value="${value}" step="${step}"`
    + ` title="config.py: ${fmt(base, dp)}">`;
}

function renderProfileEditor() {
  const name = state.profile, P = LIVE_PROFILES[name], B = D.profiles[name];
  el("profTag").textContent = name + " · " + P.category;

  let h = "";
  for (const ph of PHASES) {
    const caps = D.anchorKeys.map(k => `<span class="cap">${anchorCaps[k]}</span>`).join("");
    const rows = D.dimOrder.map(dim =>
      `<span class="rl">${D.dimLabels[dim]}<small>${D.dimUnits[dim]}</small></span>`
      + D.anchorKeys.map(k => profInput(
          `anchor.${ph}.${dim}.${k}`, P[ph][dim][k], B[ph][dim][k],
          anchorStep(dim), dim === "co2" ? 0 : 1)).join("")
    ).join("");
    h += `<div class="edgroup"><div class="gt">${ph} anchors</div>
      <div class="profgrid"><span></span>${caps}${rows}</div></div>`;
  }

  const sched = SCHED_KEYS.map(k =>
    `<div class="schedrow"><label>${k}</label>`
    + profInput("sched." + k, LIVE_SCHED[k], D.schedule[k], 5, 0)
    + `<span class="clk" id="clk-${k}"></span></div>`).join("");
  h += `<div class="edgroup"><div class="gt">Day / night window (global)</div>${sched}
    <p class="note">Minutes past midnight. The blend ramps 0→1 over
    <em>transition</em> minutes just inside each edge, and is 0 outside the window.
    Switch the time-of-day control to <strong>set clock</strong> to drive b from
    these instead of dragging it.</p></div>`;

  el("profeditor").innerHTML = h;
  refreshProfMeta();
  updateDirty();
}

// Everything in the card that is NOT an input: safe to rewrite on every
// keystroke without stealing focus mid-number.
function refreshProfMeta() {
  for (const k of SCHED_KEYS) {
    const span = el("clk-" + k);
    if (span) span.textContent = k === "transition_min" ? "min" : hhmm(LIVE_SCHED[k]);
  }
  const bad = schedProblems();
  const profBad = profileProblems(state.profile);
  document.querySelectorAll("#profeditor input[data-path]").forEach(inp => {
    const p = inp.dataset.path;
    if (p.startsWith("sched.")) { inp.classList.toggle("bad", bad.has(p.slice(6))); return; }
    const [, ph, dim] = p.split(".");
    inp.classList.toggle("bad", profBad.includes(ph + " · " + D.dimLabels[dim]));
  });

  const msgs = [];
  if (profBad.length) {
    msgs.push(`Anchors must be strictly ascending (at 0 &lt; ideal &lt; at 100):
      <strong>${profBad.join(", ")}</strong>. <code>validate_config()</code> would reject this profile.`);
  }
  if (bad.size) {
    msgs.push(`Window must satisfy 0 ≤ minutes ≤ 1440 and day_start_min &lt; day_end_min
      (<strong>${[...bad].join(", ")}</strong>).`);
  }
  el("profWarn").innerHTML = msgs.map(m => `<div>${m}</div>`).join("");
}

function applyProfileEdit(path, rawValue) {
  const v = parseFloat(rawValue);
  if (!Number.isFinite(v)) return false;
  if (path.startsWith("sched.")) {
    // The validator wants ints here, so round rather than carry a fractional
    // minute into an export that would then fail to load.
    LIVE_SCHED[path.slice(6)] = Math.round(v);
  } else {
    const [, ph, dim, key] = path.split(".");
    LIVE_PROFILES[state.profile][ph][dim][key] = v;
  }
  return true;
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
  el("edSubtitle").textContent = reg;
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

// Anchor diffs are counted per profile, not just for the selected one: switching
// species mid-session must not quietly drop the edits made to the previous.
function profChanges(name) {
  const P = LIVE_PROFILES[name], B = D.profiles[name], out = [];
  for (const ph of PHASES) {
    for (const dim of D.dimOrder) {
      for (const k of D.anchorKeys) {
        if (P[ph][dim][k] !== B[ph][dim][k]) out.push(`${ph}.${dim}.${k}`);
      }
    }
  }
  return out;
}

function schedChanges() {
  return SCHED_KEYS.filter(k => LIVE_SCHED[k] !== D.schedule[k]);
}

function updateDirty() {
  const per = D.regNames.map(n => [n, regChanges(n).length]).filter(e => e[1]);
  const profPer = Object.keys(LIVE_PROFILES).map(n => [n, profChanges(n).length]).filter(e => e[1]);
  const sched = schedChanges();
  const total = per.reduce((s, e) => s + e[1], 0)
    + profPer.reduce((s, e) => s + e[1], 0)
    + sched.length
    + (edgesChanged() ? 1 : 0);
  el("btnExport").disabled = total === 0;
  if (total === 0) {
    el("dirtySummary").innerHTML =
      `<p class="note">No changes — every value matches <code>config.py</code>.</p>`;
    return;
  }
  const parts = per.map(([n, c]) => `${n} (${c})`)
    .concat(profPer.map(([n, c]) => `profile ${n} (${c})`));
  if (sched.length) parts.push(`day/night window (${sched.length})`);
  if (edgesChanged()) parts.push("band edges");
  el("dirtySummary").innerHTML =
    `<p class="dirtynote">${total} changed value${total === 1 ? "" : "s"}: ${parts.join(", ")}.</p>`;
}

// config.py writes floats with a decimal point and ints without; match that so
// the fragment reads like the file it is going into.
function pyNum(v) {
  if (Number.isInteger(v)) return v.toFixed(1);
  return String(parseFloat(v.toFixed(6)));
}

// One species entry, formatted the way config.py writes them (one line per
// dimension). Emitted WHOLE for the same reason _surface() is: a partial anchor
// list pasted over the existing block would leave the other phase behind.
function profileBlockPy(name) {
  const P = LIVE_PROFILES[name];
  const lines = [`"${name}": {`, `    "category": "${P.category}",`];
  for (const ph of PHASES) {
    lines.push(`    "${ph}": {`);
    for (const dim of D.dimOrder) {
      const a = P[ph][dim];
      lines.push(`        "${dim}": {`
        + D.anchorKeys.map(k => `"${k}": ${pyNum(a[k])}`).join(", ") + "},");
    }
    lines.push("    },");
  }
  lines.push("},");
  return lines;
}

function buildExport() {
  const out = [];
  const sched = schedChanges();
  if (edgesChanged() || sched.length) {
    out.push("# --- regulation ---");
    if (edgesChanged()) out.push('"band_edges": [' + LIVE_EDGES.map(v => String(v)).join(", ") + "],");
    for (const k of sched) {
      const v = Math.round(LIVE_SCHED[k]);
      out.push(`"${k}": ${v},` + (k === "transition_min" ? "" : `  # ${hhmm(v)}`));
    }
    out.push("");
  }
  for (const name of Object.keys(LIVE_PROFILES)) {
    if (!profChanges(name).length) continue;
    const bad = profileProblems(name);
    out.push(`# --- regulation.profiles.${name} ---`);
    if (bad.length) {
      out.push(`# WARNING: anchors are not strictly ascending (${bad.join(", ")}) —`,
               "# validate_config() will reject this as pasted.");
    }
    out.push(...profileBlockPy(name), "");
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
  const scope = t.dataset.path;
  const B = D.regulators[state.reg];
  let base;
  if (scope.startsWith("surface.")) base = B.surface[scope.slice(8)];
  else if (scope.startsWith("adapter.")) base = B.adapter[scope.slice(8)];
  else if (scope.startsWith("edge.")) base = D.bandEdges[parseInt(scope.slice(5), 10)];
  else base = B[scope];
  t.classList.toggle("dirty", parseFloat(t.value) !== base);
});

// Profile edits never touch gridCache — no surface reads a physical unit, so
// the grids are unaffected and only the labels have to be redrawn.
el("profeditor").addEventListener("input", ev => {
  const t = ev.target;
  if (!t.dataset || !t.dataset.path) return;
  if (!applyProfileEdit(t.dataset.path, t.value)) return;
  render();
  refreshProfMeta();
  updateDirty();
  const p = t.dataset.path;
  let base;
  if (p.startsWith("sched.")) base = D.schedule[p.slice(6)];
  else { const [, ph, dim, key] = p.split("."); base = D.profiles[state.profile][ph][dim][key]; }
  t.classList.toggle("dirty", parseFloat(t.value) !== base);
});

el("btnResetProf").onclick = () => {
  LIVE_PROFILES[state.profile] = clone(D.profiles[state.profile]);
  LIVE_SCHED = Object.assign({}, D.schedule);
  syncTodSlider();
  render(); renderProfileEditor();
};
// Most shipped profiles differ between day and night in temperature only, so
// mirroring the day column is the usual starting point for a night edit.
el("btnCopyNight").onclick = () => {
  const P = LIVE_PROFILES[state.profile];
  P.night = clone(P.day);
  render(); renderProfileEditor();
};

el("showAll").onchange = e => { state.showAll = e.target.checked; renderEditor(); };
el("btnResetReg").onclick = () => {
  LIVE[state.reg] = clone(D.regulators[state.reg]);
  gridCache = {};
  render(); renderEditor();
};
el("btnResetAll").onclick = () => {
  LIVE = clone(D.regulators);
  LIVE_EDGES = D.bandEdges.slice();
  LIVE_PROFILES = clone(D.profiles);
  LIVE_SCHED = Object.assign({}, D.schedule);
  gridCache = {};
  el("exportWrap").hidden = true;
  syncTodSlider();
  render(); renderEditor(); renderProfileEditor();
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

/* ---------- boot -------------------------------------------------------- */

(function boot() {
  const saved = localStorage.getItem("rse.theme");
  const t = saved || (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  buildControls();
  selfCheck();
  setTheme(t);   // sets the attribute, the toggle state, and runs render()
  renderEditor();
  renderProfileEditor();
})();
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
