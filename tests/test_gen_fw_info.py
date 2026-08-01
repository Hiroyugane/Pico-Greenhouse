"""Tests for tools/gen_fw_info.py — the frozen firmware-identity generator."""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.gen_fw_info import (  # noqa: E402
    FwInfoError,
    build,
    firmware_version,
    main,
    mpy_source,
    read_mpy_abi,
    render,
)


def _fake_checkout(tmp_path: Path, define: str = "#define MPY_VERSION (6)", where: str = "py/persistentcode.h") -> Path:
    header = tmp_path / where
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text(f"/* header */\n{define}\n#define MPY_SUB_VERSION (3)\n")
    return tmp_path


class TestReadMpyAbi:
    def test_reads_parenthesised_define(self, tmp_path):
        assert read_mpy_abi(_fake_checkout(tmp_path)) == 6

    def test_reads_bare_define(self, tmp_path):
        assert read_mpy_abi(_fake_checkout(tmp_path, "#define MPY_VERSION 7")) == 7

    def test_rejects_a_non_checkout(self, tmp_path):
        with pytest.raises(FwInfoError, match="not a MicroPython checkout"):
            read_mpy_abi(tmp_path)

    def test_rejects_a_header_without_the_define(self, tmp_path):
        header = tmp_path / "py" / "mpconfig.h"
        header.parent.mkdir(parents=True)
        header.write_text("/* nothing useful here */\n")
        with pytest.raises(FwInfoError, match="no MPY_VERSION"):
            read_mpy_abi(tmp_path)

    def test_reads_it_from_persistentcode_header(self, tmp_path):
        """Where v1.28.0 keeps it — this is what broke the first real build."""
        assert read_mpy_abi(_fake_checkout(tmp_path, where="py/persistentcode.h")) == 6

    def test_falls_back_to_mpconfig_for_older_trees(self, tmp_path):
        """Older releases defined it in py/mpconfig.h; both layouts must work."""
        assert read_mpy_abi(_fake_checkout(tmp_path, where="py/mpconfig.h")) == 6

    def test_prefers_persistentcode_when_both_exist(self, tmp_path):
        _fake_checkout(tmp_path, define="#define MPY_VERSION 6", where="py/persistentcode.h")
        _fake_checkout(tmp_path, define="#define MPY_VERSION 5", where="py/mpconfig.h")
        assert read_mpy_abi(tmp_path) == 6


class TestFields:
    def test_firmware_version_shape(self, monkeypatch):
        import tools.gen_fw_info as module

        monkeypatch.setattr(module, "repo_short_hash", lambda *a, **k: "a1b2c3d")
        built = dt.datetime(2026, 7, 22, 15, 40, tzinfo=dt.timezone.utc)
        assert firmware_version(built) == "pg-fw-2026.07-a1b2c3d"

    def test_mpy_source_records_fork_tag_and_commit(self):
        assert mpy_source("upstream", "v1.24.1", "8f2c9d1") == "upstream@v1.24.1@8f2c9d1"


class TestRender:
    def test_module_is_importable_and_carries_the_fields(self, tmp_path):
        body = render(
            firmware_version="pg-fw-2026.07-a1b2c3d",
            mpy_abi=6,
            mpy_source="upstream@v1.24.1@8f2c9d1",
            frozen_at="2026-07-22T15:40:00Z",
        )
        path = tmp_path / "fw_info.py"
        path.write_text(body)
        namespace: dict = {}
        exec(compile(path.read_text(), str(path), "exec"), namespace)
        assert namespace["FIRMWARE_VERSION"] == "pg-fw-2026.07-a1b2c3d"
        assert namespace["MPY_ABI"] == 6
        assert namespace["MPY_SOURCE"] == "upstream@v1.24.1@8f2c9d1"
        assert namespace["FROZEN_AT"] == "2026-07-22T15:40:00Z"

    def test_abi_is_an_int_not_a_string(self, tmp_path):
        """The updater compares it numerically; a quoted ABI would silently mismatch."""
        body = render(firmware_version="v", mpy_abi=6, mpy_source="s", frozen_at="t")
        assert "MPY_ABI = 6\n" in body


class TestBuild:
    def test_reads_the_abi_from_the_checkout(self, tmp_path, monkeypatch):
        import tools.gen_fw_info as module

        monkeypatch.setattr(module, "repo_short_hash", lambda *a, **k: "a1b2c3d")
        monkeypatch.setattr(module, "tree_commit", lambda *a, **k: "8f2c9d1")
        body = build(
            mpy_tree=_fake_checkout(tmp_path),
            ref="v1.24.1",
            built_at=dt.datetime(2026, 7, 22, 15, 40, tzinfo=dt.timezone.utc),
        )
        assert "MPY_ABI = 6" in body
        assert 'MPY_SOURCE = "upstream@v1.24.1@8f2c9d1"' in body
        assert 'FROZEN_AT = "2026-07-22T15:40:00Z"' in body

    def test_explicit_abi_override_needs_no_checkout(self, monkeypatch):
        import tools.gen_fw_info as module

        monkeypatch.setattr(module, "repo_short_hash", lambda *a, **k: "a1b2c3d")
        body = build(mpy_tree=None, ref="v1.24.1", mpy_abi=6, commit="8f2c9d1")
        assert "MPY_ABI = 6" in body

    def test_refuses_to_guess_the_abi(self):
        """No tree and no override: fail loudly rather than stamp a wrong ABI."""
        with pytest.raises(FwInfoError, match="bytecode ABI"):
            build(mpy_tree=None, ref="v1.24.1")


class TestCli:
    def test_writes_the_module(self, tmp_path, capsys, monkeypatch):
        import tools.gen_fw_info as module

        monkeypatch.setattr(module, "repo_short_hash", lambda *a, **k: "a1b2c3d")
        out = tmp_path / "out" / "fw_info.py"
        assert main(["--mpy-abi", "6", "--ref", "v1.24.1", "--commit", "8f2c9d1", "--out", str(out)]) == 0
        assert out.is_file()
        assert "MPY_ABI = 6" in out.read_text()
        assert str(out) in capsys.readouterr().out

    def test_missing_abi_exits_nonzero(self, tmp_path, capsys):
        out = tmp_path / "fw_info.py"
        assert main(["--ref", "v1.24.1", "--out", str(out)]) == 1
        assert "bytecode ABI" in capsys.readouterr().err
        assert not out.exists()


class TestFrozenModulesRecord:
    """FROZEN_MODULES must describe the image being built, never the manifest's full set.

    The OTA prune sweep deletes /lib files on the strength of this record, so a
    record that over-claims removes a module with no frozen twin.
    """

    def test_records_the_default_freeze_set(self):
        from tools.gen_fw_info import resolve_frozen_modules

        modules = resolve_frozen_modules()

        assert "sdcard" in modules
        assert "sht31" in modules
        assert "event_logger" in modules, "Tier 2 is part of the default set"
        assert all(not name.endswith(".py") for name in modules)

    def test_tier1_only_narrows_the_record(self):
        from tools.gen_fw_info import resolve_frozen_modules

        full = resolve_frozen_modules()
        tier1 = resolve_frozen_modules(tier1_only=True)

        assert "sht31" in tier1
        assert "event_logger" not in tier1, "a Tier-2 module is not frozen in a Tier-1 build"
        assert set(tier1) < set(full)

    def test_freeze_only_narrows_the_record(self):
        from tools.gen_fw_info import resolve_frozen_modules

        assert resolve_frozen_modules(freeze_only="sht31.py,ds3231.py") == ("sht31", "ds3231")

    def test_freeze_only_accepts_bare_stems(self):
        from tools.gen_fw_info import resolve_frozen_modules

        assert resolve_frozen_modules(freeze_only="sht31") == ("sht31",)

    def test_freeze_only_rejects_an_unknown_name(self):
        """A typo in the build invocation must fail the build, not ship a lie."""
        from tools.gen_fw_info import FwInfoError, resolve_frozen_modules

        with pytest.raises(FwInfoError, match="unknown modules"):
            resolve_frozen_modules(freeze_only="not_a_module")

    def test_rendered_module_exposes_the_names(self, tmp_path):
        from tools.gen_fw_info import render

        body = render(
            firmware_version="pg-fw-2026.07-abc1234",
            mpy_abi=6,
            mpy_source="upstream@v1.24.1@8f2c9d1",
            frozen_at="2026-07-28T10:00:00Z",
            frozen_modules=("sht31", "event_logger"),
        )
        path = tmp_path / "fw_info.py"
        path.write_text(body)
        namespace: dict = {}
        exec(compile(body, str(path), "exec"), namespace)

        assert namespace["FROZEN_MODULES"] == ("sht31", "event_logger")

    def test_an_empty_record_renders_as_an_empty_tuple(self):
        from tools.gen_fw_info import render

        body = render(
            firmware_version="v",
            mpy_abi=6,
            mpy_source="s",
            frozen_at="t",
            frozen_modules=(),
        )
        namespace: dict = {}
        exec(compile(body, "<fw_info>", "exec"), namespace)

        assert namespace["FROZEN_MODULES"] == ()

    def test_build_stamps_the_record(self, monkeypatch):
        import tools.gen_fw_info as mod

        monkeypatch.setattr(mod, "repo_short_hash", lambda repo_root=None: "abc1234")
        body = mod.build(mpy_tree=None, ref="v1.24.1", commit="8f2c9d1", mpy_abi=6, tier1_only=True)
        namespace: dict = {}
        exec(compile(body, "<fw_info>", "exec"), namespace)

        assert "sht31" in namespace["FROZEN_MODULES"]
        assert "event_logger" not in namespace["FROZEN_MODULES"]
