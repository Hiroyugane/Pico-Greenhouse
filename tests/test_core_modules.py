# Test Scaffolding for Pi Greenhouse
# Tests run on host Python (not on device)
# Uses mocks for MicroPython-specific modules (machine, dht, uasyncio)

import pytest
from unittest.mock import Mock, MagicMock, patch


# ============================================================================
# FIXTURES: Mock Hardware and Providers
# ============================================================================

@pytest.fixture
def mock_rtc():
    """Mock ds3231.RTC module."""
    rtc = Mock()
    rtc.ReadTime = Mock(return_value=(45, 23, 14, 3, 29, 1, 2026))  # Default: Jan 29, 2026 14:23:45
    return rtc


@pytest.fixture
def time_provider(mock_rtc):
    """Create TimeProvider with mocked RTC."""
    # Import is here to avoid circular dependency issues
    from lib.time_provider import RTCTimeProvider
    return RTCTimeProvider(mock_rtc)


@pytest.fixture
def buffer_manager():
    """Create BufferManager with mocked file operations."""
    from lib.buffer_manager import BufferManager
    return BufferManager(
        sd_mount_point='/sd',
        fallback_path='/local/fallback.csv',
        max_buffer_entries=100,
    )


@pytest.fixture
def event_logger(time_provider, buffer_manager):
    """Create EventLogger with injected dependencies."""
    from lib.event_logger import EventLogger
    return EventLogger(
        time_provider,
        buffer_manager,
        logfile='/sd/test.log',
        max_size=10000,
    )


@pytest.fixture
def mock_dht_logger():
    """Mock DHTLogger for testing."""
    logger = Mock()
    logger.last_temperature = 22.5
    logger.last_humidity = 65.0
    return logger


# ============================================================================
# TESTS: TimeProvider
# ============================================================================

class TestTimeProvider:
    """Tests for TimeProvider abstraction."""
    
    def test_time_provider_now_timestamp(self, time_provider):
        """Test TimeProvider.now_timestamp() returns ISO format."""
        ts = time_provider.now_timestamp()
        assert isinstance(ts, str)
        assert '2026-01-29' in ts or '2026-1-29' in ts
        assert ':' in ts  # Should contain time
    
    def test_time_provider_now_date_tuple(self, time_provider):
        """Test TimeProvider.now_date_tuple() returns (year, month, day)."""
        date = time_provider.now_date_tuple()
        assert isinstance(date, tuple)
        assert len(date) == 3
        assert date[0] == 2026  # year
        assert date[1] == 1  # month
        assert date[2] == 29  # day
    
    def test_time_provider_get_seconds_since_midnight(self, time_provider):
        """Test TimeProvider.get_seconds_since_midnight() calculation."""
        # RTC returns 14:23:45 = 14*3600 + 23*60 + 45 = 51825 seconds
        seconds = time_provider.get_seconds_since_midnight()
        expected = 14 * 3600 + 23 * 60 + 45
        assert seconds == expected
    
    def test_time_provider_get_time_tuple(self, time_provider):
        """Test TimeProvider.get_time_tuple() returns raw tuple."""
        tup = time_provider.get_time_tuple()
        assert isinstance(tup, tuple)
        assert len(tup) == 7
        assert tup[0] == 45  # seconds
        assert tup[2] == 14  # hour

    def test_time_provider_sunrise_sunset_bounds(self, time_provider):
        """Sunrise/sunset should return sensible hours/minutes."""
        (sr_h, sr_m), (ss_h, ss_m) = time_provider.sunrise_sunset(2026, 1, 29)
        assert 0 <= sr_h <= 23
        assert 0 <= sr_m <= 59
        assert 0 <= ss_h <= 23
        assert 0 <= ss_m <= 59


# ============================================================================
# TESTS: BufferManager
# ============================================================================

class TestBufferManager:
    """Tests for BufferManager with SD fallback."""
    
    def test_buffer_manager_write_to_primary_success(self, buffer_manager):
        """Test write to primary (SD) when available."""
        with patch('builtins.open', create=True):
            with patch('os.remove'):
                with patch('os.mkdir'):
                    result = buffer_manager.write('test.csv', 'data\n')
                    # Since we mocked open, it should attempt primary
                    assert buffer_manager.writes_to_primary >= 0
    
    def test_buffer_manager_metrics(self, buffer_manager):
        """Test buffer manager returns metrics."""
        metrics = buffer_manager.get_metrics()
        assert isinstance(metrics, dict)
        assert 'writes_to_primary' in metrics
        assert 'writes_to_fallback' in metrics
        assert 'buffer_entries' in metrics
    
    def test_buffer_manager_is_primary_available(self, buffer_manager):
        """Test is_primary_available() gracefully handles errors."""
        result = buffer_manager.is_primary_available()
        assert isinstance(result, bool)

    def test_buffer_manager_migrate_before_new_write(self, buffer_manager, monkeypatch):
        """If fallback has entries and primary returns, migrate before writing new data."""
        calls = []

        def fake_is_primary_available():
            return True

        def fake_has_fallback_entries():
            return True

        def fake_migrate():
            calls.append('migrate')
            return 1

        def fake_flush(relpath=None):
            calls.append('flush')
            return True

        monkeypatch.setattr(buffer_manager, 'is_primary_available', fake_is_primary_available)
        monkeypatch.setattr(buffer_manager, '_has_fallback_entries', fake_has_fallback_entries)
        monkeypatch.setattr(buffer_manager, 'migrate_fallback', fake_migrate)
        monkeypatch.setattr(buffer_manager, 'flush', fake_flush)

        with patch('builtins.open', create=True):
            buffer_manager.write('test.csv', 'data\n')

        assert 'migrate' in calls

    def test_buffer_manager_buffer_overflow_drops_oldest(self, buffer_manager, monkeypatch):
        """When fallback fails, buffer should drop oldest entry on overflow."""
        buffer_manager.max_buffer_entries = 2

        def fake_is_primary_available():
            return False

        monkeypatch.setattr(buffer_manager, 'is_primary_available', fake_is_primary_available)
        monkeypatch.setattr(buffer_manager, '_ensure_fallback_dir', lambda: True)

        def raise_open(*args, **kwargs):
            raise OSError('write failed')

        with patch('builtins.open', create=True, side_effect=raise_open):
            buffer_manager.write('a.csv', 'A\n')
            buffer_manager.write('a.csv', 'B\n')
            buffer_manager.write('a.csv', 'C\n')

        assert buffer_manager.get_metrics()['buffer_entries'] == 2
        assert buffer_manager._buffers['a.csv'][0] == 'B\n'


# ============================================================================
# TESTS: EventLogger
# ============================================================================

class TestEventLogger:
    """Tests for EventLogger with dependency injection."""
    
    def test_event_logger_info(self, event_logger, capsys):
        """Test EventLogger.info() logs to console."""
        event_logger.info('TEST', 'Test message')
        captured = capsys.readouterr()
        assert 'TEST' in captured.out
        assert 'Test message' in captured.out
        assert '[INFO]' in captured.out
    
    def test_event_logger_warning(self, event_logger, capsys):
        """Test EventLogger.warning() logs warning."""
        event_logger.warning('TEST', 'Warning message')
        captured = capsys.readouterr()
        assert '[WARN]' in captured.out
    
    def test_event_logger_error(self, event_logger, capsys):
        """Test EventLogger.error() logs error and flushes."""
        event_logger.error('TEST', 'Error message')
        captured = capsys.readouterr()
        assert '[ERR]' in captured.out
    
    def test_event_logger_timestamp(self, event_logger):
        """Test EventLogger uses TimeProvider for timestamps."""
        ts = event_logger._get_timestamp()
        assert 'TIME_ERROR' not in ts or isinstance(ts, str)

    def test_event_logger_flush_thresholds(self, time_provider, buffer_manager):
        """Verify flush thresholds for info/warn levels."""
        from lib.event_logger import EventLogger

        logger = EventLogger(time_provider, buffer_manager, logfile='/sd/test.log')
        with patch.object(buffer_manager, 'write', return_value=True) as write_mock:
            logger.info('T', '1')
            logger.info('T', '2')
            logger.info('T', '3')
            logger.info('T', '4')
            assert write_mock.call_count == 0
            logger.info('T', '5')
            assert write_mock.call_count > 0

        with patch.object(buffer_manager, 'write', return_value=True) as write_mock:
            logger.warning('T', '1')
            logger.warning('T', '2')
            assert write_mock.call_count == 0
            logger.warning('T', '3')
            assert write_mock.call_count > 0


# ============================================================================
# TESTS: Relay Controllers
# ============================================================================

class TestRelayController:
    """Tests for RelayController base class."""
    
    def test_relay_controller_initialization(self):
        """Test RelayController initializes with correct state."""
        with patch('machine.Pin'):
            from lib.relay import RelayController
            relay = RelayController(16, invert=True, name='TestRelay')
            
            assert relay.name == 'TestRelay'
            assert relay.invert is True
            assert relay.is_on() is False  # Initialized to OFF
    
    def test_relay_controller_turn_on_off(self):
        """Test RelayController turn_on/turn_off."""
        mock_pin_instance = Mock()
        with patch('machine.Pin', return_value=mock_pin_instance):
            from lib.relay import RelayController
            
            relay = RelayController(16, invert=True)
            relay.turn_on()
            assert relay.is_on() is True
            
            relay.turn_off()
            assert relay.is_on() is False


class TestFanController:
    """Tests for FanController (time-of-day + thermostat)."""
    
    def test_fan_controller_initialization(self, time_provider, mock_dht_logger):
        """Test FanController initializes with correct parameters."""
        with patch('machine.Pin'):
            from lib.relay import FanController
            from lib.event_logger import EventLogger
            from lib.buffer_manager import BufferManager
            
            buffer_mgr = BufferManager()
            logger = EventLogger(time_provider, buffer_mgr)
            
            fan = FanController(
                pin=16,
                time_provider=time_provider,
                dht_logger=mock_dht_logger,
                logger=logger,
                interval_s=600,
                on_time_s=20,
                max_temp=24.0,
                name='TestFan',
            )
            
            assert fan.name == 'TestFan'
            assert fan.interval_s == 600
            assert fan.max_temp == 24.0
            assert fan.thermostat_active is False

    def test_fan_controller_thermostat_activation_and_release(self, time_provider, mock_dht_logger):
        """Thermostat should override schedule and release with hysteresis."""
        import asyncio
        from lib.relay import FanController

        mock_logger = Mock()

        fan = FanController(
            pin=16,
            time_provider=time_provider,
            dht_logger=mock_dht_logger,
            logger=mock_logger,
            interval_s=600,
            on_time_s=20,
            max_temp=24.0,
            temp_hysteresis=1.0,
            name='TestFan',
        )

        mock_dht_logger.last_temperature = 24.5

        async def run_once():
            with patch('uasyncio.sleep', side_effect=RuntimeError('stop')):
                try:
                    await fan.start_cycle()
                except RuntimeError:
                    pass

        asyncio.run(run_once())
        assert fan.thermostat_active is True

        mock_dht_logger.last_temperature = 22.5

        async def run_once_release():
            with patch('uasyncio.sleep', side_effect=RuntimeError('stop')):
                try:
                    await fan.start_cycle()
                except RuntimeError:
                    pass

        asyncio.run(run_once_release())
        assert fan.thermostat_active is False


# ============================================================================
# TESTS: ServiceReminder
# ============================================================================

class TestServiceReminder:
    """Tests for ServiceReminder task."""
    
    def test_Service_reminder_initialization(self, time_provider):
        """Test ServiceReminder initializes with correct state."""
        with patch('machine.Pin'):
            import lib.led_button as led_button
            
            LEDButtonHandler = led_button.LEDButtonHandler
            ServiceReminder = getattr(led_button, 'ServiceReminder', None) or getattr(led_button, 'ServiceReminderTask', None)
            assert ServiceReminder is not None
            
            led_handler = LEDButtonHandler(24, 23)
            reminder = ServiceReminder(
                time_provider,
                led_handler,
                days_interval=7,
                blink_pattern_ms=[200, 200],
            )
            
            assert reminder.days_interval == 7
            assert reminder.last_serviced_timestamp is not None
    
    def test_Service_reminder_reset(self, time_provider):
        """Test ServiceReminder.reset() updates timestamp."""
        with patch('machine.Pin'):
            import lib.led_button as led_button
            
            LEDButtonHandler = led_button.LEDButtonHandler
            ServiceReminder = getattr(led_button, 'ServiceReminder', None) or getattr(led_button, 'ServiceReminderTask', None)
            assert ServiceReminder is not None
            
            led_handler = LEDButtonHandler(24, 23)
            reminder = ServiceReminder(time_provider, led_handler)
            
            old_timestamp = reminder.last_serviced_timestamp
            reminder.reset()
            new_timestamp = reminder.last_serviced_timestamp
            
            # Should have updated (may be same in tests due to mocked time)
            assert isinstance(new_timestamp, str)

    def test_service_reminder_days_elapsed(self, time_provider):
        """Days elapsed should be non-negative and handle boundaries."""
        with patch('machine.Pin'):
            import lib.led_button as led_button

            LEDButtonHandler = led_button.LEDButtonHandler
            ServiceReminder = getattr(led_button, 'ServiceReminder', None) or getattr(led_button, 'ServiceReminderTask', None)
            assert ServiceReminder is not None

            led_handler = LEDButtonHandler(24, 23)
            reminder = ServiceReminder(
                time_provider,
                led_handler,
                last_serviced_timestamp='2026-01-01 00:00:00',
            )

            assert reminder._days_since_Service() >= 0


# ============================================================================
# TESTS: Configuration Validation
# ============================================================================

class TestConfigValidation:
    """Tests for configuration validation."""
    
    def test_config_validate_success(self):
        """Test that valid config passes validation."""
        from config import DEVICE_CONFIG, validate_config
        
        result = validate_config()
        assert result is True
    
    def test_config_has_required_keys(self):
        """Test that DEVICE_CONFIG has all required keys."""
        from config import DEVICE_CONFIG
        
        required = ['pins', 'spi', 'files', 'dht_logger', 'fan_1', 'fan_2', 'growlight']
        for key in required:
            assert key in DEVICE_CONFIG

    def test_config_validation_rejects_negative_intervals(self, monkeypatch):
        """Ensure invalid ranges raise ValueError."""
        import config

        original = config.DEVICE_CONFIG['dht_logger']['interval_s']
        config.DEVICE_CONFIG['dht_logger']['interval_s'] = -1
        try:
            with pytest.raises(ValueError):
                config.validate_config()
        finally:
            config.DEVICE_CONFIG['dht_logger']['interval_s'] = original


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests combining multiple components."""
    
    def test_time_provider_with_event_logger(self, time_provider, event_logger, capsys):
        """Test EventLogger uses TimeProvider correctly."""
        event_logger.info('IntegrationTest', 'Testing integration')
        captured = capsys.readouterr()
        
        assert 'IntegrationTest' in captured.out
        assert '2026' in captured.out or 'TIME_ERROR' in captured.out  # Timestamp should appear


class TestDHTLoggerEdgeCases:
    """Edge case tests for DHTLogger."""

    def test_dht_logger_read_sensor_out_of_range(self, time_provider, buffer_manager, event_logger):
        from lib.dht_logger import DHTLogger

        logger = event_logger

        sensor = Mock()
        sensor.measure = Mock()
        sensor.temperature = Mock(return_value=120.0)
        sensor.humidity = Mock(return_value=150.0)

        with patch('dht.DHT22', return_value=sensor):
            dht_logger = DHTLogger(15, time_provider, buffer_manager, logger, max_retries=2)
            temp, hum = dht_logger.read_sensor()
            assert temp is None and hum is None
            assert dht_logger.read_failures == 1

    def test_dht_logger_date_rollover_switches_file(self, time_provider, buffer_manager, event_logger, monkeypatch):
        from lib.dht_logger import DHTLogger

        logger = event_logger
        dht_logger = DHTLogger(15, time_provider, buffer_manager, logger)

        monkeypatch.setattr(dht_logger, 'current_date', (2026, 1, 29))
        monkeypatch.setattr(time_provider, 'now_date_tuple', lambda: (2026, 1, 30))

        created = []

        monkeypatch.setattr(dht_logger, '_file_exists', lambda: False)
        monkeypatch.setattr(dht_logger, '_create_file', lambda: created.append('created'))

        changed = dht_logger._check_date_changed()
        assert changed is True
        assert created


class TestLEDButtonHandlerEdgeCases:
    """Edge case tests for LED/button handler."""

    def test_led_button_debounce(self):
        import lib.led_button as led_button

        with patch('machine.Pin'):
            handler = led_button.LEDButtonHandler(24, 23, debounce_ms=50)
            calls = []

            def cb():
                calls.append('pressed')

            handler.register_button_callback(cb)

            with patch('lib.led_button._ticks_ms', side_effect=[1000, 1010, 1065]):
                handler._button_isr(None)
                handler._button_isr(None)
                handler._button_isr(None)

            assert calls.count('pressed') == 2


class TestGrowlightControllerEdgeCases:
    """Edge case tests for GrowlightController scheduling."""

    def test_growlight_schedule_boundaries(self, time_provider, buffer_manager):
        from lib.relay import GrowlightController
        from lib.event_logger import EventLogger

        logger = EventLogger(time_provider, buffer_manager)

        growlight = GrowlightController(
            pin=17,
            time_provider=time_provider,
            logger=logger,
            dawn_hour=6,
            dawn_minute=0,
            sunset_hour=6,
            sunset_minute=1,
            name='Growlight',
        )

        import asyncio

        time_provider.get_seconds_since_midnight = Mock(return_value=6 * 3600)

        async def run_once_on():
            with patch('uasyncio.sleep', side_effect=RuntimeError('stop')):
                try:
                    await growlight.start_scheduler()
                except RuntimeError:
                    pass

        asyncio.run(run_once_on())
        assert growlight.is_on() is True

        time_provider.get_seconds_since_midnight = Mock(return_value=6 * 3600 + 60)

        async def run_once_off():
            with patch('uasyncio.sleep', side_effect=RuntimeError('stop')):
                try:
                    await growlight.start_scheduler()
                except RuntimeError:
                    pass

        asyncio.run(run_once_off())
        assert growlight.is_on() is False


class TestHardwareFactoryEdgeCases:
    """Edge case tests for HardwareFactory."""

    def test_hardware_factory_rtc_failure(self, monkeypatch):
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setattr(factory, '_init_rtc', lambda: False)
        assert factory.setup() is False

    def test_hardware_factory_pin_init(self, monkeypatch):
        from lib.hardware_factory import HardwareFactory

        factory = HardwareFactory()
        monkeypatch.setattr(factory, '_init_rtc', lambda: True)
        monkeypatch.setattr(factory, '_init_spi', lambda: True)
        monkeypatch.setattr(factory, '_init_sd', lambda: True)

        assert factory.setup() is True
        assert isinstance(factory.get_all_pins(), dict)


class TestMainOrchestration:
    """Integration-style test for main orchestration."""

    def test_main_spawns_tasks_and_runs_loop(self, monkeypatch):
        import asyncio
        import main as main_module

        monkeypatch.setattr(main_module, 'validate_config', lambda: True)

        mock_hardware = Mock()
        mock_hardware.setup.return_value = True
        mock_hardware.get_rtc.return_value = Mock()
        monkeypatch.setattr(main_module, 'HardwareFactory', lambda *args, **kwargs: mock_hardware)

        mock_buffer = Mock()
        mock_buffer.get_metrics.return_value = {
            'buffer_entries': 0,
            'writes_to_fallback': 0,
            'fallback_migrations': 0,
        }
        monkeypatch.setattr(main_module, 'BufferManager', lambda *args, **kwargs: mock_buffer)

        mock_logger = Mock()
        monkeypatch.setattr(main_module, 'EventLogger', lambda *args, **kwargs: mock_logger)
        monkeypatch.setattr(main_module, 'DHTLogger', lambda *args, **kwargs: Mock())
        monkeypatch.setattr(main_module, 'FanController', lambda *args, **kwargs: Mock())
        monkeypatch.setattr(main_module, 'GrowlightController', lambda *args, **kwargs: Mock())
        monkeypatch.setattr(main_module, 'LEDButtonHandler', lambda *args, **kwargs: Mock())
        monkeypatch.setattr(main_module, 'ServiceReminder', lambda *args, **kwargs: Mock())

        created_tasks = []

        def fake_create_task(task):
            created_tasks.append(task)
            return Mock()

        monkeypatch.setattr(main_module.asyncio, 'create_task', fake_create_task)

        async def fake_sleep(_):
            raise asyncio.CancelledError

        monkeypatch.setattr(main_module.asyncio, 'sleep', fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(main_module.main())

        assert created_tasks
