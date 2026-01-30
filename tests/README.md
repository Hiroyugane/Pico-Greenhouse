# Pi Greenhouse Testing Guide

## Overview

This directory contains unit and integration tests for the Pi Greenhouse system.

Tests run on **host Python** (not on the Pico device) using mocks for MicroPython-specific modules like `machine`, `dht`, and `uasyncio`.

## Running Tests

### Prerequisites

```bash
pip install pytest pytest-asyncio pytest-mock
```

### Run All Tests

```bash
pytest tests/
```

### Run Specific Test File

```bash
pytest tests/test_core_modules.py -v
```

### Run Specific Test Class

```bash
pytest tests/test_core_modules.py::TestTimeProvider -v
```

### Run Specific Test

```bash
pytest tests/test_core_modules.py::TestTimeProvider::test_time_provider_now_timestamp -v
```

### Run with Coverage Report

```bash
pip install pytest-cov
pytest tests/ --cov=lib --cov=config --cov-report=html
```

## Test Structure

### conftest.py

Global pytest configuration mocks MicroPython modules:

```python
sys.modules['machine'] = MagicMock()  # GPIO pins
sys.modules['dht'] = MagicMock()      # DHT22 sensor
sys.modules['uasyncio'] = asyncio     # Use standard asyncio instead
sys.modules['lib.ds3231'] = MagicMock()
sys.modules['lib.sdcard'] = MagicMock()
```

### test_core_modules.py

Core unit tests for each module:

- **TestTimeProvider**: Tests `lib/time_provider.py` TimeProvider and RTCTimeProvider
  - `test_time_provider_now_timestamp`: Timestamp formatting
  - `test_time_provider_now_date_tuple`: Date extraction
  - `test_time_provider_get_seconds_since_midnight`: Time calculations

- **TestBufferManager**: Tests `lib/buffer_manager.py` SD/fallback resilience
  - `test_buffer_manager_write_to_primary_success`: Primary write path
  - `test_buffer_manager_write_to_fallback`: Fallback when SD unavailable
  - `test_buffer_manager_metrics`: Metrics collection
  - `test_buffer_manager_is_primary_available`: Availability checking
  - `test_buffer_manager_migrate_fallback`: Migration when SD reconnects

- **TestEventLogger**: Tests `lib/event_logger.py` with dependency injection
  - `test_event_logger_info`: Info level logging
  - `test_event_logger_warning`: Warning level logging
  - `test_event_logger_error`: Error level + flush
  - `test_event_logger_timestamp`: TimeProvider integration
  - `test_event_logger_flush`: Buffer flushing to file

- **TestRelayController**: Tests `lib/relay.py` base relay controller
  - `test_relay_controller_initialization`: Initialization state
  - `test_relay_controller_turn_on_off`: On/off switching
  - `test_relay_controller_toggle`: Toggle state

- **TestFanController**: Tests fan-specific dual-mode control
  - `test_fan_controller_initialization`: Parameter validation
  - `test_fan_controller_schedule_mode`: Time-based scheduling
  - `test_fan_controller_thermostat_mode`: Temperature-based control

- **TestGrowlightController**: Tests growlight scheduling
  - `test_growlight_controller_initialization`: Schedule setup
  - `test_growlight_controller_dawn_dusk`: On/off times

- **TestLEDButtonHandler**: Tests `lib/led_button.py` LED control
  - `test_led_handler_on_off`: LED on/off
  - `test_led_handler_toggle`: LED toggle

- **TestCleaningReminder**: Tests cleaning reminder task
  - `test_cleaning_reminder_initialization`: State setup
  - `test_cleaning_reminder_reset`: Timer reset on button press
  - `test_cleaning_reminder_days_calculation`: Elapsed days tracking

- **TestConfigValidation**: Tests `config.py` validation
  - `test_config_validate_success`: Config is valid
  - `test_config_has_required_keys`: All required keys present
  - `test_config_pin_values_valid`: Pin numbers in valid range

- **TestIntegration**: Integration tests
  - `test_time_provider_with_event_logger`: TimeProvider + EventLogger together
  - `test_hardware_factory_integration`: Full hardware initialization sequence
  - `test_dependency_injection_chain`: Component DI chain

## Mocking Strategy

### Test Fixtures

Each test uses fixtures that provide mocked dependencies:

```python
@pytest.fixture
def mock_rtc():
    """Mock ds3231.RTC module."""
    rtc = Mock()
    rtc.ReadTime = Mock(return_value=(45, 23, 14, 3, 29, 1, 2026))
    return rtc

@pytest.fixture
def time_provider(mock_rtc):
    """Create TimeProvider with mocked RTC."""
    from lib.time_provider import RTCTimeProvider
    return RTCTimeProvider(mock_rtc)

@pytest.fixture
def buffer_manager():
    """Create BufferManager with mocked SD card."""
    from lib.buffer_manager import BufferManager
    return BufferManager(
        sd_mount_point='/sd',
        fallback_path='/local/fallback.csv',
        max_buffer_entries=1000,
        flush_threshold=50,
    )
```

### Patching in Tests

Individual tests use `@patch()` to control GPIO and hardware:

```python
def test_relay_controller_initialization(self):
    with patch('machine.Pin'):
        from lib.relay import RelayController
        relay = RelayController(16, invert=True)
        assert relay.is_on() is False
```

## Adding New Tests

1. Add test class to `test_core_modules.py`
2. Use existing fixtures or create new ones in `conftest.py`
3. Use `@patch()` for hardware interactions
4. Follow naming: `test_<component>_<scenario>`

Example:

```python
class TestMyNewFeature:
    """Tests for my new feature."""
    
    def test_feature_does_thing(self, time_provider, buffer_manager):
        """Test that feature does the thing."""
        from lib.mymodule import MyFeature
        
        feature = MyFeature(time_provider, buffer_manager)
        result = feature.do_thing()
        assert result is True
```

## Device Testing

These unit tests do NOT run on the Pico device. For device testing:

1. **Manual Testing**: Flash `main.py` via Thonny and check logs via serial console
2. **Log Verification**: Check `/sd/system.log` for initialization messages
3. **Integration Testing**: Run system and verify CSV output to `/sd/dht_log_YYYY-MM-DD.csv`
4. **Hardware Verification**: Test relays, LEDs, buttons physically
5. **Fallback Testing**: Remove SD card during operation and verify `/local/fallback.csv` captures data

## Expected Initialization Sequence (from main.py)

1. Validate configuration (config.py)
2. Initialize hardware via HardwareFactory (RTC, SPI, SD, GPIO)
3. Create TimeProvider (wraps RTC for consistent timestamps)
4. Create BufferManager (SD + fallback resilience)
5. Create EventLogger (system event tracking with persistence)
6. Create DHTLogger (temperature/humidity sensor)
7. Create relay controllers: FanController × 2, GrowlightController
8. Create LED/button handler and CleaningReminder task
9. Spawn all async tasks (fan cycles, growlight scheduler, sensor logging, reminder monitoring)
10. Enter main event loop with periodic health checks

**Note**: Recommended improvement is to move EventLogger creation before step 2 (hardware init) so hardware failures can be logged persistently. See REFACTORING.md for details.

## Continuous Integration (CI)

To run tests in CI/CD pipeline:

```bash
pytest tests/ --cov=lib --cov=config --cov-report=xml -v
```

CI should run on every commit to catch regressions.

## Debugging Tests

### Print Debug Output

```bash
pytest tests/ -v -s  # -s shows print() statements
```

### Run Single Test with Debugger

```bash
pytest tests/test_core_modules.py::TestTimeProvider::test_time_provider_now_timestamp -v -s --pdb
```

### Check Mock Calls

```python
def test_mock_was_called(self, mock_rtc):
    """Verify mock was called."""
    from lib.time_provider import RTCTimeProvider
    provider = RTCTimeProvider(mock_rtc)
    provider.now_timestamp()
    
    mock_rtc.ReadTime.assert_called()  # Verify ReadTime was called
    print(mock_rtc.ReadTime.call_count)  # How many times?
    print(mock_rtc.ReadTime.call_args)   # With what arguments?
```

## Known Limitations

1. **Async Tests**: CleaningReminder, DHTLogger, and FanController have async methods not fully tested (would need pytest-asyncio fixtures)
2. **File I/O**: File operations are partially mocked; real SD behavior may differ
3. **MicroPython Specifics**: Some MicroPython-only features (e.g., memory constraints, interrupt handlers) aren't tested
4. **GPIO Interrupts**: Button interrupt handlers are mocked; real debouncing untested
5. **Hardware Timing**: Relay timing and temperature thresholds use mock data, not real sensor values

## Future Improvements

- [ ] Add pytest-asyncio fixtures for async task testing (`log_loop()`, `start_cycle()`, `monitor()`)
- [ ] Create integration test fixtures that simulate real SD card behavior
- [ ] Add device-side tests (run on Pico via Thonny with serial capture)
- [ ] Add performance benchmarks (startup time, memory usage)
- [ ] Test memory usage under sustained load (24+ hour runs)
- [ ] Add end-to-end tests combining multiple components
- [ ] Stress test relay cycling with high-frequency switching
