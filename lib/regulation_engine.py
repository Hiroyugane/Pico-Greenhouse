# Regulation Engine — the uasyncio tick loop that owns the pipeline
# Part of the regulation matrix (see docs/prompts/regulation-matrix.md).
#
# Wires normalizer → surfaces → arbiter → adapters and runs them every tick_s.
# Reads only cached sensor values (no new sensor reads); the per-tick path is
# allocation-free (preallocated float buffers, no dict/list/f-string churn).
# Emergency/latch transitions raise buzzer + event-log side effects through
# injected callbacks so the engine stays hardware-decoupled and testable.

import time

import uasyncio as asyncio

from lib.regulation_arbiter import RegulationArbiter
from lib.regulation_normalizer import RegulationNormalizer, severity
from lib.regulation_surface import evaluate, freeze_surface


def _effect_factor(delta, full_delta, min_factor):
    """External-effectiveness factor: 1.0 when outside is better by >= full_delta,
    min_factor when outside is equal/worse, linear in between."""
    if delta >= full_delta:
        return 1.0
    if delta <= 0.0:
        return min_factor
    return min_factor + (1.0 - min_factor) * (delta / full_delta)


class RegulationEngine:
    """Config-driven environmental control pipeline (one async task)."""

    def __init__(
        self,
        reg_cfg,
        reg_names,
        dim_order,
        adapters,
        th_logger,
        co2_logger,
        time_provider,
        external_read=None,
        logger=None,
        alarm_cb=None,
        clock=None,
    ):
        """
        Args:
            reg_cfg: the DEVICE_CONFIG['regulation'] dict (plain data, DI).
            reg_names: ordered regulator names (command-vector order).
            dim_order: ordered deviation dimension names ("temp","humidity","co2").
            adapters: list of actuator adapters in reg_names order (hardware DI).
            th_logger: temp/humidity logger (last_temperature/last_humidity cache).
            co2_logger: CO2 logger (last_ppm cache) or None.
            time_provider: RTC time provider (get_seconds_since_midnight()).
            external_read: optional callable() -> (t_out, h_out) or None.
            logger: optional EventLogger for band-transition events.
            alarm_cb: optional callable(kind) for buzzer alarms
                (kind in {"emergency","latch","release"}).
            clock: optional callable() -> monotonic seconds (adapter min-cycle);
                defaults to time.time.
        """
        self._reg_names = reg_names
        self._dim_order = dim_order
        self._adapters = adapters
        self._th = th_logger
        self._co2 = co2_logger
        self._time = time_provider
        self._external_read = external_read
        self._logger = logger
        self._alarm_cb = alarm_cb
        self._clock = clock or time.time
        self._tick_s = float(reg_cfg["tick_s"])

        n = len(reg_names)
        regulators = reg_cfg["regulators"]

        # Normalizer + arbiter built from the config (pure data).
        profile = reg_cfg["profiles"][reg_cfg["profile"]]
        self._norm = RegulationNormalizer(
            profile,
            reg_cfg["day_start_min"],
            reg_cfg["day_end_min"],
            reg_cfg["transition_min"],
            dim_order,
        )
        self._arb = RegulationArbiter.from_config(reg_cfg, reg_names, dim_order, self._tick_s)

        # Frozen surface params + (x,y) dim indices per surface-driven regulator.
        self._surface_params = [None] * n
        self._surface_dims = [None] * n
        for i, name in enumerate(reg_names):
            r = regulators[name]
            if r["driven"] == "surface":
                self._surface_params[i] = freeze_surface(r["surface"])
                dx = dim_order.index(r["dims"][0])
                dy = dim_order.index(r["dims"][1])
                self._surface_dims[i] = (dx, dy)

        # Regulator indices used by the derived/tod/exhaust paths.
        self._i_heater = reg_names.index("heater")
        self._i_follower = reg_names.index("heater_follower")
        self._i_exhaust = reg_names.index("exhaust")
        self._i_growlight = reg_names.index("growlight")
        self._co2_idx = dim_order.index("co2")

        follower = regulators["heater_follower"]
        self._follower_gain = float(follower["follower_gain"])
        self._follower_floor = float(follower["follower_floor"])

        exhaust = regulators["exhaust"]
        self._co2_gain = float(exhaust["co2_gain"])
        self._co2_break = float(exhaust["co2_break"])
        self._exhaust_external = bool(exhaust["external"])

        self._light_level_day = float(regulators["growlight"]["light_level_day"])

        ext = reg_cfg["external_sensor"]
        self._ext_enabled = bool(ext["enabled"])
        self._ext_full_c = float(ext["full_delta_c"])
        self._ext_min_c = float(ext["min_factor"])
        self._ext_full_rh = float(ext["full_delta_rh"])
        self._ext_min_rh = float(ext["min_factor_rh"])

        # Preallocated per-tick buffers.
        from array import array

        self._dev = array("f", [50.0] * len(dim_order))
        self._sev = array("f", [0.0] * len(dim_order))
        self._target = array("f", [0.0] * n)
        self._out = array("f", [0.0] * n)

        # Latest state (for OLED/debug; not built per tick).
        self._b = 0.0
        self._gmax = 0.0

    # -- external-effectiveness multiplier (exhaust only) ------------------

    def _external_mult(self, temp_in, hum_in):
        if not (self._ext_enabled and self._exhaust_external and self._external_read):
            return 1.0
        ext = self._external_read()
        if not ext:
            return 1.0
        t_out, h_out = ext
        ft = _effect_factor(temp_in - t_out, self._ext_full_c, self._ext_min_c)
        fh = _effect_factor(hum_in - h_out, self._ext_full_rh, self._ext_min_rh)
        return ft * fh

    # -- target vector build ----------------------------------------------

    def _compute_targets(self, ext_mult):
        dev = self._dev
        target = self._target
        for i, params in enumerate(self._surface_params):
            if params is None:
                continue
            dx, dy = self._surface_dims[i]
            val = evaluate(params, dev[dx], dev[dy])
            if i == self._i_exhaust:
                over = dev[self._co2_idx] - self._co2_break
                if over > 0.0:
                    val += self._co2_gain * over
                val *= ext_mult
                if val < 0.0:
                    val = 0.0
                elif val > 100.0:
                    val = 100.0
            target[i] = val

        # heater_follower derives from the organic heater command.
        follow = target[self._i_heater] * self._follower_gain + self._follower_floor
        if follow < 0.0:
            follow = 0.0
        elif follow > 100.0:
            follow = 100.0
        target[self._i_follower] = follow

        # growlight driven by the time-of-day blend.
        light = self._b * self._light_level_day
        if light < 0.0:
            light = 0.0
        elif light > 100.0:
            light = 100.0
        target[self._i_growlight] = light

    # -- one tick ----------------------------------------------------------

    def tick(self, now_s=None):
        """Run one regulation cycle. now_s defaults to the injected clock."""
        if now_s is None:
            now_s = self._clock()

        temp = self._th.last_temperature
        hum = self._th.last_humidity
        co2 = self._co2.last_ppm if self._co2 is not None else None

        minutes = self._time.get_seconds_since_midnight() // 60
        self._b = self._norm.update((temp, hum, co2), minutes, self._dev)
        for i in range(len(self._sev)):
            self._sev[i] = severity(self._dev[i])

        ext_mult = self._external_mult(temp if temp is not None else 0.0, hum if hum is not None else 0.0)
        self._compute_targets(ext_mult)

        self._gmax = self._arb.arbitrate(self._target, self._sev, self._dev, self._out)

        out = self._out
        for i, adapter in enumerate(self._adapters):
            adapter.apply(out[i], now_s)

        self._handle_signals()

    def _handle_signals(self):
        arb = self._arb
        if arb.just_entered_latch:
            self._event("error", "regulation latch entered (severity 50)")
            self._alarm("latch")
        elif arb.just_entered_emergency:
            self._event("warning", "regulation emergency (severity >= major)")
            self._alarm("emergency")
        if arb.just_released_latch:
            self._event("info", "regulation latch released")
            self._alarm("release")

    def _event(self, level, message):
        if not self._logger:
            return
        fn = getattr(self._logger, level, None)
        if fn:
            fn("Regulation", message)

    def _alarm(self, kind):
        if self._alarm_cb:
            self._alarm_cb(kind)

    # -- async task --------------------------------------------------------

    async def run(self):
        """uasyncio task: tick forever, await-friendly (never long-blocks)."""
        while True:
            try:
                self.tick()
            except Exception as exc:  # keep the loop alive; a stalled tick must not brick the WDT
                self._event("error", "regulation tick error: {}".format(exc))
            await asyncio.sleep(self._tick_s)

    # -- introspection for OLED/debug -------------------------------------

    def get_state(self):
        """Build a state snapshot (called by OLED/debug, not per tick)."""
        return {
            "blend": self._b,
            "global_severity": self._gmax,
            "band": self._arb.band_index(self._gmax),
            "latched": self._arb.latched,
            "emergency": self._arb.emergency_active,
            "deviations": list(self._dev),
            "severities": list(self._sev),
            "commanded": {name: self._out[i] for i, name in enumerate(self._reg_names)},
        }
