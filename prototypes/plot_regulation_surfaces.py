#!/usr/bin/env python3
# Regulation surface visualizer + golden-vector exporter (HOST ONLY).
#
# Replaces the operator's Excel tuning sheet. Renders each surface-driven
# regulator's 2D hinge surface from DEVICE_CONFIG as a heatmap (matplotlib if
# available, otherwise an ASCII grid) and exports the golden-vector CSVs the
# device tests match against.
#
# The tuning loop:
#   1. edit DEVICE_CONFIG["regulation"]["regulators"][<name>]["surface"],
#   2. run:  python prototypes/plot_regulation_surfaces.py
#   3. eyeball the heatmaps; when happy, the refreshed golden CSVs under
#      tests/golden/ are the blessed truth the on-device math must match (±1).
#
# Usage:
#   python prototypes/plot_regulation_surfaces.py            # ASCII + export CSVs
#   python prototypes/plot_regulation_surfaces.py --no-export # just render
#   python prototypes/plot_regulation_surfaces.py --png       # save PNG heatmaps

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import DEVICE_CONFIG  # noqa: E402
from lib.regulation_surface import evaluate, freeze_surface  # noqa: E402

GOLDEN_DIR = _ROOT / "tests" / "golden"
PLOT_DIR = _ROOT / "prototypes" / "regulation_plots"
GRID = list(range(0, 101, 5))  # 21 points per axis
_ASCII_RAMP = " .:-=+*#%@"


def _surface_regulators():
    """Yield (name, frozen_params, (x_dim, y_dim)) for each surface-driven regulator."""
    import config

    regs = DEVICE_CONFIG["regulation"]["regulators"]
    for name in config._REG_NAMES:
        r = regs[name]
        if r.get("driven") == "surface":
            yield name, freeze_surface(r["surface"]), tuple(r["dims"])


def export_golden(name, params):
    """Write the (x, y) -> out grid for one surface to tests/golden/."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / "regulation_{}.csv".format(name)
    with open(path, "w") as fh:
        fh.write("x,y,out\n")
        for x in GRID:
            for y in GRID:
                fh.write("{},{},{:.4f}\n".format(x, y, evaluate(params, float(x), float(y))))
    return path


def render_ascii(name, params, dims):
    """Print a coarse ASCII heatmap (y descending rows, x across)."""
    step = 10
    print("\n== {}  (x={} dev, y={} dev) ==".format(name, dims[0], dims[1]))
    print("   x-> 0" + " " * (len(range(0, 101, step)) * 2 - 6) + "100")
    for y in range(100, -1, -step):
        cells = []
        for x in range(0, 101, step):
            v = evaluate(params, float(x), float(y))
            idx = int(v / 100.0 * (len(_ASCII_RAMP) - 1))
            idx = 0 if idx < 0 else (len(_ASCII_RAMP) - 1 if idx >= len(_ASCII_RAMP) else idx)
            cells.append(_ASCII_RAMP[idx])
        print("y={:3d} {}".format(y, " ".join(cells)))


def render_png(name, params):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available — skipping PNG for {}".format(name))
        return None
    grid = [[evaluate(params, float(x), float(y)) for x in GRID] for y in GRID]
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    path = PLOT_DIR / "regulation_{}.png".format(name)
    fig, ax = plt.subplots()
    im = ax.imshow(grid, origin="lower", extent=[0, 100, 0, 100], aspect="auto", cmap="viridis")
    ax.set_title("Regulation surface: {}".format(name))
    ax.set_xlabel("x deviation")
    ax.set_ylabel("y deviation")
    fig.colorbar(im, ax=ax, label="command 0-100")
    fig.savefig(path)
    plt.close(fig)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render regulation surfaces and export golden vectors.")
    parser.add_argument("--no-export", action="store_true", help="do not (re)write tests/golden CSVs")
    parser.add_argument("--png", action="store_true", help="save matplotlib PNG heatmaps")
    args = parser.parse_args(argv)

    for name, params, dims in _surface_regulators():
        render_ascii(name, params, dims)
        if not args.no_export:
            path = export_golden(name, params)
            print("  exported {}".format(path.relative_to(_ROOT)))
        if args.png:
            path = render_png(name, params)
            if path:
                print("  wrote {}".format(path.relative_to(_ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
