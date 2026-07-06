# Regulation Adapters — commanded intensity → physical actuator
# Part of the regulation matrix (see docs/prompts/regulation-matrix.md).
#
# Stage 5 of the pipeline. Surfaces and arbitration stay continuous in [0, 100];
# every device quirk (PWM duty, relay hysteresis, compressor min-cycle, heater
# time-proportioning, DAC brightness) lives ONLY here. Each adapter exposes:
#
#   apply(intensity, now_s)  — drive the actuator toward `intensity`
#   active                    — bool, whether the actuator is currently on
#   value                     — last commanded intensity (for OLED/debug)
#
# now_s is a monotonic seconds clock passed in by the engine, so the min-cycle
# and time-proportioning logic is fully testable with a fake clock and the
# adapters import no time module.


def _clamp_pct(v):
    if v < 0.0:
        return 0.0
    if v > 100.0:
        return 100.0
    return v


class PwmAdapter:
    """Continuous PWM: intensity flows straight through to a fan output."""

    def __init__(self, output, name="pwm"):
        self._output = output  # duck-typed set_duty(pct)
        self.name = name
        self.value = 0.0
        self.active = False

    def apply(self, intensity, now_s):
        intensity = _clamp_pct(intensity)
        self._output.set_duty(intensity)
        self.value = intensity
        self.active = intensity > 0.0


class PwmPairAdapter:
    """One intensity → two scaled PWM channels (circulation center + walls)."""

    def __init__(self, center_output, wall_output, center_scale, wall_scale, name="circulation"):
        self._center = center_output
        self._wall = wall_output
        self._center_scale = center_scale
        self._wall_scale = wall_scale
        self.name = name
        self.value = 0.0
        self.active = False

    def apply(self, intensity, now_s):
        intensity = _clamp_pct(intensity)
        self._center.set_duty(_clamp_pct(intensity * self._center_scale))
        self._wall.set_duty(_clamp_pct(intensity * self._wall_scale))
        self.value = intensity
        self.active = intensity > 0.0


class _MinCycleSwitch:
    """Base for on/off adapters that honor min_on_s / min_off_s guards.

    Subclasses decide the *desired* on/off state; this base enforces the
    minimum dwell before an actual transition and drives the switch.
    """

    def __init__(self, switch, min_on_s, min_off_s, name):
        self._switch = switch  # duck-typed on()/off()
        self._min_on_s = min_on_s
        self._min_off_s = min_off_s
        self.name = name
        self.value = 0.0
        self.active = False
        self._last_change_s = None
        self._switch.off()

    def _drive(self, want_on, now_s):
        if self._last_change_s is None:
            self._last_change_s = now_s
        if want_on != self.active:
            since = now_s - self._last_change_s
            if self.active and since < self._min_on_s:
                want_on = True  # too soon to turn off
            elif (not self.active) and since < self._min_off_s:
                want_on = False  # too soon to turn on
        if want_on != self.active:
            if want_on:
                self._switch.on()
            else:
                self._switch.off()
            self.active = want_on
            self._last_change_s = now_s


class RelayHysteresisAdapter(_MinCycleSwitch):
    """On/off relay with hysteresis + min-cycle (cooler, humidifier)."""

    def __init__(self, switch, on_above, off_below, min_on_s, min_off_s, name="relay"):
        self._on_above = on_above
        self._off_below = off_below
        super().__init__(switch, min_on_s, min_off_s, name)

    def apply(self, intensity, now_s):
        intensity = _clamp_pct(intensity)
        self.value = intensity
        if not self.active and intensity > self._on_above:
            want_on = True
        elif self.active and intensity < self._off_below:
            want_on = False
        else:
            want_on = self.active
        self._drive(want_on, now_s)


class TimeProportionAdapter(_MinCycleSwitch):
    """Slow-PWM heater: duty = intensity/100 over a window_s window.

    Resistive load switched on/off (MOSFET GP3). A future gate-driver rev can
    switch to real PWM simply by wiring a PwmAdapter to the heater channel in
    main.py instead — no logic change here.
    """

    def __init__(self, switch, window_s, min_on_s, min_off_s, name="heater"):
        self._window_s = window_s
        self._window_start_s = None
        super().__init__(switch, min_on_s, min_off_s, name)

    def apply(self, intensity, now_s):
        intensity = _clamp_pct(intensity)
        self.value = intensity
        if self._window_start_s is None:
            self._window_start_s = now_s
        if now_s - self._window_start_s >= self._window_s:
            self._window_start_s = now_s
        elapsed = now_s - self._window_start_s
        duty = intensity / 100.0
        on_time = duty * self._window_s
        want_on = duty > 0.0 and elapsed < on_time
        self._drive(want_on, now_s)


class GrowlightAdapter:
    """Grow light: relay master switch, optional DAC brightness when dimmable.

    dac_set is an injected callable(percent) (the MCP4725 path); when None or
    not dimmable the light is a plain on/off bulb over the hysteresis relay.
    """

    def __init__(
        self, switch, on_above, off_below, min_on_s, min_off_s, dimmable=False, dac_set=None, name="growlight"
    ):
        self._relay = RelayHysteresisAdapter(switch, on_above, off_below, min_on_s, min_off_s, name)
        self._dimmable = dimmable and dac_set is not None
        self._dac_set = dac_set
        self.name = name

    @property
    def value(self):
        return self._relay.value

    @property
    def active(self):
        return self._relay.active

    def apply(self, intensity, now_s):
        self._relay.apply(intensity, now_s)
        if self._dimmable:
            # Brightness tracks intensity while the master relay is on; 0 when off.
            self._dac_set(intensity if self._relay.active else 0.0)
