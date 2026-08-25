# Tests for lib/regulation_engine.py
# End-to-end pipeline: normalize → surfaces → arbiter → adapters, plus the
# emergency/latch side-effect callbacks and the async run loop.

import copy

import pytest


class FakeAdapter:
    def __init__(self, name):
        self.name = name
        self.value = 0.0
        self.active = False
        self.applied = []

    def apply(self, intensity, now_s):
        self.value = intensity
        self.active = intensity > 0.0
        self.applied.append(intensity)


class FakeTh:
    def __init__(self, temp=24.0, hum=92.0):
        self.last_temperature = temp
        self.last_humidity = hum


class FakeCo2:
    def __init__(self, ppm=700.0):
        self.last_ppm = ppm


class FakeTime:
    def __init__(self, seconds=0, date=(2026, 9, 1)):
        self._seconds = seconds
        self.date = date
        self.date_calls = 0

    def get_seconds_since_midnight(self):
        return self._seconds

    def now_date_tuple(self):
        self.date_calls += 1
        return self.date


def _engine(
    temp=23.0,
    hum=92.0,
    co2=800.0,
    minutes=0,
    tick_s=None,
    alarm=None,
    logger=None,
    external_read=None,
    profile="cubensis",
):
    """Build an engine over the shipped config, pinned to one species profile.

    Every scenario below states its inputs in PHYSICAL units (21 C, 95 %RH),
    so it is only meaningful against the anchors it was authored for — the
    cubensis ones. The shipped `regulation.profile` now moves with the grow
    phase (seedling → stretch → bloom), so pinning it here keeps these tests
    about the pipeline instead of about which week the calendar says it is.
    The schedule is switched off for the same reason; TestPhaseSchedule
    exercises it deliberately through `_sched_engine`.
    """
    import config
    from lib.regulation_engine import RegulationEngine

    reg = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
    reg["profile"] = profile
    reg["phase_schedule"] = dict(reg["phase_schedule"], enabled=False)
    if tick_s is not None:
        reg["tick_s"] = tick_s
    if external_read is not None:
        reg["external_sensor"]["enabled"] = True
    names = config._REG_NAMES
    adapters = [FakeAdapter(n) for n in names]
    engine = RegulationEngine(
        reg,
        names,
        config._REG_DIMENSIONS,
        adapters,
        FakeTh(temp, hum),
        FakeCo2(co2),
        FakeTime(minutes * 60),
        external_read=external_read,
        logger=logger,
        alarm_cb=alarm,
        clock=lambda: 0.0,
    )
    return engine, adapters, names


def _adapter(adapters, names, name):
    return adapters[names.index(name)]


class TestCalm:
    def test_all_zero_at_night_ideal(self):
        # Night (b=0), everything at the night ideal → every command settles at
        # 0, except the two deliberate near-ideal trims.
        #
        # The heater's ramp starts one deviation point ABOVE ideal (bx_lo1 = 51)
        # so it holds the setpoint from below instead of waiting for the room to
        # fall out of the band. The trim must stay under the 5 % duty the
        # time-proportioning adapter can actually realize (min_on_s 30 s in a
        # 600 s window), so at ideal the element fires at most 30 s per 10 min.
        #
        # The humidifier gained the same treatment on 2026-07-31 (bx_lo1 43 →
        # 53) because its ramp used to die seven deviation points BELOW ideal,
        # which left the relay opening at RH 89.6 against a 92 % ideal — the tent
        # could not reach its own setpoint. It now trims at ideal too, and the
        # binding requirement is different from the heater's: the humidifier is a
        # RELAY, so its trim must stay under the adapter's off_below or the
        # contact would be held closed forever at the setpoint. Asserting
        # against off_below (not a bare number) keeps this tied to the shipped
        # calibration, which is the pair that has to move together.
        engine, adapters, names = _engine(temp=20.0, hum=95.0, co2=600.0, minutes=0)
        engine.tick(now_s=0.0)
        heater = _adapter(adapters, names, "heater").value
        follower = _adapter(adapters, names, "heater_follower").value
        assert 0.0 < heater < 5.0
        assert abs(follower - heater * 0.8) < 1e-3

        import config

        off_below = config.DEVICE_CONFIG["regulation"]["regulators"]["humidifier"]["adapter"]["off_below"]
        humidifier = _adapter(adapters, names, "humidifier").value
        assert 0.0 < humidifier < off_below

        for ad in adapters:
            if ad.name in ("heater", "heater_follower", "humidifier"):
                continue
            assert ad.value == 0.0

    def test_growlight_follows_daylight(self):
        # Midday (b=1) → growlight target = 1.0 * light_level_day, slew 100.
        # cubensis carries no profile override, so the configured base level is
        # what lands on the dimmer.
        import config

        base = config.DEVICE_CONFIG["regulation"]["regulators"]["growlight"]["light_level_day"]
        engine, adapters, names = _engine(temp=24.0, hum=92.0, co2=700.0, minutes=720)
        engine.tick(now_s=0.0)
        assert abs(_adapter(adapters, names, "growlight").value - base) < 1e-3

    def test_growlight_dims_for_the_seedling_phase(self):
        """The shipped profile overrides the base level down to 40 % for weeks 1-2."""
        engine, adapters, names = _engine(
            temp=23.0, hum=68.0, co2=700.0, minutes=720, profile="cannabis_seedling"
        )
        engine.tick(now_s=0.0)
        assert abs(_adapter(adapters, names, "growlight").value - 40.0) < 1e-3


class TestReactions:
    def test_hot_raises_exhaust(self):
        engine, adapters, names = _engine(temp=27.0, hum=92.0, co2=700.0, minutes=720)
        engine.tick(now_s=0.0)
        assert _adapter(adapters, names, "exhaust").value > 0.0

    def test_hot_enough_turns_on_cooler_relay(self):
        engine, adapters, names = _engine(temp=28.5, hum=92.0, co2=700.0, minutes=720)
        engine.tick(now_s=0.0)
        assert _adapter(adapters, names, "cooler").active is True

    def test_co2_additive_lifts_exhaust(self):
        # Ideal temp/hum but very high CO2 → exhaust driven by the additive term.
        engine, adapters, names = _engine(temp=21.0, hum=95.0, co2=1400.0, minutes=720)
        engine.tick(now_s=0.0)
        assert _adapter(adapters, names, "exhaust").value > 0.0

    def test_co2_moves_exhaust_even_when_the_floor_is_active(self):
        # Regression (2026-07-22): the additive CO2 term is bounded by
        # co2_gain * (100 - co2_break). At the shipped 0.8 / 60.0 that ceiling
        # was 32 — below the exhaust floor of 40, which the arbiter forces
        # whenever temp or RH severity reaches the minor edge. So in any tent
        # that was not already at ideal temp AND humidity, the exhaust sat
        # pinned at the floor and CO2 from 0 to 2000 ppm changed nothing.
        #
        # Hold RH off-ideal (so the floor IS active) with temp at the day ideal
        # and vary only CO2. The exhaust surface only responds to the HIGH side
        # of each axis, so a dry room leaves it at 0 and the floor is the sole
        # contributor — which is exactly the case the ceiling used to swallow.
        floor = 5.0  # regulation.regulators.exhaust.floor
        engine_low, ad_low, names = _engine(temp=21.0, hum=85.0, co2=600.0, minutes=720)
        engine_high, ad_high, _ = _engine(temp=21.0, hum=85.0, co2=1200.0, minutes=720)
        # slew_normal caps the per-tick climb, so let both settle.
        for i in range(10):
            engine_low.tick(now_s=float(i * 30))
            engine_high.tick(now_s=float(i * 30))
        low = _adapter(ad_low, names, "exhaust").value
        high = _adapter(ad_high, names, "exhaust").value
        # The bug was low == high == floor. Assert the response first, so a
        # regression reads as "CO2 does not move the exhaust", not as a
        # constant that drifted.
        assert high > low + 20.0  # CO2 alone swings the fan by a visible margin
        assert high > floor  # stale air clears the floor on its own
        assert low == floor  # and ambient CO2 leaves only the floor

    def test_co2_lifts_circulation_as_well_as_exhaust(self):
        # Stale air is a mixing problem as much as a venting one: the exhaust
        # pulls from one point, and without the circulation pair stirring the
        # tent the dead zones between the blocks never reach it. Hold temp and
        # RH at the day ideal so the circulation surface contributes nothing and
        # the CO2 term is the only thing that can move the pair.
        engine_low, ad_low, names = _engine(temp=21.0, hum=95.0, co2=600.0, minutes=720)
        engine_high, ad_high, _ = _engine(temp=21.0, hum=95.0, co2=1400.0, minutes=720)
        for i in range(10):  # slew_normal caps the per-tick climb
            engine_low.tick(now_s=float(i * 30))
            engine_high.tick(now_s=float(i * 30))
        low = _adapter(ad_low, names, "circulation").value
        high = _adapter(ad_high, names, "circulation").value
        assert low == 0.0  # fresh air at ideal temp/RH → the pair stays off
        assert high > 20.0  # stale air spins it up on CO2 alone

    def test_heater_follower_tracks_heater(self):
        # Cold (not extreme) → heater on; follower fan = heater*0.8.
        engine, adapters, names = _engine(temp=20.0, hum=92.0, co2=700.0, minutes=720)
        engine.tick(now_s=0.0)
        heater = _adapter(adapters, names, "heater").value
        follower = _adapter(adapters, names, "heater_follower").value
        assert heater > 0.0
        assert follower > 0.0


class TestFreshAirExchangeFallback:
    """When the CO2 reading is gone, the chamber must still breathe.

    The additive CO2 term is the only path from a CO2 reading to an actuator,
    so a neutralised reading leaves no air-exchange driver at all. That is not
    a rare case on this hardware: the S8 is specified 0-95 %RH non-condensing
    and measured a 100 % failure rate above 98 %RH during the 2026-07-27..31
    run, i.e. it goes blind exactly when a fruiting chamber is at its target.
    """

    def test_idle_when_the_sensor_is_healthy(self):
        # A live reading means the real CO2 term is in charge; the fallback
        # must not add anything on top of it.
        engine, adapters, names = _engine(temp=24.0, hum=95.0, co2=600.0, minutes=720)
        assert engine._fae_floor(600.0, 720) == 0.0

    def test_floor_applied_inside_the_window_when_blind(self):
        import config

        fae = config.DEVICE_CONFIG["regulation"]["fresh_air_exchange"]
        engine, adapters, names = _engine(temp=24.0, hum=95.0, co2=None, minutes=720)
        # minute 720 % 30 == 0 → inside the duration window.
        assert engine._fae_floor(None, 720) == fae["command"]
        # 10 minutes in, past a 5-minute duration → idle again.
        assert engine._fae_floor(None, 730) == 0.0

    def test_window_reaches_the_actuators(self):
        import config

        fae = config.DEVICE_CONFIG["regulation"]["fresh_air_exchange"]
        engine, adapters, names = _engine(temp=24.0, hum=95.0, co2=None, minutes=720)
        for i in range(10):
            engine.tick(now_s=float(i * 30))
        assert _adapter(adapters, names, "exhaust").value >= fae["command"]
        assert _adapter(adapters, names, "circulation").value >= fae["command"]

    def test_fallback_never_cuts_a_stronger_demand(self):
        """It is a floor, not a setpoint — a hot tent must still vent harder."""
        import config

        fae = config.DEVICE_CONFIG["regulation"]["fresh_air_exchange"]
        engine, adapters, names = _engine(temp=29.0, hum=95.0, co2=None, minutes=720)
        for i in range(10):
            engine.tick(now_s=float(i * 30))
        assert _adapter(adapters, names, "exhaust").value > fae["command"]

    def test_schedule_is_wall_clock_not_tick_counted(self):
        """A reboot mid-cycle must resume the schedule, not restart it."""
        engine, adapters, names = _engine(temp=24.0, hum=95.0, co2=None, minutes=720)
        fresh, _, _ = _engine(temp=24.0, hum=95.0, co2=None, minutes=720)
        assert engine._fae_floor(None, 903) == fresh._fae_floor(None, 903)

    def test_disabled_block_never_engages(self):
        import copy

        import config
        from lib.regulation_engine import RegulationEngine

        reg = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        reg["fresh_air_exchange"]["enabled"] = False
        names = config._REG_NAMES
        adapters = [FakeAdapter(n) for n in names]
        engine = RegulationEngine(
            reg,
            names,
            config._REG_DIMENSIONS,
            adapters,
            FakeTh(24.0, 95.0),
            FakeCo2(None),
            FakeTime(720 * 60),
            clock=lambda: 0.0,
        )
        assert engine._fae_floor(None, 720) == 0.0


class TestSaturationDoesNotLatch:
    """A saturated tent must not be able to latch the system shut.

    Field incident 2026-07-30/31 (the internal chat-log): RH reached 100 %,
    which was exactly the cubensis at_100 anchor, so humidity deviation pinned
    at 100 and severity at its ceiling of 50. Emergency and latch both fired and
    the safe-state vector forced the heater to 0. Heater off cooled the tent,
    colder air raised RH further at unchanged absolute moisture, severity stayed
    pinned, and the release gate (emax <= 30) became unreachable. The controller
    held that state for 12.3 h with the grow light off.

    The fix is that at_100 sits at 102 %RH — above anything the sensor can read
    — so saturation now scores deviation 85.7 / severity 35.7: past the conflict
    edge, short of the emergency edge. These tests pin that boundary from both
    sides, because it is only useful if it is TIGHT: too generous and the
    exhaust stops treating saturation as urgent.
    """

    def test_saturation_does_not_latch_or_emergency(self):
        engine, adapters, names = _engine(temp=24.0, hum=100.0, co2=600.0, minutes=720)
        for i in range(6):  # well past latch.enter_ticks (3)
            engine.tick(now_s=float(i * 30))
        assert engine._arb.latched is False
        assert engine._arb.emergency_active is False

    def test_saturation_leaves_the_heater_free_to_run(self):
        # The heater is the actuator whose forced-to-0 closed the loop. It must
        # still be following its own surface at saturation, not pinned.
        engine, adapters, names = _engine(temp=21.0, hum=100.0, co2=600.0, minutes=720)
        for i in range(6):
            engine.tick(now_s=float(i * 30))
        assert _adapter(adapters, names, "heater").value > 0.0

    def test_saturation_leaves_the_growlight_on_in_daylight(self):
        # Light-off is defensible for an over-temperature emergency (lamp load).
        # For an over-humidity one it is pure loss, and light is the pinning
        # trigger for cubensis — it was dark for ~19 h during the incident.
        engine, adapters, names = _engine(temp=24.0, hum=100.0, co2=600.0, minutes=720)
        for i in range(6):
            engine.tick(now_s=float(i * 30))
        assert _adapter(adapters, names, "growlight").value > 0.0

    def test_saturation_still_vents_hard(self):
        # The anchor must not be so loose that saturation reads as unremarkable.
        # at_100 = 105 was rejected for exactly this: it halved the exhaust.
        engine, adapters, names = _engine(temp=24.0, hum=100.0, co2=600.0, minutes=720)
        for i in range(10):
            engine.tick(now_s=float(i * 30))
        assert _adapter(adapters, names, "exhaust").value == 100.0

    def test_saturation_still_cuts_the_humidifier(self):
        engine, adapters, names = _engine(temp=24.0, hum=100.0, co2=600.0, minutes=720)
        for i in range(6):
            engine.tick(now_s=float(i * 30))
        assert _adapter(adapters, names, "humidifier").value == 0.0


class TestHumidityEmergencyKeepsItsRemedies:
    """Belt and braces for the deadlock, at the layer the anchors cannot reach.

    TestSaturationDoesNotLatch covers the cubensis case, where at_100 = 102 %RH
    puts RH-driven escalation out of reach entirely. That trick is per-profile
    and the validator cannot enforce it — oyster still has at_100 = 98, so a
    saturated oyster chamber CAN still escalate on humidity. These tests force
    the reachable case and assert the cause-aware vectors hold the line anyway.
    """

    @staticmethod
    def _engine_with_reachable_humidity(**kw):
        import copy

        import config
        from lib.regulation_engine import RegulationEngine

        reg = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        for phase in ("day", "night"):
            reg["profiles"]["cubensis"][phase]["humidity"] = {"at_0": 75.0, "at_50": 92.0, "at_100": 100.0}
        names = config._REG_NAMES
        adapters = [FakeAdapter(n) for n in names]
        engine = RegulationEngine(
            reg,
            names,
            config._REG_DIMENSIONS,
            adapters,
            FakeTh(kw.get("temp", 21.0), kw.get("hum", 100.0)),
            FakeCo2(600.0),
            FakeTime(kw.get("minutes", 720) * 60),
            clock=lambda: 0.0,
        )
        return engine, adapters, names

    def test_saturation_latches_but_leaves_heater_and_light_alone(self):
        engine, adapters, names = self._engine_with_reachable_humidity(temp=21.0, hum=100.0)
        for i in range(6):
            engine.tick(now_s=float(i * 30))
        # The latch DOES fire here — that is the point of the fixture.
        assert engine._arb.latched is True
        # …but the two actuators that were wrongly cut now survive it.
        assert _adapter(adapters, names, "heater").value > 0.0
        assert _adapter(adapters, names, "growlight").value > 0.0
        # …while the ones that genuinely help are still forced.
        assert _adapter(adapters, names, "exhaust").value == 100.0
        assert _adapter(adapters, names, "humidifier").value == 0.0

    def test_a_simultaneous_heat_emergency_takes_the_heater_back(self):
        # Too hot AND too wet: the humidity relaxation must lapse, because the
        # merge only keeps an override every active cause agrees on.
        engine, adapters, names = self._engine_with_reachable_humidity(temp=30.0, hum=100.0)
        for i in range(6):
            engine.tick(now_s=float(i * 30))
        assert engine._arb.latched is True
        assert _adapter(adapters, names, "heater").value == 0.0
        assert _adapter(adapters, names, "growlight").value == 0.0


class TestEmergencyLatch:
    def test_emergency_fires_alarm_and_logs(self):
        alarms = []
        logger = pytest.importorskip("unittest.mock").Mock()
        # temp 29 at day anchors (24/30) → dev ~91.7, severity ~41.7 → emergency.
        engine, adapters, names = _engine(temp=29.0, minutes=720, alarm=alarms.append, logger=logger)
        engine.tick(now_s=0.0)
        assert engine._arb.emergency_active is True
        assert alarms == ["emergency"]
        assert _adapter(adapters, names, "exhaust").value == 100.0  # emergency_value

    def test_emergency_alarm_not_repeated(self):
        alarms = []
        engine, adapters, names = _engine(temp=29.0, minutes=720, alarm=alarms.append)
        engine.tick(now_s=0.0)
        engine.tick(now_s=1.0)
        assert alarms == ["emergency"]  # rate-limited to entry

    def test_latch_enters_and_holds_safe_state(self):
        alarms = []
        engine, adapters, names = _engine(temp=30.0, minutes=720, alarm=alarms.append)
        # latch.enter_ticks (3) consecutive ticks over the edge before it fires.
        for i in range(3):
            engine.tick(now_s=float(i))
        assert engine._arb.latched is True
        assert "latch" in alarms
        assert _adapter(adapters, names, "exhaust").value == 100.0  # safe_state

    def test_latch_waits_for_enter_ticks(self):
        # A transient over the latch edge (shorter than enter_ticks) must not
        # shut the system down — one bad sensor read or an open door.
        engine, adapters, names = _engine(temp=30.0, minutes=720)
        engine.tick(now_s=0.0)
        engine.tick(now_s=1.0)
        assert engine._arb.latched is False

    def test_dry_startup_does_not_latch_and_humidifies(self):
        # Regression (2026-07-21): a tent brought up from ambient reads far
        # below the humidity at_0 anchor and above the CO2 at_100 anchor, i.e.
        # severity 50 on both. That is the normal startup point, not an
        # emergency: before the escalation gate it latched the safe-state
        # vector on tick 1 with the humidifier forced off, so the deviation
        # could never recover and no relay ever switched again.
        #
        # Temperature sits one degree BELOW the day ideal on purpose: cold is a
        # non-escalating direction, so the startup point is far from ideal in
        # three dimensions and still must not escalate.
        engine, adapters, names = _engine(temp=20.0, hum=60.0, co2=2400.0, minutes=720)
        for i in range(10):
            engine.tick(now_s=float(i * 30))
        state = engine.get_state()
        assert state["deviations"][1] == 0.0  # bone dry
        assert state["deviations"][2] == 100.0  # stale air
        assert state["global_severity"] == 50.0
        assert state["escalation_severity"] == 0.0  # neither direction escalates
        assert engine._arb.latched is False
        assert engine._arb.emergency_active is False
        assert _adapter(adapters, names, "humidifier").active is True
        assert _adapter(adapters, names, "exhaust").value > 0.0

    def test_hot_latch_leaves_cooler_free_to_run(self):
        # The latch safe-state pins heat/humidity sources off but leaves the
        # cooler on its organic command, so the condition that latched can
        # actually clear.
        engine, adapters, names = _engine(temp=30.0, minutes=720)
        for i in range(3):
            engine.tick(now_s=float(i))
        assert engine._arb.latched is True
        assert _adapter(adapters, names, "heater").value == 0.0
        assert _adapter(adapters, names, "cooler").value > 0.0


class TestExternalGate:
    def test_external_hotter_outside_suppresses_exhaust(self):
        # Outside hotter than inside → exhaust effectiveness floored. temp 24.5
        # (deviation 69) puts the surface output well above the exhaust floor
        # so the suppression is observable, while staying under the deviation
        # at which the surface saturates at 100 — where both cases would tie
        # and the assertion could not see a difference.
        engine_gated, ad_gated, names = _engine(temp=24.5, minutes=720, external_read=lambda: (35.0, 50.0))
        engine_open, ad_open, _ = _engine(temp=24.5, minutes=720)
        engine_gated.tick(now_s=0.0)
        engine_open.tick(now_s=0.0)
        assert _adapter(ad_gated, names, "exhaust").value < _adapter(ad_open, names, "exhaust").value


class TestState:
    def test_get_state_shape(self):
        engine, adapters, names = _engine(temp=27.0, minutes=720)
        engine.tick(now_s=0.0)
        state = engine.get_state()
        assert set(state["commanded"].keys()) == set(names)
        assert "latched" in state and "band" in state
        assert len(state["deviations"]) == 3

    def test_get_state_exposes_tick_timing(self):
        engine, adapters, names = _engine(temp=24.0, minutes=720)
        state = engine.get_state()
        # Present and integer even before run() has measured anything.
        assert isinstance(state["tick_us"], int)
        assert isinstance(state["tick_max_us"], int)
        assert state["tick_us"] == 0 and state["tick_max_us"] == 0


class TestTickTiming:
    async def test_run_records_tick_duration(self):
        import uasyncio as asyncio

        engine, adapters, names = _engine(temp=24.0, minutes=720, tick_s=0.001)

        # Deterministic microsecond clock: +100 us per read. run() reads start
        # then end per tick, so tick 1 spans 100->200 us (duration 100).
        ticks = {"v": 0}

        def fake_us():
            ticks["v"] += 100
            return ticks["v"]

        engine._ticks_us = fake_us

        counter = {"n": 0}
        real_tick = engine.tick

        def counting(now_s=None):
            counter["n"] += 1
            if counter["n"] >= 2:
                raise asyncio.CancelledError
            real_tick(now_s)

        engine.tick = counting
        with pytest.raises(asyncio.CancelledError):
            await engine.run()

        assert engine._last_tick_us == 100
        assert engine._max_tick_us == 100
        assert engine.get_state()["tick_us"] == 100

    def test_reset_tick_peak(self):
        engine, adapters, names = _engine(temp=24.0, minutes=720)
        engine._max_tick_us = 4200
        engine.reset_tick_peak()
        assert engine._max_tick_us == 0


class TestRunLoop:
    async def test_run_ticks_then_cancellable(self):
        import uasyncio as asyncio

        engine, adapters, names = _engine(temp=24.0, minutes=720, tick_s=0.001)
        counter = {"n": 0}
        real_tick = engine.tick

        def counting(now_s=None):
            counter["n"] += 1
            if counter["n"] >= 2:
                raise asyncio.CancelledError
            real_tick(now_s)

        engine.tick = counting
        with pytest.raises(asyncio.CancelledError):
            await engine.run()
        assert counter["n"] >= 2


# --- humidifier effectiveness watchdog ------------------------------------


class FakeStatus:
    def __init__(self):
        self.calls = []
        self.active = set()

    def set_warning(self, key, active):
        self.calls.append((key, active))
        if active:
            self.active.add(key)
        else:
            self.active.discard(key)


class _HumidifierRig:
    """Engine plus the handles an effectiveness test needs, on a fake clock.

    Held at cubensis day anchors with the tent dry (RH 60 against a 75 % at_0),
    which parks the humidifier surface at command 100 — far above the adapter's
    on_above of 18 — so the command is "on" until a test raises RH enough to
    push it back down.
    """

    KEY = "humidifier_ineffective"

    def __init__(self, hum=60.0, temp=21.0, window_s=100.0, min_rise=0.5, dt=30.0):
        import config
        from lib.regulation_engine import RegulationEngine

        reg = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        # Pinned to cubensis for the same reason _engine() is: the RH numbers
        # below are physical and only mean "bone dry" against those anchors.
        reg["profile"] = "cubensis"
        reg["phase_schedule"] = dict(reg["phase_schedule"], enabled=False)
        reg["humidifier_watchdog"]["ineffective_window_s"] = window_s
        reg["humidifier_watchdog"]["ineffective_min_rise"] = min_rise
        self.names = config._REG_NAMES
        self.adapters = [FakeAdapter(n) for n in self.names]
        self.th = FakeTh(temp, hum)
        self.status = FakeStatus()
        self.alarms = []
        self.logger = pytest.importorskip("unittest.mock").Mock()
        self.engine = RegulationEngine(
            reg,
            self.names,
            config._REG_DIMENSIONS,
            self.adapters,
            self.th,
            FakeCo2(600.0),
            FakeTime(720 * 60),
            logger=self.logger,
            alarm_cb=self.alarms.append,
            status_manager=self.status,
            clock=lambda: 0.0,
        )
        self._t = 0.0
        self._dt = dt

    _KEEP = object()  # "leave the reading alone" — None means a dead sensor

    def tick(self, rh=_KEEP):
        if rh is not self._KEEP:
            self.th.last_humidity = rh
        self.engine.tick(now_s=self._t)
        self._t += self._dt

    def run(self, seconds, rh=_KEEP):
        """Tick for at least `seconds` of fake time."""
        end = self._t + seconds
        while self._t <= end:
            self.tick(rh)

    @property
    def command(self):
        return _adapter(self.adapters, self.names, "humidifier").value

    @property
    def warned(self):
        return self.KEY in self.status.active

    @property
    def warn_lines(self):
        return [c for c in self.logger.warning.call_args_list if "humidifier" in str(c)]


class TestHumidifierEffectiveness:
    """The relay switches mains power to a device that reports nothing back.

    At the RH the seedling and stretch phases ask for, the reservoir empties
    faster than it is refilled, so "commanded on but dead" is the routine state
    and the controller cannot see it. The only evidence is effect: field
    episodes with a working humidifier gained 1.1 / 0.97 / 5.0 RH points per
    hour, the one with an empty tank LOST 1.3 — a half point per hour separates
    them cleanly. Monitor only: every assertion below is about a warning, never
    about an actuator.
    """

    def test_flat_humidity_under_continuous_demand_warns_exactly_once(self):
        rig = _HumidifierRig()
        rig.tick()
        assert rig.command > 18.0  # the relay really is being asked to run
        rig.run(150.0)  # one full 100 s window of unanswered demand
        assert rig.warned is True
        assert rig.status.calls == [(rig.KEY, True)]
        assert len(rig.warn_lines) == 1
        assert rig.alarms == ["supply"]

        rig.run(400.0)  # four more windows of the same fault
        assert rig.status.calls == [(rig.KEY, True)]
        assert len(rig.warn_lines) == 1
        assert rig.alarms == ["supply"]

    def test_falling_humidity_under_demand_warns(self):
        """The empty-tank field episode: commanded on and RH going backwards."""
        rig = _HumidifierRig()
        rh = 60.0
        for _ in range(6):
            rig.tick(rh)
            rh -= 0.2
        assert rig.warned is True
        assert rig.alarms == ["supply"]

    def test_rising_humidity_never_warns(self):
        """A working humidifier gains more than the threshold per window."""
        rig = _HumidifierRig()
        rh = 60.0
        for _ in range(40):  # 1200 s = twelve windows
            rig.tick(rh)
            rh += 0.3  # 0.9 points per 100 s window, comfortably over 0.5
        assert rig.warned is False
        assert rig.status.calls == []
        assert rig.alarms == []

    def test_interrupted_demand_restarts_the_window(self):
        """A humidifier that was off for part of the window was never tested."""
        rig = _HumidifierRig()
        rig.run(60.0)  # 60 s of the 100 s window accumulated at RH 60
        # One tick wet enough to push the command under on_above (surface cuts
        # back hard above dev 55), then straight back to bone dry.
        rig.tick(97.0)
        assert rig.command <= 18.0
        rig.tick(60.0)
        # 60 s more: past the original window's deadline, but only 60 s into the
        # restarted one.
        rig.run(60.0)
        assert rig.warned is False
        assert rig.alarms == []
        # Give the restarted window its full length and it fires normally.
        rig.run(100.0)
        assert rig.warned is True

    def test_recovery_clears_the_warning_and_re_arms(self):
        """A refilled tank clears it, and a second outage can warn again."""
        rig = _HumidifierRig()
        rig.run(150.0)
        assert rig.warned is True

        rig.tick(61.0)  # +1.0 over the RH the warning fired at
        assert rig.warned is False
        assert rig.status.calls == [(rig.KEY, True), (rig.KEY, False)]

        rig.run(150.0, rh=61.0)  # flat again for a full window
        assert rig.warned is True
        assert rig.status.calls == [(rig.KEY, True), (rig.KEY, False), (rig.KEY, True)]
        assert rig.alarms == ["supply", "supply"]

    def test_a_missing_reading_disarms_instead_of_accumulating(self):
        """A blind sensor cannot testify that the humidifier is failing."""
        rig = _HumidifierRig()
        rig.run(60.0)
        rig.tick(None)  # sensor gone: humidity deviation neutralised
        rig.run(60.0, rh=60.0)
        assert rig.warned is False

    def test_absent_config_block_makes_the_watchdog_inert(self):
        """An older config without the block must behave exactly as before."""
        import config
        from lib.regulation_engine import RegulationEngine

        reg = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        del reg["humidifier_watchdog"]
        names = config._REG_NAMES
        adapters = [FakeAdapter(n) for n in names]
        status = FakeStatus()
        engine = RegulationEngine(
            reg,
            names,
            config._REG_DIMENSIONS,
            adapters,
            FakeTh(21.0, 60.0),
            FakeCo2(600.0),
            FakeTime(720 * 60),
            status_manager=status,
            clock=lambda: 0.0,
        )
        assert engine._hum_watch is False
        for i in range(200):
            engine.tick(now_s=float(i * 30))
        assert status.calls == []

    def test_no_status_manager_is_a_no_op_not_a_crash(self):
        """Headless builds pass no sink; the detector must still not blow up."""
        rig = _HumidifierRig()
        rig.engine._status = None
        rig.run(150.0)
        assert rig.alarms == ["supply"]  # the rest of the side effects still fire


# --- week-based phase schedule ------------------------------------------


_START = (2026, 9, 1)


def _date_at(offset_days, start=_START):
    """Calendar date `offset_days` after the schedule start (host-only helper)."""
    import datetime

    d = datetime.date(*start) + datetime.timedelta(days=offset_days)
    return (d.year, d.month, d.day)


def _sched_engine(
    offset_days=0,
    minutes=720,
    logger=None,
    mutate=None,
    enabled=True,
    temp=23.0,
    hum=60.0,
    external_read=None,
    status_manager=None,
):
    """Engine with the cannabis phase schedule live, clocked `offset_days` in."""
    import config
    from lib.regulation_engine import RegulationEngine

    reg = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
    reg["phase_schedule"]["enabled"] = enabled
    reg["phase_schedule"]["start_date"] = _START
    reg["profile"] = reg["phase_schedule"]["phases"][0]["profile"]
    if external_read is not None:
        reg["external_sensor"]["enabled"] = True
    if mutate is not None:
        mutate(reg)
    names = config._REG_NAMES
    adapters = [FakeAdapter(n) for n in names]
    clock = FakeTime(minutes * 60, date=_date_at(offset_days))
    engine = RegulationEngine(
        reg,
        names,
        config._REG_DIMENSIONS,
        adapters,
        FakeTh(temp, hum),
        FakeCo2(800.0),
        clock,
        external_read=external_read,
        logger=logger,
        status_manager=status_manager,
        clock=lambda: 0.0,
    )
    return engine, adapters, names, clock


class TestPhaseSchedule:
    """Absolute, date-driven phase advance (2 weeks seedling, 3 stretch, bloom)."""

    def test_phase_boundaries(self):
        # The edges, not the middles: day 13 is the last seedling day, day 14
        # the first stretch day, day 34 the last stretch day, day 35 bloom.
        for offset, expected in ((0, "seedling"), (13, "seedling"), (14, "stretch"), (34, "stretch"), (35, "bloom")):
            engine, adapters, names, clock = _sched_engine(offset_days=offset)
            engine.tick(now_s=0.0)
            assert engine.get_state()["phase"] == expected, offset

    def test_date_before_start_holds_the_first_phase(self):
        """A start_date in the future is not a crash and not phase -1."""
        engine, adapters, names, clock = _sched_engine(offset_days=-40)
        engine.tick(now_s=0.0)
        assert engine.get_state()["phase"] == "seedling"

    def test_rtc_failure_holds_the_phase_and_warns_once(self):
        """(0,0,0) is a dead clock: never derive a phase from it."""
        logger = pytest.importorskip("unittest.mock").Mock()
        engine, adapters, names, clock = _sched_engine(offset_days=35, logger=logger)
        engine.tick(now_s=0.0)
        assert engine.get_state()["phase"] == "bloom"
        logger.reset_mock()

        clock.date = (0, 0, 0)
        for i in range(5):
            engine.tick(now_s=float(i))
        assert engine.get_state()["phase"] == "bloom"
        assert logger.warning.call_count == 1

        # A recovered clock resumes normal advance (the failure did not poison
        # the cached date).
        clock.date = _date_at(35)
        engine.tick(now_s=99.0)
        assert engine.get_state()["phase"] == "bloom"

    def test_same_day_ticks_do_not_re_derive(self):
        """Only a date CHANGE does schedule math — 2879 of 2880 ticks are free."""
        logger = pytest.importorskip("unittest.mock").Mock()
        engine, adapters, names, clock = _sched_engine(offset_days=13, logger=logger)
        engine.tick(now_s=0.0)
        clock.date = _date_at(14)
        engine.tick(now_s=1.0)
        assert engine.get_state()["phase"] == "stretch"
        changes = [c for c in logger.info.call_args_list if "phase" in str(c)]
        assert len(changes) == 1
        # Twenty more ticks on the same date must not log or activate again.
        for i in range(20):
            engine.tick(now_s=float(2 + i))
        changes = [c for c in logger.info.call_args_list if "phase" in str(c)]
        assert len(changes) == 1

    def test_new_day_inside_a_phase_does_not_reactivate(self):
        """A date change is the trigger, not the event: same phase = no-op."""
        logger = pytest.importorskip("unittest.mock").Mock()
        engine, adapters, names, clock = _sched_engine(offset_days=0, logger=logger)
        engine.tick(now_s=0.0)
        norm = engine._norm
        for day in range(1, 13):  # still seedling every one of them
            clock.date = _date_at(day)
            engine.tick(now_s=float(day))
        assert engine.get_state()["phase"] == "seedling"
        assert engine._norm is norm  # profile state was never rebuilt
        assert [c for c in logger.info.call_args_list if "phase" in str(c)] == []

    def test_all_phases_elapsed_holds_the_last_one(self):
        """A schedule with no open-ended phase still has to answer for day 500."""

        def mutate(reg):
            reg["phase_schedule"]["phases"][-1]["weeks"] = 1

        engine, adapters, names, clock = _sched_engine(offset_days=500, mutate=mutate)
        assert engine.get_state()["phase"] == "bloom"

    def test_failing_notice_callback_does_not_stop_the_engine(self):
        """The OLED sink is a notice, not a dependency."""
        logger = pytest.importorskip("unittest.mock").Mock()
        engine, adapters, names, clock = _sched_engine(offset_days=13, logger=logger)
        engine.set_phase_change_callback(lambda *a: 1 / 0)
        engine.tick(now_s=0.0)
        clock.date = _date_at(14)
        engine.tick(now_s=1.0)
        assert engine.get_state()["phase"] == "stretch"
        assert logger.warning.call_count == 1

    def test_reboot_lands_in_the_right_phase_at_construction(self):
        """A controller restarted deep in a grow must not replay week one."""
        engine, adapters, names, clock = _sched_engine(offset_days=60)
        assert engine.get_state()["phase"] == "bloom"
        assert engine.get_state()["profile"] == "cannabis_bloom"

    def test_phase_change_notifies_the_callback(self):
        seen = []
        engine, adapters, names, clock = _sched_engine(offset_days=13)
        engine.set_phase_change_callback(lambda old, new, date, summary: seen.append((old, new, date, summary)))
        engine.tick(now_s=0.0)
        assert seen == []  # no change yet

        clock.date = _date_at(14)
        engine.tick(now_s=1.0)
        assert len(seen) == 1
        old, new, date, summary = seen[0]
        assert old == "seedling"
        assert new == "stretch"
        assert date == _date_at(14)
        assert summary["profile"] == "cannabis_stretch"

    def test_light_level_override_applied_then_dropped(self):
        """Seedlings run at 40 %; stretch has no override so the base 80 returns."""
        import config

        base = config.DEVICE_CONFIG["regulation"]["regulators"]["growlight"]["light_level_day"]
        engine, adapters, names, clock = _sched_engine(offset_days=0, minutes=720)
        engine.tick(now_s=0.0)
        assert abs(_adapter(adapters, names, "growlight").value - 40.0) < 1e-3

        clock.date = _date_at(14)
        for i in range(5):  # slew-limited toward the new level
            engine.tick(now_s=float(i))
        assert abs(_adapter(adapters, names, "growlight").value - base) < 1e-3

    def test_surface_override_applied_then_reverted(self):
        """A phase's surface_overrides are merged on activation and dropped after.

        Readings are held at 23 C / 43 %RH, which parks the exhaust surface at
        its floor in the seedling and bloom phases, so the stretch phase's
        override is the only thing that can move the fan. Bloom carries no
        override, which proves the merge is re-done from the base surface each
        time rather than accumulating.
        """
        from lib.regulation_surface import P_OFFSET

        def mutate(reg):
            reg["profiles"]["cannabis_stretch"]["surface_overrides"] = {"exhaust": {"offset": 500.0}}

        engine, adapters, names, clock = _sched_engine(offset_days=0, mutate=mutate, temp=23.0, hum=43.0)
        exhaust = _adapter(adapters, names, "exhaust")
        floor = engine._regulators["exhaust"]["floor"]
        i_exhaust = names.index("exhaust")

        engine.tick(now_s=0.0)
        assert engine._surface_params[i_exhaust][P_OFFSET] == 0.0
        assert exhaust.value <= floor

        clock.date = _date_at(14)
        for i in range(10):  # slew-limited climb to the overridden ceiling
            engine.tick(now_s=float(i))
        assert engine._surface_params[i_exhaust][P_OFFSET] == 500.0
        assert exhaust.value == 100.0

        clock.date = _date_at(35)
        for i in range(10, 40):
            engine.tick(now_s=float(i))
        assert engine._surface_params[i_exhaust][P_OFFSET] == 0.0
        assert exhaust.value <= floor  # back off the ceiling the override held

    def test_bloom_never_humidifies_however_dry_it_gets(self):
        """Bloom's neutral surface override silences the humidifier for good.

        The relay switches the appliance's 230 V supply, so "off" here means the
        humidifier is unplugged for the whole phase — which is what bloom wants:
        with no humidifier the tent settles at 45-49 %RH against a 43 % ideal,
        and there is no dehumidifier to undo an over-correction. Feed it air far
        drier than its own at_0 anchor (28 %RH) so the un-overridden surface
        would be screaming for moisture, and assert nothing moves.
        """
        engine, adapters, names, clock = _sched_engine(offset_days=35, temp=23.0, hum=15.0)
        humidifier = _adapter(adapters, names, "humidifier")
        assert engine.get_state()["phase"] == "bloom"

        for i in range(20):
            engine.tick(now_s=float(i * 30))
            assert humidifier.value == 0.0, i
            assert humidifier.active is False, i
        # Bone dry: the deviation confirms the surface was given every reason.
        assert engine.get_state()["deviations"][1] == 0.0

    def test_seedling_and_stretch_still_humidify(self):
        """Control: the override is bloom's alone, not a global disable."""
        for offset, phase in ((0, "seedling"), (14, "stretch")):
            engine, adapters, names, clock = _sched_engine(offset_days=offset, temp=23.0, hum=15.0)
            assert engine.get_state()["phase"] == phase
            for i in range(10):
                engine.tick(now_s=float(i * 30))
            humidifier = _adapter(adapters, names, "humidifier")
            assert humidifier.value > 0.0, phase
            assert humidifier.active is True, phase

    def test_advancing_into_bloom_drops_a_running_humidifier(self):
        """The override lands on the phase change, not only on a cold boot."""
        engine, adapters, names, clock = _sched_engine(offset_days=34, temp=23.0, hum=15.0)
        humidifier = _adapter(adapters, names, "humidifier")
        for i in range(5):
            engine.tick(now_s=float(i * 30))
        assert humidifier.value > 0.0  # stretch is still humidifying

        clock.date = _date_at(35)
        engine.tick(now_s=200.0)
        assert engine.get_state()["phase"] == "bloom"
        assert humidifier.value == 0.0
        assert humidifier.active is False

    def test_disabled_schedule_is_inert(self):
        """enabled: False → the clock is never asked for a date and nothing moves."""
        engine, adapters, names, clock = _sched_engine(offset_days=60, enabled=False)
        for i in range(3):
            engine.tick(now_s=float(i))
        assert clock.date_calls == 0
        assert engine.get_state()["phase"] is None
        # The configured profile stays active — no schedule override.
        assert engine.get_state()["profile"] == "cannabis_seedling"

    def test_a_disabled_schedule_leaves_the_configured_profile_alone(self):
        """Turning the schedule off is still a supported state (e.g. a mushroom run)."""
        import config

        base = config.DEVICE_CONFIG["regulation"]["regulators"]["growlight"]["light_level_day"]
        engine, adapters, names = _engine(temp=24.0, hum=95.0, co2=700.0, minutes=720)
        for i in range(5):
            engine.tick(now_s=float(i))
        assert engine.get_state()["phase"] is None
        assert engine.get_state()["profile"] == "cubensis"
        assert abs(_adapter(adapters, names, "growlight").value - base) < 1e-3

    def test_the_shipped_config_boots_into_the_seedling_phase(self):
        """Live config + the go-live date: the engine starts the grow in seedling."""
        import copy as _copy

        import config
        from lib.regulation_engine import RegulationEngine

        reg = _copy.deepcopy(config.DEVICE_CONFIG["regulation"])
        names = config._REG_NAMES
        adapters = [FakeAdapter(n) for n in names]
        start = reg["phase_schedule"]["start_date"]
        engine = RegulationEngine(
            reg,
            names,
            config._REG_DIMENSIONS,
            adapters,
            FakeTh(23.0, 68.0),
            FakeCo2(700.0),
            FakeTime(720 * 60, date=start),
            clock=lambda: 0.0,
        )
        engine.tick(now_s=0.0)
        state = engine.get_state()
        assert state["phase"] == "seedling"
        assert state["profile"] == "cannabis_seedling"
        assert abs(_adapter(adapters, names, "growlight").value - 40.0) < 1e-3


# --- RH-target reachability monitor --------------------------------------


class _RoomRig:
    """Schedule engine with a settable room (intake) sensor on a fake clock."""

    KEY = "rh_target_unreachable"

    def __init__(self, offset_days=35, room=(21.0, 55.0), window_s=100.0, margin=None, dt=30.0):
        self.room = room
        self.reads = 0

        def external_read():
            self.reads += 1
            return self.room

        def mutate(reg):
            ext = reg["external_sensor"]
            ext["rh_unreachable_window_s"] = window_s
            if margin is not None:
                ext["rh_unreachable_margin"] = margin

        self.status = FakeStatus()
        self.logger = pytest.importorskip("unittest.mock").Mock()
        self.engine, self.adapters, self.names, self.clock = _sched_engine(
            offset_days=offset_days,
            temp=23.0,
            hum=45.0,
            mutate=mutate,
            external_read=external_read,
            status_manager=self.status,
            logger=self.logger,
        )
        self._t = 0.0
        self._dt = dt

    def tick(self):
        self.engine.tick(now_s=self._t)
        self._t += self._dt

    def run(self, seconds):
        end = self._t + seconds
        while self._t <= end:
            self.tick()

    @property
    def warned(self):
        return self.KEY in self.status.active

    @property
    def warn_lines(self):
        return [c for c in self.logger.warning.call_args_list if "unreachable" in str(c)]


class TestRhTargetUnreachable:
    """The tent cannot get below the room it stands in.

    Exhaust dilutes toward room air and there is no dehumidifier, so an RH ideal
    well under the room's own humidity is not a setpoint the actuators can miss
    — it is one they cannot reach. The operator decision is to hold the setpoint
    and raise a warning rather than slide the target to whatever is achievable
    today. Monitor only: no actuator, no buzzer.
    """

    def test_sustained_excess_warns_once(self):
        # Bloom ideal 43 %RH against a 55 % room: 12 points over a 5-point margin.
        rig = _RoomRig(offset_days=35, room=(21.0, 55.0))
        assert rig.engine.get_state()["phase"] == "bloom"
        rig.tick()
        assert rig.warned is False  # the window has to be sustained
        rig.run(150.0)
        assert rig.warned is True
        assert rig.status.calls == [(rig.KEY, True)]
        assert len(rig.warn_lines) == 1

        rig.run(400.0)  # still over, still one warning
        assert rig.status.calls == [(rig.KEY, True)]
        assert len(rig.warn_lines) == 1

    def test_same_room_never_warns_for_seedling(self):
        """The verdict follows the ACTIVE profile, not a config constant.

        Seedling wants 68 %RH — a 55 % room is drier than the target, which is
        the humidifier's problem and not this detector's.
        """
        rig = _RoomRig(offset_days=0, room=(21.0, 55.0))
        assert rig.engine.get_state()["phase"] == "seedling"
        rig.run(600.0)
        assert rig.warned is False
        assert rig.status.calls == []

    def test_advancing_into_bloom_flips_the_verdict(self):
        """One room, one sensor: only the phase change makes it unreachable."""
        rig = _RoomRig(offset_days=34, room=(21.0, 55.0))
        rig.run(600.0)
        assert rig.warned is False  # stretch wants 50 %RH: 5 points, not over

        rig.clock.date = _date_at(35)
        rig.run(300.0)
        assert rig.engine.get_state()["phase"] == "bloom"
        assert rig.warned is True

    def test_within_the_margin_never_warns(self):
        """Exactly at the margin is reachable enough — the check is strict."""
        rig = _RoomRig(offset_days=35, room=(21.0, 48.0))  # 43 + 5.0 exactly
        rig.run(600.0)
        assert rig.warned is False

    def test_recovery_clears_the_warning(self):
        rig = _RoomRig(offset_days=35, room=(21.0, 55.0))
        rig.run(150.0)
        assert rig.warned is True

        rig.room = (21.0, 44.0)  # window opened, room dried out
        rig.tick()
        assert rig.warned is False
        assert rig.status.calls == [(rig.KEY, True), (rig.KEY, False)]

        rig.room = (21.0, 55.0)  # and it can arm again
        rig.run(150.0)
        assert rig.warned is True
        assert rig.status.calls == [(rig.KEY, True), (rig.KEY, False), (rig.KEY, True)]

    def test_transient_excess_does_not_warn(self):
        """A shower next door is not an unreachable target."""
        rig = _RoomRig(offset_days=35, room=(21.0, 55.0))
        rig.run(60.0)  # 60 s of a 100 s window
        rig.room = (21.0, 44.0)
        rig.tick()  # back under: the window is discarded
        rig.room = (21.0, 55.0)
        rig.run(60.0)
        assert rig.warned is False

    def test_sensor_returning_nothing_is_silent(self):
        """A failed read is not evidence; the detector must simply do nothing."""
        rig = _RoomRig(offset_days=35, room=None)
        rig.run(600.0)
        assert rig.reads > 0
        assert rig.warned is False
        assert rig.status.calls == []

    def test_disabled_sensor_is_never_even_read(self):
        """enabled: False (the shipped default) → no I2C read, no verdict."""
        status = FakeStatus()
        reads = {"n": 0}

        def external_read():
            reads["n"] += 1
            return (21.0, 55.0)

        def mutate(reg):
            reg["external_sensor"]["enabled"] = False
            reg["external_sensor"]["rh_unreachable_window_s"] = 100.0

        engine, adapters, names, clock = _sched_engine(
            offset_days=35,
            temp=23.0,
            hum=45.0,
            mutate=mutate,
            external_read=external_read,
            status_manager=status,
        )
        for i in range(40):
            engine.tick(now_s=float(i * 30))
        assert reads["n"] == 0
        assert status.calls == []

    def test_no_external_callable_is_inert(self):
        """The sensor can be enabled in config and still fail to construct."""
        status = FakeStatus()

        def mutate(reg):
            reg["external_sensor"]["enabled"] = True
            reg["external_sensor"]["rh_unreachable_window_s"] = 100.0

        engine, adapters, names, clock = _sched_engine(
            offset_days=35, temp=23.0, hum=45.0, mutate=mutate, status_manager=status
        )
        for i in range(40):
            engine.tick(now_s=float(i * 30))
        assert status.calls == []

    def test_one_read_serves_both_consumers(self):
        """The exhaust multiplier and the monitor share a single I2C sample.

        The sample moved out of _external_mult so both can see it; the exhaust
        gate itself is still pinned by TestExternalGate.
        """
        rig = _RoomRig(offset_days=35, room=(35.0, 55.0))
        for _ in range(5):
            rig.tick()
        assert rig.reads == 5
        assert rig.engine._ext_h == 55.0
