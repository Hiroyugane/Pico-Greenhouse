# Tests for lib/heater.py
# Covers HeaterController (active-HIGH MOSFET gate, day/night thermostat).

import asyncio
from unittest.mock import Mock, patch

import pytest

from tests.conftest import FAKE_LOCALTIME


@pytest.fixture
def heater_controller(time_provider, mock_th_logger, mock_event_logger):
    """HeaterController with mocked deps. Defaults: 06:00 day / 20:00 night."""
    from lib.heater import HeaterController

    return HeaterController(
        pin=3,
        time_provider=time_provider,
        th_logger=mock_th_logger,
        logger=mock_event_logger,
        day_min_temp=22.0,
        night_min_temp=16.0,
        temp_hysteresis=0.5,
        day_start_hour=6,
        day_start_minute=0,
        night_start_hour=20,
        night_start_minute=0,
        max_stale_reads=3,
        poll_interval_s=30,
        name="TestHeater",
    )


class TestHeaterControllerInit:
    def test_init_attributes(self, heater_controller):
        assert heater_controller.name == "TestHeater"
        assert heater_controller.day_min_temp == 22.0
        assert heater_controller.night_min_temp == 16.0
        assert heater_controller.temp_hysteresis == 0.5
        assert heater_controller.poll_interval_s == 30
        assert heater_controller.is_on() is False

    def test_active_high_init_off(self, heater_controller):
        """At init, gate is driven LOW (heater off). Active-HIGH, NOT inverted."""
        # Last pin.value call in __init__ should be 0 (LOW = off for active-HIGH)
        last_call = heater_controller.pin.value.call_args_list[-1]
        assert last_call.args == (0,)

    def test_default_name_from_pin(self, time_provider, mock_th_logger, mock_event_logger):
        from lib.heater import HeaterController

        h = HeaterController(
            pin=3,
            time_provider=time_provider,
            th_logger=mock_th_logger,
            logger=mock_event_logger,
        )
        assert h.name == "Heater_3"


class TestHeaterRelayPolarity:
    def test_turn_on_drives_gate_high(self, heater_controller):
        """turn_on() must drive pin.value(1) — active-HIGH."""
        heater_controller.turn_on()
        last = heater_controller.pin.value.call_args_list[-1]
        assert last.args == (1,)
        assert heater_controller.is_on() is True

    def test_turn_off_drives_gate_low(self, heater_controller):
        """turn_off() must drive pin.value(0)."""
        heater_controller.turn_on()
        heater_controller.turn_off()
        last = heater_controller.pin.value.call_args_list[-1]
        assert last.args == (0,)
        assert heater_controller.is_on() is False


class TestHeaterDayNightWindow:
    def test_day_window_at_midday(self, heater_controller):
        """12:00 falls in the day window (06:00 → 20:00)."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        assert heater_controller.current_setpoint() == 22.0

    def test_night_window_at_22h(self, heater_controller):
        """22:00 falls in the night window."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=22 * 3600)
        assert heater_controller.current_setpoint() == 16.0

    def test_night_window_before_dawn(self, heater_controller):
        """04:00 falls in the night window (before day starts)."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=4 * 3600)
        assert heater_controller.current_setpoint() == 16.0

    def test_day_boundary_inclusive(self, heater_controller):
        """Exactly at 06:00 → day setpoint."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=6 * 3600)
        assert heater_controller.current_setpoint() == 22.0


class TestHeaterThermostat:
    def _run_once(self, heater):
        async def runner():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await heater.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(runner())

    def test_fires_when_below_setpoint(self, heater_controller, mock_th_logger):
        """Day setpoint = 22.0; temp 20.0 → heater turns ON."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        mock_th_logger.last_temperature = 20.0
        self._run_once(heater_controller)
        assert heater_controller.is_on() is True

    def test_stays_off_above_setpoint(self, heater_controller, mock_th_logger):
        """Day setpoint = 22.0; temp 23.0 → heater stays OFF."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        mock_th_logger.last_temperature = 23.0
        self._run_once(heater_controller)
        assert heater_controller.is_on() is False

    def test_hysteresis_holds_on_in_band(self, heater_controller, mock_th_logger):
        """Heater stays ON when in [setpoint-hyst, setpoint) band."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        # Force fan ON, then run at 21.8 (in band [21.5, 22.0)) → stays on
        heater_controller.turn_on()
        mock_th_logger.last_temperature = 21.8
        self._run_once(heater_controller)
        assert heater_controller.is_on() is True

    def test_hysteresis_releases_above_setpoint(self, heater_controller, mock_th_logger):
        """Heater turns OFF when temp >= setpoint."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        heater_controller.turn_on()
        mock_th_logger.last_temperature = 22.1
        self._run_once(heater_controller)
        assert heater_controller.is_on() is False

    def test_night_setpoint_applied(self, heater_controller, mock_th_logger):
        """At night, the night_min_temp (16°C) governs."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=22 * 3600)
        # 17°C is above night setpoint of 16 → stay off
        mock_th_logger.last_temperature = 17.0
        self._run_once(heater_controller)
        assert heater_controller.is_on() is False
        # 15°C is below → turn on
        mock_th_logger.last_temperature = 15.0
        self._run_once(heater_controller)
        assert heater_controller.is_on() is True


class TestHeaterStaleReads:
    def _run_once(self, heater):
        async def runner():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await heater.start_cycle()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(runner())

    def test_no_temp_at_boot_stays_off(self, heater_controller, mock_th_logger):
        """last_temperature=None at boot → no spurious activation."""
        mock_th_logger.last_temperature = None
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        self._run_once(heater_controller)
        assert heater_controller.is_on() is False

    def test_stale_reads_within_tolerance_holds_state(self, heater_controller, mock_th_logger):
        """While stale_count <= max_stale_reads, heater holds prior state."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        # Prime: fire heater normally
        mock_th_logger.last_temperature = 20.0
        self._run_once(heater_controller)
        assert heater_controller.is_on() is True

        # Now temp goes None twice — under the limit of 3
        mock_th_logger.last_temperature = None
        self._run_once(heater_controller)
        self._run_once(heater_controller)
        assert heater_controller.is_on() is True  # held

    def test_stale_reads_exceed_limit_fails_safe_off(self, heater_controller, mock_th_logger):
        """When stale_count > max_stale_reads, heater fails safe OFF."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        # Prime: fire heater
        mock_th_logger.last_temperature = 20.0
        self._run_once(heater_controller)
        assert heater_controller.is_on() is True

        # 4 stale reads exceeds max_stale_reads=3
        mock_th_logger.last_temperature = None
        for _ in range(4):
            self._run_once(heater_controller)
        assert heater_controller.is_on() is False

    def test_fresh_read_resets_stale_counter(self, heater_controller, mock_th_logger):
        """A successful read after stale reads resets the counter."""
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        mock_th_logger.last_temperature = 20.0
        self._run_once(heater_controller)
        # 2 stale
        mock_th_logger.last_temperature = None
        self._run_once(heater_controller)
        self._run_once(heater_controller)
        # Now a good read
        mock_th_logger.last_temperature = 20.0
        self._run_once(heater_controller)
        assert heater_controller._stale_count == 0  # type: ignore[attr-defined]


class TestHeaterLifecycle:
    def test_cancelled_error_drives_gate_low(self, heater_controller):
        """CancelledError must drive the gate LOW and re-raise."""

        async def runner():
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await heater_controller.start_cycle()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(runner())
        assert heater_controller.is_on() is False

    def test_unexpected_error_keeps_loop_alive(self, heater_controller, mock_th_logger):
        """Generic exceptions get logged but the loop continues."""
        call_count = 0

        async def counting_sleep(_):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("stop test")

        heater_controller.time_provider.get_seconds_since_midnight = Mock(side_effect=ValueError("bad clock"))

        with patch("asyncio.sleep", side_effect=counting_sleep):
            try:
                asyncio.run(heater_controller.start_cycle())
            except RuntimeError:
                pass

        heater_controller.logger.error.assert_called()


class TestHeaterGetState:
    def test_get_state_includes_thermostat_fields(self, heater_controller, mock_th_logger):
        mock_th_logger.last_temperature = 19.5
        heater_controller.time_provider.get_seconds_since_midnight = Mock(return_value=12 * 3600)
        state = heater_controller.get_state()
        assert state["name"] == "TestHeater"
        assert state["current_temp"] == 19.5
        assert state["current_setpoint"] == 22.0
        assert state["is_on"] is False
