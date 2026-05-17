"""Tests for tools/build_update_payload.py helpers."""

import importlib.util
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
BUILD_SCRIPT = TOOLS_DIR / "build_update_payload.py"


@pytest.fixture(scope="module")
def build_module():
    spec = importlib.util.spec_from_file_location(
        "build_update_payload", BUILD_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestShortHashFromVersion:
    def test_extracts_trailing_hash_from_auto_version(self, build_module):
        assert (
            build_module._short_hash_from_version("20260517T143052Z-c195be2")
            == "c195be2"
        )

    def test_returns_string_unchanged_when_no_dash(self, build_module):
        assert build_module._short_hash_from_version("v1.2.3") == "v1.2.3"

    def test_takes_only_final_segment_when_multiple_dashes(self, build_module):
        assert (
            build_module._short_hash_from_version("custom-tag-deadbee") == "deadbee"
        )


class TestWriteBuildInfo:
    def test_writes_version_and_build_time(self, build_module, tmp_path):
        target = tmp_path / "lib" / "build_info.py"
        build_module._write_build_info(
            target, "20260517T120000Z-abc1234", "2026-05-17T12:00:00Z"
        )

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
