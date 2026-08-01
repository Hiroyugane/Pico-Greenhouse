"""Tests for lib/version.py — the firmware/app identity helper (punch item P2).

All three fallback rungs are exercised: a frozen ``fw_info`` (device with our
custom firmware), ``os.uname()`` (device running stock MicroPython), and the
host simulator. The device rungs are reached by injecting modules into
``sys.modules`` and reloading, the same trick test_oled_display uses for
``_BUILD_VERSION``.
"""

import sys
import types

import pytest


@pytest.fixture
def version_module():
    """Import lib.version fresh, and restore sys.modules afterwards."""
    saved = {name: sys.modules.get(name) for name in ("lib.version", "fw_info", "build_info")}
    for name in saved:
        sys.modules.pop(name, None)
    import lib.version as module

    yield module
    for name, original in saved.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def _reload(module):
    import importlib

    return importlib.reload(module)


def _fake_fw_info(version="pg-fw-2026.07-a1b2c3d", abi=6, source="upstream@v1.24.1@8f2c9d1", frozen_at="2026-07-22Z"):
    module = types.ModuleType("fw_info")
    module.FIRMWARE_VERSION = version
    module.MPY_ABI = abi
    module.MPY_SOURCE = source
    module.FROZEN_AT = frozen_at
    return module


class TestResolveFirmware:
    def test_frozen_fw_info_wins(self, version_module):
        sys.modules["fw_info"] = _fake_fw_info()
        try:
            assert version_module.resolve_firmware() == (
                "pg-fw-2026.07-a1b2c3d",
                6,
                "upstream@v1.24.1@8f2c9d1",
                "2026-07-22Z",
            )
        finally:
            sys.modules.pop("fw_info", None)

    def test_frozen_fw_info_without_frozen_at_still_resolves(self, version_module):
        module = _fake_fw_info()
        del module.FROZEN_AT
        sys.modules["fw_info"] = module
        try:
            assert version_module.resolve_firmware()[3] == "?"
        finally:
            sys.modules.pop("fw_info", None)

    def test_falls_back_to_uname_on_stock_micropython(self, version_module, monkeypatch):
        """No fw_info, but a MicroPython runtime: name the build from os.uname()."""
        import os as real_os

        uname_result = types.SimpleNamespace(
            release="1.24.1",
            version="v1.24.1 on 2026-07-01 (GNU 13.2.0 MinSizeRel)",
            machine="Raspberry Pi Pico with RP2040",
        )
        monkeypatch.setattr(real_os, "uname", lambda: uname_result, raising=False)
        monkeypatch.setattr(
            sys, "implementation", types.SimpleNamespace(name="micropython", _mpy=0x0206), raising=False
        )
        sys.modules.pop("fw_info", None)

        firmware_version, abi, source, frozen_at = version_module.resolve_firmware()
        assert firmware_version == "1.24.1/v1.24.1"
        assert abi == 6
        assert source == "uname"
        assert frozen_at == "?"

    def test_host_falls_back_to_dev(self, version_module):
        """CPython: no fw_info, implementation.name is not micropython."""
        sys.modules.pop("fw_info", None)
        assert version_module.resolve_firmware() == ("dev", 0, "host", "?")


class TestMpyAbiFromSys:
    def test_takes_the_low_byte(self, version_module, monkeypatch):
        monkeypatch.setattr(sys, "implementation", types.SimpleNamespace(name="micropython", _mpy=0x0206))
        assert version_module._mpy_abi_from_sys() == 6

    def test_zero_when_attribute_absent(self, version_module):
        # CPython's sys.implementation has no _mpy.
        assert version_module._mpy_abi_from_sys() == 0


class TestCurrentMpyAbi:
    def test_prefers_the_frozen_value(self, version_module, monkeypatch):
        monkeypatch.setattr(version_module, "MPY_ABI", 6)
        assert version_module.current_mpy_abi() == 6

    def test_falls_back_to_the_runtime(self, version_module, monkeypatch):
        monkeypatch.setattr(version_module, "MPY_ABI", 0)
        monkeypatch.setattr(version_module, "_mpy_abi_from_sys", lambda: 5)
        assert version_module.current_mpy_abi() == 5

    def test_none_when_nothing_knows(self, version_module, monkeypatch):
        """Unknown must be None, not 0 — the guard has to skip, not compare."""
        monkeypatch.setattr(version_module, "MPY_ABI", 0)
        monkeypatch.setattr(version_module, "_mpy_abi_from_sys", lambda: 0)
        assert version_module.current_mpy_abi() is None


class TestResolveApp:
    def test_reads_build_info_when_present(self, version_module):
        module = types.ModuleType("build_info")
        module.VERSION = "a1b2c3d"
        module.BUILD_TIME = "2026-07-22T15:40:00Z"
        sys.modules["lib.build_info"] = module
        try:
            assert version_module.resolve_app() == ("a1b2c3d", "2026-07-22T15:40:00Z")
        finally:
            sys.modules.pop("lib.build_info", None)

    def test_dev_when_build_info_absent(self, version_module, monkeypatch):
        """build_info is gitignored and absent on a fresh checkout."""
        import builtins

        real_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):
            if name in ("lib.build_info", "build_info"):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocking_import)
        sys.modules.pop("lib.build_info", None)
        sys.modules.pop("build_info", None)
        assert version_module.resolve_app() == ("dev", "?")


class TestDescribe:
    def test_names_every_field(self, version_module, monkeypatch):
        monkeypatch.setattr(version_module, "FIRMWARE_VERSION", "pg-fw-2026.07-a1b2c3d")
        monkeypatch.setattr(version_module, "APP_VERSION", "deadbee")
        monkeypatch.setattr(version_module, "MPY_ABI", 6)
        monkeypatch.setattr(version_module, "MPY_SOURCE", "upstream@v1.24.1@8f2c9d1")
        monkeypatch.setattr(version_module, "BUILD_TIME", "2026-07-22T15:40:00Z")
        assert version_module.describe() == (
            "fw=pg-fw-2026.07-a1b2c3d app=deadbee mpy_abi=6 src=upstream@v1.24.1@8f2c9d1 built=2026-07-22T15:40:00Z"
        )

    def test_host_default_is_greppable_not_empty(self, version_module):
        reloaded = _reload(version_module)
        described = reloaded.describe()
        assert described.startswith("fw=")
        assert "app=" in described


class TestResolveFrozenModules:
    """The record the OTA prune sweep will not delete a /lib file without."""

    def test_reads_the_frozen_record(self, version_module):
        module = _fake_fw_info()
        module.FROZEN_MODULES = ("sht31", "event_logger")
        sys.modules["fw_info"] = module
        try:
            assert version_module.resolve_frozen_modules() == ("sht31", "event_logger")
        finally:
            sys.modules.pop("fw_info", None)

    def test_a_firmware_without_the_field_reports_unknown(self, version_module):
        """Pre-2026-07-28 images carry no record; that is 'cannot tell', not 'none'."""
        sys.modules["fw_info"] = _fake_fw_info()
        try:
            assert version_module.resolve_frozen_modules() == ()
        finally:
            sys.modules.pop("fw_info", None)

    def test_stock_firmware_reports_unknown(self, version_module):
        sys.modules.pop("fw_info", None)
        assert version_module.resolve_frozen_modules() == ()

    def test_names_are_coerced_to_a_tuple_of_str(self, version_module):
        """A list in the generated module must not leak a mutable into the guard."""
        module = _fake_fw_info()
        module.FROZEN_MODULES = ["sht31"]
        sys.modules["fw_info"] = module
        try:
            result = version_module.resolve_frozen_modules()
            assert result == ("sht31",)
            assert isinstance(result, tuple)
        finally:
            sys.modules.pop("fw_info", None)

    def test_current_frozen_modules_exposes_the_resolved_value(self, version_module):
        module = _fake_fw_info()
        module.FROZEN_MODULES = ("sht31",)
        sys.modules["fw_info"] = module
        try:
            reloaded = _reload(version_module)
            assert reloaded.current_frozen_modules() == ("sht31",)
        finally:
            sys.modules.pop("fw_info", None)
            _reload(version_module)
