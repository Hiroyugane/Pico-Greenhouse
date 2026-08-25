# Tests for lib/oled_display.py
# Dennis Hiro, 2026-03-02

import asyncio
import time
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
        th_logger,
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
            th_logger=th_logger,
            buffer_manager=buffer_manager,
            status_manager=mock_status_manager,
            reminder=mock_reminder,
            fans=[fan_controller],
            growlight=growlight_controller,
            logger=mock_event_logger,
            startup_banner_s=0,
            vram_clear_delay_s=0,
            invert_delay_s=0,
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
            "reg",
            "co2",
            "soil",
            "debug",
        }
        assert set(MENUS) == expected


# ---------------------------------------------------------------------------
# TestOLEDDisplayLongPressActions
# ---------------------------------------------------------------------------


class TestOLEDDisplayLongPressActions:
    def test_long_press_temp_clears_history(self, oled_display):
        """Long press on temp menu should clear th_logger reading history."""
        oled_display._th_logger._readings_history = [(1, 20.0, 50.0)]
        oled_display.current_menu = MENUS.index("temp")
        oled_display.long_press_action()
        assert oled_display._th_logger._readings_history == []

    def test_long_press_humidity_clears_history(self, oled_display):
        """Long press on humidity menu should clear th_logger reading history."""
        oled_display._th_logger._readings_history = [(1, 20.0, 50.0)]
        oled_display.current_menu = MENUS.index("humidity")
        oled_display.long_press_action()
        assert oled_display._th_logger._readings_history == []

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
        th_logger,
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
            th_logger=th_logger,
            buffer_manager=buffer_manager,
            status_manager=mock_status_manager,
            reminder=mock_reminder,
            fans=[fan_controller],
            growlight=growlight_controller,
            sd_remount_cb=None,
            logger=mock_event_logger,
            startup_banner_s=0,
            vram_clear_delay_s=0,
            invert_delay_s=0,
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

    def test_render_errors_auto_disable_after_threshold(self, oled_display):
        """After max_render_errors consecutive I2C errors, the display self-disables."""
        oled_display._max_render_errors = 3
        oled_display._oled.fill = Mock(side_effect=OSError("ETIMEDOUT"))
        oled_display.render()
        oled_display.render()
        assert oled_display.display_on is True  # not yet at the threshold
        oled_display.render()
        assert oled_display.display_on is False  # third consecutive error disables

    def test_render_success_resets_error_streak(self, oled_display):
        """A clean render clears the consecutive-error count so it never disables."""
        oled_display._max_render_errors = 3
        oled_display._oled.fill = Mock(side_effect=OSError("ETIMEDOUT"))
        oled_display.render()  # count -> 1
        oled_display.render()  # count -> 2
        oled_display._oled.fill = Mock()  # bus recovered; renders cleanly
        oled_display.render()  # success -> streak reset
        assert oled_display._render_error_count == 0
        assert oled_display.display_on is True

    def test_auto_disabled_render_is_noop(self, oled_display):
        """Once auto-disabled, render() no longer touches the (possibly wedged) bus."""
        oled_display._max_render_errors = 1
        oled_display._oled.fill = Mock(side_effect=OSError("ETIMEDOUT"))
        oled_display.render()  # single error -> disabled
        assert oled_display.display_on is False
        oled_display._oled.show = Mock()
        oled_display.render()
        oled_display._oled.show.assert_not_called()

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
# TestOLEDDisplayAdditionalCoverage
# ---------------------------------------------------------------------------


class TestOLEDDisplayAdditionalCoverage:
    def _make_display(
        self,
        mock_i2c,
        time_provider,
        th_logger,
        buffer_manager,
        mock_status_manager,
        mock_reminder,
        fan_controller,
        growlight_controller,
        logger,
    ):
        return OLEDDisplay(
            i2c=mock_i2c,
            time_provider=time_provider,
            th_logger=th_logger,
            buffer_manager=buffer_manager,
            status_manager=mock_status_manager,
            reminder=mock_reminder,
            fans=[fan_controller],
            growlight=growlight_controller,
            sd_remount_cb=Mock(),
            start_time_ms=0,
            logger=logger,
            width=128,
            height=64,
            i2c_address=0x3C,
            refresh_interval_s=5,
            stats_window_s=3600,
            menu_timeout_s=30,
            startup_banner_s=0,
            vram_clear_delay_s=0,
            invert_delay_s=0,
        )

    def test_init_logs_with_print_when_logger_missing(
        self,
        mock_i2c,
        time_provider,
        th_logger,
        buffer_manager,
        mock_status_manager,
        mock_reminder,
        fan_controller,
        growlight_controller,
    ):
        with patch("builtins.print") as print_mock:
            display = self._make_display(
                mock_i2c,
                time_provider,
                th_logger,
                buffer_manager,
                mock_status_manager,
                mock_reminder,
                fan_controller,
                growlight_controller,
                logger=None,
            )
        assert display.display_on is True
        assert isinstance(print_mock, Mock)
        assert print_mock.call_count >= 1

    def test_next_menu_wakes_display_if_inactive(self, oled_display):
        oled_display._display_active = False
        oled_display._turn_on_display = Mock()
        oled_display.next_menu()
        oled_display._turn_on_display.assert_called_once()

    def test_long_press_wakes_display_if_inactive(self, oled_display):
        oled_display.current_menu = MENUS.index("system")
        oled_display._display_active = False
        oled_display._turn_on_display = Mock()
        oled_display.long_press_action()
        oled_display._turn_on_display.assert_called_once()

    def test_render_prints_error_when_no_logger(self, oled_display):
        oled_display._logger = None
        oled_display._oled.fill = Mock(side_effect=RuntimeError("fill failed"))
        with patch("builtins.print") as print_mock:
            oled_display.render()
        assert isinstance(print_mock, Mock)
        print_mock.assert_called_once()

    async def test_refresh_loop_turns_off_display_after_timeout(self, oled_display):
        oled_display._display_timeout_s = 1
        oled_display._last_activity_ms = 0
        oled_display._display_active = True
        oled_display._turn_off_display = Mock()

        async def _fake_sleep(s):
            raise RuntimeError("stop")

        with patch("lib.oled_display._ticks_ms", return_value=2000):
            with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
                with pytest.raises(RuntimeError, match="stop"):
                    await oled_display.refresh_loop()

        oled_display._turn_off_display.assert_called_once()

    def test_turn_off_display_warning_on_error(self, oled_display, mock_event_logger):
        oled_display._display_active = True
        oled_display._logger = mock_event_logger
        oled_display._oled.fill = Mock(side_effect=RuntimeError("off error"))
        oled_display._turn_off_display()
        mock_event_logger.warning.assert_called()

    def test_turn_on_display_warning_on_error(self, oled_display, mock_event_logger):
        oled_display._display_active = False
        oled_display._logger = mock_event_logger
        with patch("lib.oled_display._ticks_ms", side_effect=RuntimeError("tick error")):
            oled_display._turn_on_display()
        mock_event_logger.warning.assert_called()

    def test_clear_display_swallows_driver_errors(self, oled_display):
        oled_display._oled.fill = Mock(side_effect=RuntimeError("clear failed"))
        oled_display._clear_display()

    def test_header_and_row_noop_when_no_oled(self, oled_display):
        oled_display._oled = None
        oled_display._header("TITLE")
        oled_display._row("row", 1)

    def test_fmt_f_and_uptime_branches(self, oled_display):
        assert oled_display._fmt_f(12.34, 1) == "12.3"

        with patch("lib.oled_display._ticks_ms", return_value=2 * 3600 * 1000):
            oled_display._start_time_ms = 0
            assert "2h" in oled_display._uptime_str()

        with patch("lib.oled_display._ticks_ms", return_value=59 * 1000):
            oled_display._start_time_ms = 0
            assert oled_display._uptime_str().endswith("59s")

    def test_render_service_without_reminder(self, oled_display):
        oled_display._reminder = None
        oled_display._row = Mock()
        oled_display._render_service()
        oled_display._row.assert_any_call("No reminder", 0)

    def test_render_sd_success_path(self, oled_display, mock_status_manager):
        oled_display._status_manager = mock_status_manager
        oled_display._status_manager._sd_healthy = False
        oled_display._row = Mock()
        with patch("os.statvfs", return_value=(1024, 0, 2048, 1024), create=True):
            oled_display._render_sd()
        oled_display._row.assert_any_call("UNMOUNTED", 0)
        oled_display._row.assert_any_call("Used: 1MB", 1)
        oled_display._row.assert_any_call("Free: 1MB", 2)

    def test_render_alerts_branches_and_system_memory(self, oled_display):
        oled_display._row = Mock()

        status_with_alerts = {
            "errors": ["ERR1", "ERR2", "ERR3"],
            "warnings": ["WRN1", "WRN2", "WRN3"],
        }
        oled_display._status_manager.get_status = Mock(return_value=status_with_alerts)
        oled_display._render_alerts()

        oled_display._status_manager = None
        oled_display._render_alerts()
        oled_display._row.assert_any_call("No data", 0)

        with patch("lib.oled_display.gc.mem_alloc", return_value=25, create=True):
            with patch("lib.oled_display.gc.mem_free", return_value=75, create=True):
                oled_display._buffer_manager.get_metrics = Mock(return_value={"buffer_entries": 3})
                oled_display._time_provider.now_timestamp = Mock(return_value="2026-04-05 12:34:56")
                oled_display._render_system()

        ram_rows = [
            call.args[0] for call in oled_display._row.call_args_list if call.args and isinstance(call.args[0], str)
        ]
        assert any(r.startswith("RAM: 25.0%") for r in ram_rows)

    def test_render_relays_lists_channels_with_gpio(self, oled_display):
        """Each wired mains channel shows its GPIO so the page maps to REL_CON1."""
        cooler = Mock()
        cooler.is_on = Mock(return_value=True)
        oled_display._relays = [("Cool", 18, cooler), ("Spar", 21, None)]
        oled_display._fans = []
        oled_display._row = Mock()
        oled_display._render_relays()
        oled_display._row.assert_any_call("Cool GP18: ON", 0)
        oled_display._row.assert_any_call("Spar GP21: --", 1)

    def test_render_relays_marks_pwm_fans_as_pwm(self, oled_display):
        """A PCA9685 fan is not a mains socket and must never read as one.

        Regression guard: before the 3.5-D migration the case fan sat on a
        relay pin, and the page kept listing it unlabelled beside the real
        relays afterwards.
        """
        fan = Mock()
        fan.name = "case"
        fan.is_on = Mock(return_value=True)
        fan.duty_pct = 60
        oled_display._relays = []
        oled_display._fans = [fan]
        oled_display._row = Mock()
        oled_display._render_relays()
        oled_display._row.assert_any_call("case PWM: 60%", 0)

    def test_render_relays_stops_at_last_drawable_row(self, oled_display):
        """More channels than rows must not silently draw off-panel."""
        oled_display._relays = [(f"C{i}", i, None) for i in range(8)]
        oled_display._fans = []
        oled_display._row = Mock()
        oled_display._render_relays()
        assert oled_display._row.call_count == 5  # rows 0-4

    def test_render_system_row0_is_combined_date_time(self, oled_display):
        """Row 0 collapses YYYY-MM-DD HH:MM:SS into 16-char YYYY-MM-DD HH:MM."""
        oled_display._row = Mock()
        oled_display._time_provider.now_timestamp = Mock(return_value="2026-04-05 12:34:56")
        oled_display._buffer_manager.get_metrics = Mock(return_value={"buffer_entries": 0})
        oled_display._render_system()
        oled_display._row.assert_any_call("2026-04-05 12:34", 0)

    def test_render_system_row1_shows_build_version(self, oled_display):
        """Row 1 shows the build version (stamped by build_update_payload)."""
        oled_display._row = Mock()
        oled_display._time_provider.now_timestamp = Mock(return_value="2026-04-05 12:34:56")
        oled_display._buffer_manager.get_metrics = Mock(return_value={"buffer_entries": 0})
        with patch("lib.oled_display._BUILD_VERSION", "abc1234"):
            oled_display._render_system()
        oled_display._row.assert_any_call("Ver:abc1234", 1)

    def test_render_system_row1_shows_dev_when_unstamped(self, oled_display):
        """When lib/build_info is missing, _BUILD_VERSION falls back to 'dev'."""
        oled_display._row = Mock()
        oled_display._time_provider.now_timestamp = Mock(return_value="2026-04-05 12:34:56")
        oled_display._buffer_manager.get_metrics = Mock(return_value={"buffer_entries": 0})
        with patch("lib.oled_display._BUILD_VERSION", "dev"):
            oled_display._render_system()
        oled_display._row.assert_any_call("Ver:dev", 1)

    def test_render_system_short_timestamp_does_not_crash(self, oled_display):
        """Defensive: short/garbage timestamps from time_provider don't blow up."""
        oled_display._row = Mock()
        oled_display._time_provider.now_timestamp = Mock(return_value="?")
        oled_display._buffer_manager.get_metrics = Mock(return_value={"buffer_entries": 0})
        oled_display._render_system()
        oled_display._row.assert_any_call("?", 0)

    def test_render_soil_no_logger(self, oled_display):
        oled_display._row = Mock()
        oled_display._soil_logger = None
        oled_display._render_soil()
        oled_display._row.assert_any_call("Not wired", 0)

    def test_render_soil_waiting_for_reading(self, oled_display):
        oled_display._row = Mock()
        sl = Mock()
        sl.last_percent = None
        sl.last_raw = None
        sl.last_root_temp_c = None
        sl.warn_pct_below = 20
        oled_display._soil_logger = sl
        oled_display._render_soil()
        oled_display._row.assert_any_call("Reading...", 0)

    def test_render_soil_low_moisture(self, oled_display):
        oled_display._row = Mock()
        sl = Mock()
        sl.last_percent = 10
        sl.last_raw = 400
        sl.last_root_temp_c = 21.4
        sl.warn_pct_below = 20
        oled_display._soil_logger = sl
        oled_display._render_soil()
        oled_display._row.assert_any_call("Moist: 10%", 0)
        oled_display._row.assert_any_call("Raw:   400", 1)
        oled_display._row.assert_any_call("Root:  21.4C", 2)
        oled_display._row.assert_any_call("Warn<20%", 3)
        oled_display._row.assert_any_call("LOW!", 4)

    def test_render_soil_without_root_temperature(self, oled_display):
        """A probe that has not answered yet shows the placeholder, not a crash."""
        oled_display._row = Mock()
        sl = Mock()
        sl.last_percent = 55
        sl.last_raw = 1200
        sl.last_root_temp_c = None
        sl.warn_pct_below = 20
        oled_display._soil_logger = sl
        oled_display._render_soil()
        oled_display._row.assert_any_call("Root:  --C", 2)

    def test_render_co2_no_logger(self, oled_display):
        oled_display._row = Mock()
        oled_display._co2_logger = None
        oled_display._render_co2()
        oled_display._row.assert_any_call("Not wired", 0)

    def test_render_co2_with_reading(self, oled_display):
        oled_display._row = Mock()
        cl = Mock()
        cl.last_ppm = 850
        cl.is_override_active = Mock(return_value=False)
        oled_display._co2_logger = cl
        oled_display._render_co2()
        oled_display._row.assert_any_call("PPM: 850", 0)
        oled_display._row.assert_any_call("Vent: off", 1)

    def test_render_co2_override_active(self, oled_display):
        oled_display._row = Mock()
        cl = Mock()
        cl.last_ppm = 1500
        cl.is_override_active = Mock(return_value=True)
        oled_display._co2_logger = cl
        oled_display._render_co2()
        oled_display._row.assert_any_call("Vent: ON", 1)

    @staticmethod
    def _fake_reg_state(latched=False, emergency=False):
        return {
            "blend": 1.0,
            "global_severity": 12.0,
            "band": 2,
            "latched": latched,
            "emergency": emergency,
            "deviations": [64.0, 50.0, 48.0],
            "severities": [14.0, 0.0, 2.0],
            "commanded": {
                "heater": 0.0,
                "heater_follower": 0.0,
                "cooler": 60.0,
                "humidifier": 0.0,
                "exhaust": 40.0,
                "circulation": 30.0,
                "growlight": 80.0,
            },
        }

    def test_render_reg_not_active(self, oled_display):
        oled_display._row = Mock()
        oled_display._regulation = None
        oled_display._render_reg()
        oled_display._row.assert_any_call("Not active", 0)

    def test_render_reg_shows_band_deviations_and_commands(self, oled_display):
        oled_display._row = Mock()
        engine = Mock()
        engine.get_state = Mock(return_value=self._fake_reg_state())
        oled_display._regulation = engine
        oled_display._render_reg()
        oled_display._row.assert_any_call("Band 2 ok", 0)
        oled_display._row.assert_any_call("T64 H50 C48", 1)
        oled_display._row.assert_any_call("He0 Fo0 Cl60", 2)
        oled_display._row.assert_any_call("Hu0 Ex40 Ci30", 3)
        oled_display._row.assert_any_call("Gl80 b1.00", 4)

    def test_render_reg_latched_wins_over_emergency(self, oled_display):
        oled_display._row = Mock()
        engine = Mock()
        engine.get_state = Mock(return_value=self._fake_reg_state(latched=True, emergency=True))
        oled_display._regulation = engine
        oled_display._render_reg()
        oled_display._row.assert_any_call("Band 2 LATCHED", 0)

    def test_render_reg_emergency_label(self, oled_display):
        oled_display._row = Mock()
        engine = Mock()
        engine.get_state = Mock(return_value=self._fake_reg_state(emergency=True))
        oled_display._regulation = engine
        oled_display._render_reg()
        oled_display._row.assert_any_call("Band 2 EMERG", 0)

    def test_render_reg_state_error_is_non_fatal(self, oled_display):
        oled_display._row = Mock()
        engine = Mock()
        engine.get_state = Mock(side_effect=RuntimeError("boom"))
        oled_display._regulation = engine
        oled_display._render_reg()
        oled_display._row.assert_any_call("State error", 0)


# ---------------------------------------------------------------------------
# TestOLEDDebugMenu — debug actions sub-menu
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_heater():
    h = Mock()
    h.turn_on = Mock()
    h.turn_off = Mock()
    return h


@pytest.fixture
def debug_oled(
    mock_i2c,
    time_provider,
    th_logger,
    buffer_manager,
    mock_status_manager,
    mock_reminder,
    fan_controller,
    growlight_controller,
    mock_event_logger,
    mock_heater,
):
    """OLEDDisplay with heater + feedback callback wired, for debug-menu tests."""
    blink_calls = []

    def _blink():
        blink_calls.append(1)

    display = OLEDDisplay(
        i2c=mock_i2c,
        time_provider=time_provider,
        th_logger=th_logger,
        buffer_manager=buffer_manager,
        status_manager=mock_status_manager,
        reminder=mock_reminder,
        fans=[fan_controller],
        relays=[
            ("Cool", 18, Mock()),
            ("Lite", 20, growlight_controller),
            ("Spar", 21, None),  # wired channel with no controller
        ],
        growlight=growlight_controller,
        sd_remount_cb=Mock(),
        start_time_ms=0,
        logger=mock_event_logger,
        heater=mock_heater,
        feedback_blink_cb=_blink,
        event_log_path=None,
        debug_test_heater_s=0.01,
        debug_test_growlight_pulse_s=0.01,
        debug_test_growlight_dim_step_s=0.01,
        debug_test_relay_pulse_s=0.01,
        debug_status_show_ms=3000,
        startup_banner_s=0,
        vram_clear_delay_s=0,
        invert_delay_s=0,
    )
    display._blink_calls = blink_calls
    return display


class TestOLEDDebugMenu:
    def test_debug_menu_exists_in_menus(self):
        assert "debug" in MENUS

    def test_long_press_on_debug_menu_enters_sub_menu(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        assert debug_oled._debug_mode is True
        assert debug_oled._debug_action_idx == 0

    def test_short_press_inside_debug_cycles_actions(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()  # enter
        starting_menu = debug_oled.current_menu
        debug_oled.next_menu()
        assert debug_oled.current_menu == starting_menu  # top-level menu unchanged
        assert debug_oled._debug_action_idx == 1

    def test_short_press_inside_debug_wraps(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        total = len(debug_oled._debug_actions)
        for _ in range(total):
            debug_oled.next_menu()
        assert debug_oled._debug_action_idx == 0

    def test_wipe_logs_requires_confirm(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()  # enter
        debug_oled._debug_action_idx = next(
            i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "wipe_logs"
        )
        debug_oled._buffer_manager._buffers = {"x": ["a"]}
        debug_oled.long_press_action()  # first long-press: arms confirm
        assert debug_oled._debug_confirm_pending is True
        # Buffer must NOT have been wiped yet.
        assert debug_oled._buffer_manager._buffers == {"x": ["a"]}

    def test_short_press_cancels_pending_confirm(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_action_idx = next(
            i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "wipe_logs"
        )
        debug_oled.long_press_action()  # arm confirm
        debug_oled.next_menu()
        assert debug_oled._debug_confirm_pending is False

    async def test_wipe_logs_second_long_press_executes(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        idx = next(i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "wipe_logs")
        debug_oled._debug_action_idx = idx
        debug_oled._buffer_manager._buffers = {"x": ["a"]}
        debug_oled.long_press_action()  # arm
        debug_oled.long_press_action()  # execute
        await asyncio.sleep(0.05)
        assert debug_oled._buffer_manager._buffers == {}
        assert debug_oled._debug_running is False

    async def test_cycle_relays_pulses_relay_channels_only(self, debug_oled):
        # PWM fans are not relays: pulsing them here made the click count lie
        # about how many mains channels exist.
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_action_idx = next(
            i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "cycle_relays"
        )
        debug_oled._fans[0].turn_on = Mock()
        debug_oled._growlight.turn_on = Mock()
        debug_oled._growlight.turn_off = Mock()
        cooler = debug_oled._relays[0][2]
        debug_oled.long_press_action()  # execute (non-destructive)
        await asyncio.sleep(0.1)
        cooler.turn_on.assert_called_once()
        cooler.turn_off.assert_called_once()
        debug_oled._growlight.turn_on.assert_called_once()
        debug_oled._growlight.turn_off.assert_called_once()
        debug_oled._fans[0].turn_on.assert_not_called()  # PWM output, not a relay

    async def test_test_heater_pulses_heater(self, debug_oled, mock_heater):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_action_idx = next(
            i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "test_heater"
        )
        debug_oled.long_press_action()
        await asyncio.sleep(0.1)
        mock_heater.turn_on.assert_called_once()
        mock_heater.turn_off.assert_called_once()

    async def test_test_growlight_pulses_growlight(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_action_idx = next(
            i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "test_growlight"
        )
        debug_oled._growlight.turn_on = Mock()
        debug_oled._growlight.turn_off = Mock()
        debug_oled.long_press_action()
        await asyncio.sleep(0.1)
        debug_oled._growlight.turn_on.assert_called_once()
        debug_oled._growlight.turn_off.assert_called_once()

    async def test_dim_sweep_only_listed_when_dac_present(
        self,
        mock_i2c,
        time_provider,
        th_logger,
        buffer_manager,
        mock_status_manager,
        mock_reminder,
        fan_controller,
        growlight_controller,
        mock_event_logger,
        mock_heater,
    ):
        # growlight_controller fixture has dac=None → dim sweep should be absent.
        display = OLEDDisplay(
            i2c=mock_i2c,
            time_provider=time_provider,
            th_logger=th_logger,
            buffer_manager=buffer_manager,
            status_manager=mock_status_manager,
            reminder=mock_reminder,
            fans=[fan_controller],
            growlight=growlight_controller,
            heater=mock_heater,
            logger=mock_event_logger,
            startup_banner_s=0,
            vram_clear_delay_s=0,
            invert_delay_s=0,
        )
        action_ids = [a["id"] for a in display._debug_actions]
        assert "test_growlight_dim" not in action_ids

    async def test_dim_sweep_runs_when_dac_present(self, debug_oled):
        # Inject a fake DAC and use set_level to capture levels.
        called_levels = []
        debug_oled._growlight.dac = Mock()
        debug_oled._growlight.set_level = lambda lvl: called_levels.append(lvl)
        debug_oled._debug_actions = debug_oled._build_debug_actions()
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_action_idx = next(
            i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "test_growlight_dim"
        )
        debug_oled.long_press_action()
        await asyncio.sleep(0.1)
        # Sweep levels plus the final off call.
        assert 0 in called_levels and 100 in called_levels

    async def test_feedback_blink_called_after_success(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_action_idx = next(
            i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "cycle_relays"
        )
        debug_oled.long_press_action()
        await asyncio.sleep(0.1)
        assert len(debug_oled._blink_calls) == 1

    async def test_action_failure_sets_status_and_skips_blink(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        # Replace the cycle_relays handler with one that raises.
        for action in debug_oled._debug_actions:
            if action["id"] == "cycle_relays":

                async def _boom():
                    raise RuntimeError("nope")

                action["handler"] = _boom
                debug_oled._debug_action_idx = debug_oled._debug_actions.index(action)
                break
        debug_oled.long_press_action()
        await asyncio.sleep(0.05)
        assert debug_oled._debug_status.startswith("FAIL")
        assert len(debug_oled._blink_calls) == 0

    def test_long_press_ignored_while_action_running(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_running = True
        before = debug_oled._debug_confirm_pending
        debug_oled.long_press_action()
        assert debug_oled._debug_confirm_pending == before

    def test_short_press_ignored_while_action_running(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_running = True
        debug_oled._debug_action_idx = 0
        debug_oled.next_menu()
        assert debug_oled._debug_action_idx == 0

    def test_render_debug_entry_view(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled._row = Mock()
        debug_oled._render_debug()
        debug_oled._row.assert_any_call("Hold to enter", 0)

    def test_render_debug_sub_menu_shows_action(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled._debug_mode = True
        debug_oled._row = Mock()
        debug_oled._render_debug()
        first_label = debug_oled._debug_actions[0]["label"]
        debug_oled._row.assert_any_call(f"> {first_label}", 0)

    def test_render_debug_confirm_shows_prompt(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled._debug_mode = True
        debug_oled._debug_confirm_pending = True
        debug_oled._row = Mock()
        debug_oled._render_debug()
        debug_oled._row.assert_any_call("CONFIRM?", 2)

    async def test_menu_timeout_exits_debug_mode(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled._debug_mode = True
        debug_oled._menu_timeout_s = 1
        debug_oled._last_interaction_ms = 0

        async def _fake_sleep(s):
            raise RuntimeError("stop")

        with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
            with pytest.raises(RuntimeError, match="stop"):
                await debug_oled.refresh_loop()
        assert debug_oled._debug_mode is False
        assert debug_oled.current_menu == 0

    async def test_confirm_auto_cancels_after_timeout(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled._debug_mode = True
        debug_oled._debug_confirm_pending = True
        debug_oled._debug_confirm_timeout_ms = 1
        debug_oled._debug_confirm_ms = 0
        debug_oled._menu_timeout_s = 3600  # keep menu timeout out of the way
        debug_oled._last_interaction_ms = int(time.time() * 1000)

        async def _fake_sleep(s):
            raise RuntimeError("stop")

        import time as _time

        with patch("lib.oled_display._ticks_ms", return_value=int(_time.time() * 1000)):
            with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
                with pytest.raises(RuntimeError, match="stop"):
                    await debug_oled.refresh_loop()
        assert debug_oled._debug_confirm_pending is False


# ---------------------------------------------------------------------------
# TestTempHumidityLoggerStats  (unit tests for new stats methods)
# ---------------------------------------------------------------------------


class TestTempHumidityLoggerStats:
    def test_get_stats_empty_returns_current(self, th_logger):
        """get_stats() with no history should return last_temperature/humidity."""
        th_logger.last_temperature = 22.0
        th_logger.last_humidity = 60.0
        th_logger._readings_history.clear()
        stats = th_logger.get_stats(3600)
        assert stats["temp_now"] == 22.0
        assert stats["hum_now"] == 60.0
        assert stats["count"] == 0

    def test_get_stats_with_history(self, th_logger):
        """get_stats() should compute hi/lo/avg from history."""
        import time

        now_ms = int(time.time() * 1000)
        th_logger._readings_history = [
            (now_ms - 1000, 20.0, 50.0),
            (now_ms - 2000, 25.0, 70.0),
            (now_ms - 3000, 22.0, 60.0),
        ]
        th_logger.last_temperature = 22.0
        th_logger.last_humidity = 60.0
        stats = th_logger.get_stats(3600)
        assert stats["temp_hi"] == 25.0
        assert stats["temp_lo"] == 20.0
        assert abs(stats["temp_avg"] - 22.333) < 0.01
        assert stats["count"] == 3

    def test_get_stats_window_filters_old_entries(self, th_logger):
        """get_stats() should ignore readings outside the window."""
        import time

        now_ms = int(time.time() * 1000)
        th_logger._readings_history = [
            (now_ms - 7200 * 1000, 99.0, 99.0),  # 2 hours ago — outside 1h window
            (now_ms - 1000, 22.0, 60.0),  # 1 second ago — inside
        ]
        stats = th_logger.get_stats(3600)
        assert stats["count"] == 1
        assert stats["temp_hi"] == 22.0

    def test_clear_history_empties_list(self, th_logger):
        """clear_history() should empty _readings_history."""
        th_logger._readings_history = [(1, 20.0, 50.0), (2, 21.0, 55.0)]
        th_logger.clear_history()
        assert th_logger._readings_history == []


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


# ---------------------------------------------------------------------------
# TestDebugMenuLoggerSignature
# ---------------------------------------------------------------------------


class _StrictLogger:
    """EventLogger stand-in with the *real* method signatures.

    The shared ``mock_event_logger`` is a ``Mock`` whose ``info`` swallows any
    keyword argument, so it hid the on-device ``TypeError`` raised when the
    debug sub-menu called ``info(module, message, action=...)`` — ``info`` on
    the real EventLogger takes no ``**fields`` (only ``debug`` does). This
    stand-in reproduces that signature so the mismatch surfaces under pytest.
    """

    def info(self, module, message):
        pass

    def warning(self, module, message):
        pass

    def error(self, module, message):
        pass

    def debug(self, module, message, **fields):
        pass


class TestDebugMenuLoggerSignature:
    """Regression: debug sub-menu info() logs must not pass **fields."""

    def _enter_debug_menu(self, oled_display):
        oled_display.current_menu = MENUS.index("debug")
        oled_display._logger = _StrictLogger()

    def test_debug_confirm_arm_does_not_raise(self, oled_display):
        """Arming a destructive action's confirm must not raise TypeError."""
        self._enter_debug_menu(oled_display)
        oled_display.long_press_action()  # enter sub-menu
        oled_display.long_press_action()  # arm confirm on destructive action
        assert oled_display._debug_confirm_pending is True

    def test_debug_action_dispatch_does_not_raise(self, oled_display, monkeypatch):
        """Dispatching a confirmed action must not raise TypeError."""
        self._enter_debug_menu(oled_display)
        # Close the dispatched coroutine instead of scheduling it: the sync
        # test has no running loop, and we only assert that reaching the
        # dispatch log line doesn't raise — not that the action runs.
        import lib.oled_display as oled_mod

        monkeypatch.setattr(oled_mod.asyncio, "create_task", lambda coro: coro.close())
        oled_display.long_press_action()  # enter sub-menu
        oled_display.long_press_action()  # arm confirm
        oled_display.long_press_action()  # confirm → dispatch
        assert oled_display._debug_confirm_pending is False


# ---------------------------------------------------------------------------
# TestOLEDPhaseNotice — the acknowledge-required grow-phase notice
# ---------------------------------------------------------------------------


class TestOLEDPhaseNotice:
    SUMMARY = {
        "profile": "cannabis_bloom",
        "light_level_day": 100.0,
        "rh_ideal": 43.0,
        "humidifier_silenced": True,
    }

    @staticmethod
    def _wire(display):
        """Attach recording raise/ack sinks, as main.py attaches the real ones."""
        raises = []
        acks = []
        display._notice_raise_cb = lambda: raises.append(1)
        display._notice_ack_cb = acks.append
        return raises, acks

    def _raise(self, display, old="stretch", new="bloom", date=(2026, 10, 6), summary=None):
        display.show_phase_notice(old, new, date, self.SUMMARY if summary is None else summary)

    # -- raising -----------------------------------------------------------

    def test_notice_starts_empty(self, oled_display):
        assert oled_display.has_pending_notice() is False

    def test_raise_sets_the_slot(self, oled_display):
        self._raise(oled_display)
        assert oled_display.has_pending_notice() is True

    def test_raise_fires_the_side_effect_callback_exactly_once(self, oled_display):
        """One melody + one LED per raise — the notice does the waiting, not the buzzer."""
        raises, _ = self._wire(oled_display)
        self._raise(oled_display)
        assert raises == [1]

    def test_each_raise_fires_its_own_side_effect(self, oled_display):
        raises, _ = self._wire(oled_display)
        self._raise(oled_display, new="stretch")
        self._raise(oled_display, new="bloom")
        assert len(raises) == 2

    def test_a_failing_side_effect_still_leaves_the_notice_up(self, oled_display, mock_event_logger):
        """A dead buzzer must not cost the operator the notice itself."""

        def _boom():
            raise RuntimeError("no buzzer")

        oled_display._notice_raise_cb = _boom
        self._raise(oled_display)
        assert oled_display.has_pending_notice() is True
        assert mock_event_logger.warning.call_count == 1

    # -- rendering ---------------------------------------------------------

    def test_notice_renders_instead_of_the_current_menu(self, oled_display):
        oled_display.current_menu = MENUS.index("system")
        self._raise(oled_display)
        oled_display._row = Mock()
        oled_display._render_system = Mock()
        oled_display.render()
        oled_display._render_system.assert_not_called()
        oled_display._row.assert_any_call("stretch -> bloom", 0)

    def test_notice_lines_carry_what_actually_changed(self, oled_display):
        """RH target, light level and humidifier state — not just the phase name."""
        self._raise(oled_display)
        oled_display._row = Mock()
        oled_display.render()
        oled_display._row.assert_any_call("stretch -> bloom", 0)
        oled_display._row.assert_any_call("ab 2026-10-06", 1)
        oled_display._row.assert_any_call("rF 43% Licht100%", 2)
        oled_display._row.assert_any_call("Befeuchter AUS", 3)
        oled_display._row.assert_any_call("Taste=verstanden", 4)

    def test_notice_lines_fit_the_panel_width(self, oled_display):
        """16 characters is the whole line; _row() would silently truncate."""
        self._raise(oled_display)
        for line in oled_display._pending_notice[0]:
            assert len(line) <= 16, line

    def test_running_humidifier_is_said_so(self, oled_display):
        self._raise(oled_display, summary={"rh_ideal": 68.0, "light_level_day": 40.0})
        oled_display._row = Mock()
        oled_display.render()
        oled_display._row.assert_any_call("Befeuchter AN", 3)
        oled_display._row.assert_any_call("rF 68% Licht40%", 2)

    def test_missing_summary_values_render_as_dashes(self, oled_display):
        self._raise(oled_display, summary={})
        oled_display._row = Mock()
        oled_display.render()
        oled_display._row.assert_any_call("rF --% Licht--%", 2)

    def test_unknown_previous_phase_renders_a_placeholder(self, oled_display):
        """A boot-raised notice may not know what the phase was before."""
        self._raise(oled_display, old=None)
        oled_display._row = Mock()
        oled_display.render()
        oled_display._row.assert_any_call("? -> bloom", 0)

    def test_a_broken_date_does_not_break_the_notice(self, oled_display):
        self._raise(oled_display, date=None)
        oled_display._row = Mock()
        oled_display.render()
        oled_display._row.assert_any_call("ab sofort", 1)

    # -- acknowledging -----------------------------------------------------

    def test_short_press_acknowledges_instead_of_navigating(self, oled_display):
        oled_display.current_menu = 2
        self._raise(oled_display)
        oled_display.next_menu()
        assert oled_display.has_pending_notice() is False
        assert oled_display.current_menu == 2  # the press did NOT move the menu

    def test_only_the_next_press_navigates(self, oled_display):
        oled_display.current_menu = 2
        self._raise(oled_display)
        oled_display.next_menu()  # acknowledges
        oled_display.next_menu()  # navigates
        assert oled_display.current_menu == 3

    def test_acknowledge_hands_the_phase_to_the_callback(self, oled_display):
        _, acks = self._wire(oled_display)
        self._raise(oled_display)
        oled_display.next_menu()
        assert acks == ["bloom"]

    def test_acknowledge_fires_the_callback_exactly_once(self, oled_display):
        _, acks = self._wire(oled_display)
        self._raise(oled_display)
        oled_display.next_menu()
        oled_display.next_menu()
        oled_display.next_menu()
        assert acks == ["bloom"]

    def test_a_failing_ack_callback_still_clears_the_notice(self, oled_display, mock_event_logger):
        """A failed write must not trap the operator on the notice screen."""

        def _boom(_phase):
            raise OSError("read-only fs")

        oled_display._notice_ack_cb = _boom
        self._raise(oled_display)
        oled_display.next_menu()
        assert oled_display.has_pending_notice() is False
        assert mock_event_logger.warning.call_count == 1

    def test_long_press_acknowledges_and_runs_no_page_action(self, oled_display, mock_reminder):
        """The operator is looking at the notice, not at the page underneath it."""
        oled_display.current_menu = MENUS.index("service")
        self._raise(oled_display)
        oled_display.long_press_action()
        assert oled_display.has_pending_notice() is False
        mock_reminder.reset.assert_not_called()

    def test_long_press_after_acknowledge_runs_the_page_action(self, oled_display, mock_reminder):
        oled_display.current_menu = MENUS.index("service")
        self._raise(oled_display)
        oled_display.long_press_action()  # acknowledges
        oled_display.long_press_action()  # the page action, as usual
        mock_reminder.reset.assert_called_once()

    # -- timeouts and sleep ------------------------------------------------

    async def test_menu_timeout_does_not_clear_the_notice(self, oled_display):
        """A notice is not a menu page: only a press clears it."""
        self._raise(oled_display)
        oled_display.current_menu = 2
        oled_display._menu_timeout_s = 1
        oled_display._last_interaction_ms = 0

        async def _fake_sleep(_s):
            raise RuntimeError("stop")

        with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
            with pytest.raises(RuntimeError, match="stop"):
                await oled_display.refresh_loop()

        assert oled_display.has_pending_notice() is True

    async def test_the_refresh_loop_keeps_drawing_the_notice(self, oled_display):
        """It reappears by itself — no special-casing outside render()."""
        self._raise(oled_display)
        oled_display._render_notice = Mock()

        async def _fake_sleep(_s):
            raise RuntimeError("stop")

        with patch("lib.oled_display.asyncio.sleep", side_effect=_fake_sleep):
            with pytest.raises(RuntimeError, match="stop"):
                await oled_display.refresh_loop()

        assert oled_display._render_notice.called

    def test_raising_a_notice_does_not_wake_a_sleeping_display(self, oled_display):
        """The buzzer and the LED reach an absent operator; the panel need not burn."""
        oled_display._display_active = False
        self._raise(oled_display)
        assert oled_display._display_active is False
        assert oled_display.has_pending_notice() is True

    def test_the_wake_press_shows_the_notice_without_acknowledging_it(self, oled_display):
        """Nobody can confirm a screen they have not seen yet."""
        self._raise(oled_display)
        oled_display._display_active = False
        oled_display.next_menu()
        assert oled_display._display_active is True
        assert oled_display.has_pending_notice() is True

    def test_the_press_after_the_wake_acknowledges(self, oled_display):
        self._raise(oled_display)
        oled_display._display_active = False
        oled_display.next_menu()  # wakes, shows
        oled_display.next_menu()  # acknowledges
        assert oled_display.has_pending_notice() is False

    def test_a_dead_panel_can_still_be_acknowledged(self, oled_display):
        """With no display there is no wake, so the press must not be swallowed."""
        oled_display._oled = None
        oled_display._display_active = False
        self._raise(oled_display)
        oled_display.next_menu()
        assert oled_display.has_pending_notice() is False

    def test_notice_renders_on_wake_from_sleep(self, oled_display):
        self._raise(oled_display)
        oled_display._display_active = False
        oled_display._render_notice = Mock()
        oled_display.next_menu()  # wake press
        assert oled_display._render_notice.called


# ---------------------------------------------------------------------------
# TestOLEDRegPagePhase — the grow phase on the REGULATION page
# ---------------------------------------------------------------------------


class TestOLEDRegPagePhase:
    @staticmethod
    def _state(phase=None):
        return {
            "blend": 1.0,
            "global_severity": 12.0,
            "band": 2,
            "latched": False,
            "emergency": False,
            "deviations": [64.0, 50.0, 48.0],
            "severities": [14.0, 0.0, 2.0],
            "profile": "cannabis_bloom",
            "phase": phase,
            "commanded": {
                "heater": 0.0,
                "heater_follower": 0.0,
                "cooler": 60.0,
                "humidifier": 0.0,
                "exhaust": 40.0,
                "circulation": 30.0,
                "growlight": 80.0,
            },
        }

    def test_active_phase_rides_in_the_title(self, oled_display):
        """All five rows are spoken for, and the phase is what makes them readable."""
        oled_display._header = Mock()
        engine = Mock()
        engine.get_state = Mock(return_value=self._state("bloom"))
        oled_display._regulation = engine
        oled_display._render_reg()
        oled_display._header.assert_called_once_with("REG bloom")

    def test_no_schedule_keeps_the_plain_title(self, oled_display):
        """A mushroom build has no phase; the page must not print 'REG None'."""
        oled_display._header = Mock()
        engine = Mock()
        engine.get_state = Mock(return_value=self._state(None))
        oled_display._regulation = engine
        oled_display._render_reg()
        oled_display._header.assert_called_once_with("REGULATION")

    def test_title_stays_inside_the_panel_width(self, oled_display):
        oled_display._header = Mock()
        engine = Mock()
        engine.get_state = Mock(return_value=self._state("a-very-long-phase-name"))
        oled_display._regulation = engine
        oled_display._render_reg()
        title = oled_display._header.call_args[0][0]
        assert len(title) <= 16

    def test_state_error_still_titles_the_page(self, oled_display):
        oled_display._header = Mock()
        oled_display._row = Mock()
        engine = Mock()
        engine.get_state = Mock(side_effect=RuntimeError("boom"))
        oled_display._regulation = engine
        oled_display._render_reg()
        oled_display._header.assert_called_once_with("REGULATION")
        oled_display._row.assert_any_call("State error", 0)
