# Regulation Normalizer — physical readings → deviation space
# Part of the regulation matrix (see docs/prompts/regulation-matrix.md).
#
# Stage 1 of the pipeline. Maps each sensor reading to a deviation d in [0, 100]
# where 50 = ideal for the current species profile and time of day. The
# per-tick path is allocation-free: anchors are frozen into float arrays at
# construction and deviations are written into a caller-owned output buffer.

from array import array

# Dimension index convention (matches config _REG_DIMENSIONS order).
DIM_TEMP = 0
DIM_HUMIDITY = 1
DIM_CO2 = 2
_NUM_DIMS = 3


def blend_factor(minutes, day_start, day_end, transition):
    """Time-of-day blend b in [0, 1]: 1 = full day, 0 = full night.

    The day window is [day_start, day_end). A linear ramp of width
    ``transition`` minutes sits just inside each edge, so b rises 0→1 over
    [day_start, day_start+transition] and falls 1→0 over
    [day_end-transition, day_end]. Outside the window b is 0.
    """
    if minutes < day_start or minutes >= day_end:
        return 0.0
    if transition <= 0:
        return 1.0
    # Clamp the ramp width so a narrow window still peaks at b=1 in the middle.
    half = (day_end - day_start) * 0.5
    ramp = transition if transition < half else half
    if ramp <= 0:
        return 1.0
    into = minutes - day_start
    left = day_end - minutes
    if into < ramp:
        return into / ramp
    if left < ramp:
        return left / ramp
    return 1.0


def deviation(value, at_0, at_50, at_100):
    """Asymmetric piecewise-linear map from a physical value to d in [0, 100].

    at_0 → 0 (far too low), at_50 → 50 (ideal), at_100 → 100 (far too high).
    Values outside [at_0, at_100] clamp. Anchors must be strictly ascending
    (guaranteed by config validation).
    """
    if value <= at_0:
        return 0.0
    if value <= at_50:
        return 50.0 * (value - at_0) / (at_50 - at_0)
    if value < at_100:
        return 50.0 + 50.0 * (value - at_50) / (at_100 - at_50)
    return 100.0


def severity(dev):
    """Severity s = |d - 50| in [0, 50]."""
    d = dev - 50.0
    return d if d >= 0.0 else -d


class RegulationNormalizer:
    """Blends day/night anchors by time of day and produces deviations.

    Anchors for the active profile are frozen at construction. Each dimension
    stores six floats (at_0/at_50/at_100 for day and night); the effective
    anchor at tick time is ``night + b*(day - night)``.
    """

    def __init__(self, profile, day_start_min, day_end_min, transition_min, dim_order):
        """Build from a config profile dict.

        Args:
            profile: dict with "day" and "night", each mapping dimension name →
                {"at_0", "at_50", "at_100"} (physical units).
            day_start_min, day_end_min, transition_min: time-of-day blend window.
            dim_order: tuple of dimension names in index order, e.g.
                ("temp", "humidity", "co2").
        """
        self._day_start = day_start_min
        self._day_end = day_end_min
        self._transition = transition_min
        # Flat float arrays [d0_a0, d0_a50, d0_a100, d1_a0, ...] for day & night.
        day = array("f", [0.0] * (_NUM_DIMS * 3))
        night = array("f", [0.0] * (_NUM_DIMS * 3))
        for i, name in enumerate(dim_order):
            base = i * 3
            d_anch = profile["day"][name]
            n_anch = profile["night"][name]
            day[base] = float(d_anch["at_0"])
            day[base + 1] = float(d_anch["at_50"])
            day[base + 2] = float(d_anch["at_100"])
            night[base] = float(n_anch["at_0"])
            night[base + 1] = float(n_anch["at_50"])
            night[base + 2] = float(n_anch["at_100"])
        self._day = day
        self._night = night

    def ideal(self, dim_index, b):
        """The blended at_50 anchor (the ideal, in physical units) for one dim.

        Same night + b*(day - night) blend update() applies, exposed on its own
        so a monitor can compare a physical reading against the ACTIVE profile's
        setpoint without re-deriving it from config — the engine swaps this
        object out on every phase change. Allocation-free.
        """
        base = dim_index * 3 + 1
        night = self._night[base]
        return night + b * (self._day[base] - night)

    def update(self, readings, minutes, out_dev):
        """Fill ``out_dev`` (len 3) with deviations; return the blend factor b.

        Args:
            readings: (temp, humidity, co2) in physical units. A None entry
                (missing/stale sensor) maps to deviation 50 (neutral).
            minutes: minutes since midnight (0-1439) from the time provider.
            out_dev: preallocated array('f') of length 3 to receive deviations.
        """
        b = blend_factor(minutes, self._day_start, self._day_end, self._transition)
        day = self._day
        night = self._night
        for i in range(_NUM_DIMS):
            value = readings[i]
            if value is None:
                out_dev[i] = 50.0
                continue
            base = i * 3
            a0 = night[base] + b * (day[base] - night[base])
            a50 = night[base + 1] + b * (day[base + 1] - night[base + 1])
            a100 = night[base + 2] + b * (day[base + 2] - night[base + 2])
            out_dev[i] = deviation(value, a0, a50, a100)
        return b
