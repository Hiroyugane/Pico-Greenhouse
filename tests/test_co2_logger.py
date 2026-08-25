# Tests for lib/co2_logger.py
# Covers CO2Logger: SenseAir-style 7-byte frame parse, async poll loop,
# BufferManager plumbing, hysteresis-driven override flag.

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import FAKE_LOCALTIME


@pytest.fixture
def fake_uart():
    """A MagicMock UART that captures writes and replays canned read frames.

    ``inject()`` ARMS a reply rather than putting bytes straight into RX: the
    real sensor only speaks when polled, so a frame must not be readable before
    the request goes out. The logger drains RX before each request precisely
    because leftover bytes desynchronise the next read, and a fixture that
    pre-filled RX would make that drain look like a bug.

    Use ``preload()`` for the opposite case — bytes genuinely left over from an
    earlier exchange, which the drain is supposed to discard.
    """
    u = MagicMock()
    u._writes = []
    u._rx = bytearray()
    u._pending = bytearray()

    def _write(buf):
        u._writes.append(bytes(buf))
        if u._pending:
            u._rx.extend(u._pending)
            u._pending = bytearray()
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
        """Arm the sensor's reply to the next request."""
        u._pending.extend(frame)

    def _preload(data: bytes) -> None:
        """Put bytes in RX as if left over from an earlier exchange."""
        u._rx.extend(data)

    u.inject = _inject
    u.preload = _preload
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
        sensor_root="/sd/sensors",
        sensor_type="co2",
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

        sd_files = list(Path(buffer_manager.sd_mount_point).rglob("co2_*.csv"))
        assert len(sd_files) == 1
        assert sd_files[0].parent.parent.name == "co2"
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

    def test_after_warmup_failure_escalates_once_on_the_outage_edge(self, co2_logger, mock_event_logger):
        """Past the warmup window, a persistent miss escalates — but only once.

        This used to warn on EVERY missed read, which is how one dead sensor
        wrote 20 533 warning lines in a 7.2-day run.
        """
        # Force out-of-warmup by backdating _started_ms
        co2_logger._started_ms -= (co2_logger.warmup_s + 1) * 1000
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            for _ in range(10):
                asyncio.run(co2_logger._poll_once())
        assert mock_event_logger.warning.call_count == 1
        assert co2_logger.health.is_unreachable() is True


class TestFilenameRollover:
    def test_filename_includes_date_under_sensor_tree(self, co2_logger):
        assert co2_logger.filename == "/sd/sensors/co2/2026/co2_2026-01-29.csv"


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


class TestErrorPaths:
    """Cover the failure branches that log errors but keep the loop alive."""

    def _run(self, coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_update_override_none_is_noop(self, co2_logger):
        # parse_frame returning None hits this branch
        assert co2_logger.is_override_active() is False
        co2_logger._update_override(None)
        assert co2_logger.is_override_active() is False

    def test_uart_write_failure_increments_read_failures(self, co2_logger, fake_uart, mock_event_logger):
        fake_uart.write = MagicMock(side_effect=OSError("uart down"))
        self._run(co2_logger._poll_once())
        assert co2_logger.read_failures >= 1
        assert mock_event_logger.error.called

    def test_uart_read_attempt_exception_is_logged_as_debug(self, co2_logger, fake_uart, mock_event_logger):
        """Mid-retry exceptions are swallowed and logged at debug level."""

        def _raising_any():
            raise OSError("intermittent")

        fake_uart.any = MagicMock(side_effect=_raising_any)
        self._run(co2_logger._poll_once())
        # No frame ever came back → read_failures bumped
        assert co2_logger.read_failures >= 1
        # And at least one debug log fired for the failed attempt
        assert mock_event_logger.debug.called

    def test_write_failure_increments_write_failures(self, co2_logger, fake_uart, buffer_manager, mock_event_logger):
        fake_uart.inject(_frame(700))
        with patch.object(buffer_manager, "write", side_effect=OSError("sd dead")):
            self._run(co2_logger._poll_once())
        assert co2_logger.write_failures >= 1
        assert mock_event_logger.error.called

    def test_write_queue_path_used_when_supplied(self, co2_logger, fake_uart):
        from unittest.mock import Mock as _Mock

        wq = _Mock()
        co2_logger.write_queue = wq
        fake_uart.inject(_frame(620))
        self._run(co2_logger._poll_once())
        wq.enqueue_write.assert_called_once()

    def test_date_changed_exception_logged(self, co2_logger, mock_event_logger):
        """now_date_tuple raising in _check_date_changed is caught and logged."""
        with patch.object(co2_logger.time_provider, "now_date_tuple", side_effect=OSError("rtc")):
            co2_logger._check_date_changed()
        assert mock_event_logger.error.called

    def test_header_write_exception_logged(self, co2_logger, buffer_manager, mock_event_logger):
        """Header write failure is logged via error()."""
        with patch.object(buffer_manager, "has_data_for", return_value=False):
            with patch.object(buffer_manager, "write", side_effect=OSError("sd dead")):
                co2_logger._ensure_header()
        assert mock_event_logger.error.called

    def test_log_loop_unexpected_error_then_cancel(self, co2_logger, mock_event_logger):
        """An unexpected exception inside the loop body is logged at error level."""
        call_count = {"n": 0}

        async def _flaky(_):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("boom")
            raise asyncio.CancelledError

        async def runner():
            with patch("asyncio.sleep", _flaky):
                with patch.object(co2_logger, "_poll_once", return_value=None):
                    with pytest.raises(asyncio.CancelledError):
                        await co2_logger.log_loop()

        # Make _poll_once raise unexpectedly
        with patch.object(co2_logger, "_poll_once", side_effect=[RuntimeError("boom"), None]):
            with patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):
                with pytest.raises(asyncio.CancelledError):
                    with patch("time.localtime", return_value=FAKE_LOCALTIME):
                        asyncio.run(co2_logger.log_loop())
        assert mock_event_logger.error.called


def _crc_frame(ppm: int) -> bytes:
    """Build a 7-byte reply with a CORRECT Modbus CRC, as the real sensor sends."""
    from lib.co2_logger import crc16

    body = bytes([0xFE, 0x44, 0x02, (ppm >> 8) & 0xFF, ppm & 0xFF])
    crc = crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class TestFrameIntegrity:
    """Checksum + window. The field run fed 8320/9470 ppm straight to the fans."""

    def test_crc_frame_accepted(self):
        from lib.co2_logger import parse_frame

        assert parse_frame(_crc_frame(742), verify_checksum=True) == 742

    def test_bad_crc_rejected(self):
        from lib.co2_logger import parse_frame

        bad = bytearray(_crc_frame(742))
        bad[5] ^= 0xFF  # corrupt the checksum
        assert parse_frame(bytes(bad), verify_checksum=True) is None

    def test_wrong_header_rejected(self):
        """A misaligned read starts mid-frame — the header is what catches it."""
        from lib.co2_logger import parse_frame

        bad = bytearray(_crc_frame(742))
        bad[0] = 0x00
        assert parse_frame(bytes(bad), verify_checksum=True) is None

    def test_short_frame_rejected_under_checksum(self):
        from lib.co2_logger import parse_frame

        assert parse_frame(_crc_frame(742)[:6], verify_checksum=True) is None

    def test_field_observed_values_are_rejected_by_the_window(self):
        """9470 and 2 ppm both parsed cleanly before the window existed."""
        from lib.co2_logger import parse_frame

        for ppm in (0, 2, 5, 48, 8320, 8903, 9470):
            assert parse_frame(_frame(ppm), min_ppm=300, max_ppm=5000) is None

    def test_window_admits_the_real_operating_range(self):
        from lib.co2_logger import parse_frame

        for ppm in (420, 600, 1300, 2000, 4999):
            assert parse_frame(_frame(ppm), min_ppm=300, max_ppm=5000) == ppm

    def test_checksum_catches_what_the_window_cannot(self):
        """The point of the checksum: a corrupt frame can look perfectly plausible."""
        from lib.co2_logger import parse_frame

        plausible_but_corrupt = bytes([0xFE, 0x44, 0x02, 0x02, 0xBC, 0x00, 0x00])  # 700 ppm, bad CRC
        assert parse_frame(plausible_but_corrupt, min_ppm=300, max_ppm=5000) == 700
        assert parse_frame(plausible_but_corrupt, min_ppm=300, max_ppm=5000, verify_checksum=True) is None


class TestStaleReading:
    """A dead sensor must stop offering its last value to the regulation engine."""

    @staticmethod
    def _logger(time_provider, buffer_manager, mock_event_logger, fake_uart, **kw):
        from lib.co2_logger import CO2Logger

        return CO2Logger(
            uart=fake_uart,
            time_provider=time_provider,
            buffer_manager=buffer_manager,
            logger=mock_event_logger,
            sensor_root="/sd/sensors",
            sensor_type="co2",
            **kw,
        )

    def test_reading_expires_after_the_timeout(self, time_provider, buffer_manager, mock_event_logger, fake_uart):
        import lib.co2_logger as mod

        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart, stale_after_s=300)
        now = [1_000_000]
        original = mod._ticks_ms
        mod._ticks_ms = lambda: now[0]
        try:
            log.last_ppm = 1159
            assert log.last_ppm == 1159
            now[0] += 299 * 1000
            assert log.last_ppm == 1159  # still fresh
            now[0] += 2 * 1000
            assert log.last_ppm is None  # aged out
            assert log.is_stale() is True
        finally:
            mod._ticks_ms = original

    def test_timeout_zero_never_expires(self, time_provider, buffer_manager, mock_event_logger, fake_uart):
        import lib.co2_logger as mod

        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart, stale_after_s=0)
        now = [1_000_000]
        original = mod._ticks_ms
        mod._ticks_ms = lambda: now[0]
        try:
            log.last_ppm = 1159
            now[0] += 10_000 * 1000
            assert log.last_ppm == 1159
            assert log.is_stale() is False
        finally:
            mod._ticks_ms = original

    def test_stale_raises_and_clears_the_operator_warning(
        self, time_provider, buffer_manager, mock_event_logger, fake_uart
    ):
        import lib.co2_logger as mod

        status = MagicMock()
        log = self._logger(
            time_provider,
            buffer_manager,
            mock_event_logger,
            fake_uart,
            stale_after_s=300,
            status_manager=status,
        )
        now = [1_000_000]
        original = mod._ticks_ms
        mod._ticks_ms = lambda: now[0]
        try:
            log.last_ppm = 700
            now[0] += 301 * 1000
            log._update_stale_alert()
            status.set_warning.assert_called_with("co2_stale", True)
            log.last_ppm = 700  # sensor comes back
            log._update_stale_alert()
            status.set_warning.assert_called_with("co2_stale", False)
        finally:
            mod._ticks_ms = original


class TestUnreachableReporting:
    """One dead sensor must cost one WARN line, not one per poll.

    The 2026-07-31..08-07 field run logged 20 533 CO2 warnings — 100 % of every
    warning the system emitted — from this single code path.
    """

    @staticmethod
    def _logger(time_provider, buffer_manager, mock_event_logger, fake_uart, **kw):
        from lib.co2_logger import CO2Logger

        params = {
            "warmup_s": 0,  # warm-up misses are deliberately exempt
            "interval_s": 30,
            "warn_after_failures": 3,
            "backoff_start_s": 60,
            "backoff_max_s": 300,
        }
        params.update(kw)
        return CO2Logger(
            uart=fake_uart,
            time_provider=time_provider,
            buffer_manager=buffer_manager,
            logger=mock_event_logger,
            sensor_root="/sd/sensors",
            sensor_type="co2",
            **params,
        )

    @staticmethod
    def _run(coro):
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            return asyncio.run(coro)

    def test_repeated_failures_warn_once(self, time_provider, buffer_manager, mock_event_logger, fake_uart):
        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart)
        for _ in range(50):
            self._run(log._poll_once())

        warn_texts = [c.args[1] for c in mock_event_logger.warning.call_args_list]
        unreachable = [t for t in warn_texts if "unreachable" in t]
        assert len(unreachable) == 1
        assert "3 failed reads" in unreachable[0]
        assert "60s" in unreachable[0]
        assert log.read_failures == 50  # the existing counter still counts them all

    def test_the_edge_warning_names_the_last_failure_cause(
        self, time_provider, buffer_manager, mock_event_logger, fake_uart
    ):
        """Nothing raises on this path, so the cause has to be spelled out."""
        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart)
        for _ in range(3):
            self._run(log._poll_once())
        unreachable = [c.args[1] for c in mock_event_logger.warning.call_args_list if "unreachable" in c.args[1]]
        assert len(unreachable) == 1
        assert "no reply frame" in unreachable[0]

    def test_early_failures_stay_at_debug(self, time_provider, buffer_manager, mock_event_logger, fake_uart):
        """Two missed reads are a blip, not an outage."""
        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart)
        self._run(log._poll_once())
        self._run(log._poll_once())
        assert mock_event_logger.warning.call_count == 0
        assert log.health.is_unreachable() is False

    def test_warmup_failures_do_not_start_an_outage(self, time_provider, buffer_manager, mock_event_logger, fake_uart):
        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart, warmup_s=300)
        for _ in range(10):
            self._run(log._poll_once())
        assert mock_event_logger.warning.call_count == 0
        assert log.health.consecutive_failures == 0

    def test_unreachable_raises_one_status_warning(self, time_provider, buffer_manager, mock_event_logger, fake_uart):
        status = MagicMock()
        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart, status_manager=status)
        for _ in range(20):
            self._run(log._poll_once())

        calls = [c.args for c in status.set_warning.call_args_list if c.args[0] == "co2_unreachable"]
        assert calls == [("co2_unreachable", True)]

    def test_recovery_logs_one_info_and_clears_the_warning(
        self, time_provider, buffer_manager, mock_event_logger, fake_uart
    ):
        status = MagicMock()
        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart, status_manager=status)
        for _ in range(5):
            self._run(log._poll_once())
        fake_uart.inject(_frame(640))
        self._run(log._poll_once())

        info_texts = [c.args[1] for c in mock_event_logger.info.call_args_list]
        recovered = [t for t in info_texts if "recovered" in t]
        assert len(recovered) == 1
        assert "5 failed reads total" in recovered[0]
        assert [c.args for c in status.set_warning.call_args_list if c.args[0] == "co2_unreachable"] == [
            ("co2_unreachable", True),
            ("co2_unreachable", False),
        ]
        assert log.last_ppm == 640

    def test_polling_backs_off_while_unreachable(self, time_provider, buffer_manager, mock_event_logger, fake_uart):
        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart)
        assert log.health.interval_s() == 30
        for _ in range(3):
            self._run(log._poll_once())
        assert log.health.interval_s() == 60
        self._run(log._poll_once())
        assert log.health.interval_s() == 120

    def test_success_snaps_the_interval_back(self, time_provider, buffer_manager, mock_event_logger, fake_uart):
        log = self._logger(time_provider, buffer_manager, mock_event_logger, fake_uart)
        for _ in range(6):
            self._run(log._poll_once())
        assert log.health.interval_s() > 30
        fake_uart.inject(_frame(700))
        self._run(log._poll_once())
        assert log.health.interval_s() == 30


class TestRxDrain:
    """Leftover RX bytes desynchronise the next read — drain before requesting."""

    def test_stale_rx_bytes_are_discarded_before_the_request(self, co2_logger, fake_uart):
        fake_uart.preload(b"\x02\xbc\x00")  # tail of a previous reply
        fake_uart.inject(_frame(640))
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            asyncio.run(co2_logger._poll_once())
        assert co2_logger.last_ppm == 640

    def test_without_the_drain_the_read_would_desynchronise(self, co2_logger, fake_uart):
        """Shows what the drain prevents: leftover bytes shift the ppm word.

        Reading 7 bytes from [leftover(3) + reply(7)] yields a frame whose
        bytes [3:5] are not the ppm word at all — which is how a healthy sensor
        reports 8320 ppm.
        """
        fake_uart.preload(b"\x02\xbc\x00")
        fake_uart.inject(_frame(640))
        fake_uart.write(b"")  # deliver the reply without draining first
        misaligned = fake_uart.read(7)
        from lib.co2_logger import parse_frame

        assert parse_frame(misaligned) != 640
