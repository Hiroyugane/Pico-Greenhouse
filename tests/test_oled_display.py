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
        sl.warn_pct_below = 20
        oled_display._soil_logger = sl
        oled_display._render_soil()
        oled_display._row.assert_any_call("Reading...", 0)

    def test_render_soil_low_moisture(self, oled_display):
        oled_display._row = Mock()
        sl = Mock()
        sl.last_percent = 10
        sl.last_raw = 800
        sl.warn_pct_below = 20
        oled_display._soil_logger = sl
        oled_display._render_soil()
        oled_display._row.assert_any_call("Moist: 10%", 0)
        oled_display._row.assert_any_call("Raw:   800", 1)
        oled_display._row.assert_any_call("LOW!", 3)

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

    async def test_cycle_relays_pulses_each_fan_and_growlight(self, debug_oled):
        debug_oled.current_menu = MENUS.index("debug")
        debug_oled.long_press_action()
        debug_oled._debug_action_idx = next(
            i for i, a in enumerate(debug_oled._debug_actions) if a["id"] == "cycle_relays"
        )
        debug_oled._fans[0].turn_on = Mock()
        debug_oled._fans[0].turn_off = Mock()
        debug_oled._growlight.turn_on = Mock()
        debug_oled._growlight.turn_off = Mock()
        debug_oled.long_press_action()  # execute (non-destructive)
        await asyncio.sleep(0.1)
        debug_oled._fans[0].turn_on.assert_called_once()
        debug_oled._fans[0].turn_off.assert_called_once()
        debug_oled._growlight.turn_on.assert_called_once()
        debug_oled._growlight.turn_off.assert_called_once()

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
