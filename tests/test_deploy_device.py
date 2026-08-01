"""Tests for tools/deploy_device.py — the mutable-app deploy over mpremote."""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import deploy_device  # noqa: E402
from tools.deploy_device import (  # noqa: E402
    DeployError,
    compile_set,
    deploy_set,
    device_lib_files,
    mpy_abi_of,
    prune,
    push,
    remote_dirs,
    stale_shadows,
)


def _fake_mpy(path: Path, abi: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes([0x4D, abi]) + b"\x00\x00")


class TestDeploySet:
    def test_skips_frozen_modules(self):
        """They live in the firmware; copying them wastes scarce flash and is a no-op."""
        remotes = [remote for _src, remote in deploy_set()]
        assert "lib/sdcard.py" not in remotes
        assert "lib/i2c_guard.py" not in remotes

    def test_includes_the_mutable_decision_modules(self):
        remotes = [remote for _src, remote in deploy_set()]
        assert "lib/regulation_engine.py" in remotes
        assert "lib/updater.py" in remotes
        assert "config.py" in remotes

    def test_no_skip_frozen_sends_everything(self):
        remotes = [remote for _src, remote in deploy_set(skip_frozen=False)]
        assert "lib/sdcard.py" in remotes

    def test_main_py_is_last(self):
        """A half-finished deploy must not leave new wiring against old modules."""
        assert deploy_set()[-1][1] == "main.py"

    def test_excludes_package_init(self):
        assert "lib/__init__.py" not in [remote for _src, remote in deploy_set()]

    def test_missing_lib_dir_is_an_error(self, tmp_path):
        with pytest.raises(DeployError, match="lib/"):
            deploy_set(lib_dir=tmp_path / "nope")


class TestRemoteDirs:
    def test_collects_device_directories(self):
        entries = [(Path("a"), "config.py"), (Path("b"), "lib/relay.py")]
        assert remote_dirs(entries) == ["lib"]

    def test_no_directory_for_root_only_sets(self):
        assert remote_dirs([(Path("a"), "main.py")]) == []


class TestMpyAbiOf:
    def test_reads_the_abi_byte(self, tmp_path):
        path = tmp_path / "x.mpy"
        _fake_mpy(path, 6)
        assert mpy_abi_of(path) == 6

    def test_rejects_a_non_mpy(self, tmp_path):
        path = tmp_path / "x.mpy"
        path.write_bytes(b"# source\n")
        with pytest.raises(DeployError, match="bad magic"):
            mpy_abi_of(path)


class TestCompileSet:
    def _fake_cross(self, monkeypatch, abi=6, fail=False):
        def fake_run(cmd, capture_output=True, text=True):
            class Result:
                returncode = 1 if fail else 0
                stdout = ""
                stderr = "boom" if fail else ""

            if not fail:
                _fake_mpy(Path(cmd[cmd.index("-o") + 1]), abi)
            return Result()

        monkeypatch.setattr(deploy_device.subprocess, "run", fake_run)

    def test_compiles_everything_but_main(self, tmp_path, monkeypatch):
        self._fake_cross(monkeypatch)
        entries = [
            (tmp_path / "config.py", "config.py"),
            (tmp_path / "lib" / "relay.py", "lib/relay.py"),
            (tmp_path / "main.py", "main.py"),
        ]
        for source, _remote in entries:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("x = 1\n")

        out = compile_set(entries, mpy_cross="mpy-cross", out_dir=tmp_path / "out", expected_abi=6)
        remotes = [remote for _src, remote in out]
        assert remotes == ["config.mpy", "lib/relay.mpy", "main.py"]

    def test_refuses_an_abi_the_firmware_cannot_import(self, tmp_path, monkeypatch):
        """The whole point: a mismatched payload imports nowhere, on a board with no REPL."""
        self._fake_cross(monkeypatch, abi=5)
        source = tmp_path / "config.py"
        source.write_text("x = 1\n")
        with pytest.raises(DeployError, match="firmware imports ABI 6"):
            compile_set([(source, "config.py")], mpy_cross="mpy-cross", out_dir=tmp_path / "out", expected_abi=6)

    def test_allows_any_abi_when_the_firmware_is_unknown(self, tmp_path, monkeypatch):
        self._fake_cross(monkeypatch, abi=5)
        source = tmp_path / "config.py"
        source.write_text("x = 1\n")
        out = compile_set([(source, "config.py")], mpy_cross="mpy-cross", out_dir=tmp_path / "out", expected_abi=None)
        assert out[0][1] == "config.mpy"

    def test_compiler_failure_names_the_file(self, tmp_path, monkeypatch):
        self._fake_cross(monkeypatch, fail=True)
        source = tmp_path / "config.py"
        source.write_text("x = 1\n")
        with pytest.raises(DeployError, match="config.py"):
            compile_set([(source, "config.py")], mpy_cross="mpy-cross", out_dir=tmp_path / "out")


class TestPush:
    def _recorder(self, monkeypatch, *, mkdir_rc=0, mkdir_msg="", cp_rc=0):
        calls = []

        def fake_run(args, *, mpremote):
            calls.append(args)

            class Result:
                returncode = mkdir_rc if args[1] == "mkdir" else cp_rc
                stdout = mkdir_msg if args[1] == "mkdir" else ""
                stderr = ""

            return Result()

        monkeypatch.setattr(deploy_device, "_run_mpremote", fake_run)
        return calls

    def test_creates_directories_before_copying(self, monkeypatch):
        """The bug that started this: mpremote cp cannot create /lib."""
        calls = self._recorder(monkeypatch)
        push([(Path("a"), "lib/relay.mpy")])
        assert calls[0][:3] == ["fs", "mkdir", ":lib"]
        assert calls[1][:2] == ["fs", "cp"]

    @pytest.mark.parametrize(
        "message",
        [
            "OSError: [Errno 17] EEXIST",
            "mpremote: mkdir: lib: File exists.",  # what mpremote 1.28 actually prints
        ],
    )
    def test_existing_directory_is_not_an_error(self, monkeypatch, message):
        """Every deploy after the first hits this; the wording varies by version."""
        self._recorder(monkeypatch, mkdir_rc=1, mkdir_msg=message)
        assert push([(Path("a"), "lib/relay.mpy")]) == 1

    def test_other_mkdir_failures_do_raise(self, monkeypatch):
        self._recorder(monkeypatch, mkdir_rc=1, mkdir_msg="no device found")
        with pytest.raises(DeployError, match="could not create"):
            push([(Path("a"), "lib/relay.mpy")])

    def test_copy_failure_raises(self, monkeypatch):
        self._recorder(monkeypatch, cp_rc=1)
        with pytest.raises(DeployError, match="copy failed"):
            push([(Path("a"), "main.py")])

    def test_dry_run_touches_nothing(self, monkeypatch, capsys):
        calls = self._recorder(monkeypatch)
        assert push([(Path("a"), "lib/relay.mpy")], dry_run=True) == 1
        assert calls == []
        assert "mkdir" in capsys.readouterr().out


class TestFirmwareAbi:
    def test_reads_the_generated_fw_info(self, tmp_path, monkeypatch):
        fw = tmp_path / "fw_info.py"
        fw.write_text('FIRMWARE_VERSION = "x"\nMPY_ABI = 6\n')
        monkeypatch.setattr(deploy_device, "FW_INFO", fw)
        assert deploy_device.firmware_abi() == 6

    def test_none_without_a_local_build(self, tmp_path, monkeypatch):
        monkeypatch.setattr(deploy_device, "FW_INFO", tmp_path / "absent.py")
        monkeypatch.setattr(deploy_device, "BUILD_NOTE", tmp_path / "absent.json")
        assert deploy_device.firmware_abi() is None

    def test_falls_back_to_the_build_note(self, tmp_path, monkeypatch):
        note = tmp_path / "firmware-build.json"
        note.write_text('{"mpy_abi": 6}')
        monkeypatch.setattr(deploy_device, "FW_INFO", tmp_path / "absent.py")
        monkeypatch.setattr(deploy_device, "BUILD_NOTE", note)
        assert deploy_device.firmware_abi() == 6


class TestCli:
    def test_dry_run_lists_the_set(self, capsys, monkeypatch):
        monkeypatch.setattr(deploy_device, "compile_set", lambda entries, **kw: entries)
        assert deploy_device.main(["--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "deploy set" in out
        assert "frozen module(s)" in out

    def test_raw_mode_skips_compilation(self, capsys, monkeypatch):
        def explode(*a, **k):
            raise AssertionError("compile_set must not run in --raw mode")

        monkeypatch.setattr(deploy_device, "compile_set", explode)
        assert deploy_device.main(["--dry-run", "--raw"]) == 0
        assert "config.py" in capsys.readouterr().out


def _uf2_unused():  # pragma: no cover - keeps struct import meaningful if extended
    return struct


class TestStaleShadows:
    """A leftover pre-freeze copy in /lib wins over the frozen module.

    Nothing warns you when it happens: the module imports, the app runs, and
    the only symptom is a heap figure that did not improve.
    """

    ENTRIES = [(Path("a"), "config.py"), (Path("b"), "lib/relay.mpy")]

    def test_flags_a_shadow_of_a_frozen_module(self):
        stale = stale_shadows(["event_logger.mpy", "relay.mpy"], self.ENTRIES, ["event_logger"])
        assert stale == ["event_logger.mpy"]

    def test_flags_a_module_no_longer_shipped(self):
        stale = stale_shadows(["heater.mpy", "relay.mpy"], self.ENTRIES, [])
        assert stale == ["heater.mpy"]

    def test_keeps_everything_currently_shipped(self):
        assert stale_shadows(["relay.mpy"], self.ENTRIES, ["event_logger"]) == []

    def test_ignores_non_module_files(self):
        assert stale_shadows(["notes.txt"], self.ENTRIES, []) == []


class TestDeviceLibFiles:
    def test_parses_an_mpremote_listing(self, monkeypatch):
        def fake_run(args, *, mpremote):
            class Result:
                returncode = 0
                stdout = "ls :lib\n        3793 event_logger.mpy\n         722 relay.mpy\n"
                stderr = ""

            return Result()

        monkeypatch.setattr(deploy_device, "_run_mpremote", fake_run)
        assert device_lib_files() == ["event_logger.mpy", "relay.mpy"]

    def test_empty_when_lib_is_absent(self, monkeypatch):
        def fake_run(args, *, mpremote):
            class Result:
                returncode = 1
                stdout = ""
                stderr = "no such directory"

            return Result()

        monkeypatch.setattr(deploy_device, "_run_mpremote", fake_run)
        assert device_lib_files() == []


class TestPrune:
    def test_removes_each_file(self, monkeypatch):
        calls = []

        def fake_run(args, *, mpremote):
            calls.append(args)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        monkeypatch.setattr(deploy_device, "_run_mpremote", fake_run)
        assert prune(["event_logger.mpy"]) == 1
        assert calls == [["fs", "rm", ":lib/event_logger.mpy"]]

    def test_dry_run_deletes_nothing(self, monkeypatch, capsys):
        calls = []
        monkeypatch.setattr(deploy_device, "_run_mpremote", lambda args, *, mpremote: calls.append(args))
        assert prune(["event_logger.mpy"], dry_run=True) == 1
        assert calls == []
        assert "rm" in capsys.readouterr().out

    def test_failure_raises(self, monkeypatch):
        def fake_run(args, *, mpremote):
            class Result:
                returncode = 1
                stdout = ""
                stderr = "read-only"

            return Result()

        monkeypatch.setattr(deploy_device, "_run_mpremote", fake_run)
        with pytest.raises(DeployError, match="could not remove"):
            prune(["event_logger.mpy"])
