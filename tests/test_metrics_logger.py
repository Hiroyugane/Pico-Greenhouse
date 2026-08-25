# Tests for lib/metrics_logger.py
# MetricsLogger: fixed-schema CSV writer driven by the health loop — header
# once, ordered rows, blank regulation cells when the engine is absent, date
# rollover, write-queue routing, and best-effort (never raises).

from unittest.mock import Mock, patch

# Relpath the logger writes to given FAKE_LOCALTIME and sensor_root "/sd/sensors".
_RELPATH = "sensors/metrics/2026/metrics_2026-01-29.csv"

_FULL_ROW = {
    "mem_free_b": 47000,
    "mem_alloc_b": 198000,
    "mem_used_pct": 80.8,
    "tasks": 11,
    "queue_depth": 0,
    "buffered": 0,
    "sd_fallback_writes": 0,
    "write_failures": 0,
    "tick_us": 420,
    "tick_max_us": 900,
    "global_severity": 12.5,
    "band": 2,
    "latched": False,
    "emergency": True,
    "dev_t": 55.0,
    "dev_h": 40.0,
    "dev_c": 50.0,
    "cmd_heater": 0.0,
    "cmd_follower": 0.0,
    "cmd_cooler": 100.0,
    "cmd_humidifier": 0.0,
    "cmd_exhaust": 33.3,
    "cmd_circulation": 20.0,
    "cmd_growlight": 0.0,
    "phase": "bloom",
}


def _make_logger(time_provider, buffer_manager, mock_event_logger, write_queue=None):
    from lib.metrics_logger import MetricsLogger

    return MetricsLogger(
        time_provider=time_provider,
        buffer_manager=buffer_manager,
        sensor_root="/sd/sensors",
        write_queue=write_queue,
        logger=mock_event_logger,
    )


class TestHeader:
    def test_header_written_once(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        from lib.metrics_logger import MetricsLogger

        _make_logger(time_provider, buffer_manager, mock_event_logger)
        sd_file = tmp_path / "sd" / _RELPATH
        assert sd_file.exists()
        content = sd_file.read_text()
        assert content.rstrip("\n") == ",".join(MetricsLogger.COLUMNS)
        assert content.count("\n") == 1  # exactly the header, no rows yet

    def test_header_not_rewritten_on_row(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        logger = _make_logger(time_provider, buffer_manager, mock_event_logger)
        logger.write_row(_FULL_ROW)
        content = (tmp_path / "sd" / _RELPATH).read_text()
        # One header + one data row.
        lines = content.strip("\n").split("\n")
        assert len(lines) == 2
        assert lines[0] == ",".join(logger.COLUMNS)


class TestRowFormat:
    def test_row_matches_schema(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        logger = _make_logger(time_provider, buffer_manager, mock_event_logger)
        assert logger.write_row(_FULL_ROW) is True

        row = (tmp_path / "sd" / _RELPATH).read_text().strip("\n").split("\n")[1]
        cells = row.split(",")
        assert len(cells) == len(logger.COLUMNS)

        by_col = dict(zip(logger.COLUMNS, cells))
        assert by_col["Timestamp"]  # stamped by the logger, non-empty
        assert by_col["mem_free_b"] == "47000"
        assert by_col["mem_used_pct"] == "80.80"  # float -> 2 decimals
        assert by_col["latched"] == "0"  # bool False -> 0
        assert by_col["emergency"] == "1"  # bool True -> 1
        assert by_col["band"] == "2"
        assert by_col["cmd_cooler"] == "100.00"
        assert by_col["phase"] == "bloom"

    def test_the_phase_column_is_last(self):
        """It was appended, not inserted: files opened before it keep aligning."""
        from lib.metrics_logger import MetricsLogger

        assert MetricsLogger.COLUMNS[-1] == "phase"

    def test_a_blind_co2_channel_writes_an_empty_cell(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        """dev_c 50.0 means "on target"; a missing sensor must not claim that."""
        logger = _make_logger(time_provider, buffer_manager, mock_event_logger)
        row_fields = dict(_FULL_ROW)
        row_fields["dev_c"] = None
        row_fields["phase"] = None
        logger.write_row(row_fields)

        row = (tmp_path / "sd" / _RELPATH).read_text().strip("\n").split("\n")[1]
        by_col = dict(zip(logger.COLUMNS, row.split(",")))
        assert by_col["dev_c"] == ""
        assert by_col["dev_h"] == "40.00"  # the other dimensions still land
        assert by_col["phase"] == ""

    def test_missing_regulation_cells_blank(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        logger = _make_logger(time_provider, buffer_manager, mock_event_logger)
        # Only the runtime-load half of the row (engine disabled / None).
        logger.write_row(
            {
                "mem_free_b": 50000,
                "mem_alloc_b": 190000,
                "mem_used_pct": 79.0,
                "tasks": 10,
                "queue_depth": 0,
                "buffered": 0,
                "sd_fallback_writes": 0,
                "write_failures": 0,
            }
        )
        row = (tmp_path / "sd" / _RELPATH).read_text().strip("\n").split("\n")[1]
        by_col = dict(zip(logger.COLUMNS, row.split(",")))
        for col in ("tick_us", "global_severity", "cmd_heater", "cmd_growlight", "latched", "phase"):
            assert by_col[col] == ""


class TestWriteQueue:
    def test_write_routes_through_queue(self, time_provider, buffer_manager, mock_event_logger):
        queue = Mock()
        queue.enqueue_write = Mock(return_value=True)
        logger = _make_logger(time_provider, buffer_manager, mock_event_logger, write_queue=queue)

        assert logger.write_row(_FULL_ROW) is True
        queue.enqueue_write.assert_called_once()
        relpath, data = queue.enqueue_write.call_args[0]
        assert relpath == _RELPATH
        assert data.endswith("\n")


class TestRollover:
    def test_date_rollover_switches_file(self, time_provider, buffer_manager, mock_event_logger, tmp_path):
        logger = _make_logger(time_provider, buffer_manager, mock_event_logger)
        logger.write_row(_FULL_ROW)

        # Advance the RTC date by one day; next write lands in a new file.
        with patch.object(logger.time_provider, "now_date_tuple", return_value=(2026, 1, 30, 0, 0, 0, 0, 30)):
            logger.write_row(_FULL_ROW)

        new_file = tmp_path / "sd" / "sensors/metrics/2026/metrics_2026-01-30.csv"
        assert new_file.exists()
        assert (tmp_path / "sd" / _RELPATH).exists()  # original still there


class TestResilience:
    def test_write_row_never_raises(self, time_provider, buffer_manager, mock_event_logger):
        logger = _make_logger(time_provider, buffer_manager, mock_event_logger)
        with patch.object(logger.buffer_manager, "write", side_effect=OSError("SD gone")):
            # Force the write path (file already created, so _create_file is skipped).
            assert logger.write_row(_FULL_ROW) is False
        mock_event_logger.error.assert_called()
