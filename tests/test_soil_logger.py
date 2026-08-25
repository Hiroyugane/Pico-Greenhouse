# Tests for lib/soil_logger.py
# Covers SoilLogger against the injected STEMMA driver: raw-count to percent
# conversion (inverted convention), root-zone temperature alarms, async poll
# loop, BufferManager plumbing, warning-LED hook, and the shared
# sensor-health reporting policy.

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import FAKE_LOCALTIME


class FakeStemma:
    """Minimal STEMMA stub: programmable raw count and probe temperature."""

    def __init__(self, raw: int = 1100, temp_c: float = 22.0):
        self.raw = raw
        self.temp_c = temp_c
        self.fail = False
        self.moisture_calls = 0

    def moisture(self) -> int:
        self.moisture_calls += 1
        if self.fail:
            raise OSError("stemma not responding")
        return self.raw

    def temperature(self) -> float:
        if self.fail:
            raise OSError("stemma not responding")
        return self.temp_c


@pytest.fixture
def fake_sensor():
    return FakeStemma()


@pytest.fixture
def soil_logger(time_provider, buffer_manager, mock_event_logger, fake_sensor):
    from lib.soil_logger import SoilLogger

    return SoilLogger(
        sensor=fake_sensor,
        time_provider=time_provider,
        buffer_manager=buffer_manager,
        logger=mock_event_logger,
        interval_s=60,
        raw_dry=200,
        raw_wet=2000,
        warn_pct_below=20,
        root_temp_min_c=20.0,
        root_temp_max_c=26.0,
        sensor_root="/sd/sensors",
        sensor_type="soil",
    )


class TestRawToPercent:
    """The capacitive probe inverts the old analog convention: wet > dry."""

    def test_at_wet_endpoint_is_100(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(2000, dry=200, wet=2000) == 100

    def test_at_dry_endpoint_is_zero(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(200, dry=200, wet=2000) == 0

    def test_midpoint_is_fifty(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(1100, dry=200, wet=2000) == 50

    def test_above_wet_clamps_to_100(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(3000, dry=200, wet=2000) == 100

    def test_below_dry_clamps_to_zero(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(50, dry=200, wet=2000) == 0

    def test_dry_direction_is_not_the_old_analog_one(self):
        """A high count is WET now — the analog probe read the other way."""
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(1800, dry=200, wet=2000) > raw_to_percent(400, dry=200, wet=2000)


class TestPollOnce:
    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_successful_poll_caches_percent_raw_and_root_temp(self, soil_logger, fake_sensor):
        fake_sensor.raw = 1100
        fake_sensor.temp_c = 21.5
        self._run(soil_logger._poll_once())
        assert soil_logger.last_percent == 50
        assert soil_logger.last_raw == 1100
        assert soil_logger.last_root_temp_c == pytest.approx(21.5)

    def test_dry_reading_records_zero_percent(self, soil_logger, fake_sensor):
        fake_sensor.raw = 200
        self._run(soil_logger._poll_once())
        assert soil_logger.last_percent == 0

    def test_wet_reading_records_hundred_percent(self, soil_logger, fake_sensor):
        fake_sensor.raw = 2000
        self._run(soil_logger._poll_once())
        assert soil_logger.last_percent == 100

    def test_successful_poll_writes_csv_row(self, soil_logger, fake_sensor, buffer_manager):
        fake_sensor.raw = 1100
        fake_sensor.temp_c = 21.5
        self._run(soil_logger._poll_once())
        from pathlib import Path

        sd_files = list(Path(buffer_manager.sd_mount_point).rglob("soil_*.csv"))
        assert len(sd_files) == 1
        assert sd_files[0].parent.parent.name == "soil"
        content = sd_files[0].read_text()
        # CSV format: Timestamp,Raw,Percent,RootTempC
        assert "Timestamp,Raw,Percent,RootTempC" in content
        assert ",1100,50,21.5" in content


class TestWarningHook:
    """Warning LED should flip when percent dips below warn_pct_below."""

    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_below_threshold_sets_warning(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        fake_sensor.raw = 400  # close to dry → ~11%
        self._run(soil_logger._poll_once())
        calls = [c.args for c in mock_status_manager.set_warning.call_args_list if c.args[0] == "soil_low"]
        assert calls == [("soil_low", True)]

    def test_above_threshold_clears_warning(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        fake_sensor.raw = 1600  # wet → high percent → no warning
        self._run(soil_logger._poll_once())
        calls = [c.args for c in mock_status_manager.set_warning.call_args_list if c.args[0] == "soil_low"]
        assert calls == [("soil_low", False)]

    def test_no_status_manager_does_not_crash(self, soil_logger, fake_sensor):
        soil_logger.status_manager = None
        fake_sensor.raw = 400
        self._run(soil_logger._poll_once())


class TestRootTemperatureAlarms:
    """Root zone is logged and alarmed only — never regulated."""

    def _poll(self, logger, sensor, temp_c):
        sensor.temp_c = temp_c
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(logger._poll_once())

    def _keys(self, status, key):
        return [c.args for c in status.set_warning.call_args_list if c.args[0] == key]

    def test_below_minimum_warns(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        self._poll(soil_logger, fake_sensor, 19.9)
        assert self._keys(mock_status_manager, "root_temp_low") == [("root_temp_low", True)]

    def test_at_minimum_does_not_warn(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        self._poll(soil_logger, fake_sensor, 20.0)
        assert self._keys(mock_status_manager, "root_temp_low") == []

    def test_at_maximum_does_not_warn(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        self._poll(soil_logger, fake_sensor, 26.0)
        assert self._keys(mock_status_manager, "root_temp_high") == []

    def test_above_maximum_warns(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        self._poll(soil_logger, fake_sensor, 26.1)
        assert self._keys(mock_status_manager, "root_temp_high") == [("root_temp_high", True)]

    def test_excursion_is_reported_once_and_cleared_once(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        for _ in range(5):
            self._poll(soil_logger, fake_sensor, 18.0)
        self._poll(soil_logger, fake_sensor, 22.0)
        assert self._keys(mock_status_manager, "root_temp_low") == [
            ("root_temp_low", True),
            ("root_temp_low", False),
        ]
        warn_texts = [c.args[1] for c in soil_logger.logger.warning.call_args_list]
        assert len([t for t in warn_texts if "root zone cold" in t]) == 1

    def test_no_status_manager_skips_root_alarms(self, soil_logger, fake_sensor):
        soil_logger.status_manager = None
        self._poll(soil_logger, fake_sensor, 5.0)
        assert soil_logger.last_root_temp_c == pytest.approx(5.0)


class TestSensorHealthIntegration:
    """Missed reads follow the shared edge-triggered policy (S1)."""

    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_repeated_failures_warn_once(self, soil_logger, fake_sensor, mock_event_logger):
        fake_sensor.fail = True
        for _ in range(30):
            self._run(soil_logger._poll_once())
        warn_texts = [c.args[1] for c in mock_event_logger.warning.call_args_list]
        unreachable = [t for t in warn_texts if "unreachable" in t]
        assert len(unreachable) == 1
        assert "3 failed reads" in unreachable[0]
        assert soil_logger.read_failures == 30  # the counter still counts them all

    def test_the_edge_warning_names_the_last_failure_cause(self, soil_logger, fake_sensor, mock_event_logger):
        """The per-read detail is DEBUG, so the one WARN has to carry the cause."""
        fake_sensor.fail = True
        for _ in range(3):
            self._run(soil_logger._poll_once())
        unreachable = [c.args[1] for c in mock_event_logger.warning.call_args_list if "unreachable" in c.args[1]]
        assert len(unreachable) == 1
        assert "stemma not responding" in unreachable[0]

    def test_early_failures_stay_at_debug(self, soil_logger, fake_sensor, mock_event_logger):
        fake_sensor.fail = True
        self._run(soil_logger._poll_once())
        self._run(soil_logger._poll_once())
        assert mock_event_logger.warning.call_count == 0
        assert soil_logger.health.is_unreachable() is False

    def test_unreachable_raises_one_status_warning(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        fake_sensor.fail = True
        for _ in range(20):
            self._run(soil_logger._poll_once())
        calls = [c.args for c in mock_status_manager.set_warning.call_args_list if c.args[0] == "soil_unreachable"]
        assert calls == [("soil_unreachable", True)]

    def test_recovery_logs_one_info_and_clears_the_warning(self, soil_logger, fake_sensor, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        fake_sensor.fail = True
        for _ in range(5):
            self._run(soil_logger._poll_once())
        fake_sensor.fail = False
        fake_sensor.raw = 1100
        self._run(soil_logger._poll_once())

        info_texts = [c.args[1] for c in soil_logger.logger.info.call_args_list]
        assert len([t for t in info_texts if "recovered after" in t]) == 1
        calls = [c.args for c in mock_status_manager.set_warning.call_args_list if c.args[0] == "soil_unreachable"]
        assert calls == [("soil_unreachable", True), ("soil_unreachable", False)]
        assert soil_logger.last_percent == 50

    def test_polling_backs_off_while_unreachable(self, soil_logger, fake_sensor):
        fake_sensor.fail = True
        assert soil_logger.health.interval_s() == 60
        for _ in range(3):
            self._run(soil_logger._poll_once())
        assert soil_logger.health.interval_s() == 60  # backoff_start_s
        for _ in range(3):
            self._run(soil_logger._poll_once())
        assert soil_logger.health.interval_s() > 60

    def test_absent_sensor_at_boot_still_constructs_and_polls(
        self, time_provider, buffer_manager, mock_event_logger, mock_status_manager
    ):
        """Degraded boot: an unplugged probe must not stop the system."""
        from lib.soil_logger import SoilLogger

        missing = FakeStemma()
        missing.fail = True
        logger_obj = SoilLogger(
            sensor=missing,
            time_provider=time_provider,
            buffer_manager=buffer_manager,
            logger=mock_event_logger,
            status_manager=mock_status_manager,
        )
        for _ in range(4):
            self._run(logger_obj._poll_once())
        assert logger_obj.last_percent is None
        assert logger_obj.health.is_unreachable() is True
        calls = [c.args for c in mock_status_manager.set_warning.call_args_list if c.args[0] == "soil_unreachable"]
        assert calls == [("soil_unreachable", True)]


class TestLogLoop:
    def test_log_loop_runs_until_cancelled(self, soil_logger, fake_sensor):
        fake_sensor.raw = 900

        async def runner():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await soil_logger.log_loop()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(runner())
        assert soil_logger.last_percent is not None

    def test_cancelled_error_propagates(self, soil_logger):
        async def runner():
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await soil_logger.log_loop()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(runner())


class TestFilenameRollover:
    def test_filename_includes_date_under_sensor_tree(self, soil_logger):
        assert soil_logger.filename == "/sd/sensors/soil/2026/soil_2026-01-29.csv"


class TestGetState:
    def test_get_state_includes_percent_raw_and_root_temp(self, soil_logger, fake_sensor):
        fake_sensor.raw = 1100
        fake_sensor.temp_c = 23.0
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(soil_logger._poll_once())
        state = soil_logger.get_state()
        assert state["last_percent"] == 50
        assert state["last_raw"] == 1100
        assert state["last_root_temp_c"] == pytest.approx(23.0)
        assert state["warn_pct_below"] == 20


class TestPrintRaw:
    """REPL calibration helper: prints one raw count + probe temperature."""

    def test_print_raw_emits_count_and_temperature(self, capsys):
        from lib.soil_logger import print_raw

        raw, temp = print_raw(FakeStemma(raw=742, temp_c=21.5))
        captured = capsys.readouterr()
        assert "742" in captured.out
        assert "21.5" in captured.out
        assert (raw, temp) == (742, 21.5)


class TestInitValidation:
    def test_wet_not_above_dry_raises(self, time_provider, buffer_manager, mock_event_logger, fake_sensor):
        from lib.soil_logger import SoilLogger

        with pytest.raises(ValueError, match="raw_wet"):
            SoilLogger(
                sensor=fake_sensor,
                time_provider=time_provider,
                buffer_manager=buffer_manager,
                logger=mock_event_logger,
                raw_dry=2000,
                raw_wet=200,
            )

    def test_root_temp_window_must_be_ordered(self, time_provider, buffer_manager, mock_event_logger, fake_sensor):
        from lib.soil_logger import SoilLogger

        with pytest.raises(ValueError, match="root_temp_max_c"):
            SoilLogger(
                sensor=fake_sensor,
                time_provider=time_provider,
                buffer_manager=buffer_manager,
                logger=mock_event_logger,
                root_temp_min_c=26.0,
                root_temp_max_c=20.0,
            )


class TestErrorPaths:
    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_sensor_read_failure_counts(self, soil_logger, fake_sensor):
        fake_sensor.fail = True
        self._run(soil_logger._poll_once())
        assert soil_logger.read_failures == 1
        assert soil_logger.last_percent is None

    def test_write_failure_logs_error(self, soil_logger, fake_sensor, buffer_manager):
        with patch.object(buffer_manager, "write", side_effect=OSError("sd dead")):
            self._run(soil_logger._poll_once())
        assert soil_logger.write_failures == 1

    def test_write_queue_path_used_when_supplied(self, soil_logger):
        wq = MagicMock()
        soil_logger.write_queue = wq
        self._run(soil_logger._poll_once())
        wq.enqueue_write.assert_called_once()

    def test_date_check_exception_logged(self, soil_logger, mock_event_logger):
        with patch.object(soil_logger.time_provider, "now_date_tuple", side_effect=OSError("rtc")):
            soil_logger._check_date_changed()
        assert mock_event_logger.error.called

    def test_header_write_exception_logged(self, soil_logger, buffer_manager, mock_event_logger):
        with patch.object(buffer_manager, "has_data_for", return_value=False):
            with patch.object(buffer_manager, "write", side_effect=OSError("sd dead")):
                soil_logger._ensure_header()
        assert mock_event_logger.error.called

    def test_recovery_clears_warning(self, soil_logger, fake_sensor, mock_status_manager):
        """Once the low warning is active, recovering above threshold clears it."""
        soil_logger.status_manager = mock_status_manager
        fake_sensor.raw = 400
        self._run(soil_logger._poll_once())
        assert soil_logger._warn_active is True
        fake_sensor.raw = 1600
        self._run(soil_logger._poll_once())
        assert soil_logger._warn_active is False
        info_msgs = " ".join(str(c) for c in soil_logger.logger.info.call_args_list)
        assert "recovered" in info_msgs

    def test_status_manager_failure_does_not_crash_root_alarm(self, soil_logger, fake_sensor):
        status = MagicMock()

        def _fail_on_root(key, active):
            if key.startswith("root_temp"):
                raise OSError("led bus dead")

        status.set_warning.side_effect = _fail_on_root
        soil_logger.status_manager = status
        fake_sensor.temp_c = 10.0
        self._run(soil_logger._poll_once())
        assert soil_logger.last_root_temp_c == pytest.approx(10.0)

    def test_log_loop_unexpected_error_continues(self, soil_logger, mock_event_logger):
        with patch.object(soil_logger, "_poll_once", side_effect=[RuntimeError("boom"), None]):
            with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):
                with pytest.raises(asyncio.CancelledError):
                    with patch("time.localtime", return_value=FAKE_LOCALTIME):
                        asyncio.run(soil_logger.log_loop())
        assert mock_event_logger.error.called
