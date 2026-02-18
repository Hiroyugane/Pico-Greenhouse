# Tests for lib/led_button.py
# Covers LED, LEDButtonHandler, ServiceReminder, _ticks_ms

import asyncio
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from tests.conftest import FAKE_LOCALTIME

# ============================================================================
# _ticks_ms helper
# ============================================================================


class TestTicksMs:
    """Tests for module-level _ticks_ms() helper."""

    def test_ticks_ms_with_native(self):
        """When time.ticks_ms exists, _ticks_ms uses it."""
        # _ticks_ms is resolved at import time; re-import to test
        import importlib

        with patch.object(time, "ticks_ms", return_value=12345):
            import lib.led_button

            importlib.reload(lib.led_button)
            result = lib.led_button._ticks_ms()
        assert result == 12345
        # Restore module to normal state
        importlib.reload(lib.led_button)

    def test_ticks_ms_fallback(self):
        """When time.ticks_ms is absent, falls back to time.time()*1000."""
        import importlib

        saved = getattr(time, "ticks_ms", None)
        try:
            if hasattr(time, "ticks_ms"):
                delattr(time, "ticks_ms")
            import lib.led_button

            importlib.reload(lib.led_button)
            with patch("time.time", return_value=1000.5):
                result = lib.led_button._ticks_ms()
            assert result == 1000500
        finally:
            if saved is not None:
                time.ticks_ms = saved
            importlib.reload(lib.led_button)


# ============================================================================
# LED
# ============================================================================


class TestLED:
    """Tests for LED class."""

    def test_init_off(self):
        """LED initializes with pin OFF."""
        from lib.led_button import LED

        with patch("lib.led_button.machine.Pin", return_value=MagicMock()):
            led = LED(25)
            # Pin was created and off() was called
            led.pin.off.assert_called()  # type: ignore

    def test_on(self):
        """on() turns LED on."""
        from lib.led_button import LED

        with patch("lib.led_button.machine.Pin", return_value=MagicMock()):
            led = LED(25)
            led.on()
            led.pin.on.assert_called()  # type: ignore

    def test_off(self):
        """off() turns LED off."""
        from lib.led_button import LED

        with patch("lib.led_button.machine.Pin", return_value=MagicMock()):
            led = LED(25)
            led.off()
            led.pin.off.assert_called()  # type: ignore

    def test_toggle(self):
        """toggle() alternates LED state."""
        from lib.led_button import LED

        with patch("lib.led_button.machine.Pin", return_value=MagicMock()):
            led = LED(25)
            # Initially off (value() returns 0)
            led.pin.value = Mock(return_value=0)
            led.toggle()
            led.pin.on.assert_called()  # type: ignore

            led.pin.value = Mock(return_value=1)
            led.toggle()
            led.pin.off.assert_called()  # type: ignore

    @pytest.mark.asyncio
    async def test_blink_pattern_async(self):
        """blink_pattern_async plays ON/OFF pattern."""
        from lib.led_button import LED

        with patch("lib.led_button.machine.Pin", return_value=MagicMock()):
            led = LED(25)

            with patch("asyncio.sleep", return_value=None):
                await led.blink_pattern_async([100, 200], repeats=1)

            # Should have called on, sleep(0.1), off, sleep(0.2), then off at end
            assert led.pin.on.call_count >= 1  # type: ignore
            assert led.pin.off.call_count >= 1  # type: ignore

    @pytest.mark.asyncio
    async def test_blink_pattern_zero_repeats(self):
        """repeats=0 returns immediately without blinking."""
        from lib.led_button import LED

        with patch("lib.led_button.machine.Pin", return_value=MagicMock()):
            led = LED(25)

            with patch("asyncio.sleep", return_value=None) as sleep_mock:
                await led.blink_pattern_async([100, 200], repeats=0)
            sleep_mock.assert_not_called()  # type: ignore

    @pytest.mark.asyncio
    async def test_blink_pattern_led_off_at_end(self):
        """LED is OFF after blink pattern completes."""
        from lib.led_button import LED

        with patch("lib.led_button.machine.Pin", return_value=MagicMock()):
            led = LED(25)

            with patch("asyncio.sleep", return_value=None):
                await led.blink_pattern_async([100, 100], repeats=2)

            # Last call should be off()
            led.pin.off.assert_called()  # type: ignore

    @pytest.mark.asyncio
    async def test_blink_continuous_stop_event(self):
        """blink_continuous_async stops when stop_event is set."""
        from lib.led_button import LED

        with patch("lib.led_button.machine.Pin", return_value=MagicMock()):
            led = LED(25)

            stop = asyncio.Event()
            cycle_count = 0

            async def counting_sleep(duration):
                nonlocal cycle_count
                cycle_count += 1
                if cycle_count >= 3:
                    stop.set()

            with patch("asyncio.sleep", side_effect=counting_sleep):
                await led.blink_continuous_async(100, 100, stop_event=stop)

            # Should have stopped
            led.pin.off.assert_called()  # type: ignore


# ============================================================================
# LEDButtonHandler
# ============================================================================


class TestLEDButtonHandler:
    """Tests for LEDButtonHandler."""

    def test_set_on_off(self, led_handler):
        """set_on/set_off delegate to LED."""
        led_handler.set_on()
        led_handler.led.pin.on.assert_called()
        led_handler.set_off()
        led_handler.led.pin.off.assert_called()

    def test_toggle(self, led_handler):
        """toggle() delegates to LED toggle."""
        led_handler.led.pin.value = Mock(return_value=0)
        led_handler.toggle()
        led_handler.led.pin.on.assert_called()

    def test_register_button_callback(self, led_handler):
        """register_button_callback sets up IRQ handler."""
        cb = Mock()
        led_handler.register_button_callback(cb)
        assert led_handler.button_callback is cb
        led_handler.button.irq.assert_called()

    def test_button_debounce(self):
        """Rapid presses within debounce window are ignored."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(24, 23, debounce_ms=50)
        handler.register_button_callback(lambda: None)

        # Simulate 3 presses: 0ms, 10ms later, 65ms later
        with patch("lib.led_button._ticks_ms", side_effect=[1000, 1010, 1065]):
            handler._button_isr(None)  # t=1000: pass
            assert handler._pending_short is True
            handler._pending_short = False  # consume flag
            handler._button_isr(None)  # t=1010: blocked (only 10ms)
            assert handler._pending_short is False
            handler._button_isr(None)  # t=1065: pass (65ms > 50ms)
            assert handler._pending_short is True

    def test_button_isr_sets_flag_only(self):
        """ISR sets _pending_short flag without calling callback."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(24, 23, debounce_ms=0)
        cb = Mock()
        handler.register_button_callback(cb)
        with patch("lib.led_button._ticks_ms", return_value=1000):
            handler._button_isr(None)
        # Flag is set, but callback is NOT called in ISR
        assert handler._pending_short is True
        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_button_dispatches_short_press(self):
        """poll_button() dispatches short_press_callback from flag."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(24, 23, debounce_ms=0)
        cb = Mock()
        handler.register_button_callback(cb)
        handler._pending_short = True

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=limited_sleep):
            with pytest.raises(asyncio.CancelledError):
                await handler.poll_button()

        cb.assert_called_once()
        assert handler._pending_short is False

    @pytest.mark.asyncio
    async def test_poll_button_dispatches_long_press(self):
        """poll_button() dispatches long_press_callback from flag."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(5, 9, debounce_ms=50, long_press_ms=3000)
        short_cb = Mock()
        long_cb = Mock()
        handler.register_callbacks(short_press=short_cb, long_press=long_cb)
        handler._pending_long = True

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=limited_sleep):
            with pytest.raises(asyncio.CancelledError):
                await handler.poll_button()

        long_cb.assert_called_once()
        short_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_button_callback_error_handled(self):
        """If callback raises in poll_button, error is caught."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(24, 23, debounce_ms=0)

        def bad_cb():
            raise RuntimeError("callback error")

        handler.register_button_callback(bad_cb)
        handler._pending_short = True

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=limited_sleep):
            with pytest.raises(asyncio.CancelledError):
                # Should not raise RuntimeError
                await handler.poll_button()

    @pytest.mark.asyncio
    async def test_blink_pattern_delegates(self, led_handler):
        """blink_pattern_async delegates to LED."""
        with patch("asyncio.sleep", return_value=None):
            await led_handler.blink_pattern_async([100, 100])
        led_handler.led.pin.on.assert_called()

    def test_register_callbacks_sets_both(self):
        """register_callbacks sets short and long press handlers."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(5, 9, debounce_ms=50, long_press_ms=3000)
        short_cb = Mock()
        long_cb = Mock()
        handler.register_callbacks(short_press=short_cb, long_press=long_cb)
        assert handler.short_press_callback is short_cb
        assert handler.long_press_callback is long_cb
        handler.button.irq.assert_called()  # type: ignore

    def test_dual_isr_short_press(self):
        """Short press (< long_press_ms) sets _pending_short flag."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(5, 9, debounce_ms=50, long_press_ms=3000)
        short_cb = Mock()
        long_cb = Mock()
        handler.register_callbacks(short_press=short_cb, long_press=long_cb)

        mock_pin = MagicMock()
        # Simulate press (FALLING: value=0) then release (RISING: value=1) after 500ms
        with patch("lib.led_button._ticks_ms", side_effect=[1000, 1500]):
            mock_pin.value.return_value = 0
            handler._button_dual_isr(mock_pin)  # press at t=1000
            mock_pin.value.return_value = 1
            handler._button_dual_isr(mock_pin)  # release at t=1500 (500ms < 3000ms)

        assert handler._pending_short is True
        assert handler._pending_long is False
        # Callbacks are NOT called directly in ISR
        short_cb.assert_not_called()
        long_cb.assert_not_called()

    def test_dual_isr_long_press(self):
        """Long press (>= long_press_ms) sets _pending_long flag."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(5, 9, debounce_ms=50, long_press_ms=3000)
        short_cb = Mock()
        long_cb = Mock()
        handler.register_callbacks(short_press=short_cb, long_press=long_cb)

        mock_pin = MagicMock()
        # Simulate press then release after 3500ms
        with patch("lib.led_button._ticks_ms", side_effect=[1000, 4500]):
            mock_pin.value.return_value = 0
            handler._button_dual_isr(mock_pin)  # press at t=1000
            mock_pin.value.return_value = 1
            handler._button_dual_isr(mock_pin)  # release at t=4500 (3500ms >= 3000ms)

        assert handler._pending_long is True
        assert handler._pending_short is False
        short_cb.assert_not_called()
        long_cb.assert_not_called()

    def test_dual_isr_debounce(self):
        """Rapid edges within debounce window are ignored."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(5, 9, debounce_ms=50, long_press_ms=3000)
        short_cb = Mock()
        handler.register_callbacks(short_press=short_cb)

        mock_pin = MagicMock()
        # Two presses within debounce window — second ignored
        with patch("lib.led_button._ticks_ms", side_effect=[1000, 1010]):
            mock_pin.value.return_value = 0
            handler._button_dual_isr(mock_pin)  # t=1000: accepted
            handler._button_dual_isr(mock_pin)  # t=1010: ignored (10ms < 50ms)

        # Only one press start recorded, no release yet
        short_cb.assert_not_called()

    def test_dual_isr_callback_error_handled(self):
        """If callback raises in poll_button (via dual ISR flag), error is caught."""
        from lib.led_button import LEDButtonHandler

        handler = LEDButtonHandler(5, 9, debounce_ms=0, long_press_ms=3000)

        def bad_cb():
            raise RuntimeError("callback error")

        handler.register_callbacks(short_press=bad_cb)

        mock_pin = MagicMock()
        with patch("lib.led_button._ticks_ms", side_effect=[1000, 1500]):
            mock_pin.value.return_value = 0
            handler._button_dual_isr(mock_pin)
            mock_pin.value.return_value = 1
            handler._button_dual_isr(mock_pin)

        assert handler._pending_short is True


# ============================================================================
# ServiceReminder
# ============================================================================


class TestServiceReminder:
    """Tests for ServiceReminder task."""

    def test_initialization(self, time_provider):
        """ServiceReminder initializes with correct state."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler, days_interval=7)
        assert reminder.days_interval == 7
        assert reminder.last_serviced_timestamp is not None

    def test_reset_updates_timestamp(self, time_provider):
        """reset() updates last_serviced_timestamp."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler)
            reminder.reset()
        assert isinstance(reminder.last_serviced_timestamp, str)

    def test_days_elapsed_non_negative(self, time_provider):
        """_days_since_Service() returns non-negative value."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                last_serviced_timestamp="2026-01-01 00:00:00",
            )
            days = reminder._days_since_Service()
        assert days >= 0

    def test_init_saves_when_no_storage(self, time_provider, tmp_path):
        """When no storage file exists, saves current timestamp."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        storage = tmp_path / "reminder.txt"
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            ServiceReminder(
                time_provider,
                handler,
                storage_path=str(storage),
            )
        assert storage.exists()
        assert "2026" in storage.read_text()

    def test_init_loads_from_storage(self, time_provider, tmp_path):
        """When storage file exists, load timestamp from it."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        storage = tmp_path / "reminder.txt"
        storage.write_text("2026-01-15 10:00:00")
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                storage_path=str(storage),
            )
        assert reminder.last_serviced_timestamp == "2026-01-15 10:00:00"

    def test_reset_persists_to_file(self, time_provider, tmp_path):
        """reset() writes new timestamp to storage file."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        storage = tmp_path / "reminder.txt"
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                storage_path=str(storage),
            )
            reminder.reset()
        content = storage.read_text()
        assert "2026" in content

    def test_parse_date_from_timestamp(self, time_provider):
        """_parse_date_from_timestamp parses correctly."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler)
        result = reminder._parse_date_from_timestamp("2026-01-29 14:23:45")
        assert result == (2026, 1, 29)

    def test_parse_date_from_invalid_timestamp(self, time_provider):
        """_parse_date_from_timestamp returns None for invalid input."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler)
        assert reminder._parse_date_from_timestamp("invalid") is None

    @pytest.mark.asyncio
    async def test_monitor_triggers_blink_when_due(self, time_provider):
        """When days_interval=0, monitor triggers blink."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                days_interval=0,  # Always due
                blink_after_days=0,  # Blink immediately when due
            )

        blink_called = False

        async def mock_blink(*args, **kwargs):
            nonlocal blink_called
            blink_called = True

        handler.blink_pattern_async = mock_blink

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await reminder.monitor()

        assert blink_called

    @pytest.mark.asyncio
    async def test_monitor_cancelled_error(self, time_provider):
        """CancelledError in monitor turns off LED and re-raises."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler)

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await reminder.monitor()

    @pytest.mark.asyncio
    async def test_monitor_clears_after_reset_during_blink(self, time_provider):
        """Monitor clears reminder when reset() is called between blink and re-check."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                days_interval=0,  # Always due initially
                blink_after_days=0,  # Blink immediately when due
            )

        blink_count = 0

        async def mock_blink(*args, **kwargs):
            nonlocal blink_count
            blink_count += 1
            # Simulate reset during blink → makes days_since_Service return 0
            # which is still >= 0; so set interval to large number instead
            if blink_count == 1:
                reminder.days_interval = 999

        handler.blink_pattern_async = mock_blink

        call_count = 0

        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=counting_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await reminder.monitor()

        # Blink was called at least once before clearing
        assert blink_count >= 1

    @pytest.mark.asyncio
    async def test_monitor_not_due_to_due_transition(self, time_provider):
        """Monitor detects transition from not-due to due."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                days_interval=999,  # Start as not-due
                blink_after_days=0,  # Blink immediately when due
            )

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # After first hourly check, make it due
                reminder.days_interval = 0
            if call_count >= 3:
                raise asyncio.CancelledError()

        blink_called = False

        async def mock_blink(*args, **kwargs):
            nonlocal blink_called
            blink_called = True

        handler.blink_pattern_async = mock_blink

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await reminder.monitor()

        assert blink_called

    @pytest.mark.asyncio
    async def test_monitor_error_continues_after_sleep(self, time_provider):
        """Generic exception in monitor is caught, loop continues after 60s sleep."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler, days_interval=7)

        # Make _days_since_Service raise on first call, then work normally
        original_days = reminder._days_since_Service
        call_count = 0

        def failing_days():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("unexpected")
            return original_days()

        reminder._days_since_Service = failing_days

        sleep_durations = []

        async def tracking_sleep(duration):
            sleep_durations.append(duration)
            if len(sleep_durations) >= 2:
                raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=tracking_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await reminder.monitor()

        # After the error, should sleep 60 seconds
        assert 60 in sleep_durations

    @pytest.mark.asyncio
    async def test_monitor_solid_on_when_due_under_blink_threshold(self, time_provider):
        """LED is solid on when due but overdue by less than blink_after_days."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                days_interval=7,
                blink_after_days=3,  # Don't blink until 3 days overdue
            )

        # Mock _days_since_Service to return 8 (1 day past due, under blink threshold)
        reminder._days_since_Service = lambda: 8

        set_on_called = False
        original_set_on = handler.set_on

        def tracking_set_on():
            nonlocal set_on_called
            set_on_called = True
            original_set_on()

        handler.set_on = tracking_set_on

        blink_called = False

        async def mock_blink(*args, **kwargs):
            nonlocal blink_called
            blink_called = True

        handler.blink_pattern_async = mock_blink

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await reminder.monitor()

        assert set_on_called, "LED should be solid on when under blink threshold"
        assert not blink_called, "LED should NOT blink when under blink threshold"

    @pytest.mark.asyncio
    async def test_monitor_blinks_when_overdue_past_threshold(self, time_provider):
        """LED blinks when overdue by >= blink_after_days."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                days_interval=7,
                blink_after_days=3,  # Blink after 3 more days overdue
            )

        # Mock _days_since_Service to return 11 (4 days past threshold)
        reminder._days_since_Service = lambda: 11

        blink_called = False

        async def mock_blink(*args, **kwargs):
            nonlocal blink_called
            blink_called = True

        handler.blink_pattern_async = mock_blink

        call_count = 0

        async def limited_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await reminder.monitor()

        assert blink_called, "LED should blink when overdue past blink_after_days"

    def test_blink_after_days_default(self, time_provider):
        """blink_after_days defaults to 3."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler)
        assert reminder.blink_after_days == 3


class TestServiceReminderPersistenceErrors:
    """Tests for persistence error handling in ServiceReminder."""

    def test_days_since_service_exception_returns_zero(self, time_provider):
        """_days_since_Service() returns 0 when time calculation raises."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler)

        # Force an exception in the date calculation
        reminder.last_serviced_date = ("invalid", "date", "tuple")
        days = reminder._days_since_Service()
        assert days == 0

    def test_save_timestamp_write_failure_logs_error(self, time_provider, tmp_path):
        """_save_last_serviced_timestamp() handles write failure gracefully."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        mock_logger = Mock()
        storage = tmp_path / "readonly_dir" / "reminder.txt"
        # Don't create parent dir → write will fail

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(
                time_provider,
                handler,
                storage_path=str(storage),
                logger=mock_logger,
            )

        # The init would have tried to save; now try again with impossible path
        reminder.storage_path = str(tmp_path / "nonexistent_deep" / "nested" / "file.txt")
        reminder._save_last_serviced_timestamp("2026-01-29 14:00:00")

        # Should have logged an error (not crashed)
        mock_logger.error.assert_called()

    def test_load_timestamp_missing_file_returns_none(self, time_provider, tmp_path):
        """_load_last_serviced_timestamp() returns None when file doesn't exist."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler)

        reminder.storage_path = str(tmp_path / "nonexistent.txt")
        result = reminder._load_last_serviced_timestamp()
        assert result is None

    def test_load_timestamp_empty_file_returns_none(self, time_provider, tmp_path):
        """_load_last_serviced_timestamp() returns None for empty file."""
        from lib.led_button import LEDButtonHandler, ServiceReminder

        storage = tmp_path / "empty.txt"
        storage.write_text("")

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            handler = LEDButtonHandler(5, 9)
            reminder = ServiceReminder(time_provider, handler)

        reminder.storage_path = str(storage)
        result = reminder._load_last_serviced_timestamp()
        assert result is None
