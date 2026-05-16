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


class TestPca9685FanOutput:
    """Pca9685FanOutput adapts a PCA9685 channel to the FanOutput API."""

    @pytest.fixture
    def mock_pca(self):
        from unittest.mock import MagicMock

        pca = MagicMock()
        pca.set_duty = MagicMock()
        return pca

    @pytest.fixture
    def output(self, mock_pca):
        from lib.fan_output import Pca9685FanOutput

        return Pca9685FanOutput(mock_pca, channel=3, name="Exhaust", default_duty_pct=80)

    def test_init_writes_zero_duty(self, mock_pca):
        from lib.fan_output import Pca9685FanOutput

        Pca9685FanOutput(mock_pca, channel=5, name="X")
        mock_pca.set_duty.assert_called_with(5, 0)

    def test_initial_state_off(self, output):
        assert output.is_on() is False

    def test_name_and_channel(self, output):
        assert output.name == "Exhaust"
        assert output.channel == 3

    def test_on_uses_default_duty(self, output, mock_pca):
        output.on()
        mock_pca.set_duty.assert_called_with(3, 80)
        assert output.is_on() is True

    def test_off_writes_zero(self, output, mock_pca):
        output.on()
        output.off()
        mock_pca.set_duty.assert_called_with(3, 0)
        assert output.is_on() is False

    def test_set_duty_passthrough(self, output, mock_pca):
        output.set_duty(45)
        mock_pca.set_duty.assert_called_with(3, 45)
        assert output.is_on() is True

    def test_set_duty_clamps_negative(self, output, mock_pca):
        output.set_duty(-5)
        mock_pca.set_duty.assert_called_with(3, 0)
        assert output.is_on() is False

    def test_set_duty_clamps_over_100(self, output, mock_pca):
        output.set_duty(150)
        mock_pca.set_duty.assert_called_with(3, 100)
        assert output.is_on() is True

    def test_set_duty_zero_marks_off(self, output):
        output.set_duty(50)
        assert output.is_on() is True
        output.set_duty(0)
        assert output.is_on() is False
