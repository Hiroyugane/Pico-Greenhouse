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
    def __init__(self, seconds=0):
        self._seconds = seconds

    def get_seconds_since_midnight(self):
        return self._seconds


def _engine(temp=23.0, hum=92.0, co2=800.0, minutes=0, tick_s=None, alarm=None, logger=None, external_read=None):
    import config
    from lib.regulation_engine import RegulationEngine

    reg = copy.deepcopy(config.DEVICE_CONFIG["regulation"])
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
        # Night (b=0), everything at the night ideal → every command settles at 0.
        engine, adapters, names = _engine(temp=23.0, hum=92.0, co2=600.0, minutes=0)
        engine.tick(now_s=0.0)
        for ad in adapters:
            assert ad.value == 0.0

    def test_growlight_follows_daylight(self):
        # Midday (b=1) → growlight target = 1.0 * light_level_day (80), slew 100.
        engine, adapters, names = _engine(temp=24.0, hum=92.0, co2=700.0, minutes=720)
        engine.tick(now_s=0.0)
        assert abs(_adapter(adapters, names, "growlight").value - 80.0) < 1e-3


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
        engine, adapters, names = _engine(temp=24.0, hum=92.0, co2=1400.0, minutes=720)
        engine.tick(now_s=0.0)
        assert _adapter(adapters, names, "exhaust").value > 0.0

    def test_heater_follower_tracks_heater(self):
        # Cold (not extreme) → heater on; follower fan = heater*0.8.
        engine, adapters, names = _engine(temp=20.0, hum=92.0, co2=700.0, minutes=720)
        engine.tick(now_s=0.0)
        heater = _adapter(adapters, names, "heater").value
        follower = _adapter(adapters, names, "heater_follower").value
        assert heater > 0.0
        assert follower > 0.0


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
        engine, adapters, names = _engine(temp=22.6, hum=60.0, co2=2400.0, minutes=720)
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
        # Outside hotter than inside → exhaust effectiveness floored. temp 28.5
        # puts the surface output above the exhaust floor so the external
        # suppression is observable (not masked by the floor).
        engine_gated, ad_gated, names = _engine(
            temp=28.5, minutes=720, external_read=lambda: (35.0, 50.0)
        )
        engine_open, ad_open, _ = _engine(temp=28.5, minutes=720)
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
