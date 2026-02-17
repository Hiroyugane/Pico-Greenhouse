# Tests for lib/buffer_manager.py
# Uses tmp_path for real filesystem I/O isolation

from unittest.mock import patch


class TestBufferManagerPrimaryWrite:
    """Tests for writing to primary (SD) storage."""

    def test_write_to_primary_creates_file(self, buffer_manager, tmp_path):
        """Write to primary creates file and appends data."""
        result = buffer_manager.write('test.csv', 'line1\n')
        assert result is True
        assert buffer_manager.writes_to_primary == 1

        content = (tmp_path / "sd" / "test.csv").read_text()
        assert 'line1\n' in content

    def test_write_appends_to_existing_file(self, buffer_manager, tmp_path):
        """Multiple writes append to the same file."""
        buffer_manager.write('test.csv', 'line1\n')
        buffer_manager.write('test.csv', 'line2\n')
        content = (tmp_path / "sd" / "test.csv").read_text()
        assert 'line1\n' in content
        assert 'line2\n' in content
        assert buffer_manager.writes_to_primary == 2

    def test_write_strips_sd_prefix(self, buffer_manager, tmp_path):
        """'/sd/test.csv' is normalized to 'test.csv' relpath."""
        buffer_manager.write('/sd/test.csv', 'data\n')
        assert (tmp_path / "sd" / "test.csv").exists()


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
        result = bm.write('sensor.csv', 'row1\n')
        assert result is False
        assert bm.writes_to_fallback == 1

        content = fallback_file.read_text()
        assert 'sensor.csv|row1\n' in content

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

        result = bm.write('data.csv', 'row\n')
        assert result is False
        assert 'data.csv' in bm._buffers
        assert bm._buffers['data.csv'] == ['row\n']


class TestBufferManagerFlush:
    """Tests for flushing in-memory buffers to primary."""

    def test_flush_writes_buffered_to_primary(self, buffer_manager, tmp_path):
        """flush() writes in-memory buffer entries to primary."""
        buffer_manager._buffers['test.csv'] = ['A\n', 'B\n']
        result = buffer_manager.flush('test.csv')
        assert result is True
        content = (tmp_path / "sd" / "test.csv").read_text()
        assert 'A\nB\n' in content
        assert buffer_manager._buffers['test.csv'] == []

    def test_flush_all_buffers(self, buffer_manager, tmp_path):
        """Flush all files when relpath is None."""
        buffer_manager._buffers['a.csv'] = ['A\n']
        buffer_manager._buffers['b.csv'] = ['B\n']
        result = buffer_manager.flush()
        assert result is True
        assert (tmp_path / "sd" / "a.csv").read_text() == 'A\n'
        assert (tmp_path / "sd" / "b.csv").read_text() == 'B\n'

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
        bm._buffers['test.csv'] = ['data\n']
        assert bm.flush() is False
        # RAM should be drained to fallback
        assert bm._buffers['test.csv'] == []
        content = fallback_file.read_text()
        assert 'test.csv|data\n' in content

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
        bm._buffers['a.csv'] = ['row1\n', 'row2\n']
        bm._buffers['b.csv'] = ['rowX\n']
        bm.flush()
        assert bm._buffers['a.csv'] == []
        assert bm._buffers['b.csv'] == []
        content = fallback_file.read_text()
        assert 'a.csv|row1\n' in content
        assert 'a.csv|row2\n' in content
        assert 'b.csv|rowX\n' in content

    def test_flush_stays_in_ram_when_both_fail(self, tmp_path):
        """flush() keeps entries in RAM only when both primary and fallback fail."""
        from lib.buffer_manager import BufferManager
        bm = BufferManager(
            sd_mount_point=str(tmp_path / "nope"),
            fallback_path=str(tmp_path / "also_nope" / "deep" / "fb.csv"),
        )
        bm.is_primary_available = lambda: False
        bm._ensure_fallback_dir = lambda: False
        bm._buffers['test.csv'] = ['data\n']
        bm.flush()
        # Still in RAM since both targets failed
        assert bm._buffers['test.csv'] == ['data\n']


class TestBufferManagerMigration:
    """Tests for migrating fallback entries to primary."""

    def test_migrate_parses_pipe_format(self, buffer_manager, tmp_path):
        """Fallback entries (relpath|data) are parsed and written to primary."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("sensor.csv|2026-01-29,22.5,65.0\n")

        count = buffer_manager.migrate_fallback()
        assert count == 1
        content = (tmp_path / "sd" / "sensor.csv").read_text()
        assert '22.5,65.0' in content

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
        assert content == ''

    def test_migrate_returns_zero_when_primary_down(self, tmp_path):
        """migrate_fallback returns 0 when primary unavailable."""
        from lib.buffer_manager import BufferManager
        bm = BufferManager(sd_mount_point=str(tmp_path / "nope"))
        assert bm.migrate_fallback() == 0

    def test_migrate_returns_zero_when_no_entries(self, buffer_manager):
        """migrate_fallback returns 0 when fallback is empty."""
        assert buffer_manager.migrate_fallback() == 0

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
        bm._buffers['sensor.csv'] = ['old_row\n']
        bm.write('sensor.csv', 'new_row\n')
        # RAM should be empty now
        assert bm._buffers.get('sensor.csv', []) == []
        content = fallback_file.read_text()
        # Old entry should appear before new entry
        old_pos = content.find('old_row')
        new_pos = content.find('new_row')
        assert old_pos < new_pos

    def test_write_ordering_migration_before_new(self, buffer_manager, tmp_path):
        """When primary reconnects with pending fallback, migrate BEFORE new write."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text("data.csv|old_entry\n")

        buffer_manager.write('data.csv', 'new_entry\n')

        content = (tmp_path / "sd" / "data.csv").read_text()
        # old_entry should appear before new_entry (chronological ordering)
        old_pos = content.find('old_entry')
        new_pos = content.find('new_entry')
        assert old_pos < new_pos


class TestBufferManagerRename:
    """Tests for file rename operations."""

    def test_rename_success(self, buffer_manager, tmp_path):
        """rename() moves file to new name."""
        (tmp_path / "sd" / "old.log").write_text("content")
        result = buffer_manager.rename('old.log', 'new.log')
        assert result is True
        assert (tmp_path / "sd" / "new.log").exists()
        assert not (tmp_path / "sd" / "old.log").exists()

    def test_rename_strips_sd_prefix(self, buffer_manager, tmp_path):
        """rename() handles /sd/ prefixed paths."""
        (tmp_path / "sd" / "system.log").write_text("logs")
        result = buffer_manager.rename('/sd/system.log', '/sd/system_old.log')
        assert result is True
        assert (tmp_path / "sd" / "system_old.log").exists()

    def test_rename_failure_returns_false(self, buffer_manager):
        """rename() returns False for non-existent files."""
        result = buffer_manager.rename('nonexistent.log', 'new.log')
        assert result is False


class TestBufferManagerUtilities:
    """Tests for path utilities and metrics."""

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
            mode = args[0] if args else kwargs.get('mode', 'r')
            if '.test' in str(path) and 'r' in mode:
                # Return wrong data to simulate read-back failure
                from io import StringIO
                return StringIO('garbage')
            return f
        with patch('builtins.open', side_effect=fake_open):
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
        assert 'sd' in buffer_manager._path_join('/sd', 'file.csv')

    def test_path_dirname(self, buffer_manager):
        """_path_dirname extracts directory from path."""
        assert buffer_manager._path_dirname('/sd/data/file.csv') == '/sd/data'

    def test_path_basename(self, buffer_manager):
        """_path_basename extracts filename from path."""
        assert buffer_manager._path_basename('/sd/data/file.csv') == 'file.csv'

    def test_get_metrics_accuracy(self, buffer_manager, tmp_path):
        """Metrics reflect actual write operations."""
        buffer_manager.write('a.csv', 'data\n')
        buffer_manager.write('b.csv', 'data\n')

        metrics = buffer_manager.get_metrics()
        assert metrics['writes_to_primary'] == 2
        assert metrics['writes_to_fallback'] == 0
        assert metrics['write_failures'] == 0
        assert metrics['buffer_entries'] == 0

    def test_buffer_overflow_drops_oldest(self, tmp_path):
        """When fallback fails, buffer drops oldest entry on overflow."""
        from lib.buffer_manager import BufferManager
        bm = BufferManager(
            sd_mount_point=str(tmp_path / "nope"),
            fallback_path=str(tmp_path / "also_nope" / "fb.csv"),
            max_buffer_entries=2,
        )
        bm._ensure_fallback_dir = lambda: True

        with patch('builtins.open', side_effect=OSError('write failed')):
            bm.write('a.csv', 'A\n')
            bm.write('a.csv', 'B\n')
            bm.write('a.csv', 'C\n')

        assert bm.get_metrics()['buffer_entries'] == 2
        assert bm._buffers['a.csv'][0] == 'B\n'

    def test_has_fallback_entries_false_when_empty(self, buffer_manager):
        """_has_fallback_entries() returns False when fallback doesn't exist or is empty."""
        assert buffer_manager._has_fallback_entries() is False

    def test_dir_exists_returns_true_for_existing(self, buffer_manager, tmp_path):
        """_dir_exists returns True for an existing directory."""
        test_dir = tmp_path / 'existing'
        test_dir.mkdir()
        assert buffer_manager._dir_exists(str(test_dir)) is True

    def test_dir_exists_returns_false_for_missing(self, buffer_manager, tmp_path):
        """_dir_exists returns False for non-existent path."""
        assert buffer_manager._dir_exists(str(tmp_path / 'nope')) is False

    def test_ensure_fallback_dir_creates_directory(self, tmp_path):
        """_ensure_fallback_dir creates parent directory of fallback path."""
        from lib.buffer_manager import BufferManager
        fb_path = str(tmp_path / 'new_dir' / 'fallback.csv')
        bm = BufferManager(sd_mount_point=str(tmp_path / 'sd'), fallback_path=fb_path)
        assert bm._ensure_fallback_dir() is True
        assert (tmp_path / 'new_dir').is_dir()

    def test_normalize_host_path_empty_returns_cwd_default(self, tmp_path):
        """_normalize_host_path with empty string returns cwd-based default."""
        from lib.buffer_manager import BufferManager
        bm = BufferManager(sd_mount_point=str(tmp_path / 'sd'))
        result = bm._normalize_host_path('', 'sd')
        assert 'sd' in result

    def test_get_metrics_includes_buffer_sizes(self, tmp_path):
        """get_metrics includes per-file buffer size detail."""
        from lib.buffer_manager import BufferManager
        bm = BufferManager(sd_mount_point=str(tmp_path / 'sd'))
        bm._buffers['a.csv'] = ['row1\n', 'row2\n']
        metrics = bm.get_metrics()
        assert metrics['buffer_entries'] == 2
        assert metrics['buffer_sizes_per_file']['a.csv'] == 2

    def test_path_join_none_parts_ignored(self, buffer_manager):
        """_path_join ignores None parts."""
        result = buffer_manager._path_join('a', None, 'b')
        assert 'a' in result and 'b' in result

    def test_path_join_empty_parts_returns_empty(self, buffer_manager):
        """_path_join with all empty parts returns empty string."""
        result = buffer_manager._path_join('', '', '')
        assert result == ''

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
        assert buffer_manager.has_data_for('test.csv') is True

    def test_has_data_for_primary_with_sd_prefix(self, buffer_manager, tmp_path):
        """has_data_for strips /sd/ prefix before checking."""
        (tmp_path / "sd" / "test.csv").write_text("header\n")
        assert buffer_manager.has_data_for('/sd/test.csv') is True

    def test_has_data_for_fallback(self, buffer_manager, tmp_path):
        """has_data_for returns True when data exists in fallback."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text('test.csv|Timestamp,Temperature,Humidity\n')
        assert buffer_manager.has_data_for('test.csv') is True

    def test_has_data_for_buffer(self, buffer_manager):
        """has_data_for returns True when data exists in memory buffer."""
        buffer_manager._buffers['test.csv'] = ['row\n']
        assert buffer_manager.has_data_for('test.csv') is True

    def test_has_data_for_false(self, buffer_manager):
        """has_data_for returns False when data absent everywhere."""
        assert buffer_manager.has_data_for('nonexistent.csv') is False

    def test_has_data_for_empty_buffer_ignored(self, buffer_manager):
        """Empty buffer list for a relpath is treated as no data."""
        buffer_manager._buffers['test.csv'] = []
        assert buffer_manager.has_data_for('test.csv') is False

    def test_has_data_for_does_not_match_other_relpath(self, buffer_manager, tmp_path):
        """Fallback entries for a different relpath don't match."""
        fallback = tmp_path / "local" / "fallback.csv"
        fallback.write_text('other.csv|data\n')
        assert buffer_manager.has_data_for('test.csv') is False
