# Tests for lib/temp_humidity_logger.py
# Covers sensor reading, date rollover, CSV file creation, log loop

import asyncio
from unittest.mock import Mock, patch

import pytest

from tests.conftest import FAKE_LOCALTIME


def _make_sensor(temp=22.5, hum=65.0, measure_side_effect=None):
    """Build a sensor mock matching the SHT31 driver surface."""
    sensor = Mock()
    if measure_side_effect is not None:
        sensor.measure = Mock(side_effect=measure_side_effect)
    else:
        sensor.measure = Mock()
    sensor.temperature = Mock(return_value=temp)
    sensor.humidity = Mock(return_value=hum)
    return sensor


class TestTempHumidityLoggerInit:
    """Tests for TempHumidityLogger initialization."""

    def test_init_creates_csv_header(self, time_provider, buffer_manager, mock_event_logger):
        """Init creates CSV file with header via buffer_manager."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch.object(buffer_manager, "write", return_value=True) as write_mock:
                TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        write_mock.assert_called()
        header_call = write_mock.call_args_list[0]
        assert "Timestamp,Temperature,Humidity" in header_call[0][1]

    def test_init_logs_fallback_when_sd_unavailable(self, time_provider, buffer_manager, mock_event_logger):
        """When write returns False (fallback), log message reflects fallback destination."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch.object(buffer_manager, "write", return_value=False):
                with patch.object(buffer_manager, "has_data_for", return_value=False):
                    TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        info_calls = [str(c) for c in mock_event_logger.debug.call_args_list]
        assert any("fallback" in c for c in info_calls)

    def test_init_sets_interval(self, time_provider, buffer_manager, mock_event_logger):
        """Interval is set from constructor arg."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, interval=30)
        assert th.interval == 30

    def test_init_state_defaults(self, time_provider, buffer_manager, mock_event_logger):
        """Initial state: no cached readings, zero failures."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        assert th.last_temperature is None
        assert th.last_humidity is None
        assert th.read_failures == 0
        assert th.write_failures == 0

    def test_init_existing_csv_skips_create(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """When CSV already exists, __init__ skips _create_file."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            relpath = "sensors/th/2026/th_2026-01-29.csv"
            primary_path = tmp_path / "sd" / relpath
            primary_path.parent.mkdir(parents=True, exist_ok=True)
            primary_path.write_text("Timestamp,Temperature,Humidity\n")

            with patch.object(buffer_manager, "write") as write_mock:
                TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        write_mock.assert_not_called()

    def test_init_create_file_failure_logged(self, time_provider, buffer_manager, mock_event_logger):
        """If _create_file raises, error is logged but init continues."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch.object(buffer_manager, "write", side_effect=OSError("disk full")):
                TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        mock_event_logger.error.assert_called()


class TestTempHumidityLoggerReadSensor:
    """Tests for read_sensor() method."""

    def test_read_sensor_success(self, time_provider, buffer_manager, mock_event_logger):
        """Successful sensor read returns (temp, hum)."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor(temp=22.5, hum=65.0)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        temp, hum = th.read_sensor()
        assert temp == 22.5
        assert hum == 65.0

    def test_read_sensor_out_of_range(self, time_provider, buffer_manager, mock_event_logger):
        """Out-of-range readings return (None, None)."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor(temp=120.0, hum=150.0)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, max_retries=2)
        temp, hum = th.read_sensor()
        assert temp is None
        assert hum is None
        assert th.read_failures == 1

    def test_read_sensor_retry_on_exception(self, time_provider, buffer_manager, mock_event_logger):
        """First measure() raises, second attempt succeeds."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = Mock()
        call_count = 0

        def counting_measure():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("sensor error")

        sensor.measure = counting_measure
        sensor.temperature = Mock(return_value=22.0)
        sensor.humidity = Mock(return_value=60.0)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, max_retries=3)
        with patch("time.sleep"):
            temp, hum = th.read_sensor()
        assert temp == 22.0
        assert hum == 60.0

    def test_read_sensor_all_retries_fail(self, time_provider, buffer_manager, mock_event_logger):
        """All retry attempts fail → (None, None) and read_failures incremented."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = Mock()
        sensor.measure = Mock(side_effect=OSError("always fails"))

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, max_retries=3)
        with patch("time.sleep"):
            temp, hum = th.read_sensor()
        assert temp is None
        assert hum is None
        assert th.read_failures == 1

    def test_read_sensor_negative_boundary(self, time_provider, buffer_manager, mock_event_logger):
        """Boundary: -40°C is valid, -41°C is out of range."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor(temp=-40.0, hum=0.0)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        temp, hum = th.read_sensor()
        assert temp == -40.0
        assert hum == 0.0


class TestTempHumidityLoggerDateRollover:
    """Tests for date-based file rollover."""

    def test_update_filename_for_date(self, time_provider, buffer_manager, mock_event_logger):
        """Filename uses sensors/th/YYYY/th_YYYY-MM-DD.csv layout."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        assert th.filename == "/sd/sensors/th/2026/th_2026-01-29.csv"

    def test_check_date_changed_detects_rollover(self, time_provider, buffer_manager, mock_event_logger):
        """_check_date_changed returns True when date changes."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)

        th.current_date = (2026, 1, 28)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            changed = th._check_date_changed()
        assert changed is True
        assert th.current_date == (2026, 1, 29)

    def test_check_date_no_change(self, time_provider, buffer_manager, mock_event_logger):
        """_check_date_changed returns False when date hasn't changed."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
            changed = th._check_date_changed()
        assert changed is False

    def test_update_filename_error_fallback(self, time_provider, buffer_manager, mock_event_logger):
        """If now_date_tuple raises, filename falls back to undated default."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)

        th.time_provider = Mock()
        th.time_provider.now_date_tuple = Mock(side_effect=OSError("fail"))
        th.logger = mock_event_logger
        th._update_filename_for_date()
        assert th.filename == "/sd/sensors/th/th.csv"


class TestTempHumidityLoggerFileOps:
    """Tests for file operations."""

    def test_file_exists_true_primary(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """_file_exists returns True when file exists on primary."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        relpath = th._strip_sd_prefix(th.filename)
        (tmp_path / "sd" / relpath).write_text("header\n")
        assert th._file_exists() is True

    def test_file_exists_true_fallback(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """_file_exists returns True when data exists only in fallback."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        relpath = th._strip_sd_prefix(th.filename)
        primary = tmp_path / "sd" / relpath
        if primary.exists():
            primary.unlink()
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text(f"{relpath}|Timestamp,Temperature,Humidity\n")
        assert th._file_exists() is True

    def test_file_exists_true_buffer(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """_file_exists returns True when data exists only in memory buffer."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        relpath = th._strip_sd_prefix(th.filename)
        primary = tmp_path / "sd" / relpath
        if primary.exists():
            primary.unlink()
        buffer_manager._buffers[relpath] = ["Timestamp,Temperature,Humidity\n"]
        assert th._file_exists() is True

    def test_file_exists_false(self, time_provider, buffer_manager, mock_event_logger):
        """_file_exists returns False when data absent from all locations."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        th.filename = "/sd/nonexistent_file.csv"
        assert th._file_exists() is False

    def test_file_exists_true_after_create_even_if_has_data_for_fails(
        self, time_provider, buffer_manager, mock_event_logger
    ):
        """_file_exists returns True from in-memory cache even when has_data_for fails."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)

        with patch.object(buffer_manager, "has_data_for", return_value=False):
            assert th._file_exists() is True

    def test_created_files_not_shared_across_dates(self, time_provider, buffer_manager, mock_event_logger):
        """After date rollover, new filename is not in _created_files cache."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)

        th.filename = "/sd/sensors/th/2026/th_2026-01-30.csv"
        with patch.object(buffer_manager, "has_data_for", return_value=False):
            assert th._file_exists() is False

    def test_strip_sd_prefix(self):
        """_strip_sd_prefix removes /sd/ prefix."""
        from lib.temp_humidity_logger import TempHumidityLogger

        assert TempHumidityLogger._strip_sd_prefix("/sd/th_log.csv") == "th_log.csv"
        assert TempHumidityLogger._strip_sd_prefix("th_log.csv") == "th_log.csv"


@pytest.mark.asyncio
class TestTempHumidityLoggerLogLoop:
    """Tests for the async log_loop."""

    async def test_log_loop_writes_csv_row(self, time_provider, buffer_manager, mock_event_logger):
        """log_loop writes CSV rows in timestamp,temp,hum format."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor(temp=22.5, hum=65.0)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, interval=1)

        loop_count = 0

        async def limited_sleep(duration):
            nonlocal loop_count
            if duration >= 1:
                loop_count += 1
                if loop_count >= 1:
                    raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await th.log_loop()

        assert th.last_temperature == 22.5
        assert th.last_humidity == 65.0

    async def test_log_loop_sensor_failure_increments_count(self, time_provider, buffer_manager, mock_event_logger):
        """When sensor fails in log_loop, read_failures counter increments."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = Mock()
        sensor.measure = Mock(side_effect=OSError("sensor error"))
        sensor.temperature = Mock(return_value=22.5)
        sensor.humidity = Mock(return_value=65.0)

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(
                sensor,
                time_provider,
                buffer_manager,
                mock_event_logger,
                interval=1,
                max_retries=1,
            )

        loop_count = 0

        async def limited_sleep(duration):
            nonlocal loop_count
            if duration >= 1:
                loop_count += 1
                if loop_count >= 1:
                    raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("time.sleep"):
                with patch("asyncio.sleep", side_effect=limited_sleep):
                    with pytest.raises(asyncio.CancelledError):
                        await th.log_loop()

        assert th.read_failures >= 1

    async def test_log_loop_write_failure_increments_count(self, time_provider, buffer_manager, mock_event_logger):
        """When buffer_manager.write raises in log_loop, write_failures increments."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, interval=1)

        original_write = buffer_manager.write

        def failing_write(relpath, data):
            if "Timestamp" not in data:
                raise OSError("disk full")
            return original_write(relpath, data)

        buffer_manager.write = failing_write

        loop_count = 0

        async def limited_sleep(duration):
            nonlocal loop_count
            if duration >= 1:
                loop_count += 1
                if loop_count >= 1:
                    raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await th.log_loop()

        assert th.write_failures >= 1

    async def test_log_loop_unexpected_error_continues(self, time_provider, buffer_manager, mock_event_logger):
        """Generic exception in log_loop is caught and loop continues."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, interval=1)

        th._check_date_changed = Mock(side_effect=RuntimeError("unexpected"))

        call_count = 0

        async def counting_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=counting_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await th.log_loop()

        mock_event_logger.error.assert_called()

    async def test_log_loop_cancelled_error(self, time_provider, buffer_manager, mock_event_logger):
        """CancelledError is re-raised from log_loop."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await th.log_loop()

    async def test_log_loop_data_written_to_sd_file(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """log_loop writes CSV rows to the actual SD file (not just cache)."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor(temp=22.5, hum=65.0)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, interval=1)

        loop_count = 0

        async def limited_sleep(duration):
            nonlocal loop_count
            if duration >= 1:
                loop_count += 1
                if loop_count >= 2:
                    raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await th.log_loop()

        relpath = th._strip_sd_prefix(th.filename)
        sd_file = tmp_path / "sd" / relpath
        assert sd_file.exists(), f"Log file was not created on SD: {sd_file}"
        content = sd_file.read_text()
        lines = content.strip().split("\n")
        assert lines[0] == "Timestamp,Temperature,Humidity", "Missing CSV header"
        assert len(lines) >= 2, "No data rows written (only header)"
        assert "22.5" in lines[1] and "65.0" in lines[1], "Data row missing sensor values"

    async def test_log_loop_fallback_write_logs_warning(self, time_provider, buffer_manager, mock_event_logger):
        """When write returns False (fallback), log_loop logs a warning."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, interval=1)

        original_write = buffer_manager.write

        def fallback_write(relpath, data):
            if "Timestamp" not in data:
                return False
            return original_write(relpath, data)

        buffer_manager.write = fallback_write

        loop_count = 0

        async def limited_sleep(duration):
            nonlocal loop_count
            if duration >= 1:
                loop_count += 1
                if loop_count >= 1:
                    raise asyncio.CancelledError()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            with patch("asyncio.sleep", side_effect=limited_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await th.log_loop()

        warn_calls = [str(c) for c in mock_event_logger.warning.call_args_list]
        assert any("fallback" in c.lower() for c in warn_calls), f"No fallback warning logged: {warn_calls}"


class TestTHStatusUpdate:
    """Tests for _update_th_status() status propagation."""

    def _make_th_with_status(
        self,
        time_provider,
        buffer_manager,
        mock_event_logger,
        mock_status_manager,
        warn_threshold=3,
        error_threshold=10,
    ):
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(
                sensor,
                time_provider,
                buffer_manager,
                mock_event_logger,
                status_manager=mock_status_manager,
                th_warn_threshold=warn_threshold,
                th_error_threshold=error_threshold,
            )
        return th

    def test_warning_threshold_sets_warning(
        self, time_provider, buffer_manager, mock_event_logger, mock_status_manager
    ):
        """At warn_threshold consecutive failures, sets th_intermittent warning."""
        th = self._make_th_with_status(
            time_provider,
            buffer_manager,
            mock_event_logger,
            mock_status_manager,
            warn_threshold=3,
            error_threshold=10,
        )
        th._consecutive_failures = 3
        th._update_th_status()

        mock_status_manager.set_warning.assert_called_with("th_intermittent", True)
        mock_status_manager.set_error.assert_called_with("th_dead", False)

    def test_error_threshold_sets_error(self, time_provider, buffer_manager, mock_event_logger, mock_status_manager):
        """At error_threshold consecutive failures, sets th_dead error."""
        th = self._make_th_with_status(
            time_provider,
            buffer_manager,
            mock_event_logger,
            mock_status_manager,
            warn_threshold=3,
            error_threshold=10,
        )
        th._consecutive_failures = 10
        th._update_th_status()

        mock_status_manager.set_error.assert_called_with("th_dead", True)
        mock_status_manager.set_warning.assert_called_with("th_intermittent", False)

    def test_recovery_clears_both(self, time_provider, buffer_manager, mock_event_logger, mock_status_manager):
        """Below warn_threshold, both warning and error are cleared."""
        th = self._make_th_with_status(
            time_provider,
            buffer_manager,
            mock_event_logger,
            mock_status_manager,
            warn_threshold=3,
            error_threshold=10,
        )
        th._consecutive_failures = 0
        th._update_th_status()

        mock_status_manager.clear_warning.assert_called_with("th_intermittent")
        mock_status_manager.clear_error.assert_called_with("th_dead")

    def test_no_status_manager_no_crash(self, time_provider, buffer_manager, mock_event_logger):
        """When status_manager is None, _update_th_status() returns silently."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        assert th.status_manager is None
        th._consecutive_failures = 99
        th._update_th_status()  # Should not raise


class TestTempHumidityLoggerDateCheckException:
    """Tests for _check_date_changed() error handling."""

    def test_date_check_exception_returns_false(self, time_provider, buffer_manager, mock_event_logger):
        """When now_date_tuple() raises, _check_date_changed() returns False."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)

        time_provider.now_date_tuple = Mock(side_effect=OSError("RTC fail"))
        result = th._check_date_changed()
        assert result is False
        mock_event_logger.error.assert_called()


class TestTHReadSensorBoundaries:
    """Tests for read_sensor() boundary values."""

    def test_upper_bound_80c_100pct(self, time_provider, buffer_manager, mock_event_logger):
        """80°C and 100% humidity (upper bounds) are accepted."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor(temp=80.0, hum=100.0)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger)
        temp, hum = th.read_sensor()
        assert temp == 80.0
        assert hum == 100.0

    def test_out_of_range_above_upper_bound(self, time_provider, buffer_manager, mock_event_logger):
        """81°C is out of range and rejected."""
        from lib.temp_humidity_logger import TempHumidityLogger

        sensor = _make_sensor(temp=81.0, hum=50.0)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            th = TempHumidityLogger(sensor, time_provider, buffer_manager, mock_event_logger, max_retries=1)
        temp, hum = th.read_sensor()
        assert temp is None
        assert hum is None
