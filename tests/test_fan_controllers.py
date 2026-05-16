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


# ============================================================================
# HeaterFollowerFanController
# ============================================================================


def _make_follower(post_run_s=60, poll_interval_s=5, duty_pct=80):
    from lib.fan_controllers import HeaterFollowerFanController

    output = Mock()
    output.name = "HeaterDist"
    state = {"on": False}

    def fake_is_on():
        return state["on"]

    def fake_set_duty(pct):
        state["on"] = pct > 0

    output.set_duty = Mock(side_effect=fake_set_duty)
    output.is_on = Mock(side_effect=fake_is_on)
    heater = Mock()
    heater.is_on = Mock(return_value=False)
    logger = Mock()
    ctrl = HeaterFollowerFanController(
        output=output,
        heater=heater,
        logger=logger,
        duty_pct=duty_pct,
        post_run_s=post_run_s,
        poll_interval_s=poll_interval_s,
        name="HeaterDist",
    )
    return ctrl, output, heater, logger


def _run_cycles(ctrl, n=1):
    """Run start_cycle for n iterations, then break out without triggering
    the cancel-cleanup path (so observable state survives for assertions).

    Uses SystemExit (a BaseException, not Exception) so the controller's
    `except Exception` doesn't catch it and the cleanup branch doesn't run.
    """
    counter = {"n": 0}

    async def fake_sleep(_):
        counter["n"] += 1
        if counter["n"] >= n:
            raise SystemExit
        return None

    async def runner():
        with patch("asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(SystemExit):
                await ctrl.start_cycle()

    asyncio.run(runner())


class TestHeaterFollowerFanControllerInit:
    def test_constructor_starts_off(self):
        ctrl, output, _, _ = _make_follower()
        # Fail safe: set_duty(0) at init
        assert output.set_duty.call_args.args[0] == 0
        assert ctrl.is_on() is False

    def test_constructor_logs(self):
        ctrl, _, _, logger = _make_follower()
        logger.info.assert_called()

    def test_default_name_from_output(self):
        from lib.fan_controllers import HeaterFollowerFanController

        output = Mock()
        output.name = "OutputName"
        output.set_duty = Mock()
        output.is_on = Mock(return_value=False)
        ctrl = HeaterFollowerFanController(
            output=output, heater=Mock(), logger=Mock(),
            duty_pct=50, post_run_s=10, poll_interval_s=1,
        )
        assert ctrl.name == "OutputName"


class TestHeaterFollowerFanControllerCycle:
    def test_heater_on_turns_fan_on(self):
        ctrl, output, heater, _ = _make_follower(post_run_s=60, poll_interval_s=5)
        heater.is_on.return_value = True
        output.set_duty.reset_mock()
        _run_cycles(ctrl, n=1)
        # First call after init when heater is on: fan should turn on at duty
        calls = [c.args[0] for c in output.set_duty.call_args_list]
        # During cycle the fan was turned on at 80%; cleanup added a 0 at the end
        assert 80 in calls

    def test_heater_off_with_no_afterrun_fan_stays_off(self):
        ctrl, output, heater, _ = _make_follower()
        heater.is_on.return_value = False
        output.set_duty.reset_mock()
        _run_cycles(ctrl, n=1)
        # No turn_on call (only the cleanup zero)
        on_calls = [c for c in output.set_duty.call_args_list if c.args[0] > 0]
        assert on_calls == []

    def test_afterrun_keeps_fan_on_after_heater_off(self):
        # post_run_s=10, poll=5 → 2 ticks of afterrun
        ctrl, output, heater, _ = _make_follower(post_run_s=10, poll_interval_s=5)

        # Tick 1: heater on, fan on, afterrun primed.
        heater.is_on.return_value = True
        _run_cycles(ctrl, n=1)
        assert ctrl.is_on() is True
        assert ctrl._afterrun_remaining_s == 10

        # Tick 2: heater off, afterrun burns down to 5, fan still on.
        heater.is_on.return_value = False
        _run_cycles(ctrl, n=1)
        assert ctrl.is_on() is True
        assert ctrl._afterrun_remaining_s == 5

        # Tick 3: afterrun burns to 0 — fan turns off.
        _run_cycles(ctrl, n=1)
        assert ctrl.is_on() is False
        assert ctrl._afterrun_remaining_s == 0

    def test_heater_recurrence_resets_afterrun(self):
        ctrl, output, heater, _ = _make_follower(post_run_s=20, poll_interval_s=5)

        heater.is_on.return_value = True
        _run_cycles(ctrl, n=1)
        heater.is_on.return_value = False
        _run_cycles(ctrl, n=1)
        # Afterrun has burned to 15
        assert ctrl._afterrun_remaining_s == 15
        # Heater fires again → afterrun reset to full
        heater.is_on.return_value = True
        _run_cycles(ctrl, n=1)
        assert ctrl._afterrun_remaining_s == 20

    def test_cancelled_sets_duty_zero(self):
        ctrl, output, heater, logger = _make_follower()
        heater.is_on.return_value = True
        output.set_duty.reset_mock()

        async def run():
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await ctrl.start_cycle()

        asyncio.run(run())
        # Cleanup forces 0
        assert output.set_duty.call_args.args[0] == 0
        logger.warning.assert_called()

    def test_unexpected_error_swallowed(self):
        ctrl, output, heater, logger = _make_follower()
        heater.is_on = Mock(side_effect=[OSError("bus glitch"), False])

        call_count = {"n": 0}

        async def fake_sleep(_):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise asyncio.CancelledError
            return None

        async def run():
            with patch("asyncio.sleep", side_effect=fake_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await ctrl.start_cycle()

        asyncio.run(run())
        logger.error.assert_called()


class TestHeaterFollowerFanControllerActions:
    def test_turn_on(self):
        ctrl, output, _, _ = _make_follower(duty_pct=70)
        output.set_duty.reset_mock()
        ctrl.turn_on()
        assert output.set_duty.call_args.args[0] == 70

    def test_turn_off_clears_afterrun(self):
        ctrl, output, _, _ = _make_follower()
        ctrl._afterrun_remaining_s = 30
        ctrl.turn_off()
        assert ctrl._afterrun_remaining_s == 0
        assert output.set_duty.call_args.args[0] == 0

    def test_get_state(self):
        ctrl, _, _, _ = _make_follower(duty_pct=80, post_run_s=60)
        state = ctrl.get_state()
        assert state["mode"] == "heater_follower"
        assert state["duty_pct"] == 80
        assert state["post_run_s"] == 60
        assert "afterrun_remaining_s" in state
        assert state["name"] == "HeaterDist"

    def test_pin_passthrough(self):
        from lib.fan_controllers import HeaterFollowerFanController

        output = Mock()
        output.name = "X"
        output.pin = "PIN_OBJ"
        output.set_duty = Mock()
        output.is_on = Mock(return_value=False)
        ctrl = HeaterFollowerFanController(
            output=output, heater=Mock(), logger=Mock(),
            duty_pct=50, post_run_s=10, poll_interval_s=1,
        )
        assert ctrl.pin == "PIN_OBJ"
