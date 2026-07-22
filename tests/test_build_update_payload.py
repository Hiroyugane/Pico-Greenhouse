"""Tests for tools/build_update_payload.py helpers."""

import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
BUILD_SCRIPT = TOOLS_DIR / "build_update_payload.py"


@pytest.fixture(scope="module")
def build_module():
    spec = importlib.util.spec_from_file_location("build_update_payload", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestShortHashFromVersion:
    def test_extracts_trailing_hash_from_auto_version(self, build_module):
        assert build_module._short_hash_from_version("20260517T143052Z-c195be2") == "c195be2"

    def test_returns_string_unchanged_when_no_dash(self, build_module):
        assert build_module._short_hash_from_version("v1.2.3") == "v1.2.3"

    def test_takes_only_final_segment_when_multiple_dashes(self, build_module):
        assert build_module._short_hash_from_version("custom-tag-deadbee") == "deadbee"


class TestWriteBuildInfo:
    def test_writes_version_and_build_time(self, build_module, tmp_path):
        target = tmp_path / "lib" / "build_info.py"
        build_module._write_build_info(target, "20260517T120000Z-abc1234", "2026-05-17T12:00:00Z")

        spec = importlib.util.spec_from_file_location("build_info_test", target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        try:
            assert module.VERSION == "abc1234"
            assert module.BUILD_TIME == "2026-05-17T12:00:00Z"
        finally:
            sys.modules.pop("build_info_test", None)

    def test_creates_parent_directories(self, build_module, tmp_path):
        target = tmp_path / "deep" / "nested" / "build_info.py"
        build_module._write_build_info(target, "deadbee", "2026-05-17T00:00:00Z")
        assert target.exists()

    def test_short_version_string_passed_through(self, build_module, tmp_path):
        # If --version is a literal like "v1.0" (no dash), VERSION uses it as-is.
        target = tmp_path / "build_info.py"
        build_module._write_build_info(target, "v1.0", "2026-05-17T00:00:00Z")
        contents = target.read_text()
        assert 'VERSION = "v1.0"' in contents
        assert 'BUILD_TIME = "2026-05-17T00:00:00Z"' in contents


def _mpy(path: Path, abi: int, body: bytes = b"\x00\x00") -> Path:
    """Write a stub .mpy file: magic 'M', ABI byte, then anything."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes([0x4D, abi]) + body)
    return path


class TestMpyAbiOf:
    def test_reads_the_abi_byte(self, build_module, tmp_path):
        assert build_module._mpy_abi_of(_mpy(tmp_path / "a.mpy", 6)) == 6

    def test_rejects_a_non_mpy_file(self, build_module, tmp_path):
        path = tmp_path / "not.mpy"
        path.write_bytes(b"# python source\n")
        with pytest.raises(build_module.PayloadError, match="bad magic"):
            build_module._mpy_abi_of(path)

    def test_rejects_a_truncated_file(self, build_module, tmp_path):
        path = tmp_path / "short.mpy"
        path.write_bytes(b"M")
        with pytest.raises(build_module.PayloadError):
            build_module._mpy_abi_of(path)


class TestDetectMpyAbi:
    def test_none_for_a_raw_python_payload(self, build_module, tmp_path):
        source = tmp_path / "main.py"
        source.write_text("print('hi')\n")
        assert build_module._detect_mpy_abi([("main.py", source)]) is None

    def test_returns_the_shared_abi(self, build_module, tmp_path):
        sources = [
            ("config.mpy", _mpy(tmp_path / "config.mpy", 6)),
            ("lib/relay.mpy", _mpy(tmp_path / "lib" / "relay.mpy", 6)),
        ]
        assert build_module._detect_mpy_abi(sources) == 6

    def test_ignores_raw_files_mixed_in(self, build_module, tmp_path):
        """--compiled payloads still ship a raw build_info.py alongside the .mpy set."""
        raw = tmp_path / "lib" / "build_info.py"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text("VERSION = 'x'\n")
        sources = [("config.mpy", _mpy(tmp_path / "config.mpy", 6)), ("lib/build_info.py", raw)]
        assert build_module._detect_mpy_abi(sources) == 6

    def test_refuses_to_stamp_a_mixed_abi_payload(self, build_module, tmp_path):
        """Two mpy-cross binaries built this; any single stamp would be a lie."""
        sources = [
            ("config.mpy", _mpy(tmp_path / "config.mpy", 6)),
            ("lib/relay.mpy", _mpy(tmp_path / "lib" / "relay.mpy", 5)),
        ]
        with pytest.raises(build_module.PayloadError, match="mixes .mpy ABI"):
            build_module._detect_mpy_abi(sources)


class TestManifestAbiField:
    def test_stamp_written_when_known(self, build_module, tmp_path):
        import json

        path = build_module._write_manifest(tmp_path, "v1", [{"path": "config.mpy", "sha256": "x", "bytes": 1}], 6)
        assert json.loads(path.read_text())["mpy_abi"] == 6

    def test_key_absent_for_raw_payloads(self, build_module, tmp_path):
        """No stamp means the device guard skips — raw .py imports under any ABI."""
        import json

        path = build_module._write_manifest(tmp_path, "v1", [{"path": "main.py", "sha256": "x", "bytes": 1}])
        assert "mpy_abi" not in json.loads(path.read_text())


class TestCliAbiStamping:
    def _build_tree(self, tmp_path, abi=6):
        build_dir = tmp_path / "build"
        (build_dir / "lib").mkdir(parents=True)
        (build_dir / "main.py").write_text("print('hi')\n")
        _mpy(build_dir / "config.mpy", abi)
        _mpy(build_dir / "lib" / "relay.mpy", abi)
        return build_dir

    def test_compiled_payload_is_stamped_automatically(self, build_module, tmp_path, monkeypatch, capsys):
        import json

        monkeypatch.setattr(build_module, "PROJECT_ROOT", tmp_path)
        build_dir = self._build_tree(tmp_path, abi=6)
        out_dir = tmp_path / "payload"
        assert (
            build_module.main(
                ["--compiled", "--build-dir", str(build_dir), "--out", str(out_dir), "--version", "test-deadbee"]
            )
            == 0
        )
        assert json.loads((out_dir / "manifest.json").read_text())["mpy_abi"] == 6
        assert "mpy_abi    : 6" in capsys.readouterr().out

    def test_no_mpy_abi_flag_omits_the_stamp(self, build_module, tmp_path, monkeypatch):
        import json

        monkeypatch.setattr(build_module, "PROJECT_ROOT", tmp_path)
        build_dir = self._build_tree(tmp_path, abi=6)
        out_dir = tmp_path / "payload"
        assert (
            build_module.main(
                [
                    "--compiled",
                    "--build-dir",
                    str(build_dir),
                    "--out",
                    str(out_dir),
                    "--version",
                    "test-deadbee",
                    "--no-mpy-abi",
                ]
            )
            == 0
        )
        assert "mpy_abi" not in json.loads((out_dir / "manifest.json").read_text())

    def test_mixed_abi_tree_exits_nonzero(self, build_module, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(build_module, "PROJECT_ROOT", tmp_path)
        build_dir = self._build_tree(tmp_path, abi=6)
        _mpy(build_dir / "lib" / "relay.mpy", 5)
        out_dir = tmp_path / "payload"
        assert (
            build_module.main(
                ["--compiled", "--build-dir", str(build_dir), "--out", str(out_dir), "--version", "test-deadbee"]
            )
            == 1
        )
        assert "mixes .mpy ABI" in capsys.readouterr().err
