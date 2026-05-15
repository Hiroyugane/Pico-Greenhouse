# Tests for lib/soil_logger.py
# Covers SoilLogger: raw ADC to percent conversion, async poll loop,
# BufferManager plumbing, warning-LED hook on low moisture.

import asyncio
from unittest.mock import MagicMock, Mock, patch

import pytest

from tests.conftest import FAKE_LOCALTIME


class FakeADC:
    """Minimal ADC stub: returns a programmable 16-bit value via read_u16()."""

    def __init__(self, value_u16: int = 0):
        self.value_u16 = value_u16
        self.read_calls = 0

    def read_u16(self) -> int:
        self.read_calls += 1
        return self.value_u16


def _raw10_to_u16(raw10: int) -> int:
    """Scale a 0-1023 reading to the 0-65535 space ADC.read_u16 returns."""
    return int(raw10 * 65535 / 1023)


@pytest.fixture
def fake_adc():
    return FakeADC(value_u16=_raw10_to_u16(600))


@pytest.fixture
def soil_logger(time_provider, buffer_manager, mock_event_logger, fake_adc):
    from lib.soil_logger import SoilLogger

    return SoilLogger(
        adc=fake_adc,
        time_provider=time_provider,
        buffer_manager=buffer_manager,
        logger=mock_event_logger,
        interval_s=60,
        adc_dry_raw=850,
        adc_wet_raw=350,
        warn_pct_below=20,
        filename_base="soil_log",
    )


class TestRawToPercent:
    """Pure-function conversion is exposed for the REPL helper + tests."""

    def test_at_wet_endpoint_is_100(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(350, dry=850, wet=350) == 100

    def test_at_dry_endpoint_is_zero(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(850, dry=850, wet=350) == 0

    def test_midpoint_is_fifty(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(600, dry=850, wet=350) == 50

    def test_below_wet_clamps_to_100(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(100, dry=850, wet=350) == 100

    def test_above_dry_clamps_to_zero(self):
        from lib.soil_logger import raw_to_percent

        assert raw_to_percent(1023, dry=850, wet=350) == 0


class TestPollOnce:
    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_successful_poll_caches_percent_and_raw(self, soil_logger, fake_adc):
        # Midpoint between 850 (dry) and 350 (wet) → 50%
        fake_adc.value_u16 = _raw10_to_u16(600)
        self._run(soil_logger._poll_once())
        assert soil_logger.last_percent == 50
        assert soil_logger.last_raw == 600

    def test_dry_reading_records_zero_percent(self, soil_logger, fake_adc):
        fake_adc.value_u16 = _raw10_to_u16(850)
        self._run(soil_logger._poll_once())
        assert soil_logger.last_percent == 0

    def test_wet_reading_records_hundred_percent(self, soil_logger, fake_adc):
        fake_adc.value_u16 = _raw10_to_u16(350)
        self._run(soil_logger._poll_once())
        assert soil_logger.last_percent == 100

    def test_successful_poll_writes_csv_row(self, soil_logger, fake_adc, buffer_manager):
        fake_adc.value_u16 = _raw10_to_u16(600)
        self._run(soil_logger._poll_once())
        from pathlib import Path

        sd_files = list(Path(buffer_manager.sd_mount_point).glob("soil_log_*.csv"))
        assert len(sd_files) == 1
        content = sd_files[0].read_text()
        # CSV format: Timestamp,Raw,Percent
        assert "Timestamp,Raw,Percent" in content
        assert "600" in content
        assert "50" in content


class TestWarningHook:
    """Warning LED should flip when percent dips below warn_pct_below."""

    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_below_threshold_sets_warning(self, soil_logger, fake_adc, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        # 10% (above wet) → triggers warning since 10 < warn_pct_below=20
        fake_adc.value_u16 = _raw10_to_u16(800)  # close to dry → low percent
        self._run(soil_logger._poll_once())
        mock_status_manager.set_warning.assert_called()
        # The warning key should be soil-related
        args = mock_status_manager.set_warning.call_args
        assert "soil" in args[0][0].lower()
        assert args[0][1] is True

    def test_above_threshold_clears_warning(self, soil_logger, fake_adc, mock_status_manager):
        soil_logger.status_manager = mock_status_manager
        fake_adc.value_u16 = _raw10_to_u16(400)  # wet → high percent → no warning
        self._run(soil_logger._poll_once())
        # Most recent set_warning call should set False
        mock_status_manager.set_warning.assert_called()
        args = mock_status_manager.set_warning.call_args
        assert args[0][1] is False

    def test_no_status_manager_does_not_crash(self, soil_logger, fake_adc):
        soil_logger.status_manager = None
        fake_adc.value_u16 = _raw10_to_u16(800)
        # Should complete without raising
        self._run(soil_logger._poll_once())


class TestLogLoop:
    def test_log_loop_runs_until_cancelled(self, soil_logger, fake_adc):
        fake_adc.value_u16 = _raw10_to_u16(500)

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
    def test_filename_includes_date(self, soil_logger):
        assert soil_logger.filename.startswith("/sd/soil_log_")
        assert soil_logger.filename.endswith(".csv")
        assert "2026-01-29" in soil_logger.filename


class TestGetState:
    def test_get_state_includes_percent_and_raw(self, soil_logger, fake_adc):
        fake_adc.value_u16 = _raw10_to_u16(600)
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(soil_logger._poll_once())
        state = soil_logger.get_state()
        assert state["last_percent"] == 50
        assert state["last_raw"] == 600
        assert state["warn_pct_below"] == 20


class TestPrintRaw:
    """REPL calibration helper: prints a single raw 10-bit ADC value."""

    def test_print_raw_emits_int_in_0_1023(self, capsys):
        from lib import soil_logger as sl_mod

        fake_machine = MagicMock()
        fake_adc = FakeADC(value_u16=_raw10_to_u16(742))
        fake_pin = Mock()
        fake_machine.ADC = Mock(return_value=fake_adc)
        fake_machine.Pin = Mock(return_value=fake_pin)
        with patch.object(sl_mod, "machine", fake_machine, create=True):
            sl_mod.print_raw(pin=28)
        captured = capsys.readouterr()
        assert "742" in captured.out

    def test_print_raw_without_machine_raises(self):
        from lib import soil_logger as sl_mod

        with patch.object(sl_mod, "machine", None, create=True):
            with pytest.raises(RuntimeError, match="machine module"):
                sl_mod.print_raw()


class TestU16Helpers:
    """Cover _u16_to_raw10 clamp paths."""

    def test_u16_below_zero_clamps_to_zero(self):
        from lib.soil_logger import _u16_to_raw10

        assert _u16_to_raw10(-1) == 0

    def test_u16_above_max_clamps_to_raw10_max(self):
        from lib.soil_logger import _u16_to_raw10

        assert _u16_to_raw10(99999) == 1023


class TestInitValidation:
    def test_bad_endpoints_raise(self, time_provider, buffer_manager, mock_event_logger, fake_adc):
        from lib.soil_logger import SoilLogger

        with pytest.raises(ValueError, match="adc_dry_raw"):
            SoilLogger(
                adc=fake_adc,
                time_provider=time_provider,
                buffer_manager=buffer_manager,
                logger=mock_event_logger,
                adc_dry_raw=300,
                adc_wet_raw=400,
            )


class TestErrorPaths:
    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_adc_read_failure_logs_error(self, soil_logger, fake_adc, mock_event_logger):
        fake_adc.read_u16 = lambda: (_ for _ in ()).throw(OSError("adc dead"))
        self._run(soil_logger._poll_once())
        assert soil_logger.read_failures == 1
        assert mock_event_logger.error.called

    def test_write_failure_logs_error(self, soil_logger, fake_adc, buffer_manager, mock_event_logger):
        fake_adc.value_u16 = _raw10_to_u16(600)
        with patch.object(buffer_manager, "write", side_effect=OSError("sd dead")):
            self._run(soil_logger._poll_once())
        assert soil_logger.write_failures == 1

    def test_write_queue_path_used_when_supplied(self, soil_logger, fake_adc):
        from unittest.mock import Mock as _Mock

        wq = _Mock()
        soil_logger.write_queue = wq
        fake_adc.value_u16 = _raw10_to_u16(500)
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

    def test_recovery_clears_warning(self, soil_logger, fake_adc, mock_status_manager):
        """Once warning is active, recovering above threshold clears it (warning recovered branch)."""
        soil_logger.status_manager = mock_status_manager
        # Below threshold: warning ON
        fake_adc.value_u16 = _raw10_to_u16(800)
        self._run(soil_logger._poll_once())
        assert soil_logger._warn_active is True
        # Above threshold: warning OFF (recovery branch)
        fake_adc.value_u16 = _raw10_to_u16(400)
        self._run(soil_logger._poll_once())
        assert soil_logger._warn_active is False
        # info recovery message logged
        info_msgs = " ".join(str(c) for c in soil_logger.logger.info.call_args_list)
        assert "recovered" in info_msgs

    def test_log_loop_unexpected_error_continues(self, soil_logger, mock_event_logger):
        with patch.object(soil_logger, "_poll_once", side_effect=[RuntimeError("boom"), None]):
            with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):
                with pytest.raises(asyncio.CancelledError):
                    with patch("time.localtime", return_value=FAKE_LOCALTIME):
                        asyncio.run(soil_logger.log_loop())
        assert mock_event_logger.error.called
