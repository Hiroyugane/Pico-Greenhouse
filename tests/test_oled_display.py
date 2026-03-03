# Tests for lib/oled_display.py
# Dennis Hiro, 2026-03-02

import asyncio
from unittest.mock import Mock, patch

import pytest

from lib.oled_display import MENUS, OLEDDisplay

# ---------------------------------------------------------------------------
# TestOLEDDisplayInit
# ---------------------------------------------------------------------------


class TestOLEDDisplayInit:
    def test_display_on_after_successful_init(self, oled_display):
        """OLEDDisplay should report display_on=True when SSD1306 init succeeds."""
        assert oled_display.display_on is True

    def test_default_menu_is_zero(self, oled_display):
        """Default menu index should be 0 (temp)."""
        assert oled_display.current_menu == 0

    def test_init_failure_is_non_fatal(
        self,
        mock_i2c,
        time_provider,
        dht_logger,
        buffer_manager,
        mock_status_manager,
        mock_reminder,
        fan_controller,
        growlight_controller,
        mock_event_logger,
    ):
        """Display init failure should set display_on=False but not raise."""
        mock_i2c.writeto.side_effect = OSError("I2C error")
        display = OLEDDisplay(
            i2c=mock_i2c,
            time_provider=time_provider,
            dht_logger=dht_logger,
            buffer_manager=buffer_manager,
            status_manager=mock_status_manager,
            reminder=mock_reminder,
            fans=[fan_controller],
            growlight=growlight_controller,
            logger=mock_event_logger,
        )
        assert display.display_on is False

    def test_stores_all_dependencies(self, oled_display, mock_reminder, fan_controller):
        """All injected dependencies should be stored."""
        assert oled_display._reminder is mock_reminder
        assert fan_controller in oled_display._fans


# ---------------------------------------------------------------------------
# TestOLEDDisplayMenuCycling
# ---------------------------------------------------------------------------


class TestOLEDDisplayMenuCycling:
    def test_next_menu_increments(self, oled_display):
        """next_menu() should advance current_menu by 1."""
        oled_display.current_menu = 0
        oled_display.next_menu()
        assert oled_display.current_menu == 1

    def test_next_menu_wraps_around(self, oled_display):
        """next_menu() should wrap back to 0 after the last menu."""
        oled_display.current_menu = len(MENUS) - 1
        oled_display.next_menu()
        assert oled_display.current_menu == 0

    def test_next_menu_renders_immediately(self, oled_display):
        """next_menu() should trigger an immediate render for responsive UX."""
        oled_display.render = Mock()
        oled_display.next_menu()
        oled_display.render.assert_called_once()

    def test_all_menus_enumerated(self):
        """MENUS tuple should contain all expected menu IDs."""
        expected = {
            "temp",
            "humidity",
            "service",
            "sd",
            "alerts",
            "system",
            "relays",
            "co2",
        }
        assert set(MENUS) == expected


# ---------------------------------------------------------------------------
# TestOLEDDisplayLongPressActions
# ---------------------------------------------------------------------------


class TestOLEDDisplayLongPressActions:
    def test_long_press_temp_clears_history(self, oled_display):
        """Long press on temp menu should clear dht_logger reading history."""
        oled_display._dht_logger._readings_history = [(1, 20.0, 50.0)]
        oled_display.current_menu = MENUS.index("temp")
        oled_display.long_press_action()
        assert oled_display._dht_logger._readings_history == []

    def test_long_press_humidity_clears_history(self, oled_display):
        """Long press on humidity menu should clear dht_logger reading history."""
        oled_display._dht_logger._readings_history = [(1, 20.0, 50.0)]
        oled_display.current_menu = MENUS.index("humidity")
        oled_display.long_press_action()
        assert oled_display._dht_logger._readings_history == []

    def test_long_press_service_resets_reminder(self, oled_display, mock_reminder):
        """Long press on service menu should call reminder.reset()."""
        oled_display.current_menu = MENUS.index("service")
        oled_display.long_press_action()
        mock_reminder.reset.assert_called_once()

    def test_long_press_sd_triggers_remount(self, oled_display):
        """Long press on sd menu should call sd_remount_cb()."""
        oled_display.current_menu = MENUS.index("sd")
        oled_display.long_press_action()
        oled_display._sd_remount_cb.assert_called_once()

    def test_long_press_system_is_noop(self, oled_display, mock_reminder):
        """Long press on system menu should do nothing harmful."""
        oled_display.current_menu = MENUS.index("system")
        oled_display.long_press_action()
        mock_reminder.reset.assert_not_called()

    def test_long_press_renders_immediately(self, oled_display):
        """long_press_action() should trigger immediate render after handling action."""
        oled_display.current_menu = MENUS.index("service")
        oled_display.render = Mock()
        oled_display.long_press_action()
        oled_display.render.assert_called_once()

    def test_long_press_no_remount_cb_safe(
        self,
        mock_i2c,
        time_provider,
        dht_logger,
        buffer_manager,
        mock_status_manager,
        mock_reminder,
        fan_controller,
        growlight_controller,
        mock_event_logger,
    ):
        """Long press on sd with no remount_cb should not raise."""
        display = OLEDDisplay(
            i2c=mock_i2c,
            time_provider=time_provider,
            dht_logger=dht_logger,
            buffer_manager=buffer_manager,
            status_manager=mock_status_manager,
            reminder=mock_reminder,
            fans=[fan_controller],
            growlight=growlight_controller,
            sd_remount_cb=None,
            logger=mock_event_logger,
        )
        display.current_menu = MENUS.index("sd")
        display.long_press_action()  # should not raise


# ---------------------------------------------------------------------------
# TestOLEDDisplayRender
# ---------------------------------------------------------------------------


class TestOLEDDisplayRender:
    def test_render_calls_show(self, oled_display):
        """render() should call oled.show() once."""
        oled_display._oled.show = Mock()
        oled_display.render()
        oled_display._oled.show.assert_called_once()

    def test_render_noop_when_display_off(self, oled_display):
        """render() should be silent when display_on=False."""
        oled_display.display_on = False
        oled_display._oled.show = Mock()
        oled_display.render()
        oled_display._oled.show.assert_not_called()

    def test_render_error_does_not_raise(self, oled_display):
        """render() should catch exceptions and not propagate them."""
        oled_display._oled.fill = Mock(side_effect=OSError("SSD1306 error"))
        oled_display.render()  # should not raise

    @pytest.mark.parametrize("menu", MENUS)
    def test_all_menus_render_without_exception(self, oled_display, menu):
        """Every menu renderer should complete without raising."""
        oled_display.current_menu = MENUS.index(menu)
        oled_display.render()


# ---------------------------------------------------------------------------
# TestOLEDDisplayTimeout
# ---------------------------------------------------------------------------


class TestOLEDDisplayTimeout:
    async def test_refresh_loop_resets_to_menu_zero_after_timeout(self, oled_display):
        """refresh_loop should return to menu 0 after menu_timeout_s of inactivity."""
        oled_display.current_menu = 2
        oled_display._menu_timeout_s = 1
        # Set last interaction far in the past
        oled_display._last_interaction_ms = 0

        # Run one iteration by patching asyncio.sleep to stop after first call
        call_count = 0

        async def _fake_sleep(s):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("stop")

        with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
            with pytest.raises(RuntimeError, match="stop"):
                await oled_display.refresh_loop()

        assert oled_display.current_menu == 0

    async def test_refresh_loop_does_not_reset_when_within_timeout(self, oled_display):
        """refresh_loop should not reset menu when user was recently active."""
        import time

        oled_display.current_menu = 3
        oled_display._menu_timeout_s = 3600  # very long
        oled_display._last_interaction_ms = int(time.time() * 1000)  # just now

        async def _fake_sleep(s):
            raise RuntimeError("stop")

        with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
            with pytest.raises(RuntimeError, match="stop"):
                await oled_display.refresh_loop()

        assert oled_display.current_menu == 3

    async def test_refresh_loop_cancelled_error_raises(self, oled_display):
        """refresh_loop should re-raise CancelledError."""

        async def _fake_sleep(s):
            raise asyncio.CancelledError()

        with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await oled_display.refresh_loop()

    async def test_refresh_loop_unexpected_error_continues(self, oled_display):
        """Unexpected errors in refresh_loop should be caught and loop should continue."""
        call_count = 0

        async def _fake_sleep(s):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
            with patch.object(oled_display, "render", side_effect=Exception("boom")):
                with pytest.raises(asyncio.CancelledError):
                    await oled_display.refresh_loop()

        # Should have survived the first render() exception and retried
        assert call_count >= 1


# ---------------------------------------------------------------------------
# TestDHTLoggerStats  (unit tests for new stats methods)
# ---------------------------------------------------------------------------


class TestDHTLoggerStats:
    def test_get_stats_empty_returns_current(self, dht_logger):
        """get_stats() with no history should return last_temperature/humidity."""
        dht_logger.last_temperature = 22.0
        dht_logger.last_humidity = 60.0
        dht_logger._readings_history.clear()
        stats = dht_logger.get_stats(3600)
        assert stats["temp_now"] == 22.0
        assert stats["hum_now"] == 60.0
        assert stats["count"] == 0

    def test_get_stats_with_history(self, dht_logger):
        """get_stats() should compute hi/lo/avg from history."""
        import time

        now_ms = int(time.time() * 1000)
        dht_logger._readings_history = [
            (now_ms - 1000, 20.0, 50.0),
            (now_ms - 2000, 25.0, 70.0),
            (now_ms - 3000, 22.0, 60.0),
        ]
        dht_logger.last_temperature = 22.0
        dht_logger.last_humidity = 60.0
        stats = dht_logger.get_stats(3600)
        assert stats["temp_hi"] == 25.0
        assert stats["temp_lo"] == 20.0
        assert abs(stats["temp_avg"] - 22.333) < 0.01
        assert stats["count"] == 3

    def test_get_stats_window_filters_old_entries(self, dht_logger):
        """get_stats() should ignore readings outside the window."""
        import time

        now_ms = int(time.time() * 1000)
        dht_logger._readings_history = [
            (now_ms - 7200 * 1000, 99.0, 99.0),  # 2 hours ago — outside 1h window
            (now_ms - 1000, 22.0, 60.0),  # 1 second ago — inside
        ]
        stats = dht_logger.get_stats(3600)
        assert stats["count"] == 1
        assert stats["temp_hi"] == 22.0

    def test_clear_history_empties_list(self, dht_logger):
        """clear_history() should empty _readings_history."""
        dht_logger._readings_history = [(1, 20.0, 50.0), (2, 21.0, 55.0)]
        dht_logger.clear_history()
        assert dht_logger._readings_history == []


# ---------------------------------------------------------------------------
# TestServiceReminderGetStatus
# ---------------------------------------------------------------------------


class TestServiceReminderGetStatus:
    def test_get_status_returns_dict(self, time_provider):
        """ServiceReminder.get_status() should return a dict with required keys."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        handler = LEDButtonHandler(5, 9)
        reminder = ServiceReminder(
            time_provider=time_provider,
            led_handler=handler,
            days_interval=7,
            auto_register_button=False,
        )
        status = reminder.get_status()
        assert "days_elapsed" in status
        assert "days_interval" in status
        assert "is_due" in status
        assert "last_serviced" in status
        assert "days_until_due" in status
        assert status["days_interval"] == 7

    def test_get_status_due_when_elapsed_exceeds_interval(self, time_provider):
        """get_status() is_due should be True when days_elapsed >= days_interval."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        handler = LEDButtonHandler(5, 9)
        reminder = ServiceReminder(
            time_provider=time_provider,
            led_handler=handler,
            days_interval=7,
            last_serviced_timestamp="2026-01-01 00:00:00",  # 28 days before FAKE_LOCALTIME (2026-01-29)
            auto_register_button=False,
        )
        status = reminder.get_status()
        assert status["is_due"] is True
        assert status["days_until_due"] == 0
