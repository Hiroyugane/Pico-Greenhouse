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
