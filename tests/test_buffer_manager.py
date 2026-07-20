# Tests for lib/buffer_manager.py
# Uses tmp_path for real filesystem I/O isolation

import os
from unittest.mock import patch


class TestBufferManagerPrimaryWrite:
    """Tests for writing to primary (SD) storage."""

    def test_write_to_primary_creates_file(self, buffer_manager, tmp_path):
        """Write to primary creates file and appends data."""
        result = buffer_manager.write("test.csv", "line1\n")
        assert result is True
        assert buffer_manager.writes_to_primary == 1

        content = (tmp_path / "sd" / "test.csv").read_text()
        assert "line1\n" in content

    def test_write_appends_to_existing_file(self, buffer_manager, tmp_path):
        """Multiple writes append to the same file."""
        buffer_manager.write("test.csv", "line1\n")
        buffer_manager.write("test.csv", "line2\n")
        content = (tmp_path / "sd" / "test.csv").read_text()
        assert "line1\n" in content
        assert "line2\n" in content
        assert buffer_manager.writes_to_primary == 2

    def test_write_strips_sd_prefix(self, buffer_manager, tmp_path):
        """'/sd/test.csv' is normalized to 'test.csv' relpath."""
        buffer_manager.write("/sd/test.csv", "data\n")
        assert (tmp_path / "sd" / "test.csv").exists()

    def test_write_creates_nested_parent_dirs(self, buffer_manager, tmp_path):
        """Writing to a nested relpath auto-creates the missing parent dirs."""
        result = buffer_manager.write("sensors/co2/2026/co2_2026-05-15.csv", "row\n")
        assert result is True
        nested = tmp_path / "sd" / "sensors" / "co2" / "2026" / "co2_2026-05-15.csv"
        assert nested.exists()
        assert nested.read_text() == "row\n"


class TestBufferManagerFallback:
    """Tests for fallback writing when primary is unavailable."""

    def test_write_to_fallback_when_primary_unavailable(self, tmp_path):
        """When SD doesn't exist, writes go to fallback with relpath|data format."""
        from lib.buffer_manager import BufferManager

        fallback_dir = tmp_path / "local"
        fallback_dir.mkdir()
        fallback_file = fallback_dir / "fallback.csv"

        bm = BufferManager(
            sd_mount_point=str(tmp_path / "nonexistent_sd"),
            fallback_path=str(fallback_file),
        )
        bm.is_primary_available = lambda: False
        result = bm.write("sensor.csv", "row1\n")
        assert result is False
        assert bm.writes_to_fallback == 1

        content = fallback_file.read_text()
        assert "sensor.csv|row1\n" in content

    def test_write_inmemory_when_both_fail(self, tmp_path):
        """When both primary and fallback are unavailable, buffer in memory."""
        from lib.buffer_manager import BufferManager

        bm = BufferManager(
            sd_mount_point=str(tmp_path / "gone"),
            fallback_path=str(tmp_path / "also_gone" / "deep" / "nope.csv"),
        )
        bm.is_primary_available = lambda: False
        # Patch _ensure_fallback_dir to fail
        bm._ensure_fallback_dir = lambda: False

        result = bm.write("data.csv", "row\n")
        assert result is False
        assert "data.csv" in bm._buffers
        assert bm._buffers["data.csv"] == ["row\n"]


class TestBufferManagerFlush:
    """Tests for flushing in-memory buffers to primary."""

    def test_flush_writes_buffered_to_primary(self, buffer_manager, tmp_path):
        """flush() writes in-memory buffer entries to primary."""
        buffer_manager._buffers["test.csv"] = ["A\n", "B\n"]
        result = buffer_manager.flush("test.csv")
        assert result is True
        content = (tmp_path / "sd" / "test.csv").read_text()
        assert "A\nB\n" in content
        assert buffer_manager._buffers["test.csv"] == []

    def test_flush_all_buffers(self, buffer_manager, tmp_path):
        """Flush all files when relpath is None."""
        buffer_manager._buffers["a.csv"] = ["A\n"]
        buffer_manager._buffers["b.csv"] = ["B\n"]
        result = buffer_manager.flush()
        assert result is True
        assert (tmp_path / "sd" / "a.csv").read_text() == "A\n"
        assert (tmp_path / "sd" / "b.csv").read_text() == "B\n"

    def test_flush_returns_false_when_primary_down(self, tmp_path):
        """flush() returns False when primary is unavailable but drains to fallback."""
        from lib.buffer_manager import BufferManager

        fallback_dir = tmp_path / "local"
        fallback_dir.mkdir()
        fallback_file = fallback_dir / "fallback.csv"
        bm = BufferManager(
            sd_mount_point=str(tmp_path / "nope"),
            fallback_path=str(fallback_file),
        )
        bm.is_primary_available = lambda: False
        bm._buffers["test.csv"] = ["data\n"]
        assert bm.flush() is False
        # RAM should be drained to fallback
        assert bm._buffers["test.csv"] == []
        content = fallback_file.read_text()
        assert "test.csv|data\n" in content

    def test_flush_to_fallback_when_primary_down(self, tmp_path):
        """flush() drains multiple RAM entries to fallback when SD unavailable."""
        from lib.buffer_manager import BufferManager

        fallback_dir = tmp_path / "local"
        fallback_dir.mkdir()
        fallback_file = fallback_dir / "fallback.csv"
        bm = BufferManager(
            sd_mount_point=str(tmp_path / "nope"),
            fallback_path=str(fallback_file),
        )
        bm.is_primary_available = lambda: False
        bm._buffers["a.csv"] = ["row1\n", "row2\n"]
        bm._buffers["b.csv"] = ["rowX\n"]
        bm.flush()
        assert bm._buffers["a.csv"] == []
        assert bm._buffers["b.csv"] == []
        content = fallback_file.read_text()
        assert "a.csv|row1\n" in content
        assert "a.csv|row2\n" in content
        assert "b.csv|rowX\n" in content

    def test_flush_stays_in_ram_when_both_fail(self, tmp_path):
        """flush() keeps entries in RAM only when both primary and fallback fail."""
        from lib.buffer_manager import BufferManager

        bm = BufferManager(
            sd_mount_point=str(tmp_path / "nope"),
            fallback_path=str(tmp_path / "also_nope" / "deep" / "fb.csv"),
        )
        bm.is_primary_available = lambda: False
        bm._ensure_fallback_dir = lambda: False
        bm._buffers["test.csv"] = ["data\n"]
        bm.flush()
        # Still in RAM since both targets failed
        assert bm._buffers["test.csv"] == ["data\n"]


class TestBufferManagerMigration:
    """Tests for migrating fallback entries to primary."""

    def test_migrate_parses_pipe_format(self, buffer_manager, tmp_path):
        """Fallback entries (relpath|data) are parsed and written to primary."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("sensor.csv|2026-01-29,22.5,65.0\n")

        count = buffer_manager.migrate_fallback()
        assert count == 1
        content = (tmp_path / "sd" / "sensor.csv").read_text()
        assert "22.5,65.0" in content

    def test_migrate_skips_malformed_lines(self, buffer_manager, tmp_path):
        """Lines without '|' separator are skipped."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("malformed line\nsensor.csv|good\n")

        count = buffer_manager.migrate_fallback()
        assert count == 1  # Only the valid line

    def test_migrate_clears_fallback(self, buffer_manager, tmp_path):
        """After successful migration, fallback file is cleared."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("a.csv|data\n")

        buffer_manager.migrate_fallback()
        content = fallback.read_text()
        assert content == ""

    def test_migrate_returns_zero_when_primary_down(self, tmp_path):
        """migrate_fallback returns 0 when primary unavailable."""
        from lib.buffer_manager import BufferManager

        bm = BufferManager(sd_mount_point=str(tmp_path / "nope"))
        assert bm.migrate_fallback() == 0

    def test_migrate_returns_zero_when_no_entries(self, buffer_manager):
        """migrate_fallback returns 0 when fallback is empty."""
        assert buffer_manager.migrate_fallback() == 0

    def test_migrate_respects_batch_max(self, tmp_path):
        """migrate_fallback drains at most migrate_batch_max rows per call.

        Why: synchronous SD writes during migration must not exceed the
        event-loop watchdog window. The cap forces the drain to spread
        across multiple health-check cycles.
        """
        from lib.buffer_manager import BufferManager

        sd_dir = tmp_path / "sd"
        sd_dir.mkdir()
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.parent.mkdir()
        # Five rows, batch cap of 2 → first call drains 2, three remain.
        fallback.write_text("a.csv|r1\na.csv|r2\na.csv|r3\na.csv|r4\na.csv|r5\n")

        bm = BufferManager(
            sd_mount_point=str(sd_dir),
            fallback_path=str(fallback),
            migrate_batch_max=2,
        )

        assert bm.migrate_fallback() == 2
        leftover = fallback.read_text()
        assert leftover == "a.csv|r3\na.csv|r4\na.csv|r5\n"

        # Second pass drains the next two; one row left.
        assert bm.migrate_fallback() == 2
        assert fallback.read_text() == "a.csv|r5\n"

        # Third pass drains the last row; fallback now empty.
        assert bm.migrate_fallback() == 1
        assert fallback.read_text() == ""

        # Primary file received rows in chronological order.
        assert (sd_dir / "a.csv").read_text() == "r1\nr2\nr3\nr4\nr5\n"

    def test_migrate_feeds_watchdog_between_rows(self, tmp_path):
        """wdt_feed is invoked at least once per migrated row.

        Why: a multi-row drain on a slow SD can take seconds; without
        watchdog feeding inside the loop, a legitimate batch can trip
        the WDT and trigger a silent reset.
        """
        from lib.buffer_manager import BufferManager

        sd_dir = tmp_path / "sd"
        sd_dir.mkdir()
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.parent.mkdir()
        fallback.write_text("a.csv|r1\na.csv|r2\na.csv|r3\n")

        feeds = []

        def fake_feed():
            feeds.append(1)

        bm = BufferManager(
            sd_mount_point=str(sd_dir),
            fallback_path=str(fallback),
            migrate_batch_max=10,
            wdt_feed=fake_feed,
        )

        assert bm.migrate_fallback() == 3
        # At least one feed per row processed.
        assert len(feeds) >= 3

    def test_migrate_wdt_feed_exceptions_are_swallowed(self, tmp_path):
        """A misbehaving wdt_feed callable must not abort migration."""
        from lib.buffer_manager import BufferManager

        sd_dir = tmp_path / "sd"
        sd_dir.mkdir()
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.parent.mkdir()
        fallback.write_text("a.csv|r1\n")

        def angry_feed():
            raise RuntimeError("hardware is on fire")

        bm = BufferManager(
            sd_mount_point=str(sd_dir),
            fallback_path=str(fallback),
            wdt_feed=angry_feed,
        )

        # Migration still succeeds even though the WDT callback throws.
        assert bm.migrate_fallback() == 1
        assert fallback.read_text() == ""

    def test_write_drains_ram_to_fallback_before_new_entry(self, tmp_path):
        """When primary is down and RAM has entries, write() drains RAM to fallback first."""
        from lib.buffer_manager import BufferManager

        fallback_dir = tmp_path / "local"
        fallback_dir.mkdir()
        fallback_file = fallback_dir / "fallback.csv"
        bm = BufferManager(
            sd_mount_point=str(tmp_path / "nope"),
            fallback_path=str(fallback_file),
        )
        bm.is_primary_available = lambda: False
        # Simulate existing RAM entries (from when fallback was also down)
        bm._buffers["sensor.csv"] = ["old_row\n"]
        bm.write("sensor.csv", "new_row\n")
        # RAM should be empty now
        assert bm._buffers.get("sensor.csv", []) == []
        content = fallback_file.read_text()
        # Old entry should appear before new entry
        old_pos = content.find("old_row")
        new_pos = content.find("new_row")
        assert old_pos < new_pos

    def test_write_ordering_migration_before_new(self, buffer_manager, tmp_path):
        """When primary reconnects with pending fallback, migrate BEFORE new write."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("data.csv|old_entry\n")

        buffer_manager.write("data.csv", "new_entry\n")

        content = (tmp_path / "sd" / "data.csv").read_text()
        # old_entry should appear before new_entry (chronological ordering)
        old_pos = content.find("old_entry")
        new_pos = content.find("new_entry")
        assert old_pos < new_pos

    def test_auto_migration_not_retried_every_write_when_fallback_persists(self, buffer_manager, tmp_path):
        """Auto-migration is attempted once until new fallback writes occur."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("system.log|stale-entry\n")

        calls = {"count": 0}

        def fake_migrate():
            calls["count"] += 1
            # Simulate failed clear/unchanged fallback so entries still exist.
            return 0

        buffer_manager.migrate_fallback = fake_migrate

        assert buffer_manager.write("system.log", "run-entry-1\n") is True
        assert buffer_manager.write("system.log", "run-entry-2\n") is True

        assert calls["count"] == 1


class TestBufferManagerRename:
    """Tests for file rename operations."""

    def test_rename_success(self, buffer_manager, tmp_path):
        """rename() moves file to new name."""
        (tmp_path / "sd" / "old.log").write_text("content")
        result = buffer_manager.rename("old.log", "new.log")
        assert result is True
        assert (tmp_path / "sd" / "new.log").exists()
        assert not (tmp_path / "sd" / "old.log").exists()

    def test_rename_strips_sd_prefix(self, buffer_manager, tmp_path):
        """rename() handles /sd/ prefixed paths."""
        (tmp_path / "sd" / "system.log").write_text("logs")
        result = buffer_manager.rename("/sd/system.log", "/sd/system_old.log")
        assert result is True
        assert (tmp_path / "sd" / "system_old.log").exists()

    def test_rename_failure_returns_false(self, buffer_manager):
        """rename() returns False for non-existent files."""
        result = buffer_manager.rename("nonexistent.log", "new.log")
        assert result is False

    def test_rename_prefers_os_rename(self, buffer_manager, tmp_path):
        """rename() uses the atomic os.rename fast path (no whole-file copy)."""
        (tmp_path / "sd" / "a.log").write_text("hello")
        with patch("lib.buffer_manager.os.rename", wraps=os.rename) as mock_rename:
            assert buffer_manager.rename("a.log", "b.log") is True
        mock_rename.assert_called_once()
        assert (tmp_path / "sd" / "b.log").read_text() == "hello"
        assert not (tmp_path / "sd" / "a.log").exists()

    def test_rename_fallback_chunked_large_file(self, buffer_manager, tmp_path):
        """When os.rename is unavailable, the chunked copy fallback preserves content."""
        content = "A" * 1500  # three full chunks
        (tmp_path / "sd" / "big.log").write_text(content)
        # Force the copy-then-delete fallback by making the fast path fail.
        with patch("lib.buffer_manager.os.rename", side_effect=OSError("no cross-fs rename")):
            assert buffer_manager.rename("big.log", "big_old.log") is True
        assert not (tmp_path / "sd" / "big.log").exists()
        assert (tmp_path / "sd" / "big_old.log").read_text() == content

    def test_rename_partial_cleanup_on_error(self, buffer_manager, tmp_path):
        """rename() removes partial destination file if the fallback write fails mid-copy."""
        content = "B" * 1500
        old_file = tmp_path / "sd" / "error.log"
        new_file = tmp_path / "sd" / "error_new.log"
        old_file.write_text(content)

        real_open = open
        call_count = [0]

        def patched_open(path, mode="r", *args, **kwargs):
            fh = real_open(path, mode, *args, **kwargs)
            # Raise on the second dst.write call to simulate mid-copy failure
            if "w" in mode and "error_new.log" in str(path):
                real_write = fh.write
                call_count[0] = 0

                def failing_write(data):
                    call_count[0] += 1
                    if call_count[0] > 1:
                        raise OSError("simulated write failure")
                    return real_write(data)

                fh.write = failing_write
            return fh

        import builtins

        # Force the copy fallback (os.rename would otherwise succeed atomically).
        with patch("lib.buffer_manager.os.rename", side_effect=OSError("no cross-fs rename")):
            with patch.object(builtins, "open", side_effect=patched_open):
                result = buffer_manager.rename("error.log", "error_new.log")

        assert result is False
        assert old_file.exists(), "source file must survive a failed rename"
        assert not new_file.exists(), "partial destination must be cleaned up"


class TestBufferManagerDirHelpers:
    """Tests for list_primary_dir() and delete_primary_file()."""

    def test_list_primary_dir_returns_names(self, buffer_manager, tmp_path):
        """list_primary_dir() returns filenames in an SD subdirectory."""
        logs = tmp_path / "sd" / "logs"
        logs.mkdir(parents=True)
        (logs / "system.log").write_text("x")
        (logs / "system_2026-01-01.log").write_text("y")
        names = buffer_manager.list_primary_dir("logs")
        assert set(names) == {"system.log", "system_2026-01-01.log"}

    def test_list_primary_dir_missing_returns_empty(self, buffer_manager):
        """list_primary_dir() returns [] for a directory that does not exist."""
        assert buffer_manager.list_primary_dir("nope") == []

    def test_list_primary_dir_strips_sd_prefix(self, buffer_manager, tmp_path):
        """list_primary_dir() accepts a /sd/-prefixed directory path."""
        logs = tmp_path / "sd" / "logs"
        logs.mkdir(parents=True)
        (logs / "a.log").write_text("x")
        assert buffer_manager.list_primary_dir("/sd/logs") == ["a.log"]

    def test_delete_primary_file_removes(self, buffer_manager, tmp_path):
        """delete_primary_file() removes an existing file and returns True."""
        target = tmp_path / "sd" / "logs" / "old.log"
        target.parent.mkdir(parents=True)
        target.write_text("x")
        assert buffer_manager.delete_primary_file("logs/old.log") is True
        assert not target.exists()

    def test_delete_primary_file_missing_returns_false(self, buffer_manager):
        """delete_primary_file() returns False when the file is absent."""
        assert buffer_manager.delete_primary_file("logs/ghost.log") is False


class TestBufferManagerUtilities:
    """Tests for path utilities and metrics."""

    def test_clear_fallback_startup_deletes_existing_file(self, buffer_manager, tmp_path):
        """clear_fallback_startup removes fallback.csv when present."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("stale\n")

        assert buffer_manager.clear_fallback_startup() is True
        assert not fallback.exists()

    def test_clear_fallback_startup_returns_false_when_missing(self, buffer_manager):
        """clear_fallback_startup is non-fatal when fallback.csv is absent."""
        assert buffer_manager.clear_fallback_startup() is False

    def test_is_primary_available_true(self, buffer_manager):
        """is_primary_available() returns True when SD directory is writable."""
        assert buffer_manager.is_primary_available() is True

    def test_is_primary_available_verifies_readback(self, buffer_manager, tmp_path):
        """is_primary_available() write+read-verifies actual data, not empty string."""
        # Sabotage reads to return wrong data (simulates ghost writes on removed card)
        import builtins

        real_open = builtins.open

        def fake_open(path, *args, **kwargs):
            f = real_open(path, *args, **kwargs)
            mode = args[0] if args else kwargs.get("mode", "r")
            if ".test" in str(path) and "r" in mode:
                # Return wrong data to simulate read-back failure
                from io import StringIO

                return StringIO("garbage")
            return f

        with patch("builtins.open", side_effect=fake_open):
            assert buffer_manager.is_primary_available() is False

    def test_is_primary_available_false(self, tmp_path):
        """is_primary_available() returns False when SD doesn't exist."""
        import shutil

        from lib.buffer_manager import BufferManager

        sd_path = tmp_path / "nope"
        bm = BufferManager(sd_mount_point=str(sd_path))
        # Constructor creates the dir; remove it to test unavailability
        shutil.rmtree(str(sd_path), ignore_errors=True)
        assert bm.is_primary_available() is False

    def test_path_join(self, buffer_manager):
        """_path_join combines path segments correctly."""
        assert "sd" in buffer_manager._path_join("/sd", "file.csv")

    def test_path_dirname(self, buffer_manager):
        """_path_dirname extracts directory from path."""
        assert buffer_manager._path_dirname("/sd/data/file.csv") == "/sd/data"

    def test_path_basename(self, buffer_manager):
        """_path_basename extracts filename from path."""
        assert buffer_manager._path_basename("/sd/data/file.csv") == "file.csv"

    def test_get_metrics_accuracy(self, buffer_manager, tmp_path):
        """Metrics reflect actual write operations."""
        buffer_manager.write("a.csv", "data\n")
        buffer_manager.write("b.csv", "data\n")

        metrics = buffer_manager.get_metrics()
        assert metrics["writes_to_primary"] == 2
        assert metrics["writes_to_fallback"] == 0
        assert metrics["write_failures"] == 0
        assert metrics["buffer_entries"] == 0

    def test_buffer_overflow_drops_oldest(self, tmp_path):
        """When fallback fails, buffer drops oldest entry on overflow."""
        from lib.buffer_manager import BufferManager

        bm = BufferManager(
            sd_mount_point=str(tmp_path / "nope"),
            fallback_path=str(tmp_path / "also_nope" / "fb.csv"),
            max_buffer_entries=2,
        )
        bm._ensure_fallback_dir = lambda: True

        with patch("builtins.open", side_effect=OSError("write failed")):
            bm.write("a.csv", "A\n")
            bm.write("a.csv", "B\n")
            bm.write("a.csv", "C\n")

        assert bm.get_metrics()["buffer_entries"] == 2
        assert bm._buffers["a.csv"][0] == "B\n"

    def test_has_fallback_entries_false_when_empty(self, buffer_manager):
        """_has_fallback_entries() returns False when fallback doesn't exist or is empty."""
        assert buffer_manager._has_fallback_entries() is False

    def test_dir_exists_returns_true_for_existing(self, buffer_manager, tmp_path):
        """_dir_exists returns True for an existing directory."""
        test_dir = tmp_path / "existing"
        test_dir.mkdir()
        assert buffer_manager._dir_exists(str(test_dir)) is True

    def test_dir_exists_returns_false_for_missing(self, buffer_manager, tmp_path):
        """_dir_exists returns False for non-existent path."""
        assert buffer_manager._dir_exists(str(tmp_path / "nope")) is False

    def test_ensure_fallback_dir_creates_directory(self, tmp_path):
        """_ensure_fallback_dir creates parent directory of fallback path."""
        from lib.buffer_manager import BufferManager

        fb_path = str(tmp_path / "new_dir" / "fallback.csv")
        bm = BufferManager(sd_mount_point=str(tmp_path / "sd"), fallback_path=fb_path)
        assert bm._ensure_fallback_dir() is True
        assert (tmp_path / "new_dir").is_dir()

    def test_normalize_host_path_empty_returns_cwd_default(self, tmp_path):
        """_normalize_host_path with empty string returns cwd-based default."""
        from lib.buffer_manager import BufferManager

        bm = BufferManager(sd_mount_point=str(tmp_path / "sd"))
        result = bm._normalize_host_path("", "sd")
        assert "sd" in result

    def test_get_metrics_includes_buffer_sizes(self, tmp_path):
        """get_metrics includes per-file buffer size detail."""
        from lib.buffer_manager import BufferManager

        bm = BufferManager(sd_mount_point=str(tmp_path / "sd"))
        bm._buffers["a.csv"] = ["row1\n", "row2\n"]
        metrics = bm.get_metrics()
        assert metrics["buffer_entries"] == 2
        assert metrics["buffer_sizes_per_file"]["a.csv"] == 2

    def test_path_join_none_parts_ignored(self, buffer_manager):
        """_path_join ignores None parts."""
        result = buffer_manager._path_join("a", None, "b")
        assert "a" in result and "b" in result

    def test_path_join_empty_parts_returns_empty(self, buffer_manager):
        """_path_join with all empty parts returns empty string."""
        result = buffer_manager._path_join("", "", "")
        assert result == ""

    def test_has_fallback_entries_true(self, buffer_manager, tmp_path):
        """_has_fallback_entries() returns True when fallback has content."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("data")
        assert buffer_manager._has_fallback_entries() is True


class TestBufferManagerHasDataFor:
    """Tests for has_data_for() method."""

    def test_has_data_for_primary(self, buffer_manager, tmp_path):
        """has_data_for returns True when file exists on primary."""
        (tmp_path / "sd" / "test.csv").write_text("header\n")
        assert buffer_manager.has_data_for("test.csv") is True

    def test_has_data_for_primary_with_sd_prefix(self, buffer_manager, tmp_path):
        """has_data_for strips /sd/ prefix before checking."""
        (tmp_path / "sd" / "test.csv").write_text("header\n")
        assert buffer_manager.has_data_for("/sd/test.csv") is True

    def test_has_data_for_fallback(self, buffer_manager, tmp_path):
        """has_data_for returns True when data exists in fallback."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("test.csv|Timestamp,Temperature,Humidity\n")
        assert buffer_manager.has_data_for("test.csv") is True

    def test_has_data_for_buffer(self, buffer_manager):
        """has_data_for returns True when data exists in memory buffer."""
        buffer_manager._buffers["test.csv"] = ["row\n"]
        assert buffer_manager.has_data_for("test.csv") is True

    def test_has_data_for_false(self, buffer_manager):
        """has_data_for returns False when data absent everywhere."""
        assert buffer_manager.has_data_for("nonexistent.csv") is False

    def test_has_data_for_empty_buffer_ignored(self, buffer_manager):
        """Empty buffer list for a relpath is treated as no data."""
        buffer_manager._buffers["test.csv"] = []
        assert buffer_manager.has_data_for("test.csv") is False

    def test_has_data_for_does_not_match_other_relpath(self, buffer_manager, tmp_path):
        """Fallback entries for a different relpath don't match."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("other.csv|data\n")
        assert buffer_manager.has_data_for("test.csv") is False


class TestBufferManagerWriteExceptions:
    """Tests for write() and flush() exception paths."""

    def test_write_primary_exception_falls_to_fallback(self, tmp_path):
        """When primary is available but open() raises during write, data goes to fallback."""
        from unittest.mock import patch as mock_patch

        from lib.buffer_manager import BufferManager

        sd_dir = tmp_path / "sd"
        sd_dir.mkdir()
        fallback_dir = tmp_path / "local"
        fallback_dir.mkdir()
        fallback_file = fallback_dir / "fallback.csv"

        bm = BufferManager(
            sd_mount_point=str(sd_dir),
            fallback_path=str(fallback_file),
        )

        # is_primary_available returns True, but the actual file open raises
        original_open = open
        call_count = 0

        def failing_open(path, mode="r", *a, **kw):
            nonlocal call_count
            path_str = str(path)
            # Allow is_primary_available test file operations, but fail on actual data write
            if mode == "a" and "test.csv" in path_str:
                raise OSError("SD write error")
            return original_open(path, mode, *a, **kw)

        with mock_patch("builtins.open", side_effect=failing_open):
            result = bm.write("test.csv", "data row\n")

        # Should have fallen through to fallback
        assert result is False
        assert fallback_file.exists()
        content = fallback_file.read_text()
        assert "test.csv|data row\n" in content

    def test_flush_primary_exception_drains_to_fallback(self, tmp_path):
        """When flush() tries primary but open() raises, entries drain to fallback."""

        from lib.buffer_manager import BufferManager

        sd_dir = tmp_path / "sd"
        sd_dir.mkdir()
        fallback_dir = tmp_path / "local"
        fallback_dir.mkdir()
        fallback_file = fallback_dir / "fallback.csv"

        bm = BufferManager(
            sd_mount_point=str(sd_dir),
            fallback_path=str(fallback_file),
        )
        bm._buffers["data.csv"] = ["row1\n", "row2\n"]

        # Primary reports unavailable → flush drains to fallback
        bm.is_primary_available = lambda: False
        bm.flush()

        assert bm._buffers["data.csv"] == []
        content = fallback_file.read_text()
        assert "data.csv|row1\n" in content
        assert "data.csv|row2\n" in content

    def test_debug_callback_invoked_on_write(self, tmp_path):
        """debug_callback receives messages during write operations."""
        from lib.buffer_manager import BufferManager

        sd_dir = tmp_path / "sd"
        sd_dir.mkdir()
        fallback_dir = tmp_path / "local"
        fallback_dir.mkdir()
        fallback_file = fallback_dir / "fallback.csv"

        debug_msgs = []
        bm = BufferManager(
            sd_mount_point=str(sd_dir),
            fallback_path=str(fallback_file),
            debug_callback=lambda msg: debug_msgs.append(msg),
        )
        bm.write("test.csv", "line\n")

        assert len(debug_msgs) > 0
        assert any("write" in m.lower() for m in debug_msgs)


class TestBufferManagerLogger:
    """Tests for optional logger injection via set_logger()."""

    def test_set_logger_stores_logger(self, buffer_manager):
        """set_logger() stores the logger instance."""
        from unittest.mock import Mock

        logger = Mock()
        buffer_manager.set_logger(logger)
        assert buffer_manager._logger is logger

    def test_init_without_logger(self, tmp_path):
        """BufferManager initializes with _logger=None by default."""
        from lib.buffer_manager import BufferManager

        bm = BufferManager(
            sd_mount_point=str(tmp_path / "sd"),
            fallback_path=str(tmp_path / "local" / "fallback.csv"),
        )
        assert bm._logger is None

    def test_init_with_logger(self, tmp_path):
        """BufferManager accepts logger in constructor."""
        from unittest.mock import Mock

        from lib.buffer_manager import BufferManager

        logger = Mock()
        sd_dir = tmp_path / "sd"
        sd_dir.mkdir()
        bm = BufferManager(
            sd_mount_point=str(sd_dir),
            fallback_path=str(tmp_path / "local" / "fallback.csv"),
            logger=logger,
        )
        assert bm._logger is logger

    def test_log_debug_with_logger(self, buffer_manager):
        """_log_debug() calls logger.debug when logger is set."""
        from unittest.mock import Mock

        logger = Mock()
        buffer_manager.set_logger(logger)
        buffer_manager._log_debug("test message", key="value")
        logger.debug.assert_called_once_with("BufferMgr", "test message", key="value")

    def test_log_debug_without_logger_no_crash(self, buffer_manager):
        """_log_debug() does nothing when logger is None."""
        buffer_manager._logger = None
        buffer_manager._log_debug("test message")  # should not raise


class TestBufferManagerFallbackPrune:
    """Tests for start_fallback_prune_task() — background size-cap loop."""

    def _make_bm(self, tmp_path, max_kb=1, logger=None):
        from lib.buffer_manager import BufferManager

        sd_dir = tmp_path / "sd"
        sd_dir.mkdir()
        return BufferManager(
            sd_mount_point=str(sd_dir),
            fallback_path=str(tmp_path / "local" / "fallback.csv"),
            max_buffer_entries=100,
            max_fallback_size_kb=max_kb,
            logger=logger,
        )

    def _run_one_iteration(self, bm):
        """Drive start_fallback_prune_task through exactly one iteration."""
        import asyncio

        # First sleep returns immediately; second raises to break the loop.
        sleeps = {"n": 0}

        async def _fake_sleep(_):
            sleeps["n"] += 1
            if sleeps["n"] > 1:
                raise asyncio.CancelledError
            return None

        async def runner():
            try:
                await bm.start_fallback_prune_task(check_interval=0)
            except asyncio.CancelledError:
                pass

        from unittest.mock import patch

        with patch("asyncio.sleep", _fake_sleep):
            asyncio.run(runner())

    def test_prune_skips_when_under_limit(self, tmp_path):
        from unittest.mock import Mock

        logger = Mock()
        bm = self._make_bm(tmp_path, max_kb=10, logger=logger)
        # Tiny fallback content — under the 10 KB ceiling
        bm.write("foo.csv", "small\n")  # forced via direct fallback write below

        # Force a write to fallback by failing the primary path
        import os as _os

        _os.makedirs(_os.path.dirname(bm.fallback_path), exist_ok=True)
        with open(bm.fallback_path, "w") as f:
            f.write("foo|x\n")

        self._run_one_iteration(bm)
        # Should not have logged a warning (no pruning happened)
        warned = [c for c in logger.warning.call_args_list if "exceeds" in str(c)]
        assert warned == []

    def test_prune_trims_when_over_limit(self, tmp_path):
        from unittest.mock import Mock

        logger = Mock()
        bm = self._make_bm(tmp_path, max_kb=1, logger=logger)
        # Write > 1 KB of fallback content (line-oriented)
        import os as _os

        _os.makedirs(_os.path.dirname(bm.fallback_path), exist_ok=True)
        with open(bm.fallback_path, "w") as f:
            for i in range(200):
                f.write(f"foo|line{i:04d}-{'x' * 30}\n")

        original_size = _os.path.getsize(bm.fallback_path)
        assert original_size > 1024

        self._run_one_iteration(bm)

        new_size = _os.path.getsize(bm.fallback_path)
        assert new_size < original_size
        # Warning about size overrun should have fired
        warning_msgs = " ".join(str(c) for c in logger.warning.call_args_list)
        assert "exceeds" in warning_msgs
        # Info about prune count should have fired
        info_msgs = " ".join(str(c) for c in logger.info.call_args_list)
        assert "Pruned" in info_msgs

    def test_prune_handles_unreadable_fallback(self, tmp_path):
        """If reading fallback fails mid-loop, the iteration is skipped gracefully."""
        from unittest.mock import Mock, patch

        logger = Mock()
        bm = self._make_bm(tmp_path, max_kb=1, logger=logger)
        # Create an oversized fallback so we reach the read step
        import os as _os

        _os.makedirs(_os.path.dirname(bm.fallback_path), exist_ok=True)
        with open(bm.fallback_path, "w") as f:
            for _ in range(100):
                f.write("x" * 100 + "\n")

        # Patch builtins.open to raise on the prune read
        original_open = open
        call_count = {"n": 0}

        def _flaky_open(path, mode="r", *a, **k):
            if path == bm.fallback_path and "r" in mode:
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise OSError("flaky read")
            return original_open(path, mode, *a, **k)

        with patch("builtins.open", side_effect=_flaky_open):
            self._run_one_iteration(bm)
        # Should not have aborted the task — we get here without exception

    def test_prune_cancelled_logs_warning(self, tmp_path):
        """CancelledError raised from inside the loop propagates and is logged."""
        from unittest.mock import Mock, patch

        logger = Mock()
        bm = self._make_bm(tmp_path, max_kb=1, logger=logger)

        import asyncio

        async def _immediate_cancel(_):
            raise asyncio.CancelledError

        async def runner():
            with pytest.raises(asyncio.CancelledError):
                await bm.start_fallback_prune_task(check_interval=0)

        import pytest

        with patch("asyncio.sleep", _immediate_cancel):
            asyncio.run(runner())
        # The CancelledError handler logs a warning
        msgs = " ".join(str(c) for c in logger.warning.call_args_list)
        assert "cancelled" in msgs.lower()

    def test_prune_unexpected_error_logs_error(self, tmp_path):
        """An unexpected exception in the loop body is logged but does not kill the task."""
        from unittest.mock import Mock, patch

        logger = Mock()
        bm = self._make_bm(tmp_path, max_kb=1, logger=logger)

        # Make _get_file_size raise an unexpected exception
        with patch.object(bm, "_get_file_size", side_effect=RuntimeError("boom")):
            self._run_one_iteration(bm)
        msgs = " ".join(str(c) for c in logger.error.call_args_list)
        assert "Unexpected error" in msgs or "boom" in msgs
