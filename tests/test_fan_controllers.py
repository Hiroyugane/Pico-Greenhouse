# Tests for lib/fan_controllers.py
# Covers AlwaysOnFanController and HeaterFollowerFanController.

import asyncio
from unittest.mock import Mock, patch

import pytest

# ============================================================================
# AlwaysOnFanController
# ============================================================================


class TestAlwaysOnFanControllerInit:
    """Constructor behavior."""

    def _make(self, duty_pct=60, refresh_interval_s=300):
        from lib.fan_controllers import AlwaysOnFanController

        output = Mock()
        output.name = "Case"
        output.set_duty = Mock()
        output.is_on = Mock(return_value=duty_pct > 0)
        logger = Mock()
        ctrl = AlwaysOnFanController(
            output=output,
            logger=logger,
            duty_pct=duty_pct,
            refresh_interval_s=refresh_interval_s,
            name="Case",
        )
        return ctrl, output, logger

    def test_constructor_sets_duty(self):
        ctrl, output, logger = self._make(duty_pct=60)
        output.set_duty.assert_called_with(60)
        assert ctrl.duty_pct == 60
        assert ctrl.refresh_interval_s == 300

    def test_constructor_logs_info(self):
        ctrl, output, logger = self._make()
        logger.info.assert_called()

    def test_name_defaults_to_output_name(self):
        from lib.fan_controllers import AlwaysOnFanController

        output = Mock()
        output.name = "OutputName"
        output.set_duty = Mock()
        output.is_on = Mock(return_value=False)
        ctrl = AlwaysOnFanController(
            output=output, logger=Mock(), duty_pct=50, refresh_interval_s=60
        )
        assert ctrl.name == "OutputName"


class TestAlwaysOnFanControllerActions:
    @pytest.fixture
    def setup(self):
        from lib.fan_controllers import AlwaysOnFanController

        output = Mock()
        output.name = "Case"
        output.set_duty = Mock()
        state = {"on": False}

        def fake_is_on():
            return state["on"]

        def fake_set_duty(pct):
            state["on"] = pct > 0

        output.set_duty.side_effect = fake_set_duty
        output.is_on.side_effect = fake_is_on
        logger = Mock()
        ctrl = AlwaysOnFanController(
            output=output, logger=logger, duty_pct=60, refresh_interval_s=300, name="Case"
        )
        return ctrl, output, logger

    def test_turn_off_zeros_duty(self, setup):
        ctrl, output, _ = setup
        ctrl.turn_off()
        # Last call is to 0
        assert output.set_duty.call_args.args[0] == 0
        assert ctrl.is_on() is False

    def test_turn_on_reasserts_default_duty(self, setup):
        ctrl, output, _ = setup
        ctrl.turn_off()
        ctrl.turn_on()
        assert output.set_duty.call_args.args[0] == 60
        assert ctrl.is_on() is True

    def test_get_state_includes_duty_and_mode(self, setup):
        ctrl, _, _ = setup
        state = ctrl.get_state()
        assert state["mode"] == "always_on"
        assert state["duty_pct"] == 60
        assert state["name"] == "Case"

    def test_pin_passthrough_when_present(self):
        from lib.fan_controllers import AlwaysOnFanController

        output = Mock()
        output.name = "X"
        output.pin = "PIN_OBJ"
        output.set_duty = Mock()
        output.is_on = Mock(return_value=False)
        ctrl = AlwaysOnFanController(
            output=output, logger=Mock(), duty_pct=50, refresh_interval_s=60
        )
        assert ctrl.pin == "PIN_OBJ"


class TestAlwaysOnFanControllerStartCycle:
    """start_cycle re-asserts duty on a timer."""

    def _make(self, duty_pct=60, refresh_interval_s=300):
        from lib.fan_controllers import AlwaysOnFanController

        output = Mock()
        output.name = "Case"
        output.set_duty = Mock()
        output.is_on = Mock(return_value=duty_pct > 0)
        logger = Mock()
        return AlwaysOnFanController(
            output=output,
            logger=logger,
            duty_pct=duty_pct,
            refresh_interval_s=refresh_interval_s,
            name="Case",
        ), output, logger

    def test_cycle_reasserts_duty(self):
        ctrl, output, _ = self._make()
        output.set_duty.reset_mock()
        # Let the first sleep return so set_duty re-asserts, then raise
        # CancelledError on the second sleep to exit cleanly.
        sleep_calls = {"n": 0}

        async def fake_sleep(_):
            sleep_calls["n"] += 1
            if sleep_calls["n"] >= 2:
                raise asyncio.CancelledError
            return None

        async def run():
            with patch("asyncio.sleep", side_effect=fake_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await ctrl.start_cycle()

        asyncio.run(run())
        # Re-assertion (set_duty=60) plus cleanup (set_duty=0) → at least 2 calls
        assert output.set_duty.call_count >= 2
        # The re-assertion call carried the configured duty
        duty_calls = [c.args[0] for c in output.set_duty.call_args_list]
        assert 60 in duty_calls

    def test_cycle_cancelled_sets_duty_zero(self):
        ctrl, output, _ = self._make()
        output.set_duty.reset_mock()

        async def run():
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await ctrl.start_cycle()

        asyncio.run(run())
        # Final set_duty call is 0 (clean shutdown)
        assert output.set_duty.call_args.args[0] == 0

    def test_cycle_swallows_unexpected_error(self):
        ctrl, output, logger = self._make()
        call_count = {"n": 0}

        async def fake_sleep(_):
            call_count["n"] += 1
            if call_count["n"] >= 3:
                raise RuntimeError("stop")
            return None

        output.set_duty = Mock(side_effect=[OSError("bus glitch"), None, None])

        async def run():
            with patch("asyncio.sleep", side_effect=fake_sleep):
                try:
                    await ctrl.start_cycle()
                except RuntimeError:
                    pass

        asyncio.run(run())
        logger.error.assert_called()
