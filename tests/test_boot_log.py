# Tests for lib/boot_log.py
# Covers configure, log, truncate-on-first-write, size cap, error tolerance.

import pytest


@pytest.fixture
def boot_log_module(tmp_path, monkeypatch):
    """Import and reset boot_log, pointing it at a tmp_path file."""
    from lib import boot_log

    boot_log._reset_for_test()
    log_file = tmp_path / "boot.log"
    monkeypatch.setattr(boot_log, "_path", str(log_file))
    monkeypatch.setattr(boot_log, "_max_bytes", 1024)
    yield boot_log, log_file
    boot_log._reset_for_test()


class TestBootLogBasics:
    """log() echoes to console AND writes to file."""

    def test_log_writes_message_to_file(self, boot_log_module):
        boot_log, log_file = boot_log_module
        boot_log.log("hello")
        assert log_file.exists()
        assert log_file.read_text().rstrip("\n") == "hello"

    def test_log_echoes_to_console(self, boot_log_module, capsys):
        boot_log, _ = boot_log_module
        boot_log.log("visible on serial")
        captured = capsys.readouterr()
        assert "visible on serial" in captured.out

    def test_multiple_logs_each_on_new_line(self, boot_log_module):
        boot_log, log_file = boot_log_module
        boot_log.log("line 1")
        boot_log.log("line 2")
        boot_log.log("line 3")
        contents = log_file.read_text().splitlines()
        assert contents == ["line 1", "line 2", "line 3"]


class TestBootLogTruncation:
    """First write per process truncates; subsequent writes append."""

    def test_first_write_truncates_existing_content(self, boot_log_module):
        boot_log, log_file = boot_log_module
        log_file.write_text("old boot's leftovers\n" * 5)
        boot_log.log("new boot")
        assert log_file.read_text().rstrip("\n") == "new boot"

    def test_size_cap_triggers_rewrite(self, boot_log_module, monkeypatch):
        boot_log, log_file = boot_log_module
        # Tighten cap so we hit it quickly.
        monkeypatch.setattr(boot_log, "_max_bytes", 20)
        boot_log.log("first")
        # Force size > cap on next call.
        log_file.write_text("x" * 100)
        boot_log.log("after cap")
        # File should have been rewritten ("w" mode), so only the last
        # message remains.
        assert log_file.read_text().rstrip("\n") == "after cap"


class TestBootLogConfigure:
    """configure() overrides path and max_bytes."""

    def test_configure_changes_path(self, tmp_path, monkeypatch):
        from lib import boot_log

        boot_log._reset_for_test()
        target = tmp_path / "elsewhere.log"
        boot_log.configure(path=str(target), max_bytes=512)
        try:
            boot_log.log("routed elsewhere")
            assert target.exists()
        finally:
            boot_log._reset_for_test()
            # Restore defaults so later tests start clean.
            boot_log.configure(path="/boot.log", max_bytes=10 * 1024)


class TestBootLogErrorTolerance:
    """File I/O failures are swallowed; print side always runs."""

    def test_unwritable_path_does_not_raise(self, monkeypatch, capsys):
        from lib import boot_log

        boot_log._reset_for_test()
        # Path that cannot be opened (directory we lack permission to,
        # represented here by a path that triggers OSError on open).
        monkeypatch.setattr(boot_log, "_path", "/this/does/not/exist/boot.log")
        boot_log.log("still echoes")  # must not raise
        captured = capsys.readouterr()
        assert "still echoes" in captured.out
        boot_log._reset_for_test()
