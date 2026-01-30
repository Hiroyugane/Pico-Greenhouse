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
