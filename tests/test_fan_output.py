# Tests for lib/fan_output.py
# Covers FanOutput interface + RelayFanOutput adapter

import pytest


class TestFanOutputInterface:
    """The abstract FanOutput contract."""

    def test_interface_methods_raise(self):
        from lib.fan_output import FanOutput

        out = FanOutput()
        with pytest.raises(NotImplementedError):
            out.on()
        with pytest.raises(NotImplementedError):
            out.off()
        with pytest.raises(NotImplementedError):
            out.set_duty(50)
        with pytest.raises(NotImplementedError):
            out.is_on()
        with pytest.raises(NotImplementedError):
            _ = out.name


class TestRelayFanOutput:
    """RelayFanOutput adapts a RelayController to the FanOutput API."""

    @pytest.fixture
    def output(self):
        from lib.fan_output import RelayFanOutput
        from lib.relay import RelayController

        relay = RelayController(16, invert=True, name="TestFan")
        return RelayFanOutput(relay)

    def test_initial_state_off(self, output):
        assert output.is_on() is False

    def test_on_then_off(self, output):
        output.on()
        assert output.is_on() is True
        output.off()
        assert output.is_on() is False

    def test_set_duty_zero_turns_off(self, output):
        output.on()
        output.set_duty(0)
        assert output.is_on() is False

    def test_set_duty_positive_turns_on(self, output):
        output.set_duty(50)
        assert output.is_on() is True

    def test_set_duty_100_turns_on(self, output):
        output.set_duty(100)
        assert output.is_on() is True

    def test_set_duty_negative_treated_as_off(self, output):
        output.on()
        output.set_duty(-5)
        assert output.is_on() is False

    def test_name_passthrough(self, output):
        assert output.name == "TestFan"

    def test_pin_passthrough(self, output):
        from lib.relay import RelayController

        relay = RelayController(42, invert=True, name="X")
        from lib.fan_output import RelayFanOutput

        out = RelayFanOutput(relay)
        assert out.pin is relay.pin

    def test_set_duty_zero_drives_pin_off_value(self, output):
        """set_duty(0) on inverted relay should drive pin HIGH (off)."""
        output.set_duty(0)
        # Inverted relay: off = HIGH = 1
        output._relay.pin.value.assert_called_with(1)

    def test_set_duty_positive_drives_pin_on_value(self, output):
        """set_duty(>0) on inverted relay should drive pin LOW (on)."""
        output.set_duty(75)
        # Inverted relay: on = LOW = 0
        output._relay.pin.value.assert_called_with(0)
