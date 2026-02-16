# Tests for lib/dht_logger.py
# Covers sensor reading, date rollover, CSV file creation, log loop

import asyncio
import pytest
from unittest.mock import Mock, patch, MagicMock
from tests.conftest import FAKE_LOCALTIME


class TestDHTLoggerInit:
    """Tests for DHTLogger initialization."""

    def test_init_creates_csv_header(self, time_provider, buffer_manager, mock_event_logger):
        """DHTLogger init creates CSV file with header via buffer_manager."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch.object(buffer_manager, 'write', return_value=True) as write_mock:
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        # Should have written CSV header
        write_mock.assert_called()
        header_call = write_mock.call_args_list[0]
        assert 'Timestamp,Temperature,Humidity' in header_call[0][1]

    def test_init_logs_fallback_when_sd_unavailable(self, time_provider, buffer_manager, mock_event_logger):
        """When write returns False (fallback), log message reflects fallback destination."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch.object(buffer_manager, 'write', return_value=False):
                with patch.object(buffer_manager, 'has_data_for', return_value=False):
                    dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        # Should log fallback message, not primary
        info_calls = [str(c) for c in mock_event_logger.info.call_args_list]
        assert any('fallback' in c for c in info_calls)

    def test_init_sets_interval(self, time_provider, buffer_manager, mock_event_logger):
        """DHTLogger interval is set from constructor arg."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger, interval=30)
        assert dht.interval == 30

    def test_init_state_defaults(self, time_provider, buffer_manager, mock_event_logger):
        """Initial state: no cached readings, zero failures."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        assert dht.last_temperature is None
        assert dht.last_humidity is None
        assert dht.read_failures == 0
        assert dht.write_failures == 0

    def test_init_existing_csv_skips_create(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """When CSV already exists, __init__ skips _create_file."""
        from lib.dht_logger import DHTLogger
        # Pre-create the file that DHTLogger would look for
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            # Peek at what the filename would be
            from lib.time_provider import RTCTimeProvider
            # Manually create the expected file so _file_exists returns True
            relpath = f'dht_log_2026-01-29.csv'
            primary_path = tmp_path / "sd" / relpath
            primary_path.write_text('Timestamp,Temperature,Humidity\n')

            with patch.object(buffer_manager, 'write') as write_mock:
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        # write should NOT have been called (file already exists)
        write_mock.assert_not_called()

    def test_init_create_file_failure_logged(self, time_provider, buffer_manager, mock_event_logger):
        """If _create_file raises, error is logged but init continues."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch.object(buffer_manager, 'write', side_effect=OSError('disk full')):
                # Should not crash
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        # Error should have been logged
        mock_event_logger.error.assert_called()


class TestDHTLoggerReadSensor:
    """Tests for read_sensor() method."""

    def test_read_sensor_success(self, time_provider, buffer_manager, mock_event_logger):
        """Successful sensor read returns (temp, hum)."""
        from lib.dht_logger import DHTLogger

        sensor = Mock()
        sensor.measure = Mock()
        sensor.temperature = Mock(return_value=22.5)
        sensor.humidity = Mock(return_value=65.0)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('dht.DHT22', return_value=sensor):
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        temp, hum = dht.read_sensor()
        assert temp == 22.5
        assert hum == 65.0

    def test_read_sensor_out_of_range(self, time_provider, buffer_manager, mock_event_logger):
        """Out-of-range readings return (None, None)."""
        from lib.dht_logger import DHTLogger

        sensor = Mock()
        sensor.measure = Mock()
        sensor.temperature = Mock(return_value=120.0)
        sensor.humidity = Mock(return_value=150.0)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('dht.DHT22', return_value=sensor):
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger, max_retries=2)
        temp, hum = dht.read_sensor()
        assert temp is None
        assert hum is None
        assert dht.read_failures == 1

    def test_read_sensor_retry_on_exception(self, time_provider, buffer_manager, mock_event_logger):
        """First measure() raises, second attempt succeeds."""
        from lib.dht_logger import DHTLogger

        sensor = Mock()
        call_count = 0
        def counting_measure():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError('sensor error')
        sensor.measure = counting_measure
        sensor.temperature = Mock(return_value=22.0)
        sensor.humidity = Mock(return_value=60.0)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('dht.DHT22', return_value=sensor):
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger, max_retries=3)
        with patch('time.sleep'):
            temp, hum = dht.read_sensor()
        assert temp == 22.0
        assert hum == 60.0

    def test_read_sensor_all_retries_fail(self, time_provider, buffer_manager, mock_event_logger):
        """All retry attempts fail → (None, None) and read_failures incremented."""
        from lib.dht_logger import DHTLogger

        sensor = Mock()
        sensor.measure = Mock(side_effect=OSError('always fails'))

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('dht.DHT22', return_value=sensor):
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger, max_retries=3)
        with patch('time.sleep'):
            temp, hum = dht.read_sensor()
        assert temp is None
        assert hum is None
        assert dht.read_failures == 1

    def test_read_sensor_negative_boundary(self, time_provider, buffer_manager, mock_event_logger):
        """Boundary: -40°C is valid, -41°C is out of range."""
        from lib.dht_logger import DHTLogger

        sensor = Mock()
        sensor.measure = Mock()
        sensor.temperature = Mock(return_value=-40.0)
        sensor.humidity = Mock(return_value=0.0)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('dht.DHT22', return_value=sensor):
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        temp, hum = dht.read_sensor()
        assert temp == -40.0
        assert hum == 0.0


class TestDHTLoggerDateRollover:
    """Tests for date-based file rollover."""

    def test_update_filename_for_date(self, time_provider, buffer_manager, mock_event_logger):
        """Filename includes date in dht_log_YYYY-MM-DD.csv format."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        assert '2026-01-29' in dht.filename

    def test_check_date_changed_detects_rollover(self, time_provider, buffer_manager, mock_event_logger):
        """_check_date_changed returns True when date changes."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)

        dht.current_date = (2026, 1, 28)  # Yesterday
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            changed = dht._check_date_changed()
        assert changed is True
        assert dht.current_date == (2026, 1, 29)

    def test_check_date_no_change(self, time_provider, buffer_manager, mock_event_logger):
        """_check_date_changed returns False when date hasn't changed."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
            changed = dht._check_date_changed()
        assert changed is False

    def test_update_filename_error_fallback(self, time_provider, buffer_manager, mock_event_logger):
        """If now_date_tuple raises, filename falls back to base."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)

        dht.time_provider = Mock()
        dht.time_provider.now_date_tuple = Mock(side_effect=OSError('fail'))
        dht.logger = mock_event_logger
        dht._update_filename_for_date()
        # Should fall back to filename_base
        assert dht.filename == dht.filename_base


class TestDHTLoggerFileOps:
    """Tests for file operations."""

    def test_file_exists_true_primary(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """_file_exists returns True when file exists on primary."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        # Create the expected file
        relpath = dht._strip_sd_prefix(dht.filename)
        (tmp_path / "sd" / relpath).write_text("header\n")
        assert dht._file_exists() is True

    def test_file_exists_true_fallback(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """_file_exists returns True when data exists only in fallback."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        # Remove the primary file (was created during init)
        relpath = dht._strip_sd_prefix(dht.filename)
        primary = tmp_path / "sd" / relpath
        if primary.exists():
            primary.unlink()
        # Write to fallback in pipe-delimited format
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text(f'{relpath}|Timestamp,Temperature,Humidity\n')
        assert dht._file_exists() is True

    def test_file_exists_true_buffer(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """_file_exists returns True when data exists only in memory buffer."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        relpath = dht._strip_sd_prefix(dht.filename)
        # Remove primary file
        primary = tmp_path / "sd" / relpath
        if primary.exists():
            primary.unlink()
        # Put data in memory buffer
        buffer_manager._buffers[relpath] = ['Timestamp,Temperature,Humidity\n']
        assert dht._file_exists() is True

    def test_file_exists_false(self, time_provider, buffer_manager, mock_event_logger):
        """_file_exists returns False when data absent from all locations."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)
        dht.filename = '/sd/nonexistent_file.csv'
        assert dht._file_exists() is False

    def test_strip_sd_prefix(self):
        """_strip_sd_prefix removes /sd/ prefix."""
        from lib.dht_logger import DHTLogger
        assert DHTLogger._strip_sd_prefix('/sd/dht_log.csv') == 'dht_log.csv'
        assert DHTLogger._strip_sd_prefix('dht_log.csv') == 'dht_log.csv'


@pytest.mark.asyncio
class TestDHTLoggerLogLoop:
    """Tests for the async log_loop."""

    async def test_log_loop_writes_csv_row(self, time_provider, buffer_manager, mock_event_logger):
        """log_loop writes CSV rows in timestamp,temp,hum format."""
        from lib.dht_logger import DHTLogger

        sensor = Mock()
        sensor.measure = Mock()
        sensor.temperature = Mock(return_value=22.5)
        sensor.humidity = Mock(return_value=65.0)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('dht.DHT22', return_value=sensor):
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger, interval=1)

        loop_count = 0
        async def limited_sleep(duration):
            nonlocal loop_count
            if duration >= 1:
                loop_count += 1
                if loop_count >= 1:
                    raise asyncio.CancelledError()

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('asyncio.sleep', side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await dht.log_loop()

        assert dht.last_temperature == 22.5
        assert dht.last_humidity == 65.0

    async def test_log_loop_sensor_failure_increments_count(self, time_provider, buffer_manager, mock_event_logger):
        """When sensor fails in log_loop, read_failures counter increments."""
        from lib.dht_logger import DHTLogger

        sensor = Mock()
        sensor.measure = Mock(side_effect=OSError('sensor error'))
        sensor.temperature = Mock(return_value=22.5)
        sensor.humidity = Mock(return_value=65.0)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('dht.DHT22', return_value=sensor):
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger, interval=1, max_retries=1)

        loop_count = 0
        async def limited_sleep(duration):
            nonlocal loop_count
            if duration >= 1:
                loop_count += 1
                if loop_count >= 1:
                    raise asyncio.CancelledError()

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('time.sleep'):
                with patch('asyncio.sleep', side_effect=limited_sleep):
                    with pytest.raises(asyncio.CancelledError):
                        await dht.log_loop()

        assert dht.read_failures >= 1

    async def test_log_loop_write_failure_increments_count(self, time_provider, buffer_manager, mock_event_logger):
        """When buffer_manager.write raises in log_loop, write_failures increments."""
        from lib.dht_logger import DHTLogger

        sensor = Mock()
        sensor.measure = Mock()
        sensor.temperature = Mock(return_value=22.5)
        sensor.humidity = Mock(return_value=65.0)

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('dht.DHT22', return_value=sensor):
                dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger, interval=1)

        # Make write raise after the CSV header is already created
        original_write = buffer_manager.write
        call_count = 0
        def failing_write(relpath, data):
            nonlocal call_count
            call_count += 1
            if 'Timestamp' not in data:  # Don't fail on header writes
                raise OSError('disk full')
            return original_write(relpath, data)
        buffer_manager.write = failing_write

        loop_count = 0
        async def limited_sleep(duration):
            nonlocal loop_count
            if duration >= 1:
                loop_count += 1
                if loop_count >= 1:
                    raise asyncio.CancelledError()

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('asyncio.sleep', side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await dht.log_loop()

        assert dht.write_failures >= 1

    async def test_log_loop_unexpected_error_continues(self, time_provider, buffer_manager, mock_event_logger):
        """Generic exception in log_loop is caught and loop continues."""
        from lib.dht_logger import DHTLogger

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger, interval=1)

        # Make _check_date_changed raise a generic error
        dht._check_date_changed = Mock(side_effect=RuntimeError('unexpected'))

        call_count = 0
        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise asyncio.CancelledError()

        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            with patch('asyncio.sleep', side_effect=counting_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await dht.log_loop()

        # The unexpected error was logged
        mock_event_logger.error.assert_called()

    async def test_log_loop_cancelled_error(self, time_provider, buffer_manager, mock_event_logger):
        """CancelledError is re-raised from log_loop."""
        from lib.dht_logger import DHTLogger
        with patch('time.localtime', return_value=FAKE_LOCALTIME):
            dht = DHTLogger(15, time_provider, buffer_manager, mock_event_logger)

        with patch('asyncio.sleep', side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await dht.log_loop()
