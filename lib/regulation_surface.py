# Regulation Surface — 2D hinge surface evaluation
# Part of the regulation matrix (see docs/prompts/regulation-matrix.md).
#
# Stage 2 of the pipeline: a pure function f(x, y) -> 0..100 over two deviation
# inputs, ported from the operator's Excel tuning sheet. Parameters are frozen
# into an array('f') at boot and addressed by the index constants below, so the
# per-tick evaluation allocates nothing.
#
# PARAM ORDER IS LOAD-BEARING — it mirrors config._SURFACE_PARAMS. A test
# (test_regulation_surface) cross-checks PARAM_NAMES against config so the two
# can never drift.

from array import array

# Index constants into the frozen params array (mirror config._SURFACE_PARAMS).
P_CA = 0
P_SA = 1
P_CROSS = 2
P_GAIN = 3
P_OFFSET = 4
P_HX_HI1 = 5
P_BX_HI1 = 6
P_HX_HI2 = 7
P_BX_HI2 = 8
P_HX_LO1 = 9
P_BX_LO1 = 10
P_HX_LO2 = 11
P_BX_LO2 = 12
P_HY_HI1 = 13
P_BY_HI1 = 14
P_HY_HI2 = 15
P_BY_HI2 = 16
P_HY_LO1 = 17
P_BY_LO1 = 18
P_HY_LO2 = 19
P_BY_LO2 = 20
P_X_TOP = 21
P_X_BOT = 22
P_Y_TOP = 23
P_Y_BOT = 24
P_BOOST_BASE = 25
P_GRAD = 26
P_MULT = 27
P_OUT_MIN = 28
P_OUT_MAX = 29
NUM_PARAMS = 30

# Ordered names for the frozen array (must equal config._SURFACE_PARAM_NAMES).
PARAM_NAMES = (
    "ca",
    "sa",
    "cross",
    "gain",
    "offset",
    "hx_hi1",
    "bx_hi1",
    "hx_hi2",
    "bx_hi2",
    "hx_lo1",
    "bx_lo1",
    "hx_lo2",
    "bx_lo2",
    "hy_hi1",
    "by_hi1",
    "hy_hi2",
    "by_hi2",
    "hy_lo1",
    "by_lo1",
    "hy_lo2",
    "by_lo2",
    "x_top",
    "x_bot",
    "y_top",
    "y_bot",
    "boost_base",
    "grad",
    "mult",
    "out_min",
    "out_max",
)


def freeze_surface(surface, param_names=PARAM_NAMES):
    """Freeze a config surface dict into an array('f') in PARAM_NAMES order."""
    frozen = array("f", [0.0] * len(param_names))
    for i, name in enumerate(param_names):
        frozen[i] = float(surface[name])
    return frozen


def _boost(v, hi, lo, base, grad):
    """Boost multiplier: base + gradient beyond the edges, 1.0 inside."""
    if v > hi:
        return base + (v - hi) * grad
    if v < lo:
        return base + (lo - v) * grad
    return 1.0


def evaluate(p, x, y):
    """Evaluate the surface at deviations (x, y); return a command in [0, 100].

    ``p`` is a frozen params array (see freeze_surface). Allocation-free.
    """
    xc = x - 50.0
    yc = y - 50.0
    ca = p[P_CA]
    sa = p[P_SA]

    lin = p[P_GAIN] * (xc * ca + yc * sa) + p[P_OFFSET] - p[P_CROSS] * (xc * sa + yc * ca)

    # Piecewise-linear hinges on each axis (relu(arg) folded inline).
    d = x - p[P_BX_HI1]
    if d > 0.0:
        lin += p[P_HX_HI1] * d
    d = x - p[P_BX_HI2]
    if d > 0.0:
        lin += p[P_HX_HI2] * d
    d = p[P_BX_LO1] - x
    if d > 0.0:
        lin += p[P_HX_LO1] * d
    d = p[P_BX_LO2] - x
    if d > 0.0:
        lin += p[P_HX_LO2] * d
    d = y - p[P_BY_HI1]
    if d > 0.0:
        lin += p[P_HY_HI1] * d
    d = y - p[P_BY_HI2]
    if d > 0.0:
        lin += p[P_HY_HI2] * d
    d = p[P_BY_LO1] - y
    if d > 0.0:
        lin += p[P_HY_LO1] * d
    d = p[P_BY_LO2] - y
    if d > 0.0:
        lin += p[P_HY_LO2] * d

    base = p[P_BOOST_BASE]
    grad = p[P_GRAD]
    bx = _boost(x, p[P_X_TOP], p[P_X_BOT], base, grad)
    by = _boost(y, p[P_Y_TOP], p[P_Y_BOT], base, grad)

    raw = lin * p[P_MULT] * bx * by

    out_min = p[P_OUT_MIN]
    out_max = p[P_OUT_MAX]
    if raw < out_min:
        raw = out_min
    elif raw > out_max:
        raw = out_max
    # Rescale the clamped output [out_min, out_max] -> [0, 100] command.
    return (raw - out_min) / (out_max - out_min) * 100.0
