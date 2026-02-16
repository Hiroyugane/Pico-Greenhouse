# pytest Configuration and Fixtures
# conftest.py — Unified MagicMock approach for MicroPython hardware
#
# Patches sys.modules for machine, dht, micropython, uasyncio ONCE at session start.
# All hardware (Pin, SPI, I2C, DHT22, RTC) is MagicMock-based with realistic attributes.
# Provides reusable fixtures for all lib/ modules under test.

import sys
import os
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Path setup: ensure project root is importable
# ---------------------------------------------------------------------------
_project_root = str(Path(__file__).resolve().parents[1])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ---------------------------------------------------------------------------
# MicroPython module stubs — applied BEFORE any lib/ imports
# ---------------------------------------------------------------------------

# --- machine module ---
_machine_mock = MagicMock()
_machine_mock.Pin.OUT = 1
_machine_mock.Pin.IN = 0
_machine_mock.Pin.PULL_UP = 1
_machine_mock.Pin.IRQ_FALLING = 2
_machine_mock.Pin.IRQ_RISING = 1

# Make Pin() return a fresh mock each time, with value tracking
def _make_pin(*args, **kwargs):
    pin = MagicMock()
    pin._current_value = 0
    pin._call_history = []  # Track (method, value) calls for assertions
    def _value_fn(v=None):
        if v is None:
            return pin._current_value
        pin._current_value = v
        pin._call_history.append(('value', v))
    pin.value = MagicMock(side_effect=_value_fn)
    pin.on = MagicMock(side_effect=lambda: (_value_fn(1), pin._call_history.append(('on', 1)))[0])
    pin.off = MagicMock(side_effect=lambda: (_value_fn(0), pin._call_history.append(('off', 0)))[0])
    pin.irq = MagicMock()
    return pin

_machine_mock.Pin = MagicMock(side_effect=_make_pin)
# Preserve class-level constants on the callable mock
_machine_mock.Pin.OUT = 1
_machine_mock.Pin.IN = 0
_machine_mock.Pin.PULL_UP = 1
_machine_mock.Pin.IRQ_FALLING = 2
_machine_mock.Pin.IRQ_RISING = 1

_machine_mock.SPI = MagicMock()
_machine_mock.I2C = MagicMock()
_machine_mock.RTC = MagicMock

# --- dht module ---
_dht_mock = MagicMock()

# --- micropython module ---
_micropython_mock = MagicMock()
_micropython_mock.const = lambda x: x

# --- uasyncio → standard asyncio ---
sys.modules['machine'] = _machine_mock
sys.modules['dht'] = _dht_mock
sys.modules['micropython'] = _micropython_mock
sys.modules['uasyncio'] = asyncio

# Patch time.sleep_ms which only exists in MicroPython
import time as _time
if not hasattr(_time, 'sleep_ms'):
    _time.sleep_ms = lambda ms: _time.sleep(ms / 1000.0)
if not hasattr(_time, 'ticks_ms'):
    _time.ticks_ms = lambda: int(_time.time() * 1000)

# ---------------------------------------------------------------------------
# Pytest configuration
# ---------------------------------------------------------------------------
import pytest

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: integration tests")


# ---------------------------------------------------------------------------
# Fixtures: Time / RTC
# ---------------------------------------------------------------------------

# Reference time: 2026-01-29 14:23:45 (Wednesday, day 29 of year)
FAKE_LOCALTIME = (2026, 1, 29, 14, 23, 45, 3, 29, -1)


@pytest.fixture
def mock_rtc():
    """Mock ds3231.RTC with configurable ReadTime() return."""
    rtc = Mock()
    # Default: Jan 29, 2026 14:23:45 Wed
    # RTC format: (sec, min, hour, wday, day, mon, year)
    rtc.ReadTime = Mock(return_value=(45, 23, 14, 3, 29, 1, 2026))
    return rtc


@pytest.fixture
def time_provider(mock_rtc):
    """RTCTimeProvider with time.localtime patched to known value."""
    with patch('time.localtime', return_value=FAKE_LOCALTIME):
        from lib.time_provider import RTCTimeProvider
        provider = RTCTimeProvider(mock_rtc)
        yield provider


@pytest.fixture
def base_time_provider():
    """Base TimeProvider (no RTC) with time.localtime patched."""
    with patch('time.localtime', return_value=FAKE_LOCALTIME):
        from lib.time_provider import TimeProvider
        yield TimeProvider()


# ---------------------------------------------------------------------------
# Fixtures: Storage (real filesystem via tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture
def buffer_manager(tmp_path):
    """BufferManager using tmp_path for isolated real filesystem I/O."""
    sd_dir = tmp_path / "sd"
    sd_dir.mkdir()
    fallback_dir = tmp_path / "local"
    fallback_dir.mkdir()
    fallback_file = fallback_dir / "fallback.csv"

    from lib.buffer_manager import BufferManager
    return BufferManager(
        sd_mount_point=str(sd_dir),
        fallback_path=str(fallback_file),
        max_buffer_entries=100,
    )


# ---------------------------------------------------------------------------
# Fixtures: Logging
# ---------------------------------------------------------------------------

@pytest.fixture
def event_logger(time_provider, buffer_manager):
    """EventLogger wired to real TimeProvider and BufferManager."""
    with patch('time.localtime', return_value=FAKE_LOCALTIME):
        from lib.event_logger import EventLogger
        return EventLogger(
            time_provider,
            buffer_manager,
            logfile='/sd/test.log',
            max_size=10000,
        )


@pytest.fixture
def mock_event_logger():
    """Lightweight mock EventLogger for tests that don't need real logging."""
    logger = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.flush = Mock()
    logger.check_size = Mock()
    return logger


# ---------------------------------------------------------------------------
# Fixtures: DHT sensor
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_dht_sensor():
    """Configurable DHT22 mock with measure/temperature/humidity."""
    sensor = Mock()
    sensor.measure = Mock()
    sensor.temperature = Mock(return_value=22.5)
    sensor.humidity = Mock(return_value=65.0)
    return sensor


@pytest.fixture
def mock_dht_logger():
    """Mock DHTLogger for relay controller tests."""
    logger = Mock()
    logger.last_temperature = 22.5
    logger.last_humidity = 65.0
    return logger


@pytest.fixture
def dht_logger(time_provider, buffer_manager, mock_event_logger, mock_dht_sensor):
    """Real DHTLogger with mocked sensor for integration-style tests."""
    with patch('time.localtime', return_value=FAKE_LOCALTIME):
        with patch('dht.DHT22', return_value=mock_dht_sensor):
            from lib.dht_logger import DHTLogger
            return DHTLogger(
                15, time_provider, buffer_manager, mock_event_logger,
                interval=60,
            )


# ---------------------------------------------------------------------------
# Fixtures: LED / Button
# ---------------------------------------------------------------------------

@pytest.fixture
def led_handler():
    """LEDButtonHandler with mocked machine.Pin."""
    from lib.led_button import LEDButtonHandler
    return LEDButtonHandler(24, 23, debounce_ms=50)


# ---------------------------------------------------------------------------
# Fixtures: Relay controllers
# ---------------------------------------------------------------------------

@pytest.fixture
def relay_controller():
    """Basic RelayController."""
    from lib.relay import RelayController
    return RelayController(16, invert=True, name='TestRelay')


@pytest.fixture
def fan_controller(time_provider, mock_dht_logger, mock_event_logger):
    """FanController with all dependencies mocked."""
    from lib.relay import FanController
    return FanController(
        pin=16,
        time_provider=time_provider,
        dht_logger=mock_dht_logger,
        logger=mock_event_logger,
        interval_s=600,
        on_time_s=20,
        max_temp=24.0,
        temp_hysteresis=1.0,
        name='TestFan',
    )


@pytest.fixture
def growlight_controller(time_provider, mock_event_logger):
    """GrowlightController with explicit schedule."""
    from lib.relay import GrowlightController
    return GrowlightController(
        pin=17,
        time_provider=time_provider,
        logger=mock_event_logger,
        dawn_hour=6,
        dawn_minute=0,
        sunset_hour=20,
        sunset_minute=0,
        name='TestGrowlight',
    )
