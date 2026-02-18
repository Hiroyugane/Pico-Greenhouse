# Tests for lib/relay.py
# Covers RelayController, FanController, GrowlightController

import asyncio
from unittest.mock import Mock, patch

import pytest

from tests.conftest import FAKE_LOCALTIME

# ============================================================================
# RelayController
# ============================================================================


class TestRelayController:
    """Tests for RelayController base class."""

    def test_initialization_off(self, relay_controller):
        """Relay initializes to OFF state."""
        assert relay_controller.is_on() is False
        assert relay_controller.name == "TestRelay"
        assert relay_controller.invert is True

    def test_turn_on(self, relay_controller):
        """turn_on() sets state to True."""
        relay_controller.turn_on()
        assert relay_controller.is_on() is True

    def test_turn_off(self, relay_controller):
        """turn_off() sets state to False."""
        relay_controller.turn_on()
        relay_controller.turn_off()
        assert relay_controller.is_on() is False

    def test_toggle(self, relay_controller):
        """toggle() alternates state."""
        relay_controller.toggle()
        assert relay_controller.is_on() is True
        relay_controller.toggle()
        assert relay_controller.is_on() is False

    def test_get_state(self, relay_controller):
        """get_state() returns dict with expected keys."""
        state = relay_controller.get_state()
        assert "name" in state
        assert "is_on" in state
        assert "pin" in state
        assert "invert" in state
        assert state["name"] == "TestRelay"
        assert state["is_on"] is False

    def test_non_inverted_mode(self):
        """Relay with invert=False: ON=HIGH, OFF=LOW."""
        from lib.relay import RelayController

        relay = RelayController(16, invert=False, name="NonInv")
        assert relay.invert is False
        relay.turn_on()
        assert relay.is_on() is True
        relay.turn_off()
        assert relay.is_on() is False

    def test_pin_value_inverted(self):
        """Inverted relay: turn_on() calls pin.value(0), turn_off() calls pin.value(1)."""
        from lib.relay import RelayController

        relay = RelayController(16, invert=True)
        relay.turn_on()
        relay.pin.value.assert_called_with(0)  # type: ignore
        relay.turn_off()
        relay.pin.value.assert_called_with(1)  # type: ignore

    def test_pin_value_non_inverted(self):
        """Non-inverted relay: turn_on() calls pin.value(1)."""
        from lib.relay import RelayController

        relay = RelayController(16, invert=False)
        relay.turn_on()
        relay.pin.value.assert_called_with(1)  # type: ignore

    def test_default_name_from_pin(self):
        """Default name is 'Relay_{pin}'."""
        from lib.relay import RelayController

        relay = RelayController(42, invert=True)
        assert relay.name == "Relay_42"


# ============================================================================
# FanController
# ============================================================================


class TestFanController:
    """Tests for FanController (time-of-day + thermostat)."""

    def test_initialization(self, fan_controller):
        """FanController initializes with correct parameters."""
        assert fan_controller.name == "TestFan"
        assert fan_controller.interval_s == 600
        assert fan_controller.on_time_s == 20
        assert fan_controller.max_temp == 24.0
        assert fan_controller.thermostat_active is False
        assert fan_controller.thermostat_on_count == 0

    def test_thermostat_activation(self, fan_controller, mock_dht_logger):
        """Thermostat activates when temp >= max_temp."""
        mock_dht_logger.last_temperature = 24.5

        async def run_once():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan_controller.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(run_once())
        assert fan_controller.thermostat_active is True
        assert fan_controller.thermostat_on_count == 1

    def test_thermostat_release_with_hysteresis(self, fan_controller, mock_dht_logger):
        """Thermostat releases when temp < (max_temp - hysteresis)."""
        # First activate
        mock_dht_logger.last_temperature = 25.0
        fan_controller.thermostat_active = False

        async def activate():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan_controller.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(activate())
        assert fan_controller.thermostat_active is True

        # Now release (below 24.0 - 1.0 = 23.0)
        mock_dht_logger.last_temperature = 22.5

        async def release():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan_controller.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(release())
        assert fan_controller.thermostat_active is False

    def test_schedule_only_no_temperature(self, time_provider, mock_event_logger):
        """When last_temperature is None, fan follows schedule only."""
        mock_dht = Mock()
        mock_dht.last_temperature = None

        from lib.relay import FanController

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            fan = FanController(
                pin=16,
                time_provider=time_provider,
                dht_logger=mock_dht,
                logger=mock_event_logger,
                interval_s=600,
                on_time_s=20,
            )

        async def run_once():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(run_once())
        assert fan.thermostat_active is False

    def test_on_time_clamping(self, time_provider, mock_dht_logger):
        """on_time_s > interval_s gets clamped and warning logged."""
        mock_logger = Mock()
        from lib.relay import FanController

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            fan = FanController(
                pin=16,
                time_provider=time_provider,
                dht_logger=mock_dht_logger,
                logger=mock_logger,
                interval_s=10,
                on_time_s=20,
            )
        assert fan.on_time_s == 10  # Clamped to interval_s
        mock_logger.warning.assert_called()

    def test_start_cycle_cancelled_error(self, fan_controller):
        """CancelledError turns off fan and re-raises."""

        async def run():
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await fan_controller.start_cycle()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(run())
        assert fan_controller.is_on() is False

    def test_start_cycle_unexpected_error_continues(self, fan_controller, mock_dht_logger):
        """Generic exception is logged, loop continues."""
        call_count = 0

        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("stop test")
            raise ValueError("simulated error")

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=counting_sleep):
                try:
                    asyncio.run(fan_controller.start_cycle())
                except RuntimeError:
                    pass

        # The ValueError should have been caught and logged
        fan_controller.logger.error.assert_called()

    def test_get_state_includes_thermostat(self, fan_controller, mock_dht_logger):
        """get_state() includes thermostat fields."""
        state = fan_controller.get_state()
        assert "thermostat_active" in state
        assert "thermostat_activations" in state
        assert "max_temp" in state
        assert "current_temp" in state
        assert state["current_temp"] == 22.5

    def test_schedule_state_change_logging(self, fan_controller, mock_dht_logger):
        """Schedule transitions log SCHEDULE ON or SCHEDULE OFF."""
        mock_dht_logger.last_temperature = None  # No thermostat

        async def run_once():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan_controller.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(run_once())

        # Should have logged a schedule state (either ON or OFF)
        calls = [str(c) for c in fan_controller.logger.info.call_args_list]
        schedule_logged = any("SCHEDULE" in c for c in calls)
        assert schedule_logged

    def test_thermostat_turn_on_error(self, fan_controller, mock_dht_logger):
        """When turn_on() raises during thermostat activation, error is logged."""
        mock_dht_logger.last_temperature = 25.0  # Above max_temp=24.0
        fan_controller.pin.value = Mock(side_effect=OSError("pin fault"))

        async def run():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan_controller.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(run())

        # Error should have been logged for the failed turn_on
        error_calls = [str(c) for c in fan_controller.logger.error.call_args_list]
        assert any("failed to turn ON" in c for c in error_calls)

    def test_thermostat_deactivation_turn_off_error(self, fan_controller, mock_dht_logger):
        """When turn_off() raises after thermostat deactivation, error is logged."""
        # First activate thermostat
        fan_controller.thermostat_active = True
        fan_controller.thermostat_on_count = 1
        # Temperature below hysteresis threshold: 24.0 - 1.0 = 23.0
        mock_dht_logger.last_temperature = 22.5
        # Make turn_off raise
        fan_controller.pin.value = Mock(side_effect=OSError("pin fault"))

        async def run():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan_controller.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(run())

        error_calls = [str(c) for c in fan_controller.logger.error.call_args_list]
        assert any("failed to turn OFF after thermostat deactivation" in c for c in error_calls)

    def test_schedule_transition_error(self, fan_controller, mock_dht_logger):
        """When turn_on/turn_off raises during schedule transition, error is logged."""
        mock_dht_logger.last_temperature = None  # No thermostat
        fan_controller.last_schedule_state = None  # Force state change
        fan_controller.pin.value = Mock(side_effect=OSError("pin fault"))

        async def run():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan_controller.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(run())

        error_calls = [str(c) for c in fan_controller.logger.error.call_args_list]
        assert any("failed to update" in c for c in error_calls)

    def test_invalid_timing_logged(self, time_provider, mock_dht_logger):
        """on_time <= 0 or interval <= 0 logs error."""
        mock_logger = Mock()
        from lib.relay import FanController

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            FanController(
                pin=16,
                time_provider=time_provider,
                dht_logger=mock_dht_logger,
                logger=mock_logger,
                interval_s=0,
                on_time_s=0,
            )
        mock_logger.error.assert_called()


# ============================================================================
# GrowlightController
# ============================================================================


class TestGrowlightController:
    """Tests for GrowlightController (dawn/sunset scheduling)."""

    def test_initialization(self, growlight_controller):
        """GrowlightController initializes with schedule."""
        assert growlight_controller.name == "TestGrowlight"
        assert growlight_controller.dawn_hour == 6
        assert growlight_controller.sunset_hour == 20

    def test_schedule_on_during_day(self, growlight_controller):
        """Light turns ON between dawn and sunset."""
        # 10:00 = 36000 seconds (between 6:00 and 20:00)
        growlight_controller.time_provider.get_seconds_since_midnight = Mock(return_value=36000)

        async def run_once():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await growlight_controller.start_scheduler()
                except RuntimeError:
                    pass

        asyncio.run(run_once())
        assert growlight_controller.is_on() is True

    def test_schedule_off_at_night(self, growlight_controller):
        """Light turns OFF after sunset."""
        # 22:00 = 79200 seconds (after 20:00 sunset)
        growlight_controller.time_provider.get_seconds_since_midnight = Mock(return_value=79200)

        async def run_once():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await growlight_controller.start_scheduler()
                except RuntimeError:
                    pass

        asyncio.run(run_once())
        assert growlight_controller.is_on() is False

    def test_schedule_boundary_dawn(self, growlight_controller):
        """Exactly at dawn, light should be ON."""
        dawn_seconds = 6 * 3600  # 21600
        growlight_controller.time_provider.get_seconds_since_midnight = Mock(return_value=dawn_seconds)

        async def run():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await growlight_controller.start_scheduler()
                except RuntimeError:
                    pass

        asyncio.run(run())
        assert growlight_controller.is_on() is True

    def test_schedule_boundary_sunset(self, growlight_controller):
        """Exactly at sunset, light should be OFF."""
        sunset_seconds = 20 * 3600  # 72000
        growlight_controller.time_provider.get_seconds_since_midnight = Mock(return_value=sunset_seconds)

        async def run():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await growlight_controller.start_scheduler()
                except RuntimeError:
                    pass

        asyncio.run(run())
        assert growlight_controller.is_on() is False

    def test_auto_sunrise_sunset_derivation(self, time_provider, mock_event_logger):
        """Omitting dawn/sunset derives them from time_provider.sunrise_sunset()."""
        from lib.relay import GrowlightController

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            gl = GrowlightController(
                pin=17,
                time_provider=time_provider,
                logger=mock_event_logger,
                name="AutoLight",
            )
        # Should have derived dawn/sunset from sunrise_sunset()
        assert gl.dawn_hour > 0 or gl.dawn_minute > 0
        assert gl.sunset_hour > 0 or gl.sunset_minute > 0

    def test_start_scheduler_cancelled_error(self, growlight_controller):
        """CancelledError turns off light and re-raises."""
        growlight_controller.time_provider.get_seconds_since_midnight = Mock(return_value=36000)

        async def run():
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await growlight_controller.start_scheduler()

        asyncio.run(run())
        assert growlight_controller.is_on() is False

    def test_start_scheduler_unexpected_error(self, growlight_controller):
        """Generic exception is logged, loop continues."""
        call_count = 0
        growlight_controller.time_provider.get_seconds_since_midnight = Mock(side_effect=ValueError("bad"))

        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("stop test")

        with patch("asyncio.sleep", side_effect=counting_sleep):
            try:
                asyncio.run(growlight_controller.start_scheduler())
            except RuntimeError:
                pass

        growlight_controller.logger.error.assert_called()

    def test_get_state_includes_schedule(self, growlight_controller):
        """get_state() includes dawn and sunset."""
        state = growlight_controller.get_state()
        assert "dawn" in state
        assert "sunset" in state
        assert state["dawn"] == "06:00"
        assert state["sunset"] == "20:00"


class TestFanControllerHysteresisNoAction:
    """Tests for thermostat hysteresis no-action band."""

    def test_temp_in_hysteresis_band_no_state_change(self, time_provider, mock_event_logger):
        """When thermostat_active=True and temp is in hysteresis band, relay state unchanged."""
        mock_dht = Mock()
        # max_temp=25.0, hysteresis=1.0 → release threshold = 24.0
        # temp=24.5 is in the band [24.0, 25.0) → no action
        mock_dht.last_temperature = 24.5

        from lib.relay import FanController

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            fan = FanController(
                pin=16,
                time_provider=time_provider,
                dht_logger=mock_dht,
                logger=mock_event_logger,
                interval_s=600,
                on_time_s=20,
                max_temp=25.0,
                temp_hysteresis=1.0,
                name="HystFan",
            )
        # Pre-set thermostat as active (fan already ON from previous temp spike)
        fan.thermostat_active = True
        fan.thermostat_on_count = 1
        fan.turn_on()  # Fan is ON because thermostat activated it

        # Reset call tracking after setup
        fan.pin.value.reset_mock()

        # Run one cycle
        async def run_once():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await fan.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(run_once())

        # Thermostat should still be active (temp not below release threshold)
        assert fan.thermostat_active is True
        # thermostat_on_count should NOT have increased (no new activation)
        assert fan.thermostat_on_count == 1
