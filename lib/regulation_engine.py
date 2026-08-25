# Regulation Engine — the uasyncio tick loop that owns the pipeline
# Part of the regulation matrix (see docs/prompts/regulation-matrix.md).
#
# Wires normalizer → surfaces → arbiter → adapters and runs them every tick_s.
# Reads only cached sensor values (no new sensor reads); the per-tick path is
# allocation-free (preallocated float buffers, no dict/list/f-string churn).
# Optionally advances the active species profile on a week-based phase schedule
# (regulation.phase_schedule) — resolved from the calendar, gated on a date
# change, and rebuilt through the single _activate_profile() path.
# Emergency/latch transitions raise buzzer + event-log side effects through
# injected callbacks so the engine stays hardware-decoupled and testable.
# Also hosts two monitor-only detectors — humidifier effectiveness and RH-target
# reachability — which never touch an actuator, only raise operator warnings.

import time
from array import array

import uasyncio as asyncio

from lib.regulation_arbiter import RegulationArbiter
from lib.regulation_normalizer import RegulationNormalizer, severity
from lib.regulation_surface import evaluate, freeze_surface


def _days_from_civil(year, month, day):
    """Days since 1970-01-01 for a proleptic-Gregorian date (integer math only).

    Howard Hinnant's civil-from-days inverse. Used to turn (today - start_date)
    into a day count so the phase schedule is ABSOLUTE: a controller that
    reboots mid-grow resolves the same phase the running one was in, instead of
    replaying the schedule from week one.
    """
    y = year - (1 if month <= 2 else 0)
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    mp = month - 3 if month > 2 else month + 9
    doy = (153 * mp + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


# fixed: how far before its own start_date a resolved calendar date may fall
# before the schedule refuses to believe it. Two years is generous enough for a
# schedule configured well ahead of the grow, and short enough to reject the
# RP2040's own 2021-01-01 power-on default, which an unreadable DS3231 leaves
# in place. Not operator-tunable — it is a sanity bound, not a setting.
_MAX_PRE_START_DAYS = 730


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
        status_manager=None,
        clock=None,
        fallback_phase=None,
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
                (kind in {"emergency","latch","release","supply"}).
            status_manager: optional StatusManager for named warning keys
                (monitor-only detectors; the engine never reads it back).
            clock: optional callable() -> monotonic seconds (adapter min-cycle);
                defaults to time.time.
            fallback_phase: optional phase NAME (a plain string, not a store)
                to adopt when the very first schedule resolve is held because
                the RTC date is implausible. main.py passes the last phase the
                operator acknowledged, so a controller that boots with a dead
                coin cell stays in the phase it was actually in instead of
                dropping back to week one.
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
        self._status = status_manager
        self._clock = clock or time.time
        self._tick_s = float(reg_cfg["tick_s"])

        # Microsecond monotonic for per-tick duration (health metrics). Prefer
        # the MicroPython ticks_us/ticks_diff pair (wrap-safe on device); fall
        # back to perf_counter on host/CPython where ticks_us is absent. Bound
        # once here so run() does no per-tick attribute lookups or branching.
        if hasattr(time, "ticks_us") and hasattr(time, "ticks_diff"):
            self._ticks_us = time.ticks_us
            self._ticks_diff = time.ticks_diff
        else:
            self._ticks_us = lambda: int(time.perf_counter() * 1000000)
            self._ticks_diff = lambda a, b: a - b
        self._last_tick_us = 0
        self._max_tick_us = 0

        n = len(reg_names)
        regulators = reg_cfg["regulators"]
        self._regulators = regulators
        self._profiles = reg_cfg["profiles"]
        self._day_start_min = reg_cfg["day_start_min"]
        self._day_end_min = reg_cfg["day_end_min"]
        self._transition_min = reg_cfg["transition_min"]

        self._arb = RegulationArbiter.from_config(reg_cfg, reg_names, dim_order, self._tick_s)

        # Per-profile state (normalizer, frozen surfaces, light level) is built
        # by _activate_profile — the single place it is ever created, so a phase
        # change and a cold boot take the identical code path.
        self._norm = None
        self._surface_params = [None] * n
        self._surface_dims = [None] * n
        self._base_light_day = float(regulators["growlight"]["light_level_day"])
        self._light_level_day = self._base_light_day
        self._profile_name = reg_cfg["profile"]
        self._activate_profile(reg_cfg["profile"])

        # Regulator indices used by the derived/tod/exhaust paths.
        self._i_heater = reg_names.index("heater")
        self._i_follower = reg_names.index("heater_follower")
        self._i_growlight = reg_names.index("growlight")
        self._i_humidifier = reg_names.index("humidifier")
        self._co2_idx = dim_order.index("co2")
        self._hum_idx = dim_order.index("humidity")

        # Humidifier effectiveness watchdog (monitor only — see _check_humidifier).
        # Every field below is a scalar and the check runs branch-first, so the
        # per-tick cost is one compare on the overwhelmingly common path.
        watchdog = reg_cfg.get("humidifier_watchdog")
        hum_adapter = regulators["humidifier"].get("adapter") or {}
        on_above = hum_adapter.get("on_above")
        self._hum_watch = watchdog is not None and on_above is not None
        self._hum_on_above = float(on_above) if on_above is not None else 0.0
        self._hum_window_s = float(watchdog["ineffective_window_s"]) if watchdog else 0.0
        self._hum_min_rise = float(watchdog["ineffective_min_rise"]) if watchdog else 0.0
        self._hum_on_since = None  # monotonic start of the current on-window
        self._hum_win_rh = 0.0  # RH when that window opened
        self._hum_warned = False  # warning currently raised (edge guard)
        self._hum_warn_rh = 0.0  # RH when it was raised (the recovery baseline)

        follower = regulators["heater_follower"]
        self._follower_gain = float(follower["follower_gain"])
        self._follower_floor = float(follower["follower_floor"])

        # CO2 additive term + external-effectiveness multiplier, per regulator.
        # Any surface regulator carrying a co2_gain takes the term; CO2 is not a
        # surface dimension, so this is the only path by which it reaches an
        # actuator. Held as parallel per-index sequences so the tick path does a
        # subscript instead of a dict lookup.
        self._co2_active = tuple("co2_gain" in regulators[name] for name in reg_names)
        self._ext_active = tuple(bool(regulators[name].get("external", False)) for name in reg_names)
        self._co2_gain = array("f", [0.0] * n)
        self._co2_break = array("f", [0.0] * n)
        for i, name in enumerate(reg_names):
            if self._co2_active[i]:
                self._co2_gain[i] = float(regulators[name]["co2_gain"])
                self._co2_break[i] = float(regulators[name]["co2_break"])
        self._any_external = any(self._ext_active)

        # Fresh-air exchange fallback for a blind CO2 channel. The window is
        # derived from wall-clock minutes rather than a tick counter so it is
        # deterministic across reboots — a controller that resets mid-window
        # resumes the same schedule instead of restarting the cycle.
        fae = reg_cfg.get("fresh_air_exchange")
        self._fae_enabled = bool(fae["enabled"]) if fae else False
        self._fae_interval_min = float(fae["interval_min"]) if fae else 0.0
        self._fae_duration_min = float(fae["duration_min"]) if fae else 0.0
        self._fae_command = float(fae["command"]) if fae else 0.0

        ext = reg_cfg["external_sensor"]
        self._ext_enabled = bool(ext["enabled"])
        self._ext_full_c = float(ext["full_delta_c"])
        self._ext_min_c = float(ext["min_factor"])
        self._ext_full_rh = float(ext["full_delta_rh"])
        self._ext_min_rh = float(ext["min_factor_rh"])
        # Latest external reading, cached into scalars once per tick so the
        # exhaust multiplier and the RH-reachability monitor share one I2C read.
        self._ext_t = None
        self._ext_h = None

        # RH-target reachability monitor (monitor only — see _check_rh_target).
        self._rh_margin = float(ext.get("rh_unreachable_margin", 0.0))
        self._rh_window_s = float(ext.get("rh_unreachable_window_s", 0.0))
        self._rh_watch = self._rh_margin > 0.0 and self._rh_window_s > 0.0
        self._rh_over_since = None  # monotonic start of the sustained excess
        self._rh_warned = False  # warning currently raised (edge guard)

        # Preallocated per-tick buffers.
        self._dev = array("f", [50.0] * len(dim_order))
        self._sev = array("f", [0.0] * len(dim_order))
        self._target = array("f", [0.0] * n)
        self._out = array("f", [0.0] * n)

        # Latest state (for OLED/debug; not built per tick).
        self._b = 0.0
        self._gmax = 0.0

        # Week-based phase schedule (plant grows). Disabled = every field below
        # is inert and tick() never asks the clock for a date.
        sched = reg_cfg.get("phase_schedule")
        self._phase_enabled = bool(sched["enabled"]) if sched else False
        self._phases = sched["phases"] if self._phase_enabled else None
        self._phase_index = -1
        self._phase_name = None
        self._on_phase_change = None
        self._rtc_warned = False
        self._fallback_phase = fallback_phase
        # Cached date, compared element-wise so the fast path allocates nothing
        # of its own. (0,0,0) can never match a real date, so the first tick
        # after boot always resolves.
        self._date_y = 0
        self._date_m = 0
        self._date_d = 0
        if self._phase_enabled:
            start = sched["start_date"]
            self._phase_start_day = _days_from_civil(int(start[0]), int(start[1]), int(start[2]))
            # Resolve at construction, not on the first tick: a controller that
            # reboots in week six must be in the right phase before the first
            # actuator command goes out, not one tick_s later.
            self._maybe_advance_phase(announce=False)

    # -- profile activation (phase schedule) -------------------------------

    def _activate_profile(self, name):
        """(Re)build every profile-derived object. Allocates — never call per tick.

        This is the ONE place phase state is created: __init__ routes through it
        for the configured profile and the schedule calls it again on each phase
        change, so a boot deep in a grow is byte-identical to having advanced
        into that phase.
        """
        profile = self._profiles[name]
        self._norm = RegulationNormalizer(
            profile,
            self._day_start_min,
            self._day_end_min,
            self._transition_min,
            self._dim_order,
        )
        # Surfaces are re-frozen from the BASE config every time, with this
        # profile's overrides merged on top, so overrides never accumulate
        # across phases — a phase without them gets the shipped surface back.
        overrides = profile.get("surface_overrides")
        for i, reg_name in enumerate(self._reg_names):
            r = self._regulators[reg_name]
            if r["driven"] != "surface":
                continue
            surface = r["surface"]
            if overrides:
                over = overrides.get(reg_name)
                if over:
                    surface = dict(surface)
                    surface.update(over)
            self._surface_params[i] = freeze_surface(surface)
            self._surface_dims[i] = (
                self._dim_order.index(r["dims"][0]),
                self._dim_order.index(r["dims"][1]),
            )
        self._light_level_day = float(profile.get("light_level_day", self._base_light_day))
        # Is the humidifier switched off for the whole of this phase? A surface
        # override that pins mult to 0 collapses the hinge plane to a constant
        # zero command, which sits permanently under the adapter's off_below —
        # i.e. a dead appliance (see cannabis_bloom in config.py). Resolved here
        # rather than at notice time so the operator notice reads the same fact
        # the surfaces were frozen from.
        hum_over = overrides.get("humidifier") if overrides else None
        self._humidifier_silenced = bool(hum_over) and float(hum_over.get("mult", 1.0)) == 0.0
        self._profile_name = name

    def _phase_for_day(self, day_offset):
        """Index of the phase covering ``day_offset`` days after start_date.

        Absolute: derived from the offset alone, never from the previous phase.
        A negative offset (start_date still in the future) resolves to the first
        phase; ``weeks: 0`` marks the open-ended terminal phase.
        """
        if day_offset < 0:
            return 0
        last = len(self._phases) - 1
        elapsed = 0
        for i in range(last + 1):
            weeks = self._phases[i]["weeks"]
            if weeks <= 0:
                return i
            elapsed += weeks * 7
            if day_offset < elapsed:
                return i
        # Every phase bounded and all of them elapsed: hold the last one.
        return last

    def _date_plausible(self, date):
        """Can this date be believed enough to move a grow phase on it?

        The sentinel test this replaced ((0,0,0)) caught the ONE failure mode
        the time provider can no longer produce on-device: now_date_tuple()
        only returns it when time.localtime() itself raises, which it does not
        on MicroPython. The failures that actually happen return a date that is
        merely WRONG — a DS3231 with a flat coin cell powers up at 2000-01-01,
        and an unreadable DS3231 leaves the RP2040 at its own 2021-01-01
        default. Either one resolves to "day one", which silently walks a
        flowering canopy back to the seedling profile: light 40 %, RH ideal
        68 %, humidifier un-silenced, mould gate loosened — i.e. botrytis
        conditions, announced as one routine info line.

        So the gate is plausibility, not a sentinel. Four clauses, each
        catching something the others do not:

        * a calendar-shaped year and a real month/day (kills (0,0,0) and the
          2000-01-01 a flat coin cell produces);
        * the provider's OWN verdict on its clock, when it exposes one — but
          only when it exposes one, because a DS3231 that cannot be READ never
          updates that flag and leaves it optimistically True;
        * which is why the last clause exists: a date that predates the
          schedule's own start_date by more than two years cannot be today,
          whatever the year looks like. That is what catches the RP2040's
          2021-01-01 power-on default surviving an unreadable RTC.
        """
        if not (2020 <= date[0] <= 2100):
            return False
        if not (1 <= date[1] <= 12) or not (1 <= date[2] <= 31):
            return False
        if not getattr(self._time, "time_valid", True):
            return False
        return _days_from_civil(date[0], date[1], date[2]) - self._phase_start_day >= -_MAX_PRE_START_DAYS

    def _hold_phase(self):
        """Keep the current phase and make the reason operator-visible.

        The date cache is deliberately left stale, so every later tick retries
        the resolve instead of the first bad date poisoning the schedule for
        the rest of the run.
        """
        if not self._rtc_warned:
            self._rtc_warned = True
            self._event("warning", "regulation phase held: RTC date implausible")
            self._set_warning("rtc_phase_held", True)
        if self._phase_index < 0:
            self._adopt_fallback_phase()

    def _adopt_fallback_phase(self):
        """Cold boot with an unusable clock: start from the acknowledged phase.

        Without this the engine sits at phases[0] — week one — which is the
        single worst guess available, because the operator only ever
        acknowledges a phase the controller was really in.
        """
        name = self._fallback_phase
        if not name:
            return
        for i, phase in enumerate(self._phases):
            if phase["name"] != name:
                continue
            self._activate_profile(phase["profile"])
            self._phase_index = i
            self._phase_name = phase["name"]
            self._event("warning", "regulation phase fell back to the acknowledged {}".format(name))
            return
        self._event("warning", "regulation fallback phase {} is not in the schedule".format(name))

    def _maybe_advance_phase(self, announce=True):
        """Re-resolve the active phase, but only when the calendar date changed.

        Gated hard on the date so 2879 of 2880 daily ticks cost one
        now_date_tuple() — a localtime() call plus two small tuples — and three
        integer compares. That is not free, but against a 30 s tick it is
        noise, and the alternative (caching the date behind the provider)
        would put the schedule one clock-correction behind the RTC.
        """
        date = self._time.now_date_tuple()
        if date[0] == self._date_y and date[1] == self._date_m and date[2] == self._date_d:
            return
        if not self._date_plausible(date):
            self._hold_phase()
            return
        if self._rtc_warned:
            # First believable date after a hold. Re-arm the one-shot as well
            # as clearing the key: a SECOND clock failure has to warn again.
            self._rtc_warned = False
            self._set_warning("rtc_phase_held", False)
            self._event("info", "regulation phase hold released: RTC date plausible again")
        index = self._phase_for_day(_days_from_civil(date[0], date[1], date[2]) - self._phase_start_day)
        if index == self._phase_index:
            self._date_y = date[0]
            self._date_m = date[1]
            self._date_d = date[2]
            return

        previous = self._phase_name
        phase = self._phases[index]
        # Activate FIRST, commit the state afterwards. _activate_profile
        # allocates a normalizer and re-freezes every surface, which can
        # MemoryError on a tight heap; committing the phase name and the date
        # cache before that would leave the engine reporting a phase it is not
        # running and never retrying, because the cached date already matches.
        self._activate_profile(phase["profile"])
        self._phase_index = index
        self._phase_name = phase["name"]
        self._date_y = date[0]
        self._date_m = date[1]
        self._date_d = date[2]
        if not announce:
            return
        self._event(
            "info",
            "regulation phase {} -> {} (profile {}, {:04d}-{:02d}-{:02d})".format(
                previous, self._phase_name, phase["profile"], date[0], date[1], date[2]
            ),
        )
        if self._on_phase_change:
            try:
                self._on_phase_change(
                    previous,
                    self._phase_name,
                    date,
                    self.phase_summary(),
                )
            except Exception as exc:  # a notice sink must never stop the engine
                self._event("warning", "phase-change notice failed: {}".format(exc))

    def phase_summary(self):
        """What the ACTIVE profile means for the operator, as a plain dict.

        The three numbers a phase change actually costs someone attention for,
        not just the profile's name: the RH setpoint (the DAY anchor, b=1 — the
        notice is about the phase, not about what time it happens to be), the
        light level, and whether the humidifier runs at all this phase.

        Built on demand rather than cached so a notice raised at BOOT — from
        the acknowledgement store, with no live transition behind it — reads
        identically to one raised by the transition itself. Allocates: only
        ever called on a phase change or at boot, never per tick.
        """
        return {
            "profile": self._profile_name,
            "light_level_day": self._light_level_day,
            "rh_ideal": self._norm.ideal(self._hum_idx, 1.0),
            "humidifier_silenced": self._humidifier_silenced,
        }

    def set_phase_change_callback(self, callback):
        """Set the operator-notice sink: callback(old, new, date_tuple, summary).

        Wired by main.py to the OLED acknowledge flow; None (the default) is a
        no-op, which is what the tests and a headless build use.
        """
        self._on_phase_change = callback

    # -- external-effectiveness multiplier (exhaust only) ------------------

    def _read_external(self):
        """Sample the external (intake/room) sensor once per tick into scalars.

        Two consumers now share the reading — the exhaust effectiveness
        multiplier and the RH-reachability monitor — so it is read here rather
        than inside _external_mult, which used to own it. Both stay silent while
        the sensor is disabled or answering None.
        """
        self._ext_t = None
        self._ext_h = None
        if not (self._ext_enabled and self._external_read):
            return
        ext = self._external_read()
        if ext:
            self._ext_t = ext[0]
            self._ext_h = ext[1]

    def _external_mult(self, temp_in, hum_in):
        if not (self._any_external and self._ext_t is not None):
            return 1.0
        ft = _effect_factor(temp_in - self._ext_t, self._ext_full_c, self._ext_min_c)
        fh = _effect_factor(hum_in - self._ext_h, self._ext_full_rh, self._ext_min_rh)
        return ft * fh

    # -- RH-target reachability monitor (monitor only) ---------------------

    def _check_rh_target(self, now_s):
        """Warn when the room's own humidity puts the RH setpoint out of reach.

        MONITOR ONLY — no actuator, no buzzer, one warning key.

        The tent has no dehumidifier. Its only humidity-lowering path is the
        exhaust, which dilutes toward room air, so the floor it can reach is the
        room it stands in. Against the assumed 35-70 %RH room, the bloom ideal
        of 43 %RH is periodically not achievable by any command the engine can
        issue, and the actuators will simply run flat out failing.

        The operator decision is to keep the setpoint FIXED and say so, rather
        than sliding the target to whatever is achievable today: a target that
        chases the room is no longer a target. So this raises
        rh_target_unreachable and leaves the regulation untouched.

        The ideal comes from the live normalizer (rebuilt by _activate_profile
        on every phase change) and the current day/night blend, never from a
        config constant — bloom's 43 and seedling's 68 have opposite verdicts
        against the same room.

        Allocation-free: one subtraction, one timestamp, one flag.
        """
        room = self._ext_h
        if room is None:
            return  # sensor disabled or not answering: no opinion either way
        ideal = self._norm.ideal(self._hum_idx, self._b)
        if room - ideal <= self._rh_margin:
            self._rh_over_since = None
            if self._rh_warned:
                self._rh_warned = False
                self._set_warning("rh_target_unreachable", False)
            return
        if self._rh_warned:
            return
        if self._rh_over_since is None:
            self._rh_over_since = now_s
            return
        if now_s - self._rh_over_since >= self._rh_window_s:
            self._rh_warned = True
            self._set_warning("rh_target_unreachable", True)
            self._event("warning", "room humidity above the RH target: setpoint unreachable")

    # -- fresh-air exchange fallback ---------------------------------------

    def _fae_floor(self, co2, minutes):
        """Command floor for the CO2-carrying regulators, or 0.0 when idle.

        Only ever non-zero while ``co2`` is None. A fruiting chamber still needs
        air exchange when the sensor is blind, and on this hardware it is blind
        precisely when the tent is running correctly: the S8 is specified
        0-95 %RH non-condensing and measured a 100 % failure rate above 98 %RH
        over the 2026-07-27..31 run. Since the additive CO2 term is the only
        path from CO2 to an actuator, a neutralised reading otherwise leaves no
        air-exchange driver at all.
        """
        if co2 is not None or not self._fae_enabled:
            return 0.0
        if minutes % self._fae_interval_min < self._fae_duration_min:
            return self._fae_command
        return 0.0

    # -- humidifier effectiveness watchdog (monitor only) ------------------

    def _check_humidifier(self, command, hum, now_s):
        """Warn when the humidifier is energised and the air is not getting wetter.

        MONITOR ONLY. Nothing in here touches an actuator, a floor or the
        arbiter — the entire output is a warning key, one WARN line and one
        buzzer pattern. That is deliberate: the humidifier's tank runs dry as a
        matter of routine at the RH the early phases ask for, and the correct
        response is a human with a watering can, not a firmware override.

        The rule is the only evidence the hardware offers. The GP19 relay
        switches the appliance's mains supply and nothing comes back — no tank
        level, no humidistat state, not even a current reading — so the sole
        way to tell "misting" from "plugged in but empty" is the effect on RH.
        Commanded on CONTINUOUSLY for ineffective_window_s while RH gained less
        than ineffective_min_rise over that window = it is not working. Any
        interruption of the on-state restarts the window, because a humidifier
        that was off for part of it was never given the chance.

        Clearing is one rule, not two: the warning drops as soon as RH climbs
        ineffective_min_rise above where it stood when the warning fired. That
        covers both recoveries — a refilled tank under an unchanged command, and
        a command that dropped away while the room came back on its own.

        Allocation-free: four scalars and an early return.
        """
        if hum is None:
            # A blind sensor cannot testify either way. Disarm rather than
            # accumulate a window against readings that are not there.
            self._hum_on_since = None
            return

        if self._hum_warned and hum - self._hum_warn_rh >= self._hum_min_rise:
            self._hum_warned = False
            self._hum_on_since = None
            self._set_warning("humidifier_ineffective", False)

        if command <= self._hum_on_above:
            self._hum_on_since = None
            return

        if self._hum_on_since is None:
            self._hum_on_since = now_s
            self._hum_win_rh = hum
            return
        if now_s - self._hum_on_since < self._hum_window_s:
            return

        # A full window of uninterrupted demand has elapsed — judge it, then
        # re-open a fresh window from here either way, so a persistent fault is
        # measured continuously without ever re-firing the alarm.
        if hum - self._hum_win_rh < self._hum_min_rise:
            if not self._hum_warned:
                self._hum_warned = True
                self._hum_warn_rh = hum
                self._set_warning("humidifier_ineffective", True)
                self._event("warning", "humidifier commanded on with no RH response")
                self._alarm("supply")
        elif self._hum_warned:
            self._hum_warned = False
            self._set_warning("humidifier_ineffective", False)
        self._hum_on_since = now_s
        self._hum_win_rh = hum

    # -- target vector build ----------------------------------------------

    def _compute_targets(self, ext_mult, fae_floor=0.0):
        dev = self._dev
        target = self._target
        for i, params in enumerate(self._surface_params):
            if params is None:
                continue
            dx, dy = self._surface_dims[i]
            val = evaluate(params, dev[dx], dev[dy])
            if self._co2_active[i]:
                over = dev[self._co2_idx] - self._co2_break[i]
                if over > 0.0:
                    val += self._co2_gain[i] * over
                # Scheduled fresh-air exchange, non-zero only while the CO2
                # reading is unavailable. Applied as a floor, never a cap, so
                # it can only raise a command — and only on the regulators that
                # already carry the CO2 term, which is exactly the exhaust and
                # the circulation pair.
                if fae_floor > val:
                    val = fae_floor
            if self._ext_active[i]:
                val *= ext_mult
            # evaluate() already returns 0..100; this bounds the CO2 term and
            # the external multiplier, which are applied on top of it.
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

        if self._phase_enabled:
            self._maybe_advance_phase()

        temp = self._th.last_temperature
        hum = self._th.last_humidity
        co2 = self._co2.last_ppm if self._co2 is not None else None

        minutes = self._time.get_seconds_since_midnight() // 60
        self._b = self._norm.update((temp, hum, co2), minutes, self._dev)
        for i in range(len(self._sev)):
            self._sev[i] = severity(self._dev[i])

        self._read_external()
        ext_mult = self._external_mult(temp if temp is not None else 0.0, hum if hum is not None else 0.0)
        self._compute_targets(ext_mult, self._fae_floor(co2, minutes))

        self._gmax = self._arb.arbitrate(self._target, self._sev, self._dev, self._out)

        out = self._out
        for i, adapter in enumerate(self._adapters):
            adapter.apply(out[i], now_s)

        if self._hum_watch:
            self._check_humidifier(out[self._i_humidifier], hum, now_s)
        if self._rh_watch:
            self._check_rh_target(now_s)

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

    def _set_warning(self, key, active):
        """Raise/clear a named operator warning; a missing sink is a no-op."""
        if self._status:
            self._status.set_warning(key, active)

    # -- async task --------------------------------------------------------

    async def run(self):
        """uasyncio task: tick forever, await-friendly (never long-blocks)."""
        while True:
            try:
                start = self._ticks_us()
                self.tick()
                # Record how long the tick took so the health loop can prove
                # the allocation-free path stays far under tick_s (WDT budget).
                self._last_tick_us = self._ticks_diff(self._ticks_us(), start)
                if self._last_tick_us > self._max_tick_us:
                    self._max_tick_us = self._last_tick_us
            except Exception as exc:  # keep the loop alive; a stalled tick must not brick the WDT
                self._event("error", "regulation tick error: {}".format(exc))
            await asyncio.sleep(self._tick_s)

    # -- introspection for OLED/debug -------------------------------------

    def get_state(self):
        """Build a state snapshot (called by OLED/debug, not per tick)."""
        return {
            "blend": self._b,
            # Active species profile, and the schedule phase that selected it
            # (None when no phase schedule is running).
            "profile": self._profile_name,
            "phase": self._phase_name,
            "global_severity": self._gmax,
            # Severity restricted to the directions allowed to escalate — this,
            # not global_severity, is what fires emergency/latch.
            "escalation_severity": self._arb.escalation_severity,
            "band": self._arb.band_index(self._gmax),
            "latched": self._arb.latched,
            "emergency": self._arb.emergency_active,
            "deviations": list(self._dev),
            "severities": list(self._sev),
            "commanded": {name: self._out[i] for i, name in enumerate(self._reg_names)},
            "tick_us": self._last_tick_us,
            "tick_max_us": self._max_tick_us,
        }

    def reset_tick_peak(self):
        """Re-arm the tick-duration high-water mark (per-interval peak)."""
        self._max_tick_us = 0
