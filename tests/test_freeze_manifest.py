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
    for key in ("PG_FREEZE_TIER1_ONLY", "PG_FREEZE_ONLY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    recorder = _Recorder()
    namespace = recorder.as_globals()
    exec(compile(MANIFEST.read_text(encoding="utf-8"), str(MANIFEST), "exec"), namespace)
    return recorder


def _frozen_files(recorder):
    """Frozen module filenames, excluding the generated fw_info."""
    return [name for name, _base in recorder.modules if name != "fw_info.py"]


class TestDefaultScope:
    def test_freezes_as_top_level_modules_not_a_lib_package(self, monkeypatch):
        """A package cannot be split across frozen and filesystem.

        Freezing package("lib", ...) produced a firmware that contained every
        module and could import none of them: sys.path is ['', '.frozen',
        '/lib'], so the filesystem /lib directory (which must exist, for the
        mutable modules) claims the name `lib` first and the frozen package is
        never consulted. Top-level names sidestep that entirely.
        """
        recorder = _exec_manifest(monkeypatch)
        assert recorder.packages == [], "no package() call may reintroduce the shadowing bug"
        assert ("sdcard.py", "/repo/lib") in recorder.modules
        assert ("i2c_guard.py", "/repo/lib") in recorder.modules

    def test_tier2_is_frozen_by_default(self, monkeypatch):
        """Operator decision 2026-07-23, after P0.5 measured the heap 97.5% full."""
        assert "hardware_factory.py" in _frozen_files(_exec_manifest(monkeypatch))

    @pytest.mark.parametrize("module_name", NEVER_FREEZE)
    def test_decision_modules_are_never_frozen(self, monkeypatch, module_name):
        recorder = _exec_manifest(monkeypatch)
        assert module_name not in _frozen_files(recorder)

    def test_fw_info_is_frozen_from_the_generated_directory(self, monkeypatch):
        recorder = _exec_manifest(monkeypatch)
        assert ("fw_info.py", "/repo/build/frozen") in recorder.modules

    def test_frozen_modules_come_from_the_lib_source_directory(self, monkeypatch):
        """Sources still live in lib/ in the repo; only the frozen NAME is top-level."""
        recorder = _exec_manifest(monkeypatch)
        bases = {base for name, base in recorder.modules if name != "fw_info.py"}
        assert bases == {"/repo/lib"}

    def test_keeps_the_port_board_manifest(self, monkeypatch):
        """Dropping it would take asyncio with it, and the whole task model."""
        recorder = _exec_manifest(monkeypatch)
        assert any("boards/manifest.py" in path for path in recorder.includes)

    def test_every_frozen_module_exists_in_lib(self, monkeypatch):
        """A typo here fails the firmware build, not the test suite — catch it early."""
        lib_dir = MANIFEST.resolve().parents[1] / "lib"
        for name in _frozen_files(_exec_manifest(monkeypatch)):
            assert (lib_dir / name).is_file(), f"{name} is frozen but not present in lib/"


class TestTier1OnlyOptOut:
    def test_flag_restricts_to_tier1(self, monkeypatch):
        files = _frozen_files(_exec_manifest(monkeypatch, PG_FREEZE_TIER1_ONLY="1"))
        assert "sdcard.py" in files
        assert "hardware_factory.py" not in files

    def test_default_scope_extends_tier1_rather_than_replacing_it(self, monkeypatch):
        files = _frozen_files(_exec_manifest(monkeypatch))
        assert "sdcard.py" in files and "hardware_factory.py" in files

    def test_co2_logger_is_excluded_from_every_scope(self, monkeypatch):
        """Its sense half is stable; the hysteresis override it also carries is not."""
        assert "co2_logger.py" not in _frozen_files(_exec_manifest(monkeypatch))
        assert "co2_logger.py" not in _frozen_files(_exec_manifest(monkeypatch, PG_FREEZE_TIER1_ONLY="1"))


class TestFreezeOnly:
    def test_subset_selection_replaces_the_tier(self, monkeypatch):
        """The P0.5 loop freezes the coldest modules first and re-measures."""
        files = _frozen_files(_exec_manifest(monkeypatch, PG_FREEZE_ONLY="sdcard.py, ds3231.py"))
        assert sorted(files) == ["ds3231.py", "sdcard.py"]

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
    """The builders take minutes to fail for real reasons (clone, submodules,
    compile). A syntax error in one must not cost that round trip."""

    SCRIPT = MANIFEST.resolve().parent / "build_firmware.ps1"
    SH_SCRIPT = MANIFEST.resolve().parent / "build_firmware.sh"

    def test_script_exists(self):
        assert self.SCRIPT.is_file()

    def test_shell_script_exists(self):
        assert self.SH_SCRIPT.is_file()

    def test_shell_script_has_lf_endings(self):
        """CRLF makes bash report 'bad interpreter' and breaks every heredoc.

        The file is executed inside WSL, and git on this machine converts line
        endings on checkout unless .gitattributes pins it — which it now does.
        """
        assert b"\r\n" not in self.SH_SCRIPT.read_bytes()

    def test_shell_script_parses(self):
        import shutil
        import subprocess

        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("no bash available to syntax-check with")
        # Relative path + cwd, not an absolute Windows path: which() may find
        # the WSL launcher (system32\bash.exe), whose bash cannot resolve
        # "L:\..." but does inherit the Windows cwd as /mnt/<drive>/....
        result = subprocess.run(
            [bash, "-n", f"tools/{self.SH_SCRIPT.name}"],
            cwd=self.SH_SCRIPT.parents[1],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr

    def test_both_builders_agree_on_the_manifest_contract(self):
        """Both set the same env vars — the manifest hard-errors without them."""
        ps1 = self.SCRIPT.read_text(encoding="utf-8")
        sh = self.SH_SCRIPT.read_text(encoding="utf-8")
        for name in ("PG_REPO_DIR", "PG_FW_INFO_DIR", "PG_FREEZE_TIER1_ONLY", "PG_FREEZE_ONLY"):
            assert name in ps1, f"{name} missing from the PowerShell builder"
            assert name in sh, f"{name} missing from the shell builder"

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
