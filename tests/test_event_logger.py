# Tests for lib/event_logger.py
# Covers info/warning/error logging, flush thresholds, rotation, error paths,
# debug level, level gating, and _format helper.

from unittest.mock import Mock, patch

from tests.conftest import FAKE_LOCALTIME


class TestEventLoggerBasic:
    """Basic logging tests for INFO, WARN, ERR levels."""

    def test_info_logs_to_console(self, event_logger, capsys):
        """info() prints to console with [INFO] tag."""
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            event_logger.info("TEST", "Test message")
        captured = capsys.readouterr()
        assert "[INFO]" in captured.out
        assert "TEST" in captured.out
        assert "Test message" in captured.out

    def test_warning_logs_to_console(self, event_logger, capsys):
        """warning() prints to console with [WARN] tag."""
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            event_logger.warning("TEST", "Warning message")
        captured = capsys.readouterr()
        assert "[WARN]" in captured.out

    def test_error_logs_to_console(self, event_logger, capsys):
        """error() prints to console with [ERR] tag."""
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            event_logger.error("TEST", "Error message")
        captured = capsys.readouterr()
        assert "[ERR]" in captured.out

    def test_timestamp_in_log_entry(self, event_logger, capsys):
        """Log entries include timestamp from TimeProvider."""
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            event_logger.info("TEST", "Timestamped")
        captured = capsys.readouterr()
        assert "2026" in captured.out


class TestEventLoggerFlush:
    """Tests for flush behavior and thresholds."""

    def test_info_flushes_at_5(self, time_provider, buffer_manager):
        """5 info messages trigger a flush."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log")
            for i in range(4):
                logger.info("T", f"msg{i}")
            assert logger.flush_count == 0
            logger.info("T", "msg4")
            assert logger.flush_count == 1

    def test_warning_flushes_at_3(self, time_provider, buffer_manager):
        """3 warnings trigger a flush."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log")
            logger.warning("T", "1")
            logger.warning("T", "2")
            assert logger.flush_count == 0
            logger.warning("T", "3")
            assert logger.flush_count == 1

    def test_error_flushes_immediately(self, time_provider, buffer_manager):
        """Error messages trigger immediate flush."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log")
            logger.error("T", "critical")
            assert logger.flush_count == 1

    def test_flush_with_none_buffer_manager(self, time_provider):
        """flush() with buffer_manager=None clears buffer without error."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, None, logfile="/sd/test.log")
            logger.buffer = ["entry1\n", "entry2\n"]
            logger.flush()
        assert logger.buffer == []

    def test_flush_writes_to_buffer_manager(self, time_provider, buffer_manager, tmp_path):
        """flush() writes all buffered entries via buffer_manager.write()."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/system.log")
            logger.buffer = ["[2026] line1\n", "[2026] line2\n"]
            logger.flush()
        # Check file was created in tmp_path
        content = (tmp_path / "sd" / "system.log").read_text()
        assert "line1" in content
        assert "line2" in content

    def test_flush_count_increments(self, time_provider, buffer_manager):
        """Each successful flush increments flush_count."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log")
            logger.buffer = ["entry\n"]
            logger.flush()
            logger.buffer = ["entry2\n"]
            logger.flush()
        assert logger.flush_count == 2

    def test_flush_clears_buffer_on_error(self, time_provider):
        """flush() clears buffer even when write fails."""
        from lib.event_logger import EventLogger

        mock_bm = Mock()
        mock_bm.write = Mock(side_effect=OSError("disk fail"))
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, mock_bm, logfile="/sd/test.log")
            logger.buffer = ["entry\n"]
            logger.flush()
        assert logger.buffer == []


class TestEventLoggerTimestamp:
    """Tests for _get_timestamp error handling."""

    def test_get_timestamp_returns_string(self, event_logger):
        """_get_timestamp returns a string timestamp."""
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            ts = event_logger._get_timestamp()
        assert isinstance(ts, str)
        assert "TIME_ERROR" not in ts

    def test_get_timestamp_error_returns_TIME_ERROR(self, time_provider, buffer_manager):
        """When TimeProvider raises, _get_timestamp returns 'TIME_ERROR'."""
        from lib.event_logger import EventLogger

        mock_tp = Mock()
        mock_tp.now_timestamp = Mock(side_effect=Exception("fail"))
        logger = EventLogger(mock_tp, buffer_manager, logfile="/sd/test.log")
        assert logger._get_timestamp() == "TIME_ERROR"


class TestEventLoggerRotation:
    """Tests for log rotation (check_size)."""

    def test_check_size_rotates_when_over_limit(self, time_provider, buffer_manager, tmp_path):
        """check_size() renames log when _log_size > max_size."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/system.log", max_size=100)
            # Create the actual log file
            (tmp_path / "sd" / "system.log").write_text("x" * 200)
            logger._log_size = 200
            logger.check_size()
        assert logger._log_size == 0

    def test_check_size_no_rotation_under_limit(self, event_logger):
        """check_size() does nothing when _log_size < max_size."""
        event_logger._log_size = 50
        original_size = event_logger._log_size
        event_logger.check_size()
        assert event_logger._log_size == original_size

    def test_check_size_rename_failure_resets_counter(self, time_provider, buffer_manager):
        """If rename fails, _log_size IS zeroed to suppress retry spam until SD recovers."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/system.log", max_size=100)
            logger._log_size = 200
            # rename will fail since file doesn't exist — counter must be zeroed to avoid
            # hammering the SD with rename attempts every cycle while it is unavailable.
            logger.check_size()
        assert logger._log_size == 0

    def test_check_size_uses_debug_max_size_when_debug_to_file(self, time_provider, buffer_manager, tmp_path):
        """When debug_to_file=True, debug_max_size is the rotation threshold, not max_size."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider,
                buffer_manager,
                logfile="/sd/system.log",
                max_size=50000,
                debug_max_size=100,
                debug_to_file=True,
            )
            (tmp_path / "sd" / "system.log").write_text("x" * 200)
            logger._log_size = 200  # above debug_max_size=100, below max_size=50000
            logger.check_size()
        # Rotation should have fired (debug_max_size used) and counter reset
        assert logger._log_size == 0

    def test_check_size_uses_max_size_when_not_debug_to_file(self, time_provider, buffer_manager, tmp_path):
        """When debug_to_file=False, max_size is the threshold regardless of debug_max_size."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider,
                buffer_manager,
                logfile="/sd/system.log",
                max_size=50000,
                debug_max_size=100,
                debug_to_file=False,
            )
            logger._log_size = 200  # above debug_max_size=100, below max_size=50000
            logger.check_size()
        # Rotation must NOT have fired (max_size=50000 not exceeded)
        assert logger._log_size != 0


class TestEventLoggerStripPrefix:
    """Tests for _strip_sd_prefix static method."""

    def test_strip_sd_prefix_removes_prefix(self):
        """'/sd/system.log' → 'system.log'."""
        from lib.event_logger import EventLogger

        assert EventLogger._strip_sd_prefix("/sd/system.log") == "system.log"

    def test_strip_sd_prefix_no_prefix(self):
        """'system.log' → 'system.log' (unchanged)."""
        from lib.event_logger import EventLogger

        assert EventLogger._strip_sd_prefix("system.log") == "system.log"


class TestEventLoggerDebug:
    """Tests for debug() method and debug_enabled/debug_to_file config."""

    def test_debug_disabled_no_output(self, time_provider, buffer_manager, capsys):
        """When debug_enabled=False, debug() produces no output."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", debug_enabled=False)
            capsys.readouterr()  # clear init output
            logger.debug("TEST", "should not appear")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_debug_disabled_no_buffer(self, time_provider, buffer_manager):
        """When debug_enabled=False, debug() doesn't add to buffer."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", debug_enabled=False)
            logger.buffer.clear()
            logger.debug("TEST", "should not buffer")
        assert len(logger.buffer) == 0

    def test_debug_enabled_prints_to_console(self, time_provider, buffer_manager, capsys):
        """When debug_enabled=True, debug() prints [DEBUG] to console."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", debug_enabled=True)
            capsys.readouterr()  # clear init output
            logger.debug("TEST", "debug message")
        captured = capsys.readouterr()
        assert "[DEBUG]" in captured.out
        assert "[TEST]" in captured.out
        assert "debug message" in captured.out

    def test_debug_enabled_no_file_by_default(self, time_provider, buffer_manager):
        """When debug_enabled=True but debug_to_file=False, debug() doesn't buffer."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider, buffer_manager, logfile="/sd/test.log", debug_enabled=True, debug_to_file=False
            )
            logger.buffer.clear()
            logger.debug("TEST", "console only")
        assert len(logger.buffer) == 0

    def test_debug_to_file_buffers_entry(self, time_provider, buffer_manager):
        """When debug_to_file=True, debug entries are added to buffer."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider, buffer_manager, logfile="/sd/test.log", debug_enabled=True, debug_to_file=True
            )
            logger.buffer.clear()
            logger.debug("TEST", "file debug")
        assert len(logger.buffer) == 1
        assert "[DEBUG]" in logger.buffer[0]

    def test_debug_with_structured_fields(self, time_provider, buffer_manager, capsys):
        """debug() with **fields appends key=value pairs after ' | '."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", debug_enabled=True)
            capsys.readouterr()
            logger.debug("FAN", "cycle tick", temp=23.5, state="ON")
        captured = capsys.readouterr()
        assert "| temp=23.5" in captured.out
        assert "state=ON" in captured.out

    def test_debug_without_fields_no_pipe(self, time_provider, buffer_manager, capsys):
        """debug() without fields does not include ' | ' separator."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", debug_enabled=True)
            capsys.readouterr()
            logger.debug("TEST", "no fields")
        captured = capsys.readouterr()
        assert " | " not in captured.out

    def test_debug_to_file_with_fields_in_buffer(self, time_provider, buffer_manager):
        """debug_to_file buffers structured field entries correctly."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider, buffer_manager, logfile="/sd/test.log", debug_enabled=True, debug_to_file=True
            )
            logger.buffer.clear()
            logger.debug("SENSOR", "read ok", temp=22.0, hum=65)
        assert len(logger.buffer) == 1
        assert "| temp=22.0 hum=65" in logger.buffer[0]

    def test_debug_to_file_flushes_at_threshold(self, time_provider, buffer_manager):
        """debug() triggers flush when buffer reaches debug_flush_threshold."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider,
                buffer_manager,
                logfile="/sd/test.log",
                debug_enabled=True,
                debug_to_file=True,
                debug_flush_threshold=3,
            )
            logger.buffer.clear()
            logger.debug("TEST", "entry 1")
            logger.debug("TEST", "entry 2")
            assert len(logger.buffer) == 2
            logger.debug("TEST", "entry 3")
            # Buffer should have been flushed (threshold=3)
            assert len(logger.buffer) == 0
            assert logger.flush_count >= 1

    def test_debug_to_file_no_flush_below_threshold(self, time_provider, buffer_manager):
        """debug() does not flush when buffer is below debug_flush_threshold."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider,
                buffer_manager,
                logfile="/sd/test.log",
                debug_enabled=True,
                debug_to_file=True,
                debug_flush_threshold=10,
            )
            logger.buffer.clear()
            initial_flush = logger.flush_count
            for i in range(5):
                logger.debug("TEST", f"entry {i}")
            assert len(logger.buffer) == 5
            assert logger.flush_count == initial_flush


class TestEventLoggerLevelGating:
    """Tests for log level gating."""

    def test_info_suppressed_at_warn_level(self, time_provider, buffer_manager, capsys):
        """info() is suppressed when log_level=WARN."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", log_level="WARN")
            logger.info("TEST", "should not appear")
        captured = capsys.readouterr()
        assert "should not appear" not in captured.out
        assert len(logger.buffer) == 0

    def test_warning_suppressed_at_err_level(self, time_provider, buffer_manager, capsys):
        """warning() is suppressed when log_level=ERR."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", log_level="ERR")
            logger.warning("TEST", "should not appear")
        captured = capsys.readouterr()
        assert "should not appear" not in captured.out

    def test_error_never_suppressed(self, time_provider, buffer_manager, capsys):
        """error() is never gated, even at ERR level."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", log_level="ERR")
            logger.error("TEST", "always visible")
        captured = capsys.readouterr()
        assert "always visible" in captured.out

    def test_debug_level_allows_all(self, time_provider, buffer_manager, capsys):
        """At DEBUG level, info/warning/error all pass through."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(time_provider, buffer_manager, logfile="/sd/test.log", log_level="DEBUG")
            logger.info("T", "info_msg")
            logger.warning("T", "warn_msg")
        captured = capsys.readouterr()
        assert "info_msg" in captured.out
        assert "warn_msg" in captured.out


class TestEventLoggerFormat:
    """Tests for the _format() shared helper."""

    def test_format_produces_consistent_output(self, event_logger):
        """_format() returns a consistent formatted string."""
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            result = event_logger._format("INFO", "MOD", "hello")
        assert "[INFO]" in result
        assert "[MOD]" in result
        assert "hello" in result
        assert result.endswith("\n")

    def test_format_with_debug_tag(self, event_logger):
        """_format() works with DEBUG tag."""
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            result = event_logger._format("DEBUG", "TEST", "dbg msg")
        assert "[DEBUG]" in result
        assert "[TEST]" in result


class TestEventLoggerStatusManager:
    """Tests for StatusManager integration in error()."""

    def test_error_sets_logged_error_on_status_manager(self, time_provider, buffer_manager):
        """error() calls status_manager.set_error('logged_error', True)."""
        from lib.event_logger import EventLogger

        mock_sm = Mock()
        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider,
                buffer_manager,
                logfile="/sd/test.log",
                status_manager=mock_sm,
            )
            logger.error("MOD", "something broke")
        mock_sm.set_error.assert_called_with("logged_error", True)

    def test_error_without_status_manager_no_crash(self, time_provider, buffer_manager):
        """error() works fine when status_manager is None."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider,
                buffer_manager,
                logfile="/sd/test.log",
                status_manager=None,
            )
            logger.error("MOD", "something broke")  # Should not raise
        assert logger.flush_count == 1

    def test_custom_flush_thresholds(self, time_provider, buffer_manager):
        """Custom info/warn flush thresholds are respected."""
        from lib.event_logger import EventLogger

        with patch("time.localtime", return_value=FAKE_LOCALTIME):
            logger = EventLogger(
                time_provider,
                buffer_manager,
                logfile="/sd/test.log",
                info_flush_threshold=2,
                warn_flush_threshold=1,
            )
            # Single warning should trigger flush with threshold=1
            logger.warning("T", "warn")
            assert logger.flush_count == 1

            # Two info messages should trigger flush with threshold=2
            logger.info("T", "msg1")
            assert logger.flush_count == 1
            logger.info("T", "msg2")
            assert logger.flush_count == 2
