# Tests for lib/regulation_arbiter.py
# Slew limiting, forced-stage precedence, floors, conflicts, emergency, latch.

from array import array

EDGES = [5, 10, 20, 30, 40, 50]  # minor=20, conflict=30, emergency=40, latch=50


def _arb(
    n=1,
    reg_dims=None,
    slew_normal=None,
    slew_fast=None,
    floor=None,
    emergency=None,
    safe_state=None,
    conflicts=(),
    release_max=30.0,
    release_ticks=3,
    min_s=90.0,
    tick_s=30.0,
):
    from lib.regulation_arbiter import RegulationArbiter

    reg_dims = reg_dims if reg_dims is not None else tuple((0,) for _ in range(n))
    return RegulationArbiter(
        reg_dims,
        EDGES,
        slew_normal if slew_normal is not None else [10.0] * n,
        slew_fast if slew_fast is not None else [40.0] * n,
        floor if floor is not None else [0.0] * n,
        emergency if emergency is not None else [0.0] * n,
        safe_state if safe_state is not None else [0.0] * n,
        conflicts,
        release_max,
        release_ticks,
        min_s,
        tick_s,
    )


def _run(arb, target, sev, dev=None, n=1):
    dev = dev if dev is not None else [50.0, 50.0, 50.0]
    out = array("f", [0.0] * n)
    gmax = arb.arbitrate(array("f", target), array("f", sev), array("f", dev), out)
    return out, gmax


class TestSlew:
    def test_slew_normal_limits_calm_moves(self):
        arb = _arb(slew_normal=[10.0])
        out, _ = _run(arb, [100.0], [0.0, 0.0, 0.0])
        assert out[0] == 10.0  # capped from 0 → +10

    def test_slew_accumulates_across_ticks(self):
        arb = _arb(slew_normal=[10.0])
        _run(arb, [100.0], [0.0, 0.0, 0.0])
        out, _ = _run(arb, [100.0], [0.0, 0.0, 0.0])
        assert out[0] == 20.0

    def test_slew_fast_when_minor_band(self):
        # reg severity 25 (>= minor edge 20) uses slew_fast.
        arb = _arb(slew_normal=[10.0], slew_fast=[40.0])
        out, _ = _run(arb, [100.0], [25.0, 0.0, 0.0])
        assert out[0] == 40.0


class TestFloors:
    def test_floor_raises_when_banded(self):
        arb = _arb(slew_normal=[5.0], floor=[50.0])
        # reg sev 25 >= minor → floor applies after the (tiny) slew move.
        out, _ = _run(arb, [0.0], [25.0, 0.0, 0.0])
        assert out[0] == 50.0

    def test_floor_never_reduces(self):
        # slew_fast high so the organic move fully lands, then floor must not cut it.
        arb = _arb(slew_normal=[100.0], slew_fast=[100.0], floor=[50.0])
        out, _ = _run(arb, [80.0], [25.0, 0.0, 0.0])
        assert out[0] == 80.0  # max(80, floor 50)

    def test_no_floor_below_band(self):
        arb = _arb(slew_normal=[100.0], floor=[50.0])
        out, _ = _run(arb, [0.0], [5.0, 0.0, 0.0])  # sev 5 < minor
        assert out[0] == 0.0


class TestConflicts:
    def test_later_rule_wins(self):
        # Two rules, both fire when temp is above by >= 30; later forces 90.
        conflicts = (
            (((0, True, 30.0),), ((0, 10.0),), ()),
            (((0, True, 30.0),), ((0, 90.0),), ()),
        )
        arb = _arb(n=1, slew_normal=[100.0], conflicts=conflicts)
        # dev temp 85 → severity 35 (>= conflict 30, < emergency 40).
        out, gmax = _run(arb, [0.0], [35.0, 0.0, 0.0], dev=[85.0, 50.0, 50.0])
        assert gmax == 35.0
        assert out[0] == 90.0

    def test_prefer_applies_max_only(self):
        conflicts = ((((1, True, 30.0),), (), ((0, 60.0),)),)
        arb = _arb(n=1, slew_normal=[100.0], conflicts=conflicts)
        # humidity dev 85 → sev 35 triggers; target already 80 > prefer 60.
        out, _ = _run(arb, [80.0], [0.0, 35.0, 0.0], dev=[50.0, 85.0, 50.0])
        assert out[0] == 80.0

    def test_conflict_ignored_below_edge(self):
        conflicts = ((((0, True, 5.0),), ((0, 99.0),), ()),)
        arb = _arb(n=1, slew_normal=[100.0], conflicts=conflicts)
        # global severity 15 < conflict edge 30 → rule does not fire.
        out, _ = _run(arb, [10.0], [15.0, 0.0, 0.0], dev=[65.0, 50.0, 50.0])
        assert out[0] == 10.0


class TestEmergency:
    def test_emergency_forced_in_one_tick_bypassing_slew(self):
        arb = _arb(slew_normal=[1.0], emergency=[77.0])
        out, _ = _run(arb, [0.0], [45.0, 0.0, 0.0])  # sev 45 >= emergency 40
        assert out[0] == 77.0  # not 0+slew; forced
        assert arb.emergency_active is True
        assert arb.just_entered_emergency is True

    def test_emergency_entry_flag_only_once(self):
        arb = _arb(emergency=[77.0])
        _run(arb, [0.0], [45.0, 0.0, 0.0])
        out, _ = _run(arb, [0.0], [45.0, 0.0, 0.0])
        assert arb.just_entered_emergency is False  # rate-limited
        assert arb.emergency_active is True

    def test_emergency_clears_when_severity_drops(self):
        arb = _arb(emergency=[77.0])
        _run(arb, [0.0], [45.0, 0.0, 0.0])
        _run(arb, [0.0], [0.0, 0.0, 0.0])
        assert arb.emergency_active is False


class TestLatch:
    def test_latch_enters_at_50_and_holds_safe_state(self):
        arb = _arb(safe_state=[5.0])
        out, gmax = _run(arb, [100.0], [50.0, 0.0, 0.0])
        assert gmax == 50.0
        assert arb.latched is True
        assert arb.just_entered_latch is True
        assert out[0] == 5.0

    def test_latch_holds_despite_instant_recovery(self):
        # release needs 3 consecutive calm ticks AND 90 s (3 ticks at 30 s).
        arb = _arb(safe_state=[5.0], release_max=30.0, release_ticks=3, min_s=90.0, tick_s=30.0)
        _run(arb, [100.0], [50.0, 0.0, 0.0])  # entry tick
        for _ in range(2):
            out, _ = _run(arb, [100.0], [0.0, 0.0, 0.0])  # instant recovery
            assert arb.latched is True
            assert out[0] == 5.0

    def test_latch_releases_after_gate_met(self):
        arb = _arb(safe_state=[5.0], release_max=30.0, release_ticks=3, min_s=90.0, tick_s=30.0)
        _run(arb, [100.0], [50.0, 0.0, 0.0])  # entry
        _run(arb, [100.0], [0.0, 0.0, 0.0])  # calm 1
        _run(arb, [100.0], [0.0, 0.0, 0.0])  # calm 2
        out, _ = _run(arb, [100.0], [0.0, 0.0, 0.0])  # calm 3 → gate met
        assert arb.latched is False
        assert arb.just_released_latch is True

    def test_latch_release_counter_resets_on_spike(self):
        arb = _arb(safe_state=[5.0], release_max=30.0, release_ticks=2, min_s=30.0, tick_s=30.0)
        _run(arb, [100.0], [50.0, 0.0, 0.0])  # entry
        _run(arb, [100.0], [0.0, 0.0, 0.0])  # calm 1
        _run(arb, [100.0], [45.0, 0.0, 0.0])  # spike resets counter
        out, _ = _run(arb, [100.0], [0.0, 0.0, 0.0])  # calm 1 again — not yet 2 consecutive
        assert arb.latched is True


class TestBandIndex:
    def test_band_index(self):
        arb = _arb()
        assert arb.band_index(0.0) == 0
        assert arb.band_index(5.0) == 1
        assert arb.band_index(20.0) == 3
        assert arb.band_index(50.0) == 6


class TestFromConfig:
    def test_builds_from_default_config_and_runs(self):
        import config
        from lib.regulation_arbiter import RegulationArbiter

        reg = config.DEVICE_CONFIG["regulation"]
        arb = RegulationArbiter.from_config(reg, config._REG_NAMES, config._REG_DIMENSIONS, 30.0)
        n = len(config._REG_NAMES)
        out = array("f", [0.0] * n)
        # Calm: everything ideal → all commands settle at 0 (slew from 0).
        gmax = arb.arbitrate(
            array("f", [0.0] * n), array("f", [0.0, 0.0, 0.0]), array("f", [50.0, 50.0, 50.0]), out
        )
        assert gmax == 0.0
        assert all(v == 0.0 for v in out)

    def test_hot_humid_conflict_cuts_humidifier(self):
        import config
        from lib.regulation_arbiter import RegulationArbiter

        reg = config.DEVICE_CONFIG["regulation"]
        names = config._REG_NAMES
        arb = RegulationArbiter.from_config(reg, names, config._REG_DIMENSIONS, 30.0)
        n = len(names)
        out = array("f", [0.0] * n)
        # Hot + humid: temp dev 85 (sev 35), humidity dev 85 (sev 35) → the
        # shipped mold-risk rule forces humidifier to 0, prefers exhaust/cooler.
        target = array("f", [0.0] * n)
        target[names.index("humidifier")] = 100.0  # organic wants to humidify
        arb.arbitrate(target, array("f", [35.0, 35.0, 0.0]), array("f", [85.0, 85.0, 50.0]), out)
        assert out[names.index("humidifier")] == 0.0
        assert out[names.index("exhaust")] >= 60.0
        assert out[names.index("cooler")] >= 100.0
