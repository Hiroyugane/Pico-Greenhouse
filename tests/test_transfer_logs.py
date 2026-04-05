# Tests for transfer_logs.py

from pathlib import Path
from unittest.mock import Mock

import prototypes.transfer_logs as transfer_logs


class TestNormalizeSdPath:
    def test_drive_letter_adds_root_backslash(self):
        result = transfer_logs._normalize_sd_path("G:")
        assert isinstance(result, Path)
        assert str(result).upper().endswith("G:\\")

    def test_explicit_path_preserved(self, tmp_path):
        custom = str(tmp_path / "sd_mount")
        result = transfer_logs._normalize_sd_path(custom)
        assert result == Path(custom)


class TestTransferLogs:
    def test_missing_sd_path_reports_error_and_returns(self, tmp_path, capsys, monkeypatch):
        fake_module_file = tmp_path / "transfer_logs.py"
        monkeypatch.setattr(transfer_logs, "__file__", str(fake_module_file))

        missing = tmp_path / "does_not_exist"
        transfer_logs.transfer_logs(sd_drive=str(missing))

        out = capsys.readouterr().out
        assert "[ERROR] SD card not found" in out

    def test_empty_sd_reports_no_files(self, tmp_path, capsys, monkeypatch):
        fake_module_file = tmp_path / "transfer_logs.py"
        monkeypatch.setattr(transfer_logs, "__file__", str(fake_module_file))

        sd = tmp_path / "sd"
        sd.mkdir()

        transfer_logs.transfer_logs(sd_drive=str(sd))
        out = capsys.readouterr().out
        assert "[INFO] No files found" in out

    def test_dry_run_lists_files_without_copying_or_deleting(self, tmp_path, capsys, monkeypatch):
        fake_module_file = tmp_path / "transfer_logs.py"
        monkeypatch.setattr(transfer_logs, "__file__", str(fake_module_file))

        sd = tmp_path / "sd"
        nested = sd / "nested"
        nested.mkdir(parents=True)
        file_a = sd / "a.txt"
        file_b = nested / "b.log"
        file_a.write_text("hello")
        file_b.write_text("world")

        transfer_logs.transfer_logs(sd_drive=str(sd), dry_run=True)
        out = capsys.readouterr().out

        assert "[DRY RUN] Would copy" in out
        assert file_a.exists()
        assert file_b.exists()
        assert not (tmp_path / "logs").exists()

    def test_successful_transfer_copies_and_deletes_source(self, tmp_path, monkeypatch):
        fake_module_file = tmp_path / "transfer_logs.py"
        monkeypatch.setattr(transfer_logs, "__file__", str(fake_module_file))

        sd = tmp_path / "sd"
        nested = sd / "nested"
        nested.mkdir(parents=True)
        (sd / "a.txt").write_text("alpha")
        (nested / "b.log").write_text("beta")

        transfer_logs.transfer_logs(sd_drive=str(sd), dry_run=False, keep_source=False)

        logs_root = tmp_path / "logs"
        archives = list(logs_root.iterdir())
        assert len(archives) == 1
        archive = archives[0]

        assert (archive / "a.txt").read_text() == "alpha"
        assert (archive / "nested" / "b.log").read_text() == "beta"
        assert not (sd / "a.txt").exists()
        assert not (nested / "b.log").exists()

    def test_keep_source_retains_files_on_sd(self, tmp_path, monkeypatch):
        fake_module_file = tmp_path / "transfer_logs.py"
        monkeypatch.setattr(transfer_logs, "__file__", str(fake_module_file))

        sd = tmp_path / "sd"
        sd.mkdir(parents=True)
        src = sd / "keep.txt"
        src.write_text("keep me")

        transfer_logs.transfer_logs(sd_drive=str(sd), keep_source=True)

        logs_root = tmp_path / "logs"
        archive = next(logs_root.iterdir())
        assert (archive / "keep.txt").read_text() == "keep me"
        assert src.exists()

    def test_copy_failure_is_reported(self, tmp_path, capsys, monkeypatch):
        fake_module_file = tmp_path / "transfer_logs.py"
        monkeypatch.setattr(transfer_logs, "__file__", str(fake_module_file))

        sd = tmp_path / "sd"
        sd.mkdir(parents=True)
        src = sd / "bad.txt"
        src.write_text("x")

        def _copy_raises(*args, **kwargs):
            raise OSError("copy failed")

        monkeypatch.setattr(transfer_logs.shutil, "copy2", _copy_raises)

        transfer_logs.transfer_logs(sd_drive=str(sd), keep_source=False)
        out = capsys.readouterr().out

        assert "[ERROR] Failed to copy bad.txt" in out
        assert src.exists()

    def test_delete_failure_is_warning_not_fatal(self, tmp_path, capsys, monkeypatch):
        fake_module_file = tmp_path / "transfer_logs.py"
        monkeypatch.setattr(transfer_logs, "__file__", str(fake_module_file))

        sd = tmp_path / "sd"
        sd.mkdir(parents=True)
        src = sd / "nodelete.txt"
        src.write_text("value")

        original_unlink = Path.unlink

        def _unlink_with_failure(path_self, *args, **kwargs):
            if path_self == src:
                raise PermissionError("locked")
            return original_unlink(path_self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _unlink_with_failure)

        transfer_logs.transfer_logs(sd_drive=str(sd), keep_source=False)
        out = capsys.readouterr().out

        assert "[WARN] Failed to delete nodelete.txt" in out
        assert src.exists()


class TestMainCli:
    def test_main_parses_args_and_calls_transfer(self, monkeypatch):
        called = {}

        def _capture(**kwargs):
            called.update(kwargs)

        monkeypatch.setattr(transfer_logs, "transfer_logs", _capture)
        monkeypatch.setattr(
            transfer_logs.argparse.ArgumentParser,
            "parse_args",
            Mock(return_value=Mock(sd_drive="H:", dry_run=True, keep_source=True)),
        )

        transfer_logs.main()

        assert called == {
            "sd_drive": "H:",
            "dry_run": True,
            "keep_source": True,
        }
