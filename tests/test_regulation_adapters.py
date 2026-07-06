# Tests for lib/regulation_adapters.py
# PWM pass-through, circulation pair scaling, relay hysteresis + min-cycle,
# heater time-proportioning, growlight DAC path — all with a fake clock.


class FakeSwitch:
    def __init__(self):
        self.state = False
        self.on_calls = 0
        self.off_calls = 0

    def on(self):
        self.state = True
        self.on_calls += 1

    def off(self):
        self.state = False
        self.off_calls += 1

    def is_on(self):
        return self.state


class FakeOutput:
    def __init__(self):
        self.duty = None
        self.history = []

    def set_duty(self, pct):
        self.duty = pct
        self.history.append(pct)


class TestPwmAdapter:
    def test_passthrough_and_active(self):
        from lib.regulation_adapters import PwmAdapter

        out = FakeOutput()
        ad = PwmAdapter(out)
        ad.apply(63.0, 0.0)
        assert out.duty == 63.0
        assert ad.active is True
        assert ad.value == 63.0

    def test_zero_is_inactive_and_clamps(self):
        from lib.regulation_adapters import PwmAdapter

        out = FakeOutput()
        ad = PwmAdapter(out)
        ad.apply(0.0, 0.0)
        assert ad.active is False
        ad.apply(150.0, 1.0)
        assert out.duty == 100.0


class TestPwmPairAdapter:
    def test_scales_both_channels(self):
        from lib.regulation_adapters import PwmPairAdapter

        c, w = FakeOutput(), FakeOutput()
        ad = PwmPairAdapter(c, w, 1.0, 0.8)
        ad.apply(50.0, 0.0)
        assert c.duty == 50.0
        assert abs(w.duty - 40.0) < 1e-4


class TestRelayHysteresis:
    def test_hysteresis_band(self):
        from lib.regulation_adapters import RelayHysteresisAdapter

        sw = FakeSwitch()
        ad = RelayHysteresisAdapter(sw, on_above=60.0, off_below=40.0, min_on_s=0, min_off_s=0)
        ad.apply(70.0, 0.0)
        assert ad.active is True
        ad.apply(50.0, 1.0)  # inside band → stays on
        assert ad.active is True
        ad.apply(30.0, 2.0)  # below off_below → off
        assert ad.active is False
        ad.apply(50.0, 3.0)  # inside band → stays off
        assert ad.active is False

    def test_min_off_blocks_restart(self):
        from lib.regulation_adapters import RelayHysteresisAdapter

        sw = FakeSwitch()
        ad = RelayHysteresisAdapter(sw, 60.0, 40.0, min_on_s=0, min_off_s=300)
        ad.apply(70.0, 0.0)  # on
        ad.apply(30.0, 1.0)  # off
        ad.apply(70.0, 2.0)  # wants on but only 1s since off → blocked
        assert ad.active is False
        ad.apply(70.0, 400.0)  # 399s later → allowed
        assert ad.active is True

    def test_min_on_blocks_stop(self):
        from lib.regulation_adapters import RelayHysteresisAdapter

        sw = FakeSwitch()
        ad = RelayHysteresisAdapter(sw, 60.0, 40.0, min_on_s=300, min_off_s=0)
        ad.apply(70.0, 0.0)  # on
        ad.apply(10.0, 1.0)  # wants off but only 1s on → stays on
        assert ad.active is True
        ad.apply(10.0, 400.0)  # allowed now
        assert ad.active is False


class TestTimeProportion:
    def test_duty_half_on_first_half_of_window(self):
        from lib.regulation_adapters import TimeProportionAdapter

        sw = FakeSwitch()
        ad = TimeProportionAdapter(sw, window_s=100, min_on_s=0, min_off_s=0)
        ad.apply(50.0, 0.0)  # on_time = 50, elapsed 0 → on
        assert ad.active is True
        ad.apply(50.0, 40.0)  # elapsed 40 < 50 → on
        assert ad.active is True
        ad.apply(50.0, 60.0)  # elapsed 60 >= 50 → off
        assert ad.active is False
        ad.apply(50.0, 100.0)  # new window → on again
        assert ad.active is True

    def test_duty_zero_off_full_on(self):
        from lib.regulation_adapters import TimeProportionAdapter

        sw = FakeSwitch()
        ad = TimeProportionAdapter(sw, window_s=100, min_on_s=0, min_off_s=0)
        ad.apply(0.0, 0.0)
        assert ad.active is False
        ad.apply(100.0, 1.0)
        assert ad.active is True
        ad.apply(100.0, 99.0)
        assert ad.active is True

    def test_min_on_holds_through_window_boundary(self):
        from lib.regulation_adapters import TimeProportionAdapter

        sw = FakeSwitch()
        ad = TimeProportionAdapter(sw, window_s=100, min_on_s=80, min_off_s=0)
        ad.apply(50.0, 0.0)  # on
        ad.apply(50.0, 60.0)  # wants off (elapsed 60 >= 50) but on only 60s < 80 → hold
        assert ad.active is True
        ad.apply(50.0, 90.0)  # 90s on ≥ 80 → off
        assert ad.active is False


class TestGrowlightAdapter:
    def test_non_dimmable_relay_only(self):
        from lib.regulation_adapters import GrowlightAdapter

        sw = FakeSwitch()
        ad = GrowlightAdapter(sw, on_above=50.0, off_below=40.0, min_on_s=0, min_off_s=0)
        ad.apply(80.0, 0.0)
        assert ad.active is True
        ad.apply(30.0, 1.0)
        assert ad.active is False

    def test_dimmable_drives_dac(self):
        from lib.regulation_adapters import GrowlightAdapter

        sw = FakeSwitch()
        calls = []
        ad = GrowlightAdapter(
            sw, on_above=50.0, off_below=40.0, min_on_s=0, min_off_s=0, dimmable=True, dac_set=calls.append
        )
        ad.apply(80.0, 0.0)
        assert calls[-1] == 80.0
        ad.apply(30.0, 1.0)  # relay off → dac 0
        assert calls[-1] == 0.0
