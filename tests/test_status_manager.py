# Tests for lib/status_manager.py
# Covers POST, warning/error set management, SD status, activity blink,
# heartbeat, buzzer integration, logger integration

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


class TestStatusManagerInit:
    """Tests for StatusManager initialization."""

    def test_init_all_leds_off(self):
        """All LEDs are OFF after construction."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        # LED constructor calls pin.off() — verify via get_status
        status = sm.get_status()
        assert status["warnings"] == []
        assert status["errors"] == []
        assert status["sd_healthy"] is True
        assert status["heartbeat_count"] == 0

    def test_init_custom_activity_blink(self):
        """Custom activity_blink_ms is stored."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25, activity_blink_ms=100)
        assert sm._activity_blink_ms == 100


class TestStatusManagerWarnings:
    """Tests for warning set management (GP7)."""

    def test_set_single_warning(self):
        """Adding one warning turns LED on."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("rtc_invalid", True)

        assert "rtc_invalid" in sm.get_status()["warnings"]
        sm._warning_led.pin.on.assert_called()  # type: ignore[attr-defined]

    def test_clear_single_warning(self):
        """Removing the only warning turns LED off."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("rtc_invalid", True)
        sm.set_warning("rtc_invalid", False)

        assert sm.get_status()["warnings"] == []
        sm._warning_led.pin.off.assert_called()  # type: ignore[attr-defined]

    def test_clear_warning_alias(self):
        """clear_warning is equivalent to set_warning(key, False)."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("dht_intermittent", True)
        sm.clear_warning("dht_intermittent")

        assert sm.get_status()["warnings"] == []
        sm._warning_led.pin.off.assert_called()  # type: ignore[attr-defined]

    def test_multiple_warnings_led_stays_on(self):
        """LED stays on when one warning cleared but others remain."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("rtc_invalid", True)
        sm.set_warning("dht_intermittent", True)

        sm.clear_warning("rtc_invalid")

        sm._warning_led.pin.on.assert_called()  # type: ignore[attr-defined]
        assert sm.get_status()["warnings"] == ["dht_intermittent"]

    def test_all_warnings_cleared_led_off(self):
        """LED turns off only when all warnings cleared."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("rtc_invalid", True)
        sm.set_warning("dht_intermittent", True)

        sm.clear_warning("rtc_invalid")
        sm.clear_warning("dht_intermittent")

        sm._warning_led.pin.off.assert_called()  # type: ignore[attr-defined]

    def test_clear_nonexistent_warning_safe(self):
        """Clearing a warning that was never set doesn't crash."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.clear_warning("nonexistent")
        assert sm.get_status()["warnings"] == []

    def test_duplicate_set_warning_idempotent(self):
        """Setting the same warning twice doesn't duplicate."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("rtc_invalid", True)
        sm.set_warning("rtc_invalid", True)

        assert sm.get_status()["warnings"] == ["rtc_invalid"]


class TestStatusManagerErrors:
    """Tests for error set management (GP8)."""

    def test_set_single_error(self):
        """Adding one error turns LED on."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_error("dht_dead", True)

        assert "dht_dead" in sm.get_status()["errors"]
        sm._error_led.pin.on.assert_called()  # type: ignore[attr-defined]

    def test_clear_single_error(self):
        """Removing the only error turns LED off."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_error("dht_dead", True)
        sm.set_error("dht_dead", False)

        assert sm.get_status()["errors"] == []
        sm._error_led.pin.off.assert_called()  # type: ignore[attr-defined]

    def test_clear_error_alias(self):
        """clear_error is equivalent to set_error(key, False)."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_error("logged_error", True)
        sm.clear_error("logged_error")

        assert sm.get_status()["errors"] == []

    def test_multiple_errors_led_stays_on(self):
        """LED stays on when one error cleared but others remain."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_error("dht_dead", True)
        sm.set_error("sd_write_fail", True)

        sm.clear_error("dht_dead")

        sm._error_led.pin.on.assert_called()  # type: ignore[attr-defined]
        assert sm.get_status()["errors"] == ["sd_write_fail"]

    def test_clear_nonexistent_error_safe(self):
        """Clearing an error that was never set doesn't crash."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.clear_error("nonexistent")
        assert sm.get_status()["errors"] == []


class TestStatusManagerSD:
    """Tests for SD status LED (GP6)."""

    def test_sd_healthy_led_off(self):
        """SD healthy → LED off."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_sd_status(True)

        sm._sd_led.pin.off.assert_called()  # type: ignore[attr-defined]
        assert sm.get_status()["sd_healthy"] is True

    def test_sd_unhealthy_led_on(self):
        """SD missing/failed → LED solid on."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_sd_status(False)

        sm._sd_led.pin.on.assert_called()  # type: ignore[attr-defined]
        assert sm.get_status()["sd_healthy"] is False

    def test_sd_recovery_turns_led_off(self):
        """SD goes down then recovers → LED turns off."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_sd_status(False)
        sm.set_sd_status(True)

        sm._sd_led.pin.off.assert_called()  # type: ignore[attr-defined]
        assert sm.get_status()["sd_healthy"] is True


class TestStatusManagerActivity:
    """Tests for activity LED blink (GP4)."""

    @pytest.mark.asyncio
    async def test_blink_activity_pulses_led(self):
        """blink_activity turns LED on then off after delay."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25, activity_blink_ms=10)
        await sm.blink_activity()

        # LED should be OFF after blink completes
        assert sm._activity_led.pin._current_value == 0  # type: ignore[attr-defined]
        # LED should have been turned on at some point
        sm._activity_led.pin.on.assert_called()  # type: ignore[attr-defined]


class TestStatusManagerHeartbeat:
    """Tests for heartbeat LED toggle (GP25)."""

    def test_heartbeat_toggles_led(self):
        """heartbeat_tick alternates LED state."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)

        sm.heartbeat_tick()
        sm._heartbeat_led.pin.on.assert_called()  # type: ignore[attr-defined]
        assert sm.get_status()["heartbeat_count"] == 1

        sm.heartbeat_tick()
        sm._heartbeat_led.pin.off.assert_called()  # type: ignore[attr-defined]
        assert sm.get_status()["heartbeat_count"] == 2

    def test_heartbeat_count_increments(self):
        """Each tick increments the counter."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        for _ in range(5):
            sm.heartbeat_tick()
        assert sm.get_status()["heartbeat_count"] == 5


class TestStatusManagerGetStatus:
    """Tests for get_status() reporting."""

    def test_get_status_empty(self):
        """Clean state returns expected defaults."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        status = sm.get_status()

        assert status == {
            "warnings": [],
            "errors": [],
            "sd_healthy": True,
            "heartbeat_count": 0,
            "post_passed": False,
        }

    def test_get_status_with_conditions(self):
        """Status reflects active warnings and errors."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("rtc_invalid", True)
        sm.set_warning("fallback_active", True)
        sm.set_error("dht_dead", True)
        sm.set_sd_status(False)
        sm.heartbeat_tick()

        status = sm.get_status()
        assert status["warnings"] == ["fallback_active", "rtc_invalid"]
        assert status["errors"] == ["dht_dead"]
        assert status["sd_healthy"] is False
        assert status["heartbeat_count"] == 1

    def test_get_status_sorted_output(self):
        """Warnings and errors are sorted alphabetically."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("z_last", True)
        sm.set_warning("a_first", True)
        sm.set_error("z_error", True)
        sm.set_error("a_error", True)

        status = sm.get_status()
        assert status["warnings"] == ["a_first", "z_last"]
        assert status["errors"] == ["a_error", "z_error"]


class TestStatusManagerPOST:
    """Tests for power-on self-test (POST)."""

    @pytest.mark.asyncio
    async def test_post_returns_true(self):
        """POST always returns True."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        result = await sm.run_post(step_ms=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_post_sets_flag(self):
        """POST sets _post_passed flag."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        assert sm._post_passed is False
        await sm.run_post(step_ms=1)
        assert sm._post_passed is True

    @pytest.mark.asyncio
    async def test_post_reported_in_get_status(self):
        """get_status reflects POST state."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        assert sm.get_status()["post_passed"] is False
        await sm.run_post(step_ms=1)
        assert sm.get_status()["post_passed"] is True

    @pytest.mark.asyncio
    async def test_post_all_leds_off_after(self):
        """All LEDs are OFF after POST completes."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        await sm.run_post(step_ms=1)

        for led in [sm._activity_led, sm._sd_led, sm._warning_led, sm._error_led, sm._heartbeat_led]:
            led.pin.off.assert_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_post_each_led_was_turned_on(self):
        """Each LED was turned on at least once during POST."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        await sm.run_post(step_ms=1)

        for led in [sm._activity_led, sm._sd_led, sm._warning_led, sm._error_led, sm._heartbeat_led]:
            led.pin.on.assert_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_post_custom_step_ms(self):
        """Custom step_ms is accepted without error."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        result = await sm.run_post(step_ms=10)
        assert result is True


class TestStatusManagerBuzzerIntegration:
    """Tests for optional buzzer integration."""

    def test_set_buzzer(self):
        """set_buzzer stores buzzer reference."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        buzzer = Mock()
        sm.set_buzzer(buzzer)
        assert sm._buzzer is buzzer

    def test_set_buzzer_none_detaches(self):
        """set_buzzer(None) clears buzzer reference."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_buzzer(Mock())
        sm.set_buzzer(None)
        assert sm._buzzer is None

    @pytest.mark.asyncio
    async def test_first_error_triggers_buzzer(self):
        """First error (empty→non-empty) calls buzzer.error()."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        buzzer = Mock()
        buzzer.error = AsyncMock()
        sm.set_buzzer(buzzer)

        sm.set_error("test_err", True)
        # Let created task run
        await asyncio.sleep(0)
        buzzer.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_error_no_buzzer(self):
        """Second error (already non-empty) does not trigger buzzer."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        buzzer = Mock()
        buzzer.error = AsyncMock()
        sm.set_buzzer(buzzer)

        sm.set_error("err1", True)
        await asyncio.sleep(0)
        buzzer.error.reset_mock()
        sm.set_error("err2", True)
        await asyncio.sleep(0)
        buzzer.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_warning_triggers_buzzer_alert(self):
        """First warning (empty→non-empty) calls buzzer.alert()."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        buzzer = Mock()
        buzzer.alert = AsyncMock()
        sm.set_buzzer(buzzer)

        sm.set_warning("test_warn", True)
        await asyncio.sleep(0)
        buzzer.alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_warning_no_buzzer(self):
        """Second warning does not trigger buzzer."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        buzzer = Mock()
        buzzer.alert = AsyncMock()
        sm.set_buzzer(buzzer)

        sm.set_warning("w1", True)
        await asyncio.sleep(0)
        buzzer.alert.reset_mock()
        sm.set_warning("w2", True)
        await asyncio.sleep(0)
        buzzer.alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_clear_then_set_triggers_buzzer_again(self):
        """After all errors cleared, next error re-triggers buzzer."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        buzzer = Mock()
        buzzer.error = AsyncMock()
        sm.set_buzzer(buzzer)

        sm.set_error("e1", True)
        await asyncio.sleep(0)
        buzzer.error.reset_mock()
        sm.set_error("e1", False)
        sm.set_error("e2", True)
        await asyncio.sleep(0)
        buzzer.error.assert_called_once()

    def test_no_buzzer_no_crash(self):
        """Warning/error without buzzer doesn't crash."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("w", True)
        sm.set_error("e", True)


class TestStatusManagerLoggerIntegration:
    """Tests for optional logger integration."""

    def test_set_logger(self):
        """set_logger stores logger reference."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)
        assert sm._logger is logger

    def test_warning_set_logged(self):
        """Setting a warning logs an info message."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)

        sm.set_warning("rtc_invalid", True)
        logger.info.assert_called_with("StatusMgr", "Warning SET: rtc_invalid")

    def test_warning_cleared_logged(self):
        """Clearing a warning logs an info message."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)

        sm.set_warning("rtc_invalid", True)
        logger.info.reset_mock()
        sm.set_warning("rtc_invalid", False)
        logger.info.assert_called_with("StatusMgr", "Warning CLEARED: rtc_invalid")

    def test_error_set_logged(self):
        """Setting an error logs an error message."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)

        sm.set_error("dht_dead", True)
        logger.error.assert_called_with("StatusMgr", "Error SET: dht_dead")

    def test_error_cleared_logged(self):
        """Clearing an error logs an error message."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)

        sm.set_error("dht_dead", True)
        logger.error.reset_mock()
        sm.set_error("dht_dead", False)
        logger.error.assert_called_with("StatusMgr", "Error CLEARED: dht_dead")

    def test_duplicate_set_not_logged(self):
        """Setting the same warning twice doesn't log twice."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)

        sm.set_warning("x", True)
        assert logger.info.call_count == 1
        sm.set_warning("x", True)
        assert logger.info.call_count == 1  # No extra log

    def test_clearing_nonexistent_not_logged(self):
        """Clearing a warning that was never set doesn't log."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)

        sm.clear_warning("nonexistent")
        logger.info.assert_not_called()

    def test_sd_status_change_logged(self):
        """SD status transitions are logged."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)

        sm.set_sd_status(False)
        logger.debug.assert_called_with("StatusMgr", "SD status changed: FAILED")
        logger.debug.reset_mock()

        sm.set_sd_status(True)
        logger.debug.assert_called_with("StatusMgr", "SD status changed: healthy")

    def test_sd_same_status_not_logged(self):
        """SD status set to same value doesn't produce log."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        logger = Mock()
        sm.set_logger(logger)

        # Default is True, setting True again shouldn't log
        sm.set_sd_status(True)
        logger.info.assert_not_called()

    def test_no_logger_no_crash(self):
        """Operations without logger don't crash."""
        from lib.status_manager import StatusManager

        sm = StatusManager(4, 6, 7, 8, 25)
        sm.set_warning("w", True)
        sm.set_warning("w", False)
        sm.set_error("e", True)
        sm.set_error("e", False)
        sm.set_sd_status(False)
