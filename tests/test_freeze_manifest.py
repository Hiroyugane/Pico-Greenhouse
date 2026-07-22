"""Tests for tools/freeze_manifest.py — the module set baked into the firmware.

The manifest is executed by MicroPython's makemanifest.py with freeze/module/
package/include injected as globals, so it is exercised here the same way:
exec it with recording stubs and assert on what it asked to freeze.

The load-bearing assertions are the negative ones. A frozen module cannot be
fixed by OTA — only by rebuilding and reflashing every unit — so anything that
*decides* when actuators run must never end up in this list (plan section 2).
"""

import sys
from pathlib import Path

import pytest

MANIFEST = Path(__file__).resolve().parents[1] / "tools" / "freeze_manifest.py"

# Modules whose presence in a frozen image would cost a fleet reflash to undo.
# Each is here for a reason spelled out in the plan; see the manifest header.
NEVER_FREEZE = (
    "updater.py",
    "updater_feedback.py",
    "oled_display.py",
    "relay.py",
    "fan_controllers.py",
    "fan_output.py",
    "regulation_adapters.py",
    "regulation_engine.py",
    "regulation_surface.py",
    "regulation_arbiter.py",
    "regulation_normalizer.py",
    "co2_logger.py",
    "build_info.py",
)


class _Recorder:
    def __init__(self):
        self.packages = []
        self.modules = []
        self.includes = []

    def _package(self, name, files=(), base_path=None, **kw):
        self.packages.append((name, tuple(files), base_path))

    def as_globals(self):
        return {
            "package": self._package,
            "module": lambda name, base_path=None, **kw: self.modules.append((name, base_path)),
            "include": lambda path, **kw: self.includes.append(path),
            "freeze": lambda *a, **kw: None,
            "require": lambda *a, **kw: None,
            "options": object(),
        }


def _exec_manifest(monkeypatch, **env):
    """Run the manifest with recording stubs; returns the recorder."""
    monkeypatch.setenv("PG_REPO_DIR", env.pop("PG_REPO_DIR", "/repo"))
    monkeypatch.setenv("PG_FW_INFO_DIR", env.pop("PG_FW_INFO_DIR", "/repo/build/frozen"))
    for key in ("PG_FREEZE_TIER2", "PG_FREEZE_ONLY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    recorder = _Recorder()
    namespace = recorder.as_globals()
    exec(compile(MANIFEST.read_text(encoding="utf-8"), str(MANIFEST), "exec"), namespace)
    return recorder


def _frozen_files(recorder):
    files = []
    for _name, package_files, _base in recorder.packages:
        files.extend(package_files)
    return files


class TestDefaultScope:
    def test_freezes_the_tier1_set_as_the_lib_package(self, monkeypatch):
        recorder = _exec_manifest(monkeypatch)
        assert len(recorder.packages) == 1
        name, files, base_path = recorder.packages[0]
        assert name == "lib"
        assert base_path == "/repo"
        assert "sdcard.py" in files
        assert "i2c_guard.py" in files

    def test_tier2_is_not_frozen_by_default(self, monkeypatch):
        """Blocked on the next-rev migration closing — see plan 2.2."""
        assert "hardware_factory.py" not in _frozen_files(_exec_manifest(monkeypatch))

    @pytest.mark.parametrize("module_name", NEVER_FREEZE)
    def test_decision_modules_are_never_frozen(self, monkeypatch, module_name):
        recorder = _exec_manifest(monkeypatch)
        assert module_name not in _frozen_files(recorder)

    def test_fw_info_is_frozen_from_the_generated_directory(self, monkeypatch):
        recorder = _exec_manifest(monkeypatch)
        assert ("fw_info.py", "/repo/build/frozen") in recorder.modules

    def test_keeps_the_port_board_manifest(self, monkeypatch):
        """Dropping it would take asyncio with it, and the whole task model."""
        recorder = _exec_manifest(monkeypatch)
        assert any("boards/manifest.py" in path for path in recorder.includes)

    def test_every_frozen_module_exists_in_lib(self, monkeypatch):
        """A typo here fails the firmware build, not the test suite — catch it early."""
        lib_dir = MANIFEST.resolve().parents[1] / "lib"
        for name in _frozen_files(_exec_manifest(monkeypatch)):
            assert (lib_dir / name).is_file(), f"{name} is frozen but not present in lib/"


class TestTier2OptIn:
    def test_tier2_flag_adds_the_plumbing_set(self, monkeypatch):
        files = _frozen_files(_exec_manifest(monkeypatch, PG_FREEZE_TIER2="1"))
        assert "hardware_factory.py" in files
        assert "sdcard.py" in files, "tier 2 must extend tier 1, not replace it"

    def test_tier2_still_excludes_co2_logger(self, monkeypatch):
        """Its sense half is stable; the hysteresis override it also carries is not."""
        assert "co2_logger.py" not in _frozen_files(_exec_manifest(monkeypatch, PG_FREEZE_TIER2="1"))

    def test_every_tier2_module_exists_in_lib(self, monkeypatch):
        lib_dir = MANIFEST.resolve().parents[1] / "lib"
        for name in _frozen_files(_exec_manifest(monkeypatch, PG_FREEZE_TIER2="1")):
            assert (lib_dir / name).is_file(), f"{name} is frozen but not present in lib/"


class TestFreezeOnly:
    def test_subset_selection_replaces_the_tier(self, monkeypatch):
        """The P0.5 loop freezes the coldest modules first and re-measures."""
        files = _frozen_files(_exec_manifest(monkeypatch, PG_FREEZE_ONLY="sdcard.py, ds3231.py"))
        assert files == ["sdcard.py", "ds3231.py"]

    def test_unknown_module_name_is_a_hard_error(self, monkeypatch):
        with pytest.raises(SystemExit, match="unknown modules"):
            _exec_manifest(monkeypatch, PG_FREEZE_ONLY="sdcard.py,nonexistent.py")


class TestEnvironmentContract:
    def test_missing_repo_dir_refuses_to_run(self, monkeypatch):
        monkeypatch.delenv("PG_REPO_DIR", raising=False)
        monkeypatch.setenv("PG_FW_INFO_DIR", "/repo/build/frozen")
        with pytest.raises(SystemExit, match="PG_REPO_DIR"):
            exec(compile(MANIFEST.read_text(encoding="utf-8"), str(MANIFEST), "exec"), _Recorder().as_globals())

    def test_missing_fw_info_dir_refuses_to_run(self, monkeypatch):
        monkeypatch.setenv("PG_REPO_DIR", "/repo")
        monkeypatch.delenv("PG_FW_INFO_DIR", raising=False)
        with pytest.raises(SystemExit, match="PG_FW_INFO_DIR"):
            exec(compile(MANIFEST.read_text(encoding="utf-8"), str(MANIFEST), "exec"), _Recorder().as_globals())


class TestBuildScript:
    """The PowerShell builder is not runnable here (no ARM toolchain), but a
    syntax error in it must not wait until someone has installed one."""

    SCRIPT = MANIFEST.resolve().parent / "build_firmware.ps1"

    def test_script_exists(self):
        assert self.SCRIPT.is_file()

    def test_script_is_pure_ascii(self):
        """Windows PowerShell 5.1 reads a BOM-less UTF-8 .ps1 as ANSI.

        One em dash inside a quoted string is then decoded as three cp1252
        characters, one of which closes the string early and the whole script
        stops parsing. Keeping it ASCII sidesteps the encoding question
        entirely.
        """
        raw = self.SCRIPT.read_bytes()
        offenders = sorted({byte for byte in raw if byte > 127})
        assert not offenders, f"non-ASCII bytes in build_firmware.ps1: {offenders}"

    @pytest.mark.skipif(sys.platform != "win32", reason="PowerShell parser is Windows-only here")
    def test_script_parses(self):
        import subprocess

        command = (
            "$errors = $null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{self.SCRIPT}', [ref]$null, [ref]$errors) "
            "| Out-Null; "
            "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.Message }; exit 1 }; exit 0"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
