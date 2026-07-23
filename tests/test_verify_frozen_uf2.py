"""Tests for tools/verify_frozen_uf2.py — the pre-flash freeze check.

The failure this guards against is silent: a build where FROZEN_MANIFEST never
reached the port produces a working stock firmware, and every symptom shows up
only at runtime as a heap number that did not move.
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.verify_frozen_uf2 import (  # noqa: E402
    UF2_MAGIC_START0,
    UF2_MAGIC_START1,
    VerifyError,
    frozen_module_names,
    main,
    uf2_payload,
    verify,
)


def _uf2(payload: bytes, *, family: int = 0xE48BFF56) -> bytes:
    """Wrap a payload into UF2 blocks, 256 data bytes each (as picotool emits)."""
    chunks = [payload[i : i + 256] for i in range(0, max(len(payload), 1), 256)] or [b""]
    blocks = bytearray()
    for index, chunk in enumerate(chunks):
        header = struct.pack(
            "<8I",
            UF2_MAGIC_START0,
            UF2_MAGIC_START1,
            0x00002000,
            0x10000000 + index * 256,
            len(chunk),
            index,
            len(chunks),
            family,
        )
        blocks += header + chunk.ljust(256, b"\x00") + b"\x00" * (512 - 32 - 256)
    return bytes(blocks)


class TestUf2Payload:
    def test_reassembles_the_flash_image(self, tmp_path):
        payload = bytes(range(256)) * 4
        path = tmp_path / "fw.uf2"
        path.write_bytes(_uf2(payload))
        assert uf2_payload(path) == payload

    def test_finds_a_string_spanning_a_block_boundary(self, tmp_path):
        """The reason this reassembles instead of grepping the raw file."""
        payload = b"x" * 250 + b"i2c_guard" + b"y" * 300
        path = tmp_path / "fw.uf2"
        path.write_bytes(_uf2(payload))
        raw = path.read_bytes()
        assert b"i2c_guard" not in raw, "test is meaningless unless the name really straddles a block"
        assert b"i2c_guard" in uf2_payload(path)

    def test_rejects_a_non_uf2_file(self, tmp_path):
        path = tmp_path / "not.uf2"
        path.write_bytes(b"\x00" * 1024)
        with pytest.raises(VerifyError, match="bad magic"):
            uf2_payload(path)

    def test_rejects_a_truncated_file(self, tmp_path):
        path = tmp_path / "short.uf2"
        path.write_bytes(b"\x00" * 16)
        with pytest.raises(VerifyError, match="too small"):
            uf2_payload(path)


class TestFrozenModuleNames:
    def test_reads_tier1_from_the_real_manifest(self):
        names = frozen_module_names()
        assert "sdcard" in names and "i2c_guard" in names
        assert all(not name.endswith(".py") for name in names)

    def test_tier2_is_opt_in(self):
        assert "hardware_factory" not in frozen_module_names()
        assert "hardware_factory" in frozen_module_names(tier2=True)

    def test_survives_parentheses_inside_the_tier_comments(self, tmp_path):
        """A text-slicing extractor got this wrong; ast does not."""
        manifest = tmp_path / "freeze_manifest.py"
        manifest.write_text(
            'TIER1 = (\n    # boot-critical (see main.py Step 0) and cold\n    "boot_log.py",\n    "buzzer.py",\n)\n'
            'TIER2 = (\n    "event_logger.py",\n)\n'
        )
        assert frozen_module_names(manifest) == ["boot_log", "buzzer"]

    def test_missing_tier1_is_an_error(self, tmp_path):
        manifest = tmp_path / "freeze_manifest.py"
        manifest.write_text("SOMETHING_ELSE = ()\n")
        with pytest.raises(VerifyError, match="no TIER1"):
            frozen_module_names(manifest)


class TestVerify:
    def _image(self, names, extra=b""):
        return b"".join(name.encode() + b"\x00" for name in names) + b"fw_info\x00" + extra

    def test_passes_when_everything_expected_is_present(self):
        missing, leaked, _ = verify(self._image(["sdcard", "buzzer"]), expected=["sdcard", "buzzer"])
        assert missing == [] and leaked == []

    def test_reports_missing_modules(self):
        missing, leaked, _ = verify(self._image(["sdcard"]), expected=["sdcard", "buzzer"])
        assert missing == ["buzzer"] and leaked == []

    def test_missing_fw_info_is_reported(self):
        """No fw_info means the image cannot identify itself or gate OTA payloads."""
        missing, _leaked, _ = verify(b"sdcard\x00", expected=["sdcard"])
        assert "fw_info" in missing

    def test_reports_a_leaked_decision_module(self):
        image = self._image(["sdcard"]) + b"regulation_engine\x00"
        missing, leaked, _ = verify(image, expected=["sdcard"])
        assert leaked == ["regulation_engine"]
        assert missing == []

    def test_version_stamp_mismatch_is_a_failure(self):
        missing, _leaked, _ = verify(self._image(["sdcard"]), expected=["sdcard"], expect_version="pg-fw-2026.07-abc")
        assert any("pg-fw-2026.07-abc" in item for item in missing)

    def test_version_stamp_match_is_noted(self):
        image = self._image(["sdcard"], extra=b"pg-fw-2026.07-abc\x00")
        missing, _leaked, notes = verify(image, expected=["sdcard"], expect_version="pg-fw-2026.07-abc")
        assert missing == []
        assert any("pg-fw-2026.07-abc" in note for note in notes)


class TestCli:
    def _write(self, tmp_path, names, name="fw.uf2", extra=b""):
        payload = b"".join(n.encode() + b"\x00" for n in names) + b"fw_info\x00" + extra
        path = tmp_path / name
        path.write_bytes(_uf2(payload))
        return path

    def test_good_image_exits_zero(self, tmp_path, capsys):
        path = self._write(tmp_path, frozen_module_names())
        assert main([str(path)]) == 0
        assert "OK:" in capsys.readouterr().out

    def test_stock_image_exits_nonzero(self, tmp_path, capsys):
        """A firmware where the freeze silently did not take."""
        path = self._write(tmp_path, ["some_unrelated_symbol"])
        assert main([str(path)]) == 1
        assert "DO NOT FLASH" in capsys.readouterr().err

    def test_leaked_module_exits_nonzero(self, tmp_path, capsys):
        path = self._write(tmp_path, frozen_module_names() + ["updater"])
        assert main([str(path)]) == 1
        err = capsys.readouterr().err
        assert "never be frozen" in err
        assert "updater" in err

    def test_unreadable_image_exits_nonzero(self, tmp_path, capsys):
        assert main([str(tmp_path / "missing.uf2")]) == 1
        assert "error:" in capsys.readouterr().err

    def test_compare_stock_reports_a_delta(self, tmp_path, capsys):
        good = self._write(tmp_path, frozen_module_names(), name="new.uf2")
        stock = self._write(tmp_path, ["nothing"], name="stock.uf2")
        assert main([str(good), "--compare-stock", str(stock)]) == 0
        assert "vs stock" in capsys.readouterr().out
