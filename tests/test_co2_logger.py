# Tests for lib/co2_logger.py
# Covers CO2Logger: SenseAir-style 7-byte frame parse, async poll loop,
# BufferManager plumbing, hysteresis-driven override flag.

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import FAKE_LOCALTIME


@pytest.fixture
def fake_uart():
    """A MagicMock UART that captures writes and replays canned read frames."""
    u = MagicMock()
    u._writes = []
    u._rx = bytearray()

    def _write(buf):
        u._writes.append(bytes(buf))
        return len(buf)

    def _any():
        return len(u._rx)

    def _read(n=None):
        if not u._rx:
            return None
        if n is None or n >= len(u._rx):
            data = bytes(u._rx)
            u._rx.clear()
            return data
        data = bytes(u._rx[:n])
        del u._rx[:n]
        return data

    def _flush():
        u._rx.clear()

    u.write = MagicMock(side_effect=_write)
    u.any = MagicMock(side_effect=_any)
    u.read = MagicMock(side_effect=_read)
    u.flush = MagicMock(side_effect=_flush)

    def _inject(frame: bytes) -> None:
        u._rx.extend(frame)

    u.inject = _inject
    return u


@pytest.fixture
def co2_logger(time_provider, buffer_manager, mock_event_logger, fake_uart):
    """CO2Logger with mocked UART and real BufferManager (tmp_path SD)."""
    from lib.co2_logger import CO2Logger

    return CO2Logger(
        uart=fake_uart,
        time_provider=time_provider,
        buffer_manager=buffer_manager,
        logger=mock_event_logger,
        interval_s=30,
        warmup_s=30,
        max_retries=3,
        override_ppm_on=1000,
        override_ppm_off=800,
        filename_base="co2_log",
    )


def _frame(ppm: int) -> bytes:
    """Build a synthetic 7-byte SenseAir-style reply with ppm at bytes [3:5]."""
    hi = (ppm >> 8) & 0xFF
    lo = ppm & 0xFF
    return bytes([0xFE, 0x44, 0x02, hi, lo, 0x00, 0x00])


class TestFrameParse:
    def test_parse_valid_frame(self):
        from lib.co2_logger import parse_frame

        assert parse_frame(_frame(450)) == 450
        assert parse_frame(_frame(1500)) == 1500
        assert parse_frame(_frame(0)) == 0

    def test_parse_none_returns_none(self):
        from lib.co2_logger import parse_frame

        assert parse_frame(None) is None

    def test_parse_short_frame_returns_none(self):
        from lib.co2_logger import parse_frame

        # Less than 5 bytes can't carry ppm at index 3/4
        assert parse_frame(b"\xfe\x44\x02\x01") is None
        assert parse_frame(b"") is None

    def test_parse_out_of_range_returns_none(self):
        from lib.co2_logger import parse_frame

        # 0xFFFF = 65535 is well outside any plausible CO2 reading
        assert parse_frame(_frame(50000)) is None


class TestOverrideHysteresis:
    def test_below_on_threshold_no_override(self, co2_logger):
        co2_logger._update_override(800)
        assert co2_logger.is_override_active() is False
        co2_logger._update_override(999)
        assert co2_logger.is_override_active() is False

    def test_at_on_threshold_activates(self, co2_logger):
        co2_logger._update_override(1000)
        assert co2_logger.is_override_active() is True

    def test_holds_in_hysteresis_band(self, co2_logger):
        """Once active, override stays on until ppm drops below off-threshold."""
        co2_logger._update_override(1100)
        assert co2_logger.is_override_active() is True
        # In hysteresis band [800, 1000) — should stay on
        co2_logger._update_override(950)
        assert co2_logger.is_override_active() is True
        co2_logger._update_override(800)
        assert co2_logger.is_override_active() is True

    def test_drops_below_off_threshold_releases(self, co2_logger):
        co2_logger._update_override(1100)
        co2_logger._update_override(799)
        assert co2_logger.is_override_active() is False

    def test_callable_returns_bool(self, co2_logger):
        """is_override_active() is a plain method — FanController calls it bool-like."""
        assert co2_logger.is_override_active() is False
        co2_logger._update_override(1500)
        assert co2_logger.is_override_active() is True


class TestPollOnce:
    """Single-iteration tests for the async poll path."""

    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_successful_poll_caches_ppm(self, co2_logger, fake_uart):
        fake_uart.inject(_frame(650))
        self._run(co2_logger._poll_once())
        assert co2_logger.last_ppm == 650

    def test_successful_poll_sends_request(self, co2_logger, fake_uart):
        fake_uart.inject(_frame(450))
        self._run(co2_logger._poll_once())
        # SenseAir read-holding-register request, byte-for-byte
        assert fake_uart._writes[-1] == b"\xfe\x44\x00\x08\x02\x9f\x25"

    def test_no_response_keeps_last_ppm_none(self, co2_logger, fake_uart):
        # No frame injected → poll fails, no ppm captured
        self._run(co2_logger._poll_once())
        assert co2_logger.last_ppm is None

    def test_invalid_frame_does_not_corrupt_last_ppm(self, co2_logger, fake_uart):
        # Prime a known good reading
        fake_uart.inject(_frame(500))
        self._run(co2_logger._poll_once())
        assert co2_logger.last_ppm == 500
        # Now an invalid frame
        fake_uart.inject(b"\x00\x00")
        self._run(co2_logger._poll_once())
        # last_ppm should hold the previous good value, not get clobbered
        assert co2_logger.last_ppm == 500

    def test_successful_poll_writes_csv_row(self, co2_logger, fake_uart, buffer_manager):
        fake_uart.inject(_frame(723))
        self._run(co2_logger._poll_once())
        # Verify a row landed somewhere via the buffer manager
        # (real BufferManager backed by tmp_path)
        from pathlib import Path

        sd_files = list(Path(buffer_manager.sd_mount_point).glob("co2_log_*.csv"))
        assert len(sd_files) == 1
        content = sd_files[0].read_text()
        assert "723" in content

    def test_poll_updates_override_flag(self, co2_logger, fake_uart):
        fake_uart.inject(_frame(1500))
        self._run(co2_logger._poll_once())
        assert co2_logger.is_override_active() is True


class TestLogLoop:
    """Smoke-test the outer async loop via patched asyncio.sleep."""

    def test_log_loop_runs_until_cancelled(self, co2_logger, fake_uart):
        fake_uart.inject(_frame(600))

        async def runner():
            with patch("asyncio.sleep", side_effect=RuntimeError("stop")):
                try:
                    await co2_logger.log_loop()
                except RuntimeError:
                    pass

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(runner())
        assert co2_logger.last_ppm == 600

    def test_cancelled_error_propagates(self, co2_logger):
        async def runner():
            with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await co2_logger.log_loop()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(runner())

    def test_warmup_window_swallows_initial_failures(self, co2_logger, mock_event_logger):
        """During warmup, missed reads log as debug, not warning/error."""
        # No frame injected — poll will find no data
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(co2_logger._poll_once())
        # No warning/error expected while in warmup window
        assert mock_event_logger.warning.call_count == 0
        assert mock_event_logger.error.call_count == 0

    def test_after_warmup_failure_logs_warning(self, co2_logger, mock_event_logger):
        """Past the warmup window, a missed read escalates to warning."""
        # Force out-of-warmup by backdating _started_ms
        co2_logger._started_ms -= (co2_logger.warmup_s + 1) * 1000
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(co2_logger._poll_once())
        assert mock_event_logger.warning.call_count >= 1


class TestFilenameRollover:
    def test_filename_includes_date(self, co2_logger):
        assert co2_logger.filename.startswith("/sd/co2_log_")
        assert co2_logger.filename.endswith(".csv")
        # Date from FAKE_LOCALTIME (2026-01-29)
        assert "2026-01-29" in co2_logger.filename


class TestGetState:
    def test_get_state_includes_ppm_and_override(self, co2_logger, fake_uart):
        fake_uart.inject(_frame(850))

        async def runner():
            await co2_logger._poll_once()

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(runner())

        state = co2_logger.get_state()
        assert state["last_ppm"] == 850
        assert state["override_active"] is False
        assert state["override_ppm_on"] == 1000
        assert state["override_ppm_off"] == 800
